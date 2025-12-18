"""Тести для сервісу авторизації користувачів."""

from __future__ import annotations

import pytest

import agromat_help_desk_bot.auth.service as auth_service
import agromat_help_desk_bot.config as config
from agromat_help_desk_bot.auth.service import RegistrationOutcome


def patch_auth_flow(
    monkeypatch: pytest.MonkeyPatch,
    *,
    token_payload: tuple[bool, dict[str, object]],
    normalized: tuple[str, str | None, str],
    member: bool,
) -> None:
    """Допоміжна утиліта для підміни викликів YouTrack."""
    monkeypatch.setattr(auth_service, 'validate_token', lambda _token: token_payload)
    monkeypatch.setattr(auth_service, 'normalize_user', lambda _payload: normalized)
    monkeypatch.setattr(auth_service, 'is_member_of_project', lambda _user_id: member)


def test_register_user_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Успішна реєстрація робить користувача активним."""
    patch_auth_flow(
        monkeypatch,
        token_payload=(True, {'id': 'YT-1'}),
        normalized=('support', 'support@example.com', 'YT-1'),
        member=True,
    )

    result = auth_service.register_user(123, 'token')
    assert result is RegistrationOutcome.SUCCESS

    login, email, yt_user_id = auth_service.get_authorized_yt_user(123)
    assert login == 'support'
    assert email == 'support@example.com'
    assert yt_user_id == 'YT-1'
    assert auth_service.is_authorized(123) is True


def test_register_user_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Некоректний токен породжує RegistrationError."""
    patch_auth_flow(
        monkeypatch,
        token_payload=(False, {}),
        normalized=('support', None, 'YT-1'),
        member=True,
    )

    with pytest.raises(auth_service.RegistrationError):
        auth_service.register_user(456, 'invalid')

    assert auth_service.is_authorized(456) is False


def test_register_user_blocks_foreign_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не дозволяє підключити той самий YouTrack до іншого Telegram."""
    patch_auth_flow(
        monkeypatch,
        token_payload=(True, {'id': 'YT-9'}),
        normalized=('helper', 'helper@example.com', 'YT-9'),
        member=True,
    )
    monkeypatch.setattr(auth_service, '_ensure_migrated', lambda: None, raising=False)
    monkeypatch.setattr(auth_service, 'fetch_user_by_tg_id', lambda _tg: None, raising=False)
    monkeypatch.setattr(
        auth_service,
        'fetch_user_by_yt_id',
        lambda _yt: {'tg_user_id': 444},
        raising=False,
    )

    def fail_upsert(_: object) -> None:  # pragma: no cover - перевірка безпеки
        pytest.fail('upsert_user не має викликатися для чужого токена')

    monkeypatch.setattr(auth_service, 'upsert_user', fail_upsert, raising=False)

    result = auth_service.register_user(333, 'token')

    assert result is RegistrationOutcome.FOREIGN_OWNER


def test_register_user_detects_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """Коли токен не змінено, повертається ALREADY_CONNECTED."""
    patch_auth_flow(
        monkeypatch,
        token_payload=(True, {'id': 'YT-5'}),
        normalized=('helper', 'helper@example.com', 'YT-5'),
        member=True,
    )
    monkeypatch.setattr(auth_service, '_ensure_migrated', lambda: None, raising=False)
    monkeypatch.setattr(
        auth_service,
        'fetch_user_by_yt_id',
        lambda _yt: {'tg_user_id': 555, 'token_hash': 'hash'},
        raising=False,
    )
    monkeypatch.setattr(
        auth_service,
        'fetch_user_by_tg_id',
        lambda _tg: {
            'registered_at': '2024-01-01T00:00:00+00:00',
            'created_at': '2024-01-01T00:00:00+00:00',
        },
        raising=False,
    )
    monkeypatch.setattr(auth_service, '_hash_token', lambda _token: 'hash', raising=False)
    saved_records: list[dict[str, object]] = []
    monkeypatch.setattr(auth_service, 'upsert_user', saved_records.append, raising=False)

    result = auth_service.register_user(555, 'token')

    assert result is RegistrationOutcome.ALREADY_CONNECTED
    assert saved_records  # переконуємось, що дані оновлено


def test_is_authorized_false_after_deactivation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Після деактивації доступ стає недоступним."""
    patch_auth_flow(
        monkeypatch,
        token_payload=(True, {'id': 'YT-2'}),
        normalized=('agent', None, 'YT-2'),
        member=True,
    )

    auth_service.register_user(789, 'token')
    auth_service.deactivate_user(789)

    assert auth_service.is_authorized(789) is False
    login, email, yt_user_id = auth_service.get_authorized_yt_user(789)
    assert login is None and email is None and yt_user_id is None


def test_get_user_token_returns_decrypted_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Після реєстрації токен можна отримати для викликів."""
    patch_auth_flow(
        monkeypatch,
        token_payload=(True, {'id': 'YT-88'}),
        normalized=('agent', None, 'YT-88'),
        member=True,
    )

    auth_service.register_user(901, 'secret-token')
    stored: str | None = auth_service.get_user_token(901)

    assert stored == 'secret-token'


def test_register_user_requires_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без USER_TOKEN_SECRET реєстрація завершується помилкою."""
    patch_auth_flow(
        monkeypatch,
        token_payload=(True, {'id': 'YT-90'}),
        normalized=('agent', None, 'YT-90'),
        member=True,
    )
    monkeypatch.setattr(config, 'USER_TOKEN_SECRET', None, raising=False)

    with pytest.raises(auth_service.RegistrationError):
        auth_service.register_user(902, 'token')
