"""Перевіряє сумісність застарілих Telegram-команд."""

from __future__ import annotations

import pytest

import agromat_it_desk_bot.telegram.telegram_commands as telegram_commands
from agromat_it_desk_bot.messages import Msg, render
from tests.conftest import FakeTelegramSender

pytestmark = pytest.mark.asyncio


def build_message(tg_user_id: int, text: str) -> dict[str, object]:
    """Формує мінімальний payload повідомлення Telegram."""
    return {
        'chat': {'id': 123, 'type': 'private'},
        'from': {'id': tg_user_id},
        'from_user': {'id': tg_user_id},
        'text': text,
    }


async def test_handle_link_command_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Команда /link повторно використовує логіку /connect."""
    captured: tuple[int, dict[str, object], str] | None = None

    async def fake_connect(chat_id: int, message: dict[str, object], text: str) -> None:
        nonlocal captured
        captured = (chat_id, message, text)

    monkeypatch.setattr(telegram_commands, 'handle_connect_command', fake_connect, raising=False)

    message = build_message(111, '/link token-legacy')
    await telegram_commands.handle_link_command(123, message, '/link token-legacy')

    assert captured is not None
    chat_id, payload, text = captured
    assert chat_id == 123
    assert payload['text'] == '/link token-legacy'
    assert text.startswith('/connect ')


async def test_handle_reconnect_shortcut_sends_prompt(fake_sender: FakeTelegramSender) -> None:
    """Кнопка заміни токена показує підказку з командою /connect."""
    await telegram_commands.handle_reconnect_shortcut(123)

    assert len(fake_sender.sent_messages) == 1
    payload = fake_sender.sent_messages[0]
    assert payload['text'] == render(Msg.CONNECT_SHORTCUT_PROMPT)


async def test_notify_authorization_required_uses_start(fake_sender: FakeTelegramSender) -> None:
    """Підказка авторизації посилається на команду /start."""
    await telegram_commands.notify_authorization_required(321)

    assert len(fake_sender.sent_messages) == 1
    payload = fake_sender.sent_messages[0]
    assert payload['text'] == render(Msg.AUTH_REQUIRED)
