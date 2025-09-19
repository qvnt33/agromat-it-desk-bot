"""Хелпери для обробки Telegram callback'ів (кнопка «Прийняти»)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, NamedTuple

from fastapi import HTTPException, Request

from agromat_it_desk_bot.config import (
    ALLOWED_TG_USER_IDS,
    TELEGRAM_WEBHOOK_SECRET,
    YOUTRACK_STATE_IN_PROGRESS,
)
from agromat_it_desk_bot.telegram_service import call_api
from agromat_it_desk_bot.utils import as_mapping
from agromat_it_desk_bot.youtrack_service import assign_issue, resolve_account, set_state

logger: logging.Logger = logging.getLogger(__name__)


class CallbackContext(NamedTuple):
    """Структурований набір параметрів із callback-повідомлення Telegram."""

    callback_id: str
    chat_id: int
    message_id: int
    payload: str
    tg_user_id: int | None


def verify_telegram_secret(request: Request) -> None:
    """Перевірити секрет вебхука Telegram перед обробкою callback.

    :param request: Запит FastAPI із заголовками Telegram.
    :type request: Request
    :raises HTTPException: 403, якщо секрет не збігається.
    """
    if TELEGRAM_WEBHOOK_SECRET:
        secret: str | None = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if secret != TELEGRAM_WEBHOOK_SECRET:
            logger.warning('Невірний секрет Telegram вебхука')
            raise HTTPException(status_code=403, detail='Forbidden')


def parse_callback_payload(payload: Any) -> CallbackContext | None:
    """Розібрати callback-пейлоад та побудувати контекст.

    :param payload: Сирий JSON із даними Telegram.
    :type payload: Any
    :returns: ``CallbackContext`` або ``None``.
    :rtype: CallbackContext | None
    """
    callback: Mapping[str, object] | None = as_mapping(payload.get('callback_query'))
    if callback is None:
        return None

    callback_id_obj: object | None = callback.get('id')
    callback_id: str | None = str(callback_id_obj) if isinstance(callback_id_obj, (str, int)) else None

    from_user_mapping: Mapping[str, object] | None = as_mapping(callback.get('from'))
    tg_user_id: int | None = None
    if from_user_mapping is not None:
        tg_user_id_obj: object | None = from_user_mapping.get('id')
        if isinstance(tg_user_id_obj, int):
            tg_user_id = tg_user_id_obj

    chat_id: int | None = None
    message_id: int | None = None
    message_mapping: Mapping[str, object] | None = as_mapping(callback.get('message'))
    if message_mapping is not None:
        chat_mapping: Mapping[str, object] | None = as_mapping(message_mapping.get('chat'))
        if chat_mapping is not None:
            chat_id_obj: object | None = chat_mapping.get('id')
            if isinstance(chat_id_obj, int):
                chat_id = chat_id_obj

        message_id_obj: object | None = message_mapping.get('message_id')
        if isinstance(message_id_obj, int):
            message_id = message_id_obj

    payload_raw: object | None = callback.get('data')
    payload_value: str = str(payload_raw) if isinstance(payload_raw, (str, int)) else ''

    if not (callback_id and chat_id and message_id):
        return None

    return CallbackContext(callback_id, chat_id, message_id, payload_value, tg_user_id)


def is_user_allowed(tg_user_id: int | None) -> bool:
    """Перевірити, чи має користувач право натискати кнопку «Прийняти».

    :param tg_user_id: Telegram ID користувача.
    :type tg_user_id: int | None
    :returns: ``True`` якщо користувач дозволений або whitelist порожній.
    :rtype: bool
    """
    if tg_user_id is None:
        return False

    if not ALLOWED_TG_USER_IDS:
        login, email, yt_user_id = resolve_account(tg_user_id)
        return any((login, email, yt_user_id))

    if tg_user_id in ALLOWED_TG_USER_IDS:
        return True

    login, email, yt_user_id = resolve_account(tg_user_id)
    return any((login, email, yt_user_id))


def parse_action(payload: str) -> tuple[str, str | None]:
    """Виділити назву дії та параметр із callback-рядка.

    :param payload: Рядок формату ``"accept|ABC-1"``.
    :type payload: str
    :returns: Пару ``(назва дії, ID задачі)``.
    :rtype: tuple[str, str | None]
    """
    action, _, issue_id = payload.partition('|')
    return action, issue_id or None


def handle_accept(issue_id: str, context: CallbackContext) -> None:
    """Призначити задачу в YouTrack та відповісти користувачу.

    :param issue_id: Читабельний ID задачі.
    :type issue_id: str
    :param context: Контекст callback-запиту.
    :type context: CallbackContext
    """
    try:
        login: str | None
        email: str | None
        yt_user_id: str | None
        login, email, yt_user_id = resolve_account(context.tg_user_id)
        if not any((login, email, yt_user_id)):
            raise RuntimeError('Не знайдено мапінг користувача')

        assigned: bool = assign_issue(issue_id, login, email, yt_user_id)
        if assigned:
            if YOUTRACK_STATE_IN_PROGRESS:
                set_state(issue_id, YOUTRACK_STATE_IN_PROGRESS)

            reply_success(context.callback_id)
            remove_keyboard(context.chat_id, context.message_id)
        else:
            reply_assign_failed(context.callback_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception('Не вдалося обробити прийняття: %s', exc)
        reply_assign_error(context.callback_id)


def reply_insufficient_rights(callback_id: str) -> None:
    """Повідомити про відсутність прав у користувача."""
    call_api(
        'answerCallbackQuery',
        {
            'callback_query_id': callback_id,
            'text': 'Недостатньо прав',
            'show_alert': True,
        },
    )


def reply_unknown_action(callback_id: str) -> None:
    """Відповісти на невідому дію callback-даних."""
    call_api(
        'answerCallbackQuery',
        {
            'callback_query_id': callback_id,
            'text': 'Невідома дія',
        },
    )


def reply_success(callback_id: str) -> None:
    """Підтвердити користувачу успішне призначення."""
    call_api(
        'answerCallbackQuery',
        {
            'callback_query_id': callback_id,
            'text': 'Прийнято ✅',
        },
    )


def reply_assign_failed(callback_id: str) -> None:
    """Повідомити про невдалу спробу призначення."""
    call_api(
        'answerCallbackQuery',
        {
            'callback_query_id': callback_id,
            'text': 'Не вдалося призначити',
            'show_alert': True,
        },
    )


def reply_assign_error(callback_id: str) -> None:
    """Показати системну помилку під час прийняття."""
    call_api(
        'answerCallbackQuery',
        {
            'callback_query_id': callback_id,
            'text': 'Помилка: не вдалось прийняти',
            'show_alert': True,
        },
    )


def remove_keyboard(chat_id: int, message_id: int) -> None:
    """Прибрати клавіатуру з повідомлення Telegram після успішного прийняття."""
    call_api(
        'editMessageReplyMarkup',
        {
            'chat_id': chat_id,
            'message_id': message_id,
            'reply_markup': {},
        },
    )
