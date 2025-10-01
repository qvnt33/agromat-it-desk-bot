"""Реалізує бізнес-логіку Telegram команд для бота."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import NamedTuple

from agromat_it_desk_bot.config import YT_BASE_URL, YT_TOKEN
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.telegram.telegram_service import call_api
from agromat_it_desk_bot.utils import is_login_taken, resolve_from_map, upsert_user_map_entry
from agromat_it_desk_bot.youtrack.youtrack_service import lookup_user_by_login

logger: logging.Logger = logging.getLogger(__name__)


class PendingLoginChange(NamedTuple):
    """Описує запис для відкладеного оновлення логіна."""

    requested_login: str
    resolved_login: str
    email: str | None
    yt_user_id: str


# Поточні незавершені зміни логіна за Telegram ID
pending_login_updates: dict[int, PendingLoginChange] = {}

__all__ = [
    'PendingLoginChange',
    'pending_login_updates',
    'handle_register_command',
    'handle_confirm_login_command',
    'send_help',
    'call_api',
]


def handle_register_command(chat_id: int, message: Mapping[str, object], text: str) -> None:
    """Обробляє команду ``/register`` та зберігає дані користувача."""
    logger.debug('Отримано /register: chat_id=%s text=%s', chat_id, text)
    # Слова з повідомлення користувача
    parts: list[str] = text.split()
    if len(parts) < 2:
        _send_template(chat_id, Msg.ERR_REGISTER_FORMAT)
        return

    _, *args = parts
    # Потенційний логін з команди
    login_candidate: str | None = args[0] if args else None
    if not login_candidate:
        _send_template(chat_id, Msg.ERR_REGISTER_FORMAT)
        return

    # Очищений логін для реєстрації
    login: str = login_candidate.strip()
    if not login:
        _send_template(chat_id, Msg.ERR_REGISTER_FORMAT)
        return

    from_obj: object | None = message.get('from') or message.get('from_user')
    from_mapping: Mapping[str, object] | None = from_obj if isinstance(from_obj, dict) else None
    # Беруть ідентифікатор користувача з метаданих повідомлення
    tg_user_obj: object | None = from_mapping.get('id') if from_mapping else None
    tg_user_id: int | None = tg_user_obj if isinstance(tg_user_obj, int) else None
    if tg_user_id is None:
        logger.warning('Не вдалося визначити відправника для команди /register: %s', message)
        _send_template(chat_id, Msg.ERR_TG_ID_UNAVAILABLE)
        return

    current_login, _, _ = resolve_from_map(tg_user_id)
    if current_login and current_login.lower() == login.lower():
        pending_login_updates.pop(tg_user_id, None)
        _send_template(chat_id, Msg.REGISTER_ALREADY, login=current_login, suggested=current_login)
        return

    details: PendingLoginChange | None = _resolve_login_details(chat_id, login)
    if details is None:
        # Очищають буфер, якщо дані не отримано
        pending_login_updates.pop(tg_user_id, None)
        logger.debug('Не вдалося отримати дані YouTrack: tg_user_id=%s login=%s', tg_user_id, login)
        return

    # Ідентифікатор для виключення з пошуку дублікатів
    exclude_key: int | None = tg_user_id if current_login is not None else None
    if is_login_taken(details.resolved_login, exclude_tg_user_id=exclude_key):
        pending_login_updates.pop(tg_user_id, None)
        _send_template(chat_id, Msg.ERR_LOGIN_TAKEN)
        logger.debug('Логін зайнятий під час /register: login=%s', details.resolved_login)
        return

    if current_login and current_login.lower() != details.resolved_login.lower():
        # Зберігають зміну для підтвердження користувачем
        pending_login_updates[tg_user_id] = details
        logger.debug('Очікування підтвердження логіна: tg_user_id=%s requested=%s resolved=%s',
                     tg_user_id,
                     details.requested_login,
                     details.resolved_login)
        _send_template(chat_id, Msg.REGISTER_PROMPT_CONFIRM, login=details.requested_login)
        return

    pending_login_updates.pop(tg_user_id, None)
    logger.debug('Негайна реєстрація без підтвердження: tg_user_id=%s resolved_login=%s',
                 tg_user_id,
                 details.resolved_login)
    _complete_registration(chat_id, tg_user_id, details)


def handle_confirm_login_command(chat_id: int, message: Mapping[str, object], text: str) -> None:
    """Підтверджує зміну логіна на новий."""
    logger.debug('Отримано /confirm_login: chat_id=%s text=%s', chat_id, text)
    # Аргументи команди /confirm_login
    parts: list[str] = text.split()
    if len(parts) < 2:
        _send_template(chat_id, Msg.ERR_CONFIRM_FORMAT)
        return

    _, *args = parts
    # Логін, який підтверджують
    login_candidate: str | None = args[0] if args else None
    if not login_candidate:
        _send_template(chat_id, Msg.ERR_CONFIRM_FORMAT)
        return

    login: str = login_candidate.strip()
    if not login:
        _send_template(chat_id, Msg.ERR_CONFIRM_FORMAT)
        return

    from_obj: object | None = message.get('from') or message.get('from_user')
    from_mapping: Mapping[str, object] | None = from_obj if isinstance(from_obj, dict) else None
    # Захищаються від підміни чату під час підтвердження
    tg_user_obj: object | None = from_mapping.get('id') if from_mapping else None
    tg_user_id: int | None = tg_user_obj if isinstance(tg_user_obj, int) else None
    if tg_user_id is None:
        logger.warning('Не вдалося визначити відправника для команди /confirm_login: %s', message)
        _send_template(chat_id, Msg.ERR_TG_ID_UNAVAILABLE)
        return

    pending_details: PendingLoginChange | None = pending_login_updates.get(tg_user_id)
    if pending_details is None:
        _send_template(chat_id, Msg.ERR_NO_PENDING)
        logger.debug('Відсутній запит на підтвердження: tg_user_id=%s', tg_user_id)
        return

    if pending_details.requested_login.lower() != login.lower():
        # Повідомляють про спробу підтвердити інший логін
        _send_template(chat_id, Msg.ERR_CONFIRM_MISMATCH, expected=pending_details.requested_login, actual=login)
        logger.debug('Невідповідність логіна при підтвердженні: tg_user_id=%s expected=%s actual=%s',
                     tg_user_id,
                     pending_details.requested_login,
                     login)
        return

    current_login, _, _ = resolve_from_map(tg_user_id)
    if current_login and current_login.lower() == pending_details.resolved_login.lower():
        pending_login_updates.pop(tg_user_id, None)
        _send_template(chat_id, Msg.REGISTER_ALREADY, login=current_login, suggested=current_login)
        return

    if is_login_taken(pending_details.resolved_login, exclude_tg_user_id=tg_user_id):
        pending_login_updates.pop(tg_user_id, None)
        _send_template(chat_id, Msg.ERR_LOGIN_TAKEN)
        logger.debug('Логін зайнятий під час підтвердження: login=%s', pending_details.resolved_login)
        return

    _complete_registration(chat_id, tg_user_id, pending_details, previous_login=current_login)
    logger.debug('Підтверджено зміну логіна: tg_user_id=%s new_login=%s',
                 tg_user_id,
                 pending_details.resolved_login)


def send_help(chat_id: int) -> None:
    """Надсилає інформаційне повідомлення з інструкцією /register."""
    _send_template(chat_id, Msg.HELP_REGISTER)


def _complete_registration(
    chat_id: int,
    tg_user_id: int,
    details: PendingLoginChange,
    *,
    previous_login: str | None = None,
) -> bool:
    """Завершує реєстрацію користувача з підготовленими даними."""
    try:
        upsert_user_map_entry(
            tg_user_id,
            login=details.resolved_login,
            email=details.email,
            yt_user_id=details.yt_user_id,
        )
        logger.debug('Оновлення user_map успішне: tg_user_id=%s login=%s', tg_user_id, details.resolved_login)
    except ValueError as err:
        friendly_error: str = str(err) or render(Msg.ERR_STORAGE_GENERIC)
        _reply_text(chat_id, friendly_error)
        logger.error('Помилка валідації user_map: tg_user_id=%s err=%s', tg_user_id, err)
        return False
    except FileNotFoundError as err:
        # Сховище користувачів недоступне, фіксують помилку для DevOps
        logger.exception('Не вдалося створити user_map.json: %s', err)
        _send_template(chat_id, Msg.ERR_STORAGE)
        return False
    except Exception as err:  # noqa: BLE001
        # Логують причину, щоб не втратити інформацію про часткову невдачу
        logger.exception('Помилка при оновленні user_map для %s: %s', tg_user_id, err)
        _send_template(chat_id, Msg.ERR_UNKNOWN)
        return False

    pending_login_updates.pop(tg_user_id, None)
    logger.info(
        'Користувач %s зареєструвався: login=%s email=%s yt_id=%s',
        tg_user_id,
        details.resolved_login,
        details.email,
        details.yt_user_id,
    )

    base_text: str = render(
        Msg.REGISTER_SAVED,
        login=details.resolved_login,
        email=details.email or '-',
        yt_id=details.yt_user_id,
    )
    extra_line: str = ''
    if previous_login and previous_login.lower() != details.resolved_login.lower():
        extra_line = '\n' + render(Msg.REGISTER_UPDATED_NOTE, previous=previous_login, current=details.resolved_login)
        logger.debug('Повідомлення про зміну логіна: tg_user_id=%s previous=%s new=%s',
                     tg_user_id,
                     previous_login,
                     details.resolved_login)

    _reply_text(chat_id, base_text + extra_line)
    logger.info('Завершено реєстрацію користувача: tg_user_id=%s login=%s', tg_user_id, details.resolved_login)
    return True


def _resolve_login_details(chat_id: int, login: str) -> PendingLoginChange | None:
    """Отримує деталі облікового запису YouTrack для заданого логіна."""
    if not (YT_BASE_URL and YT_TOKEN):
        # Неможливо звернутися до YouTrack без базових параметрів
        logger.error('Команда /register недоступна: не налаштовано YT_BASE_URL або YT_TOKEN')
        _send_template(chat_id, Msg.ERR_YT_NOT_CONFIGURED)
        return None

    try:
        resolved_login, email, yt_user_id = lookup_user_by_login(login)
        logger.debug('Запит YouTrack користувача: login=%s', login)
    except AssertionError:
        # Бібліотека YouTrack сигналізує про відсутність токена
        logger.exception('Не налаштовано токен YouTrack для пошуку користувача')
        _send_template(chat_id, Msg.ERR_YT_TOKEN_MISSING)
        return None
    except Exception as err:  # noqa: BLE001
        # Обробляють несподівані помилки мережі або API
        logger.exception('Помилка пошуку користувача YouTrack за логіном %s: %s', login, err)
        _send_template(chat_id, Msg.ERR_YT_FETCH)
        return None

    if yt_user_id is None:
        # Повідомляють, що користувача з таким логіном не існує
        _send_template(chat_id, Msg.ERR_YT_USER_NOT_FOUND)
        logger.debug('YouTrack не знайшов користувача: login=%s', login)
        return None

    resolved: str = resolved_login or login
    logger.debug('YouTrack користувач знайдений: login=%s resolved=%s', login, resolved)
    return PendingLoginChange(login, resolved, email, yt_user_id)


def _reply_text(chat_id: int, text: str) -> None:
    """Надсилає просте текстове повідомлення у чат."""
    # Параметри звичайного повідомлення без форматування
    payload: dict[str, object] = {'chat_id': chat_id, 'text': text, 'disable_web_page_preview': True}
    call_api('sendMessage', payload)


def _send_template(chat_id: int, msg: Msg, **params: object) -> None:
    """Надсилає повідомлення за ключем локалізованого шаблону."""
    # Рендерять шаблон локалізації та використовують загальну утиліту відправлення
    text: str = render(msg, locale='uk', **params)
    _reply_text(chat_id, text)
