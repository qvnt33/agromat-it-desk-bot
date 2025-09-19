"""Функції-обгортки для викликів Telegram Bot API."""

from __future__ import annotations

import logging
from typing import Any

import requests
from fastapi import HTTPException

from agromat_it_desk_bot.config import BOT_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


def send_message(text: str, reply_markup: dict[str, Any] | None = None) -> None:
    """Надіслати повідомлення у вказаний чат Telegram.

    :param text: Вміст повідомлення, яке необхідно показати користувачам.
    :type text: str
    :param reply_markup: Inline-клавіатура з кнопками (може бути ``None``).
    :type reply_markup: dict[str, Any] | None
    :raises HTTPException: 500, якщо бот не налаштований; 502, якщо Telegram повернув помилку.
    """
    if not BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(status_code=500, detail='Telegram credentials are not configured')

    payload: dict[str, Any] = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'disable_web_page_preview': True,
        'parse_mode': 'HTML',
    }
    if reply_markup is not None:
        payload['reply_markup'] = reply_markup

    response: requests.Response = requests.post(
        f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
        json=payload,
        timeout=10,
    )
    if not response.ok:
        logger.error('Telegram повернув помилку під час надсилання повідомлення: %s', response.text)
        raise HTTPException(status_code=502, detail=f'Telegram error: {response.text}')

    logger.info('Надіслано повідомлення в Telegram чат %s', TELEGRAM_CHAT_ID)


def call_api(method: str, payload: dict[str, Any]) -> requests.Response:
    """Викликати довільний метод Telegram Bot API.

    :param method: Назва методу (наприклад, ``answerCallbackQuery``).
    :type method: str
    :param payload: Тіло запиту у форматі JSON.
    :type payload: dict[str, Any]
    :returns: Обʼєкт ``Response`` з результатом виклику.
    :rtype: requests.Response
    :raises HTTPException: 500, якщо токен бота не налаштований.
    """
    if BOT_TOKEN is None:
        raise HTTPException(status_code=500, detail='Telegram token not configured')

    # Викликати API Telegram; у разі помилки лише логування
    response: requests.Response = requests.post(
        f'https://api.telegram.org/bot{BOT_TOKEN}/{method}',
        json=payload,
        timeout=10,
    )
    if not response.ok:
        logger.error('Помилка Telegram API (%s): %s', method, response.text)
    return response
