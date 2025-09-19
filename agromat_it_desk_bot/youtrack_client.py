"""Низькорівневі виклики YouTrack REST API."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import TypedDict, cast

import requests

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


def get_issue_internal_id(issue_id_readable: str) -> str | None:
    """Повернути внутрішній ID задачі за ``idReadable``.

    :param issue_id_readable: Короткий ідентифікатор задачі (наприклад, ``ABC-123``).
    :type issue_id_readable: str
    :returns: Внутрішній ID, якщо задачу знайдено, інакше ``None``.
    :rtype: str | None
    """
    headers: dict[str, str] = _base_headers()
    # Пошук задачі за коротким ID за допомогою REST API YouTrack
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
    """Отримати опис кастомних полів задачі.

    :param issue_internal_id: Внутрішній ID задачі.
    :type issue_internal_id: str
    :param field_names: Назви полів, які необхідно знайти.
    :type field_names: Iterable[str]
    :returns: Словник ``назва поля -> опис`` або ``None``.
    :rtype: dict[str, object] | None
    """
    headers: dict[str, str] = _base_headers()
    # Повернути повний список customFields для подальшої фільтрації
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
        project_custom: Mapping[str, object] | dict[str, object] = as_mapping(custom_field.get(
            'projectCustomField')) or {}
        field_info: Mapping[str, object] | dict[str, object] = as_mapping(project_custom.get(
            'field')) or {}
        field_name: object | None = field_info.get('name')
        if isinstance(field_name, str) and field_name.lower() in normalized:
            result[field_name.lower()] = cast(CustomField, custom_field)
    return result


def assign_custom_field(issue_internal_id: str, field_id: str, payload: dict[str, object]) -> bool:
    """Оновити значення custom field для задачі.

    :param issue_internal_id: Внутрішній ID задачі.
    :type issue_internal_id: str
    :param field_id: Ідентифікатор кастомного поля.
    :type field_id: str
    :param payload: Тіло запиту з новим значенням.
    :type payload: dict[str, object]
    :returns: ``True`` у разі успішного оновлення, інакше ``False``.
    :rtype: bool
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


def find_user_id(login: str | None, email: str | None) -> str | None:
    """Визначити ID користувача за логіном або email.

    :param login: Логін користувача у YouTrack.
    :type login: str | None
    :param email: Email користувача у YouTrack.
    :type email: str | None
    :returns: Внутрішній ID користувача або ``None``.
    :rtype: str | None
    """
    if not (login or email):
        return None

    headers: dict[str, str] = _base_headers()
    response: requests.Response = requests.get(
        f'{YT_BASE_URL}/api/users',
        params={'query': login or email or '', 'fields': 'id,login,email'},
        headers=headers,
        timeout=10,
    )
    if not response.ok:
        logger.error('Помилка пошуку користувача %s у YouTrack: %s', login or email, response.text)
        return None

    users: list[dict[str, object]] = cast(list[dict[str, object]], response.json() or [])
    candidate = None
    if login:
        candidate: dict[str, object] | None = next((user for user in users if user.get('login') == login), None)
    if candidate is None and email:
        candidate = next((user for user in users if user.get('email') == email), None)

    user_id: object | None = candidate.get('id') if isinstance(candidate, dict) else None
    return user_id if isinstance(user_id, str) else None


def find_state_value_id(field_data: CustomField, desired_state: str) -> str | None:
    """Знайти ідентифікатор значення стану у бандлі кастомного поля.

    :param field_data: Опис кастомного поля, отриманий із YouTrack.
    :type field_data: dict[str, object]
    :param desired_state: Назва стану, яке шукаємо.
    :type desired_state: str
    :returns: Ідентифікатор значення стану або ``None``.
    :rtype: str | None
    """
    project_custom: Mapping[str, object] | dict[str, object] = as_mapping(field_data.get('projectCustomField')) or {}
    bundle: Mapping[str, object] | dict[str, object] = as_mapping(project_custom.get('bundle')) or {}
    values: list[dict[str, object]] = cast(list[dict[str, object]], bundle.get('values') or [])
    # Перевірити усі доступні значення стану та знайти потрібне
    for value in values:
        if value.get('name') == desired_state and isinstance(value.get('id'), str):
            return str(value['id'])
    return None


def _base_headers() -> dict[str, str]:
    """Повернути стандартні заголовки для викликів YouTrack API."""
    assert YT_TOKEN
    return {
        'Authorization': f'Bearer {YT_TOKEN}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
