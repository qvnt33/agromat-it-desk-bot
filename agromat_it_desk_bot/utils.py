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
from typing import Any, TypedDict

from agromat_it_desk_bot.config import (
    DESCRIPTION_MAX_LEN,
    LOG_LEVEL,
    TELEGRAM_MAIN_MESSAGE_TEMPLATE,
    USER_MAP_FILE,
)
from agromat_it_desk_bot.messages import Msg, render

logger: logging.Logger = logging.getLogger(__name__)

_DEFAULT_AUTHOR: str = '[невідомо]'
_DEFAULT_STATUS: str = '[невідомо]'
_DEFAULT_ASSIGNEE: str = '[не призначено]'
_EMAIL_SUMMARY_FALLBACK_PREFIX: str = 'проблема з електронним листом'


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


class UserMapEntry(TypedDict, total=False):
    """Одна запис у user_map.json."""

    login: str
    email: str
    id: str


UserMap = dict[str, UserMapEntry | str]


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

    header: str = f'Заявка {formatted_issue_id}'

    url_clean: str = url.strip()
    if url_clean and url_clean.lower().startswith(('http://', 'https://')):
        header = f'<a href="{escape(url_clean, quote=True)}">{header}</a>'

    if summary_formatted:
        header = f'{header} — <b>{summary_formatted}</b>'

    telegram_msg: str = TELEGRAM_MAIN_MESSAGE_TEMPLATE.format(
        header=header,
        author=author_text,
        status=status_text,
        assignee=assignee_text,
        description=description_text,
    )
    return telegram_msg


def resolve_from_map(tg_user_id: int | None) -> tuple[str | None, str | None, str | None]:
    """Знаходить ``login``, ``email`` та ``yt_user_id`` для користувача з Telegram ID."""
    # Локальний логін користувача
    login: str | None = None
    # Локальний email користувача
    email: str | None = None
    # Локальний YouTrack ID користувача
    yt_user_id: str | None = None

    if tg_user_id is None:
        logger.debug('resolve_from_map викликано без tg_user_id')
        return login, email, yt_user_id

    try:
        # Шлях до файлу мапи користувачів
        target_file: Path | None = _resolve_map_path()
        if target_file is None or not target_file.exists():
            logger.error('Файл мапи користувачів не знайдено за шляхом: %s', USER_MAP_FILE)
            return login, email, yt_user_id

        # Актуальна мапа користувачів
        mapping: UserMap = _load_mapping(target_file)
        entry: UserMapEntry | str | None = mapping.get(str(tg_user_id))
        if isinstance(entry, dict):
            login_value: object | None = entry.get('login')
            email_value: object | None = entry.get('email')
            yt_user_value: object | None = entry.get('id')
            login = login_value if isinstance(login_value, str) else None
            email = email_value if isinstance(email_value, str) else None
            yt_user_id = yt_user_value if isinstance(yt_user_value, str) else None
            logger.debug('Мапа користувача %s: login=%s email=%s yt_id=%s', tg_user_id, login, email, yt_user_id)
        elif isinstance(entry, str):
            login = entry
            logger.debug('Мапа користувача %s: login=%s (рядок)', tg_user_id, login)
        else:
            logger.warning('Користувача %s немає у user_map', tg_user_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception('Не вдалося прочитати USER_MAP_FILE: %s', exc)

    logger.debug('resolve_from_map результат: tg_user_id=%s login=%s email=%s yt_user_id=%s',
                 tg_user_id,
                 login,
                 email,
                 yt_user_id)
    return login, email, yt_user_id


def _resolve_map_path() -> Path | None:
    """Повертає шлях до JSON-файла з мапою користувачів."""
    target_file: Path = USER_MAP_FILE
    if target_file.is_dir():
        candidate: Path = target_file / 'user_map.json'
        logger.debug('USER_MAP_FILE визначено як директорія, використовую %s', candidate)
        return candidate
    # Робота безпосередньо з файлом user_map
    logger.debug('USER_MAP_FILE використовується напряму: %s', target_file)
    return target_file


def _load_mapping(path: Path) -> UserMap:
    """Завантажує JSON-дані з файлу мапи користувачів."""
    raw_text: str = path.read_text(encoding='utf-8')
    if not raw_text.strip():
        # Повідомлення про порожній файл user_map
        logger.warning('USER_MAP_FILE %s порожній, використовую порожню мапу', path)
        return {}

    try:
        raw_data: object = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error('USER_MAP_FILE %s має некоректний JSON: %s', path, exc)
        return {}

    if not isinstance(raw_data, dict):
        # Захист від непідтримуваного формату user_map
        logger.error('USER_MAP_FILE має некоректний формат (очікувався dict)')
        return {}

    result: UserMap = {}
    # Записи user_map з сирого словника
    for key_obj, value in raw_data.items():
        if not isinstance(key_obj, str):
            # Пропуск запису з некоректним типом ключа
            logger.debug('Пропускаю запис user_map із некоректним ключем: %r', key_obj)
            continue

        key: str = key_obj
        normalized: UserMapEntry | str | None = _normalize_user_record(key, value)
        if normalized is None:
            continue
        result[key] = normalized

    logger.debug('Завантажено %s запис(ів) user_map', len(result))
    return result


def _normalize_user_record(key: str, value: object) -> UserMapEntry | str | None:
    """Перетворює будь-який запис user_map на уніфікований вигляд."""
    if isinstance(value, dict):
        return _extract_entry(value)

    if isinstance(value, str):
        return value

    logger.debug('Пропускаю запис user_map %s через некоректний формат: %r', key, value)
    return None


def _extract_entry(mapping_value: Mapping[str, object]) -> UserMapEntry:
    """Створює ``UserMapEntry`` із словникового значення."""
    entry: UserMapEntry = {}

    login_val: object | None = mapping_value.get('login')
    if isinstance(login_val, str):
        entry['login'] = login_val

    email_val: object | None = mapping_value.get('email')
    if isinstance(email_val, str):
        entry['email'] = email_val

    id_val: object | None = mapping_value.get('id')
    if isinstance(id_val, str):
        entry['id'] = id_val

    return entry


def upsert_user_map_entry(
    tg_user_id: int,
    *,
    login: str | None = None,
    email: str | None = None,
    yt_user_id: str | None = None,
) -> None:
    """Додає або оновлює запис користувача у ``user_map.json``."""
    if not any((login, email, yt_user_id)):
        message_required: str = 'Потрібно надати принаймні одне з полів: login, email або yt_user_id'
        logger.error('Не вдалося оновити мапу користувачів: %s', message_required)
        raise ValueError(message_required)

    path: Path | None = _resolve_map_path()
    if path is None:
        raise FileNotFoundError('Не вдалося визначити шлях до user_map.json')

    mapping: UserMap = {}
    if path.exists():
        mapping = _load_mapping(path)

    _ensure_unique_mapping(mapping, tg_user_id, login=login, yt_user_id=yt_user_id)

    entry: UserMapEntry = {}
    if login:
        entry['login'] = login
    if email:
        entry['email'] = email
    if yt_user_id:
        entry['id'] = yt_user_id

    if not entry:
        message_empty: str = 'Надано порожні дані для оновлення мапи користувачів'
        logger.error(message_empty)
        raise ValueError(message_empty)

    mapping[str(tg_user_id)] = entry
    _write_mapping(path, mapping)
    logger.info('Оновлено user_map для користувача %s', tg_user_id)


def _write_mapping(path: Path, mapping: UserMap) -> None:
    """Зберігає ``user_map.json`` на диск."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    logger.debug('Збережено user_map (%s записів) у %s', len(mapping), path)


def is_login_taken(login: str, *, exclude_tg_user_id: int | None = None) -> bool:
    """Перевіряє, чи закріплений логін за іншим Telegram користувачем."""
    path: Path | None = _resolve_map_path()
    if path is None or not login:
        return False

    if not path.exists():
        return False

    mapping: UserMap = _load_mapping(path)
    login_normalized: str = login.lower()
    exclude_key: str | None = str(exclude_tg_user_id) if exclude_tg_user_id is not None else None

    for key, raw_entry in mapping.items():
        if exclude_key is not None and key == exclude_key:
            continue

        existing_login: str | None = None
        if isinstance(raw_entry, dict):
            login_val: object | None = raw_entry.get('login')
            if isinstance(login_val, str):
                existing_login = login_val
        else:
            existing_login = raw_entry

        if existing_login and existing_login.lower() == login_normalized:
            logger.debug('Перевірка зайнятого логіна: target=%s власник=%s', login, key)
            return True

    return False


def _ensure_unique_mapping(mapping: UserMap, tg_user_id: int, *, login: str | None, yt_user_id: str | None) -> None:
    """Переконує, що логін та YouTrack ID не зайняті іншими користувачами."""
    target_key: str = str(tg_user_id)
    login_normalized: str | None = login.lower() if login is not None else None

    for existing_key, raw_entry in mapping.items():
        if existing_key == target_key:
            continue

        existing_login: str | None = None
        existing_yt_id: str | None = None

        if isinstance(raw_entry, dict):
            login_val: object | None = raw_entry.get('login')
            if isinstance(login_val, str):
                existing_login = login_val
            yt_val: object | None = raw_entry.get('id')
            if isinstance(yt_val, str):
                existing_yt_id = yt_val
        else:
            existing_login = raw_entry

        if login_normalized and existing_login and existing_login.lower() == login_normalized:
            # Блокування дублювання логіна між користувачами
            logger.warning('Логін %s вже закріплено за користувачем %s', login, existing_key)
            raise ValueError('Цей логін вже закріплено за іншим користувачем.')

        if yt_user_id and existing_yt_id and existing_yt_id == yt_user_id:
            # Заборона повторного привʼязування YouTrack акаунта
            logger.warning('YouTrack ID %s вже закріплено за користувачем %s', yt_user_id, existing_key)
            raise ValueError('Цей YouTrack акаунт вже привʼязаний до іншого користувача.')
