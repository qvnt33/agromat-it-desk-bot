"""Contains Aiogram middleware for user authorization checks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from agromat_it_desk_bot.auth import is_authorized
from agromat_it_desk_bot.telegram.telegram_commands import notify_authorization_required


class AuthorizationMiddleware(BaseMiddleware):
    """Check whether user has activated bot access."""

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
            if tg_user_id is None:
                return await handler(event, data)
            authorized: bool = await asyncio.to_thread(is_authorized, tg_user_id)
            if authorized:
                return await handler(event, data)

            chat_id: int | None = event.chat.id if event.chat else None
            if chat_id is not None:
                await notify_authorization_required(chat_id)
            return None

        return await handler(event, data)


def _extract_command(text: str | None) -> str | None:
    """Return command from message or ``None``."""
    if not text or not text.startswith('/'):
        return None
    token: str = text.split(maxsplit=1)[0]
    normalized: str = token.split('@', 1)[0].lstrip('/').lower()
    return normalized or None
