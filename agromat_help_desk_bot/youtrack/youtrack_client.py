"""Low-level YouTrack REST API calls."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable, Mapping
from typing import Any, TypedDict, cast

from agromat_help_desk_bot.config import YT_BASE_URL, YT_TOKEN

requests: Any = importlib.import_module('requests')

logger: logging.Logger = logging.getLogger(__name__)


def _ensure_mapping(value: object | None) -> Mapping[str, object]:
    """Return mapping if value is dict, otherwise empty mapping."""
    return value if isinstance(value, dict) else {}


def _extract_text(entry: object | None) -> str | None:
    """Return textual representation of YouTrack field if present."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, Mapping):
        text_obj: object | None = entry.get('text')
        if isinstance(text_obj, str):
            return text_obj
    return None


class CustomField(TypedDict, total=False):
    """Structure of a YouTrack custom field."""

    id: str
    name: str
    value: object
    projectCustomField: object


CustomFieldMap = dict[str, CustomField]


class YouTrackUser(TypedDict, total=False):
    """Set of useful YouTrack user fields."""

    id: str
    login: str
    email: str


def get_issue_internal_id(issue_id_readable: str) -> str | None:
    """Return internal issue ID for ``idReadable``.

    :param issue_id_readable: Short issue identifier (for example ``ABC-123``).
    :returns: Internal ID if issue found, otherwise ``None``.
    """
    headers: dict[str, str] = _base_headers()  # Request headers to YouTrack
    # Search for issue by readable ID via YouTrack REST API
    response: requests.Response = requests.get(
        f'{YT_BASE_URL}/api/issues',
        params={'query': issue_id_readable, 'fields': 'id,idReadable'},
        headers=headers,
        timeout=10,
    )
    logger.debug('YouTrack get_issue_internal_id запит: issue=%s status=%s', issue_id_readable, response.status_code)
    if not response.ok:
        logger.error('Помилка пошуку задачі в YouTrack: %s', response.text)
        return None

    items: list[dict[str, object]] = cast(list[dict[str, object]], response.json() or [])
    # Find first issue matching idReadable
    issue: dict[str, object] | None = next((it for it in items if it.get('idReadable') == issue_id_readable), None)
    if not issue:
        logger.error('Задачу %s не знайдено у YouTrack', issue_id_readable)
        return None

    issue_id: object | None = issue.get('id')
    logger.debug('YouTrack internal id знайдено: issue=%s internal_id=%s', issue_id_readable, issue_id)
    return issue_id if isinstance(issue_id, str) else None


def fetch_issue_custom_fields(issue_internal_id: str, field_names: Iterable[str]) -> CustomFieldMap | None:
    """Fetch custom field descriptions for issue.

    :param issue_internal_id: Internal issue ID.
    :param field_names: Names of fields to find.
    :returns: Mapping ``field name -> description`` or ``None``.
    """
    headers: dict[str, str] = _base_headers()  # Request headers to YouTrack
    # Fetch full customFields list for subsequent filtering
    response: requests.Response = requests.get(
        f'{YT_BASE_URL}/api/issues/{issue_internal_id}',
        params={'fields': 'customFields(id,name,projectCustomField(id,field(id,name),bundle(values(id,name))))'},
        headers=headers,
        timeout=10,
    )
    logger.debug('YouTrack fetch_issue_custom_fields: issue=%s status=%s', issue_internal_id, response.status_code)
    if not response.ok:
        logger.debug('Не вдалося отримати customFields задачі %s: %s', issue_internal_id, response.text)
        return None

    issue_data: dict[str, object] = cast(dict[str, object], response.json() or {})
    custom_fields: list[dict[str, object]] = cast(list[dict[str, object]], issue_data.get('customFields') or [])

    result: CustomFieldMap = {}
    normalized: set[str] = {name.lower() for name in field_names}
    for custom_field in custom_fields:
        project_custom_obj: object | None = custom_field.get('projectCustomField')
        project_custom: Mapping[str, object] = _ensure_mapping(project_custom_obj)  # Field description in project

        field_info_obj: object | None = project_custom.get('field')
        field_info: Mapping[str, object] = _ensure_mapping(field_info_obj)  # Field metadata
        field_name: object | None = field_info.get('name')
        if isinstance(field_name, str) and field_name.lower() in normalized:
            result[field_name.lower()] = cast(CustomField, custom_field)
    logger.debug('YouTrack custom fields знайдено: issue=%s fields=%s', issue_internal_id, list(result))
    return result


def assign_custom_field(
    issue_internal_id: str,
    field_id: str,
    payload: dict[str, object],
    auth_token: str | None = None,
) -> bool:
    """Update custom field value for issue.

    :param issue_internal_id: Internal issue ID.
    :param field_id: Custom field identifier.
    :param payload: Request body with new value.
    :param auth_token: YouTrack token used for request.
    :returns: ``True`` if updated successfully, otherwise ``False``.
    """
    headers: dict[str, str] = _base_headers(auth_token)
    response: requests.Response = requests.post(
        f'{YT_BASE_URL}/api/issues/{issue_internal_id}/customFields/{field_id}',
        params={'fields': 'id'},
        json=payload,
        headers=headers,
        timeout=10,
    )
    logger.debug('YouTrack assign_custom_field: issue=%s field=%s status=%s',
                 issue_internal_id,
                 field_id,
                 response.status_code)
    if not response.ok:
        logger.debug('YouTrack customFields повернув помилку: %s', response.text)
        return False
    return True


def find_user(login: str | None, email: str | None) -> YouTrackUser | None:
    """Return YouTrack user description by login."""
    if not login:
        logger.warning('find_user викликано без логіна (email=%s)', email)
        return None

    users: list[dict[str, object]] | None = _search_users(login)
    if not users:
        logger.warning('Користувача login=%s не знайдено у YouTrack', login)
        return None

    candidate: Mapping[str, object] | None = None
    for user in users:
        login_candidate: object | None = user.get('login')
        if isinstance(login_candidate, str) and login_candidate == login:
            candidate = user
            break

    if candidate is None:
        logger.warning('Серед результатів запиту login=%s немає точного збігу', login)
        return None

    mapped: YouTrackUser | None = _map_user(candidate)
    if mapped:
        return mapped

    logger.warning('Не вдалося спроєктувати користувача YouTrack login=%s', login)
    return None


def find_user_id(login: str | None, email: str | None) -> str | None:
    """Determine user ID by login or email."""
    user: YouTrackUser | None = find_user(login, email)
    if user is None:
        return None

    user_id: str | None = user.get('id')
    return user_id if isinstance(user_id, str) else None


def fetch_issue_overview(issue_internal_id: str) -> Mapping[str, object] | None:
    """Return main issue fields along with custom fields.

    :param issue_internal_id: Internal YouTrack issue ID.
    :returns: Dict with ``summary``, ``description`` and ``customFields``.
    """
    headers: dict[str, str] = _base_headers()
    response: requests.Response = requests.get(
        f'{YT_BASE_URL}/api/issues/{issue_internal_id}',
        params={
            'fields': (
                'summary,description,'
                'reporter(fullName,name,login,email),'
                'createdBy(fullName,name,login,email),'
                'assignee(fullName,name,login,email),'
                'customFields('
                'name,value('
                'name,fullName,login,email,localizedName,presentation,text'
                ')'
                ')'
            ),
        },
        headers=headers,
        timeout=10,
    )
    logger.debug('YouTrack fetch_issue_overview: issue=%s status=%s', issue_internal_id, response.status_code)
    if not response.ok:
        logger.debug('Не вдалося отримати дані задачі %s: %s', issue_internal_id, response.text)
        return None
    return cast(dict[str, object], response.json() or {})


def _search_users(query: str) -> list[dict[str, object]] | None:
    """Perform user search in YouTrack by arbitrary query."""
    headers: dict[str, str] = _base_headers()  # Заголовки запиту до YouTrack
    users_endpoint: str = f'{YT_BASE_URL}/api/users'
    response: requests.Response = requests.get(
        users_endpoint,
        params={'query': query, 'fields': 'id,login,email'},
        headers=headers,
        timeout=10,
    )
    logger.debug('YouTrack пошук користувачів: query=%s status=%s', query, response.status_code)
    if not response.ok:
        logger.error('Помилка пошуку користувача %s у YouTrack: %s', query, response.text)
        return None

    return cast(list[dict[str, object]], response.json() or [])


def _map_user(candidate: Mapping[str, object]) -> YouTrackUser | None:
    """Normalize user record to ``YouTrackUser``."""
    result: YouTrackUser = {}

    id_val: object | None = candidate.get('id')
    if isinstance(id_val, str):
        result['id'] = id_val

    login_val: object | None = candidate.get('login')
    if isinstance(login_val, str):
        result['login'] = login_val

    email_val: object | None = candidate.get('email')
    if isinstance(email_val, str):
        result['email'] = email_val

    return result or None


def find_state_value_id(field_data: CustomField, desired_state: str) -> str | None:
    """Find state value identifier inside custom field bundle.

    :param field_data: Опис кастомного поля, отриманий із YouTrack.
    :param desired_state: Назва стану, яке шукають.
    :returns: Ідентифікатор значення стану або ``None``.
    """
    project_custom_obj: object | None = field_data.get('projectCustomField')
    project_custom: Mapping[str, object] = _ensure_mapping(project_custom_obj)  # State field configuration

    bundle_obj: object | None = project_custom.get('bundle')
    bundle: Mapping[str, object] = _ensure_mapping(bundle_obj)  # Bundle with state values
    values: list[dict[str, object]] = cast(list[dict[str, object]], bundle.get('values') or [])
    desired_normalized: str = desired_state.strip().casefold()

    for value in values:
        candidates: set[str] = {
            extracted.strip().casefold()
            for key in ('name', 'localizedName', 'value', 'idReadable')
            if (extracted := _extract_text(value.get(key)))
        }

        if desired_normalized in candidates and isinstance(value.get('id'), str):
            return str(value['id'])
    return None


def _base_headers(token_override: str | None = None) -> dict[str, str]:
    """Return default headers for YouTrack API calls."""
    token: str | None = token_override or YT_TOKEN
    if not token:
        raise RuntimeError('YT_TOKEN не налаштовано')
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }


def update_issue_summary(issue_id: str, summary: str) -> bool:
    """Update issue summary via REST API."""
    headers: dict[str, str] = _base_headers()
    response: requests.Response = requests.post(
        f'{YT_BASE_URL}/api/issues/{issue_id}',
        params={'fields': 'id'},
        json={'summary': summary},
        headers=headers,
        timeout=10,
    )
    if not response.ok:
        logger.debug('Не вдалося оновити summary issue=%s: %s', issue_id, response.text)
        return False
    return True
