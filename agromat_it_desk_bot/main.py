"""Забезпечує FastAPI застосунок для обробки вебхуків YouTrack та Telegram."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from aiogram import Bot, Dispatcher
from fastapi import FastAPI, HTTPException, Request

from agromat_it_desk_bot.callback_handlers import verify_telegram_secret
from agromat_it_desk_bot.config import BOT_TOKEN, TELEGRAM_CHAT_ID, YT_BASE_URL, YT_WEBHOOK_SECRET
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.telegram import context as telegram_context
from agromat_it_desk_bot.telegram import telegram_aiogram, telegram_commands
from agromat_it_desk_bot.telegram.telegram_sender import AiogramTelegramSender
from agromat_it_desk_bot.utils import (
    configure_logging,
    extract_issue_assignee,
    extract_issue_author,
    extract_issue_id,
    extract_issue_status,
    format_telegram_message,
    get_str,
)

configure_logging()
logger: logging.Logger = logging.getLogger(__name__)


_TELEGRAM_CHAT_ID_RESOLVED: int | str
if TELEGRAM_CHAT_ID is None:
    raise RuntimeError('TELEGRAM_CHAT_ID не налаштовано')
try:
    _TELEGRAM_CHAT_ID_RESOLVED = int(TELEGRAM_CHAT_ID)
except ValueError:
    _TELEGRAM_CHAT_ID_RESOLVED = TELEGRAM_CHAT_ID


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Керує запуском та завершенням FastAPI застосунку.

    :param _app: Поточний екземпляр FastAPI.
    :yields: ``None`` протягом роботи застосунку.
    """
    if not BOT_TOKEN:
        raise RuntimeError('BOT_TOKEN не налаштовано')

    bot: Bot = Bot(token=BOT_TOKEN)
    dispatcher: Dispatcher = Dispatcher()
    sender = AiogramTelegramSender(bot)
    telegram_commands.configure_sender(sender)
    telegram_aiogram.configure(bot, dispatcher)

    try:
        yield
    finally:
        # Закривають HTTP-сесію бота Aiogram при виході
        await telegram_aiogram.shutdown()


app = FastAPI(lifespan=_lifespan)

# Перехідні псевдоніми для збереження сумісності тестів/імпортів
PendingTokenUpdate = telegram_commands.PendingTokenUpdate
pending_token_updates = telegram_commands.pending_token_updates
# Сумісність зі старим API
PendingLoginChange = PendingTokenUpdate
pending_login_updates = pending_token_updates
send_help = telegram_commands.send_help
handle_start_command = telegram_commands.handle_start_command
handle_link_command = telegram_commands.handle_link_command
handle_unlink_command = telegram_commands.handle_unlink_command
handle_connect_command = telegram_commands.handle_connect_command
handle_reconnect_command = telegram_commands.handle_connect_command  # зворотна сумісність
handle_confirm_reconnect = telegram_commands.handle_confirm_reconnect
handle_reconnect_shortcut = telegram_commands.handle_reconnect_shortcut


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
        raise HTTPException(status_code=400, detail='Некоректний формат тіла запиту')

    if YT_WEBHOOK_SECRET is not None:
        auth_header: str | None = request.headers.get('Authorization')
        expected: str = f'Bearer {YT_WEBHOOK_SECRET}'

        if auth_header != expected:
            # Контроль секрету YouTrack
            logger.warning('Невірний секрет YouTrack вебхука')
            raise HTTPException(status_code=403, detail='Доступ заборонено')

    logger.info('Отримано вебхук YouTrack: %s', payload)

    # Дані задачі вебхука
    issue_candidate: object | None = payload.get('issue')
    issue: Mapping[str, object] = issue_candidate if isinstance(issue_candidate, dict) else payload

    issue_id: str = extract_issue_id(issue)
    summary: str = get_str(issue, 'summary')
    description: str = get_str(issue, 'description')

    logger.debug('YouTrack webhook: issue_id=%s summary=%s', issue_id, summary)

    url_val: str | None = None  # Посилання на задачу для повідомлення
    url_field: object | None = issue.get('url')  # Поле URL з вебхука YouTrack

    issue_id_unknown_msg: str = render(Msg.YT_ISSUE_NO_ID)  # Текст маркера невідомого ID задачі

    status_text: str | None = extract_issue_status(issue)
    assignee_text: str | None = extract_issue_assignee(issue)
    author_text: str | None = extract_issue_author(issue)

    if isinstance(url_field, str) and url_field:
        # Використання посилання з вебхука
        url_val = url_field
    elif issue_id != issue_id_unknown_msg and YT_BASE_URL:
        # Формування посилання на задачу в YouTrack
        url_val = f'{YT_BASE_URL}/issue/{issue_id}'
    elif url_val is None:
        # Повідомлення, що невідомо URL заявки
        url_val = render(Msg.ERR_YT_ISSUE_NO_URL)
    logger.debug('YouTrack webhook: resolved_url=%s', url_val)

    telegram_msg: str = format_telegram_message(issue_id,
                                                summary,
                                                description,
                                                url_val,
                                                assignee=assignee_text,
                                                status=status_text,
                                                author=author_text)
    logger.debug('YouTrack webhook: message_length=%s', len(telegram_msg))

    # Inline-клавіатура з кнопкою прийняття
    reply_markup: dict[str, object] | None = None
    if issue_id and issue_id != issue_id_unknown_msg:
        button_text: str = render(Msg.TG_BTN_ACCEPT_ISSUE)
        reply_markup = {
            # Додавання кнопки прийняття задачі
            'inline_keyboard': [[{'text': button_text, 'callback_data': f'accept|{issue_id}'}]],
        }
        logger.debug('YouTrack webhook: inline keyboard prepared for %s', issue_id)

    issue_label: str = issue_id if issue_id and issue_id != issue_id_unknown_msg else issue_id_unknown_msg
    logger.info('Підготовано повідомлення для задачі %s', issue_label)

    sender = telegram_context.get_sender()
    await sender.send_message(
        _TELEGRAM_CHAT_ID_RESOLVED,
        telegram_msg,
        parse_mode='HTML',
        reply_markup=reply_markup,
        disable_web_page_preview=False,
    )
    return {'ok': True}


@app.post('/telegram')
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Обробляє webhook від Telegram та делегує Aiogram-логіку."""
    logger.info('Отримано вебхук Telegram')

    verify_telegram_secret(request)  # Перевірка секрету вебхука Телеграм

    payload: Any = await request.json()
    if not isinstance(payload, dict):
        # Ігнорування невідомих оновлень, щоб не зривати роботу бота
        logger.warning('Отримано некоректний payload від Telegram: %r', payload)
        return {'ok': True}

    try:
        # Передати оновлення у диспетчер Aiogram для маршрутизації
        await telegram_aiogram.process_update(payload)
        logger.debug('Telegram webhook передано до Aiogram успішно')
    except Exception as err:  # noqa: BLE001
        # Фіксування помилки, але не відповідати користувачу повторно
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
