"""Перевіряє маршрутизацію Telegram-повідомлень."""

from __future__ import annotations

from datetime import datetime

import pytest
from aiogram.types import Message

import agromat_it_desk_bot.telegram.telegram_aiogram as telegram_aiogram

pytestmark = pytest.mark.asyncio


def build_message(text: str) -> Message:
    """Створює мінімальний ``Message`` для тестів."""
    return Message.model_validate({
        'message_id': 1,
        'date': datetime.now(),
        'chat': {'id': 500, 'type': 'private'},
        'text': text,
    })


async def test_on_text_ignores_non_token_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Якщо повідомлення не схоже на токен, бот нічого не відповідає."""

    async def fake_submission(chat_id: int, payload: dict[str, object], text: str) -> bool:  # noqa: ARG001
        assert chat_id == 500
        assert payload['text'] == 'привіт'
        assert text == 'привіт'
        return False

    monkeypatch.setattr(telegram_aiogram, 'handle_token_submission', fake_submission)

    message: Message = build_message('привіт')
    await telegram_aiogram._on_text(message)


async def test_on_text_accepts_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Текст, розпізнаний як токен, передає дані в handle_token_submission."""

    async def fake_submission(chat_id: int, payload: dict[str, object], text: str) -> bool:
        assert chat_id == 500
        assert payload['text'] == 'token-123'
        assert text == 'token-123'
        return True

    monkeypatch.setattr(telegram_aiogram, 'handle_token_submission', fake_submission)

    message: Message = build_message('token-123')
    await telegram_aiogram._on_text(message)
