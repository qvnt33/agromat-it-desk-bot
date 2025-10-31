"""Забезпечує вищерівневі операції з YouTrack: мапінг користувачів, призначення задач, оновлення стану."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import NamedTuple

from .youtrack_client import (
    CustomField,
    CustomFieldMap,
    YouTrackUser,
    assign_custom_field,
    fetch_issue_custom_fields,
    fetch_issue_overview,
    find_state_value_id,
    find_user,
    find_user_id,
    get_issue_internal_id,
)

from agromat_it_desk_bot.auth import get_authorized_yt_user
from agromat_it_desk_bot.config import (
    YOUTRACK_ASSIGNEE_FIELD_NAME,
    YOUTRACK_STATE_FIELD_NAME,
    YOUTRACK_STATE_IN_PROGRESS,
)
from agromat_it_desk_bot.utils import extract_issue_assignee, extract_issue_author, extract_issue_status

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


class IssueDetails(NamedTuple):
    """Описує основну інформацію задачі для оновлення повідомлень."""

    summary: str
    description: str
    assignee: str | None
    status: str | None
    author: str | None


def resolve_account(tg_user_id: int | None) -> tuple[str | None, str | None, str | None]:
    """Повертає дані авторизованого користувача YouTrack за Telegram ID.

    :param tg_user_id: Telegram ID користувача.
    :returns: Логін, email та внутрішній ID користувача YouTrack.
    """
    if tg_user_id is None:
        logger.debug('resolve_account викликано без tg_user_id')
        return None, None, None
    login, email, yt_user_id = get_authorized_yt_user(tg_user_id)
    logger.debug('resolve_account: tg_user_id=%s yt_user_id=%s', tg_user_id, yt_user_id)
    return login, email, yt_user_id


def fetch_issue_details(issue_id_readable: str) -> IssueDetails | None:
    """Отримує актуальні дані задачі для оновлення повідомлення Telegram.

    :param issue_id_readable: Зовнішній ідентифікатор задачі (``ABC-123``).
    :returns: ``IssueDetails`` або ``None``, якщо дані недоступні.
    """
    issue_internal_id: str | None = get_issue_internal_id(issue_id_readable)
    if issue_internal_id is None:
        logger.warning('Не вдалося визначити внутрішній ID задачі %s', issue_id_readable)
        return None

    overview: Mapping[str, object] | None = fetch_issue_overview(issue_internal_id)
    if overview is None:
        logger.debug('Не вдалося отримати дані задачі %s', issue_id_readable)
        return None

    summary_obj: object | None = overview.get('summary')
    summary: str = str(summary_obj) if summary_obj is not None else ''
    description_obj: object | None = overview.get('description')
    description: str = str(description_obj) if description_obj is not None else ''

    assignee: str | None = extract_issue_assignee(overview)
    status: str | None = extract_issue_status(overview)
    author: str | None = extract_issue_author(overview)
    return IssueDetails(summary, description, assignee, status, author)


def assign_issue(issue_id_readable: str, login: str | None, email: str | None, user_id: str | None) -> bool:
    """Призначає задачу на вказаного користувача.

    :param issue_id_readable: Короткий ID задачі (``ABC-123``).
    :param login: Логін користувача YouTrack.
    :param email: Email користувача YouTrack.
    :param user_id: Внутрішній ID користувача (може бути ``None``).
    :returns: ``True`` у разі успішного призначення.
    """
    issue_id: str | None = get_issue_internal_id(issue_id_readable)
    # Перевіряють, чи вдалося отримати внутрішній ID задачі
    if issue_id is None:
        logger.warning('Не знайдено внутрішній ID задачі: %s', issue_id_readable)
        return False

    assignee_field_id: str | None = _resolve_assignee_field_id(issue_id, issue_id_readable)
    # Перевіряють наявність кастомного поля виконавця
    if assignee_field_id is None:
        logger.warning('Відсутнє поле виконавця для задачі %s', issue_id_readable)
        return False

    payload: dict[str, object]
    yt_user_id_resolved: str | None = None
    if login is None and email is None and user_id is None:
        # Зняття призначення
        payload = {'value': None}
        logger.debug('Готую payload для зняття виконавця: issue=%s', issue_id_readable)
    else:
        yt_user_id_resolved = _resolve_target_user_id(login, email, user_id)
        # Переконуються, що користувача можна однозначно ідентифікувати
        if yt_user_id_resolved is None:
            logger.warning('Не визначено користувача для призначення: issue=%s login=%s email=%s',
                           issue_id_readable,
                           login,
                           email)
            return False

        payload = {'value': _build_assignee_value(yt_user_id_resolved, login, email)}

    if assign_custom_field(issue_id, assignee_field_id, payload):
        logger.info('Задачу %s призначено на користувача id=%s login=%s',
                    issue_id_readable,
                    yt_user_id_resolved,
                    login)
        _ensure_in_progress(issue_id, issue_id_readable)
        return True

    logger.debug('YouTrack customFields повернув помилку під час призначення')
    return False


def _pick_field(fields: CustomFieldMap, names: set[str]) -> CustomField | None:
    """Вибирає перше поле з переданих назв."""
    for name in names:
        field: CustomField | None = fields.get(name.lower())
        if field is not None:
            return field
    return None


def lookup_user_by_login(login: str) -> tuple[str | None, str | None, str | None]:
    """Повертає ``login``, ``email`` та ``id`` користувача YouTrack за логіном."""
    if not login:
        return None, None, None

    user: YouTrackUser | None = find_user(login, None)
    if user is None:
        return None, None, None

    login_value: str | None = user.get('login')
    resolved_login: str | None = login_value if isinstance(login_value, str) else login

    email_value: str | None = user.get('email')
    email: str | None = email_value if isinstance(email_value, str) else None

    user_id_value: str | None = user.get('id')
    yt_user_id: str | None = user_id_value if isinstance(user_id_value, str) else None
    return resolved_login, email, yt_user_id


def _resolve_target_user_id(login: str | None, email: str | None, user_id: str | None) -> str | None:
    """Визначає внутрішній ID користувача YouTrack."""
    if user_id:
        return user_id

    yt_user_id: str | None = find_user_id(login, email)
    if yt_user_id is None:
        logger.error('Не вдалося визначити ID користувача (login=%s, email=%s)', login, email)
    return yt_user_id


def _resolve_assignee_field_id(issue_id: str, issue_id_readable: str) -> str | None:
    """Повертає ID поля виконавця для задачі."""
    assignee_fields: set[str] = {YOUTRACK_ASSIGNEE_FIELD_NAME, 'assignee'}
    fields_optional: CustomFieldMap | None = fetch_issue_custom_fields(issue_id, assignee_fields)
    if not fields_optional:
        logger.error('Поле виконавця не знайдено у задачі %s', issue_id_readable)
        return None

    fields_map: CustomFieldMap = fields_optional
    assignee_field: CustomField | None = _pick_field(fields_map, assignee_fields)
    if assignee_field is None:
        logger.error('Поле виконавця не знайдено у задачі %s', issue_id_readable)
        return None

    project_custom_obj: object | None = assignee_field.get('projectCustomField')
    project_custom: Mapping[str, object] = (
        project_custom_obj if isinstance(project_custom_obj, dict) else {}
    )
    # Переконуються, що у кастомного поля виконавця є ідентифікатор
    field_id: object | None = project_custom.get('id')
    if not isinstance(field_id, str):
        logger.error('ID поля виконавця відсутній у задачі %s', issue_id_readable)
        return None

    return field_id


def _build_assignee_value(yt_user_id: str, login: str | None, email: str | None) -> dict[str, object]:
    """Збирає тіло значення для призначення виконавця."""
    value_payload: dict[str, object] = {'id': yt_user_id, '$type': 'User'}
    if login:
        value_payload['login'] = login
    if email:
        value_payload['email'] = email
    return value_payload


def _ensure_in_progress(issue_id: str, issue_id_readable: str) -> None:
    """Встановлює статус задачі у значення «в роботі», якщо налаштовано."""
    state_field_name: str | None = YOUTRACK_STATE_FIELD_NAME
    desired_state: str | None = YOUTRACK_STATE_IN_PROGRESS
    if not state_field_name or not desired_state:
        logger.debug('Статус не налаштовано: field=%s desired=%s', state_field_name, desired_state)
        return

    fields_optional: CustomFieldMap | None = fetch_issue_custom_fields(issue_id, {state_field_name})
    if not fields_optional:
        logger.warning('Поле стану %s не знайдено у задачі %s', state_field_name, issue_id_readable)
        return

    field: CustomField | None = _pick_field(fields_optional, {state_field_name})
    if field is None:
        logger.warning('Поле стану %s відсутнє у задачі %s', state_field_name, issue_id_readable)
        return

    state_id: str | None = find_state_value_id(field, desired_state)
    if state_id is None:
        logger.warning('Значення стану %s не знайдено у задачі %s', desired_state, issue_id_readable)
        return

    payload: dict[str, object] = {'value': {'id': state_id}}
    project_custom_obj: object | None = field.get('projectCustomField')
    project_custom: Mapping[str, object] = (
        project_custom_obj if isinstance(project_custom_obj, dict) else {}
    )
    field_id_obj: object | None = project_custom.get('id')
    if not isinstance(field_id_obj, str):
        logger.warning('ID поля стану відсутній у задачі %s', issue_id_readable)
        return

    if assign_custom_field(issue_id, field_id_obj, payload):
        logger.info('Статус задачі %s оновлено на %s', issue_id_readable, desired_state)
    else:
        logger.warning('Не вдалося оновити статус задачі %s на %s', issue_id_readable, desired_state)
