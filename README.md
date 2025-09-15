# Agromat IT Desk Bot

Agromat IT Desk Bot — невеликий сервіс на FastAPI, який приймає вебхуки з YouTrack і пересилає короткі оновлення про задачі у вказаний чат Telegram.

## Що всередині
- Ендпоінт FastAPI `/youtrack` приймає події з YouTrack, дістає ID/заголовок/опис/URL і формує повідомлення.
- Відправка у Telegram через Bot API з HTML-екрануванням контенту.
- workflow для YouTrack (`webhooks/yt2tg_webhook.js`) — шле дані при створенні задачі; у разі відсутнього `idReadable` обчислює його з `project.shortName|name` та `numberInProject` або бере `id`.

## Вимоги
- Python 3.10+
- Токен Telegram-бота і ID цільового чату
- Публічний URL для вебхуків (*наприклад, через ngrok*)

## Встановлення
1) Клонувати репозиторій
    ```bash
    git clone <repository-url>
    cd agromat-it-desk-bot
    ```

2) Створити та активувати віртуальне середовище
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```

3) Встановити залежності
    ```bash
    pip install -r requirements.txt
    ```

4) Налаштувати змінні середовища (`.env`)
    Скопіювати `.env.example` у `.env` та задати значення:
    ```env
    BOT_TOKEN=<токен-бота-telegram>
    TELEGRAM_CHAT_ID=<id-чату-telegram>
    YT_BASE_URL=<базова-адреса-youtrack>
    DESCRIPTION_MAX_LEN=<number>
    ```
    - `YT_BASE_URL` використовується для побудови посилання, якщо `url` не прийшов у payload.
    - `DESCRIPTION_MAX_LEN` — максимальна довжина опису у повідомленні (надлишок обрізається та додається «…»).

## Запуск
```bash
uvicorn agromat_it_desk_bot.main:app --host 0.0.0.0 --port 8000
```

## Доступ ззовні (ngrok)
1) Встановити ngrok і увійти в акаунт
2) Запустити тунель
    ```bash
    ngrok http 8000
    ```
3) Використати виданий HTTPS-адрес як базовий URL для workflow

## Налаштування workflow в YouTrack
1) Administration → Workflows → додати кастомний workflow
2) Взяти код із `webhooks/yt2tg_webhook.js`
3) Замінити `WEBHOOK_URL` на ваш публічний базовий URL (без шляху `/youtrack`)
4) Зберегти та увімкнути workflow

## Безпека
Ендпоінт `/youtrack` відкритий публічно. Для продакшена рекомендується додати перевірку підпису або shared secret у заголовках запиту й перевіряти його на бекенді.
