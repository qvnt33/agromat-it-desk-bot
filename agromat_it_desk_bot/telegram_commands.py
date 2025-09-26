"""Реалізує бізнес-логіку Telegram команд для бота."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import NamedTuple

from agromat_it_desk_bot.config import YT_BASE_URL, YT_TOKEN
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.telegram_service import call_api
from agromat_it_desk_bot.utils import as_mapping, is_login_taken, resolve_from_map, upsert_user_map_entry
from agromat_it_desk_bot.youtrack_service import lookup_user_by_login

logger: logging.Logger = logging.getLogger(__name__)


class PendingLoginChange(NamedTuple):
    """Описує запис для відкладеного оновлення логіна."""

    requested_login: str
    resolved_login: str
    email: str | None
    yt_user_id: str


pending_login_updates: dict[int, PendingLoginChange] = {}


def handle_register_command(chat_id: int, message: Mapping[str, object], text: str) -> None:
    """Обробляє команду ``/register`` та зберігає дані користувача."""
    parts: list[str] = text.split()
    if len(parts) < 2:
        _send_template(chat_id, Msg.ERR_REGISTER_FORMAT)
        return

    _, *args = parts
    login_candidate: str | None = args[0] if args else None
    if not login_candidate:
        _send_template(chat_id, Msg.ERR_REGISTER_FORMAT)
        return

    login: str = login_candidate.strip()
    if not login:
        _send_template(chat_id, Msg.ERR_REGISTER_FORMAT)
        return

    from_mapping: Mapping[str, object] | None = as_mapping(message.get('from'))
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
        pending_login_updates.pop(tg_user_id, None)
        return

    exclude_key: int | None = tg_user_id if current_login is not None else None
    if is_login_taken(details.resolved_login, exclude_tg_user_id=exclude_key):
        pending_login_updates.pop(tg_user_id, None)
        _send_template(chat_id, Msg.ERR_LOGIN_TAKEN)
        return

    if current_login and current_login.lower() != details.resolved_login.lower():
        pending_login_updates[tg_user_id] = details
        _send_template(chat_id, Msg.REGISTER_PROMPT_CONFIRM, login=details.requested_login)
        return

    pending_login_updates.pop(tg_user_id, None)
    _complete_registration(chat_id, tg_user_id, details)


def handle_confirm_login_command(chat_id: int, message: Mapping[str, object], text: str) -> None:
    """Підтверджує зміну логіна на новий."""
    parts: list[str] = text.split()
    if len(parts) < 2:
        _send_template(chat_id, Msg.ERR_CONFIRM_FORMAT)
        return

    _, *args = parts
    login_candidate: str | None = args[0] if args else None
    if not login_candidate:
        _send_template(chat_id, Msg.ERR_CONFIRM_FORMAT)
        return

    login: str = login_candidate.strip()
    if not login:
        _send_template(chat_id, Msg.ERR_CONFIRM_FORMAT)
        return

    from_mapping: Mapping[str, object] | None = as_mapping(message.get('from'))
    tg_user_obj: object | None = from_mapping.get('id') if from_mapping else None
    tg_user_id: int | None = tg_user_obj if isinstance(tg_user_obj, int) else None
    if tg_user_id is None:
        logger.warning('Не вдалося визначити відправника для команди /confirm_login: %s', message)
        _send_template(chat_id, Msg.ERR_TG_ID_UNAVAILABLE)
        return

    pending_details: PendingLoginChange | None = pending_login_updates.get(tg_user_id)
    if pending_details is None:
        _send_template(chat_id, Msg.ERR_NO_PENDING)
        return

    if pending_details.requested_login.lower() != login.lower():
        _send_template(chat_id, Msg.ERR_CONFIRM_MISMATCH, expected=pending_details.requested_login, actual=login)
        return

    current_login, _, _ = resolve_from_map(tg_user_id)
    if current_login and current_login.lower() == pending_details.resolved_login.lower():
        pending_login_updates.pop(tg_user_id, None)
        _send_template(chat_id, Msg.REGISTER_ALREADY, login=current_login, suggested=current_login)
        return

    if is_login_taken(pending_details.resolved_login, exclude_tg_user_id=tg_user_id):
        pending_login_updates.pop(tg_user_id, None)
        _send_template(chat_id, Msg.ERR_LOGIN_TAKEN)
        return

    _complete_registration(chat_id, tg_user_id, pending_details, previous_login=current_login)


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
    except ValueError as err:
        friendly_error: str = str(err) or 'Не вдалося зберегти дані.'
        _reply_text(chat_id, friendly_error)
        return False
    except FileNotFoundError as err:
        logger.exception('Не вдалося створити user_map.json: %s', err)
        _send_template(chat_id, Msg.ERR_STORAGE)
        return False
    except Exception as err:  # noqa: BLE001
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

    _reply_text(chat_id, base_text + extra_line)
    return True


def _resolve_login_details(chat_id: int, login: str) -> PendingLoginChange | None:
    """Отримує деталі облікового запису YouTrack для заданого логіна."""
    if not (YT_BASE_URL and YT_TOKEN):
        logger.error('Команда /register недоступна: не налаштовано YT_BASE_URL або YT_TOKEN')
        _send_template(chat_id, Msg.ERR_YT_NOT_CONFIGURED)
        return None

    try:
        resolved_login, email, yt_user_id = lookup_user_by_login(login)
    except AssertionError:
        logger.exception('Не налаштовано токен YouTrack для пошуку користувача')
        _send_template(chat_id, Msg.ERR_YT_TOKEN_MISSING)
        return None
    except Exception as err:  # noqa: BLE001
        logger.exception('Помилка пошуку користувача YouTrack за логіном %s: %s', login, err)
        _send_template(chat_id, Msg.ERR_YT_FETCH)
        return None

    if yt_user_id is None:
        _send_template(chat_id, Msg.ERR_YT_USER_NOT_FOUND)
        return None

    resolved: str = resolved_login or login
    return PendingLoginChange(login, resolved, email, yt_user_id)


def _reply_text(chat_id: int, text: str) -> None:
    """Надсилає просте текстове повідомлення у чат."""
    payload: dict[str, object] = {'chat_id': chat_id, 'text': text, 'disable_web_page_preview': True}
    call_api('sendMessage', payload)


def _send_template(chat_id: int, msg: Msg, **params: object) -> None:
    """Надсилає повідомлення за ключем локалізованого шаблону."""
    text: str = render(msg, locale='uk', **params)
    _reply_text(chat_id, text)
