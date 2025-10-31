"""Містить інтерфейс та реалізацію асинхронного відправника Telegram."""

from __future__ import annotations

import asyncio
import logging
from html import escape
from typing import Any, Protocol, runtime_checkable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

logger: logging.Logger = logging.getLogger(__name__)


def escape_html(text: str) -> str:
    """Безпечно екранує текст для HTML parse_mode."""
    return escape(text, quote=False)


@runtime_checkable
class TelegramSender(Protocol):
    """Описує очікуваний контракт взаємодії з Telegram Bot API."""

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = 'HTML',
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool = True,
    ) -> None: ...

    async def delete_message(self, chat_id: int | str, message_id: int) -> None: ...

    async def answer_callback(
        self,
        callback_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None: ...

    async def edit_reply_markup(
        self,
        chat_id: int | str,
        message_id: int,
        reply_markup: dict[str, Any] | None,
    ) -> None: ...

    async def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = 'HTML',
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool = True,
    ) -> None: ...


class AiogramTelegramSender:
    """Реалізація TelegramSender поверх aiogram.Bot з підтримкою Retry-After."""

    def __init__(
        self,
        bot: Bot,
        *,
        request_timeout: float = 10.0,
        max_attempts: int = 5,
    ) -> None:
        self._bot: Bot = bot
        self._request_timeout: float = request_timeout
        self._max_attempts: int = max_attempts

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = 'HTML',
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool = True,
    ) -> None:
        await self._request_with_retry(
            self._bot.send_message,
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
            request_timeout=self._request_timeout,
        )

    async def delete_message(self, chat_id: int | str, message_id: int) -> None:
        await self._request_with_retry(
            self._bot.delete_message,
            chat_id=chat_id,
            message_id=message_id,
            request_timeout=self._request_timeout,
        )

    async def answer_callback(
        self,
        callback_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        await self._request_with_retry(
            self._bot.answer_callback_query,
            callback_query_id=callback_id,
            text=text,
            show_alert=show_alert,
            request_timeout=self._request_timeout,
        )

    async def edit_reply_markup(
        self,
        chat_id: int | str,
        message_id: int,
        reply_markup: dict[str, Any] | None,
    ) -> None:
        await self._request_with_retry(
            self._bot.edit_message_reply_markup,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
            request_timeout=self._request_timeout,
        )

    async def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = 'HTML',
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool = True,
    ) -> None:
        await self._request_with_retry(
            self._bot.edit_message_text,
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
            request_timeout=self._request_timeout,
        )

    async def _request_with_retry(self, method: Any, /, **kwargs: Any) -> None:
        attempt: int = 0
        while True:
            try:
                await method(**kwargs)
                return
            except TelegramRetryAfter as exc:
                attempt += 1
                if attempt >= self._max_attempts:
                    logger.warning('Вичерпано спроби після RetryAfter=%s', exc.retry_after)
                    raise
                delay: float = max(exc.retry_after, 1.0)
                logger.info('Отримано 429, чекаємо %s с перед повтором', delay)
                await asyncio.sleep(delay)
            except TelegramAPIError:
                logger.exception('Помилка Telegram API для методу %s', getattr(method, '__name__', method))
                raise
