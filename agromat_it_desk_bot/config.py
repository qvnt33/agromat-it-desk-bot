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


# Задають параметри доступу до YouTrack API
YT_TOKEN: str | None = os.getenv('YT_TOKEN')

USER_MAP_PATH: str = os.getenv('USER_MAP_PATH', './user_map.json')
USER_MAP_FILE: Path = Path(USER_MAP_PATH)

PROJECT_KEY: str | None = os.getenv('YT_PROJECT_KEY')
PROJECT_ID: str | None = os.getenv('YT_PROJECT_ID')

# Шлях до локальної БД користувачів
DATABASE_PATH: Path = Path(os.getenv('DATABASE_PATH', './data/bot.sqlite3'))

# Таймаути та кількість спроб перевірки токенів YouTrack
YT_VALIDATE_TIMEOUT: float = float(os.getenv('YT_VALIDATE_TIMEOUT', '5.0'))
YT_VALIDATE_RETRIES: int = int(os.getenv('YT_VALIDATE_RETRIES', '3'))

# Визначають назву кастом-філда для виконавця в YouTrack (за замовчуванням Assignee)
YOUTRACK_ASSIGNEE_FIELD_NAME: str = os.getenv('YOUTRACK_ASSIGNEE_FIELD_NAME', 'Assignee')

# Поле статусу та значення для режиму «В роботі»
YOUTRACK_STATE_FIELD_NAME: str | None = os.getenv('YOUTRACK_STATE_FIELD_NAME')
YOUTRACK_STATE_IN_PROGRESS: str | None = os.getenv('YOUTRACK_STATE_IN_PROGRESS')

# Рівень логування для root/основних хендлерів
LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO').strip() or 'INFO'

# Шаблони текстів
TELEGRAM_MAIN_MESSAGE_TEMPLATE = (
    '{header}\n'
    '\n'
    '<b>Автор:</b> <code>{author}</code>\n'
    '<b>Статус:</b> <code>{status}</code>\n'
    '<b>Виконавець:</b> <code>{assignee}</code>\n'
    '\n'
    '{description}'
)
