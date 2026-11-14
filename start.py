import asyncio
import os

import uvicorn

import main as bot_main
from miniapp_server import app, set_bot_instance


async def run():
    # Передаём Mini App тот же объект бота — он нужен, например,
    # для ручного запуска раздачи из защищённой админ-панели.
    set_bot_instance(bot_main.bot)

    # Сначала запускаем обычный MurrlyBot.
    bot_task = asyncio.create_task(bot_main.main())

    # Инициализация таблиц в main.py занимает доли секунды.
    # Небольшая задержка не даёт веб-интерфейсу принять запрос раньше БД.
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

    # Если одна часть завершилась — корректно завершаем вторую,
    # чтобы Bothost мог перезапустить весь контейнер целиком.
    server.should_exit = True
    for task in pending:
        task.cancel()

    for task in done:
        exc = task.exception()
        if exc:
            raise exc


if __name__ == "__main__":
    asyncio.run(run())
