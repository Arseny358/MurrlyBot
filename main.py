import os
import random
import asyncio
import html

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not found")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

RP_ACTIONS = {
    "обнять": [
        "🫂 {actor} крепко обнял {target}.",
        "💛 {actor} подошёл поближе и тепло обнял {target}.",
    ],
    "поцеловать": [
        "💋 {actor} нежно поцеловал {target}.",
        "💕 {actor} приблизился и чмокнул {target}.",
    ],
    "погладить": [
        "🐾 {actor} аккуратно погладил {target}.",
        "✨ {actor} ласково погладил {target}.",
    ],
    "укусить": [
        "😼 {actor} игриво укусил {target}.",
        "😈 {actor} слегка прикусил {target}.",
    ],
    "лизнуть": [
        "😛 {actor} игриво лизнул {target}.",
        "🐱 {actor} неожиданно лизнул {target}.",
    ],
    "потискать": [
        "💕 {actor} принялся тискать {target}.",
        "🐾 {actor} крепко затискал {target}.",
    ],
    "прижаться": [
        "💞 {actor} уютно прижался к {target}.",
        "💗 {actor} тихонько прижался к {target}.",
    ],
}

def mention(user):
    name = html.escape(user.full_name or "Пользователь")
    return f'<a href="tg://user?id={user.id}">{name}</a>'

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🐝 <b>MurrlyBot запущен!</b>\n\n"
        "Ответь на сообщение участника одной из RP-команд.\n"
        "Например: <code>обнять</code> или <code>поцеловать</code>."
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    actions = "\n".join(f"• <code>{x}</code>" for x in RP_ACTIONS)
    await message.answer(
        "🐝 <b>RP-команды:</b>\n\n"
        + actions
        + "\n\nКоманду нужно отправлять <b>ответом на сообщение</b> участника."
    )

@dp.message(F.text)
async def rp_handler(message: Message):
    text = (message.text or "").strip().lower()

    if text.startswith("/") or text not in RP_ACTIONS:
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("🐝 Ответь этой командой на сообщение нужного участника.")
        return

    actor = message.from_user
    target = message.reply_to_message.from_user

    if actor.id == target.id:
        await message.reply("🐝 Мря?.. С самим собой так не получится :3")
        return

    if target.is_bot:
        await message.reply("🐝 С ботами RP-взаимодействия пока не работают.")
        return

    phrase = random.choice(RP_ACTIONS[text]).format(
        actor=mention(actor),
        target=mention(target),
    )
    await message.answer(phrase)

async def main():
    print("MurrlyBot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
