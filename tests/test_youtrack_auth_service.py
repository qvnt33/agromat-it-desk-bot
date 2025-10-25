"""Перевіряє допоміжні функції авторизації YouTrack."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import requests  # type: ignore[import-untyped]

import agromat_it_desk_bot.youtrack.youtrack_auth_service as auth_service


class FakeResponse:
    """Проста заглушка для ``requests.Response``."""

    def __init__(self, status_code: int, json_data: Any = None, text: str = '') -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return self._json_data


@pytest.fixture(autouse=True)
def configure_auth(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Налаштовує базову конфігурацію для тестів."""
    monkeypatch.setattr(auth_service, 'YT_BASE_URL', 'https://example.test', raising=False)
    monkeypatch.setattr(auth_service, 'YT_TOKEN', 'service-token', raising=False)
    monkeypatch.setattr(auth_service, 'PROJECT_KEY', 'SUP', raising=False)
    monkeypatch.setattr(auth_service, 'PROJECT_ID', None, raising=False)
    monkeypatch.setattr(auth_service, 'time', SimpleNamespace(sleep=lambda _delay: None), raising=False)
    yield


class SimpleNamespace:
    """Мінімальна реалізація для патчу ``time.sleep``."""

    def __init__(self, **attributes: Any) -> None:
        self.__dict__.update(attributes)


def test_validate_token_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Успішна перевірка токена має повертати payload користувача."""

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        assert url.endswith('/api/users/me')
        params: dict[str, object] | None = kwargs.get('params')
        assert params == {'fields': 'id,login,ringId,fullName,profile(email,username)'}
        return FakeResponse(200, {'id': 'YT-1', 'login': 'support', 'email': 'user@example.com'})

    monkeypatch.setattr(requests, 'get', fake_get)

    ok, payload = auth_service.validate_token('token-123')
    assert ok is True
    assert payload['id'] == 'YT-1'


def test_normalize_user_prefers_email_field() -> None:
    """normalize_user має повертати email з верхнього рівня відповіді."""
    login, email, yt_user_id = auth_service.normalize_user(
        {'id': 'YT-77', 'login': 'agent', 'email': 'agent@example.com'}
    )

    assert login == 'agent'
    assert email == 'agent@example.com'
    assert yt_user_id == 'YT-77'


def test_validate_token_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """401/403 мають повертати ``False`` без підняття винятку."""

    def fake_get(_url: str, **_kwargs: Any) -> FakeResponse:
        return FakeResponse(401, text='unauthorized')

    monkeypatch.setattr(requests, 'get', fake_get)

    ok, payload = auth_service.validate_token('token-123')
    assert ok is False
    assert payload == {}


def test_validate_token_rejects_non_ascii() -> None:
    """Токени з не-ASCII символами вважаються недійсними без HTTP-запиту."""
    ok, payload = auth_service.validate_token('токен🔑')
    assert ok is False
    assert payload == {}


def test_validate_token_retries_and_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """5xx помилки призводять до ``TemporaryYouTrackError`` після декількох спроб."""
    attempts: int = 0

    def fake_get(_url: str, **_kwargs: Any) -> FakeResponse:
        nonlocal attempts
        attempts += 1
        return FakeResponse(503, text='maintenance')

    monkeypatch.setattr(requests, 'get', fake_get)
    monkeypatch.setattr(auth_service, 'YT_VALIDATE_RETRIES', 2, raising=False)

    with pytest.raises(auth_service.TemporaryYouTrackError):
        auth_service.validate_token('token-123')
    assert attempts == 2


def test_is_member_of_project_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Користувач має розпізнаватися через поле memberships."""

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        assert url.endswith('/youtrack/api/admin/projects/SUP/team')
        assert kwargs.get('params') == {'fields': 'users(id,login),memberships(user(id,login))'}
        payload = [{'memberships': [{'user': {'id': 'YT-1'}}]}]
        return FakeResponse(200, payload)

    monkeypatch.setattr(requests, 'get', fake_get)

    assert auth_service.is_member_of_project('YT-1') is True


def test_is_member_of_project_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Відсутність користувача у складі команди повертає ``False``."""

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        assert url.endswith('/youtrack/api/admin/projects/SUP/team')
        assert kwargs.get('params') == {'fields': 'users(id,login),memberships(user(id,login))'}
        payload = [{'memberships': [{'user': {'id': 'YT-2'}}]}]
        return FakeResponse(200, payload)

    monkeypatch.setattr(requests, 'get', fake_get)

    assert auth_service.is_member_of_project('YT-1') is False


def test_is_member_of_project_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 по проєкту сигналізує про конфігураційну помилку."""

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        assert url.endswith('/youtrack/api/admin/projects/SUP/team')
        assert kwargs.get('params') == {'fields': 'users(id,login),memberships(user(id,login))'}
        return FakeResponse(404, text='not found')

    monkeypatch.setattr(requests, 'get', fake_get)

    with pytest.raises(RuntimeError):
        auth_service.is_member_of_project('YT-1')


def test_is_member_of_project_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """5xx по членству має кидати ``TemporaryYouTrackError``."""

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        assert url.endswith('/youtrack/api/admin/projects/SUP/team')
        assert kwargs.get('params') == {'fields': 'users(id,login),memberships(user(id,login))'}
        return FakeResponse(502, text='bad gateway')

    monkeypatch.setattr(requests, 'get', fake_get)

    with pytest.raises(auth_service.TemporaryYouTrackError):
        auth_service.is_member_of_project('YT-1')


def test_normalize_user_fallback_to_ring_id() -> None:
    """normalize_user має враховувати ringId та profile.email."""
    payload: dict[str, object] = {
        'id': 'YT-42',
        'ringId': 'john.doe',
        'profile': {'email': 'john.doe@example.com'},
    }

    login, email, yt_user_id = auth_service.normalize_user(payload)

    assert login == 'john.doe'
    assert email == 'john.doe@example.com'
    assert yt_user_id == 'YT-42'
