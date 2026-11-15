import hashlib
import hmac
import os
from datetime import datetime, timedelta

from database import connect

BOT_TIME_OFFSET_HOURS = 3
ADMIN_SESSION_HOURS = 24

DEFAULT_CONFIG = {
    "farm.production.1": "10", "farm.production.2": "15", "farm.production.3": "20",
    "farm.production.4": "25", "farm.production.5": "30", "farm.production.6": "38",
    "farm.production.7": "47", "farm.production.8": "58", "farm.production.9": "72",
    "farm.production.10": "90", "farm.production.11": "112", "farm.production.12": "140",

    "farm.capacity.1": "15", "farm.capacity.2": "25", "farm.capacity.3": "35",
    "farm.capacity.4": "50", "farm.capacity.5": "70", "farm.capacity.6": "95",
    "farm.capacity.7": "125", "farm.capacity.8": "160", "farm.capacity.9": "210",
    "farm.capacity.10": "280", "farm.capacity.11": "360", "farm.capacity.12": "460",

    "farm.upgrade.1": "75", "farm.upgrade.2": "150", "farm.upgrade.3": "275",
    "farm.upgrade.4": "450", "farm.upgrade.5": "700", "farm.upgrade.6": "1000",
    "farm.upgrade.7": "1450", "farm.upgrade.8": "2000", "farm.upgrade.9": "2800",
    "farm.upgrade.10": "3800", "farm.upgrade.11": "5000",

    "farm.improvement.flowers.base_cost": "120",
    "farm.improvement.flowers.growth": "1.65",
    "farm.improvement.flowers.bonus_pct": "5",
    "farm.improvement.combs.base_cost": "140",
    "farm.improvement.combs.growth": "1.65",
    "farm.improvement.combs.bonus_pct": "6",
    "farm.improvement.beekeeper.base_cost": "180",
    "farm.improvement.beekeeper.growth": "1.70",
    "farm.improvement.beekeeper.bonus_pct": "4",
    "farm.improvement.queen.base_cost": "350",
    "farm.improvement.queen.growth": "2.00",
    "farm.improvement.queen.bonus_pct": "8",

    "farm.boost.cost": "10",
    "farm.boost.duration_minutes": "180",
    "farm.boost.production_bonus_pct": "20",

    "farm.event.chance_pct": "12",
    "farm.event.cooldown_hours": "6",
    "farm.event.duration_minutes": "120",

    "farm.golden_chance_pct": "3",
    "farm.golden_vip_bonus_pct": "1",
    "farm.golden_min_collect": "5",

    "task.collect.goal": "20",
    "task.collect.reward": "5",
    "task.gift.goal": "1",
    "task.gift.reward": "8",
    "task.trade.goal": "1",
    "task.trade.reward": "7",

    "honey.enabled": "1",
    "honey.total": "300",
    "honey.min": "30",
    "honey.max": "40",
    "honey.duration_minutes": "60",
    "honey.morning_start": "09:00",
    "honey.morning_end": "15:00",
    "honey.evening_start": "16:00",
    "honey.evening_end": "23:00",

    "gift.rose.price": "20", "gift.rose.health_bonus": "0.1",
    "gift.chocolate.price": "35", "gift.chocolate.health_bonus": "0.2",
    "gift.teddy.price": "75", "gift.teddy.health_bonus": "0.3",
    "gift.bouquet.price": "120", "gift.bouquet.health_bonus": "0.5",
    "gift.crystal.price": "250", "gift.crystal.health_bonus": "0.7",
    "gift.crown.price": "500", "gift.crown.health_bonus": "1.0",
    "gift.resale_pct": "60",

    "exchange.enabled": "1",
    "exchange.start_price": "20",
    "exchange.min_price": "5",
    "exchange.max_price": "100",
    "exchange.volatility_pct": "3",
    "exchange.update_minutes": "5",
    "exchange.buy_fee_pct": "1",
    "exchange.sell_fee_pct": "1",
    "exchange.news_chance_pct": "6",
    "exchange.admin_nudge_pct": "5",

    "vip.enabled": "1",
    "vip.days.7": "7",
    "vip.days.30": "30",
    "vip.price.7": "250",
    "vip.price.30": "750",
    "vip.farm_production_bonus_pct": "20",
    "vip.farm_capacity_bonus_pct": "25",
    "vip.giveaway_bonus_pct": "10",

    "rules.text": "Правила пока не опубликованы.",

    "backup.auto_enabled": "0",
    "backup.hour": "04:00",
    "backup.keep_local": "7",
}

def bot_now():
    return datetime.utcnow() + timedelta(hours=BOT_TIME_OFFSET_HOURS)

def init_config_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS bot_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'admin',
            first_authorized_at TEXT NOT NULL,
            last_authorized_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_sessions (
            user_id INTEGER PRIMARY KEY,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            created_at TEXT NOT NULL
        );
        """)
        now = bot_now().isoformat(timespec="seconds")
        for key, value in DEFAULT_CONFIG.items():
            con.execute(
                "INSERT OR IGNORE INTO bot_config(key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )

def get_setting(key: str, default=None):
    with connect() as con:
        row = con.execute("SELECT value FROM bot_config WHERE key=?", (key,)).fetchone()
    if row:
        return row["value"]
    if default is not None:
        return default
    return DEFAULT_CONFIG.get(key)

def get_int(key: str, default: int = 0) -> int:
    try:
        return int(float(get_setting(key, default)))
    except (TypeError, ValueError):
        return int(default)

def get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(get_setting(key, default))
    except (TypeError, ValueError):
        return float(default)

def get_bool(key: str, default: bool = False) -> bool:
    value = str(get_setting(key, "1" if default else "0")).strip().lower()
    return value in {"1", "true", "yes", "on", "да"}

def log_admin_action(user_id: int, action: str, old_value=None, new_value=None):
    with connect() as con:
        con.execute(
            """
            INSERT INTO admin_audit(user_id, action, old_value, new_value, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(user_id), str(action),
                None if old_value is None else str(old_value),
                None if new_value is None else str(new_value),
                bot_now().isoformat(timespec="seconds"),
            ),
        )

def set_setting(key: str, value, admin_user_id: int | None = None, action_label: str | None = None):
    old = get_setting(key)
    value = str(value)
    now = bot_now().isoformat(timespec="seconds")
    with connect() as con:
        con.execute(
            """
            INSERT INTO bot_config(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now),
        )
    if admin_user_id is not None:
        log_admin_action(admin_user_id, action_label or f"Изменена настройка {key}", old, value)
    return old, value

def is_admin_user_allowed(user_id: int) -> bool:
    raw = (os.getenv("ADMIN_USER_IDS") or os.getenv("ADMIN_USER_ID") or "").strip()
    if not raw:
        return True
    allowed = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            allowed.add(int(part))
        except ValueError:
            continue
    return int(user_id) in allowed

def verify_admin_password(password: str) -> tuple[bool, str | None]:
    expected_hash = (os.getenv("ADMIN_PASSWORD_HASH") or "").strip().lower()
    expected_plain = os.getenv("ADMIN_PASSWORD")
    if expected_hash:
        digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, expected_hash), None
    if expected_plain is not None and expected_plain != "":
        return hmac.compare_digest(password, expected_plain), None
    return False, "Пароль администратора не настроен. Добавь ADMIN_PASSWORD или ADMIN_PASSWORD_HASH."

def authorize_admin(user_id: int, name: str) -> str:
    now = bot_now()
    expires = now + timedelta(hours=ADMIN_SESSION_HOURS)
    with connect() as con:
        existing = con.execute(
            "SELECT first_authorized_at FROM admin_users WHERE user_id=?", (user_id,)
        ).fetchone()
        first = existing["first_authorized_at"] if existing else now.isoformat(timespec="seconds")
        con.execute(
            """
            INSERT INTO admin_users(user_id, name, role, first_authorized_at, last_authorized_at)
            VALUES (?, ?, 'admin', ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name,
                last_authorized_at=excluded.last_authorized_at
            """,
            (user_id, name or "", first, now.isoformat(timespec="seconds")),
        )
        con.execute(
            """
            INSERT INTO admin_sessions(user_id, expires_at) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at
            """,
            (user_id, expires.isoformat(timespec="seconds")),
        )
    log_admin_action(user_id, "Вход в панель администратора")
    return expires.isoformat(timespec="seconds")

def is_admin_session(user_id: int) -> bool:
    now = bot_now()
    with connect() as con:
        row = con.execute("SELECT expires_at FROM admin_sessions WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return False
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except Exception:
            con.execute("DELETE FROM admin_sessions WHERE user_id=?", (user_id,))
            return False
        if expires <= now:
            con.execute("DELETE FROM admin_sessions WHERE user_id=?", (user_id,))
            return False
    return True

def logout_admin(user_id: int):
    with connect() as con:
        con.execute("DELETE FROM admin_sessions WHERE user_id=?", (user_id,))
    log_admin_action(user_id, "Выход из панели администратора")

def get_admin_user_ids() -> list[int]:
    with connect() as con:
        rows = con.execute("SELECT user_id FROM admin_users ORDER BY user_id").fetchall()
    return [int(row["user_id"]) for row in rows]

def get_recent_audit(limit: int = 10):
    limit = max(1, min(int(limit), 50))
    with connect() as con:
        rows = con.execute(
            """
            SELECT a.id, a.user_id, a.action, a.old_value, a.new_value, a.created_at,
                   COALESCE(u.name, '') AS admin_name
            FROM admin_audit a
            LEFT JOIN admin_users u ON u.user_id=a.user_id
            ORDER BY a.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]

def get_admin_stats():
    with connect() as con:
        def count(table: str, where: str = "", params=()):
            try:
                row = con.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()
                return int(row["c"] if row else 0)
            except Exception:
                return 0

        users = count("users")
        chats = count("chats")
        wallets = count("honey_wallets")
        farms = count("honey_farms")
        profiles = count("profiles")
        active_marriages = count("marriages", "WHERE active=1")
        active_vips = count(
            "vip_subscriptions", "WHERE expires_at>?",
            (bot_now().isoformat(timespec="seconds"),),
        )
        exchange_players = count("exchange_portfolios", "WHERE shares>0")
        golden_players = count("golden_honey_wallets", "WHERE balance>0")

        honey_total = 0
        try:
            row = con.execute("SELECT COALESCE(SUM(balance), 0) AS s FROM honey_wallets").fetchone()
            honey_total = int(row["s"] if row else 0)
        except Exception:
            pass

    return {
        "users": users, "chats": chats, "wallets": wallets,
        "honey_total": honey_total, "farms": farms, "profiles": profiles,
        "active_marriages": active_marriages, "active_vips": active_vips,
        "exchange_players": exchange_players, "golden_players": golden_players,
    }
