# Agromat IT Desk Bot

**Agromat IT Desk Bot** – це сервіс на **FastAPI** з інтегрованим **Aiogram v3**, який приймає вебхуки з **YouTrack**, трансформує їх у компактні повідомлення та публікує у **Telegram**. Інженер підтримки може натиснути кнопку «Прийняти», щоб призначити задачу на себе, а бот автоматично оновить статус у **YouTrack**.


## Можливості
- Прийом вебхуків **YouTrack** (`POST /youtrack`) і побудова HTML-повідомлень з ID, заголовком, описом та посиланням.
- Відправлення повідомлень у **Telegram** з інлайновою кнопкою «Прийняти».
- Обробка оновлень **Telegram** (повідомлення + callback) через Aiogram роутер, делегування існуючій бізнес-логіці та перевірка прав користувачів.
- Призначення задачі у **YouTrack** та опційне автоматичне оновлення стану через REST API.
- Опціональне автоматичне оновлення статусу задачі (*наприклад, на «В роботі»*).
- Гнучке логування ключових дій для спостереження та діагностики.


## Вимоги
- Python 3.10+
- Токен Telegram-бота з доступом до Bot API
- YouTrack (Cloud або On-Premise) з API токеном і правами на призначення задач
- Публічний HTTPS-URL для прийому вебхуків (наприклад, через ngrok)


## Швидкий старт
1. **Клонувати репозиторій**
   ```bash
   git clone <repository-url>
   cd agromat-it-desk-bot
   ```
2. **Створити середовище та встановити залежності**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Сконфігурувати середовище**
   ```bash
   cp .env.example .env
   ```
   Заповнити `.env` значеннями (див. [Налаштування](#налаштування)).
4. **Підняти API**
   ```bash
   uvicorn agromat_it_desk_bot.main:app --host 0.0.0.0 --port 8080
   ```
5. **Налаштувати публічний доступ** (для локальної розробки)
   ```bash
   ngrok http 8080
   ```
6. **Реєструвати вебхук бота Telegram**
   ```bash
   curl -X POST "https://api.telegram.org/bot$BOT_TOKEN/setWebhook" \
        -d "url=https://<public-domain>/telegram" \
        -d "secret_token=$TELEGRAM_WEBHOOK_SECRET" \
        -d "allowed_updates[]=message" \
        -d "allowed_updates[]=callback_query"
   ```
7. **Налаштувати YouTrack workflow** (див. нижче).


## Налаштування

### Змінні середовища
Файл `.env.example` містить повний перелік. Основні ключі:

| Змінна | Призначення |
| --- | --- |
| `BOT_TOKEN` | Токен **Telegram-бота** (використовується для Aiogram Dispatcher) |
| `TELEGRAM_CHAT_ID` | ID чату, куди надсилати повідомлення |
| `TELEGRAM_WEBHOOK_SECRET` | Секретний токен для перевірки вебхука (*рекомендовано*) |
| `ALLOWED_TG_USER_IDS` | Список дозволених **Telegram user ID** через кому |
| `YT_BASE_URL` | Базовий **URL YouTrack** без `/api` |
| `YT_TOKEN` | Персональний токен **YouTrack** |
| `DESCRIPTION_MAX_LEN` | Максимальна довжина опису в **Telegram** |
| `USER_MAP_PATH` | Шлях до **JSON-файла** з мапою користувачів |
| `YOUTRACK_ASSIGNEE_FIELD_NAME` | Назва поля виконавця (*наприклад, «Виконавець»*) |

> Якщо `TELEGRAM_WEBHOOK_SECRET` не вказано, перевірка секрету вимикається. Для продакшен середовища краще залишити її увімкненою.

### Мапа користувачів
`user_map.json.example` демонструє кілька форматів записів:
```json
{
  "<telegram_id>": {"id": "1-23", "login": "petro.ivanov", "email": "petro.ivanov@example.com"},
  "<telegram_id>": {"login": "olena.sydorenko", "email": "olena.sydorenko@example.com"},
  "<telegram_id>": "support.engineer"
}
```
- `id` — внутрішній ID користувача **YouTrack** (*дозволяє пропустити пошук*).
- `login` / `email` — використовуються для пошуку користувача, якщо `id` не задано.
- Строкове значення (`"support.engineer"`) інтерпретується як логін.

Користувачі можуть додавати себе в мапу напряму з Telegram, надіславши `/register <логін>`. Бот автоматично знайде відповідний обліковий запис у YouTrack і збереже `login`, `email` та `id` у `user_map.json`. Логін та YouTrack ID мають бути унікальними — якщо вони вже привʼязані до іншого Telegram ID, реєстрацію буде відхилено. Для зміни логіна спершу виконайте `/register <новий_логін>`, після чого бот попросить підтвердити дію командою `/confirm_login <новий_логін>`.

### YouTrack workflow
У каталозі `webhooks/` є `yt2tg-webhook-app.zip` для інтеграції:

- У **Administration → Apps → Add app → Upload ZIP file** завантажити `yt2tg-webhook-app.zip`. Далі в налаштуваннях додатку заповнити `Basic Backend URL` (адреса сервера без суфіксу `/youtrack`) та `Secret for Authorization`, а у вкладці **Projects** додати свій проєкт. Пакет містить:
   - `yt2tg_webhook.js` — відправляє дані про створені задачі на ваш бекенд (для авторизації використовує `WEBHOOK_SECRET`).
   - `yt_assignee_status_sync.js` — ставить «В роботі», коли призначають виконавця, і навпаки (ігнорує сервісні акаунти).

## Архітектура
- `agromat_it_desk_bot/main.py` — **FastAPI** додаток з ендпоінтами `/youtrack` і `/telegram`, логікою форматування повідомлень, призначення та оновлення стану.
- `agromat_it_desk_bot/config.py` — зчитування змінних середовища з `.env` з типами.
- `webhooks/yt2tg_webhook.js` — приклад **workflow** для **YouTrack**.
- `user_map.json` — відповідності **Telegram ID** → обліковки **YouTrack**.

### Послідовність подій
1. **YouTrack** надсилає вебхук на `/youtrack`.
2. Сервіс формує **HTML-повідомлення** з кнопкою «Прийняти» та шле його в **Telegram**.
3. Користувач натискає кнопку → **Telegram** викликає `/telegram`.
4. Сервіс перевіряє секрет, доступ користувача, знаходить відповідника в `user_map.json`.
5. Через **REST API** призначає задачу та (*опційно*) оновлює стан.
6. Бот прибирає клавіатуру й відповідає користувачеві в **Telegram**.


## Логування
У `main.py` використовується `logger = logging.getLogger(__name__)`. Журнал містить:
- прийом вебхуків (`info`/`debug`),
- надсилання повідомлень (`info`),
- призначення задачі та оновлення стану (`info`),
- помилки REST/HTTP (`error`/`exception`).

Налаштувати рівень виводу можна у `logging.basicConfig(...)` або у власному застосунку/конфігураційному файлі.


## Налаштування вебхука Telegram
- **Перевірити поточний стан**
  ```bash
  curl "https://api.telegram.org/bot$BOT_TOKEN/getWebhookInfo"
  ```
- **Зареєструвати вебхук**
  ```bash
  curl -X POST "https://api.telegram.org/bot$BOT_TOKEN/setWebhook" \
       -d "url=https://<public-domain>/telegram" \
       -d "secret_token=$TELEGRAM_WEBHOOK_SECRET" \
  ```
- **Очистити чергу** (*наприклад, після зміни домену*)
  ```bash
  curl "https://api.telegram.org/bot$BOT_TOKEN/deleteWebhook?drop_pending_updates=true"
  ```


## Тестування локально
- **YouTrack → Telegram**
  ```bash
  curl -X POST http://localhost:8080/youtrack \
       -H 'Content-Type: application/json' \
       -d '{"idReadable":"ID-1","summary":"Саппорт","description":"Опис","url":"https://youtrack/issue/ID-1"}'
  ```
- **Telegram webhook без секрету**
  ```bash
  curl -X POST http://localhost:8080/telegram \
       -H 'Content-Type: application/json' \
       -d '{"callback_query":{"id":"cb1","from":{"id":123456789},"message":{"message_id":1,"chat":{"id":-100}},"data":"accept|ID-1"}}'
  ```
- **Telegram webhook із секретом** — додайте заголовок `X-Telegram-Bot-Api-Secret-Token: $TELEGRAM_WEBHOOK_SECRET`.


## Усунення несправностей
| Симптом | Дії |
| --- | --- |
| `/telegram` повертає 403 | Перевірити `TELEGRAM_WEBHOOK_SECRET` у `.env` та при `setWebhook`. |
| Натискання «Прийняти» нічого не дає | Переконатися, що вебхук **Telegram** вказує на `/telegram` і сервіс працює. |
| «Не вдалося визначити ID користувача» | Надіслати `/register <логін>` у бот або вручну додати запис у `user_map.json`. |
| «Не знайдено читабельного ID» | Перевірити workflow: має передавати `idReadable` або `project.shortName` + `numberInProject`. |


## Troubleshooting
- **Server refuses to bind on 127.0.0.1:*** Перевірте, що порт не зайнятий, та спробуйте `--port 0` або інший порт. У середовищах із sandbox-політикою мережа може бути недоступною – сервер все одно проходить фазу ініціалізації, що видно з логів `Application startup complete`.
- **`ModuleNotFoundError: uvicorn/pytest/mypy`**: Обовʼязково активуйте локальне середовище `source .venv/bin/activate`. У цьому віртуальному середовищі вже встановлено залежності, тож додаткові інсталяції не потрібні.
- **`asyncio` тести падають із повідомленням про відсутність плагіну**: Використовуйте синхронний виклик через `asyncio.run(...)`, як показано в `tests/test_telegram_aiogram.py`, або додайте `pytest-asyncio` у середовище.
- **Валідація токена YouTrack повертає тимчасову помилку**: лог містить запис `YouTrack тимчасово недоступний`. Перевірте мережевий доступ до `YT_BASE_URL` та повторіть запит пізніше; сервіс автоматично робить до трьох спроб із backoff.
- **Mypy скаржиться на відсутність типів для `requests`**: у проєкті використано `# type: ignore[import-untyped]` для бібліотеки `requests`. Якщо запускаєте mypy поза репозиторієм – встановіть `types-requests` або використовуйте наданий `.venv`.


## Структура проєкту (з ключовими модулями)
```
agromat_it_desk_bot/
├─ main.py             # FastAPI застосунок, вебхуки /youtrack та /telegram
├─ callback_handlers.py# Призначення задач (кнопка «Прийняти»)
├─ telegram/
│  ├─ __init__.py
│  ├─ telegram_aiogram.py # Router/Dispatcher Aiogram, обробка message + callback
│  ├─ telegram_commands.py # Бізнес-логіка команд /register та /confirm_login
│  └─ telegram_service.py # Синхронні виклики Telegram Bot API
├─ youtrack/
│  ├─ __init__.py
│  ├─ youtrack_client.py # Низькорівневий клієнт YouTrack REST API
│  └─ youtrack_service.py # Логіка призначення задач та зміни стану
├─ utils.py            # Допоміжні функції, user_map, YouTrack форматування
└─ ...
webhooks/
├─ yt2tg_webhook.js           # приклад workflow для YouTrack
└─ yt2tg-webhook-app.zip      # готовий YouTrack app (вебхук + синхронізація статусу/виконавця)
.env.example           # приклад налаштування середовища
user_map.json.example  # приклади відповідностей TG → YouTrack
requirements.txt       # перелік залежностей
```

## Тестування та перевірки
Перед релізом рекомендується запускати повний цикл перевірок:
```bash
source .venv/bin/activate
python -m pytest -q
ruff check .
mypy .
python -m compileall -q .
```
Ці команди також інтегровані у CI-підхід проєкту, тому локальний запуск допомагає швидко виявити проблеми.
