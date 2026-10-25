from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import connect


# Уровень: производство в сутки, вместимость сот, цена перехода на следующий уровень.
FARM_LEVELS = {
    1: {"production": 10, "capacity": 15, "upgrade_cost": 200},
    2: {"production": 15, "capacity": 25, "upgrade_cost": 450},
    3: {"production": 20, "capacity": 35, "upgrade_cost": 800},
    4: {"production": 25, "capacity": 50, "upgrade_cost": 1400},
    5: {"production": 30, "capacity": 70, "upgrade_cost": None},
}
MAX_FARM_LEVEL = max(FARM_LEVELS)


def _now():
    return datetime.utcnow()


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
    row = con.execute(
        "SELECT * FROM honey_farms WHERE user_id=?",
        (user_id,),
    ).fetchone()

    if row:
        return row

    now = _now().isoformat(timespec="seconds")
    con.execute("""
        INSERT INTO honey_farms(user_id, level, stored, last_update)
        VALUES (?, 1, 0, ?)
    """, (user_id, now))

    return con.execute(
        "SELECT * FROM honey_farms WHERE user_id=?",
        (user_id,),
    ).fetchone()


def _sync_farm(con, row):
    level = int(row["level"])
    data = FARM_LEVELS[level]
    now = _now()

    try:
        last_update = datetime.fromisoformat(row["last_update"])
    except Exception:
        last_update = now

    elapsed = max(0.0, (now - last_update).total_seconds())
    produced = elapsed * (float(data["production"]) / 86400.0)
    stored = min(float(data["capacity"]), float(row["stored"]) + produced)

    con.execute("""
        UPDATE honey_farms
        SET stored=?, last_update=?
        WHERE user_id=?
    """, (
        stored,
        now.isoformat(timespec="seconds"),
        row["user_id"],
    ))

    result = dict(row)
    result["stored"] = stored
    result["last_update"] = now.isoformat(timespec="seconds")
    return result


def _decorate(farm: dict):
    level = int(farm["level"])
    data = FARM_LEVELS[level]
    result = dict(farm)
    result.update({
        "production": data["production"],
        "capacity": data["capacity"],
        "upgrade_cost": data["upgrade_cost"],
        "max_level": MAX_FARM_LEVEL,
    })
    return result


def get_farm(user_id: int):
    with connect() as con:
        row = _ensure_farm(con, user_id)
        farm = _sync_farm(con, row)
        return _decorate(farm)


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
        con.execute(
            "UPDATE honey_farms SET stored=? WHERE user_id=?",
            (remaining_fraction, user_id),
        )

        con.execute("""
            INSERT INTO honey_wallets(
                user_id, balance, total_earned, giveaways_claimed, biggest_claim
            )
            VALUES (?, ?, ?, 0, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = balance + excluded.balance,
                total_earned = total_earned + excluded.total_earned
        """, (user_id, amount, amount))

        wallet = con.execute(
            "SELECT balance FROM honey_wallets WHERE user_id=?",
            (user_id,),
        ).fetchone()

        con.commit()

        updated = dict(farm)
        updated["stored"] = remaining_fraction
        return {
            "status": "ok",
            "amount": amount,
            "balance": int(wallet["balance"]),
            "farm": _decorate(updated),
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

        cost = int(FARM_LEVELS[level]["upgrade_cost"])
        wallet = con.execute(
            "SELECT balance FROM honey_wallets WHERE user_id=?",
            (user_id,),
        ).fetchone()
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
        con.execute(
            "UPDATE honey_wallets SET balance=balance-? WHERE user_id=?",
            (cost, user_id),
        )
        con.execute(
            "UPDATE honey_farms SET level=? WHERE user_id=?",
            (new_level, user_id),
        )

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
    buttons = [[
        InlineKeyboardButton(
            text="🍯 Собрать мёдик",
            callback_data=f"farm:collect:{user_id}",
        )
    ]]

    if int(farm["level"]) < MAX_FARM_LEVEL:
        buttons.append([
            InlineKeyboardButton(
                text=f"⬆️ Улучшить за {farm['upgrade_cost']} 🍯",
                callback_data=f"farm:upgrade:{user_id}",
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
