import os
import random
import asyncio
import html
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message

from rp_actions import ACTIONS, ALIASES
from database import (
    init_db,
    upsert_user,
    record_action,
    get_pair,
    get_user,
    get_user_action_count,
    top_pairs,
    top_actions_between,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не найдена.")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Короткий антиспам только для RP-действий.
COOLDOWN_SECONDS = 2.0
last_action_time = {}


def normalize(text: str) -> str:
    return " ".join(
        (text or "")
        .strip()
        .lower()
        .replace("ё", "е")
        .split()
    )


# Дополнительно нормализуем алиасы с ё/е.
NORMALIZED_ALIASES = {normalize(alias): key for alias, key in ALIASES.items()}


def mention(user) -> str:
    name = html.escape(user.full_name or "Пользователь")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def mention_by_id(user_id: int, name: str | None) -> str:
    safe = html.escape(name or "Пользователь")
    return f'<a href="tg://user?id={user_id}">{safe}</a>'


def relationship_level(points: int) -> str:
    if points < 10:
        return "🌱 Незнакомцы"
    if points < 30:
        return "🙂 Знакомые"
    if points < 80:
        return "🤝 Друзья"
    if points < 150:
        return "💛 Близкие"
    if points < 300:
        return "💞 Очень близкие"
    if points < 600:
        return "💖 Неразлучные"
    return "✨ Особая связь"


def action_list_text() -> str:
    rows = []
    for data in ACTIONS.values():
        rows.append(f"• <code>{html.escape(data['aliases'][0])}</code> — {data['title']}")
    return "\n".join(rows)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    upsert_user(message.from_user.id, message.from_user.full_name)
    await message.answer(
        "🐝 <b>MurrlyBot работает!</b>\n\n"
        "Это RP-бот для групповых чатов.\n"
        "Чтобы выполнить действие, <b>ответь на сообщение участника</b> "
        "и напиши действие обычным сообщением.\n\n"
        "Например: <code>обнять</code>, <code>поцеловать</code>, "
        "<code>погладить</code>.\n\n"
        "📖 <code>рп команды</code> — все действия\n"
        "💕 <code>отношения</code> — ответом на сообщение человека\n"
        "👤 <code>рп профиль</code> — твоя статистика\n"
        "🏆 <code>рп топ</code> — пары чата"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await cmd_start(message)


@dp.message(F.text)
async def text_handler(message: Message):
    if not message.from_user:
        return

    raw = message.text or ""
    text = normalize(raw)

    # Второй формат RP-команд:
    # 1-я строка — сама RP-команда.
    # 2-я и последующие строки — дополнительная реплика/описание.
    raw_lines = [line.strip() for line in raw.splitlines() if line.strip()]
    rp_command_text = normalize(raw_lines[0]) if raw_lines else ""
    rp_extra_text = "\n".join(raw_lines[1:]).strip() if len(raw_lines) > 1 else ""

    if text.startswith("/"):
        return

    upsert_user(message.from_user.id, message.from_user.full_name)

    # Список команд
    if text in {"рп", "рп команды", "rp", "rp команды", "рп помощь"}:
        await message.answer(
            "🐝 <b>RP-команды MurrlyBot</b>\n\n"
            + action_list_text()
            + "\n\n"
            "💡 Любое действие отправляется <b>ответом на сообщение</b> участника.\n"
            "💕 <code>отношения</code> — статистика конкретной пары.\n"
            "👤 <code>рп профиль</code> — личная статистика.\n"
            "🏆 <code>рп топ</code> — самые близкие пары чата."
        )
        return

    # Профиль
    if text in {"рп профиль", "rp профиль", "рп профиль мой", "профиль рп"}:
        user = get_user(message.from_user.id)
        chat_actions = get_user_action_count(message.chat.id, message.from_user.id)
        total = user["total_actions"] if user else 0
        await message.answer(
            f"👤 <b>RP-профиль {mention(message.from_user)}</b>\n\n"
            f"🎭 Действий в этом чате: <b>{chat_actions}</b>\n"
            f"🌍 Всего действий: <b>{total}</b>"
        )
        return

    # Отношения пары
    if text in {"отношения", "наши отношения", "рп отношения"}:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.reply("💕 Отправь <code>отношения</code> ответом на сообщение нужного человека.")
            return

        target = message.reply_to_message.from_user
        if target.id == message.from_user.id:
            await message.reply("🐝 Для отношений нужен другой участник :3")
            return

        upsert_user(target.id, target.full_name)
        pair = get_pair(message.chat.id, message.from_user.id, target.id)
        top = top_actions_between(message.chat.id, message.from_user.id, target.id)

        details = ""
        if top:
            names = {key: data["title"] for key, data in ACTIONS.items()}
            details = "\n\n<b>Чаще всего:</b>\n" + "\n".join(
                f"• {names.get(row['action'], row['action'])}: <b>{row['c']}</b>"
                for row in top
            )

        await message.answer(
            f"💕 <b>{mention(message.from_user)} × {mention(target)}</b>\n\n"
            f"✨ Близость: <b>{pair['closeness']}</b>\n"
            f"🎭 Взаимодействий: <b>{pair['total_actions']}</b>\n"
            f"📈 Уровень: <b>{relationship_level(pair['closeness'])}</b>"
            + details
        )
        return

    # Топ пар чата
    if text in {"рп топ", "rp топ", "топ отношений", "топ пар"}:
        rows = top_pairs(message.chat.id)
        if not rows:
            await message.answer("🏆 В этом чате пока нет RP-статистики.")
            return

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows, 1):
            icon = medals[i - 1] if i <= 3 else f"{i}."
            a = mention_by_id(row["user1_id"], row["name1"])
            b = mention_by_id(row["user2_id"], row["name2"])
            lines.append(
                f"{icon} {a} × {b} — <b>{row['closeness']}</b> ✨"
            )

        await message.answer(
            "🏆 <b>Самые близкие пары чата</b>\n\n" + "\n".join(lines)
        )
        return

    # RP-действия
    # Для двухстрочного формата командой считается только первая строка.
    action_key = NORMALIZED_ALIASES.get(rp_command_text)
    if not action_key:
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply(
            "🐝 Ответь этой RP-командой на сообщение нужного участника."
        )
        return

    actor = message.from_user
    target = message.reply_to_message.from_user

    if actor.id == target.id:
        await message.reply("🐝 Мря?.. С самим собой это действие выполнить нельзя :3")
        return

    if target.is_bot:
        await message.reply("🐝 С ботами RP-взаимодействия пока не работают.")
        return

    now = time.monotonic()
    last = last_action_time.get(actor.id, 0)
    if now - last < COOLDOWN_SECONDS:
        remain = COOLDOWN_SECONDS - (now - last)
        await message.reply(f"⏳ Не так быстро! Подожди ещё {remain:.1f} сек.")
        return
    last_action_time[actor.id] = now

    upsert_user(target.id, target.full_name)

    data = ACTIONS[action_key]
    points = random.randint(*data["points"])
    phrase = random.choice(data["phrases"]).format(
        actor=mention(actor),
        target=mention(target),
    )

    record_action(
        chat_id=message.chat.id,
        actor_id=actor.id,
        target_id=target.id,
        action=action_key,
        points=points,
    )

    pair = get_pair(message.chat.id, actor.id, target.id)

    result_text = phrase

    # Если после команды была вторая строка — выводим её как реплику.
    if rp_extra_text:
        safe_extra = html.escape(rp_extra_text)
        result_text += f'\n💬 С репликой: «{safe_extra}»'

    result_text += (
        f"\n\n<blockquote>✨ +{points} близости · "
        f"Всего: {pair['closeness']}</blockquote>"
    )

    if rp_extra_text:
        # В двухстрочном формате отвечаем на сообщение с командой.
        # Поэтому Telegram сверху показывает цитату команды и второй строки,
        # как в Iris.
        await message.reply(result_text)
    else:
        # Старый однострочный формат оставляем как был.
        await message.answer(result_text)


async def main():
    init_db()
    print("MurrlyBot v2 starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
