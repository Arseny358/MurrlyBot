import asyncio
import os

import uvicorn
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import main as bot_main
from miniapp_server import app, set_bot_instance


GROUP_APP_ALIASES = {
    "приложение",
    "мини приложение",
    "миниапп",
    "mini app",
    "app",
    "/app",
    "/приложение",
}


def _normalize_app_command(text: str) -> str:
    value = " ".join(
        (text or "")
        .strip()
        .lower()
        .replace("ё", "е")
        .split()
    )
    # Поддержка /app@MurrlyBot в группах.
    return value.split("@", 1)[0]


async def miniapp_group_middleware(handler, event, data):
    """
    Перехватывает команду запуска Mini App в группах раньше общего F.text-handler.
    В личке ничего не меняет: там остаётся штатная Menu Button Telegram.
    """
    if (
        isinstance(event, Message)
        and event.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}
        and event.text
        and _normalize_app_command(event.text) in GROUP_APP_ALIASES
    ):
        if event.from_user:
            # Не теряем обычную статистику активности из-за раннего перехвата.
            try:
                bot_main.upsert_user(event.from_user.id, event.from_user.full_name)
                await bot_main.remember_group_chat(event)
                bot_main.record_chat_message(event.chat.id, event.from_user.id)
            except Exception as exc:
                print(f"Mini App group activity tracking failed: {exc}")

        me = await event.bot.get_me()
        if not me.username:
            await event.answer(
                "⚠️ У бота не настроен username, поэтому Mini App пока нельзя открыть по ссылке."
            )
            return

        # Main Mini App direct link.
        app_url = f"https://t.me/{me.username}?startapp=group"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="🍯 Открыть MurrlyBot",
                    url=app_url,
                )
            ]]
        )

        await event.answer(
            "🐝 <b>MurrlyBot Mini App</b>\n\n"
            "🍯 Управляй медовой фермой\n"
            "🎁 Покупай подарки\n"
            "👑 Проверяй VIP\n"
            "👤 Смотри профиль и правила\n\n"
            "Нажми кнопку ниже, чтобы открыть приложение.",
            reply_markup=keyboard,
        )
        return

    return await handler(event, data)


# Регистрируем перехват до запуска polling.
bot_main.dp.message.outer_middleware(miniapp_group_middleware)


@bot_main.bot.session.middleware()
async def telegram_network_retry_middleware(make_request, current_bot, method):
    """
    Не даёт временному сетевому таймауту Telegram уронить весь MurrlyBot.

    Aiogram оборачивает aiohttp/asyncio timeout в TelegramNetworkError.
    При такой ошибке повторяем тот же запрос с увеличивающейся задержкой.
    Это особенно важно на старте polling, когда Dispatcher вызывает getMe().
    """
    attempt = 0

    while True:
        try:
            return await make_request(current_bot, method)
        except TelegramNetworkError as exc:
            attempt += 1
            delay = min(30, 3 * attempt)

            print(
                "Telegram network error: "
                f"method={method.__class__.__name__}, "
                f"attempt={attempt}, retry_in={delay}s, error={exc}"
            )

            await asyncio.sleep(delay)


async def run():
    # Передаём Mini App тот же объект бота — он нужен, например,
    # для ручного запуска раздачи из защищённой админ-панели.
    set_bot_instance(bot_main.bot)

    # Запускаем обычный MurrlyBot.
    # Временные сетевые таймауты Telegram теперь перехватываются
    # telegram_network_retry_middleware и не завершают эту задачу.
    bot_task = asyncio.create_task(bot_main.main())

    # Инициализация таблиц в main.py занимает доли секунды.
    await asyncio.sleep(1.0)

    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    web_task = asyncio.create_task(server.serve())

    print(f"MurrlyBot Mini App server starting on 0.0.0.0:{port}")

    done, pending = await asyncio.wait(
        {bot_task, web_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Если одна из основных частей реально завершилась, корректно завершаем вторую,
    # чтобы Bothost мог перезапустить весь контейнер.
    server.should_exit = True
    for task in pending:
        task.cancel()

    for task in done:
        exc = task.exception()
        if exc:
            raise exc


if __name__ == "__main__":
    asyncio.run(run())
