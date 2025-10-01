"""Перевіряє обробку невідомих повідомлень у Telegram роутері."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

import pytest
from aiogram.types import Message

import agromat_it_desk_bot.telegram.telegram_aiogram as telegram_aiogram


def test_unknown_message_sends_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """Невідомий текст має повертати інструкцію для користувача."""
    captured_chat_ids: list[int] = []

    def fake_send_help(chat_id: int) -> None:
        captured_chat_ids.append(chat_id)

    async def fake_to_thread(
        func: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object:
        result: object = func(*args, **kwargs)
        await asyncio.sleep(0)
        return result

    monkeypatch.setattr(telegram_aiogram, 'send_help', fake_send_help)
    monkeypatch.setattr(asyncio, 'to_thread', fake_to_thread, raising=False)

    message: Message = Message.model_validate({
        'message_id': 101,
        'date': datetime.now(),
        'chat': {'id': 555, 'type': 'private'},
        'text': 'привіт',
    })

    asyncio.run(telegram_aiogram._on_unknown_message(message))

    assert captured_chat_ids == [555]
