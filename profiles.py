from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import connect
from rp_actions import ACTIONS


BOT_TIME_OFFSET_HOURS = 3

PROFILE_FIELDS = {
    "display_name": "Имя / ник",
    "age": "Возраст",
    "city": "Город",
    "gender": "Пол",
    "bio": "О себе",
}


def bot_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=BOT_TIME_OFFSET_HOURS)


def init_profiles_db():
    """
    ВАЖНО: таблицу profiles не пересоздаём и не очищаем.
    Существующие анкеты остаются без изменений.
    Новая статистика хранится в отдельных таблицах.
    """
    with connect() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT,
                age INTEGER,
                city TEXT,
                gender TEXT,
                bio TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profile_chat_activity (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL,
                joined_at TEXT,
                last_seen_at TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS profile_daily_activity (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, user_id, day)
            );

            CREATE INDEX IF NOT EXISTS idx_profile_daily_chat_day
            ON profile_daily_activity(chat_id, day);

            CREATE INDEX IF NOT EXISTS idx_profile_activity_chat_messages
            ON profile_chat_activity(chat_id, message_count DESC);
        """)


def get_profile(user_id: int):
    with connect() as con:
        row = con.execute("""
            SELECT user_id, display_name, age, city, gender, bio, updated_at
            FROM profiles
            WHERE user_id=?
        """, (user_id,)).fetchone()

    if not row:
        return {
            "user_id": user_id,
            "display_name": None,
            "age": None,
            "city": None,
            "gender": None,
            "bio": None,
            "updated_at": None,
        }

    return dict(row)


def profile_is_empty(profile: dict):
    return not any(
        profile.get(key)
        for key in ("display_name", "age", "city", "gender", "bio")
    )


def set_profile_field(user_id: int, field: str, value):
    if field not in PROFILE_FIELDS:
        raise ValueError("Unknown profile field")

    now = datetime.utcnow().isoformat(timespec="seconds")

    with connect() as con:
        con.execute("""
            INSERT INTO profiles(
                user_id, display_name, age, city, gender, bio, updated_at
            )
            VALUES (?, NULL, NULL, NULL, NULL, NULL, ?)
            ON CONFLICT(user_id) DO NOTHING
        """, (user_id, now))

        con.execute(
            f"UPDATE profiles SET {field}=?, updated_at=? WHERE user_id=?",
            (value, now, user_id),
        )

    return get_profile(user_id)


def touch_chat_member(chat_id: int, user_id: int):
    """Запоминает участника, не увеличивая счётчик сообщений."""
    now = bot_now().isoformat(timespec="seconds")

    with connect() as con:
        con.execute("""
            INSERT INTO profile_chat_activity(
                chat_id, user_id, first_seen_at, joined_at,
                last_seen_at, message_count
            )
            VALUES (?, ?, ?, NULL, ?, 0)
            ON CONFLICT(chat_id, user_id) DO NOTHING
        """, (chat_id, user_id, now, now))


def record_member_join(chat_id: int, user_id: int):
    """
    Сохраняет точную дату вступления, если Telegram прислал service-message.
    При повторном вступлении joined_at обновляется, first_seen_at сохраняется.
    """
    now = bot_now().isoformat(timespec="seconds")

    with connect() as con:
        con.execute("""
            INSERT INTO profile_chat_activity(
                chat_id, user_id, first_seen_at, joined_at,
                last_seen_at, message_count
            )
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                joined_at = excluded.joined_at,
                last_seen_at = excluded.last_seen_at
        """, (chat_id, user_id, now, now, now))


def record_chat_message(chat_id: int, user_id: int):
    """Учитывает одно сообщение пользователя в конкретном групповом чате."""
    now_dt = bot_now()
    now = now_dt.isoformat(timespec="seconds")
    day = now_dt.date().isoformat()

    with connect() as con:
        con.execute("""
            INSERT INTO profile_chat_activity(
                chat_id, user_id, first_seen_at, joined_at,
                last_seen_at, message_count
            )
            VALUES (?, ?, ?, NULL, ?, 1)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                message_count = profile_chat_activity.message_count + 1
        """, (chat_id, user_id, now, now))

        con.execute("""
            INSERT INTO profile_daily_activity(
                chat_id, user_id, day, message_count
            )
            VALUES (?, ?, ?, 1)
            ON CONFLICT(chat_id, user_id, day) DO UPDATE SET
                message_count = profile_daily_activity.message_count + 1
        """, (chat_id, user_id, day))


def activity_level(messages_30d: int) -> str:
    if messages_30d <= 0:
        return "🌙 Тихоня"
    if messages_30d <= 10:
        return "🌱 Редко заглядывает"
    if messages_30d <= 50:
        return "💬 Общительный"
    if messages_30d <= 150:
        return "🔥 Активный"
    if messages_30d <= 400:
        return "⚡ Очень активный"
    return "👑 Легенда чата"


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _consecutive_activity_days(days: list[str]) -> int:
    if not days:
        return 0

    parsed = set()
    for value in days:
        try:
            parsed.add(datetime.fromisoformat(value).date())
        except Exception:
            pass

    if not parsed:
        return 0

    today = bot_now().date()
    cursor = today if today in parsed else today - timedelta(days=1)

    if cursor not in parsed:
        return 0

    streak = 0
    while cursor in parsed:
        streak += 1
        cursor -= timedelta(days=1)

    return streak


def get_chat_activity(chat_id: int, user_id: int):
    now = bot_now()
    today = now.date()
    day_7 = (today - timedelta(days=6)).isoformat()
    day_30 = (today - timedelta(days=29)).isoformat()

    with connect() as con:
        row = con.execute("""
            SELECT first_seen_at, joined_at, last_seen_at, message_count
            FROM profile_chat_activity
            WHERE chat_id=? AND user_id=?
        """, (chat_id, user_id)).fetchone()

        if not row:
            return {
                "chat_id": chat_id,
                "user_id": user_id,
                "first_seen_at": None,
                "joined_at": None,
                "last_seen_at": None,
                "message_count": 0,
                "messages_7d": 0,
                "messages_30d": 0,
                "rank_30d": None,
                "tracked_users": 0,
                "streak_days": 0,
                "average_per_day": 0.0,
                "busiest_weekday": None,
                "activity_level": activity_level(0),
                "tracked_days": 0,
                "membership_days": 0,
                "membership_exact": False,
            }

        messages_7d = int(con.execute("""
            SELECT COALESCE(SUM(message_count), 0)
            FROM profile_daily_activity
            WHERE chat_id=? AND user_id=? AND day>=?
        """, (chat_id, user_id, day_7)).fetchone()[0])

        messages_30d = int(con.execute("""
            SELECT COALESCE(SUM(message_count), 0)
            FROM profile_daily_activity
            WHERE chat_id=? AND user_id=? AND day>=?
        """, (chat_id, user_id, day_30)).fetchone()[0])

        rank_rows = con.execute("""
            SELECT user_id, SUM(message_count) AS total
            FROM profile_daily_activity
            WHERE chat_id=? AND day>=?
            GROUP BY user_id
            HAVING total > 0
            ORDER BY total DESC, user_id ASC
        """, (chat_id, day_30)).fetchall()

        rank_30d = None
        for index, rank_row in enumerate(rank_rows, 1):
            if int(rank_row["user_id"]) == user_id:
                rank_30d = index
                break

        tracked_users = int(con.execute("""
            SELECT COUNT(*)
            FROM profile_chat_activity
            WHERE chat_id=?
        """, (chat_id,)).fetchone()[0])

        active_days_rows = con.execute("""
            SELECT day
            FROM profile_daily_activity
            WHERE chat_id=? AND user_id=? AND message_count>0
            ORDER BY day DESC
        """, (chat_id, user_id)).fetchall()
        active_days = [r["day"] for r in active_days_rows]

        weekday_rows = con.execute("""
            SELECT day, message_count
            FROM profile_daily_activity
            WHERE chat_id=? AND user_id=? AND message_count>0
        """, (chat_id, user_id)).fetchall()

    first_seen = _parse_dt(row["first_seen_at"])
    joined_at = _parse_dt(row["joined_at"])
    membership_start = joined_at or first_seen

    tracked_days = 0
    membership_days = 0
    if first_seen:
        tracked_days = max(0, (today - first_seen.date()).days)
    if membership_start:
        membership_days = max(0, (today - membership_start.date()).days)

    average_per_day = (
        int(row["message_count"]) / max(1, tracked_days + 1)
        if first_seen
        else 0.0
    )

    weekdays = [0] * 7
    for weekday_row in weekday_rows:
        try:
            day_obj = datetime.fromisoformat(weekday_row["day"]).date()
            weekdays[day_obj.weekday()] += int(weekday_row["message_count"])
        except Exception:
            pass

    weekday_names = [
        "понедельник",
        "вторник",
        "среда",
        "четверг",
        "пятница",
        "суббота",
        "воскресенье",
    ]
    busiest_weekday = None
    if any(weekdays):
        busiest_weekday = weekday_names[max(range(7), key=lambda i: weekdays[i])]

    return {
        "chat_id": chat_id,
        "user_id": user_id,
        "first_seen_at": row["first_seen_at"],
        "joined_at": row["joined_at"],
        "last_seen_at": row["last_seen_at"],
        "message_count": int(row["message_count"]),
        "messages_7d": messages_7d,
        "messages_30d": messages_30d,
        "rank_30d": rank_30d,
        "tracked_users": tracked_users,
        "streak_days": _consecutive_activity_days(active_days),
        "average_per_day": average_per_day,
        "busiest_weekday": busiest_weekday,
        "activity_level": activity_level(messages_30d),
        "tracked_days": tracked_days,
        "membership_days": membership_days,
        "membership_exact": bool(joined_at),
    }


def get_extended_profile_stats(chat_id: int, user_id: int):
    activity = get_chat_activity(chat_id, user_id)

    with connect() as con:
        rp_total_row = con.execute("""
            SELECT COALESCE(SUM(count), 0) AS total
            FROM action_stats
            WHERE chat_id=? AND actor_id=?
        """, (chat_id, user_id)).fetchone()
        rp_total = int(rp_total_row["total"]) if rp_total_row else 0

        favorite_row = con.execute("""
            SELECT action, SUM(count) AS total
            FROM action_stats
            WHERE chat_id=? AND actor_id=?
            GROUP BY action
            ORDER BY total DESC, action ASC
            LIMIT 1
        """, (chat_id, user_id)).fetchone()

        total_closeness_row = con.execute("""
            SELECT COALESCE(SUM(closeness), 0) AS total
            FROM pair_stats
            WHERE chat_id=? AND (user1_id=? OR user2_id=?)
        """, (chat_id, user_id, user_id)).fetchone()
        total_closeness = int(total_closeness_row["total"]) if total_closeness_row else 0

        partner_row = con.execute("""
            SELECT
                CASE WHEN user1_id=? THEN user2_id ELSE user1_id END AS partner_id,
                closeness,
                total_actions
            FROM pair_stats
            WHERE chat_id=? AND (user1_id=? OR user2_id=?)
            ORDER BY closeness DESC, total_actions DESC
            LIMIT 1
        """, (user_id, chat_id, user_id, user_id)).fetchone()

        rp_partners_row = con.execute("""
            SELECT COUNT(*) AS c
            FROM pair_stats
            WHERE chat_id=? AND (user1_id=? OR user2_id=?)
        """, (chat_id, user_id, user_id)).fetchone()
        rp_partners = int(rp_partners_row["c"]) if rp_partners_row else 0

        wallet_row = con.execute("""
            SELECT balance, total_earned, giveaways_claimed, biggest_claim
            FROM honey_wallets
            WHERE user_id=?
        """, (user_id,)).fetchone()

        farm_row = con.execute("""
            SELECT level
            FROM honey_farms
            WHERE user_id=?
        """, (user_id,)).fetchone()

        gifts_sent_row = con.execute("""
            SELECT COUNT(*) AS c
            FROM gift_history
            WHERE giver_id=?
        """, (user_id,)).fetchone()

        gifts_received_row = con.execute("""
            SELECT COUNT(*) AS c
            FROM gift_history
            WHERE recipient_id=?
        """, (user_id,)).fetchone()

        marriage_row = con.execute("""
            SELECT *
            FROM marriages
            WHERE active=1 AND (user1_id=? OR user2_id=?)
            ORDER BY id DESC
            LIMIT 1
        """, (user_id, user_id)).fetchone()

        closest_partner = None
        if partner_row:
            partner_id = int(partner_row["partner_id"])
            user_row = con.execute(
                "SELECT name FROM users WHERE user_id=?",
                (partner_id,),
            ).fetchone()
            closest_partner = {
                "user_id": partner_id,
                "name": user_row["name"] if user_row else "Пользователь",
                "closeness": int(partner_row["closeness"]),
                "total_actions": int(partner_row["total_actions"]),
            }

        marriage = None
        if marriage_row:
            partner_id = (
                int(marriage_row["user2_id"])
                if int(marriage_row["user1_id"]) == user_id
                else int(marriage_row["user1_id"])
            )
            partner_user = con.execute(
                "SELECT name FROM users WHERE user_id=?",
                (partner_id,),
            ).fetchone()
            marriage = {
                "partner_id": partner_id,
                "partner_name": partner_user["name"] if partner_user else "Пользователь",
                "started_at": marriage_row["started_at"],
                "health": float(marriage_row["health"]),
            }

    favorite_action = None
    if favorite_row:
        action_key = favorite_row["action"]
        action_data = ACTIONS.get(action_key)
        favorite_action = {
            "key": action_key,
            "title": (
                action_data["title"]
                if action_data
                else str(action_key).replace("_", " ").title()
            ),
            "count": int(favorite_row["total"]),
        }

    wallet = {
        "balance": int(wallet_row["balance"]) if wallet_row else 0,
        "total_earned": int(wallet_row["total_earned"]) if wallet_row else 0,
        "giveaways_claimed": int(wallet_row["giveaways_claimed"]) if wallet_row else 0,
        "biggest_claim": int(wallet_row["biggest_claim"]) if wallet_row else 0,
    }

    gifts_sent = int(gifts_sent_row["c"]) if gifts_sent_row else 0
    gifts_received = int(gifts_received_row["c"]) if gifts_received_row else 0
    farm_level = int(farm_row["level"]) if farm_row else None

    marriage_days = 0
    if marriage and marriage.get("started_at"):
        try:
            marriage_start = datetime.fromisoformat(marriage["started_at"])
            marriage_days = max(0, (bot_now().date() - marriage_start.date()).days)
        except Exception:
            pass

    achievements = []
    if activity["membership_days"] >= 90:
        achievements.append("🥇 Старожил")
    if activity["message_count"] >= 500:
        achievements.append("💬 Болтун")
    if activity["rank_30d"] == 1 and activity["messages_30d"] >= 50:
        achievements.append("💕 Душа компании")
    if rp_total >= 100:
        achievements.append("🌹 Романтик")
    if wallet["total_earned"] >= 1000:
        achievements.append("🍯 Медовый магнат")
    if gifts_sent >= 10:
        achievements.append("🎁 Щедрая душа")
    if marriage and marriage_days >= 30:
        achievements.append("💍 Крепкая пара")

    return {
        "activity": activity,
        "rp": {
            "total_actions": rp_total,
            "total_closeness": total_closeness,
            "partners": rp_partners,
            "favorite_action": favorite_action,
            "closest_partner": closest_partner,
        },
        "honey": wallet,
        "farm_level": farm_level,
        "gifts": {
            "sent": gifts_sent,
            "received": gifts_received,
        },
        "marriage": marriage,
        "marriage_days": marriage_days,
        "achievements": achievements,
    }


def profile_view_keyboard(
    user_id: int,
    filled: bool,
    chat_id: int | None = None,
    is_owner: bool = True,
):
    rows = []

    if chat_id is not None:
        rows.append([
            InlineKeyboardButton(
                text="📊 Подробнее",
                callback_data=f"profile:stats:{user_id}:{chat_id}",
            )
        ])

    if is_owner:
        text = "✏️ Редактировать анкету" if filled else "✏️ Заполнить анкету"
        rows.append([
            InlineKeyboardButton(
                text=text,
                callback_data=f"profile:edit:{user_id}",
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def profile_stats_keyboard(user_id: int, chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="👤 К анкете",
            callback_data=f"profile:back:{user_id}:{chat_id}",
        )
    ]])


def profile_edit_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🏷 Имя / ник",
                callback_data=f"profile:field:display_name:{user_id}",
            ),
            InlineKeyboardButton(
                text="🎂 Возраст",
                callback_data=f"profile:field:age:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🏙 Город",
                callback_data=f"profile:field:city:{user_id}",
            ),
            InlineKeyboardButton(
                text="⚧ Пол",
                callback_data=f"profile:field:gender:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📝 О себе",
                callback_data=f"profile:field:bio:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="✅ Готово",
                callback_data=f"profile:done:{user_id}",
            ),
        ],
    ])


def gender_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="♂️ Мужской",
                callback_data=f"profile:gender:Мужской:{user_id}",
            ),
            InlineKeyboardButton(
                text="♀️ Женский",
                callback_data=f"profile:gender:Женский:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="⚧ Другое",
                callback_data=f"profile:gender:Другое:{user_id}",
            ),
            InlineKeyboardButton(
                text="➖ Не указывать",
                callback_data=f"profile:gender:clear:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"profile:cancel:{user_id}",
            ),
        ],
    ])


def profile_cancel_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=f"profile:cancel:{user_id}",
        )
    ]])
