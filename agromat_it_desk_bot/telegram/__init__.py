"""Пакет із підтримкою інтеграції Telegram."""

from __future__ import annotations

from .telegram_aiogram import process_update, shutdown
from .telegram_commands import handle_confirm_login_command, handle_register_command, send_help
from .telegram_service import call_api, send_message

# Публічний API telegram-пакета
__all__ = [
    'process_update',
    'shutdown',
    'handle_confirm_login_command',
    'handle_register_command',
    'send_help',
    'call_api',
    'send_message',
]
