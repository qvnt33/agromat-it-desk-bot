"""Забезпечує вищерівневі операції з YouTrack: мапінг користувачів та оновлення стану."""

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
    get_issue_internal_id,
)

from agromat_it_desk_bot.auth import get_authorized_yt_user
from agromat_it_desk_bot.config import YOUTRACK_STATE_FIELD_NAME, YOUTRACK_STATE_IN_PROGRESS
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


def assign_issue(
    issue_id_readable: str,
    login: str | None,
    email: str | None,
    user_id: str | None,
    user_token: str | None,
) -> bool:
    """Переводить задачу в стан «в роботі» після підтвердження користувачем.

    :param issue_id_readable: Короткий ID задачі (``ABC-123``).
    :param login: Логін користувача YouTrack (використовується для журналювання).
    :param email: Email користувача YouTrack.
    :param user_id: Внутрішній ID користувача (може бути ``None``).
    :param user_token: Персональний токен користувача для REST-запиту.
    :returns: ``True`` якщо статус оновлено.
    """
    logger.debug('Отримано запит оновлення статусу: issue=%s login=%s email=%s yt_user_id=%s',
                 issue_id_readable,
                 login,
                 email,
                 user_id)
    issue_id: str | None = get_issue_internal_id(issue_id_readable)
    if issue_id is None:
        logger.warning('Не знайдено внутрішній ID задачі: %s', issue_id_readable)
        return False

    status_updated: bool = _ensure_in_progress(issue_id, issue_id_readable, user_token)
    if status_updated:
        logger.info(
            'Статус задачі %s переведено у %s користувачем login=%s email=%s yt_user_id=%s',
            issue_id_readable,
            YOUTRACK_STATE_IN_PROGRESS,
            login,
            email,
            user_id,
        )
    return status_updated


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


def _ensure_in_progress(issue_id: str, issue_id_readable: str, auth_token: str | None) -> bool:
    """Встановлює статус задачі у значення «в роботі», якщо налаштовано."""
    if not auth_token:
        logger.warning('Відсутній персональний токен для оновлення задачі %s', issue_id_readable)
        return False
    state_field_name: str | None = YOUTRACK_STATE_FIELD_NAME
    desired_state: str | None = YOUTRACK_STATE_IN_PROGRESS
    if not state_field_name or not desired_state:
        logger.debug('Статус не налаштовано: field=%s desired=%s', state_field_name, desired_state)
        return False

    fields_optional: CustomFieldMap | None = fetch_issue_custom_fields(issue_id, {state_field_name})
    if not fields_optional:
        logger.warning('Поле стану %s не знайдено у задачі %s', state_field_name, issue_id_readable)
        return False

    field: CustomField | None = _pick_field(fields_optional, {state_field_name})
    if field is None:
        logger.warning('Поле стану %s відсутнє у задачі %s', state_field_name, issue_id_readable)
        return False

    state_id: str | None = find_state_value_id(field, desired_state)
    if state_id is None:
        logger.warning('Значення стану %s не знайдено у задачі %s', desired_state, issue_id_readable)
        return False

    payload: dict[str, object] = {'value': {'id': state_id}}
    project_custom_obj: object | None = field.get('projectCustomField')
    project_custom: Mapping[str, object] = (
        project_custom_obj if isinstance(project_custom_obj, dict) else {}
    )
    field_id_obj: object | None = project_custom.get('id')
    if not isinstance(field_id_obj, str):
        logger.warning('ID поля стану відсутній у задачі %s', issue_id_readable)
        return False

    if assign_custom_field(issue_id, field_id_obj, payload, auth_token=auth_token):
        logger.info('Статус задачі %s оновлено на %s', issue_id_readable, desired_state)
        return True

    logger.warning('Не вдалося оновити статус задачі %s на %s', issue_id_readable, desired_state)
    return False
