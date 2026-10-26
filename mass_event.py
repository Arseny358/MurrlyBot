import asyncio
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import connect
from honey import BOT_TIME_OFFSET_HOURS


EVENT_DURATION_MINUTES = 60
EVENT_HOUR = 23
EVENT_MINUTE = 0


def bot_now():
    return datetime.utcnow() + timedelta(hours=BOT_TIME_OFFSET_HOURS)


def init_mass_event_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS mass_orgy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            kind TEXT NOT NULL DEFAULT 'scheduled',
            event_day TEXT NOT NULL,
            event_slot TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            message_id INTEGER,
            participants INTEGER NOT NULL DEFAULT 0,
            UNIQUE(chat_id, event_day, event_slot)
        );

        CREATE TABLE IF NOT EXISTS mass_orgy_participants (
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            PRIMARY KEY (event_id, user_id)
        );
        """)


def _setting_get(key: str):
    with connect() as con:
        row = con.execute(
            "SELECT value FROM bot_settings WHERE key=?",
            (key,),
        ).fetchone()
    return row["value"] if row else None


def _setting_set(key: str, value: str):
    with connect() as con:
        con.execute("""
            INSERT INTO bot_settings(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))


def _registered_chats():
    with connect() as con:
        rows = con.execute("""
            SELECT chat_id FROM chats
            WHERE chat_type IN ('group', 'supergroup')
            ORDER BY chat_id
        """).fetchall()
    return [int(row["chat_id"]) for row in rows]


def event_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🔥 Присоединиться",
                callback_data=f"massorgy:join:{event_id}",
            )
        ]]
    )


def event_text(participants: int = 0, closes_at: str | None = None):
    close_line = (
        f"\n⏰ Событие закроется в <b>{closes_at}</b>.\n"
        if closes_at else ""
    )

    return (
        "🔥 <b>МАССОВАЯ ОРГИЯ</b>\n\n"
        "18+ RP-событие для участников чата.\n"
        f"\n👥 Участников: <b>{participants}</b>"
        f"{close_line}\n"
        "Нажми кнопку, если хочешь присоединиться."
    )


def finished_event_text(participants: int):
    return (
        "🔥 <b>МАССОВАЯ ОРГИЯ ЗАВЕРШЕНА</b>\n\n"
        f"👥 Участников: <b>{participants}</b>\n"
        "Событие завершено."
    )


def create_event(chat_id: int, kind: str, event_day: str, event_slot: str):
    now = bot_now()
    expires = now + timedelta(minutes=EVENT_DURATION_MINUTES)

    try:
        with connect() as con:
            cur = con.execute("""
                INSERT INTO mass_orgy_events(
                    chat_id, kind, event_day, event_slot,
                    created_at, expires_at, active, participants
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, 0)
            """, (
                chat_id,
                kind,
                event_day,
                event_slot,
                now.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
            ))

            return {
                "id": int(cur.lastrowid),
                "expires_at": expires.isoformat(timespec="seconds"),
            }
    except Exception:
        return None


def set_event_message(event_id: int, message_id: int):
    with connect() as con:
        con.execute("""
            UPDATE mass_orgy_events
            SET message_id=?
            WHERE id=?
        """, (message_id, event_id))


def get_event(event_id: int):
    with connect() as con:
        row = con.execute("""
            SELECT id, chat_id, kind, event_day, event_slot,
                   created_at, expires_at, active, message_id, participants
            FROM mass_orgy_events
            WHERE id=?
        """, (event_id,)).fetchone()
    return dict(row) if row else None


def join_event(event_id: int, user_id: int):
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")

        event = con.execute("""
            SELECT active, expires_at, participants
            FROM mass_orgy_events
            WHERE id=?
        """, (event_id,)).fetchone()

        if not event or not event["active"]:
            con.rollback()
            return {"status": "ended"}

        try:
            expires_at = datetime.fromisoformat(event["expires_at"])
        except Exception:
            expires_at = None

        if expires_at is not None and bot_now() >= expires_at:
            con.execute(
                "UPDATE mass_orgy_events SET active=0 WHERE id=?",
                (event_id,),
            )
            con.commit()
            return {"status": "ended"}

        exists = con.execute("""
            SELECT 1 FROM mass_orgy_participants
            WHERE event_id=? AND user_id=?
        """, (event_id, user_id)).fetchone()

        if exists:
            con.rollback()
            return {"status": "already"}

        now = bot_now().isoformat(timespec="seconds")
        con.execute("""
            INSERT INTO mass_orgy_participants(event_id, user_id, joined_at)
            VALUES (?, ?, ?)
        """, (event_id, user_id, now))

        participants = int(event["participants"]) + 1
        con.execute("""
            UPDATE mass_orgy_events
            SET participants=?
            WHERE id=?
        """, (participants, event_id))

        con.commit()
        return {
            "status": "ok",
            "participants": participants,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


async def launch_event(bot, chat_id: int, kind: str, event_day: str, event_slot: str):
    created = create_event(chat_id, kind, event_day, event_slot)
    if created is None:
        return False

    event_id = created["id"]
    closes_at = datetime.fromisoformat(created["expires_at"]).strftime("%H:%M")

    try:
        message = await bot.send_message(
            chat_id,
            event_text(
                participants=0,
                closes_at=closes_at,
            ),
            reply_markup=event_keyboard(event_id),
        )
        set_event_message(event_id, message.message_id)
        return True
    except Exception as exc:
        print(f"Mass orgy event send failed for chat {chat_id}: {exc}")
        return False


def _today_event_exists(chat_id: int, day: str):
    with connect() as con:
        row = con.execute("""
            SELECT 1 FROM mass_orgy_events
            WHERE chat_id=? AND event_day=? AND event_slot='23:00'
            LIMIT 1
        """, (chat_id, day)).fetchone()
    return bool(row)


async def mass_event_scheduler(bot):
    while True:
        try:
            now = bot_now()
            today = now.date().isoformat()

            # После 23:00 создаём одно штатное событие на чат.
            # UNIQUE + проверка даты не дадут создать дубль после перезапуска.
            if (now.hour, now.minute) >= (EVENT_HOUR, EVENT_MINUTE):
                for chat_id in _registered_chats():
                    if not _today_event_exists(chat_id, today):
                        await launch_event(
                            bot,
                            chat_id,
                            kind="scheduled",
                            event_day=today,
                            event_slot="23:00",
                        )

        except Exception as exc:
            print(f"Mass orgy scheduler error: {exc}")

        await asyncio.sleep(20)


def get_expired_events():
    now = bot_now()

    with connect() as con:
        rows = con.execute("""
            SELECT id, chat_id, message_id, participants, expires_at
            FROM mass_orgy_events
            WHERE active=1
        """).fetchall()

    result = []
    for row in rows:
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
        except Exception:
            continue

        if now >= expires_at:
            result.append(dict(row))

    return result


def close_event(event_id: int):
    with connect() as con:
        row = con.execute("""
            SELECT active, participants
            FROM mass_orgy_events
            WHERE id=?
        """, (event_id,)).fetchone()

        if not row:
            return None

        con.execute(
            "UPDATE mass_orgy_events SET active=0 WHERE id=?",
            (event_id,),
        )

        return {
            "was_active": bool(row["active"]),
            "participants": int(row["participants"]),
        }


async def mass_event_expiration_scheduler(bot):
    while True:
        try:
            for event in get_expired_events():
                closed = close_event(event["id"])

                if not closed or not closed["was_active"]:
                    continue

                if event["message_id"]:
                    try:
                        await bot.edit_message_text(
                            chat_id=event["chat_id"],
                            message_id=event["message_id"],
                            text=finished_event_text(closed["participants"]),
                            reply_markup=None,
                        )
                    except Exception as exc:
                        print(f"Mass orgy close edit failed: {exc}")

        except Exception as exc:
            print(f"Mass orgy expiration scheduler error: {exc}")

        await asyncio.sleep(10)
