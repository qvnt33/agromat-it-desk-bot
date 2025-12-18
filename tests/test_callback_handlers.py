"""Перевіряє обробку callback'ів прийняття задачі."""

from types import SimpleNamespace
from typing import cast

import pytest

import agromat_help_desk_bot.callback_handlers as handlers
from agromat_help_desk_bot.messages import Msg, render
from tests.conftest import FakeTelegramSender

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def callback_context() -> handlers.CallbackContext:
    """Створює базовий callback-контекст."""
    return handlers.CallbackContext('cb-1', 200, 300, 'accept|SUP-1', 555)


async def test_handle_accept_assigns_issue(
    monkeypatch: pytest.MonkeyPatch,
    fake_sender: FakeTelegramSender,
    callback_context: handlers.CallbackContext,
) -> None:
    """Авторизований користувач має призначати задачу та отримувати підтвердження."""
    monkeypatch.setattr(handlers, 'assign_issue', lambda *_: True)
    monkeypatch.setattr(handlers, 'get_authorized_yt_user', lambda _tg_user_id: ('login', 'mail', 'YT-1'))
    monkeypatch.setattr(handlers, 'get_user_token', lambda _tg_user_id: 'user-token')

    def stub_details(_issue_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            summary='Заявка',
            description='<div>Опис</div>',
            assignee='Agent Smith',
            status='In Progress',
            author='Reporter',
        )

    monkeypatch.setattr(
        handlers,
        'fetch_issue_details',
        stub_details,
    )
    monkeypatch.setattr(handlers, '_resolve_issue_url', lambda *_: 'https://example.test/SUP-1')
    await handlers.handle_accept('SUP-1', callback_context)

    assert any(answer['text'] == render(Msg.CALLBACK_ACCEPTED) for answer in fake_sender.callback_answers)
    assert fake_sender.edited_markup[-1] == {'chat_id': 200, 'message_id': 300, 'reply_markup': {}}
    assert fake_sender.edited_text, 'Очікували оновлення тексту повідомлення'
    updated_message = fake_sender.edited_text[-1]['text']
    assert '<a href="https://example.test/SUP-1">' in str(updated_message)
    assert '<b>Автор:</b> <code>Reporter</code>' in str(updated_message)
    assert 'Виконавець:' in str(updated_message)
    assert 'Agent Smith' in str(updated_message)
    assert 'Статус:' in str(updated_message)
    assert 'In Progress' in str(updated_message)
    assert '<div>' not in str(updated_message)


async def test_handle_accept_fails_for_unknown_user(
    monkeypatch: pytest.MonkeyPatch,
    fake_sender: FakeTelegramSender,
    callback_context: handlers.CallbackContext,
) -> None:
    """Якщо користувача не знайдено, бот показує помилку."""
    monkeypatch.setattr(handlers, 'assign_issue', lambda *_: True)
    monkeypatch.setattr(handlers, 'get_authorized_yt_user', lambda _tg_user_id: (None, None, None))

    await handlers.handle_accept('SUP-2', callback_context)

    expected_text: str = render(Msg.ERR_CALLBACK_AUTH_REQUIRED)
    assert any(answer['text'] == expected_text for answer in fake_sender.callback_answers)


async def test_handle_accept_duplicate_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    fake_sender: FakeTelegramSender,
    callback_context: handlers.CallbackContext,
) -> None:
    """Повторний callback не викликає повторного assign_issue, але відповідає успіхом."""
    calls: list[str] = []

    def fake_assign(issue_id: str, *_: object) -> bool:
        calls.append(issue_id)
        return True

    monkeypatch.setattr(handlers, 'assign_issue', fake_assign, raising=False)
    monkeypatch.setattr(handlers, 'get_authorized_yt_user', lambda _tg_user_id: ('login', 'mail', 'YT-1'))
    monkeypatch.setattr(handlers, 'get_user_token', lambda _tg_user_id: 'user-token')

    def stub_duplicate_details(_issue_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            summary='Заявка',
            description='Опис',
            assignee='Agent Smith',
            status='In Progress',
            author='Reporter',
        )

    monkeypatch.setattr(
        handlers,
        'fetch_issue_details',
        stub_duplicate_details,
    )
    monkeypatch.setattr(handlers, '_resolve_issue_url', lambda *_: 'https://example.test/SUP-3')

    await handlers.handle_accept('SUP-3', callback_context)
    await handlers.handle_accept('SUP-3', callback_context)

    assert calls == ['SUP-3']
    successes = [answer for answer in fake_sender.callback_answers if answer['text'] == render(Msg.CALLBACK_ACCEPTED)]
    assert len(successes) >= 2


async def test_handle_accept_requires_auth_every_time(
    monkeypatch: pytest.MonkeyPatch,
    fake_sender: FakeTelegramSender,
    callback_context: handlers.CallbackContext,
) -> None:
    """Неавторизований користувач завжди бачить попередження про авторизацію."""
    monkeypatch.setattr(handlers, 'assign_issue', lambda *_: True)
    monkeypatch.setattr(handlers, 'get_authorized_yt_user', lambda _tg_user_id: (None, None, None))

    await handlers.handle_accept('SUP-4', callback_context)
    await handlers.handle_accept('SUP-4', callback_context)

    auth_required_text: str = render(Msg.ERR_CALLBACK_AUTH_REQUIRED)
    shown: list[str | None] = [cast(str | None, answer['text']) for answer in fake_sender.callback_answers]
    assert shown == [auth_required_text, auth_required_text]


async def test_handle_accept_requires_fresh_token(
    monkeypatch: pytest.MonkeyPatch,
    fake_sender: FakeTelegramSender,
    callback_context: handlers.CallbackContext,
) -> None:
    """Якщо токен відсутній, користувач отримує інструкцію оновити /connect."""
    monkeypatch.setattr(handlers, 'assign_issue', lambda *_: True)
    monkeypatch.setattr(handlers, 'get_authorized_yt_user', lambda _tg_user_id: ('login', 'mail', 'YT-1'))
    monkeypatch.setattr(handlers, 'get_user_token', lambda _tg_user_id: None)

    await handlers.handle_accept('SUP-5', callback_context)

    texts = [cast(str | None, answer['text']) for answer in fake_sender.callback_answers]
    assert render(Msg.ERR_CALLBACK_TOKEN_REQUIRED) in texts
