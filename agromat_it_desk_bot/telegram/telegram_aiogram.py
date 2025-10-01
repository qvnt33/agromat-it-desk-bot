"""Налаштовує Aiogram роутер для обробки Telegram команд."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .telegram_commands import (
    handle_confirm_login_command,
    handle_register_command,
    send_help,
)
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InaccessibleMessage, Message, Update

from agromat_it_desk_bot.config import BOT_TOKEN

if TYPE_CHECKING:
    from agromat_it_desk_bot.callback_handlers import CallbackContext

logger: logging.Logger = logging.getLogger(__name__)

_router: Router = Router()
_bot: Bot | None = None
_dispatcher: Dispatcher | None = None


async def process_update(payload: dict[str, Any]) -> None:
    """Передає webhook-оновлення у Dispatcher Aiogram."""
    dispatcher, bot = _ensure_app()
    update: Update = Update.model_validate(payload)

    logger.debug('Обробка Telegram update: update_id=%s', update.update_id)

    await dispatcher.feed_update(bot, update)


async def shutdown() -> None:
    """Закриває HTTP-сесію бота (для graceful shutdown)."""
    if _bot is not None:
        await _bot.session.close()
        logger.debug('HTTP-сесію бота Aiogram закрито')


def _ensure_app() -> tuple[Dispatcher, Bot]:
    """Створює або повертає готові Dispatcher та Bot."""
    global _bot, _dispatcher

    if _bot is None:
        if not BOT_TOKEN:
            raise RuntimeError('BOT_TOKEN не налаштовано; Aiogram неможливий')
        _bot = Bot(token=BOT_TOKEN)
        logger.debug('Створено екземпляр Bot з активним токеном')

    if _dispatcher is None:
        _dispatcher = Dispatcher()
        _dispatcher.include_router(_router)
        logger.debug('Створено Dispatcher та підключено router')
    return _dispatcher, _bot


async def _on_help(message: Message) -> None:
    """Надсилає інструкцію при командах /start та /help."""
    chat_id: int | None = message.chat.id if message.chat else None
    if chat_id is None:
        logger.debug('Невідомий chat_id для повідомлення: %s', message.model_dump(mode='python'))
        return
    logger.debug('Відправлення повідомлення /help: chat_id=%s', chat_id)
    await asyncio.to_thread(send_help, chat_id)


async def _on_register(message: Message) -> None:
    """Обробляє команду /register через існуючу бізнес-логіку."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено /register: chat_id=%s text=%s', chat_id, text)
        return

    payload: dict[str, object] = message.model_dump(mode='python')  # Серіалізоване повідомлення Telegram
    logger.debug('Переадресація /register в командний модуль: chat_id=%s', chat_id)
    await asyncio.to_thread(handle_register_command, chat_id, payload, text)


async def _on_confirm_login(message: Message) -> None:
    """Обробляє команду /confirm_login."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено /confirm_login: chat_id=%s text=%s', chat_id, text)
        return

    payload: dict[str, object] = message.model_dump(mode='python')  # Сирі дані повідомлення для бізнес-логіки
    logger.debug('Переадресація /confirm_login в командний модуль: chat_id=%s', chat_id)
    await asyncio.to_thread(handle_confirm_login_command, chat_id, payload, text)


async def _on_accept_issue_callback(query: CallbackQuery) -> None:
    """Обробляє callback натискання кнопки прийняття задачі."""
    from agromat_it_desk_bot import callback_handlers

    callback_message: Message | InaccessibleMessage | None = query.message
    if (not isinstance(callback_message, Message)
        or callback_message.chat is None
        or callback_message.message_id is None):
        logger.debug('Пропущено callback без повідомлення: %s', query.model_dump(mode='python'))
        return

    chat_id: int = callback_message.chat.id
    message_id: int = callback_message.message_id
    tg_user_id: int | None = query.from_user.id if query.from_user else None
    callback_id: str = query.id
    payload_text: str = query.data or ''  # Рядок дії callback

    logger.debug('Отримано callback: callback_id=%s payload=%s', callback_id, payload_text)

    if not callback_handlers.is_user_allowed(tg_user_id):
        logger.info('Callback відхилено: tg_user_id=%s не має прав', tg_user_id)
        await asyncio.to_thread(callback_handlers.reply_insufficient_rights, callback_id)
        return

    action, issue_id = callback_handlers.parse_action(payload_text)
    if action != 'accept' or not issue_id:
        logger.debug('Callback без дії "accept": action=%s issue_id=%s', action, issue_id)
        await asyncio.to_thread(callback_handlers.reply_unknown_action, callback_id)
        return

    context: 'CallbackContext' = callback_handlers.CallbackContext(callback_id,
                                                                   chat_id,
                                                                   message_id,
                                                                   payload_text,
                                                                   tg_user_id)
    logger.debug('Callback передано до handle_accept: issue_id=%s tg_user_id=%s', issue_id, tg_user_id)
    await asyncio.to_thread(callback_handlers.handle_accept, issue_id, context)


_router.message(CommandStart())(_on_help)
_router.message(Command(commands=['help']))(_on_help)
_router.message(Command(commands=['register']))(_on_register)
_router.message(Command(commands=['confirm_login']))(_on_confirm_login)
_router.callback_query()(_on_accept_issue_callback)


_KNOWN_SLASH_COMMANDS: set[str] = {'/start', '/help', '/register', '/confirm_login'}


async def _on_unknown_message(message: Message) -> None:
    """Надсилає довідку, якщо отримано текст без відомої команди."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено повідомлення без тексту або chat_id: %s', message.model_dump(mode='python'))
        return

    command_token: str = text.split(maxsplit=1)[0]
    normalized_command: str = command_token.split('@', 1)[0].lower()
    if normalized_command in _KNOWN_SLASH_COMMANDS:
        logger.debug('Повідомлення з відомою командою, обробка пропущена: %s', normalized_command)
        return

    logger.debug('Отримано невідому команду: chat_id=%s текст=%s', chat_id, text)
    await asyncio.to_thread(send_help, chat_id)


_router.message(F.text)(_on_unknown_message)
