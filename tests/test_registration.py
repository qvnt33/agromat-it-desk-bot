"""Перевіряє допоміжні відповіді для Telegram."""

from __future__ import annotations

import pytest

import agromat_help_desk_bot.telegram.telegram_commands as telegram_commands
from agromat_help_desk_bot.messages import Msg, render
from tests.conftest import FakeTelegramSender

pytestmark = pytest.mark.asyncio


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
