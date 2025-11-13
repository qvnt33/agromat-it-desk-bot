"""Перевіряє додавання статусних емодзі у повідомлення."""

from __future__ import annotations

from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.utils import format_telegram_message


def _build_message(status: str | None) -> str:
    """Формує повідомлення для тестів."""
    return format_telegram_message(
        'ID-1',
        'Summary',
        'Description text',
        'https://example.com/ID-1',
        assignee='Agent',
        status=status,
        author='Reporter',
    )


def test_format_message_sets_known_status_emoji() -> None:
    """Статус 'Нова' має додавати жовтий індикатор."""
    message: str = _build_message('Нова')
    assert message.startswith('🟡 ')


def test_format_message_falls_back_to_default_emoji() -> None:
    """Невідомий статус веде до коричневого індикатора."""
    message: str = _build_message('Custom Status')
    assert message.startswith('🟤 ')


def test_format_message_uses_archived_emoji() -> None:
    """Статус 'Архівовано' має показувати біле коло."""
    archived_status: str = render(Msg.STATUS_ARCHIVED)
    message: str = _build_message(archived_status)
    assert message.startswith('⚪ ')
