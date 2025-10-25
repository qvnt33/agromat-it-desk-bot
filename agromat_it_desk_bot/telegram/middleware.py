"""Містить Aiogram middleware для перевірки авторизації користувачів."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from agromat_it_desk_bot.auth import is_authorized
from agromat_it_desk_bot.telegram.telegram_commands import notify_authorization_required


class AuthorizationMiddleware(BaseMiddleware):
    """Перевіряє, чи має користувач активований доступ до бота."""

    def __init__(self, allowed_commands: set[str] | None = None) -> None:
        self._allowed_commands: set[str] = {command.lower() for command in (allowed_commands or set())}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            text: str | None = event.text
            command: str | None = _extract_command(text)
            if command is None or command in self._allowed_commands:
                return await handler(event, data)

            tg_user_id: int | None = event.from_user.id if event.from_user else None
            if tg_user_id is None or is_authorized(tg_user_id):
                return await handler(event, data)

            chat_id: int | None = event.chat.id if event.chat else None
            if chat_id is not None:
                await asyncio.to_thread(notify_authorization_required, chat_id)
            return None

        return await handler(event, data)


def _extract_command(text: str | None) -> str | None:
    """Повертає команду з повідомлення або ``None``."""
    if not text or not text.startswith('/'):
        return None
    token: str = text.split(maxsplit=1)[0]
    normalized: str = token.split('@', 1)[0].lstrip('/').lower()
    return normalized or None
