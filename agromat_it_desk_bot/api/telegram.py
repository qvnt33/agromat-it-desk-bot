"""FastAPI routes for Telegram webhook."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from agromat_it_desk_bot.callback_handlers import verify_telegram_secret
from agromat_it_desk_bot.telegram import telegram_aiogram

router = APIRouter()
logger: logging.Logger = logging.getLogger(__name__)


@router.post('/telegram')
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Handle Telegram webhook and delegate to Aiogram logic."""
    logger.info('Отримано вебхук Telegram')

    verify_telegram_secret(request)

    payload: Any = await request.json()
    if not isinstance(payload, dict):
        logger.warning('Отримано некоректний payload від Telegram: %r', payload)
        return {'ok': True}

    try:
        await telegram_aiogram.process_update(payload)
        logger.debug('Telegram webhook передано до Aiogram успішно')
    except Exception as err:  # noqa: BLE001
        logger.exception('Помилка обробки Telegram update: %s', err)

    return {'ok': True}


@router.post('/telegram/webhook')
async def telegram_webhook_alias(request: Request) -> dict[str, bool]:
    """Forward request to main ``/telegram`` handler (fallback route)."""
    return await telegram_webhook(request)
