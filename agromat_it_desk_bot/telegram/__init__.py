"""Пакет із підтримкою інтеграції Telegram."""

from __future__ import annotations

from .telegram_aiogram import process_update, shutdown
from .telegram_commands import (
    handle_confirm_login_command,
    handle_confirm_reconnect,
    handle_connect_command,
    handle_link_command,
    handle_reconnect_shortcut,
    handle_register_command,
    handle_start_command,
    handle_unlink_command,
    handle_unlink_decision,
    notify_authorization_required,
    send_help,
)
from .telegram_service import call_api, send_message

# Публічний API telegram-пакета
__all__ = [
    'process_update',
    'shutdown',
    'handle_confirm_login_command',
    'handle_confirm_reconnect',
    'handle_connect_command',
    'handle_link_command',
    'handle_register_command',
    'handle_reconnect_shortcut',
    'handle_start_command',
    'handle_unlink_command',
    'handle_unlink_decision',
    'send_help',
    'notify_authorization_required',
    'call_api',
    'send_message',
]
