"""Забезпечує FastAPI застосунок для обробки вебхуків YouTrack та Telegram."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

import agromat_it_desk_bot.telegram_aiogram as telegram_aiogram
import agromat_it_desk_bot.telegram_commands as telegram_commands
from agromat_it_desk_bot.callback_handlers import verify_telegram_secret
from agromat_it_desk_bot.config import YT_BASE_URL, YT_WEBHOOK_SECRET
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.telegram_service import send_message
from agromat_it_desk_bot.utils import (
    configure_logging,
    extract_issue_id,
    format_telegram_message,
    get_str,
)

configure_logging()
logger: logging.Logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Керує запуском та завершенням FastAPI застосунку.

    :param _app: Поточний екземпляр FastAPI.
    :yields: ``None`` протягом роботи застосунку.
    """
    try:
        yield
    finally:
        # Закривають HTTP-сесію бота Aiogram при виході
        await telegram_aiogram.shutdown()


app = FastAPI(lifespan=_lifespan)

# Перехідні псевдоніми для збереження сумісності тестів/імпортів
PendingLoginChange = telegram_commands.PendingLoginChange
pending_login_updates = telegram_commands.pending_login_updates
handle_register_command = telegram_commands.handle_register_command
handle_confirm_login_command = telegram_commands.handle_confirm_login_command
send_help = telegram_commands.send_help


@app.post('/youtrack')
async def youtrack_webhook(request: Request) -> dict[str, bool]:
    """Обробляє вебхук від YouTrack та повідомляє Telegram.

    :param request: Запит FastAPI з тілом вебхука.
    :returns: Словник ``{"ok": True}`` у разі успішного виконання.
    :raises HTTPException: 400 при некоректному пейлоаді; 403 при невірному секреті.
    """
    payload: Any = await request.json()

    if not isinstance(payload, dict):
        # Перевірка формату JSON
        raise HTTPException(status_code=400, detail=render(Msg.HTTP_INVALID_PAYLOAD))

    if YT_WEBHOOK_SECRET is not None:
        auth_header: str | None = request.headers.get('Authorization')
        expected: str = f'Bearer {YT_WEBHOOK_SECRET}'

        if auth_header != expected:
            # Контроль секрету YouTrack
            logger.warning('Невірний секрет YouTrack вебхука')
            raise HTTPException(status_code=403, detail=render(Msg.HTTP_FORBIDDEN))

    logger.debug('Отримано вебхук YouTrack: %s', payload)

    # Дані задачі вебхука
    issue_candidate: object | None = payload.get('issue')
    issue: Mapping[str, object] = issue_candidate if isinstance(issue_candidate, dict) else payload

    issue_id: str = extract_issue_id(issue)
    summary: str = get_str(issue, 'summary')
    description: str = get_str(issue, 'description')

    url_val: str | None = None  # Посилання на задачу для повідомлення
    url_field: object | None = issue.get('url')  # Поле URL з вебхука YouTrack

    issue_id_unknown_msg: str = render(Msg.UTILS_ISSUE_NO_ID)  # Текст маркера невідомого ID задачі

    if isinstance(url_field, str) and url_field:
        # Використання посилання з вебхука
        url_val = url_field
    elif issue_id != issue_id_unknown_msg and YT_BASE_URL:
        # Формування посилання на задачу в YouTrack
        url_val = f'{YT_BASE_URL}/issue/{issue_id}'
    elif url_val is None:
        # Повідомлення, що невідомо URL заявки
        url_val = render(Msg.ERR_YT_ISSUE_NO_URL)

    message: str = format_telegram_message(issue_id, summary, description, url_val)

    # Inline-клавіатура з кнопкою прийняття
    reply_markup: dict[str, object] | None = None
    if issue_id and issue_id != issue_id_unknown_msg:
        button_text: str = render(Msg.CALLBACK_ACCEPT_BUTTON)
        reply_markup = {
            # Додавання кнопки прийняття задачі
            'inline_keyboard': [[{'text': button_text, 'callback_data': f'accept|{issue_id}'}]],
        }

    issue_label: str = issue_id if issue_id and issue_id != issue_id_unknown_msg else issue_id_unknown_msg
    logger.info('Підготовано повідомлення для задачі %s', issue_label)
    await run_in_threadpool(send_message, message, reply_markup)
    return {'ok': True}


@app.post('/telegram')
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Обробляє webhook від Telegram та делегує Aiogram-логіку."""
    logger.info('Отримано вебхук Telegram')
    verify_telegram_secret(request)
    payload: Any = await request.json()
    if not isinstance(payload, dict):
        # Ігнорують невідомі оновлення, щоб не зривати роботу бота
        logger.warning('Отримано некоректний payload від Telegram: %r', payload)
        return {'ok': True}
    try:
        # Передають оновлення у диспетчер Aiogram для маршрутизації
        await telegram_aiogram.process_update(payload)  # type: ignore
    except Exception as err:  # noqa: BLE001
        # Фіксують помилку, але не відповідають користувачу повторно
        logger.exception('Помилка обробки Telegram update: %s', err)
    return {'ok': True}


@app.post('/telegram/webhook')
async def telegram_webhook_alias(request: Request) -> dict[str, bool]:
    """Переадресовує запит на основний обробник ``/telegram`` (запасний маршрут)."""
    return await telegram_webhook(request)


def main() -> None:
    """Запускає Uvicorn сервер для FastAPI застосунку."""
    uvicorn.run(app, host='0.0.0.0', port=8080)


if __name__ == '__main__':
    main()
