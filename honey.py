import asyncio
import random
import sqlite3
from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import connect

HONEY_TOTAL = 300
HONEY_MIN = 30
HONEY_MAX = 40

_demo_lock = asyncio.Lock()


def init_honey_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            chat_type TEXT NOT NULL DEFAULT 'group',
            title TEXT NOT NULL DEFAULT '',
            last_seen TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS honey_wallets (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            total_earned INTEGER NOT NULL DEFAULT 0,
            giveaways_claimed INTEGER NOT NULL DEFAULT 0,
            biggest_claim INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS honey_schedule (
            day TEXT PRIMARY KEY,
            morning_time TEXT NOT NULL,
            evening_time TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS honey_giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            total_amount INTEGER NOT NULL DEFAULT 300,
            remaining INTEGER NOT NULL DEFAULT 300,
            active INTEGER NOT NULL DEFAULT 1,
            kind TEXT NOT NULL DEFAULT 'scheduled',
            schedule_day TEXT NOT NULL,
            schedule_slot TEXT NOT NULL,
            message_id INTEGER,
            participants INTEGER NOT NULL DEFAULT 0,
            UNIQUE(chat_id, schedule_day, schedule_slot)
        );

        CREATE TABLE IF NOT EXISTS honey_claims (
            giveaway_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            claimed_at TEXT NOT NULL,
            PRIMARY KEY (giveaway_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)

        # У старой версии не было отдельной таблицы чатов.
        # Берём уже знакомые чаты из существующей RP-статистики,
        # чтобы одноразовая демо-раздача могла появиться сразу после обновления.
        now = datetime.now().isoformat(timespec="seconds")
        con.execute("""
            INSERT OR IGNORE INTO chats(chat_id, chat_type, title, last_seen)
            SELECT DISTINCT chat_id, 'group', '', ? FROM pair_stats
        """, (now,))
        con.execute("""
            INSERT OR IGNORE INTO chats(chat_id, chat_type, title, last_seen)
            SELECT DISTINCT chat_id, 'group', '', ? FROM action_stats
        """, (now,))


def register_chat(chat_id: int, chat_type: str, title: str | None = None):
    if chat_type not in {"group", "supergroup"}:
        return
    with connect() as con:
        con.execute("""
            INSERT INTO chats(chat_id, chat_type, title, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type=excluded.chat_type,
                title=excluded.title,
                last_seen=excluded.last_seen
        """, (
            chat_id,
            chat_type,
            title or "",
            datetime.now().isoformat(timespec="seconds"),
        ))


def get_registered_chats():
    with connect() as con:
        rows = con.execute("""
            SELECT chat_id FROM chats
            WHERE chat_type IN ('group', 'supergroup')
            ORDER BY chat_id
        """).fetchall()
    return [int(row["chat_id"]) for row in rows]


def get_wallet(user_id: int):
    with connect() as con:
        row = con.execute("""
            SELECT balance, total_earned, giveaways_claimed, biggest_claim
            FROM honey_wallets WHERE user_id=?
        """, (user_id,)).fetchone()
    if not row:
        return {
            "balance": 0,
            "total_earned": 0,
            "giveaways_claimed": 0,
            "biggest_claim": 0,
        }
    return dict(row)


def _setting_get(key: str):
    with connect() as con:
        row = con.execute(
            "SELECT value FROM bot_settings WHERE key=?", (key,)
        ).fetchone()
    return row["value"] if row else None


def _setting_set(key: str, value: str):
    with connect() as con:
        con.execute("""
            INSERT INTO bot_settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))


def _random_time(start_hour: int, end_hour: int) -> str:
    start = start_hour * 60
    end = end_hour * 60
    minute_of_day = random.randint(start, end)
    hour, minute = divmod(minute_of_day, 60)
    return f"{hour:02d}:{minute:02d}"


def ensure_today_schedule(day: str | None = None):
    if day is None:
        day = datetime.now().date().isoformat()

    with connect() as con:
        row = con.execute(
            "SELECT morning_time, evening_time FROM honey_schedule WHERE day=?",
            (day,),
        ).fetchone()
        if row:
            return dict(row)

        morning = _random_time(9, 15)
        evening = _random_time(16, 23)
        con.execute("""
            INSERT INTO honey_schedule(day, morning_time, evening_time)
            VALUES (?, ?, ?)
        """, (day, morning, evening))

    return {"morning_time": morning, "evening_time": evening}


def honey_keyboard(giveaway_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text="🍯 Забрать мёдик",
            callback_data=f"honey:{giveaway_id}",
        )]]
    )


def giveaway_text(remaining: int = HONEY_TOTAL, demo: bool = False):
    demo_line = "\n🧪 <i>Одноразовая демонстрационная раздача после обновления.</i>\n" if demo else ""
    return (
        "🍯 <b>ВНЕЗАПНАЯ РАЗДАЧА МЁДИКА!</b>\n\n"
        "🐝 В улье появилась свежая партия мёдика!\n"
        f"{demo_line}\n"
        f"Всего в улье: <b>{HONEY_TOTAL} 🍯</b>\n"
        f"Осталось: <b>{remaining} 🍯</b>\n\n"
        f"Каждый может забрать один раз от <b>{HONEY_MIN} до {HONEY_MAX} 🍯</b>.\n"
        "Успей забрать свою долю!"
    )


def finished_text(participants: int):
    return (
        "🍯 <b>РАЗДАЧА ЗАВЕРШЕНА!</b>\n\n"
        "🐝 Весь мёдик разобрали.\n\n"
        f"Разобрано: <b>{HONEY_TOTAL} 🍯</b>\n"
        f"Получили мёдик: <b>{participants}</b>"
    )


def create_giveaway(chat_id: int, kind: str, schedule_day: str, schedule_slot: str):
    try:
        with connect() as con:
            cur = con.execute("""
                INSERT INTO honey_giveaways(
                    chat_id, created_at, total_amount, remaining, active,
                    kind, schedule_day, schedule_slot, participants
                )
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, 0)
            """, (
                chat_id,
                datetime.now().isoformat(timespec="seconds"),
                HONEY_TOTAL,
                HONEY_TOTAL,
                kind,
                schedule_day,
                schedule_slot,
            ))
            return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None


def delete_giveaway(giveaway_id: int):
    with connect() as con:
        con.execute("DELETE FROM honey_claims WHERE giveaway_id=?", (giveaway_id,))
        con.execute("DELETE FROM honey_giveaways WHERE id=?", (giveaway_id,))


def set_giveaway_message(giveaway_id: int, message_id: int):
    with connect() as con:
        con.execute(
            "UPDATE honey_giveaways SET message_id=? WHERE id=?",
            (message_id, giveaway_id),
        )


def get_giveaway(giveaway_id: int):
    with connect() as con:
        row = con.execute("""
            SELECT id, chat_id, total_amount, remaining, active, kind,
                   participants, message_id
            FROM honey_giveaways WHERE id=?
        """, (giveaway_id,)).fetchone()
    return dict(row) if row else None


def claim_honey(giveaway_id: int, user_id: int):
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")

        giveaway = con.execute("""
            SELECT remaining, active, participants
            FROM honey_giveaways WHERE id=?
        """, (giveaway_id,)).fetchone()

        if not giveaway or not giveaway["active"] or giveaway["remaining"] <= 0:
            con.rollback()
            return {"status": "ended"}

        already = con.execute("""
            SELECT 1 FROM honey_claims
            WHERE giveaway_id=? AND user_id=?
        """, (giveaway_id, user_id)).fetchone()
        if already:
            con.rollback()
            return {"status": "already"}

        remaining = int(giveaway["remaining"])
        if remaining < HONEY_MIN:
            amount = remaining
        else:
            amount = min(random.randint(HONEY_MIN, HONEY_MAX), remaining)

        new_remaining = remaining - amount
        new_active = 1 if new_remaining > 0 else 0
        new_participants = int(giveaway["participants"]) + 1
        now = datetime.now().isoformat(timespec="seconds")

        con.execute("""
            INSERT INTO honey_claims(giveaway_id, user_id, amount, claimed_at)
            VALUES (?, ?, ?, ?)
        """, (giveaway_id, user_id, amount, now))

        con.execute("""
            INSERT INTO honey_wallets(
                user_id, balance, total_earned, giveaways_claimed, biggest_claim
            ) VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = balance + excluded.balance,
                total_earned = total_earned + excluded.total_earned,
                giveaways_claimed = giveaways_claimed + 1,
                biggest_claim = MAX(biggest_claim, excluded.biggest_claim)
        """, (user_id, amount, amount, amount))

        con.execute("""
            UPDATE honey_giveaways
            SET remaining=?, active=?, participants=?
            WHERE id=?
        """, (new_remaining, new_active, new_participants, giveaway_id))

        wallet = con.execute("""
            SELECT balance FROM honey_wallets WHERE user_id=?
        """, (user_id,)).fetchone()

        con.commit()
        return {
            "status": "ok",
            "amount": amount,
            "remaining": new_remaining,
            "active": bool(new_active),
            "participants": new_participants,
            "balance": int(wallet["balance"]),
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


async def launch_giveaway(bot, chat_id: int, kind: str, schedule_day: str, schedule_slot: str):
    giveaway_id = create_giveaway(chat_id, kind, schedule_day, schedule_slot)
    if giveaway_id is None:
        return False

    try:
        message = await bot.send_message(
            chat_id,
            giveaway_text(HONEY_TOTAL, demo=(kind == "demo")),
            reply_markup=honey_keyboard(giveaway_id),
        )
        set_giveaway_message(giveaway_id, message.message_id)
        return True
    except Exception as exc:
        print(f"Honey giveaway send failed for chat {chat_id}: {exc}")
        delete_giveaway(giveaway_id)
        return False


async def maybe_launch_demo_once(bot, preferred_chat_id: int | None = None):
    async with _demo_lock:
        if _setting_get("honey_demo_v1_done") == "1":
            return

        # Если запись демо уже есть, значит сообщение успело уйти до перезапуска.
        with connect() as con:
            existing = con.execute("""
                SELECT 1 FROM honey_giveaways
                WHERE schedule_day='demo' AND schedule_slot='demo_v1'
                LIMIT 1
            """).fetchone()
        if existing:
            _setting_set("honey_demo_v1_done", "1")
            return

        chats = get_registered_chats()
        if preferred_chat_id is not None and preferred_chat_id not in chats:
            chats.insert(0, preferred_chat_id)
        elif preferred_chat_id is not None:
            chats = [preferred_chat_id] + [x for x in chats if x != preferred_chat_id]

        if not chats:
            return

        sent_any = False
        for chat_id in chats:
            sent = await launch_giveaway(
                bot,
                chat_id,
                kind="demo",
                schedule_day="demo",
                schedule_slot="demo_v1",
            )
            sent_any = sent_any or sent

        if sent_any:
            _setting_set("honey_demo_v1_done", "1")


async def honey_scheduler(bot):
    """Две раздачи ежедневно по локальным системным часам сервера.

    Первая: случайная минута с 09:00 до 15:00.
    Вторая: случайная минута с 16:00 до 23:00.
    """
    last_minute = None

    while True:
        try:
            now = datetime.now()
            current_day = now.date().isoformat()
            current_minute = now.strftime("%H:%M")

            # Не выполняем одинаковую минуту несколько раз из-за короткого цикла.
            minute_key = f"{current_day} {current_minute}"
            if minute_key != last_minute:
                last_minute = minute_key
                schedule = ensure_today_schedule(current_day)

                slot = None
                if current_minute == schedule["morning_time"]:
                    slot = "morning"
                elif current_minute == schedule["evening_time"]:
                    slot = "evening"

                if slot:
                    for chat_id in get_registered_chats():
                        await launch_giveaway(
                            bot,
                            chat_id,
                            kind="scheduled",
                            schedule_day=current_day,
                            schedule_slot=slot,
                        )

        except Exception as exc:
            print(f"Honey scheduler error: {exc}")

        await asyncio.sleep(10)
