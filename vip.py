from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import bot_now, get_bool, get_int
from database import connect


def init_vip_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS vip_subscriptions (
            user_id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_purchase_at TEXT NOT NULL,
            last_plan_days INTEGER NOT NULL,
            last_price INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS vip_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_days INTEGER NOT NULL,
            price INTEGER NOT NULL,
            purchased_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        """)


def get_vip_status(user_id: int):
    enabled = get_bool("vip.enabled", True)
    with connect() as con:
        row = con.execute(
            """
            SELECT started_at, expires_at, last_purchase_at, last_plan_days, last_price
            FROM vip_subscriptions WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()

    if not row:
        return {
            "active": False,
            "enabled": enabled,
            "started_at": None,
            "expires_at": None,
            "remaining_days": 0,
            "remaining_hours": 0,
        }

    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except Exception:
        expires = bot_now()

    now = bot_now()
    remaining_seconds = max(0, int((expires - now).total_seconds()))
    active = enabled and remaining_seconds > 0

    return {
        "active": active,
        "enabled": enabled,
        "started_at": row["started_at"],
        "expires_at": row["expires_at"],
        "remaining_days": remaining_seconds // 86400,
        "remaining_hours": (remaining_seconds % 86400) // 3600,
        "last_plan_days": int(row["last_plan_days"]),
        "last_price": int(row["last_price"]),
    }


def get_vip_period(user_id: int):
    with connect() as con:
        row = con.execute(
            "SELECT started_at, expires_at FROM vip_subscriptions WHERE user_id=?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return {
            "started_at": datetime.fromisoformat(row["started_at"]),
            "expires_at": datetime.fromisoformat(row["expires_at"]),
        }
    except Exception:
        return None


def vip_production_multiplier(user_id: int) -> float:
    if not get_vip_status(user_id)["active"]:
        return 1.0
    return 1.0 + get_int("vip.farm_production_bonus_pct", 20) / 100.0


def vip_capacity_multiplier(user_id: int) -> float:
    if not get_vip_status(user_id)["active"]:
        return 1.0
    return 1.0 + get_int("vip.farm_capacity_bonus_pct", 25) / 100.0


def vip_giveaway_multiplier(user_id: int) -> float:
    if not get_vip_status(user_id)["active"]:
        return 1.0
    return 1.0 + get_int("vip.giveaway_bonus_pct", 10) / 100.0


def purchase_vip(user_id: int, plan: int):
    if not get_bool("vip.enabled", True):
        return {"status": "disabled"}
    if plan not in {7, 30}:
        return {"status": "invalid"}

    days = max(1, get_int(f"vip.days.{plan}", plan))
    price = get_int(f"vip.price.{plan}", 250 if plan == 7 else 750)

    # Синхронизируем ферму до смены VIP-статуса, чтобы новый бонус
    # не применился задним числом к уже прошедшему времени.
    try:
        from farm import get_farm
        get_farm(user_id)
    except Exception:
        pass

    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")

        wallet = con.execute(
            "SELECT balance FROM honey_wallets WHERE user_id=?", (user_id,)
        ).fetchone()
        balance = int(wallet["balance"]) if wallet else 0
        if balance < price:
            con.rollback()
            return {
                "status": "insufficient",
                "balance": balance,
                "need": price - balance,
                "price": price,
            }

        now = bot_now()
        row = con.execute(
            "SELECT started_at, expires_at FROM vip_subscriptions WHERE user_id=?",
            (user_id,),
        ).fetchone()

        if row:
            try:
                old_expires = datetime.fromisoformat(row["expires_at"])
            except Exception:
                old_expires = now
        else:
            old_expires = now

        if old_expires > now:
            start = datetime.fromisoformat(row["started_at"]) if row else now
            base = old_expires
        else:
            start = now
            base = now

        expires = base + timedelta(days=days)
        now_text = now.isoformat(timespec="seconds")
        expires_text = expires.isoformat(timespec="seconds")

        con.execute(
            "UPDATE honey_wallets SET balance=balance-? WHERE user_id=?",
            (price, user_id),
        )
        con.execute(
            """
            INSERT INTO vip_subscriptions(
                user_id, started_at, expires_at, last_purchase_at,
                last_plan_days, last_price
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                started_at=excluded.started_at,
                expires_at=excluded.expires_at,
                last_purchase_at=excluded.last_purchase_at,
                last_plan_days=excluded.last_plan_days,
                last_price=excluded.last_price
            """,
            (
                user_id,
                start.isoformat(timespec="seconds"),
                expires_text,
                now_text,
                days,
                price,
            ),
        )
        con.execute(
            """
            INSERT INTO vip_purchases(user_id, plan_days, price, purchased_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, days, price, now_text, expires_text),
        )
        con.commit()

        return {
            "status": "ok",
            "price": price,
            "days": days,
            "balance": balance - price,
            "expires_at": expires_text,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def vip_keyboard(user_id: int):
    if not get_bool("vip.enabled", True):
        return None
    d7 = max(1, get_int("vip.days.7", 7))
    d30 = max(1, get_int("vip.days.30", 30))
    p7 = get_int("vip.price.7", 250)
    p30 = get_int("vip.price.30", 750)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"👑 VIP {d7} дней · {p7} 🍯",
                    callback_data=f"vip:buy:7:{user_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"💎 VIP {d30} дней · {p30} 🍯",
                    callback_data=f"vip:buy:30:{user_id}",
                )
            ],
        ]
    )
