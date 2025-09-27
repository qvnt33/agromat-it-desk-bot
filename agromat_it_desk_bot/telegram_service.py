"""Функції-обгортки для викликів Telegram Bot API."""

from __future__ import annotations

import logging
from typing import Any

import requests  # type: ignore[import-untyped]
from fastapi import HTTPException

from agromat_it_desk_bot.config import BOT_TOKEN, TELEGRAM_CHAT_ID
from agromat_it_desk_bot.messages import Msg, render

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


def send_message(text: str, reply_markup: dict[str, Any] | None = None) -> None:
    """Надсилає повідомлення у вказаний чат Telegram.

    :param text: Вміст повідомлення, яке необхідно показати користувачам.
    :param reply_markup: Inline-клавіатура з кнопками (може бути ``None``).
    :raises HTTPException: 500, якщо бот не налаштований; 502, якщо Telegram повернув помилку.
    """
    if not BOT_TOKEN or not TELEGRAM_CHAT_ID:
        # Припиняють відправку, якщо бот не налаштовано
        raise HTTPException(status_code=500, detail=render(Msg.ERR_TELEGRAM_CREDENTIALS))

    payload: dict[str, Any] = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'disable_web_page_preview': True,
        'parse_mode': 'HTML',
    }
    if reply_markup is not None:
        # Приєднують клавіатуру лише коли вона надана
        payload['reply_markup'] = reply_markup

    endpoint: str = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    # Звертаються до Telegram Bot API з JSON-повідомленням
    response: requests.Response = requests.post(endpoint, json=payload, timeout=10)
    if not response.ok:
        # Повідомляють про помилку HTTP та пробрасывають 502
        logger.error('Telegram повернув помилку під час надсилання повідомлення: %s', response.text)
        raise HTTPException(status_code=502, detail=render(Msg.ERR_TELEGRAM_API, error=response.text))

    logger.info('Надіслано повідомлення в Telegram чат %s', TELEGRAM_CHAT_ID)


def call_api(method: str, payload: dict[str, Any]) -> requests.Response:
    """Викликає довільний метод Telegram Bot API.

    :param method: Назва методу (наприклад, ``answerCallbackQuery``).
    :param payload: Тіло запиту у форматі JSON.
    :returns: Обʼєкт ``Response`` з результатом виклику.
    :raises HTTPException: 500, якщо токен бота не налаштований.
    """
    if BOT_TOKEN is None:
        # Захищають універсальні виклики API від відсутнього токена
        raise HTTPException(status_code=500, detail=render(Msg.ERR_TELEGRAM_TOKEN))

    # Викликають API Telegram; у разі помилки лише логування
    endpoint: str = f'https://api.telegram.org/bot{BOT_TOKEN}/{method}'
    response: requests.Response = requests.post(endpoint, json=payload, timeout=10)
    if not response.ok:
        # Занотовують відповідь Telegram для подальшого дебагу
        logger.error('Помилка Telegram API (%s): %s', method, response.text)
    return response
