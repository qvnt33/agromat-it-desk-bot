"""Надає хелпери для обробки Telegram callback'ів (кнопка "Прийняти")."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, NamedTuple

from fastapi import HTTPException, Request

from agromat_it_desk_bot.auth import get_authorized_yt_user, get_user_token
from agromat_it_desk_bot.config import TELEGRAM_WEBHOOK_SECRET, YOUTRACK_STATE_IN_PROGRESS, YT_BASE_URL
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.telegram import context as telegram_context
from agromat_it_desk_bot.telegram.telegram_sender import TelegramSender
from agromat_it_desk_bot.utils import format_telegram_message
from agromat_it_desk_bot.youtrack.youtrack_service import IssueDetails, assign_issue, fetch_issue_details

logger: logging.Logger = logging.getLogger(__name__)
_processed_accept_keys: set[str] = set()
_processed_queue: deque[str] = deque()
_processed_lock: asyncio.Lock = asyncio.Lock()
_PROCESSED_LIMIT: int = 512


class CallbackContext(NamedTuple):
    """Описує структурований набір параметрів із callback-повідомлення Telegram."""

    callback_id: str
    chat_id: int
    message_id: int
    payload: str
    tg_user_id: int | None


def verify_telegram_secret(request: Request) -> None:
    """Перевіряє секрет вебхука Telegram перед обробкою callback.

    :param request: Запит FastAPI із заголовками Telegram.
    :raises HTTPException: 403, якщо секрет не збігається.
    """
    if TELEGRAM_WEBHOOK_SECRET:
        secret: str | None = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if secret != TELEGRAM_WEBHOOK_SECRET:
            logger.warning('Невірний секрет Telegram вебхука')
            raise HTTPException(status_code=403, detail='Доступ заборонено.')


def parse_callback_payload(payload: Any) -> CallbackContext | None:
    """Розбирає callback-пейлоад та будує контекст.

    :param payload: Сирий JSON із даними Telegram.
    :returns: ``CallbackContext`` або ``None``.
    """
    callback = payload.get('callback_query')
    if callback is None:
        logger.debug('Callback payload без callback_query: %s', payload)
        return None

    callback_id_obj: object | None = callback.get('id')
    # Ідентифікатор callback для відповіді
    callback_id: str | None = str(callback_id_obj) if isinstance(callback_id_obj, (str, int)) else None

    from_user_mapping = callback.get('from')
    tg_user_id: int | None = None
    if from_user_mapping is not None:
        # Telegram ID користувача з оновлення
        tg_user_id_obj: object | None = from_user_mapping.get('id')
        if isinstance(tg_user_id_obj, int):
            tg_user_id = tg_user_id_obj

    chat_id: int | None = None
    message_id: int | None = None
    message_mapping = callback.get('message')
    if message_mapping is not None:
        chat_mapping = message_mapping.get('chat')
        if chat_mapping is not None:
            chat_id_obj: object | None = chat_mapping.get('id')
            if isinstance(chat_id_obj, int):
                chat_id = chat_id_obj

        message_id_obj: object | None = message_mapping.get('message_id')
        # Оригінальне повідомлення для редагування клавіатури
        if isinstance(message_id_obj, int):
            message_id = message_id_obj

    payload_raw: object | None = callback.get('data')
    payload_value: str = str(payload_raw) if isinstance(payload_raw, (str, int)) else ''

    if not (callback_id and chat_id and message_id):
        logger.debug('Некоректний callback: callback_id=%s chat_id=%s message_id=%s',
                     callback_id,
                     chat_id,
                     message_id)
        return None
    context = CallbackContext(callback_id, chat_id, message_id, payload_value, tg_user_id)
    logger.debug('Побудовано CallbackContext: callback_id=%s tg_user_id=%s', callback_id, tg_user_id)
    return context


def parse_action(payload: str) -> tuple[str, str | None]:
    """Виділяє назву дії та параметр із callback-рядка.

    :param payload: Рядок формату ``"accept|ABC-1"``.
    :returns: Пару ``(назва дії, ID задачі)``.
    """
    action, _, issue_id = payload.partition('|')
    logger.debug('Розбір дії callback: action=%s issue_id=%s', action, issue_id)
    return action, issue_id or None


async def handle_accept(issue_id: str, context: CallbackContext) -> None:
    """Призначає задачу в YouTrack та відповідає користувачу.

    :param issue_id: Читабельний ID задачі.
    :param context: Контекст callback-запиту.
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
    """Відповідає на невідому дію callback-даних."""
    await _sender().answer_callback(callback_id, text=render(Msg.ERR_CALLBACK_UNKNOWN))


async def reply_success(callback_id: str) -> None:
    """Підтверджує користувачу успішне призначення."""
    await _sender().answer_callback(callback_id, text=render(Msg.CALLBACK_ACCEPTED))


async def reply_assign_failed(callback_id: str) -> None:
    """Повідомляє про невдалу спробу призначення."""
    await _sender().answer_callback(callback_id, text=render(Msg.ERR_CALLBACK_ASSIGN_FAILED), show_alert=True)


async def reply_assign_error(callback_id: str) -> None:
    """Показує системну помилку під час прийняття."""
    await _sender().answer_callback(callback_id, text=render(Msg.ERR_CALLBACK_ASSIGN_ERROR), show_alert=True)


async def reply_authorization_required(callback_id: str) -> None:
    """Пояснює, що потрібно авторизуватись перед прийняттям задачі."""
    await _sender().answer_callback(callback_id, text=render(Msg.ERR_CALLBACK_AUTH_REQUIRED), show_alert=True)


async def reply_token_required(callback_id: str) -> None:
    """Пояснює, що необхідно оновити персональний токен."""
    await _sender().answer_callback(callback_id, text=render(Msg.ERR_CALLBACK_TOKEN_REQUIRED), show_alert=True)


async def remove_keyboard(chat_id: int, message_id: int) -> None:
    """Прибирає клавіатуру з повідомлення Telegram після успішного прийняття."""
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
    """Оновлює текст повідомлення Telegram після призначення задачі."""
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
    """Формує URL задачі для використання в повідомленні."""
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
