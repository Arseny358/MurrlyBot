from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import connect


PROFILE_FIELDS = {
    "display_name": "Имя / ник",
    "age": "Возраст",
    "city": "Город",
    "gender": "Пол",
    "bio": "О себе",
}


def init_profiles_db():
    with connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT,
                age INTEGER,
                city TEXT,
                gender TEXT,
                bio TEXT,
                updated_at TEXT NOT NULL
            )
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


def profile_view_keyboard(user_id: int, filled: bool):
    text = "✏️ Редактировать анкету" if filled else "✏️ Заполнить анкету"

    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=text,
            callback_data=f"profile:edit:{user_id}",
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
