"""Загальні допоміжні функції для роботи з даними задач та форматування."""

from __future__ import annotations

import json
import logging
import logging.config
import re
from collections.abc import Iterable, Mapping
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from agromat_it_desk_bot.config import (
    DESCRIPTION_MAX_LEN,
    LOG_LEVEL,
    TELEGRAM_MAIN_MESSAGE_TEMPLATE,
)
from agromat_it_desk_bot.messages import Msg, render

logger: logging.Logger = logging.getLogger(__name__)

_DEFAULT_AUTHOR: str = '[невідомо]'
_DEFAULT_STATUS: str = '[невідомо]'
_DEFAULT_ASSIGNEE: str = '[не призначено]'
_EMAIL_SUMMARY_FALLBACK_PREFIX: str = 'проблема з електронним листом'
_HTML_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)
_STATUS_EMOJI_MAP: dict[str, str] = {
    'нова': '🔵',
    'в роботі': '🟡',
    'виконано': '🟢',
}
_STATUS_EMOJI_ARCHIVED: str = '⚪'
_STATUS_EMOJI_DEFAULT: str = '🟤'


class _HTMLStripper(HTMLParser):
    """Перетворює HTML на текст, зберігаючи прості розриви рядків."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, _: list[tuple[str, str | None]]) -> None:  # noqa: D401
        if tag in {'br', 'p', 'div', 'li'}:
            self._parts.append('\n')

    def handle_startendtag(self, tag: str, _: list[tuple[str, str | None]]) -> None:
        if tag in {'br', 'hr'}:
            self._parts.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag in {'p', 'div', 'li'}:
            self._parts.append('\n')

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_data(self) -> str:
        raw: str = ''.join(self._parts)
        normalized = re.sub(r'\n\s*\n+', '\n', raw)
        return normalized.strip()


def strip_html(value: str) -> str:
    """Видаляє HTML-теги та розкодовує сутності."""
    value = _HTML_COMMENT_RE.sub('', value)
    stripper = _HTMLStripper()
    stripper.feed(value)
    text = stripper.get_data()
    return unescape(text)


def _stringify_issue_value(value: object | None) -> str | None:
    """Повертає рядкове представлення значення з payload YouTrack."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped: str = value.strip()
        return stripped or None
    if isinstance(value, list):
        for item in value:
            candidate: str | None = _stringify_issue_value(item)
            if candidate:
                return candidate
        return None
    if isinstance(value, Mapping):
        for key in ('fullName', 'presentation', 'text', 'localizedName', 'name', 'login', 'email'):
            candidate = value.get(key)
            if isinstance(candidate, str):
                stripped_candidate: str = candidate.strip()
                if stripped_candidate:
                    return stripped_candidate
    return None


def normalize_issue_summary(summary_raw: str | None) -> str:
    """Повертає валідний заголовок задачі з урахуванням поштових заглушок."""
    summary_text: str = (summary_raw or '').strip()
    if not summary_text:
        return render(Msg.YT_EMAIL_SUBJECT_MISSING)
    if summary_text.casefold().startswith(_EMAIL_SUMMARY_FALLBACK_PREFIX):
        return render(Msg.YT_EMAIL_SUBJECT_MISSING)
    return summary_text


def _extract_from_custom_fields(custom_fields: object, names: Iterable[str]) -> str | None:
    """Повертає значення поля з переліку customFields."""
    if not isinstance(custom_fields, list):
        return None
    normalized: set[str] = {name.casefold() for name in names if name}
    if not normalized:
        return None
    for entry in custom_fields:
        if not isinstance(entry, Mapping):
            continue
        field_name_obj: object | None = entry.get('name')
        if not isinstance(field_name_obj, str):
            continue
        if field_name_obj.casefold() not in normalized:
            continue
        value_obj: object | None = entry.get('value')
        extracted: str | None = _stringify_issue_value(value_obj)
        if extracted:
            return extracted
    return None


def extract_issue_status(issue: Mapping[str, object]) -> str | None:
    """Повертає статус задачі з payload YouTrack."""
    status: str | None = _stringify_issue_value(issue.get('status'))
    if status:
        return status
    state: str | None = _stringify_issue_value(issue.get('state'))
    if state:
        return state
    custom_fields: object = issue.get('customFields', [])
    return _extract_from_custom_fields(custom_fields, {'status', 'state', 'Статус'})


def extract_issue_assignee(issue: Mapping[str, object]) -> str | None:
    """Повертає виконавця задачі з payload YouTrack."""
    assignee: str | None = _stringify_issue_value(issue.get('assignee'))
    if assignee:
        return assignee
    custom_fields: object = issue.get('customFields', [])
    return _extract_from_custom_fields(custom_fields, {'assignee', 'Assignee', 'Виконавець'})


def extract_issue_author(issue: Mapping[str, object]) -> str | None:
    """Повертає автора (репортера) задачі з payload YouTrack."""
    for key in ('author', 'reporter', 'createdBy'):
        author_candidate: str | None = _stringify_issue_value(issue.get(key))
        if author_candidate:
            return author_candidate
    return None


def _resolve_log_level(target_level: str | None) -> str | None:
    """Повертає валідне ім'я рівня логування (DEBUG/INFO/...)."""
    if not target_level:
        return None
    normalized: str = target_level.strip()
    if not normalized:
        return None
    if normalized.isdigit():
        numerical = int(normalized)
        resolved = logging.getLevelName(numerical)
        return resolved if isinstance(resolved, str) else None
    upper_level: str = normalized.upper()
    lookup = logging.getLevelName(upper_level)
    return upper_level if isinstance(lookup, int) else None


def _apply_log_level_override(config_data: dict[str, Any], level_name: str) -> None:
    """Оновлює рівні root/стандартних хендлерів під час конфігурації."""
    handlers_obj: object = config_data.get('handlers')
    if isinstance(handlers_obj, dict):
        for handler_cfg in handlers_obj.values():
            if isinstance(handler_cfg, dict):
                handler_cfg['level'] = level_name

    loggers_obj: object = config_data.get('loggers')
    if isinstance(loggers_obj, dict):
        root_logger: object | None = loggers_obj.get('root')
        if isinstance(root_logger, dict):
            root_logger['level'] = level_name

    root_config: object | None = config_data.get('root')
    if isinstance(root_config, dict):
        root_config['level'] = level_name


def configure_logging(config_path: Path | None = None) -> None:
    """Завантажує конфіг логування з ``logging.conf`` або застосовує дефолт."""
    # Шлях до файлу конфігурації логування
    target_path: Path = config_path if config_path is not None else Path(__file__).resolve().parents[1] / 'logging.conf'
    try:
        # Зчитування налаштувань логування
        with target_path.open('r', encoding='utf-8') as config_file:
            config_data: dict[str, Any] = json.load(config_file)
    except FileNotFoundError:
        logging.basicConfig(level=logging.DEBUG)
        message_missing: str = 'logging.conf не знайдено (%s), використовую базову конфігурацію'
        logging.getLogger(__name__).warning(message_missing, target_path)
    except json.JSONDecodeError as exc:
        logging.basicConfig(level=logging.DEBUG)
        message_invalid: str = 'Не вдалося прочитати logging.conf (%s): %s, використовую базову конфігурацію'
        logging.getLogger(__name__).warning(message_invalid, target_path, exc)
    else:
        log_level_override: str | None = _resolve_log_level(LOG_LEVEL)
        if log_level_override:
            _apply_log_level_override(config_data, log_level_override)
        logging.config.dictConfig(config_data)


def get_str(source: Mapping[str, object], key: str) -> str:
    """Повертає значення ключа як рядок без зайвих пробілів."""
    value: object | None = source.get(key)
    return '' if value is None else str(value).strip()


def extract_issue_id(issue: Mapping[str, object]) -> str:
    """Отримує читабельний ID задачі (<PROJECT>-<NUMBER>) з доступних полів або формує його."""
    identifier: str = get_str(issue, 'idReadable') or get_str(issue, 'id')
    if identifier:
        return identifier

    number: object | None = issue.get('numberInProject')  # Номер задачі в межах проєкту
    project_raw: object | None = issue.get('project')  # Сирі дані проєкту з вебхука
    project_short: str | None = None  # Скорочена назва проєкту

    if project_raw is not None and isinstance(project_raw, dict):
        short_name_obj: object | None = project_raw.get('shortName')
        name_obj: object | None = project_raw.get('name')
        short_name: str | None = short_name_obj if isinstance(short_name_obj, str) else None
        name: str | None = name_obj if isinstance(name_obj, str) else None

        if short_name:
            project_short = short_name
        elif name:
            project_short = name

    if project_short is not None and isinstance(number, (str, int)):
        # Формування читабельного ідентифікатора PROJECT-N
        return f'{project_short}-{number}'

    issue_id_unknown_msg: str = render(Msg.YT_ISSUE_NO_ID)

    return issue_id_unknown_msg


def format_telegram_message(
    issue_id: str,
    summary_raw: str,
    description_raw: str,
    url: str,
    *,
    assignee: str | None = None,
    status: str | None = None,
    author: str | None = None,
) -> str:
    """Формує HTML-повідомлення для Telegram.

    :param issue_id: Короткий ідентифікатор задачі.
    :param summary_raw: Назва задачі з вебхука або API.
    :param description_raw: Опис задачі.
    :param url: Посилання на задачу (може бути повідомленням про помилку).
    :param assignee: Текстове представлення виконавця.
    :param status: Людиночитний статус задачі.
    :param author: Текстове представлення автора (репортера).
    :returns: Готовий HTML текст повідомлення.
    """
    formatted_issue_id: str = escape(issue_id)
    summary_value: str = summary_raw.strip()
    summary_formatted: str = escape(summary_value) if summary_value else ''

    description_source: str = description_raw.strip()
    if '<' in description_source:
        description_source = strip_html(description_source)
    if not description_source:
        description_text: str = render(Msg.ERR_YT_DESCRIPTION_EMPTY)
    else:
        description_candidate: str = escape(description_source)
        if len(description_candidate) > DESCRIPTION_MAX_LEN:
            description_candidate = f'{description_candidate[:DESCRIPTION_MAX_LEN]}…'
        description_text = description_candidate

    author_text: str = escape(author) if author else _DEFAULT_AUTHOR
    status_text: str = escape(status) if status else _DEFAULT_STATUS
    assignee_text: str = escape(assignee) if assignee else _DEFAULT_ASSIGNEE

    status_emoji: str = _pick_status_emoji(status)
    header_label: str = f'Заявка {formatted_issue_id}'

    url_clean: str = url.strip()
    if url_clean and url_clean.lower().startswith(('http://', 'https://')):
        header_label = f'<a href="{escape(url_clean, quote=True)}">{header_label}</a>'

    if summary_formatted:
        header_label = f'{header_label} — <b>{summary_formatted}</b>'
    header: str = f'{status_emoji} {header_label}'

    telegram_msg: str = TELEGRAM_MAIN_MESSAGE_TEMPLATE.format(
        header=header,
        author=author_text,
        status=status_text,
        assignee=assignee_text,
        description=description_text,
    )
    return telegram_msg


def _pick_status_emoji(status: str | None) -> str:
    """Повертає емодзі відповідно до статусу."""
    if not status:
        return _STATUS_EMOJI_DEFAULT
    normalized: str = status.strip().casefold()
    if not normalized:
        return _STATUS_EMOJI_DEFAULT
    archived_token: str = render(Msg.STATUS_ARCHIVED).casefold()
    if normalized == archived_token:
        return _STATUS_EMOJI_ARCHIVED
    return _STATUS_EMOJI_MAP.get(normalized, _STATUS_EMOJI_DEFAULT)
