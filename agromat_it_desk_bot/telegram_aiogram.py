"""Налаштовує Aiogram роутер для обробки Telegram команд."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, Update

from agromat_it_desk_bot.callback_handlers import (
    CallbackContext,
    handle_accept,
    is_user_allowed,
    parse_action,
    reply_insufficient_rights,
    reply_unknown_action,
)
from agromat_it_desk_bot.config import BOT_TOKEN
from agromat_it_desk_bot.telegram_commands import (
    handle_confirm_login_command,
    handle_register_command,
    send_help,
)

logger: logging.Logger = logging.getLogger(__name__)

_router: Router = Router()
_bot: Bot | None = None
_dispatcher: Dispatcher | None = None


def _ensure_app() -> tuple[Dispatcher, Bot]:
    """Створює або повертає готові Dispatcher та Bot."""
    global _bot, _dispatcher
    if _bot is None:
        if not BOT_TOKEN:
            raise RuntimeError('BOT_TOKEN не налаштовано; Aiogram неможливий')
        _bot = Bot(token=BOT_TOKEN)
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        _dispatcher.include_router(_router)
    return _dispatcher, _bot


async def _on_help(message: Message) -> None:
    """Надсилає інструкцію при командах /start та /help."""
    chat_id: int | None = message.chat.id if message.chat else None
    if chat_id is None:
        logger.debug('Невідомий chat_id для повідомлення: %s', message.model_dump(mode='python'))
        return
    await asyncio.to_thread(send_help, chat_id)


async def _on_register(message: Message) -> None:
    """Обробляє команду /register через існуючу бізнес-логіку."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено /register: chat_id=%s text=%s', chat_id, text)
        return

    payload: dict[str, object] = message.model_dump(mode='python')
    await asyncio.to_thread(handle_register_command, chat_id, payload, text)


async def _on_confirm_login(message: Message) -> None:
    """Обробляє команду /confirm_login."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено /confirm_login: chat_id=%s text=%s', chat_id, text)
        return

    payload: dict[str, object] = message.model_dump(mode='python')
    await asyncio.to_thread(handle_confirm_login_command, chat_id, payload, text)


async def _on_callback(query: CallbackQuery) -> None:
    """Обробляє callback-запити (кнопка «Прийняти»)."""
    message: Message | None = query.message
    if message is None or message.chat is None or message.message_id is None:
        logger.debug('Пропущено callback без повідомлення: %s', query.model_dump(mode='python'))
        return

    chat_id: int = message.chat.id
    message_id: int = message.message_id
    tg_user_id: int | None = query.from_user.id if query.from_user else None
    callback_id: str = query.id
    payload_text: str = query.data or ''

    if not is_user_allowed(tg_user_id):
        await asyncio.to_thread(reply_insufficient_rights, callback_id)
        return

    action, issue_id = parse_action(payload_text)
    if action != 'accept' or not issue_id:
        await asyncio.to_thread(reply_unknown_action, callback_id)
        return

    context = CallbackContext(callback_id, chat_id, message_id, payload_text, tg_user_id)
    await asyncio.to_thread(handle_accept, issue_id, context)


async def process_update(payload: dict[str, Any]) -> None:
    """Передає webhook-оновлення у Dispatcher Aiogram."""
    dispatcher, bot = _ensure_app()
    update: Update = Update.model_validate(payload)
    await dispatcher.feed_update(bot, update)


async def shutdown() -> None:
    """Закриває HTTP-сесію бота (для graceful shutdown)."""
    if _bot is not None:
        await _bot.session.close()


_router.message(CommandStart())(_on_help)
_router.message(Command(commands=['help']))(_on_help)
_router.message(Command(commands=['register']))(_on_register)
_router.message(Command(commands=['confirm_login']))(_on_confirm_login)
_router.callback_query()(_on_callback)
