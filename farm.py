from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import get_bool, get_int
from database import connect
from vip import get_vip_period, get_vip_status

MAX_FARM_LEVEL = 5


def _now():
    return datetime.utcnow()


def _base_level_data(level: int):
    level = max(1, min(MAX_FARM_LEVEL, int(level)))
    return {
        "production": get_int(f"farm.production.{level}", 10 + (level - 1) * 5),
        "capacity": get_int(f"farm.capacity.{level}", {1: 15, 2: 25, 3: 35, 4: 50, 5: 70}[level]),
        "upgrade_cost": (
            None if level >= MAX_FARM_LEVEL
            else get_int(f"farm.upgrade.{level}", {1: 75, 2: 150, 3: 275, 4: 450}[level])
        ),
    }


def _current_level_data(level: int, user_id: int):
    base = _base_level_data(level)
    vip = get_vip_status(user_id)
    prod = int(base["production"])
    cap = int(base["capacity"])
    if vip["active"]:
        prod = round(prod * (1 + get_int("vip.farm_production_bonus_pct", 20) / 100))
        cap = round(cap * (1 + get_int("vip.farm_capacity_bonus_pct", 25) / 100))
    return {
        **base,
        "production": prod,
        "capacity": cap,
        "base_production": int(base["production"]),
        "base_capacity": int(base["capacity"]),
        "vip_active": bool(vip["active"]),
    }


def init_farm_db():
    with connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS honey_farms (
                user_id INTEGER PRIMARY KEY,
                level INTEGER NOT NULL DEFAULT 1,
                stored REAL NOT NULL DEFAULT 0,
                last_update TEXT NOT NULL
            )
        """)


def _ensure_farm(con, user_id: int):
    row = con.execute("SELECT * FROM honey_farms WHERE user_id=?", (user_id,)).fetchone()
    if row:
        return row
    now = _now().isoformat(timespec="seconds")
    con.execute(
        "INSERT INTO honey_farms(user_id, level, stored, last_update) VALUES (?, 1, 0, ?)",
        (user_id, now),
    )
    return con.execute("SELECT * FROM honey_farms WHERE user_id=?", (user_id,)).fetchone()


def _seconds_overlap(start: datetime, end: datetime, a: datetime, b: datetime) -> float:
    left = max(start, a)
    right = min(end, b)
    return max(0.0, (right - left).total_seconds())


def _sync_farm(con, row):
    level = int(row["level"])
    user_id = int(row["user_id"])
    base = _base_level_data(level)
    now = _now()
    try:
        last_update = datetime.fromisoformat(row["last_update"])
    except Exception:
        last_update = now
    if last_update > now:
        last_update = now

    elapsed = max(0.0, (now - last_update).total_seconds())
    vip_seconds = 0.0
    period = get_vip_period(user_id) if get_bool("vip.enabled", True) else None
    if period:
        # vip.py использует часы UTC+3, а ферма исторически UTC.
        # Разница постоянная, поэтому переводим период на UTC.
        from datetime import timedelta
        vip_start = period["started_at"] - timedelta(hours=3)
        vip_end = period["expires_at"] - timedelta(hours=3)
        vip_seconds = _seconds_overlap(last_update, now, vip_start, vip_end)

    normal_seconds = max(0.0, elapsed - vip_seconds)
    base_rate = float(base["production"]) / 86400.0
    vip_rate = base_rate * (1 + get_int("vip.farm_production_bonus_pct", 20) / 100.0)
    produced = normal_seconds * base_rate + vip_seconds * vip_rate

    current = _current_level_data(level, user_id)
    capacity = float(current["capacity"])
    old_stored = float(row["stored"])
    # Если VIP закончился и запас выше обычной вместимости, ничего не теряем:
    # просто не производим новое, пока пользователь не соберёт излишек.
    if old_stored >= capacity:
        stored = old_stored
    else:
        stored = min(capacity, old_stored + produced)

    con.execute(
        "UPDATE honey_farms SET stored=?, last_update=? WHERE user_id=?",
        (stored, now.isoformat(timespec="seconds"), user_id),
    )
    result = dict(row)
    result["stored"] = stored
    result["last_update"] = now.isoformat(timespec="seconds")
    return result


def _decorate(farm: dict):
    level = int(farm["level"])
    data = _current_level_data(level, int(farm["user_id"]))
    result = dict(farm)
    result.update({**data, "max_level": MAX_FARM_LEVEL})
    return result


def get_farm(user_id: int):
    with connect() as con:
        row = _ensure_farm(con, user_id)
        return _decorate(_sync_farm(con, row))


def sync_all_farms():
    with connect() as con:
        rows = con.execute("SELECT * FROM honey_farms").fetchall()
        for row in rows:
            _sync_farm(con, row)


def collect_farm(user_id: int):
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _ensure_farm(con, user_id)
        farm = _sync_farm(con, row)
        amount = int(float(farm["stored"]))
        if amount <= 0:
            con.commit()
            return {"status": "empty", "farm": _decorate(farm)}

        remaining_fraction = max(0.0, float(farm["stored"]) - amount)
        con.execute("UPDATE honey_farms SET stored=? WHERE user_id=?", (remaining_fraction, user_id))
        con.execute("""
            INSERT INTO honey_wallets(user_id, balance, total_earned, giveaways_claimed, biggest_claim)
            VALUES (?, ?, ?, 0, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = balance + excluded.balance,
                total_earned = total_earned + excluded.total_earned
        """, (user_id, amount, amount))
        wallet = con.execute("SELECT balance FROM honey_wallets WHERE user_id=?", (user_id,)).fetchone()
        con.commit()

        farm["stored"] = remaining_fraction
        return {
            "status": "ok",
            "amount": amount,
            "balance": int(wallet["balance"]),
            "farm": _decorate(farm),
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def upgrade_farm(user_id: int):
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _ensure_farm(con, user_id)
        farm = _sync_farm(con, row)
        level = int(farm["level"])
        if level >= MAX_FARM_LEVEL:
            con.commit()
            return {"status": "max", "farm": _decorate(farm)}

        cost = int(_base_level_data(level)["upgrade_cost"])
        wallet = con.execute("SELECT balance FROM honey_wallets WHERE user_id=?", (user_id,)).fetchone()
        balance = int(wallet["balance"]) if wallet else 0
        if balance < cost:
            con.commit()
            return {
                "status": "insufficient",
                "need": cost - balance,
                "balance": balance,
                "cost": cost,
                "farm": _decorate(farm),
            }

        new_level = level + 1
        con.execute("UPDATE honey_wallets SET balance=balance-? WHERE user_id=?", (cost, user_id))
        con.execute("UPDATE honey_farms SET level=? WHERE user_id=?", (new_level, user_id))
        con.commit()
        farm["level"] = new_level
        return {
            "status": "ok",
            "cost": cost,
            "balance": balance - cost,
            "farm": _decorate(farm),
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def farm_keyboard(user_id: int, farm: dict):
    buttons = [[InlineKeyboardButton(text="🍯 Собрать мёдик", callback_data=f"farm:collect:{user_id}")]]
    if int(farm["level"]) < MAX_FARM_LEVEL:
        buttons.append([
            InlineKeyboardButton(
                text=f"⬆️ Улучшить за {farm['upgrade_cost']} 🍯",
                callback_data=f"farm:upgrade:{user_id}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
