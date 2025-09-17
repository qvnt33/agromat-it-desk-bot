import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# Токен бота Telegram (обовʼязково)
BOT_TOKEN: str | None = os.getenv('BOT_TOKEN')

# ID цільового чату Telegram (обовʼязково)
TELEGRAM_CHAT_ID: str | None = os.getenv('TELEGRAM_CHAT_ID')

# Базова адреса інстансу YouTrack для формування посилань
YT_BASE_URL: str = os.getenv('YT_BASE_URL', '').rstrip('/')

# Максимальна довжина опису, який надсилається у Telegram
DESCRIPTION_MAX_LEN: int = int(os.getenv('DESCRIPTION_MAX_LEN', '500'))

# Секрет для перевірки Telegram вебхука (X-Telegram-Bot-Api-Secret-Token)
TELEGRAM_WEBHOOK_SECRET: str | None = os.getenv('TELEGRAM_WEBHOOK_SECRET')

# Дозволені Telegram user IDs (через кому)
ALLOWED_TG_USER_IDS_RAW: str = os.getenv('ALLOWED_TG_USER_IDS', '').strip()
ALLOWED_TG_USER_IDS: set[int] = {int(x) for x in ALLOWED_TG_USER_IDS_RAW.split(',') if x.strip().isdigit()}

# YouTrack API
YT_TOKEN: str | None = os.getenv('YT_TOKEN')

USER_MAP_PATH: str = os.getenv('USER_MAP_PATH', './user_map.json')
USER_MAP_FILE: Path = Path(USER_MAP_PATH)

# Назва кастом-філда для виконавця в YouTrack (за замовчуванням Assignee)
YOUTRACK_ASSIGNEE_FIELD_NAME: str = os.getenv('YOUTRACK_ASSIGNEE_FIELD_NAME', 'Assignee')

# Поле стану та значення для встановлення при "Прийняти"
YOUTRACK_STATE_FIELD_NAME: str = os.getenv('YOUTRACK_STATE_FIELD_NAME', 'State')
YOUTRACK_STATE_IN_PROGRESS: str = os.getenv('YOUTRACK_STATE_IN_PROGRESS', 'In Progress')
