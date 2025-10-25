"""Пакет із підтримкою інтеграції Telegram."""

from __future__ import annotations

from .telegram_aiogram import configure, process_update, shutdown
from .telegram_commands import (
    configure_sender,
    handle_confirm_reconnect,
    handle_connect_command,
    handle_reconnect_shortcut,
    handle_start_command,
    handle_unlink_command,
    handle_unlink_decision,
    notify_authorization_required,
)

# Публічний API telegram-пакета
__all__ = [
    'configure',
    'process_update',
    'shutdown',
    'configure_sender',
    'handle_confirm_reconnect',
    'handle_connect_command',
    'handle_reconnect_shortcut',
    'handle_start_command',
    'handle_unlink_command',
    'handle_unlink_decision',
    'notify_authorization_required',
]
