"""Service configuration: reading environment variables."""

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


def _env_float(value: str | None, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value.strip())
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


# Telegram bot token (required)
BOT_TOKEN: str | None = os.getenv('BOT_TOKEN')

# Target Telegram chat ID (required)
TELEGRAM_CHAT_ID: str | None = os.getenv('TELEGRAM_CHAT_ID')

# Base YouTrack instance URL for links
YT_BASE_URL: str = os.getenv('YT_BASE_URL', '').rstrip('/')

# Maximum length of description sent to Telegram
DESCRIPTION_MAX_LEN: int = int(os.getenv('DESCRIPTION_MAX_LEN', '500'))

# Secret for Telegram webhook validation (X-Telegram-Bot-Api-Secret-Token)
TELEGRAM_WEBHOOK_SECRET: str | None = os.getenv('TELEGRAM_WEBHOOK_SECRET')

# Secret for YouTrack webhook validation
YT_WEBHOOK_SECRET: str | None = os.getenv('YT_WEBHOOK_SECRET')


# YouTrack API access parameters
YT_TOKEN: str | None = os.getenv('YT_TOKEN')

PROJECT_KEY: str | None = os.getenv('YT_PROJECT_KEY')
PROJECT_ID: str | None = os.getenv('YT_PROJECT_ID')

# Path to local user database
_DATABASE_PATH_ENV: str | None = os.getenv('DATABASE_PATH')
if _DATABASE_PATH_ENV:
    DATABASE_PATH: Path = Path(_DATABASE_PATH_ENV)
else:
    DATABASE_DIR: Path = Path(os.getenv('DATABASE_DIR', './data'))
    DATABASE_FILENAME: str = os.getenv('DATABASE_FILENAME', 'bot.sqlite3').strip() or 'bot.sqlite3'
    DATABASE_PATH = DATABASE_DIR / DATABASE_FILENAME

# Timeouts and retry counts for YouTrack token checks
YT_VALIDATE_TIMEOUT: float = float(os.getenv('YT_VALIDATE_TIMEOUT', '5.0'))
YT_VALIDATE_RETRIES: int = int(os.getenv('YT_VALIDATE_RETRIES', '3'))

# Name of assignee custom field in YouTrack (defaults to Assignee)
YOUTRACK_ASSIGNEE_FIELD_NAME: str = os.getenv('YOUTRACK_ASSIGNEE_FIELD_NAME', 'Assignee')

# Status field and value for "In progress"
YOUTRACK_STATE_FIELD_NAME: str | None = os.getenv('YOUTRACK_STATE_FIELD_NAME')
YOUTRACK_STATE_IN_PROGRESS: str | None = os.getenv('YOUTRACK_STATE_IN_PROGRESS')

# Log level for root/primary handlers
LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO').strip() or 'INFO'

# Secret to encrypt user personal tokens
USER_TOKEN_SECRET: str | None = os.getenv('USER_TOKEN_SECRET')

# Text templates
TELEGRAM_MAIN_MESSAGE_TEMPLATE = (
    '{header}\n'
    '\n'
    '<b>Автор:</b> <code>{author}</code>\n'
    '<b>Статус:</b> <code>{status}</code>\n'
    '<b>Виконавець:</b> <code>{assignee}</code>\n'
    '\n'
    '{description}'
)

# Weekly schedule settings (Outlook/Exchange)
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
    """Describe deferred message about ``New`` status."""

    index: int
    minutes: int
    message: str


def _load_alert_minutes() -> tuple[int, ...]:
    # default alert delays in minutes
    defaults: tuple[int, int, int] = (1, 2, 3)
    values: list[int] = []
    for position, default in enumerate(defaults, start=1):
        env_name = f'NEW_STATUS_ALERT_MINUTES_{position}'
        values.append(_env_int(os.getenv(env_name), default=default))
    return tuple(values)


NEW_STATUS_ALERT_SUFFIX_DEFAULT: str = (os.getenv('NEW_STATUS_ALERT_MESSAGE_SUFFIX') or '').strip()
NEW_STATUS_ALERT_SUFFIX_ADMIN_ID: int | None = (
    _env_int(os.getenv('NEW_STATUS_ALERT_SUFFIX_ADMIN_ID'), default=0) or None
)


def _load_alert_messages() -> tuple[str, ...]:
    defaults: tuple[str, str, str] = (
        '❗Нова заявка без реакції понад <b>20 хвилин</b>.',
        '⚠️ Нова заявка без реакції понад <b>1 годину</b>!',
        '📛 Нова заявка без реакції понад <b>2 години</b>!',
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


NEW_STATUS_ALERT_ENABLED: bool = True
NEW_STATUS_ALERT_STATE_NAME: str = os.getenv('NEW_STATUS_STATE_NAME', 'Нова').strip() or 'Нова'
NEW_STATUS_ALERT_STEPS: tuple[StatusAlertStep, ...] = _build_alert_steps(
    _load_alert_minutes(),
    _load_alert_messages(),
)
_ALERT_POLL_MINUTES: int = max(_env_int(os.getenv('NEW_STATUS_ALERT_POLL_MINUTES'), default=1), 1)
NEW_STATUS_ALERT_POLL_SECONDS: int = _ALERT_POLL_MINUTES * 60

_ARCHIVE_SCAN_MINUTES: float = max(_env_float(os.getenv('ARCHIVE_SCAN_INTERVAL_MINUTES'), default=10.0), 0.1)
ARCHIVE_SCAN_INTERVAL_SECONDS: float = _ARCHIVE_SCAN_MINUTES * 60
_ARCHIVE_IDLE_MINUTES: float = max(_env_float(os.getenv('ARCHIVE_IDLE_THRESHOLD_MINUTES'), default=2880.0), 0.1)
ARCHIVE_IDLE_THRESHOLD_SECONDS: float = _ARCHIVE_IDLE_MINUTES * 60
