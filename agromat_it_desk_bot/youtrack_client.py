"""Низькорівневі виклики YouTrack REST API."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import TypedDict, cast

import requests  # type: ignore[import-untyped]

from agromat_it_desk_bot.config import YT_BASE_URL, YT_TOKEN
from agromat_it_desk_bot.utils import as_mapping

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


class CustomField(TypedDict, total=False):
    """Структура кастомного поля YouTrack."""

    id: str
    name: str
    value: object
    projectCustomField: object


CustomFieldMap = dict[str, CustomField]


class YouTrackUser(TypedDict, total=False):
    """Перелік корисних полів користувача YouTrack."""

    id: str
    login: str
    email: str


def get_issue_internal_id(issue_id_readable: str) -> str | None:
    """Повертає внутрішній ID задачі за ``idReadable``.

    :param issue_id_readable: Короткий ідентифікатор задачі (наприклад, ``ABC-123``).
    :returns: Внутрішній ID, якщо задачу знайдено, інакше ``None``.
    """
    headers: dict[str, str] = _base_headers()
    # Виконують пошук задачі за коротким ID за допомогою REST API YouTrack
    response: requests.Response = requests.get(
        f'{YT_BASE_URL}/api/issues',
        params={'query': issue_id_readable, 'fields': 'id,idReadable'},
        headers=headers,
        timeout=10,
    )
    if not response.ok:
        logger.error('Помилка пошуку задачі в YouTrack: %s', response.text)
        return None

    items: list[dict[str, object]] = cast(list[dict[str, object]], response.json() or [])
    issue: dict[str, object] | None = next((it for it in items if it.get('idReadable') == issue_id_readable), None)
    if not issue:
        logger.error('Задачу %s не знайдено у YouTrack', issue_id_readable)
        return None

    issue_id: object | None = issue.get('id')
    return issue_id if isinstance(issue_id, str) else None


def fetch_issue_custom_fields(issue_internal_id: str, field_names: Iterable[str]) -> CustomFieldMap | None:
    """Отримує опис кастомних полів задачі.

    :param issue_internal_id: Внутрішній ID задачі.
    :param field_names: Назви полів, які необхідно знайти.
    :returns: Словник ``назва поля -> опис`` або ``None``.
    """
    headers: dict[str, str] = _base_headers()
    # Отримують повний список customFields для подальшої фільтрації
    response: requests.Response = requests.get(
        f'{YT_BASE_URL}/api/issues/{issue_internal_id}',
        params={'fields': 'customFields(id,name,projectCustomField(id,field(id,name),bundle(values(id,name))))'},
        headers=headers,
        timeout=10,
    )
    if not response.ok:
        logger.debug('Не вдалося отримати customFields задачі %s: %s', issue_internal_id, response.text)
        return None

    issue_data: dict[str, object] = cast(dict[str, object], response.json() or {})
    custom_fields: list[dict[str, object]] = cast(list[dict[str, object]], issue_data.get('customFields') or [])

    result: CustomFieldMap = {}
    normalized: set[str] = {name.lower() for name in field_names}
    for custom_field in custom_fields:
        project_custom: Mapping[str, object] | dict[str, object] = (
            as_mapping(custom_field.get('projectCustomField')) or {}
        )
        field_info: Mapping[str, object] | dict[str, object] = as_mapping(project_custom.get('field')) or {}
        field_name: object | None = field_info.get('name')
        if isinstance(field_name, str) and field_name.lower() in normalized:
            result[field_name.lower()] = cast(CustomField, custom_field)
    return result


def assign_custom_field(issue_internal_id: str, field_id: str, payload: dict[str, object]) -> bool:
    """Оновлює значення custom field для задачі.

    :param issue_internal_id: Внутрішній ID задачі.
    :param field_id: Ідентифікатор кастомного поля.
    :param payload: Тіло запиту з новим значенням.
    :returns: ``True`` у разі успішного оновлення, інакше ``False``.
    """
    headers: dict[str, str] = _base_headers()
    response: requests.Response = requests.post(
        f'{YT_BASE_URL}/api/issues/{issue_internal_id}/customFields/{field_id}',
        params={'fields': 'id'},
        json=payload,
        headers=headers,
        timeout=10,
    )
    if not response.ok:
        logger.debug('YouTrack customFields повернув помилку: %s', response.text)
        return False
    return True


def find_user(login: str | None, email: str | None) -> YouTrackUser | None:
    """Повертає опис користувача YouTrack за логіном."""
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
    """Визначає ID користувача за логіном або email."""
    user: YouTrackUser | None = find_user(login, email)
    if user is None:
        return None

    user_id: str | None = user.get('id')
    return user_id if isinstance(user_id, str) else None


def _search_users(query: str) -> list[dict[str, object]] | None:
    """Виконує пошук користувачів у YouTrack за довільним запитом."""
    headers: dict[str, str] = _base_headers()
    users_endpoint: str = f'{YT_BASE_URL}/api/users'
    response: requests.Response = requests.get(
        users_endpoint,
        params={'query': query, 'fields': 'id,login,email'},
        headers=headers,
        timeout=10,
    )
    if not response.ok:
        logger.error('Помилка пошуку користувача %s у YouTrack: %s', query, response.text)
        return None

    return cast(list[dict[str, object]], response.json() or [])


def _map_user(candidate: Mapping[str, object]) -> YouTrackUser | None:
    """Приводить запис користувача до ``YouTrackUser``."""
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
    """Знаходить ідентифікатор значення стану у бандлі кастомного поля.

    :param field_data: Опис кастомного поля, отриманий із YouTrack.
    :param desired_state: Назва стану, яке шукають.
    :returns: Ідентифікатор значення стану або ``None``.
    """
    project_custom: Mapping[str, object] | dict[str, object] = as_mapping(field_data.get('projectCustomField')) or {}
    bundle: Mapping[str, object] | dict[str, object] = as_mapping(project_custom.get('bundle')) or {}
    values: list[dict[str, object]] = cast(list[dict[str, object]], bundle.get('values') or [])
    desired_normalized: str = desired_state.strip().casefold()

    def _extract_text(entry: object | None) -> str | None:
        if isinstance(entry, str):
            return entry
        if isinstance(entry, Mapping):
            text_obj: object | None = entry.get('text')
            if isinstance(text_obj, str):
                return text_obj
        return None

    for value in values:
        candidates: set[str] = set()
        for key in ('name', 'localizedName', 'value', 'idReadable'):
            raw: object | None = value.get(key)
            extracted: str | None = _extract_text(raw)
            if extracted:
                candidates.add(extracted.strip().casefold())

        if desired_normalized in candidates and isinstance(value.get('id'), str):
            return str(value['id'])
    return None


def _base_headers() -> dict[str, str]:
    """Повертає стандартні заголовки для викликів YouTrack API."""
    assert YT_TOKEN
    return {'Authorization': f'Bearer {YT_TOKEN}', 'Accept': 'application/json', 'Content-Type': 'application/json'}
