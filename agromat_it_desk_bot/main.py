"""FastAPI застосунок для обробки вебхуків YouTrack та Telegram."""

from __future__ import annotations

if __name__ == '__main__' and __package__ is None:  # pragma: no cover - CLI запуск
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import logging
from collections.abc import Mapping
from typing import Any, cast

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
from agromat_it_desk_bot.config import (
    YT_BASE_URL,
    YT_WEBHOOK_SECRET,
)
from agromat_it_desk_bot.telegram_service import send_message
from agromat_it_desk_bot.utils import configure_logging, extract_issue_id, format_message, get_str

configure_logging()
logger: logging.Logger = logging.getLogger(__name__)

app = FastAPI()


@app.post('/youtrack')
async def youtrack_webhook(request: Request) -> dict[str, bool]:
    """Обробити вебхук від YouTrack та повідомити Telegram.

    Обробити JSON-пейлоад із даними задачі, сформувати текст повідомлення та
    відправити його до Telegram. Якщо відомий ID задачі, додати кнопку
    «Прийняти» для швидкої реакції інженера підтримки.

    :param request: Запит FastAPI з тілом вебхука.
    :type request: Request
    :returns: Словник ``{"ok": True}`` у разі успішного виконання.
    :rtype: dict[str, bool]
    :raises HTTPException: 400 при некоректному пейлоаді; 403 при невірному секреті.
    """
    # YouTrack надсилає JSON-тіло з даними задачі
    payload: Any = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Invalid payload shape')

    # Гарантувати тип словника для подальшої роботи
    data: dict[str, object] = cast(dict[str, object], payload)

    # Додатково перевірити секрет вебхука, якщо він увімкнений
    if YT_WEBHOOK_SECRET is not None:
        auth_header: str | None = request.headers.get('Authorization')
        expected: str = f'Bearer {YT_WEBHOOK_SECRET}'
        if auth_header != expected:
            logger.warning('Невірний секрет YouTrack вебхука')
            raise HTTPException(status_code=403, detail='Forbidden')

    logger.debug('Отримано вебхук YouTrack: %s', data)

    # Дістати поле ``issue``, якщо YouTrack огортає дані в нього
    issue_candidate: object | None = data.get('issue')
    issue: Mapping[str, object] = cast(
        dict[str, object], issue_candidate,
    ) if isinstance(issue_candidate, dict) else data

    # Зібрати ключові атрибути для повідомлення
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
        reply_markup = {
            'inline_keyboard': [[{'text': 'Прийняти', 'callback_data': f'accept|{issue_id}'}]],
        }

    logger.info('Підготовано повідомлення для задачі %s', issue_id or '(без ID)')
    await run_in_threadpool(send_message, message, reply_markup)
    return {'ok': True}


@app.post('/telegram')
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Обробити callback від Telegram та призначити задачу у YouTrack.

    Перевірити секрет вебхука, розібрати callback із кнопки «Прийняти»,
    призначити задачу користувачу (й оновити стан) та відповісти в Telegram.

    :param request: Запит FastAPI з callback-даними.
    :type request: Request
    :returns: Словник ``{"ok": True}`` незалежно від результату обробки.
    :rtype: dict[str, bool]
    :raises HTTPException: 403, якщо секрет Telegram не збігається.
    """
    logger.info('Отримано вебхук Telegram')

    verify_telegram_secret(request)

    # Telegram надсилає JSON з callback-структурою
    payload: Any = await request.json()
    if not isinstance(payload, dict):
        logger.warning('Отримано некоректний payload від Telegram: %r', payload)
        return {'ok': True}

    # Спробувати побудувати структурований контекст callback
    context: CallbackContext | None = parse_callback_payload(payload)
    if context is None:
        logger.debug('Не вдалося розібрати callback_payload: %s', payload)
        return {'ok': True}

    # Пустити далі лише дозволених користувачів (якщо список заданий)
    if not is_user_allowed(context.tg_user_id):
        logger.warning('Користувач %s не має прав для прийняття задачі', context.tg_user_id)
        reply_insufficient_rights(context.callback_id)
        return {'ok': True}

    # Payload має формат ``accept|ABC-1`` — отримання дії та ID
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
    """Проксувати запит на основний обробник ``/telegram`` (запасний маршрут)."""
    return await telegram_webhook(request)


def main() -> None:
    """Запустити Uvicorn сервер для FastAPI застосунку."""
    uvicorn.run(app, host='0.0.0.0', port=8080)


if __name__ == '__main__':
    main()
