"""Provide higher-level YouTrack operations: user mapping and state updates."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import NamedTuple

from .youtrack_client import (
    CustomField,
    CustomFieldMap,
    assign_custom_field,
    fetch_issue_custom_fields,
    fetch_issue_overview,
    find_state_value_id,
    get_issue_internal_id,
    update_issue_summary,
)

from agromat_help_desk_bot.auth import get_authorized_yt_user
from agromat_help_desk_bot.config import YOUTRACK_STATE_FIELD_NAME, YOUTRACK_STATE_IN_PROGRESS
from agromat_help_desk_bot.messages import Msg, render
from agromat_help_desk_bot.utils import extract_issue_assignee, extract_issue_author, extract_issue_status

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


class IssueDetails(NamedTuple):
    """Describe core issue info for message updates."""

    summary: str
    description: str
    assignee: str | None
    status: str | None
    author: str | None


def resolve_account(tg_user_id: int | None) -> tuple[str | None, str | None, str | None]:
    """Return authorized YouTrack user data by Telegram ID.

    :param tg_user_id: Telegram user ID.
    :returns: Login, email and internal YouTrack user ID.
    """
    if tg_user_id is None:
        logger.debug('resolve_account викликано без tg_user_id')
        return None, None, None
    login, email, yt_user_id = get_authorized_yt_user(tg_user_id)
    logger.debug('resolve_account: tg_user_id=%s yt_user_id=%s', tg_user_id, yt_user_id)
    return login, email, yt_user_id


def fetch_issue_details(issue_id_readable: str) -> IssueDetails | None:
    """Fetch current issue data to update Telegram message.

    :param issue_id_readable: External issue ID (``ABC-123``).
    :returns: ``IssueDetails`` or ``None`` if unavailable.
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
    """Move issue to "in progress" after user confirmation.

    :param issue_id_readable: Short issue ID (``ABC-123``).
    :param login: YouTrack login (for logging).
    :param email: YouTrack email.
    :param user_id: Internal user ID (optional).
    :param user_token: Personal user token for REST request.
    :returns: ``True`` if status updated.
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
    """Pick first field from provided names."""
    for name in names:
        field: CustomField | None = fields.get(name.lower())
        if field is not None:
            return field
    return None


def _ensure_in_progress(issue_id: str, issue_id_readable: str, auth_token: str | None) -> bool:
    """Set issue status to \"in progress\" if configured."""
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


def ensure_summary_placeholder(
    issue_id_readable: str,
    normalized_summary: str,
    issue_internal_id: str | None = None,
) -> None:
    """Update issue summary in YouTrack when placeholder must be applied."""
    placeholder: str = render(Msg.YT_EMAIL_SUBJECT_MISSING)
    if normalized_summary != placeholder:
        return
    target_id: str = issue_internal_id or issue_id_readable
    if update_issue_summary(target_id, normalized_summary):
        logger.info('Summary задачі %s оновлено на плейсхолдер', issue_id_readable)
    else:
        logger.warning('Не вдалося оновити summary задачі %s', issue_id_readable)
