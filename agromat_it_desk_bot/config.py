import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# Токен бота Telegram (обовʼязково)
BOT_TOKEN: str | None = os.getenv('BOT_TOKEN')

# ID цільового чату Telegram (обовʼязково)
TELEGRAM_CHAT_ID: str | None = os.getenv('TELEGRAM_CHAT_ID')

# Базова адреса інстансу YouTrack для формування посилань
YT_BASE_URL: str = os.getenv('YT_BASE_URL', '').rstrip('/')

# Максимальна довжина опису, який надсилається у Telegram
DESCRIPTION_MAX_LEN: int = 50
