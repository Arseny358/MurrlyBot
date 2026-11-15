MurrlyBot Mini App cache hotfix

Заменить:
- miniapp_server.py
- miniapp_static/index.html

После commit сделать новый deploy/rebuild на Bothost.

Проверка:
1. /health должен содержать "economy_update":2
2. Полностью закрыть Mini App крестиком.
3. Открыть заново.
4. Внизу должно быть 5 вкладок, включая 📈 Биржа.

Hotfix:
- добавляет версию к app.js/style.css;
- отключает HTTP-кэш для оболочки Mini App и статических файлов.
