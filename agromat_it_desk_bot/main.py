"""Забезпечує FastAPI застосунок для обробки вебхуків YouTrack та Telegram."""

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

import agromat_it_desk_bot.telegram_aiogram as telegram_aiogram
import agromat_it_desk_bot.telegram_commands as telegram_commands
from agromat_it_desk_bot.callback_handlers import verify_telegram_secret
from agromat_it_desk_bot.config import YT_BASE_URL, YT_WEBHOOK_SECRET
from agromat_it_desk_bot.telegram_service import send_message
from agromat_it_desk_bot.utils import configure_logging, extract_issue_id, format_message, get_str

configure_logging()
logger: logging.Logger = logging.getLogger(__name__)

app = FastAPI()

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
        raise HTTPException(status_code=400, detail='Invalid payload shape')

    data: dict[str, object] = cast(dict[str, object], payload)

    if YT_WEBHOOK_SECRET is not None:
        auth_header: str | None = request.headers.get('Authorization')
        expected: str = f'Bearer {YT_WEBHOOK_SECRET}'
        if auth_header != expected:
            logger.warning('Невірний секрет YouTrack вебхука')
            raise HTTPException(status_code=403, detail='Forbidden')

    logger.debug('Отримано вебхук YouTrack: %s', data)

    issue_candidate: object | None = data.get('issue')
    issue: Mapping[str, object] = (
        cast(dict[str, object], issue_candidate) if isinstance(issue_candidate, dict) else data
    )

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
    """Обробляє webhook від Telegram та делегує Aiogram-логіку."""
    logger.info('Отримано вебхук Telegram')
    verify_telegram_secret(request)
    payload: Any = await request.json()
    if not isinstance(payload, dict):
        logger.warning('Отримано некоректний payload від Telegram: %r', payload)
        return {'ok': True}
    try:
        await telegram_aiogram.process_update(payload)
    except Exception as err:  # noqa: BLE001
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


@app.on_event('shutdown')
async def _shutdown_bot() -> None:
    """Закриває сесію бота Aiogram при завершенні FastAPI."""
    await telegram_aiogram.shutdown()
