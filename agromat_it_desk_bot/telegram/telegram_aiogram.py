"""Налаштовує Aiogram роутер для обробки Telegram команд."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InaccessibleMessage, Message, Update

from agromat_it_desk_bot.config import BOT_TOKEN
from agromat_it_desk_bot.telegram.middleware import AuthorizationMiddleware
from agromat_it_desk_bot.telegram.telegram_commands import (
    CALLBACK_CONFIRM_NO,
    CALLBACK_CONFIRM_YES,
    CALLBACK_RECONNECT_START,
    CALLBACK_UNLINK_YES,
    CALLBACK_UNLINK_NO,
    handle_confirm_reconnect,
    handle_connect_command,
    handle_link_command,
    handle_reconnect_shortcut,
    handle_start_command,
    handle_token_submission,
    handle_unlink_command,
    handle_unlink_decision,
    send_help,
)

if TYPE_CHECKING:
    from agromat_it_desk_bot.callback_handlers import CallbackContext

logger: logging.Logger = logging.getLogger(__name__)

_router: Router = Router()
_router.message.middleware(AuthorizationMiddleware({'start', 'help', 'connect', 'link', 'unlink'}))
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


async def _on_start(message: Message) -> None:
    """Надсилає інструкцію для команди /start."""
    chat_id: int | None = message.chat.id if message.chat else None
    if chat_id is None:
        logger.debug('Невідомий chat_id для /start: %s', message.model_dump(mode='python'))
        return
    payload: dict[str, object] = message.model_dump(mode='python')
    await asyncio.to_thread(handle_start_command, chat_id, payload)


async def _on_help(message: Message) -> None:
    """Пояснює процедуру привʼязки токена."""
    chat_id: int | None = message.chat.id if message.chat else None
    if chat_id is None:
        logger.debug('Невідомий chat_id для /help: %s', message.model_dump(mode='python'))
        return
    await asyncio.to_thread(send_help, chat_id)


async def _on_connect(message: Message) -> None:
    """Обробляє команду /connect."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено /connect: chat_id=%s text=%s', chat_id, text)
        return
    payload: dict[str, object] = message.model_dump(mode='python')
    await asyncio.to_thread(handle_connect_command, chat_id, payload, text)


async def _on_link(message: Message) -> None:
    """Обробляє команду /link."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено /link: chat_id=%s text=%s', chat_id, text)
        return
    payload: dict[str, object] = message.model_dump(mode='python')
    await asyncio.to_thread(handle_link_command, chat_id, payload, text)


async def _on_unlink(message: Message) -> None:
    """Обробляє команду /unlink."""
    chat_id: int | None = message.chat.id if message.chat else None
    if chat_id is None:
        logger.debug('Пропущено /unlink: chat_id=%s', chat_id)
        return
    payload: dict[str, object] = message.model_dump(mode='python')
    await asyncio.to_thread(handle_unlink_command, chat_id, payload)


async def _on_text(message: Message) -> None:
    """Розглядає повідомлення як токен або надсилає підказку."""
    chat_id: int | None = message.chat.id if message.chat else None
    text: str | None = message.text
    if chat_id is None or text is None:
        logger.debug('Пропущено повідомлення без тексту: %s', message.model_dump(mode='python'))
        return

    payload: dict[str, object] = message.model_dump(mode='python')
    await asyncio.to_thread(handle_token_submission, chat_id, payload, text)


async def _on_reconnect_shortcut_callback(query: CallbackQuery) -> None:
    """Обробляє кнопку швидкого переходу до оновлення токена."""
    callback_message: Message | InaccessibleMessage | None = query.message
    if not isinstance(callback_message, Message) or callback_message.chat is None:
        logger.debug('Пропущено reconnect:start без повідомлення: %s', query.model_dump(mode='python'))
        await query.answer()
        return

    chat_id: int = callback_message.chat.id
    await query.answer()
    await asyncio.to_thread(handle_reconnect_shortcut, chat_id)


async def _process_confirm_callback(query: CallbackQuery, accept: bool) -> None:
    """Обробляє підтвердження або скасування оновлення токена."""
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

    processed: bool = await asyncio.to_thread(handle_confirm_reconnect, chat_id, message_id, tg_user_id, accept)
    if processed:
        await query.answer()
        return

    await query.answer('Запит на оновлення не знайдено', show_alert=True)


async def _on_confirm_yes(query: CallbackQuery) -> None:
    """Підтверджує оновлення токена."""
    await _process_confirm_callback(query, True)


async def _on_confirm_no(query: CallbackQuery) -> None:
    """Скасовує оновлення токена."""
    await _process_confirm_callback(query, False)


async def _on_unlink_yes(query: CallbackQuery) -> None:
    """Підтверджує відʼєднання поточного акаунта."""
    await _process_unlink_callback(query, True)


async def _on_unlink_no(query: CallbackQuery) -> None:
    """Скасовує відʼєднання."""
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

    processed: bool = await asyncio.to_thread(handle_unlink_decision, chat_id, message_id, tg_user_id, accept)
    if processed:
        await query.answer()
    else:
        await query.answer('Запит на відʼєднання не знайдено', show_alert=True)


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


_router.message(CommandStart())(_on_start)
_router.message(Command(commands=['help']))(_on_help)
_router.message(Command(commands=['connect']))(_on_connect)
_router.message(Command(commands=['link']))(_on_link)
_router.message(Command(commands=['unlink']))(_on_unlink)
_router.callback_query(F.data == CALLBACK_RECONNECT_START)(_on_reconnect_shortcut_callback)
_router.callback_query(F.data == CALLBACK_CONFIRM_YES)(_on_confirm_yes)
_router.callback_query(F.data == CALLBACK_CONFIRM_NO)(_on_confirm_no)
_router.callback_query(F.data == CALLBACK_UNLINK_YES)(_on_unlink_yes)
_router.callback_query(F.data == CALLBACK_UNLINK_NO)(_on_unlink_no)
_router.callback_query()(_on_accept_issue_callback)
_router.message(F.text)(_on_text)
