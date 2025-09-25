"""Тести логіки реєстрації користувачів через Telegram."""

from __future__ import annotations

from typing import Any

import pytest

import agromat_it_desk_bot.main as main_module
from agromat_it_desk_bot.main import (
    PendingLoginChange,
    handle_confirm_login_command,
    handle_register_command,
    pending_login_updates,
)

SentMessages = list[dict[str, object]]


@pytest.fixture(autouse=True)
def clear_state(monkeypatch: pytest.MonkeyPatch) -> SentMessages:
    """Очистити глобальний стан та перехопити вихідні повідомлення."""
    pending_login_updates.clear()
    sent_messages: SentMessages = []

    def fake_call_api(method: str, payload: dict[str, object]) -> None:  # pragma: no cover - технічний хук
        sent_messages.append({'method': method, 'payload': payload})

    monkeypatch.setattr(main_module, 'call_api', fake_call_api)
    monkeypatch.setattr(main_module, 'YT_BASE_URL', 'https://example.test')
    monkeypatch.setattr(main_module, 'YT_TOKEN', 'token')
    return sent_messages


def build_message(user_id: int, text: str) -> dict[str, object]:
    """Сконструювати мінімальний payload Telegram для тестів."""
    return {
        'chat': {'id': 777, 'type': 'private'},
        'from': {'id': user_id},
        'text': text,
    }


def patch_resolve_from_map(
    monkeypatch: pytest.MonkeyPatch,
    result: tuple[str | None, str | None, str | None],
) -> None:
    """Встановити кастомний resolver для resolve_from_map."""

    def resolver(_: int) -> tuple[str | None, str | None, str | None]:
        return result

    monkeypatch.setattr(main_module, 'resolve_from_map', resolver)


def patch_is_login_taken(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    """Переоприділити ``is_login_taken`` з фіксованим результатом."""

    def checker(login: str, *, exclude_tg_user_id: int | None = None) -> bool:  # noqa: ARG001
        return value

    monkeypatch.setattr(main_module, 'is_login_taken', checker)


def patch_resolve_login_details(
    monkeypatch: pytest.MonkeyPatch,
    details: PendingLoginChange | None,
    *,
    failure_message: str | None = None,
) -> None:
    """Переоприділити ``_resolve_login_details`` з заздалегідь відомою поведінкою."""

    def resolver(chat_id: int, login: str) -> PendingLoginChange | None:  # noqa: ARG001
        if details is None and failure_message is not None:
            main_module.call_api(
                'sendMessage',
                {'chat_id': chat_id,
                 'text': failure_message,
                 'disable_web_page_preview': True},
            )
            return None
        return details

    monkeypatch.setattr(main_module, '_resolve_login_details', resolver)


def test_register_same_login_returns_notice(
    monkeypatch: pytest.MonkeyPatch,
    clear_state: SentMessages,
) -> None:
    """/register із тим самим логіном має повернути інформаційне повідомлення."""
    patch_resolve_from_map(monkeypatch, ('existing', 'mail', 'YT-1'))

    message: dict[str, object] = build_message(111, '/register existing')
    handle_register_command(777, message, '/register existing')

    assert not pending_login_updates
    last_message: dict[str, object] = clear_state[-1]
    payload: dict[str, object] = last_message['payload']  # type: ignore[assignment]
    text: str = payload['text']  # type: ignore[assignment]
    assert text.startswith('Ви вже зареєстровані')


def test_register_new_login_requires_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    clear_state: SentMessages,
) -> None:
    """/register із новим логіном має вимагати підтвердження."""
    requested = PendingLoginChange('newlogin', 'newlogin', 'user@example.com', 'YT-2')

    patch_resolve_from_map(monkeypatch, ('oldlogin', 'mail', 'YT-1'))
    patch_resolve_login_details(monkeypatch, requested)
    patch_is_login_taken(monkeypatch, False)

    message: dict[str, object] = build_message(222, '/register newlogin')
    handle_register_command(777, message, '/register newlogin')

    assert pending_login_updates[222] == requested
    last_message: dict[str, object] = clear_state[-1]
    payload: object = last_message['payload']  # type: ignore[assignment]
    text: Any = payload['text']  # type: ignore[assignment]
    assert '/confirm_login newlogin' in text


def test_register_fails_when_login_unknown(
    monkeypatch: pytest.MonkeyPatch,
    clear_state: SentMessages,
) -> None:
    """Коли логін не знайдено в YouTrack, бот має одразу відповісти про помилку."""
    patch_resolve_from_map(monkeypatch, (None, None, None))
    patch_resolve_login_details(
        monkeypatch,
        None,
        failure_message='Користувача з таким логіном у YouTrack не знайдено.',
    )

    message: dict[str, object] = build_message(333, '/register ghost')
    handle_register_command(777, message, '/register ghost')

    assert not pending_login_updates
    last_message: dict[str, object] = clear_state[-1]
    payload: object = last_message['payload']  # type: ignore[assignment]
    text: Any = payload['text']  # type: ignore[assignment]
    assert text == 'Користувача з таким логіном у YouTrack не знайдено.'


def test_register_new_login_creates_entry(
    monkeypatch: pytest.MonkeyPatch,
    clear_state: SentMessages,
) -> None:
    """/register без попереднього логіна створює новий запис у user_map."""
    requested = PendingLoginChange('fresh', 'fresh', 'fresh@example.com', 'YT-3')

    patch_resolve_from_map(monkeypatch, (None, None, None))
    patch_resolve_login_details(monkeypatch, requested)
    patch_is_login_taken(monkeypatch, False)

    captured: dict[str, object] = {}

    def fake_upsert(
        tg_user_id: int,
        *,
        login: str | None,
        email: str | None,
        yt_user_id: str | None,
    ) -> None:
        captured.update({'tg_user_id': tg_user_id, 'login': login, 'email': email, 'yt_user_id': yt_user_id})

    monkeypatch.setattr(main_module, 'upsert_user_map_entry', fake_upsert)

    message: dict[str, object] = build_message(444, '/register fresh')
    handle_register_command(777, message, '/register fresh')

    assert not pending_login_updates
    assert captured == {'tg_user_id': 444, 'login': 'fresh', 'email': 'fresh@example.com', 'yt_user_id': 'YT-3'}
    last_message: dict[str, object] = clear_state[-1]
    payload: object = last_message['payload']  # type: ignore[assignment]
    text = payload['text']  # type: ignore[assignment]
    assert '✅ Дані збережено' in text


def test_confirm_login_success(
    monkeypatch: pytest.MonkeyPatch,
    clear_state: SentMessages,
) -> None:
    """/confirm_login підтверджує зміну логіна та оновлює user_map."""
    details = PendingLoginChange('target', 'target', 'user@example.com', 'YT-5')
    pending_login_updates[555] = details

    patch_resolve_from_map(monkeypatch, ('old', 'mail', 'YT-1'))
    patch_is_login_taken(monkeypatch, False)

    captured: dict[str, object] = {}

    def fake_upsert(
        tg_user_id: int,
        *,
        login: str | None,
        email: str | None,
        yt_user_id: str | None,
    ) -> None:
        captured.update({'tg_user_id': tg_user_id, 'login': login, 'email': email, 'yt_user_id': yt_user_id})

    monkeypatch.setattr(main_module, 'upsert_user_map_entry', fake_upsert)

    message: dict[str, object] = build_message(555, '/confirm_login target')
    handle_confirm_login_command(777, message, '/confirm_login target')

    assert not pending_login_updates
    assert captured == {'tg_user_id': 555, 'login': 'target', 'email': 'user@example.com', 'yt_user_id': 'YT-5'}
    last_message: dict[str, object] = clear_state[-1]
    payload: object = last_message['payload']  # type: ignore[assignment]
    text = payload['text']  # type: ignore[assignment]
    assert text.startswith('✅ Дані збережено')  # type: ignore


def test_confirm_login_rejects_foreign_login(
    monkeypatch: pytest.MonkeyPatch,
    clear_state: SentMessages,
) -> None:
    """Підтвердження має відхилятись, якщо логін уже зайнятий іншою особою."""
    details = PendingLoginChange('target', 'target', 'user@example.com', 'YT-5')
    pending_login_updates[777] = details

    patch_resolve_from_map(monkeypatch, ('old', 'mail', 'YT-1'))
    patch_is_login_taken(monkeypatch, True)

    message: dict[str, object] = build_message(777, '/confirm_login target')
    handle_confirm_login_command(777, message, '/confirm_login target')

    assert not pending_login_updates
    last_message: dict[str, object] = clear_state[-1]
    payload: object = last_message['payload']  # type: ignore[assignment]
    text: Any = payload['text']  # type: ignore[assignment]
    assert text == 'Цей логін вже закріплено за іншим користувачем.'
