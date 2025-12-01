"""Implements business logic of bot user authorization."""

from __future__ import annotations

import hashlib
import logging
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone
from enum import Enum
from threading import Lock

import agromat_it_desk_bot.config as app_config
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
    """Signal an error during user registration."""


class RegistrationOutcome(str, Enum):
    """Describe possible outcomes of user registration."""

    SUCCESS = 'success'
    ALREADY_CONNECTED = 'already_connected'
    FOREIGN_OWNER = 'foreign_owner'


def register_user(tg_user_id: int, token_plain: str) -> RegistrationOutcome:  # noqa: C901
    """Register user using personal YouTrack token.

    :param tg_user_id: Telegram user identifier.
    :param token_plain: Personal YouTrack token.
    :returns: Registration result.
    :raises RegistrationError: If token invalid or user not in project.
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
    token_encrypted: str = _encrypt_token(token_plain)
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
            'token_encrypted': token_encrypted,
            'is_active': True,
            'last_seen_at': now,
            'registered_at': registered_at,
            'created_at': registered_at,
        },
    )
    logger.info('Користувача активовано: tg_user_id=%s yt_user_id=%s', tg_user_id, yt_user_id)
    return outcome


def is_authorized(tg_user_id: int) -> bool:
    """Check whether user has active access to bot.

    :param tg_user_id: Telegram user ID.
    :returns: ``True`` if user is activated.
    """
    _ensure_migrated()
    record = fetch_user_by_tg_id(tg_user_id)
    if record is None or not record.get('is_active'):
        return False

    touch_last_seen(tg_user_id)
    return True


def get_authorized_yt_user(tg_user_id: int) -> tuple[str | None, str | None, str | None]:
    """Return YouTrack user data if authorized.

    :param tg_user_id: Telegram user ID.
    :returns: ``(login, email, yt_user_id)`` or ``(None, None, None)``.
    """
    _ensure_migrated()
    record = fetch_user_by_tg_id(tg_user_id)
    if record is None or not record.get('is_active'):
        return None, None, None

    login: str | None = record.get('yt_login')
    email: str | None = record.get('yt_email')
    yt_user_id: str | None = record.get('yt_user_id')
    return login, email, yt_user_id


def get_user_token(tg_user_id: int) -> str | None:
    """Return user's personal token for YouTrack calls."""
    _ensure_migrated()
    record = fetch_user_by_tg_id(tg_user_id)
    if record is None or not record.get('is_active'):
        return None
    encrypted_obj: object | None = record.get('token_encrypted')
    encrypted: str | None = encrypted_obj if isinstance(encrypted_obj, str) else None
    if not encrypted:
        return None
    token: str | None = _decrypt_token(encrypted)
    if token is None:
        logger.warning('Не вдалося дешифрувати токен користувача tg_user_id=%s', tg_user_id)
    return token


def deactivate_user(tg_user_id: int) -> None:
    """Disable user access and remove token hash.

    :param tg_user_id: Telegram user ID.
    """
    _ensure_migrated()
    storage_deactivate_user(tg_user_id)
    logger.info('Користувача деактивовано: tg_user_id=%s', tg_user_id)


def _hash_token(token_plain: str) -> str:
    """Compute SHA-256 hash of token."""
    digest = hashlib.sha256()
    digest.update(token_plain.encode('utf-8'))
    return digest.hexdigest()


def _encrypt_token(token_plain: str) -> str:
    """Encrypt personal token for storage in DB."""
    key: bytes | None = _token_secret_bytes(strict=True)
    if key is None:  # pragma: no cover - handled in strict mode
        raise RegistrationError('USER_TOKEN_SECRET не налаштовано')
    encrypted: bytes = _xor_bytes(token_plain.encode('utf-8'), key)
    return urlsafe_b64encode(encrypted).decode('ascii')


def _decrypt_token(token_encrypted: str) -> str | None:
    """Decrypt user token."""
    key: bytes | None = _token_secret_bytes(strict=False)
    if key is None:
        return None
    try:
        data: bytes = urlsafe_b64decode(token_encrypted.encode('ascii'))
    except Exception as exc:  # noqa: BLE001
        logger.error('Невалідний формат шифрованого токена: %s', exc)
        return None
    decrypted: bytes = _xor_bytes(data, key)
    try:
        return decrypted.decode('utf-8')
    except UnicodeDecodeError:
        logger.error('Не вдалося розкодувати токен після дешифрування')
        return None


def _token_secret_bytes(strict: bool) -> bytes | None:
    """Return key for token encryption."""
    secret: str | None = app_config.USER_TOKEN_SECRET
    if not secret:
        if strict:
            raise RegistrationError('USER_TOKEN_SECRET не налаштовано')
        logger.error('USER_TOKEN_SECRET не налаштовано')
        return None
    digest = hashlib.sha256()
    digest.update(secret.encode('utf-8'))
    return digest.digest()


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """Perform XOR encryption/decryption."""
    key_len: int = len(key)
    return bytes(byte ^ key[index % key_len] for index, byte in enumerate(data))


def _utcnow() -> str:
    """Return current time in ISO format."""
    return datetime.now(tz=timezone.utc).isoformat()


def _ensure_migrated() -> None:
    """Run migrations once per process lifetime."""
    global _migrated
    if _migrated:
        return
    with _migration_lock:
        if not _migrated:
            migrate()
            _migrated = True
