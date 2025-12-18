"""Helpers for handling Telegram callbacks (accept button)."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import NamedTuple

from fastapi import HTTPException, Request

from agromat_help_desk_bot.auth import get_authorized_yt_user, get_user_token
from agromat_help_desk_bot.config import TELEGRAM_WEBHOOK_SECRET, YOUTRACK_STATE_IN_PROGRESS, YT_BASE_URL
from agromat_help_desk_bot.messages import Msg, render
from agromat_help_desk_bot.telegram import context as telegram_context
from agromat_help_desk_bot.telegram.telegram_sender import TelegramSender
from agromat_help_desk_bot.utils import format_telegram_message
from agromat_help_desk_bot.youtrack.youtrack_service import IssueDetails, assign_issue, fetch_issue_details

logger: logging.Logger = logging.getLogger(__name__)
_processed_accept_keys: set[str] = set()
_processed_queue: deque[str] = deque()
_processed_lock: asyncio.Lock = asyncio.Lock()
_PROCESSED_LIMIT: int = 512


class CallbackContext(NamedTuple):
    """Structured set of parameters from Telegram callback message."""

    callback_id: str
    chat_id: int
    message_id: int
    payload: str
    tg_user_id: int | None


def verify_telegram_secret(request: Request) -> None:
    """Validate Telegram webhook secret before handling callback.

    :param request: FastAPI request with Telegram headers.
    :raises HTTPException: 403 if secret mismatches.
    """
    if TELEGRAM_WEBHOOK_SECRET:
        secret: str | None = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if secret != TELEGRAM_WEBHOOK_SECRET:
            logger.warning('Невірний секрет Telegram вебхука')
            raise HTTPException(status_code=403, detail='Доступ заборонено.')


def parse_action(payload: str) -> tuple[str, str | None]:
    """Extract action name and parameter from callback string.

    :param payload: String like ``"accept|ABC-1"``.
    :returns: Pair ``(action name, issue ID)``.
    """
    action, _, issue_id = payload.partition('|')
    logger.debug('Розбір дії callback: action=%s issue_id=%s', action, issue_id)
    return action, issue_id or None


async def handle_accept(issue_id: str, context: CallbackContext) -> None:
    """Assign issue in YouTrack and reply to user.

    :param issue_id: Readable issue ID.
    :param context: Callback request context.
    """
    if context.tg_user_id is None:
        logger.warning('Callback без ідентифікатора користувача: issue_id=%s', issue_id)
        await reply_assign_error(context.callback_id)
        return

    try:
        login, email, yt_user_id = await asyncio.to_thread(get_authorized_yt_user, context.tg_user_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception('Не вдалося знайти користувача для прийняття: %s', exc)
        await reply_assign_error(context.callback_id)
        return
    if not any((login, email, yt_user_id)):
        logger.info('Прийняття без авторизації: tg_user_id=%s issue_id=%s', context.tg_user_id, issue_id)
        await reply_authorization_required(context.callback_id)
        return

    user_token: str | None
    try:
        user_token = await asyncio.to_thread(get_user_token, context.tg_user_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception('Не вдалося отримати токен користувача tg_user_id=%s: %s', context.tg_user_id, exc)
        await reply_assign_error(context.callback_id)
        return
    if not user_token:
        logger.info('Відсутній токен користувача, прийняття неможливе: tg_user_id=%s', context.tg_user_id)
        await reply_token_required(context.callback_id)
        return

    key: str = f'{context.chat_id}:{context.message_id}:{issue_id}'
    is_new: bool = await _register_accept_attempt(key)
    if not is_new:
        logger.info('Ігнорують дубль callback для %s', key)
        await reply_success(context.callback_id)
        return

    assigned: bool = await asyncio.to_thread(assign_issue, issue_id, login, email, yt_user_id, user_token)
    if not assigned:
        await reply_assign_failed(context.callback_id)
        logger.warning('Не вдалося призначити задачу через callback: issue_id=%s', issue_id)
        return

    await reply_success(context.callback_id)
    await _update_issue_message(context.chat_id, context.message_id, issue_id, login, email)
    await remove_keyboard(context.chat_id, context.message_id)
    logger.info('Задачу призначено через callback: issue_id=%s tg_user_id=%s', issue_id, context.tg_user_id)


async def reply_unknown_action(callback_id: str) -> None:
    """Respond to unknown callback action."""
    await _sender().answer_callback(callback_id, text=render(Msg.ERR_CALLBACK_UNKNOWN))


async def reply_success(callback_id: str) -> None:
    """Confirm successful assignment to user."""
    await _sender().answer_callback(callback_id, text=render(Msg.CALLBACK_ACCEPTED))


async def reply_assign_failed(callback_id: str) -> None:
    """Notify about failed assignment attempt."""
    await _sender().answer_callback(callback_id, text=render(Msg.ERR_CALLBACK_ASSIGN_FAILED), show_alert=True)


async def reply_assign_error(callback_id: str) -> None:
    """Show system error during assignment."""
    await _sender().answer_callback(callback_id, text=render(Msg.ERR_CALLBACK_ASSIGN_ERROR), show_alert=True)


async def reply_authorization_required(callback_id: str) -> None:
    """Explain authorization is required before accepting issue."""
    await _sender().answer_callback(callback_id, text=render(Msg.ERR_CALLBACK_AUTH_REQUIRED), show_alert=True)


async def reply_token_required(callback_id: str) -> None:
    """Explain personal token must be updated."""
    await _sender().answer_callback(callback_id, text=render(Msg.ERR_CALLBACK_TOKEN_REQUIRED), show_alert=True)


async def remove_keyboard(chat_id: int, message_id: int) -> None:
    """Remove keyboard from Telegram message after successful accept."""
    try:
        await _sender().edit_reply_markup(chat_id, message_id, {})
    except Exception as exc:  # noqa: BLE001
        logger.debug('Не вдалося прибрати клавіатуру: %s', exc)


def _sender() -> TelegramSender:
    return telegram_context.get_sender()


async def _update_issue_message(
    chat_id: int,
    message_id: int,
    issue_id: str,
    login: str | None,
    email: str | None,
) -> None:
    """Update Telegram message text after assigning issue."""
    details: IssueDetails | None = None
    try:
        details = await asyncio.to_thread(fetch_issue_details, issue_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception('Не вдалося отримати деталі задачі %s: %s', issue_id, exc)

    summary: str = ''
    description: str = ''
    assignee_text: str | None = None
    status_text: str | None = None
    author_text: str | None = None

    if details is not None:
        summary = str(details.summary or '')
        description = str(details.description or '')
        assignee_text = details.assignee or login or email
        status_text = details.status or YOUTRACK_STATE_IN_PROGRESS
        author_text = details.author
    else:
        assignee_text = login or email
        status_text = YOUTRACK_STATE_IN_PROGRESS

    if assignee_text:
        assignee_text = assignee_text.strip() or None
    if status_text:
        status_text = status_text.strip() or None
    if author_text:
        author_text = author_text.strip() or None

    url: str = _resolve_issue_url(issue_id)

    message_text: str = format_telegram_message(
        issue_id,
        summary,
        description,
        url,
        assignee=assignee_text,
        status=status_text,
        author=author_text,
    )

    try:
        await _sender().edit_message_text(
            chat_id,
            message_id,
            message_text,
            parse_mode='HTML',
            reply_markup=None,
            disable_web_page_preview=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug('Не вдалося оновити текст повідомлення: %s', exc)


def _resolve_issue_url(issue_id: str) -> str:
    """Compose issue URL for message use."""
    if issue_id and YT_BASE_URL:
        return f'{YT_BASE_URL}/issue/{issue_id}'
    return render(Msg.ERR_YT_ISSUE_NO_URL)


async def _register_accept_attempt(key: str) -> bool:
    async with _processed_lock:
        if key in _processed_accept_keys:
            return False
        _processed_accept_keys.add(key)
        _processed_queue.append(key)
        while len(_processed_queue) > _PROCESSED_LIMIT:
            expired: str = _processed_queue.popleft()
            _processed_accept_keys.discard(expired)
        return True
