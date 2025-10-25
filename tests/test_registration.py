"""Перевіряє сумісність застарілих Telegram-команд."""

from __future__ import annotations

from typing import TypedDict

import pytest

import agromat_it_desk_bot.telegram.telegram_commands as telegram_commands
from agromat_it_desk_bot.messages import Msg, render


class CapturedMessage(TypedDict):
    method: str
    payload: dict[str, object]


@pytest.fixture(name='sent_messages')
def sent_messages_fixture(monkeypatch: pytest.MonkeyPatch) -> list[CapturedMessage]:
    """Перехоплює виклики до Telegram API."""
    sent: list[CapturedMessage] = []

    def fake_call_api(method: str, payload: dict[str, object]) -> None:  # pragma: no cover - технічний хук
        sent.append({'method': method, 'payload': payload})

    monkeypatch.setattr(telegram_commands, 'call_api', fake_call_api, raising=False)
    return sent


def build_message(tg_user_id: int, text: str) -> dict[str, object]:
    """Формує мінімальний payload повідомлення Telegram."""
    return {
        'chat': {'id': 123, 'type': 'private'},
        'from': {'id': tg_user_id},
        'from_user': {'id': tg_user_id},
        'text': text,
    }


def test_handle_link_command_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Команда /link повторно використовує логіку /connect."""
    captured: tuple[int, dict[str, object], str] | None = None

    def fake_connect(chat_id: int, message: dict[str, object], text: str) -> None:
        nonlocal captured
        captured = (chat_id, message, text)

    monkeypatch.setattr(telegram_commands, 'handle_connect_command', fake_connect, raising=False)

    message = build_message(111, '/link token-legacy')
    telegram_commands.handle_link_command(123, message, '/link token-legacy')

    assert captured is not None
    chat_id, payload, text = captured
    assert chat_id == 123
    assert payload['text'] == '/link token-legacy'
    assert text.startswith('/connect ')


def test_handle_reconnect_shortcut_sends_prompt(sent_messages: list[CapturedMessage]) -> None:
    """Кнопка заміни токена показує підказку з командою /connect."""
    telegram_commands.handle_reconnect_shortcut(123)

    assert len(sent_messages) == 1
    payload = sent_messages[0]['payload']
    assert payload['text'] == render(Msg.CONNECT_SHORTCUT_PROMPT)


def test_notify_authorization_required_uses_start(sent_messages: list[CapturedMessage]) -> None:
    """Підказка авторизації посилається на команду /start."""
    telegram_commands.notify_authorization_required(321)

    assert len(sent_messages) == 1
    payload = sent_messages[0]['payload']
    assert payload['text'] == render(Msg.AUTH_REQUIRED)
