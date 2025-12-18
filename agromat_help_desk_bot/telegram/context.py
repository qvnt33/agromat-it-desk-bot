"""Store shared Telegram-level dependencies (e.g., sender)."""

from __future__ import annotations

from agromat_help_desk_bot.telegram.telegram_sender import TelegramSender

_sender: TelegramSender | None = None


def set_sender(sender: TelegramSender) -> None:
    """Register TelegramSender instance for global use."""
    global _sender
    _sender = sender


def get_sender() -> TelegramSender:
    """Return configured TelegramSender."""
    if _sender is None:
        raise RuntimeError('TelegramSender не налаштовано')
    return _sender
