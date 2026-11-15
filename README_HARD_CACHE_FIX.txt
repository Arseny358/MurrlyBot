MurrlyBot Economy v2 — жёсткий фикс старого Telegram WebView-кэша

Проблема:
backend уже обновлён (новые уровни фермы видны), но Telegram показывает старый frontend с 4 вкладками.

Что делает этот фикс:
- не использует старые index.html / app.js / style.css;
- добавляет новый URL /economy-v2;
- использует уникальные файлы:
  app-economy-v2.js
  style-economy-v2.css
  index-economy-v2.html
- отключает HTTP-кэш для новой оболочки.

Загрузить в GitHub:
1. В корень заменить miniapp_server.py
2. В miniapp_static ДОБАВИТЬ:
   - index-economy-v2.html
   - app-economy-v2.js
   - style-economy-v2.css

Старые index.html/app.js/style.css удалять не нужно.

После commit:
1. Bothost -> новый deploy/rebuild.
2. Проверить:
   https://ТВОЙ-ДОМЕН/health
   должно быть economy_update: 2

3. В обычном браузере открыть:
   https://ТВОЙ-ДОМЕН/economy-v2

   В браузере без Telegram initData приложение покажет сообщение
   "Открой Mini App через Telegram" — это нормально. Главное, что URL отвечает.

4. В BotFather поменять URL Main Mini App на:
   https://ТВОЙ-ДОМЕН/economy-v2?build=20261115-2

5. Если настроен Menu Button, его URL поменять на тот же:
   https://ТВОЙ-ДОМЕН/economy-v2?build=20261115-2

6. Полностью закрыть Mini App крестиком и открыть снова.

Ожидаемый frontend:
🏠 Главная | 🐝 Ферма | 🎁 Магазин | 📈 Биржа | 👤 Профиль

В магазине должна появиться продажа подарков.
На ферме — улучшения, буст, события, золотой мёд и задания.
