"""Перевіряє сценарії підключення та оновлення токенів через Telegram."""

from __future__ import annotations

from typing import TypedDict

import pytest

import agromat_it_desk_bot.telegram.telegram_commands as telegram_commands
from agromat_it_desk_bot.auth.service import RegistrationOutcome
from agromat_it_desk_bot.messages import Msg, render


class CapturedMessage(TypedDict):
    method: str
    payload: dict[str, object]


def last_payload(messages: list[CapturedMessage], method: str = 'sendMessage') -> dict[str, object]:
    for record in reversed(messages):
        if record['method'] == method:
            return record['payload']
    raise AssertionError(f'Expected call {method} not found')


def render_md(msg: Msg, **kwargs: str) -> str:
    escaped = {key: telegram_commands._escape_markdown(value) for key, value in kwargs.items()}
    return render(msg, **escaped)


def build_message(tg_user_id: int, text: str) -> dict[str, object]:
    """Конструює мінімальний payload Telegram для тестів."""
    return {
        'chat': {'id': 700, 'type': 'private'},
        'from': {'id': tg_user_id},
        'from_user': {'id': tg_user_id},
        'text': text,
    }


@pytest.fixture(autouse=True)
def setup_state(monkeypatch: pytest.MonkeyPatch) -> list[CapturedMessage]:
    """Очищає глобальний стан та перехоплює відправлені повідомлення."""
    telegram_commands.pending_token_updates.clear()
    sent: list[CapturedMessage] = []

    def fake_call_api(method: str, payload: dict[str, object]) -> None:  # pragma: no cover - технічний хук
        sent.append({'method': method, 'payload': payload})

    monkeypatch.setattr(telegram_commands, 'call_api', fake_call_api, raising=False)
    monkeypatch.setattr(telegram_commands, 'PROJECT_KEY', 'SUP', raising=False)
    monkeypatch.setattr(telegram_commands, 'is_authorized', lambda _tg_id: False, raising=False)
    monkeypatch.setattr(
        telegram_commands,
        'get_authorized_yt_user',
        lambda _tg_id: (None, None, None),
        raising=False,
    )
    monkeypatch.setattr(
        telegram_commands,
        'register_user',
        lambda _tg_id, _token: RegistrationOutcome.SUCCESS,
        raising=False,
    )
    return sent


def test_start_for_new_user_shows_instruction(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Команда /start для нового користувача показує інструкцію з кнопкою довідки."""
    message = build_message(101, '/start')
    telegram_commands.handle_start_command(700, message)

    assert len(setup_state) == 1
    payload = setup_state[0]['payload']
    assert payload['text'] == render(Msg.CONNECT_START_NEW)
    assert payload['parse_mode'] == 'MarkdownV2'
    reply_markup = payload['reply_markup']
    assert isinstance(reply_markup, dict)
    buttons = reply_markup.get('inline_keyboard')
    assert buttons == [[{'text': render(Msg.CONNECT_GUIDE_BUTTON), 'url': telegram_commands.TOKEN_GUIDE_URL}]]


def test_start_for_existing_user_shows_status(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Команда /start для активного користувача показує статус без додаткових кнопок."""
    monkeypatch.setattr(
        telegram_commands,
        'get_authorized_yt_user',
        lambda _tg_id: ('agent', 'agent@example.com', 'YT-1'),
        raising=False,
    )

    message = build_message(202, '/start')
    telegram_commands.handle_start_command(700, message)

    assert len(setup_state) == 1
    payload = setup_state[0]['payload']
    expected = render_md(
        Msg.CONNECT_START_REGISTERED,
        login='agent',
        email='agent@example.com',
        project_key='SUP',
    )
    assert payload['text'] == expected
    assert payload['parse_mode'] == 'MarkdownV2'
    assert 'reply_markup' not in payload


def test_unlink_prompts_confirmation(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Команда /unlink надсилає повідомлення з кнопками підтвердження."""
    monkeypatch.setattr(telegram_commands, 'is_authorized', lambda _tg: True, raising=False)

    telegram_commands.handle_unlink_command(700, build_message(222, '/unlink'))

    payload = last_payload(setup_state)
    assert payload['text'] == render(Msg.UNLINK_CONFIRM_PROMPT)
    assert payload['parse_mode'] == 'Markdown'
    assert payload['reply_markup'] == {
        'inline_keyboard': [
            [
                {'text': render(Msg.UNLINK_CONFIRM_YES_BUTTON), 'callback_data': telegram_commands.CALLBACK_UNLINK_YES},
                {'text': render(Msg.UNLINK_CONFIRM_NO_BUTTON), 'callback_data': telegram_commands.CALLBACK_UNLINK_NO},
            ],
        ],
    }


def test_unlink_confirm_accepts(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Підтвердження відʼєднання деактивує користувача та видаляє повідомлення."""
    calls: list[int] = []
    monkeypatch.setattr(telegram_commands, 'deactivate_user', lambda tg_id: calls.append(tg_id), raising=False)
    monkeypatch.setattr(telegram_commands, 'is_authorized', lambda _tg: True, raising=False)

    processed = telegram_commands.handle_unlink_decision(700, 321, 333, True)

    assert processed is True
    assert calls == [333]
    delete_payload = last_payload(setup_state, 'deleteMessage')
    assert delete_payload == {'chat_id': 700, 'message_id': 321}
    send_payload = last_payload(setup_state)
    assert send_payload['text'] == render(Msg.AUTH_UNLINK_DONE)
    assert send_payload['parse_mode'] == 'Markdown'


def test_unlink_confirm_declines(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Скасування відʼєднання видаляє повідомлення та інформує користувача."""
    monkeypatch.setattr(telegram_commands, 'is_authorized', lambda _tg: True, raising=False)
    processed = telegram_commands.handle_unlink_decision(700, 321, 444, False)

    assert processed is True
    delete_payload = last_payload(setup_state, 'deleteMessage')
    assert delete_payload == {'chat_id': 700, 'message_id': 321}
    send_payload = last_payload(setup_state)
    assert send_payload['text'] == render(Msg.UNLINK_CANCELLED)
    assert send_payload['parse_mode'] == 'Markdown'


def test_connect_registers_new_user(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Команда /connect з новим токеном виконує реєстрацію."""
    calls: list[tuple[int, str]] = []

    def fake_register(tg_user_id: int, token: str) -> RegistrationOutcome:
        calls.append((tg_user_id, token))
        return RegistrationOutcome.SUCCESS

    monkeypatch.setattr(telegram_commands, 'register_user', fake_register, raising=False)
    monkeypatch.setattr(
        telegram_commands,
        'get_authorized_yt_user',
        lambda _tg_id: ('agent', 'agent@example.com', 'YT-1'),
        raising=False,
    )

    message = build_message(303, '/connect token-123')
    telegram_commands.handle_connect_command(700, message, '/connect token-123')

    assert calls == [(303, 'token-123')]
    assert telegram_commands.pending_token_updates == {}
    payload = last_payload(setup_state)
    assert payload['text'] == render_md(
        Msg.CONNECT_SUCCESS_NEW,
        login='agent',
        email='agent@example.com',
        yt_id='YT-1',
    )
    assert payload['parse_mode'] == 'Markdown'


def test_connect_rejects_already_linked(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Другий Telegram не може привʼязати той самий YouTrack акаунт."""
    monkeypatch.setattr(
        telegram_commands,
        'register_user',
        lambda _tg, _token: RegistrationOutcome.FOREIGN_OWNER,
        raising=False,
    )

    message = build_message(350, '/connect stolen-token')
    telegram_commands.handle_connect_command(700, message, '/connect stolen-token')

    payload = last_payload(setup_state)
    assert payload['text'] == render(Msg.CONNECT_ALREADY_LINKED)
    assert payload['parse_mode'] == 'Markdown'


def test_connect_existing_user_requests_confirmation(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Команда /connect для активного користувача зберігає запит на підтвердження."""
    monkeypatch.setattr(telegram_commands, 'is_authorized', lambda _tg_id: True, raising=False)
    monkeypatch.setattr(
        telegram_commands,
        'get_authorized_yt_user',
        lambda _tg_id: ('agent', 'agent@example.com', 'YT-1'),
        raising=False,
    )

    message = build_message(404, '/connect new-token')
    telegram_commands.handle_connect_command(700, message, '/connect new-token')

    pending = telegram_commands.pending_token_updates[404]
    assert pending.chat_id == 700
    assert pending.token == 'new-token'
    payload = last_payload(setup_state)
    expected = render_md(Msg.CONNECT_CONFIRM_PROMPT, login='agent', email='agent@example.com')
    assert payload['text'] == expected


def test_confirm_reconnect_accepts_and_updates_token(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Підтвердження оновлення викликає register_user та надсилає повідомлення про успіх."""
    telegram_commands.pending_token_updates[505] = telegram_commands.PendingTokenUpdate(chat_id=700, token='refresh')

    calls: list[tuple[int, str]] = []

    def fake_register(tg_user_id: int, token: str) -> RegistrationOutcome:
        calls.append((tg_user_id, token))
        return RegistrationOutcome.SUCCESS

    monkeypatch.setattr(telegram_commands, 'register_user', fake_register, raising=False)
    monkeypatch.setattr(
        telegram_commands,
        'get_authorized_yt_user',
        lambda _tg_id: ('agent', 'agent@example.com', 'YT-1'),
        raising=False,
    )

    processed: bool = telegram_commands.handle_confirm_reconnect(700, 100, 505, True)

    assert processed is True
    assert calls == [(505, 'refresh')]
    assert telegram_commands.pending_token_updates == {}
    delete_payload = last_payload(setup_state, 'deleteMessage')
    assert delete_payload == {'chat_id': 700, 'message_id': 100}
    send_payload = last_payload(setup_state)
    assert send_payload['text'] == render(Msg.CONNECT_SUCCESS_UPDATED)
    assert send_payload['parse_mode'] == 'Markdown'


def test_confirm_reconnect_handles_no_change(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Підтвердження без змін надсилає відповідне повідомлення."""
    telegram_commands.pending_token_updates[606] = telegram_commands.PendingTokenUpdate(chat_id=700, token='same')
    monkeypatch.setattr(
        telegram_commands,
        'register_user',
        lambda *_: RegistrationOutcome.ALREADY_CONNECTED,
        raising=False,
    )

    processed: bool = telegram_commands.handle_confirm_reconnect(700, 101, 606, True)

    assert processed is True
    delete_payload = last_payload(setup_state, 'deleteMessage')
    assert delete_payload == {'chat_id': 700, 'message_id': 101}
    send_payload = last_payload(setup_state)
    assert send_payload['text'] == render(Msg.CONNECT_ALREADY_CONNECTED)
    assert send_payload['parse_mode'] == 'Markdown'


def test_confirm_reconnect_rejects_foreign_token(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Підтвердження відхиляє токен, який належить іншому Telegram."""
    telegram_commands.pending_token_updates[707] = telegram_commands.PendingTokenUpdate(chat_id=700, token='intruder')
    monkeypatch.setattr(
        telegram_commands,
        'register_user',
        lambda *_: RegistrationOutcome.FOREIGN_OWNER,
        raising=False,
    )

    processed: bool = telegram_commands.handle_confirm_reconnect(700, 102, 707, True)

    assert processed is True
    delete_payload = last_payload(setup_state, 'deleteMessage')
    assert delete_payload == {'chat_id': 700, 'message_id': 102}
    send_payload = last_payload(setup_state)
    assert send_payload['text'] == render(Msg.CONNECT_ALREADY_LINKED)
    assert send_payload['parse_mode'] == 'Markdown'


def test_confirm_reconnect_decline(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Відмова видаляє запит та надсилає повідомлення без виклику register_user."""
    telegram_commands.pending_token_updates[606] = telegram_commands.PendingTokenUpdate(chat_id=700, token='keep-old')
    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(
        telegram_commands,
        'register_user',
        lambda *args: calls.append(args),
        raising=False,
    )

    processed: bool = telegram_commands.handle_confirm_reconnect(700, 103, 606, False)

    assert processed is True
    assert calls == []
    delete_payload = last_payload(setup_state, 'deleteMessage')
    assert delete_payload == {'chat_id': 700, 'message_id': 103}
    send_payload = last_payload(setup_state)
    assert send_payload['text'] == render(Msg.CONNECT_CANCELLED)
    assert send_payload['parse_mode'] == 'Markdown'


def test_token_submission_prompts_start_for_guests(setup_state: list[CapturedMessage]) -> None:
    """Звичайне повідомлення від неавторизованого користувача повертає підказку про /start."""
    message = build_message(909, 'привіт')
    handled = telegram_commands.handle_token_submission(700, message, 'привіт')

    assert handled is True
    payload = last_payload(setup_state)
    assert payload['text'] == render(Msg.CONNECT_NEEDS_START)
    assert payload['parse_mode'] == 'MarkdownV2'


def test_token_submission_prompts_start_for_token(monkeypatch: pytest.MonkeyPatch, setup_state: list[CapturedMessage]) -> None:
    """Bare-токен від активного користувача все одно веде до підказки про /start."""
    monkeypatch.setattr(telegram_commands, 'is_authorized', lambda _tg_id: True, raising=False)
    message = build_message(1001, 'token-xyz')

    handled = telegram_commands.handle_token_submission(700, message, 'token-xyz')

    assert handled is True
    payload = last_payload(setup_state)
    assert payload['text'] == render(Msg.CONNECT_NEEDS_START)
    assert payload['parse_mode'] == 'MarkdownV2'


def test_token_submission_ignores_regular_text_for_active_user(
    monkeypatch: pytest.MonkeyPatch,
    setup_state: list[CapturedMessage],
) -> None:
    """Будь-який текст активного користувача завершується підказкою про /start."""
    monkeypatch.setattr(telegram_commands, 'is_authorized', lambda _tg_id: True, raising=False)
    message = build_message(1002, 'звичайний текст')

    handled = telegram_commands.handle_token_submission(700, message, 'звичайний текст')

    assert handled is True
    payload = last_payload(setup_state)
    assert payload['text'] == render(Msg.CONNECT_NEEDS_START)
    assert payload['parse_mode'] == 'MarkdownV2'
