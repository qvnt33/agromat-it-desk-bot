"""Забезпечує вищерівневі операції з YouTrack: мапінг користувачів, призначення задач, оновлення стану."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from agromat_it_desk_bot.config import YOUTRACK_ASSIGNEE_FIELD_NAME, YOUTRACK_STATE_FIELD_NAME
from agromat_it_desk_bot.utils import as_mapping, resolve_from_map
from agromat_it_desk_bot.youtrack_client import (
    CustomField,
    CustomFieldMap,
    YouTrackUser,
    assign_custom_field,
    fetch_issue_custom_fields,
    find_state_value_id,
    find_user,
    find_user_id,
    get_issue_internal_id,
)

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


def resolve_account(tg_user_id: int | None) -> tuple[str | None, str | None, str | None]:
    """Визначає користувача YouTrack за TG ID через локальну мапу.

    :param tg_user_id: Telegram ID користувача.
    :returns: Логін, email та внутрішній ID користувача YouTrack.
    """
    return resolve_from_map(tg_user_id)


def assign_issue(issue_id_readable: str, login: str | None, email: str | None, user_id: str | None) -> bool:
    """Призначає задачу на вказаного користувача.

    :param issue_id_readable: Короткий ID задачі (``ABC-123``).
    :param login: Логін користувача YouTrack.
    :param email: Email користувача YouTrack.
    :param user_id: Внутрішній ID користувача (може бути ``None``).
    :returns: ``True`` у разі успішного призначення.
    """
    issue_id: str | None = get_issue_internal_id(issue_id_readable)
    if issue_id is None:
        return False

    yt_user_id: str | None = _resolve_target_user_id(login, email, user_id)
    if yt_user_id is None:
        return False

    assignee_field_id: str | None = _resolve_assignee_field_id(issue_id, issue_id_readable)
    if assignee_field_id is None:
        return False

    payload: dict[str, object] = {'value': _build_assignee_value(yt_user_id, login, email)}

    if assign_custom_field(issue_id, assignee_field_id, payload):
        logger.info('Задачу %s призначено на користувача id=%s login=%s', issue_id_readable, yt_user_id, login)
        return True

    logger.debug('YouTrack customFields повернув помилку під час призначення')
    return False


def set_state(issue_id_readable: str, desired_state: str | None) -> bool:
    """Змінює стан задачі на вказане значення.

    :param issue_id_readable: Короткий ID задачі.
    :param desired_state: Назва стану, який потрібно встановити.
    :returns: ``True`` при успішному оновленні, інакше ``False``.
    """
    if not desired_state:
        return True

    issue_id: str | None = get_issue_internal_id(issue_id_readable)
    if issue_id is None:
        return False

    fields_optional: CustomFieldMap | None = fetch_issue_custom_fields(issue_id, {YOUTRACK_STATE_FIELD_NAME, 'state'})
    if not fields_optional:
        return False

    assert fields_optional is not None
    fields_map: CustomFieldMap = fields_optional

    state_field: CustomField | None = _pick_field(fields_map, {YOUTRACK_STATE_FIELD_NAME, 'state'})
    if state_field is None:
        return False

    project_custom: Mapping[str, object] | dict[str, object] = as_mapping(state_field.get('projectCustomField')) or {}
    field_id: object | None = project_custom.get('id')
    if not isinstance(field_id, str):
        return False

    value_id: str | None = find_state_value_id(state_field, desired_state)
    if value_id is None:
        message_missing: str = 'Поле стану або значення не знайдено (field=%s, value=%s)'
        logger.debug(message_missing, YOUTRACK_STATE_FIELD_NAME, desired_state)
        return False

    value_payload: dict[str, object] = {'id': value_id}
    payload: dict[str, object] = {'value': value_payload}
    if assign_custom_field(issue_id, field_id, payload):
        logger.info('Оновлено стан задачі %s на "%s"', issue_id_readable, desired_state)
        return True

    logger.debug('YouTrack customFields повернув помилку під час оновлення стану')
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

    project_custom: Mapping[str, object] | dict[str, object] = (
        as_mapping(assignee_field.get('projectCustomField')) or {}
    )
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
