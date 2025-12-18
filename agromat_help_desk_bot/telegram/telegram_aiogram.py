"""Configure Aiogram router to handle Telegram commands."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InaccessibleMessage, Message, Update

from agromat_help_desk_bot.telegram.middleware import AuthorizationMiddleware
from agromat_help_desk_bot.telegram.telegram_commands import (
    CALLBACK_CONFIRM_NO,
    CALLBACK_CONFIRM_YES,
    CALLBACK_RECONNECT_START,
    CALLBACK_UNLINK_NO,
    CALLBACK_UNLINK_YES,
    handle_confirm_reconnect,
    handle_connect_command,
    handle_reconnect_shortcut,
    handle_set_suffix_command,
    handle_start_command,
    handle_token_submission,
    handle_unlink_command,
    handle_unlink_decision,
)

if TYPE_CHECKING:
    from agromat_help_desk_bot.callback_handlers import CallbackContext

logger: logging.Logger = logging.getLogger(__name__)

_router: Router = Router()
_router.message.middleware(AuthorizationMiddleware({'start', 'connect', 'unlink', 'setsuffix'}))
_bot: Bot | None = None
_dispatcher: Dispatcher | None = None
_router_registered: bool = False


def configure(bot: Bot, dispatcher: Dispatcher) -> None:
    """Store Bot and Dispatcher, attach router."""
    global _bot, _dispatcher, _router_registered
    _bot = bot
    _dispatcher = dispatcher
    if not _router_registered:
        _dispatcher.include_router(_router)
        _router_registered = True
        logger.debug('Router підключено до Dispatcher')


async def process_update(payload: dict[str, Any]) -> None:
    """Pass webhook update to Aiogram Dispatcher."""
    if _dispatcher is None or _bot is None:
        raise RuntimeError('Aiogram бот не сконфігурований')
    update: Update = Update.model_validate(payload)

    logger.debug('Обробка Telegram update: update_id=%s', update.update_id)

    await _dispatcher.feed_update(_bot, update)


async def shutdown() -> None:
    """Close bot HTTP session (graceful shutdown)."""
    if _bot is not None:
        await _bot.session.close()
        logger.debug('HTTP-сесію бота Aiogram закрито')


async def _on_start(message: Message) -> None:
    """Send instructions for /start command."""
    chat_id: int | None = message.chat.id if message.chat else None
    if chat_id is None:
        logger.debug('Невідомий chat_id для /start: %s', message.model_dump(mode='python'))
        return
    payload: dict[str, object] = message.model_dump(mode='python')
    await handle_start_command(chat_id, payload)


async def _on_connect(message: Message) -> None:
    """Handle /connect command."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено /connect: chat_id=%s text=%s', chat_id, text)
        return
    payload: dict[str, object] = message.model_dump(mode='python')
    await handle_connect_command(chat_id, payload, text)


async def _on_unlink(message: Message) -> None:
    """Handle /unlink command."""
    chat_id: int | None = message.chat.id if message.chat else None
    if chat_id is None:
        logger.debug('Пропущено /unlink: chat_id=%s', chat_id)
        return
    payload: dict[str, object] = message.model_dump(mode='python')
    await handle_unlink_command(chat_id, payload)


async def _on_set_suffix(message: Message) -> None:
    """Handle /setsuffix command."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено /setsuffix: chat_id=%s text=%s', chat_id, text)
        return
    payload: dict[str, object] = message.model_dump(mode='python')
    await handle_set_suffix_command(chat_id, payload, text)


async def _on_text(message: Message) -> None:
    """Treat message as token or send a hint."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено повідомлення без тексту: %s', message.model_dump(mode='python'))
        return

    payload: dict[str, object] = message.model_dump(mode='python')
    await handle_token_submission(chat_id, payload, text)


async def _on_reconnect_shortcut_callback(query: CallbackQuery) -> None:
    """Handle quick reconnect button for token update."""
    callback_message: Message | InaccessibleMessage | None = query.message
    if not isinstance(callback_message, Message) or callback_message.chat is None:
        logger.debug('Пропущено reconnect:start без повідомлення: %s', query.model_dump(mode='python'))
        await query.answer()
        return

    chat_id: int = callback_message.chat.id
    await query.answer()
    await handle_reconnect_shortcut(chat_id)


async def _process_confirm_callback(query: CallbackQuery, accept: bool) -> None:
    """Handle confirmation or cancellation of token update."""
    callback_message: Message | InaccessibleMessage | None = query.message
    tg_user_id: int | None = query.from_user.id if query.from_user else None
    if tg_user_id is None or not isinstance(callback_message, Message) or callback_message.chat is None:
        await query.answer('Невідомий користувач', show_alert=True)
        return

    chat_id: int = callback_message.chat.id
    message_id: int | None = callback_message.message_id
    if message_id is None:
        await query.answer('Невідоме повідомлення', show_alert=True)
        return

    processed: bool = await handle_confirm_reconnect(chat_id, message_id, tg_user_id, accept)
    if processed:
        await query.answer()
        return

    await query.answer('Запит на оновлення не знайдено', show_alert=True)


async def _on_confirm_yes(query: CallbackQuery) -> None:
    """Confirm token update."""
    await _process_confirm_callback(query, True)


async def _on_confirm_no(query: CallbackQuery) -> None:
    """Cancel token update."""
    await _process_confirm_callback(query, False)


async def _on_unlink_yes(query: CallbackQuery) -> None:
    """Confirm unlink of current account."""
    await _process_unlink_callback(query, True)


async def _on_unlink_no(query: CallbackQuery) -> None:
    """Cancel unlink."""
    await _process_unlink_callback(query, False)


async def _process_unlink_callback(query: CallbackQuery, accept: bool) -> None:
    callback_message: Message | InaccessibleMessage | None = query.message
    tg_user_id: int | None = query.from_user.id if query.from_user else None
    if tg_user_id is None or not isinstance(callback_message, Message) or callback_message.chat is None:
        await query.answer('Невідомий користувач', show_alert=True)
        return

    chat_id: int = callback_message.chat.id
    message_id: int | None = callback_message.message_id
    if message_id is None:
        await query.answer('Невідоме повідомлення', show_alert=True)
        return

    processed: bool = await handle_unlink_decision(chat_id, message_id, tg_user_id, accept)
    if processed:
        await query.answer()
    else:
        await query.answer('Запит на відʼєднання не знайдено', show_alert=True)


async def _on_accept_issue_callback(query: CallbackQuery) -> None:
    """Handle callback of pressing accept issue button."""
    from agromat_help_desk_bot import callback_handlers

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
    payload_text: str = query.data or ''  # Callback action string

    logger.debug('Отримано callback: callback_id=%s payload=%s', callback_id, payload_text)

    action, issue_id = callback_handlers.parse_action(payload_text)
    if action != 'accept' or not issue_id:
        logger.debug('Callback без дії "accept": action=%s issue_id=%s', action, issue_id)
        await callback_handlers.reply_unknown_action(callback_id)
        return

    context: 'CallbackContext' = callback_handlers.CallbackContext(callback_id,
                                                                   chat_id,
                                                                   message_id,
                                                                   payload_text,
                                                                   tg_user_id)
    logger.debug('Callback передано до handle_accept: issue_id=%s tg_user_id=%s', issue_id, tg_user_id)
    await callback_handlers.handle_accept(issue_id, context)


_router.message(CommandStart())(_on_start)
_router.message(Command(commands=['connect']))(_on_connect)
_router.message(Command(commands=['unlink']))(_on_unlink)
_router.message(Command(commands=['setsuffix']))(_on_set_suffix)
_router.callback_query(F.data == CALLBACK_RECONNECT_START)(_on_reconnect_shortcut_callback)
_router.callback_query(F.data == CALLBACK_CONFIRM_YES)(_on_confirm_yes)
_router.callback_query(F.data == CALLBACK_CONFIRM_NO)(_on_confirm_no)
_router.callback_query(F.data == CALLBACK_UNLINK_YES)(_on_unlink_yes)
_router.callback_query(F.data == CALLBACK_UNLINK_NO)(_on_unlink_no)
_router.callback_query()(_on_accept_issue_callback)
_router.message(F.text)(_on_text)
