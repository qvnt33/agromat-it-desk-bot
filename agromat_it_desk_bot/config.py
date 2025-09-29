"""Налаштування сервісу: зчитування змінних середовища."""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# Вказують токен бота Telegram (обовʼязково)
BOT_TOKEN: str | None = os.getenv('BOT_TOKEN')

# Вказують ID цільового чату Telegram (обовʼязково)
TELEGRAM_CHAT_ID: str | None = os.getenv('TELEGRAM_CHAT_ID')

# Фіксують базову адресу інстансу YouTrack для формування посилань
YT_BASE_URL: str = os.getenv('YT_BASE_URL', '').rstrip('/')

# Визначають максимальну довжину опису, який надсилають у Telegram
DESCRIPTION_MAX_LEN: int = int(os.getenv('DESCRIPTION_MAX_LEN', '500'))

# Налаштовують секрет для перевірки Telegram вебхука (X-Telegram-Bot-Api-Secret-Token)
TELEGRAM_WEBHOOK_SECRET: str | None = os.getenv('TELEGRAM_WEBHOOK_SECRET')

# Налаштовують секрет для перевірки YouTrack вебхука
YT_WEBHOOK_SECRET: str | None = os.getenv('YT_WEBHOOK_SECRET')

# Перелічують дозволені Telegram user IDs (через кому)
ALLOWED_TG_USER_IDS_RAW: str = os.getenv('ALLOWED_TG_USER_IDS', '').strip()
ALLOWED_TG_USER_IDS: set[int] = {int(x) for x in ALLOWED_TG_USER_IDS_RAW.split(',') if x.strip().isdigit()}

# Задають параметри доступу до YouTrack API
YT_TOKEN: str | None = os.getenv('YT_TOKEN')

USER_MAP_PATH: str = os.getenv('USER_MAP_PATH', './user_map.json')
USER_MAP_FILE: Path = Path(USER_MAP_PATH)

# Визначають назву кастом-філда для виконавця в YouTrack (за замовчуванням Assignee)
YOUTRACK_ASSIGNEE_FIELD_NAME: str = os.getenv('YOUTRACK_ASSIGNEE_FIELD_NAME', 'Assignee')

# Налаштовують поле стану та значення для встановлення при "Прийняти"
YOUTRACK_STATE_FIELD_NAME: str = os.getenv('YOUTRACK_STATE_FIELD_NAME', 'State')
YOUTRACK_STATE_IN_PROGRESS: str = os.getenv('YOUTRACK_STATE_IN_PROGRESS', 'In Progress')

# Шаблони текстів
TELEGRAM_MESSAGE_TEMPLATE = '<b>{issue_id}</b> — {summary}\n\
    {url}\n\
    {description}'
