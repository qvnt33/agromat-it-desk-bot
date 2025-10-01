"""Надає хелпери для обробки Telegram callback'ів (кнопка "Прийняти")."""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from fastapi import HTTPException, Request

from agromat_it_desk_bot.config import ALLOWED_TG_USER_IDS, TELEGRAM_WEBHOOK_SECRET
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.telegram.telegram_service import call_api
from agromat_it_desk_bot.youtrack.youtrack_service import assign_issue, resolve_account

logger: logging.Logger = logging.getLogger(__name__)


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


def is_user_allowed(tg_user_id: int | None) -> bool:
    """Перевіряє, чи має користувач право натискати кнопку "Прийняти".

    :param tg_user_id: Telegram ID користувача.
    :returns: ``True`` якщо користувач дозволений або whitelist порожній.
    """
    if tg_user_id is None:
        return False

    if not ALLOWED_TG_USER_IDS:
        login, email, yt_user_id = resolve_account(tg_user_id)
        allowed: bool = any((login, email, yt_user_id))
        logger.debug('Перевірка доступу без whitelist: tg_user_id=%s allowed=%s', tg_user_id, allowed)
        return allowed

    if tg_user_id in ALLOWED_TG_USER_IDS:
        logger.debug('Користувач у whitelist: tg_user_id=%s', tg_user_id)
        return True

    login, email, yt_user_id = resolve_account(tg_user_id)
    allowed = any((login, email, yt_user_id))
    logger.debug('Перевірка доступу через map: tg_user_id=%s allowed=%s', tg_user_id, allowed)
    return allowed


def parse_action(payload: str) -> tuple[str, str | None]:
    """Виділяє назву дії та параметр із callback-рядка.

    :param payload: Рядок формату ``"accept|ABC-1"``.
    :returns: Пару ``(назва дії, ID задачі)``.
    """
    action, _, issue_id = payload.partition('|')
    logger.debug('Розбір дії callback: action=%s issue_id=%s', action, issue_id)
    return action, issue_id or None


def handle_accept(issue_id: str, context: CallbackContext) -> None:
    """Призначає задачу в YouTrack та відповідає користувачу.

    :param issue_id: Читабельний ID задачі.
    :param context: Контекст callback-запиту.
    """
    login: str | None
    email: str | None
    yt_user_id: str | None
    try:
        login, email, yt_user_id = resolve_account(context.tg_user_id)
        if not any((login, email, yt_user_id)):
            raise RuntimeError('Не знайдено мапінг користувача')
    except Exception as exc:  # noqa: BLE001
        logger.exception('Не вдалося знайти користувача для прийняття: %s', exc)
        reply_assign_error(context.callback_id)
        return

    assigned: bool = assign_issue(issue_id, login, email, yt_user_id)
    if not assigned:
        reply_assign_failed(context.callback_id)
        logger.warning('Не вдалося призначити задачу через callback: issue_id=%s', issue_id)
        return

    reply_success(context.callback_id)
    remove_keyboard(context.chat_id, context.message_id)
    logger.info('Задачу призначено через callback: issue_id=%s tg_user_id=%s', issue_id, context.tg_user_id)


def reply_insufficient_rights(callback_id: str) -> None:
    """Повідомляє про відсутність прав у користувача."""
    payload: dict[str, object] = {
        'callback_query_id': callback_id,
        'text': render(Msg.ERR_CALLBACK_RIGHTS),
        'show_alert': True,
    }
    call_api('answerCallbackQuery', payload)


def reply_unknown_action(callback_id: str) -> None:
    """Відповідає на невідому дію callback-даних."""
    call_api(
        'answerCallbackQuery',
        {'callback_query_id': callback_id, 'text': render(Msg.ERR_CALLBACK_UNKNOWN)},
    )


def reply_success(callback_id: str) -> None:
    """Підтверджує користувачу успішне призначення."""
    call_api(
        'answerCallbackQuery',
        {'callback_query_id': callback_id, 'text': render(Msg.CALLBACK_ACCEPTED)},
    )


def reply_assign_failed(callback_id: str) -> None:
    """Повідомляє про невдалу спробу призначення."""
    payload: dict[str, object] = {
        'callback_query_id': callback_id,
        'text': render(Msg.ERR_CALLBACK_ASSIGN_FAILED),
        'show_alert': True,
    }
    call_api('answerCallbackQuery', payload)


def reply_assign_error(callback_id: str) -> None:
    """Показує системну помилку під час прийняття."""
    payload: dict[str, object] = {
        'callback_query_id': callback_id,
        'text': render(Msg.ERR_CALLBACK_ASSIGN_ERROR),
        'show_alert': True,
    }
    call_api('answerCallbackQuery', payload)


def remove_keyboard(chat_id: int, message_id: int) -> None:
    """Прибирає клавіатуру з повідомлення Telegram після успішного прийняття."""
    call_api('editMessageReplyMarkup', {'chat_id': chat_id, 'message_id': message_id, 'reply_markup': {}})
