"""Налаштування сервісу: зчитування змінних середовища."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())


def _env_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized in {'1', 'true', 'yes', 'on'}


def _env_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _env_time(value: str | None, *, fallback: tuple[int, int]) -> tuple[int, int]:
    if value is None:
        return fallback
    parts = value.strip().split(':', 1)
    if len(parts) != 2:
        return fallback
    hour_str, minute_str = parts
    try:
        hour_val = int(hour_str)
        minute_val = int(minute_str)
    except ValueError:
        return fallback
    if 0 <= hour_val <= 23 and 0 <= minute_val <= 59:
        return hour_val, minute_val
    return fallback


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

PROJECT_KEY: str | None = os.getenv('YT_PROJECT_KEY')
PROJECT_ID: str | None = os.getenv('YT_PROJECT_ID')

# Шлях до локальної БД користувачів
_DATABASE_PATH_ENV: str | None = os.getenv('DATABASE_PATH')
if _DATABASE_PATH_ENV:
    DATABASE_PATH: Path = Path(_DATABASE_PATH_ENV)
else:
    DATABASE_DIR: Path = Path(os.getenv('DATABASE_DIR', './data'))
    DATABASE_FILENAME: str = os.getenv('DATABASE_FILENAME', 'bot.sqlite3').strip() or 'bot.sqlite3'
    DATABASE_PATH = DATABASE_DIR / DATABASE_FILENAME

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

# Секрет для шифрування персональних токенів користувачів
USER_TOKEN_SECRET: str | None = os.getenv('USER_TOKEN_SECRET')

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

# Налаштування тижневого розкладу (Outlook/Exchange)
SCHEDULE_PIN_WEEKLY: bool = True
SCHEDULE_EXCHANGE_EMAIL: str | None = os.getenv('SCHEDULE_EXCHANGE_EMAIL')
SCHEDULE_EXCHANGE_USERNAME: str | None = os.getenv('SCHEDULE_EXCHANGE_USERNAME') or SCHEDULE_EXCHANGE_EMAIL
SCHEDULE_EXCHANGE_PASSWORD: str | None = os.getenv('SCHEDULE_EXCHANGE_PASSWORD')
SCHEDULE_EXCHANGE_SERVER: str | None = os.getenv('SCHEDULE_EXCHANGE_SERVER')
SCHEDULE_CALENDAR_NAME: str | None = os.getenv('SCHEDULE_CALENDAR_NAME')
SCHEDULE_TIMEZONE: str = os.getenv('SCHEDULE_TIMEZONE', 'Europe/Kyiv')
SCHEDULE_SEND_WEEKDAY: int = _env_int(os.getenv('SCHEDULE_SEND_WEEKDAY'), default=6)
_SCHEDULE_HOUR, _SCHEDULE_MINUTE = _env_time(os.getenv('SCHEDULE_SEND_TIME'), fallback=(9, 0))
SCHEDULE_SEND_HOUR: int = _SCHEDULE_HOUR
SCHEDULE_SEND_MINUTE: int = _SCHEDULE_MINUTE
_REMINDER_HOUR, _REMINDER_MINUTE = _env_time(os.getenv('SCHEDULE_DAILY_REMINDER_TIME'), fallback=(18, 0))
SCHEDULE_DAILY_REMINDER_HOUR: int = _REMINDER_HOUR
SCHEDULE_DAILY_REMINDER_MINUTE: int = _REMINDER_MINUTE


@dataclass(frozen=True)
class StatusAlertStep:
    """Описує відкладене повідомлення про статус ``Нова``."""

    index: int
    minutes: int
    message: str


def _load_alert_minutes() -> tuple[int, ...]:
    defaults: tuple[int, int, int] = (20, 60, 120)
    values: list[int] = []
    for position, default in enumerate(defaults, start=1):
        env_name = f'NEW_STATUS_ALERT_MINUTES_{position}'
        values.append(_env_int(os.getenv(env_name), default=default))
    return tuple(values)


def _load_alert_messages() -> tuple[str, ...]:
    defaults: tuple[str, str, str] = (
        '⚠️ Нова заявка очікує на реакцію понад 20 хвилин.',
        '⚠️ Нова заявка очікує понад 1 годину.',
        '⚠️ Нова заявка очікує понад 2 години.',
    )
    messages: list[str] = []
    for position, default in enumerate(defaults, start=1):
        env_name = f'NEW_STATUS_ALERT_MESSAGE_{position}'
        text = (os.getenv(env_name) or default).strip()
        messages.append(text or default)
    return tuple(messages)


def _build_alert_steps(minutes: tuple[int, ...], messages: tuple[str, ...]) -> tuple[StatusAlertStep, ...]:
    steps: list[StatusAlertStep] = []
    count: int = min(len(minutes), len(messages))
    for offset in range(count):
        minute_value: int = minutes[offset]
        if minute_value <= 0:
            continue
        steps.append(StatusAlertStep(index=offset + 1, minutes=minute_value, message=messages[offset]))
    return tuple(steps)


NEW_STATUS_ALERT_ENABLED: bool = _env_bool(os.getenv('NEW_STATUS_ALERT_ENABLED'))
NEW_STATUS_ALERT_STATE_NAME: str = os.getenv('NEW_STATUS_STATE_NAME', 'Нова').strip() or 'Нова'
NEW_STATUS_ALERT_STEPS: tuple[StatusAlertStep, ...] = _build_alert_steps(
    _load_alert_minutes(),
    _load_alert_messages(),
)
_ALERT_POLL_MINUTES: int = max(_env_int(os.getenv('NEW_STATUS_ALERT_POLL_MINUTES'), default=1), 1)
NEW_STATUS_ALERT_POLL_SECONDS: int = _ALERT_POLL_MINUTES * 60
