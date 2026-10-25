import asyncio
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import connect

# Брак теряет 1% здоровья каждые 3 полных дня.
DECAY_INTERVAL_DAYS = 3
DECAY_AMOUNT = 1.0

# За сутки RP-командами можно восстановить не больше 3%.
DAILY_HEALTH_GAIN_LIMIT = 3.0

# Только обычные RP-команды влияют на здоровье брака.
RP_HEALTH_GAINS = {
    "hug": 0.4,
    "kiss": 0.7,
    "kiss_cheek": 0.5,
    "kiss_forehead": 0.5,
    "pat": 0.3,
    "cuddle": 0.5,
    "bite": 0.1,
    "lick": 0.2,
    "snuggle": 0.5,
    "carry": 0.4,
    "scratch_ears": 0.3,
    "ruffle_ears": 0.2,
    "boop": 0.1,
    "highfive": 0.2,
    "feed": 0.4,
    "flower": 1.0,
    "blanket": 0.5,
    "wake": 0.2,
    "sleep_near": 0.7,
    "tease": 0.1,
    "scare": 0.1,
    "tickle": 0.2,
    "praise": 0.3,
    "wink": 0.2,
    "embarrass": 0.1,
    "hold_hands": 0.4,
}


def utc_now():
    return datetime.utcnow()


def init_marriage_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS marriage_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            proposer_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS marriages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER NOT NULL,
            user2_id INTEGER NOT NULL,
            created_chat_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            health REAL NOT NULL DEFAULT 100.0,
            last_decay_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            ended_at TEXT
        );

        CREATE TABLE IF NOT EXISTS marriage_daily_health (
            marriage_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            gained REAL NOT NULL DEFAULT 0.0,
            PRIMARY KEY (marriage_id, day)
        );
        """)


def proposal_keyboard(proposal_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="💍 Принять",
            callback_data=f"marriage:accept:{proposal_id}",
        ),
        InlineKeyboardButton(
            text="❌ Отказаться",
            callback_data=f"marriage:reject:{proposal_id}",
        ),
    ]])


def divorce_keyboard(marriage_id: int, requester_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="💔 Развестись",
            callback_data=f"marriage:divorce:{marriage_id}:{requester_id}",
        ),
        InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=f"marriage:cancel_divorce:{marriage_id}:{requester_id}",
        ),
    ]])


def _get_user_name(con, user_id: int):
    row = con.execute(
        "SELECT name FROM users WHERE user_id=?",
        (user_id,),
    ).fetchone()
    return row["name"] if row else "Пользователь"


def _apply_decay_row(con, row):
    if not row or not row["active"]:
        return dict(row) if row else None

    now = utc_now()
    try:
        last_decay = datetime.fromisoformat(row["last_decay_at"])
    except Exception:
        last_decay = datetime.fromisoformat(row["started_at"])

    interval = timedelta(days=DECAY_INTERVAL_DAYS)
    elapsed = now - last_decay
    steps = int(elapsed.total_seconds() // interval.total_seconds())

    if steps <= 0:
        return dict(row)

    new_health = max(0.0, float(row["health"]) - steps * DECAY_AMOUNT)
    new_last_decay = last_decay + steps * interval

    con.execute(
        """
        UPDATE marriages
        SET health=?, last_decay_at=?
        WHERE id=?
        """,
        (
            new_health,
            new_last_decay.isoformat(timespec="seconds"),
            row["id"],
        ),
    )

    updated = dict(row)
    updated["health"] = new_health
    updated["last_decay_at"] = new_last_decay.isoformat(timespec="seconds")
    return updated


def get_active_marriage(user_id: int):
    with connect() as con:
        row = con.execute(
            """
            SELECT * FROM marriages
            WHERE active=1 AND (user1_id=? OR user2_id=?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, user_id),
        ).fetchone()
        if not row:
            return None

        marriage = _apply_decay_row(con, row)
        marriage["user1_name"] = _get_user_name(con, marriage["user1_id"])
        marriage["user2_name"] = _get_user_name(con, marriage["user2_id"])
        return marriage


def get_marriage_by_id(marriage_id: int):
    with connect() as con:
        row = con.execute(
            "SELECT * FROM marriages WHERE id=?",
            (marriage_id,),
        ).fetchone()
        if not row:
            return None
        marriage = _apply_decay_row(con, row)
        marriage["user1_name"] = _get_user_name(con, marriage["user1_id"])
        marriage["user2_name"] = _get_user_name(con, marriage["user2_id"])
        return marriage


def get_marriage_between(user_a: int, user_b: int):
    lo, hi = sorted((user_a, user_b))
    with connect() as con:
        row = con.execute(
            """
            SELECT * FROM marriages
            WHERE active=1
              AND ((user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?))
            ORDER BY id DESC
            LIMIT 1
            """,
            (lo, hi, hi, lo),
        ).fetchone()
        if not row:
            return None
        return _apply_decay_row(con, row)


def create_proposal(chat_id: int, proposer_id: int, target_id: int):
    if proposer_id == target_id:
        return {"status": "self"}

    if get_active_marriage(proposer_id):
        return {"status": "proposer_married"}
    if get_active_marriage(target_id):
        return {"status": "target_married"}

    with connect() as con:
        existing = con.execute(
            """
            SELECT id FROM marriage_proposals
            WHERE status='pending'
              AND ((proposer_id=? AND target_id=?) OR (proposer_id=? AND target_id=?))
            ORDER BY id DESC
            LIMIT 1
            """,
            (proposer_id, target_id, target_id, proposer_id),
        ).fetchone()
        if existing:
            return {"status": "already_pending", "proposal_id": existing["id"]}

        cur = con.execute(
            """
            INSERT INTO marriage_proposals(
                chat_id, proposer_id, target_id, created_at, status
            ) VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                chat_id,
                proposer_id,
                target_id,
                utc_now().isoformat(timespec="seconds"),
            ),
        )
        return {"status": "ok", "proposal_id": int(cur.lastrowid)}


def get_proposal(proposal_id: int):
    with connect() as con:
        row = con.execute(
            "SELECT * FROM marriage_proposals WHERE id=?",
            (proposal_id,),
        ).fetchone()
        return dict(row) if row else None


def reject_proposal(proposal_id: int, target_id: int):
    with connect() as con:
        row = con.execute(
            "SELECT * FROM marriage_proposals WHERE id=?",
            (proposal_id,),
        ).fetchone()
        if not row:
            return {"status": "missing"}
        if row["target_id"] != target_id:
            return {"status": "not_target"}
        if row["status"] != "pending":
            return {"status": "closed"}

        con.execute(
            "UPDATE marriage_proposals SET status='rejected' WHERE id=?",
            (proposal_id,),
        )
        return {"status": "ok", **dict(row)}


def accept_proposal(proposal_id: int, target_id: int):
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        proposal = con.execute(
            "SELECT * FROM marriage_proposals WHERE id=?",
            (proposal_id,),
        ).fetchone()
        if not proposal:
            con.rollback()
            return {"status": "missing"}
        if proposal["target_id"] != target_id:
            con.rollback()
            return {"status": "not_target"}
        if proposal["status"] != "pending":
            con.rollback()
            return {"status": "closed"}

        proposer_id = int(proposal["proposer_id"])
        target_id = int(proposal["target_id"])

        occupied = con.execute(
            """
            SELECT id FROM marriages
            WHERE active=1
              AND (user1_id IN (?, ?) OR user2_id IN (?, ?))
            LIMIT 1
            """,
            (proposer_id, target_id, proposer_id, target_id),
        ).fetchone()
        if occupied:
            con.execute(
                "UPDATE marriage_proposals SET status='cancelled' WHERE id=?",
                (proposal_id,),
            )
            con.commit()
            return {"status": "someone_married"}

        user1_id, user2_id = sorted((proposer_id, target_id))
        now = utc_now().isoformat(timespec="seconds")
        cur = con.execute(
            """
            INSERT INTO marriages(
                user1_id, user2_id, created_chat_id,
                started_at, health, last_decay_at, active
            ) VALUES (?, ?, ?, ?, 100.0, ?, 1)
            """,
            (
                user1_id,
                user2_id,
                proposal["chat_id"],
                now,
                now,
            ),
        )
        marriage_id = int(cur.lastrowid)

        con.execute(
            "UPDATE marriage_proposals SET status='accepted' WHERE id=?",
            (proposal_id,),
        )

        # Другие незакрытые предложения этих пользователей больше неактуальны.
        con.execute(
            """
            UPDATE marriage_proposals
            SET status='cancelled'
            WHERE status='pending'
              AND id<>?
              AND (proposer_id IN (?, ?) OR target_id IN (?, ?))
            """,
            (proposal_id, proposer_id, target_id, proposer_id, target_id),
        )
        con.commit()

        return {
            "status": "ok",
            "marriage_id": marriage_id,
            "proposer_id": proposer_id,
            "target_id": target_id,
            "started_at": now,
            "health": 100.0,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def marriage_state(health: float):
    if health >= 90:
        return "❤️ Идеальные отношения"
    if health >= 70:
        return "💕 Крепкий брак"
    if health >= 50:
        return "💛 Всё хорошо"
    if health >= 30:
        return "🧡 Отношения остывают"
    if health >= 10:
        return "💔 Брак в кризисе"
    if health > 0:
        return "🖤 На грани"
    return "🖤 Критическое состояние"


def format_marriage_age(started_at: str):
    try:
        start = datetime.fromisoformat(started_at)
    except Exception:
        return "неизвестно"

    seconds = max(0, int((utc_now() - start).total_seconds()))
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24

    if days >= 365:
        years = days // 365
        rest_days = days % 365
        months = rest_days // 30
        if months:
            return f"{years} г. {months} мес."
        return f"{years} г."

    if days >= 30:
        months = days // 30
        rest_days = days % 30
        if rest_days:
            return f"{months} мес. {rest_days} дн."
        return f"{months} мес."

    if days > 0:
        return f"{days} дн. {hours % 24} ч."
    if hours > 0:
        return f"{hours} ч. {minutes % 60} мин."
    if minutes > 0:
        return f"{minutes} мин."
    return "только что"


def apply_rp_health(user_a: int, user_b: int, action_key: str):
    requested_gain = RP_HEALTH_GAINS.get(action_key, 0.0)
    if requested_gain <= 0:
        return None

    marriage = get_marriage_between(user_a, user_b)
    if not marriage:
        return None

    marriage_id = int(marriage["id"])
    today = utc_now().date().isoformat()

    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")

        row = con.execute(
            "SELECT gained FROM marriage_daily_health WHERE marriage_id=? AND day=?",
            (marriage_id, today),
        ).fetchone()
        gained_today = float(row["gained"]) if row else 0.0

        available = max(0.0, DAILY_HEALTH_GAIN_LIMIT - gained_today)
        actual_gain = min(requested_gain, available)

        current = con.execute(
            "SELECT health, active FROM marriages WHERE id=?",
            (marriage_id,),
        ).fetchone()
        if not current or not current["active"]:
            con.rollback()
            return None

        old_health = float(current["health"])
        actual_gain = min(actual_gain, max(0.0, 100.0 - old_health))
        new_health = min(100.0, old_health + actual_gain)

        if actual_gain > 0:
            con.execute(
                "UPDATE marriages SET health=? WHERE id=?",
                (new_health, marriage_id),
            )
            con.execute(
                """
                INSERT INTO marriage_daily_health(marriage_id, day, gained)
                VALUES (?, ?, ?)
                ON CONFLICT(marriage_id, day) DO UPDATE SET
                    gained = gained + excluded.gained
                """,
                (marriage_id, today, actual_gain),
            )

        con.commit()
        return {
            "marriage_id": marriage_id,
            "gain": actual_gain,
            "old_health": old_health,
            "new_health": new_health,
            "daily_gained": gained_today + actual_gain,
            "daily_limit": DAILY_HEALTH_GAIN_LIMIT,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def apply_bonus_health(user_a: int, user_b: int, requested_gain: float):
    """Добавляет здоровье брака от подарков, используя тот же дневной лимит 3%."""
    if requested_gain <= 0:
        return None

    marriage = get_marriage_between(user_a, user_b)
    if not marriage:
        return None

    marriage_id = int(marriage["id"])
    today = utc_now().date().isoformat()

    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")

        row = con.execute(
            "SELECT gained FROM marriage_daily_health WHERE marriage_id=? AND day=?",
            (marriage_id, today),
        ).fetchone()
        gained_today = float(row["gained"]) if row else 0.0

        available = max(0.0, DAILY_HEALTH_GAIN_LIMIT - gained_today)
        actual_gain = min(float(requested_gain), available)

        current = con.execute(
            "SELECT health, active FROM marriages WHERE id=?",
            (marriage_id,),
        ).fetchone()
        if not current or not current["active"]:
            con.rollback()
            return None

        old_health = float(current["health"])
        actual_gain = min(actual_gain, max(0.0, 100.0 - old_health))
        new_health = min(100.0, old_health + actual_gain)

        if actual_gain > 0:
            con.execute(
                "UPDATE marriages SET health=? WHERE id=?",
                (new_health, marriage_id),
            )
            con.execute(
                """
                INSERT INTO marriage_daily_health(marriage_id, day, gained)
                VALUES (?, ?, ?)
                ON CONFLICT(marriage_id, day) DO UPDATE SET
                    gained = gained + excluded.gained
                """,
                (marriage_id, today, actual_gain),
            )

        con.commit()
        return {
            "marriage_id": marriage_id,
            "gain": actual_gain,
            "old_health": old_health,
            "new_health": new_health,
            "daily_gained": gained_today + actual_gain,
            "daily_limit": DAILY_HEALTH_GAIN_LIMIT,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def divorce_marriage(marriage_id: int, requester_id: int):
    with connect() as con:
        row = con.execute(
            "SELECT * FROM marriages WHERE id=?",
            (marriage_id,),
        ).fetchone()
        if not row:
            return {"status": "missing"}
        if requester_id not in {row["user1_id"], row["user2_id"]}:
            return {"status": "not_spouse"}
        if not row["active"]:
            return {"status": "ended"}

        con.execute(
            "UPDATE marriages SET active=0, ended_at=? WHERE id=?",
            (utc_now().isoformat(timespec="seconds"), marriage_id),
        )
        return {"status": "ok", **dict(row)}


def decay_all_marriages():
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM marriages WHERE active=1"
        ).fetchall()
        changed = 0
        for row in rows:
            before = float(row["health"])
            updated = _apply_decay_row(con, row)
            if updated and float(updated["health"]) != before:
                changed += 1
        return changed


async def marriage_decay_scheduler():
    while True:
        try:
            decay_all_marriages()
        except Exception as exc:
            print(f"Marriage decay scheduler error: {exc}")
        await asyncio.sleep(3600)
