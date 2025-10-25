"""Зберігає спільні залежності Telegram рівня (наприклад, відправник)."""

from __future__ import annotations

from agromat_it_desk_bot.telegram.telegram_sender import TelegramSender

_sender: TelegramSender | None = None


def set_sender(sender: TelegramSender) -> None:
    """Реєструє екземпляр TelegramSender для глобального використання."""
    global _sender
    _sender = sender


def get_sender() -> TelegramSender:
    """Повертає налаштований TelegramSender."""
    if _sender is None:
        raise RuntimeError('TelegramSender не налаштовано')
    return _sender
