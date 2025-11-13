"""Надає допоміжні функції для авторизації користувачів через YouTrack."""

from __future__ import annotations

import importlib
import logging
import time
from collections.abc import Iterable, Mapping
from typing import Any

from agromat_it_desk_bot.config import (
    PROJECT_ID,
    PROJECT_KEY,
    YT_BASE_URL,
    YT_TOKEN,
    YT_VALIDATE_RETRIES,
    YT_VALIDATE_TIMEOUT,
)

requests: Any = importlib.import_module('requests')

logger: logging.Logger = logging.getLogger(__name__)

_USER_FIELDS: str = 'id,login,email,ringId,fullName,profile(email,username)'
_TEAM_FIELDS: str = 'users(id,login),memberships(user(id,login))'


class TemporaryYouTrackError(RuntimeError):
    """Позначає тимчасову недоступність YouTrack API."""


class InvalidTokenError(RuntimeError):
    """Позначає, що наданий токен некоректний або відкликаний."""


def validate_token(token: str) -> tuple[bool, dict[str, object]]:
    """Перевіряє персональний токен YouTrack та повертає інформацію про користувача.

    :param token: Персональний токен користувача.
    :returns: Пару ``(is_valid, payload)``.
    :raises TemporaryYouTrackError: Якщо YouTrack тимчасово недоступний.
    """
    normalized: str = token.strip()
    if not normalized:
        logger.debug('Перевірка токена: порожній рядок')
        return False, {}
    if not normalized.isascii():
        logger.info('Перевірка токена: виявлено не-ASCII символи')
        return False, {}

    headers: dict[str, str] = {
        'Authorization': f'Bearer {normalized}',
        'Accept': 'application/json',
    }

    for attempt in range(1, YT_VALIDATE_RETRIES + 1):
        try:
            response: requests.Response = requests.get(
                f'{YT_BASE_URL}/api/users/me',
                params={'fields': _USER_FIELDS},
                headers=headers,
                timeout=YT_VALIDATE_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.warning('Спроба %s: не вдалося перевірити токен у YouTrack: %s', attempt, exc)
            _maybe_wait(attempt)
            if attempt == YT_VALIDATE_RETRIES:
                raise TemporaryYouTrackError('YouTrack тимчасово недоступний') from exc
            continue

        if response.status_code in (401, 403):
            logger.info('Перевірка токена завершилася невдачею: код %s', response.status_code)
            return False, {}

        if response.status_code >= 500:
            logger.warning('YouTrack повернув %s під час перевірки токена', response.status_code)
            _maybe_wait(attempt)
            if attempt == YT_VALIDATE_RETRIES:
                raise TemporaryYouTrackError('YouTrack тимчасово недоступний')
            continue

        if not response.ok:
            logger.error('YouTrack повернув неочікувану відповідь: %s', response.text)
            return False, {}

        payload_raw: object = response.json() or {}
        payload: dict[str, object] = payload_raw if isinstance(payload_raw, dict) else {}
        logger.debug('Перевірка токена успішна: отримано поля %s', list(payload))
        return True, payload

    return False, {}


def is_member_of_project(yt_user_id: str, project_identifier: str | None = None) -> bool:
    """Перевіряє, чи належить користувач до заданого проєкту YouTrack.

    :param yt_user_id: Ідентифікатор користувача YouTrack.
    :param project_identifier: Ідентифікатор чи ключ проєкту (опційно).
    :returns: ``True`` якщо користувач входить до команди проєкту.
    :raises TemporaryYouTrackError: Якщо YouTrack тимчасово недоступний.
    :raises RuntimeError: Якщо конфігурацію проєкту не налаштовано.
    """
    project_ref: str | None = project_identifier or PROJECT_ID or PROJECT_KEY
    if not project_ref:
        raise RuntimeError('PROJECT_KEY або PROJECT_ID не налаштовано')

    headers: dict[str, str] = _service_headers()

    try:
        response: requests.Response = requests.get(
            f'{YT_BASE_URL}/youtrack/api/admin/projects/{project_ref}/team',
            params={'fields': _TEAM_FIELDS},
            headers=headers,
            timeout=YT_VALIDATE_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning('Не вдалося отримати команди проєкту %s: %s', project_ref, exc)
        raise TemporaryYouTrackError('YouTrack тимчасово недоступний') from exc

    if response.status_code == 404:
        logger.error('Проєкт %s не знайдено або недоступний', project_ref)
        raise RuntimeError('Проєкт не знайдено або недоступний')

    if response.status_code >= 500:
        logger.warning('YouTrack повернув %s під час перевірки членства', response.status_code)
        raise TemporaryYouTrackError('YouTrack тимчасово недоступний')

    if not response.ok:
        logger.error('Неочікувана відповідь від YouTrack: %s', response.text)
        return False

    teams_raw: object = response.json() or []
    for team in _as_iterable(teams_raw):
        if not isinstance(team, Mapping):
            continue
        if _team_contains_user(team, yt_user_id):
            logger.debug('Користувач %s знайдений у складі команди', yt_user_id)
            return True

    logger.info('Користувач %s не входить до проєкту %s', yt_user_id, project_ref)
    return False


def normalize_user(payload: Mapping[str, object]) -> tuple[str, str | None, str]:
    """Витягує логін, email та ідентифікатор користувача зі відповіді YouTrack.

    :param payload: Дані користувача з ``/api/users/me``.
    :returns: Пару ``(login, email, yt_user_id)``.
    :raises InvalidTokenError: Якщо дані неповні.
    """
    login: str | None = _extract_string(
        payload,
        'login',
        'ringId',
        'name',
        'fullName',
        'username',
    )
    if login is None:
        profile_obj: object | None = payload.get('profile')
        profile: Mapping[str, object] | None = profile_obj if isinstance(profile_obj, Mapping) else None
        if profile is not None:
            login = _extract_string(profile, 'login', 'username', 'name')

    user_id_obj: object | None = payload.get('id')
    if login is None:
        logger.error('Відповідь YouTrack не містить логіна')
        raise InvalidTokenError('Неможливо визначити логін користувача')

    if not isinstance(user_id_obj, str) or not user_id_obj.strip():
        logger.error('Відповідь YouTrack не містить ідентифікатора користувача')
        raise InvalidTokenError('Неможливо визначити користувача YouTrack')

    email: str | None = _extract_string(payload, 'email')
    if email is None:
        profile_obj = payload.get('profile')
        profile = profile_obj if isinstance(profile_obj, Mapping) else None
        if profile is not None:
            email = _extract_string(profile, 'email', 'emailAddress')

    yt_user_id: str = user_id_obj.strip()
    return login.strip(), email, yt_user_id


def _service_headers() -> dict[str, str]:
    """Повертає заголовки для службових запитів YouTrack."""
    if not YT_TOKEN:
        raise RuntimeError('YT_TOKEN не налаштовано для сервісних викликів')
    return {
        'Authorization': f'Bearer {YT_TOKEN}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }


def _team_contains_user(team: Mapping[str, object], yt_user_id: str) -> bool:
    """Перевіряє, чи присутній користувач у складі однієї команди."""
    memberships: Iterable[object] = _as_iterable(team.get('memberships'))
    if _entries_contain_user(memberships, yt_user_id, key='user'):
        return True
    users: Iterable[object] = _as_iterable(team.get('users'))
    return _entries_contain_user(users, yt_user_id)


def _entries_contain_user(entries: Iterable[object], yt_user_id: str, *, key: str | None = None) -> bool:
    """Шукає користувача у переданій послідовності записів."""
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        candidate: object | None = entry.get(key) if key else entry
        if isinstance(candidate, Mapping) and str(candidate.get('id')) == yt_user_id:
            return True
    return False


def _as_iterable(value: object) -> Iterable[object]:
    """Повертає значення як ітеративну послідовність."""
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _extract_string(source: Mapping[str, object], *keys: str) -> str | None:
    """Повертає перший непорожній рядок з переданих ключів."""
    for key in keys:
        candidate: object | None = source.get(key)
        if isinstance(candidate, str):
            stripped: str = candidate.strip()
            if stripped:
                return stripped
    return None


def _maybe_wait(attempt: int) -> None:
    """Додає експоненційний backoff між повторними спробами."""
    delay: float = min(5.0, 0.5 * (2 ** (attempt - 1)))
    time.sleep(delay)
