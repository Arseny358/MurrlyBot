import math
import random
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import bot_now, get_bool, get_float, get_int
from database import connect
from vip import get_vip_period, get_vip_status

MAX_FARM_LEVEL = 12

FARM_LEVELS = {
    1: ("🪹", "Маленький улей"),
    2: ("🐝", "Улей"),
    3: ("🌼", "Пасека"),
    4: ("🌻", "Большая пасека"),
    5: ("🏡", "Медовая ферма"),
    6: ("🌾", "Медовые угодья"),
    7: ("🏘", "Пчелиная деревня"),
    8: ("🏭", "Медовый комбинат"),
    9: ("🏰", "Королевская пасека"),
    10: ("👑", "Империя мёда"),
    11: ("✨", "Золотой улей"),
    12: ("🌟", "Легендарная пасека"),
}

DEFAULT_PRODUCTION = {1:10, 2:15, 3:20, 4:25, 5:30, 6:38, 7:47, 8:58, 9:72, 10:90, 11:112, 12:140}
DEFAULT_CAPACITY = {1:15, 2:25, 3:35, 4:50, 5:70, 6:95, 7:125, 8:160, 9:210, 10:280, 11:360, 12:460}
DEFAULT_UPGRADE = {1:75, 2:150, 3:275, 4:450, 5:700, 6:1000, 7:1450, 8:2000, 9:2800, 10:3800, 11:5000}

IMPROVEMENTS = {
    "flowers": {
        "emoji": "🌻", "name": "Цветочные поля", "max_level": 5,
        "effect": "production",
        "base_cost_key": "farm.improvement.flowers.base_cost",
        "growth_key": "farm.improvement.flowers.growth",
        "bonus_key": "farm.improvement.flowers.bonus_pct",
        "default_base": 120, "default_growth": 1.65, "default_bonus": 5,
    },
    "combs": {
        "emoji": "🍯", "name": "Большие соты", "max_level": 5,
        "effect": "capacity",
        "base_cost_key": "farm.improvement.combs.base_cost",
        "growth_key": "farm.improvement.combs.growth",
        "bonus_key": "farm.improvement.combs.bonus_pct",
        "default_base": 140, "default_growth": 1.65, "default_bonus": 6,
    },
    "beekeeper": {
        "emoji": "🧑‍🌾", "name": "Пчеловод", "max_level": 5,
        "effect": "production",
        "base_cost_key": "farm.improvement.beekeeper.base_cost",
        "growth_key": "farm.improvement.beekeeper.growth",
        "bonus_key": "farm.improvement.beekeeper.bonus_pct",
        "default_base": 180, "default_growth": 1.70, "default_bonus": 4,
    },
    "queen": {
        "emoji": "👑", "name": "Матка", "max_level": 3,
        "effect": "production",
        "base_cost_key": "farm.improvement.queen.base_cost",
        "growth_key": "farm.improvement.queen.growth",
        "bonus_key": "farm.improvement.queen.bonus_pct",
        "default_base": 350, "default_growth": 2.00, "default_bonus": 8,
    },
}

EVENTS = {
    "rare_flowers": {"emoji": "🌸", "name": "Редкие цветы", "production_multiplier": 1.20, "description": "+20% производства"},
    "rich_swarm": {"emoji": "🐝", "name": "Богатый рой", "production_multiplier": 1.15, "description": "+15% производства"},
    "sunny": {"emoji": "☀️", "name": "Солнечный день", "production_multiplier": 1.10, "description": "+10% производства"},
    "rain": {"emoji": "🌧", "name": "Дождь", "production_multiplier": 0.90, "description": "-10% производства"},
}


def _now():
    return datetime.utcnow()


def _base_level_data(level: int):
    level = max(1, min(MAX_FARM_LEVEL, int(level)))
    emoji, name = FARM_LEVELS[level]
    return {
        "level": level,
        "emoji": emoji,
        "stage_name": name,
        "production": get_int(f"farm.production.{level}", DEFAULT_PRODUCTION[level]),
        "capacity": get_int(f"farm.capacity.{level}", DEFAULT_CAPACITY[level]),
        "upgrade_cost": None if level >= MAX_FARM_LEVEL else get_int(
            f"farm.upgrade.{level}", DEFAULT_UPGRADE[level]
        ),
    }


def _improvement_levels(con, user_id: int):
    rows = con.execute(
        "SELECT improvement_key, level FROM farm_improvements WHERE user_id=?",
        (int(user_id),),
    ).fetchall()
    values = {key: 0 for key in IMPROVEMENTS}
    for row in rows:
        if row["improvement_key"] in values:
            values[row["improvement_key"]] = int(row["level"])
    return values


def _improvement_bonus(levels: dict):
    production_pct = 0.0
    capacity_pct = 0.0
    for key, level in levels.items():
        meta = IMPROVEMENTS[key]
        bonus = get_float(meta["bonus_key"], meta["default_bonus"]) * int(level)
        if meta["effect"] == "production":
            production_pct += bonus
        elif meta["effect"] == "capacity":
            capacity_pct += bonus
    return production_pct, capacity_pct


def improvement_cost(key: str, current_level: int):
    meta = IMPROVEMENTS[key]
    if current_level >= meta["max_level"]:
        return None
    base = max(0, get_int(meta["base_cost_key"], meta["default_base"]))
    growth = max(1.0, get_float(meta["growth_key"], meta["default_growth"]))
    return int(round(base * (growth ** current_level)))


def init_farm_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS honey_farms (
            user_id INTEGER PRIMARY KEY,
            level INTEGER NOT NULL DEFAULT 1,
            stored REAL NOT NULL DEFAULT 0,
            last_update TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS farm_improvements (
            user_id INTEGER NOT NULL,
            improvement_key TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, improvement_key)
        );

        CREATE TABLE IF NOT EXISTS farm_boosts (
            user_id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS farm_events (
            user_id INTEGER PRIMARY KEY,
            event_key TEXT,
            started_at TEXT,
            expires_at TEXT,
            last_roll_at TEXT
        );

        CREATE TABLE IF NOT EXISTS golden_honey_wallets (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            total_found INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS golden_honey_rolls (
            user_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            attempted_at TEXT NOT NULL,
            found INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, day)
        );
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


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _active_period(con, table: str, user_id: int):
    row = con.execute(
        f"SELECT started_at, expires_at FROM {table} WHERE user_id=?",
        (int(user_id),),
    ).fetchone()
    if not row:
        return None
    start = _parse_dt(row["started_at"])
    end = _parse_dt(row["expires_at"])
    if not start or not end:
        return None
    return start, end


def _event_period(con, user_id: int):
    row = con.execute(
        "SELECT event_key, started_at, expires_at FROM farm_events WHERE user_id=?",
        (int(user_id),),
    ).fetchone()
    if not row or row["event_key"] not in EVENTS:
        return None
    start = _parse_dt(row["started_at"])
    end = _parse_dt(row["expires_at"])
    if not start or not end:
        return None
    return row["event_key"], start, end


def _vip_period_utc(user_id: int):
    period = get_vip_period(user_id) if get_bool("vip.enabled", True) else None
    if not period:
        return None
    # vip.py хранит время по UTC+3, историческая ферма работает в UTC.
    return (
        period["started_at"] - timedelta(hours=3),
        period["expires_at"] - timedelta(hours=3),
    )


def _is_in_period(mid: datetime, period):
    return bool(period and period[0] <= mid < period[1])


def _sync_farm(con, row):
    level = max(1, min(MAX_FARM_LEVEL, int(row["level"])))
    user_id = int(row["user_id"])
    base = _base_level_data(level)
    now = _now()

    last_update = _parse_dt(row["last_update"]) or now
    if last_update > now:
        last_update = now

    levels = _improvement_levels(con, user_id)
    imp_prod_pct, imp_cap_pct = _improvement_bonus(levels)

    base_daily = float(base["production"]) * (1 + imp_prod_pct / 100.0)

    vip_period = _vip_period_utc(user_id)
    boost_period = _active_period(con, "farm_boosts", user_id)
    event_period = _event_period(con, user_id)

    boundaries = {last_update, now}
    for period in [vip_period, boost_period]:
        if period:
            for point in period:
                if last_update < point < now:
                    boundaries.add(point)
    if event_period:
        for point in event_period[1:]:
            if last_update < point < now:
                boundaries.add(point)

    points = sorted(boundaries)
    produced = 0.0
    vip_bonus = get_float("vip.farm_production_bonus_pct", 20)
    boost_bonus = get_float("farm.boost.production_bonus_pct", 20)

    for a, b in zip(points, points[1:]):
        if b <= a:
            continue
        mid = a + (b - a) / 2
        multiplier = 1.0
        if _is_in_period(mid, vip_period):
            multiplier *= 1 + vip_bonus / 100.0
        if _is_in_period(mid, boost_period):
            multiplier *= 1 + boost_bonus / 100.0
        if event_period and event_period[1] <= mid < event_period[2]:
            multiplier *= EVENTS[event_period[0]]["production_multiplier"]
        produced += (b - a).total_seconds() * (base_daily * multiplier / 86400.0)

    vip_active = bool(vip_period and vip_period[0] <= now < vip_period[1])
    capacity = float(base["capacity"]) * (1 + imp_cap_pct / 100.0)
    if vip_active:
        capacity *= 1 + get_float("vip.farm_capacity_bonus_pct", 25) / 100.0
    capacity = max(1, int(round(capacity)))

    old_stored = float(row["stored"])
    stored = old_stored if old_stored >= capacity else min(float(capacity), old_stored + produced)

    con.execute(
        "UPDATE honey_farms SET stored=?, last_update=? WHERE user_id=?",
        (stored, now.isoformat(timespec="seconds"), user_id),
    )
    result = dict(row)
    result["level"] = level
    result["stored"] = stored
    result["last_update"] = now.isoformat(timespec="seconds")
    return result


def _active_event_view(con, user_id: int, now=None):
    now = now or _now()
    row = con.execute(
        "SELECT event_key, started_at, expires_at, last_roll_at FROM farm_events WHERE user_id=?",
        (int(user_id),),
    ).fetchone()
    if not row or row["event_key"] not in EVENTS:
        return None
    start = _parse_dt(row["started_at"])
    end = _parse_dt(row["expires_at"])
    if not start or not end or end <= now:
        return None
    meta = EVENTS[row["event_key"]]
    return {
        "key": row["event_key"],
        **meta,
        "started_at": start.isoformat(timespec="seconds"),
        "expires_at": end.isoformat(timespec="seconds"),
        "remaining_seconds": max(0, int((end - now).total_seconds())),
    }


def _maybe_roll_event(con, user_id: int):
    now = _now()
    active = _active_event_view(con, user_id, now)
    if active:
        return active

    row = con.execute(
        "SELECT last_roll_at FROM farm_events WHERE user_id=?",
        (int(user_id),),
    ).fetchone()
    last_roll = _parse_dt(row["last_roll_at"]) if row else None
    cooldown = timedelta(hours=max(1, get_float("farm.event.cooldown_hours", 6)))
    if last_roll and now - last_roll < cooldown:
        return None

    chance = max(0.0, min(100.0, get_float("farm.event.chance_pct", 12)))
    event_key = random.choice(list(EVENTS)) if random.random() * 100 < chance else None
    duration = timedelta(minutes=max(1, get_int("farm.event.duration_minutes", 120)))
    start_text = now.isoformat(timespec="seconds")
    end_text = (now + duration).isoformat(timespec="seconds") if event_key else None

    con.execute("""
        INSERT INTO farm_events(user_id, event_key, started_at, expires_at, last_roll_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            event_key=excluded.event_key,
            started_at=excluded.started_at,
            expires_at=excluded.expires_at,
            last_roll_at=excluded.last_roll_at
    """, (int(user_id), event_key, start_text if event_key else None, end_text, start_text))

    return _active_event_view(con, user_id, now)


def _decorate(con, farm: dict):
    user_id = int(farm["user_id"])
    level = int(farm["level"])
    base = _base_level_data(level)
    levels = _improvement_levels(con, user_id)
    imp_prod_pct, imp_cap_pct = _improvement_bonus(levels)
    vip = get_vip_status(user_id)

    production = float(base["production"]) * (1 + imp_prod_pct / 100.0)
    capacity = float(base["capacity"]) * (1 + imp_cap_pct / 100.0)
    if vip["active"]:
        production *= 1 + get_float("vip.farm_production_bonus_pct", 20) / 100.0
        capacity *= 1 + get_float("vip.farm_capacity_bonus_pct", 25) / 100.0

    now = _now()
    boost = _active_period(con, "farm_boosts", user_id)
    boost_active = bool(boost and boost[0] <= now < boost[1])
    if boost_active:
        production *= 1 + get_float("farm.boost.production_bonus_pct", 20) / 100.0

    event = _active_event_view(con, user_id, now)
    if event:
        production *= float(event["production_multiplier"])

    return {
        **farm,
        **base,
        "production": max(1, int(round(production))),
        "capacity": max(1, int(round(capacity))),
        "base_production": int(base["production"]),
        "base_capacity": int(base["capacity"]),
        "vip_active": bool(vip["active"]),
        "max_level": MAX_FARM_LEVEL,
        "improvement_production_pct": round(imp_prod_pct, 2),
        "improvement_capacity_pct": round(imp_cap_pct, 2),
        "boost_active": boost_active,
        "event": event,
    }


def get_farm(user_id: int):
    init_farm_db()
    with connect() as con:
        row = _ensure_farm(con, user_id)
        synced = _sync_farm(con, row)
        _maybe_roll_event(con, user_id)
        return _decorate(con, synced)


def sync_all_farms():
    init_farm_db()
    with connect() as con:
        rows = con.execute("SELECT * FROM honey_farms").fetchall()
        for row in rows:
            _sync_farm(con, row)


def get_golden_wallet(user_id: int):
    init_farm_db()
    with connect() as con:
        row = con.execute(
            "SELECT balance, total_found FROM golden_honey_wallets WHERE user_id=?",
            (int(user_id),),
        ).fetchone()
    if not row:
        return {"balance": 0, "total_found": 0}
    return dict(row)


def _roll_golden_honey(user_id: int, collected: int):
    minimum = max(1, get_int("farm.golden_min_collect", 5))
    if collected < minimum:
        return {"rolled": False, "found": False}

    day = bot_now().date().isoformat()
    init_farm_db()
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute(
            "SELECT found FROM golden_honey_rolls WHERE user_id=? AND day=?",
            (int(user_id), day),
        ).fetchone()
        if existing:
            con.rollback()
            return {"rolled": False, "found": bool(existing["found"])}

        chance = get_float("farm.golden_chance_pct", 3)
        if get_vip_status(user_id)["active"]:
            chance += get_float("farm.golden_vip_bonus_pct", 1)
        chance = max(0, min(100, chance))
        found = random.random() * 100 < chance
        now = bot_now().isoformat(timespec="seconds")
        con.execute(
            "INSERT INTO golden_honey_rolls(user_id, day, attempted_at, found) VALUES (?, ?, ?, ?)",
            (int(user_id), day, now, 1 if found else 0),
        )
        if found:
            con.execute("""
                INSERT INTO golden_honey_wallets(user_id, balance, total_found)
                VALUES (?, 1, 1)
                ON CONFLICT(user_id) DO UPDATE SET
                    balance=balance+1,
                    total_found=total_found+1
            """, (int(user_id),))
        con.commit()
        return {"rolled": True, "found": found}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def collect_farm(user_id: int):
    init_farm_db()
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _ensure_farm(con, user_id)
        farm = _sync_farm(con, row)
        amount = int(float(farm["stored"]))
        if amount <= 0:
            result_farm = _decorate(con, farm)
            con.commit()
            return {"status": "empty", "farm": result_farm}

        remaining_fraction = max(0.0, float(farm["stored"]) - amount)
        con.execute("UPDATE honey_farms SET stored=? WHERE user_id=?", (remaining_fraction, user_id))
        con.execute("""
            INSERT INTO honey_wallets(user_id, balance, total_earned, giveaways_claimed, biggest_claim)
            VALUES (?, ?, ?, 0, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                balance=balance+excluded.balance,
                total_earned=total_earned+excluded.total_earned
        """, (user_id, amount, amount))
        wallet = con.execute("SELECT balance FROM honey_wallets WHERE user_id=?", (user_id,)).fetchone()
        farm["stored"] = remaining_fraction
        result_farm = _decorate(con, farm)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    try:
        from daily_tasks import record_task_progress
        record_task_progress(user_id, "collect", amount)
    except Exception:
        pass

    golden = _roll_golden_honey(user_id, amount)
    return {
        "status": "ok",
        "amount": amount,
        "balance": int(wallet["balance"]),
        "farm": result_farm,
        "golden": golden,
    }


def upgrade_farm(user_id: int):
    init_farm_db()
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _ensure_farm(con, user_id)
        farm = _sync_farm(con, row)
        level = int(farm["level"])
        if level >= MAX_FARM_LEVEL:
            result_farm = _decorate(con, farm)
            con.commit()
            return {"status": "max", "farm": result_farm}

        cost = int(_base_level_data(level)["upgrade_cost"])
        wallet = con.execute("SELECT balance FROM honey_wallets WHERE user_id=?", (user_id,)).fetchone()
        balance = int(wallet["balance"]) if wallet else 0
        if balance < cost:
            result_farm = _decorate(con, farm)
            con.commit()
            return {
                "status": "insufficient",
                "need": cost - balance,
                "balance": balance,
                "cost": cost,
                "farm": result_farm,
            }

        new_level = level + 1
        con.execute("UPDATE honey_wallets SET balance=balance-? WHERE user_id=?", (cost, user_id))
        con.execute("UPDATE honey_farms SET level=? WHERE user_id=?", (new_level, user_id))
        farm["level"] = new_level
        result_farm = _decorate(con, farm)
        con.commit()
        return {
            "status": "ok",
            "cost": cost,
            "balance": balance - cost,
            "farm": result_farm,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def get_improvements(user_id: int):
    init_farm_db()
    with connect() as con:
        levels = _improvement_levels(con, user_id)

    result = []
    for key, meta in IMPROVEMENTS.items():
        level = levels[key]
        bonus_per_level = get_float(meta["bonus_key"], meta["default_bonus"])
        result.append({
            "key": key,
            "emoji": meta["emoji"],
            "name": meta["name"],
            "level": level,
            "max_level": meta["max_level"],
            "effect": meta["effect"],
            "bonus_per_level": bonus_per_level,
            "total_bonus_pct": round(level * bonus_per_level, 2),
            "upgrade_cost": improvement_cost(key, level),
        })
    return result


def buy_improvement(user_id: int, key: str):
    if key not in IMPROVEMENTS:
        return {"status": "missing"}

    init_farm_db()
    meta = IMPROVEMENTS[key]
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _ensure_farm(con, user_id)
        _sync_farm(con, row)

        current_row = con.execute(
            "SELECT level FROM farm_improvements WHERE user_id=? AND improvement_key=?",
            (int(user_id), key),
        ).fetchone()
        level = int(current_row["level"]) if current_row else 0
        if level >= meta["max_level"]:
            con.commit()
            return {"status": "max"}

        cost = improvement_cost(key, level)
        wallet = con.execute("SELECT balance FROM honey_wallets WHERE user_id=?", (int(user_id),)).fetchone()
        balance = int(wallet["balance"]) if wallet else 0
        if balance < cost:
            con.commit()
            return {"status": "insufficient", "need": cost - balance, "cost": cost}

        new_level = level + 1
        con.execute("UPDATE honey_wallets SET balance=balance-? WHERE user_id=?", (cost, int(user_id)))
        con.execute("""
            INSERT INTO farm_improvements(user_id, improvement_key, level, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, improvement_key) DO UPDATE SET
                level=excluded.level,
                updated_at=excluded.updated_at
        """, (int(user_id), key, new_level, _now().isoformat(timespec="seconds")))
        con.commit()
        return {
            "status": "ok",
            "key": key,
            "level": new_level,
            "cost": cost,
            "balance": balance - cost,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def activate_boost(user_id: int):
    init_farm_db()
    # Фиксируем накопление до начала нового буста.
    get_farm(user_id)

    now = _now()
    with connect() as con:
        row = con.execute(
            "SELECT expires_at FROM farm_boosts WHERE user_id=?",
            (int(user_id),),
        ).fetchone()
        expires = _parse_dt(row["expires_at"]) if row else None
        if expires and expires > now:
            return {
                "status": "active",
                "remaining_seconds": int((expires - now).total_seconds()),
            }

    cost = max(0, get_int("farm.boost.cost", 10))
    duration = max(1, get_int("farm.boost.duration_minutes", 180))
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        wallet = con.execute("SELECT balance FROM honey_wallets WHERE user_id=?", (int(user_id),)).fetchone()
        balance = int(wallet["balance"]) if wallet else 0
        if balance < cost:
            con.rollback()
            return {"status": "insufficient", "need": cost - balance, "cost": cost}

        start = _now()
        end = start + timedelta(minutes=duration)
        con.execute("UPDATE honey_wallets SET balance=balance-? WHERE user_id=?", (cost, int(user_id)))
        con.execute("""
            INSERT INTO farm_boosts(user_id, started_at, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                started_at=excluded.started_at,
                expires_at=excluded.expires_at
        """, (
            int(user_id),
            start.isoformat(timespec="seconds"),
            end.isoformat(timespec="seconds"),
        ))
        con.commit()
        return {
            "status": "ok",
            "cost": cost,
            "balance": balance - cost,
            "expires_at": end.isoformat(timespec="seconds"),
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def get_farm_details(user_id: int):
    farm = get_farm(user_id)
    init_farm_db()
    now = _now()
    with connect() as con:
        boost = _active_period(con, "farm_boosts", user_id)
        boost_view = None
        if boost and boost[0] <= now < boost[1]:
            boost_view = {
                "active": True,
                "expires_at": boost[1].isoformat(timespec="seconds"),
                "remaining_seconds": int((boost[1] - now).total_seconds()),
                "bonus_pct": get_float("farm.boost.production_bonus_pct", 20),
            }
        else:
            boost_view = {"active": False}

        event = _active_event_view(con, user_id, now)

    return {
        "farm": farm,
        "improvements": get_improvements(user_id),
        "boost": {
            **boost_view,
            "cost": get_int("farm.boost.cost", 10),
            "duration_minutes": get_int("farm.boost.duration_minutes", 180),
        },
        "event": event,
        "golden": get_golden_wallet(user_id),
    }


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
