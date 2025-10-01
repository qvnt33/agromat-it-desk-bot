"""Перевіряє логіку реєстрації користувачів через Telegram."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict, cast

import pytest

import agromat_it_desk_bot.telegram.telegram_commands as commands_module
from agromat_it_desk_bot.messages import Msg, render


class CapturedMessage(TypedDict):
    method: str
    payload: dict[str, object]


SentMessages = list[CapturedMessage]
Pending = commands_module.PendingLoginChange


@pytest.fixture(autouse=True)
def clear_state(monkeypatch: pytest.MonkeyPatch) -> SentMessages:
    """Очищає глобальний стан та перехоплює вихідні повідомлення."""
    # Ініціалізують буфер для відправлених повідомлень
    commands_module.pending_login_updates.clear()
    sent_messages: SentMessages = []

    def fake_call_api(method: str, payload: dict[str, object]) -> None:  # pragma: no cover - технічний хук
        sent_messages.append({'method': method, 'payload': payload})

    monkeypatch.setattr(commands_module, 'call_api', fake_call_api)
    monkeypatch.setattr(commands_module, 'YT_BASE_URL', 'https://example.test', raising=False)
    monkeypatch.setattr(commands_module, 'YT_TOKEN', 'token', raising=False)
    return sent_messages


def build_message(user_id: int, text: str) -> dict[str, object]:
    """Конструює мінімальний payload Telegram для тестів."""
    return {'chat': {'id': 777, 'type': 'private'}, 'from': {'id': user_id}, 'text': text}


def patch_resolve_from_map(monkeypatch: pytest.MonkeyPatch, result: tuple[str | None, str | None, str | None]) -> None:
    """Встановлює кастомний resolver для ``resolve_from_map``."""
    # Підміняють пошук запису user_map за Telegram ID

    def resolver(_: int) -> tuple[str | None, str | None, str | None]:
        return result

    monkeypatch.setattr(commands_module, 'resolve_from_map', resolver)


def patch_is_login_taken(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    """Переозначає ``is_login_taken`` з фіксованим результатом."""
    # Форсують наперед визначену відповідь щодо зайнятості логіна

    def checker(login: str, *, exclude_tg_user_id: int | None = None) -> bool:  # noqa: ARG001
        return value

    monkeypatch.setattr(commands_module, 'is_login_taken', checker)


def patch_resolve_login_details(
    monkeypatch: pytest.MonkeyPatch,
    details: Pending | None,
    *,
    failure_message: str | None = None,
) -> None:
    """Переозначає ``_resolve_login_details`` із заздалегідь відомою поведінкою."""

    def resolver(chat_id: int, login: str) -> Pending | None:  # noqa: ARG001
        if details is None and failure_message is not None:
            call_api_attr: object = commands_module.call_api
            call_api_func: Callable[[str, dict[str, object]], object] = cast(
                Callable[[str, dict[str, object]], object], call_api_attr,
            )
            payload: dict[str, object] = {'chat_id': chat_id, 'text': failure_message, 'disable_web_page_preview': True}
            call_api_func('sendMessage', payload)
            return None
        return details

    monkeypatch.setattr(commands_module, '_resolve_login_details', resolver)


def test_register_same_login_returns_notice(monkeypatch: pytest.MonkeyPatch, clear_state: SentMessages) -> None:
    """/register із тим самим логіном має повернути інформаційне повідомлення."""
    patch_resolve_from_map(monkeypatch, ('existing', 'mail', 'YT-1'))

    message: dict[str, object] = build_message(111, '/register existing')
    commands_module.handle_register_command(777, message, '/register existing')

    assert not commands_module.pending_login_updates
    last_message: CapturedMessage = clear_state[-1]
    payload: dict[str, object] = last_message['payload']
    text_obj: object | None = payload.get('text')
    expected: str = render(Msg.REGISTER_ALREADY, login='existing', suggested='existing')
    assert isinstance(text_obj, str)
    assert text_obj == expected


def test_register_new_login_requires_confirmation(monkeypatch: pytest.MonkeyPatch, clear_state: SentMessages) -> None:
    """/register із новим логіном має вимагати підтвердження."""
    requested = Pending('newlogin', 'newlogin', 'user@example.com', 'YT-2')

    patch_resolve_from_map(monkeypatch, ('oldlogin', 'mail', 'YT-1'))
    patch_resolve_login_details(monkeypatch, requested)
    patch_is_login_taken(monkeypatch, False)

    message: dict[str, object] = build_message(222, '/register newlogin')
    commands_module.handle_register_command(777, message, '/register newlogin')

    assert commands_module.pending_login_updates[222] == requested
    last_message: CapturedMessage = clear_state[-1]
    payload: dict[str, object] = last_message['payload']
    text_obj: object | None = payload.get('text')
    expected: str = render(Msg.REGISTER_PROMPT_CONFIRM, login='newlogin')
    assert isinstance(text_obj, str)
    assert text_obj == expected


def test_register_fails_when_login_unknown(monkeypatch: pytest.MonkeyPatch, clear_state: SentMessages) -> None:
    """Переконується, що бот одразу відповідає про помилку, коли YouTrack не знаходить логін."""
    patch_resolve_from_map(monkeypatch, (None, None, None))
    patch_resolve_login_details(monkeypatch, None, failure_message=render(Msg.ERR_YT_USER_NOT_FOUND))

    message: dict[str, object] = build_message(333, '/register ghost')
    commands_module.handle_register_command(777, message, '/register ghost')

    assert not commands_module.pending_login_updates
    last_message: CapturedMessage = clear_state[-1]
    payload: dict[str, object] = last_message['payload']
    text_obj: object | None = payload.get('text')
    expected: str = render(Msg.ERR_YT_USER_NOT_FOUND)
    assert isinstance(text_obj, str)
    assert text_obj == expected


def test_register_new_login_creates_entry(monkeypatch: pytest.MonkeyPatch, clear_state: SentMessages) -> None:
    """/register без попереднього логіна створює новий запис у user_map."""
    requested = Pending('fresh', 'fresh', 'fresh@example.com', 'YT-3')

    patch_resolve_from_map(monkeypatch, (None, None, None))
    patch_resolve_login_details(monkeypatch, requested)
    patch_is_login_taken(monkeypatch, False)

    captured: dict[str, object] = {}

    def fake_upsert(tg_user_id: int, *, login: str | None, email: str | None, yt_user_id: str | None) -> None:
        captured.update({'tg_user_id': tg_user_id, 'login': login, 'email': email, 'yt_user_id': yt_user_id})

    monkeypatch.setattr(commands_module, 'upsert_user_map_entry', fake_upsert)

    message: dict[str, object] = build_message(444, '/register fresh')
    commands_module.handle_register_command(777, message, '/register fresh')

    assert not commands_module.pending_login_updates
    assert captured == {'tg_user_id': 444, 'login': 'fresh', 'email': 'fresh@example.com', 'yt_user_id': 'YT-3'}
    last_message: CapturedMessage = clear_state[-1]
    payload: dict[str, object] = last_message['payload']
    text_obj: object | None = payload.get('text')
    expected_text: str = render(Msg.REGISTER_SAVED, login='fresh', email='fresh@example.com', yt_id='YT-3')
    assert isinstance(text_obj, str)
    assert text_obj == expected_text


def test_confirm_login_success(monkeypatch: pytest.MonkeyPatch, clear_state: SentMessages) -> None:
    """/confirm_login підтверджує зміну логіна та оновлює user_map."""
    details = Pending('target', 'target', 'user@example.com', 'YT-5')
    commands_module.pending_login_updates[555] = details

    patch_resolve_from_map(monkeypatch, ('old', 'mail', 'YT-1'))
    patch_is_login_taken(monkeypatch, False)

    captured: dict[str, object] = {}

    def fake_upsert(tg_user_id: int, *, login: str | None, email: str | None, yt_user_id: str | None) -> None:
        captured.update({'tg_user_id': tg_user_id, 'login': login, 'email': email, 'yt_user_id': yt_user_id})

    monkeypatch.setattr(commands_module, 'upsert_user_map_entry', fake_upsert)

    message: dict[str, object] = build_message(555, '/confirm_login target')
    commands_module.handle_confirm_login_command(777, message, '/confirm_login target')

    assert not commands_module.pending_login_updates
    assert captured == {'tg_user_id': 555, 'login': 'target', 'email': 'user@example.com', 'yt_user_id': 'YT-5'}
    last_message: CapturedMessage = clear_state[-1]
    payload: dict[str, object] = last_message['payload']
    text_obj: object | None = payload.get('text')
    expected_base: str = render(Msg.REGISTER_SAVED, login='target', email='user@example.com', yt_id='YT-5')
    expected_note: str = render(Msg.REGISTER_UPDATED_NOTE, previous='old', current='target')
    assert isinstance(text_obj, str)
    assert text_obj == f'{expected_base}\n{expected_note}'


def test_confirm_login_rejects_foreign_login(monkeypatch: pytest.MonkeyPatch, clear_state: SentMessages) -> None:
    """Підтверджує, що підтвердження відхиляється, якщо логін уже зайнятий іншою особою."""
    details = Pending('target', 'target', 'user@example.com', 'YT-5')
    commands_module.pending_login_updates[777] = details

    patch_resolve_from_map(monkeypatch, ('old', 'mail', 'YT-1'))
    patch_is_login_taken(monkeypatch, True)

    message: dict[str, object] = build_message(777, '/confirm_login target')
    commands_module.handle_confirm_login_command(777, message, '/confirm_login target')

    assert not commands_module.pending_login_updates
    last_message: CapturedMessage = clear_state[-1]
    payload: dict[str, object] = last_message['payload']
    text_obj: object | None = payload.get('text')
    expected: str = render(Msg.ERR_LOGIN_TAKEN)
    assert isinstance(text_obj, str)
    assert text_obj == expected
