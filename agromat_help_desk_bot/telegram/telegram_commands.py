"""Implement business logic of Telegram commands for the bot."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import NamedTuple

from agromat_help_desk_bot.auth import (
    RegistrationError,
    RegistrationOutcome,
    deactivate_user,
    get_authorized_yt_user,
    is_authorized,
    register_user,
)
from agromat_help_desk_bot.config import NEW_STATUS_ALERT_SUFFIX_ADMIN_ID
from agromat_help_desk_bot.messages import Msg, get_template, render
from agromat_help_desk_bot.storage import update_alert_suffix
from agromat_help_desk_bot.telegram import context as telegram_context
from agromat_help_desk_bot.telegram.telegram_sender import TelegramSender, escape_html

logger: logging.Logger = logging.getLogger(__name__)

TOKEN_GUIDE_URL: str = 'https://www.jetbrains.com/help/youtrack/server/Manage-Permanent-Token.html'
CALLBACK_RECONNECT_START: str = 'reconnect:start'
CALLBACK_CONFIRM_YES: str = 'confirm_reconnect_yes'
CALLBACK_CONFIRM_NO: str = 'confirm_reconnect_no'
CALLBACK_UNLINK_YES: str = 'unlink:yes'
CALLBACK_UNLINK_NO: str = 'unlink:no'


class PendingTokenUpdate(NamedTuple):
    """Store data about a pending token update request."""

    chat_id: int
    token: str


pending_token_updates: dict[int, PendingTokenUpdate] = {}

__all__ = [
    'PendingTokenUpdate',
    'pending_token_updates',
    'CALLBACK_RECONNECT_START',
    'CALLBACK_CONFIRM_YES',
    'CALLBACK_CONFIRM_NO',
    'CALLBACK_UNLINK_YES',
    'CALLBACK_UNLINK_NO',
    'handle_start_command',
    'handle_connect_command',
    'handle_reconnect_shortcut',
    'handle_unlink_decision',
    'handle_confirm_reconnect',
    'handle_unlink_command',
    'handle_token_submission',
    'notify_authorization_required',
    'configure_sender',
    'handle_set_suffix_command',
]


def configure_sender(sender: TelegramSender) -> None:
    """Configure TelegramSender for all commands."""
    telegram_context.set_sender(sender)


def _require_sender() -> TelegramSender:
    return telegram_context.get_sender()


async def handle_start_command(chat_id: int, message: Mapping[str, object]) -> None:
    """Determine user status and send connection instructions.

    :param chat_id: Telegram chat identifier.
    :param message: Telegram message as dict.
    """
    tg_user_id = _extract_user_id(message)
    if tg_user_id is None:
        await _reply(chat_id, render(Msg.ERR_TG_ID_UNAVAILABLE))
        return

    login, email, _ = await asyncio.to_thread(get_authorized_yt_user, tg_user_id)
    if not login:
        keyboard: dict[str, object] = {
            'inline_keyboard': [
                [{'text': render(Msg.CONNECT_GUIDE_BUTTON), 'url': TOKEN_GUIDE_URL}],
            ],
        }
        await _reply(chat_id, render(Msg.CONNECT_START_NEW), reply_markup=keyboard)
        return

    text: str = render(
        Msg.CONNECT_START_REGISTERED,
        login=escape_html(login or '-'),
        email=escape_html(email or '-'),
    )
    await _reply(chat_id, text)


async def handle_connect_command(chat_id: int, message: Mapping[str, object], text: str) -> None:
    """Accept token from ``/connect`` command and link or update.

    :param chat_id: Telegram chat identifier.
    :param message: Telegram message as dict.
    :param text: Full command text.
    """
    tg_user_id = _extract_user_id(message)
    if tg_user_id is None:
        await _reply(chat_id, render(Msg.ERR_TG_ID_UNAVAILABLE))
        return

    token = _extract_token_argument(text)
    if token is None:
        await _reply(chat_id, render(Msg.CONNECT_EXPECTS_TOKEN))
        return

    authorized: bool = await asyncio.to_thread(is_authorized, tg_user_id)
    if not authorized:
        await _complete_registration(chat_id, tg_user_id, token, Msg.CONNECT_SUCCESS_NEW)
        return

    await _prepare_token_update(chat_id, tg_user_id, token)


async def handle_reconnect_shortcut(chat_id: int) -> None:
    """Explain how to update token after pressing button in ``/start``.

    :param chat_id: Telegram chat identifier.
    """
    await _reply(chat_id, render(Msg.CONNECT_SHORTCUT_PROMPT))


async def handle_unlink_decision(chat_id: int, message_id: int, tg_user_id: int, accept: bool) -> bool:
    """Process confirmation or cancellation of unlink."""
    await _delete_message(chat_id, message_id)

    authorized: bool = await asyncio.to_thread(is_authorized, tg_user_id)
    if not authorized:
        return False

    if not accept:
        await _reply(chat_id, render(Msg.UNLINK_CANCELLED))
        return True

    await asyncio.to_thread(deactivate_user, tg_user_id)
    await _reply(chat_id, render(Msg.AUTH_UNLINK_DONE))
    return True


async def handle_confirm_reconnect(chat_id: int, message_id: int, tg_user_id: int, accept: bool) -> bool:
    """Handle inline choice to confirm or cancel token update.

    :param tg_user_id: Telegram user identifier.
    :param accept: ``True`` if user confirmed update.
    :returns: ``True`` if callback recognized.
    """
    await _delete_message(chat_id, message_id)

    pending = pending_token_updates.pop(tg_user_id, None)
    if pending is None:
        logger.debug('Відсутній запит на оновлення токена: tg_user_id=%s', tg_user_id)
        return False

    if not accept:
        await _reply(chat_id, render(Msg.CONNECT_CANCELLED))
        return True

    await _complete_registration(chat_id, tg_user_id, pending.token, Msg.CONNECT_SUCCESS_UPDATED)
    return True


async def handle_unlink_command(chat_id: int, message: Mapping[str, object]) -> None:
    """Request confirmation to unlink user.

    :param chat_id: Chat identifier.
    :param message: Telegram message.
    """
    tg_user_id = _extract_user_id(message)
    if tg_user_id is None:
        await _reply(chat_id, render(Msg.ERR_TG_ID_UNAVAILABLE))
        return

    authorized: bool = await asyncio.to_thread(is_authorized, tg_user_id)
    if not authorized:
        await _reply(chat_id, render(Msg.AUTH_NOTHING_TO_UNLINK))
        return

    keyboard: dict[str, object] = {
        'inline_keyboard': [
            [
                {'text': render(Msg.UNLINK_CONFIRM_YES_BUTTON), 'callback_data': CALLBACK_UNLINK_YES},
                {'text': render(Msg.UNLINK_CONFIRM_NO_BUTTON), 'callback_data': CALLBACK_UNLINK_NO},
            ],
        ],
    }
    await _reply(chat_id, render(Msg.UNLINK_CONFIRM_PROMPT), reply_markup=keyboard)


async def handle_set_suffix_command(chat_id: int, message: Mapping[str, object], text: str) -> None:
    """Update alert suffix if Telegram user is allowed."""
    tg_user_id = _extract_user_id(message)
    if tg_user_id is None or NEW_STATUS_ALERT_SUFFIX_ADMIN_ID is None or tg_user_id != NEW_STATUS_ALERT_SUFFIX_ADMIN_ID:
        await _reply(chat_id, render(Msg.ERR_COMMAND_UNAVAILABLE))
        return
    parts: list[str] = text.split(maxsplit=1)
    if len(parts) != 2:
        await _reply(chat_id, render(Msg.SUFFIX_USAGE))
        return
    suffix: str = parts[1].strip()
    await asyncio.to_thread(update_alert_suffix, suffix)
    escaped: str = escape_html(suffix)
    await _reply(chat_id, render(Msg.SUFFIX_UPDATED, value=escaped))


async def handle_token_submission(chat_id: int, message: Mapping[str, object], text: str) -> bool:
    """Respond to private message, hinting command format.

    :param chat_id: Chat identifier.
    :param message: Telegram message.
    :param text: Message text without commands.
    :returns: ``True`` if handled.
    """
    candidate: str = text.strip()
    if not candidate or candidate.startswith('/'):
        await _reply(chat_id, render(Msg.CONNECT_NEEDS_START))
        return True

    tg_user_id = _extract_user_id(message)
    if tg_user_id is None:
        await _reply(chat_id, render(Msg.ERR_TG_ID_UNAVAILABLE))
        return True

    authorized: bool = await asyncio.to_thread(is_authorized, tg_user_id)
    if not authorized:
        await _reply(chat_id, render(Msg.CONNECT_NEEDS_START))
        return True

    await _reply(chat_id, render(Msg.CONNECT_NEEDS_START))
    return True


async def notify_authorization_required(chat_id: int) -> None:
    """Notify that bot must be linked before using command.

    :param chat_id: Chat identifier.
    """
    await _reply(chat_id, render(Msg.AUTH_REQUIRED))


async def _prepare_token_update(chat_id: int, tg_user_id: int, token: str) -> None:
    """Prepare token update confirmation."""
    login, email, _ = await asyncio.to_thread(get_authorized_yt_user, tg_user_id)
    pending_token_updates[tg_user_id] = PendingTokenUpdate(chat_id=chat_id, token=token)
    await _reply(
        chat_id,
        render(
            Msg.CONNECT_CONFIRM_PROMPT,
            login=escape_html(login or '-'),
            email=escape_html(email or '-'),
        ),
        reply_markup=_confirm_keyboard(),
    )


async def _complete_registration(chat_id: int, tg_user_id: int, token: str, success_msg: Msg) -> None:
    """Perform token registration and send result to user."""
    try:
        outcome: RegistrationOutcome = await asyncio.to_thread(register_user, tg_user_id, token)
    except RegistrationError as err:
        logger.info('Не вдалося зберегти токен користувача %s: %s', tg_user_id, err)
        await _reply(chat_id, _map_registration_error(err))
        return
    if outcome is RegistrationOutcome.FOREIGN_OWNER:
        await _reply(chat_id, render(Msg.CONNECT_ALREADY_LINKED))
        return
    if outcome is RegistrationOutcome.ALREADY_CONNECTED:
        await _reply(chat_id, render(Msg.CONNECT_ALREADY_CONNECTED))
        return

    login, email, yt_user_id = await asyncio.to_thread(get_authorized_yt_user, tg_user_id)
    logger.info('Токен збережено: tg_user_id=%s yt_user_id=%s', tg_user_id, yt_user_id)
    template: str = get_template(success_msg)
    placeholders: dict[str, str] = {}
    if '{login' in template:
        placeholders['login'] = escape_html(login or '-')
    if '{email' in template:
        placeholders['email'] = escape_html(email or '-')
    if '{yt_id' in template:
        placeholders['yt_id'] = escape_html(yt_user_id or '-')
    await _reply(chat_id, render(success_msg, **placeholders))


async def _delete_message(chat_id: int, message_id: int) -> None:
    """Delete confirmation message, ignoring errors."""
    sender = _require_sender()
    try:
        await sender.delete_message(chat_id, message_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug('Ігнорують помилку видалення повідомлення %s: %s', message_id, exc)


def _confirm_keyboard() -> dict[str, object]:
    """Create inline keyboard for token update confirmation."""
    return {
        'inline_keyboard': [
            [
                {'text': render(Msg.CONNECT_CONFIRM_YES_BUTTON), 'callback_data': CALLBACK_CONFIRM_YES},
                {'text': render(Msg.CONNECT_CONFIRM_NO_BUTTON), 'callback_data': CALLBACK_CONFIRM_NO},
            ],
        ],
    }


def _extract_token_argument(text: str | None) -> str | None:
    """Return token from command text or ``None``."""
    if not text:
        return None
    parts: list[str] = text.split(maxsplit=1)
    if len(parts) != 2:
        return None
    token: str = parts[1].strip()
    return token or None


async def _reply(
    chat_id: int,
    text: str,
    *,
    reply_markup: dict[str, object] | None = None,
    parse_mode: str | None = 'HTML',
) -> None:
    """Send message to user."""
    sender = _require_sender()
    await sender.send_message(
        chat_id,
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


def _extract_user_id(message: Mapping[str, object]) -> int | None:
    """Return user identifier from message object."""
    from_candidate: object | None = message.get('from') or message.get('from_user')
    if isinstance(from_candidate, Mapping):
        user_id_obj: object | None = from_candidate.get('id')
        if isinstance(user_id_obj, int):
            return user_id_obj
    return None


def _map_registration_error(error: RegistrationError) -> str:
    """Return localized text for registration error."""
    message: str = str(error)
    if message == 'YouTrack тимчасово недоступний':
        return render(Msg.AUTH_LINK_TEMPORARY)
    if message == 'Помилка конфігурації сервера':
        return render(Msg.AUTH_LINK_CONFIG)
    return render(Msg.CONNECT_FAILURE_INVALID)
