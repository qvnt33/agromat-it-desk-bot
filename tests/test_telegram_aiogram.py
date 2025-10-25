"""Перевіряє маршрутизацію Telegram-повідомлень."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

import pytest
from aiogram.types import Message

import agromat_it_desk_bot.telegram.telegram_aiogram as telegram_aiogram


def build_message(text: str) -> Message:
    """Створює мінімальний ``Message`` для тестів."""
    return Message.model_validate({
        'message_id': 1,
        'date': datetime.now(),
        'chat': {'id': 500, 'type': 'private'},
        'text': text,
    })


def patch_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Патчить ``asyncio.to_thread`` так, щоб виконання було синхронним."""

    async def fake_to_thread(
        func: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object:
        result: object = func(*args, **kwargs)
        await asyncio.sleep(0)
        return result

    monkeypatch.setattr(asyncio, 'to_thread', fake_to_thread, raising=False)


def test_on_text_ignores_non_token_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Якщо повідомлення не схоже на токен, бот нічого не відповідає."""
    patch_to_thread(monkeypatch)
    called: list[int] = []

    def fake_submission(chat_id: int, payload: dict[str, object], text: str) -> bool:  # noqa: ARG001
        return False

    def fake_help(chat_id: int) -> None:
        called.append(chat_id)

    monkeypatch.setattr(telegram_aiogram, 'handle_token_submission', fake_submission)
    monkeypatch.setattr(telegram_aiogram, 'send_help', fake_help)

    message: Message = build_message('привіт')
    asyncio.run(telegram_aiogram._on_text(message))

    assert called == []


def test_on_text_accepts_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Текст, розпізнаний як токен, не викликає send_help."""
    patch_to_thread(monkeypatch)
    help_calls: list[int] = []

    def fake_submission(chat_id: int, payload: dict[str, object], text: str) -> bool:
        assert chat_id == 500
        assert payload['text'] == 'token-123'
        assert text == 'token-123'
        return True

    def fake_help(chat_id: int) -> None:
        help_calls.append(chat_id)

    monkeypatch.setattr(telegram_aiogram, 'handle_token_submission', fake_submission)
    monkeypatch.setattr(telegram_aiogram, 'send_help', fake_help)

    message: Message = build_message('token-123')
    asyncio.run(telegram_aiogram._on_text(message))

    assert help_calls == []
