"""Виконує бізнес-логіку авторизації користувачів бота."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from enum import Enum
from threading import Lock

from agromat_it_desk_bot.storage import deactivate_user as storage_deactivate_user
from agromat_it_desk_bot.storage import (
    fetch_user_by_tg_id,
    fetch_user_by_yt_id,
    migrate,
    touch_last_seen,
    upsert_user,
)
from agromat_it_desk_bot.youtrack.youtrack_auth_service import (
    InvalidTokenError,
    TemporaryYouTrackError,
    is_member_of_project,
    normalize_user,
    validate_token,
)

logger: logging.Logger = logging.getLogger(__name__)

_migration_lock: Lock = Lock()
_migrated: bool = False


class RegistrationError(RuntimeError):
    """Сигналізує про помилку під час реєстрації користувача."""


class RegistrationOutcome(str, Enum):
    """Описує можливі результати реєстрації користувача."""

    SUCCESS = 'success'
    ALREADY_CONNECTED = 'already_connected'
    FOREIGN_OWNER = 'foreign_owner'


def register_user(tg_user_id: int, token_plain: str) -> RegistrationOutcome:
    """Реєструє користувача на основі персонального токена YouTrack.

    :param tg_user_id: Ідентифікатор користувача Telegram.
    :param token_plain: Персональний токен YouTrack.
    :returns: Результат реєстрації.
    :raises RegistrationError: Якщо токен некоректний або користувач не у проєкті.
    """
    try:
        is_valid, payload = validate_token(token_plain)
    except TemporaryYouTrackError as exc:
        logger.warning('Перевірка токена тимчасово недоступна: tg_user_id=%s', tg_user_id)
        raise RegistrationError('YouTrack тимчасово недоступний') from exc

    if not is_valid:
        logger.info('Невдала перевірка токена: tg_user_id=%s', tg_user_id)
        raise RegistrationError('Невірний токен або немає членства у проєкті')

    try:
        login, email, yt_user_id = normalize_user(payload)
    except InvalidTokenError as exc:
        logger.error('Неможливо нормалізувати користувача: tg_user_id=%s', tg_user_id)
        raise RegistrationError('Невірний токен або немає членства у проєкті') from exc

    try:
        member: bool = is_member_of_project(yt_user_id)
    except TemporaryYouTrackError as exc:
        logger.warning('Перевірка членства недоступна: tg_user_id=%s yt_user_id=%s', tg_user_id, yt_user_id)
        raise RegistrationError('YouTrack тимчасово недоступний') from exc
    except RuntimeError as exc:
        logger.error('Проблема конфігурації проєкту: %s', exc)
        raise RegistrationError('Помилка конфігурації сервера') from exc

    if not member:
        logger.info('Користувач не входить до проєкту: tg_user_id=%s yt_user_id=%s', tg_user_id, yt_user_id)
        raise RegistrationError('Невірний токен або немає членства у проєкті')

    token_hash: str = _hash_token(token_plain)
    now: str = _utcnow()
    _ensure_migrated()
    owner_record = fetch_user_by_yt_id(yt_user_id)
    outcome: RegistrationOutcome = RegistrationOutcome.SUCCESS
    if owner_record is not None:
        owner_tg_id = int(owner_record['tg_user_id'])
        if owner_tg_id != tg_user_id:
            logger.info(
                'YouTrack акаунт вже привʼязано: tg_user_id=%s yt_user_id=%s власник=%s',
                tg_user_id,
                yt_user_id,
                owner_tg_id,
            )
            return RegistrationOutcome.FOREIGN_OWNER
        stored_hash_obj: object | None = owner_record.get('token_hash')
        stored_hash: str | None = stored_hash_obj if isinstance(stored_hash_obj, str) else None
        if stored_hash and stored_hash == token_hash:
            logger.debug(
                'Токен не змінено: tg_user_id=%s yt_user_id=%s',
                tg_user_id,
                yt_user_id,
            )
            outcome = RegistrationOutcome.ALREADY_CONNECTED

    existing_record = fetch_user_by_tg_id(tg_user_id)
    registered_at: str = now
    if existing_record is not None:
        stored_registered_obj: object | None = existing_record.get('registered_at')
        stored_registered: str | None = (
            stored_registered_obj if isinstance(stored_registered_obj, str) else None
        )
        stored_created_obj: object | None = existing_record.get('created_at')
        stored_created: str | None = stored_created_obj if isinstance(stored_created_obj, str) else None
        if stored_registered:
            registered_at = stored_registered
        elif stored_created:
            registered_at = stored_created
    upsert_user(
        {
            'tg_user_id': tg_user_id,
            'yt_user_id': yt_user_id,
            'yt_login': login,
            'yt_email': email,
            'token_hash': token_hash,
            'token_created_at': now,
            'is_active': True,
            'last_seen_at': now,
            'registered_at': registered_at,
            'created_at': registered_at,
        },
    )
    logger.info('Користувача активовано: tg_user_id=%s yt_user_id=%s', tg_user_id, yt_user_id)
    return outcome


def is_authorized(tg_user_id: int) -> bool:
    """Перевіряє, чи користувач має активний доступ до бота.

    :param tg_user_id: Telegram ID користувача.
    :returns: ``True`` якщо користувач активований.
    """
    _ensure_migrated()
    record = fetch_user_by_tg_id(tg_user_id)
    if record is None or not record.get('is_active'):
        return False

    touch_last_seen(tg_user_id)
    return True


def get_authorized_yt_user(tg_user_id: int) -> tuple[str | None, str | None, str | None]:
    """Повертає дані користувача YouTrack, якщо він авторизований.

    :param tg_user_id: Telegram ID користувача.
    :returns: ``(login, email, yt_user_id)`` або ``(None, None, None)``.
    """
    _ensure_migrated()
    record = fetch_user_by_tg_id(tg_user_id)
    if record is None or not record.get('is_active'):
        return None, None, None

    login: str | None = record.get('yt_login')
    email: str | None = record.get('yt_email')
    yt_user_id: str | None = record.get('yt_user_id')
    return login, email, yt_user_id


def deactivate_user(tg_user_id: int) -> None:
    """Вимикає доступ користувача та видаляє хеш токена.

    :param tg_user_id: Telegram ID користувача.
    """
    _ensure_migrated()
    storage_deactivate_user(tg_user_id)
    logger.info('Користувача деактивовано: tg_user_id=%s', tg_user_id)


def _hash_token(token_plain: str) -> str:
    """Обчислює SHA-256 хеш токена."""
    digest = hashlib.sha256()
    digest.update(token_plain.encode('utf-8'))
    return digest.hexdigest()


def _utcnow() -> str:
    """Повертає поточний час у форматі ISO."""
    return datetime.now(tz=timezone.utc).isoformat()


def _ensure_migrated() -> None:
    """Виконує міграцію таблиць один раз за життєвий цикл процесу."""
    global _migrated
    if _migrated:
        return
    with _migration_lock:
        if not _migrated:
            migrate()
            _migrated = True
