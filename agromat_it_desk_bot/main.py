"""Забезпечує FastAPI застосунок для обробки вебхуків YouTrack та Telegram."""

from __future__ import annotations

if __name__ == '__main__' and __package__ is None:  # pragma: no cover - CLI запуск
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import logging
from collections.abc import Mapping
from typing import Any, NamedTuple, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from agromat_it_desk_bot.callback_handlers import (
    CallbackContext,
    handle_accept,
    is_user_allowed,
    parse_action,
    parse_callback_payload,
    reply_insufficient_rights,
    reply_unknown_action,
    verify_telegram_secret,
)
from agromat_it_desk_bot.config import YT_BASE_URL, YT_TOKEN, YT_WEBHOOK_SECRET
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.telegram_service import call_api, send_message
from agromat_it_desk_bot.utils import (
    as_mapping,
    configure_logging,
    extract_issue_id,
    format_message,
    get_str,
    is_login_taken,
    resolve_from_map,
    upsert_user_map_entry,
)
from agromat_it_desk_bot.youtrack_service import lookup_user_by_login

configure_logging()
logger: logging.Logger = logging.getLogger(__name__)

app = FastAPI()


class PendingLoginChange(NamedTuple):
    """Описує запис для відкладеного оновлення логіна."""

    requested_login: str
    resolved_login: str
    email: str | None
    yt_user_id: str


pending_login_updates: dict[int, PendingLoginChange] = {}


@app.post('/youtrack')
async def youtrack_webhook(request: Request) -> dict[str, bool]:
    """Обробляє вебхук від YouTrack та повідомляє Telegram.

    Обробляє JSON-пейлоад із даними задачі, формує текст повідомлення та
    відправляє його до Telegram. Якщо відомий ID задачі, додає кнопку
    «Прийняти» для швидкої реакції інженера підтримки.

    :param request: Запит FastAPI з тілом вебхука.
    :returns: Словник ``{"ok": True}`` у разі успішного виконання.
    :raises HTTPException: 400 при некоректному пейлоаді; 403 при невірному секреті.
    """
    # Обробляють JSON тіло з даними задачі від YouTrack
    payload: Any = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Invalid payload shape')

    # Забезпечують тип словника для подальшої роботи
    data: dict[str, object] = cast(dict[str, object], payload)

    # Перевіряють секрет вебхука, якщо він увімкнений
    if YT_WEBHOOK_SECRET is not None:
        auth_header: str | None = request.headers.get('Authorization')
        expected: str = f'Bearer {YT_WEBHOOK_SECRET}'
        if auth_header != expected:
            logger.warning('Невірний секрет YouTrack вебхука')
            raise HTTPException(status_code=403, detail='Forbidden')

    logger.debug('Отримано вебхук YouTrack: %s', data)

    # Виділяють поле ``issue``, якщо YouTrack огортає дані в нього
    issue_candidate: object | None = data.get('issue')
    issue: Mapping[str, object] = (
        cast(dict[str, object], issue_candidate) if isinstance(issue_candidate, dict) else data
    )

    # Збирають ключові атрибути для повідомлення
    issue_id: str = extract_issue_id(issue)
    summary: str = get_str(issue, 'summary')
    description: str = get_str(issue, 'description')

    url_val: str | None = None
    url_field: object | None = issue.get('url')
    if isinstance(url_field, str) and url_field:
        url_val = url_field
    elif issue_id and issue_id != '(без ID)' and YT_BASE_URL:
        url_val = f'{YT_BASE_URL}/issue/{issue_id}'

    message: str = format_message(issue_id, summary, description, url_val)

    reply_markup: dict[str, object] | None = None
    if issue_id and issue_id != '(без ID)':
        reply_markup = {'inline_keyboard': [[{'text': 'Прийняти', 'callback_data': f'accept|{issue_id}'}]]}

    logger.info('Підготовано повідомлення для задачі %s', issue_id or '(без ID)')
    await run_in_threadpool(send_message, message, reply_markup)
    return {'ok': True}


@app.post('/telegram')
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Обробляє callback від Telegram та призначає задачу у YouTrack.

    Перевіряє секрет вебхука, розбирає callback із кнопки «Прийняти»,
    призначає задачу користувачу (й оновлює стан) та відповідає в Telegram.

    :param request: Запит FastAPI з callback-даними.
    :returns: Словник ``{"ok": True}`` незалежно від результату обробки.
    :raises HTTPException: 403, якщо секрет Telegram не збігається.
    """
    logger.info('Отримано вебхук Telegram')

    verify_telegram_secret(request)

    # Обробляють JSON із даними оновлення від Telegram
    payload: Any = await request.json()
    if not isinstance(payload, dict):
        logger.warning('Отримано некоректний payload від Telegram: %r', payload)
        return {'ok': True}

    message_mapping: Mapping[str, object] | None = as_mapping(payload.get('message'))
    if message_mapping is not None:
        logger.debug('Отримано текстове повідомлення від Telegram')
        _handle_message_update(message_mapping)
        return {'ok': True}

    # Намагаються побудувати структурований контекст callback
    context: CallbackContext | None = parse_callback_payload(payload)
    if context is None:
        logger.debug('Не вдалося розібрати callback_payload: %s', payload)
        return {'ok': True}

    # Пропускають далі лише дозволених користувачів (якщо список заданий)
    if not is_user_allowed(context.tg_user_id):
        logger.warning('Користувач %s не має прав для прийняття задачі', context.tg_user_id)
        reply_insufficient_rights(context.callback_id)
        return {'ok': True}

    # Розбирають payload формату ``accept|ABC-1`` для отримання дії та ID
    action, issue_id = parse_action(context.payload)
    if action != 'accept' or not issue_id:
        logger.warning('Отримано невідому дію: action=%s payload=%s', action, context.payload)
        reply_unknown_action(context.callback_id)
        return {'ok': True}

    logger.info('Натиснуто кнопку "Прийняти" для задачі %s користувачем %s', issue_id, context.tg_user_id)

    handle_accept(issue_id, context)

    return {'ok': True}


@app.post('/telegram/webhook')
async def telegram_webhook_alias(request: Request) -> dict[str, bool]:
    """Переадресовує запит на основний обробник ``/telegram`` (запасний маршрут)."""
    return await telegram_webhook(request)


def _handle_message_update(message: Mapping[str, object]) -> None:
    """Обробляє звичайне повідомлення Telegram (команди користувачів)."""
    chat_mapping: Mapping[str, object] | None = as_mapping(message.get('chat'))
    chat_id_obj: object | None = chat_mapping.get('id') if chat_mapping else None
    chat_id: int | None = chat_id_obj if isinstance(chat_id_obj, int) else None
    chat_type: str | None = None
    if chat_mapping is not None:
        chat_type_obj: object | None = chat_mapping.get('type')
        chat_type = chat_type_obj if isinstance(chat_type_obj, str) else None

    if chat_id is None:
        logger.debug('Не вдалося визначити chat_id для повідомлення: %s', message)
        return

    if chat_type and chat_type != 'private':
        logger.debug('Команда /register проігнорована у чаті типу %s (chat_id=%s)', chat_type, chat_id)
        return

    text_obj: object | None = message.get('text')
    text: str | None = text_obj if isinstance(text_obj, str) else None
    if not text:
        return

    normalized_text: str = text.strip()
    if normalized_text.startswith('/register'):
        handle_register_command(chat_id, message, normalized_text)
    elif normalized_text.startswith('/confirm_login'):
        handle_confirm_login_command(chat_id, message, normalized_text)
    elif normalized_text in {'/start', '/help'}:
        _send_template(chat_id, Msg.HELP_REGISTER)


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
        extra_line = '\n' + render(
            Msg.REGISTER_UPDATED_NOTE,
            previous=previous_login,
            current=details.resolved_login,
        )

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
    call_api('sendMessage', {'chat_id': chat_id, 'text': text, 'disable_web_page_preview': True})


def _send_template(chat_id: int, msg: Msg, **params: object) -> None:
    """Надсилає повідомлення за ключем локалізованого шаблону."""
    text: str = render(msg, locale='uk', **params)
    _reply_text(chat_id, text)


def main() -> None:
    """Запускає Uvicorn сервер для FastAPI застосунку."""
    uvicorn.run(app, host='0.0.0.0', port=8080)


if __name__ == '__main__':
    main()
