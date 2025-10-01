"""Функції-обгортки для викликів Telegram Bot API."""

from __future__ import annotations

import logging
from typing import Any

import requests
from fastapi import HTTPException

from agromat_it_desk_bot.config import BOT_TOKEN, TELEGRAM_CHAT_ID

logger: logging.Logger = logging.getLogger(__name__)


def send_message(text: str, reply_markup: dict[str, Any] | None = None) -> None:
    """Надсилає повідомлення у вказаний чат Telegram.

    :param text: Вміст повідомлення, яке необхідно показати користувачам.
    :param reply_markup: Inline-клавіатура з кнопками (може бути ``None``).
    :raises HTTPException: 500, якщо бот не налаштований; 502, якщо Telegram повернув помилку.
    """
    if not BOT_TOKEN or not TELEGRAM_CHAT_ID:
        # Перевіряють наявність налаштувань Telegram
        raise HTTPException(status_code=500, detail='Конфігурація Telegram відсутня')

    # Формують параметри запиту sendMessage
    payload: dict[str, Any] = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'disable_web_page_preview': True,
        'parse_mode': 'HTML',
    }
    logger.debug('Відправлення повідомлення: chat_id=%s length=%s', TELEGRAM_CHAT_ID, len(text))
    if reply_markup is not None:
        # Додають клавіатуру відповіді
        payload['reply_markup'] = reply_markup

    endpoint: str = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'  # Формують URL виклику Telegram Bot API

    # Відправляють запит до Telegram Bot API з JSON-повідомленням
    response: requests.Response = requests.post(endpoint, json=payload, timeout=10)
    if not response.ok:
        # Обробляють помилку відповіді Telegram
        logger.error('Telegram повернув помилку під час надсилання повідомлення: %s', response.text)
        raise HTTPException(status_code=502, detail=f'Помилка Telegram API: {response.text}')

    logger.info('Надсилають повідомлення в Telegram чат %s', TELEGRAM_CHAT_ID)


def call_api(method: str, payload: dict[str, Any]) -> requests.Response:
    """Викликає довільний метод Telegram Bot API.

    :param method: Назва методу (наприклад, ``answerCallbackQuery``).
    :param payload: Тіло запиту у форматі JSON.
    :returns: Обʼєкт ``Response`` з результатом виклику.
    :raises HTTPException: 500, якщо токен бота не налаштований.
    """
    if BOT_TOKEN is None:
        # Перевіряють доступність токена
        raise HTTPException(status_code=500, detail='Telegram токен не налаштовано')

    # Викликають API Telegram з довільним методом
    endpoint: str = f'https://api.telegram.org/bot{BOT_TOKEN}/{method}'
    logger.debug('Виклик Telegram API: method=%s', method)
    response: requests.Response = requests.post(endpoint, json=payload, timeout=10)

    if not response.ok:
        # Журналюють помилку Telegram
        logger.error('Помилка Telegram API (%s): %s', method, response.text)
    return response
