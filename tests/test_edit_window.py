"""Перевіряє обробку 48-годинного вікна редагування повідомлень."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agromat_help_desk_bot import main


def test_edit_window_expired_true() -> None:
    """Повідомлення старше 48 годин має пропускатися."""
    past: datetime = datetime.now(tz=timezone.utc) - timedelta(hours=49)
    assert main._is_edit_window_expired(past.isoformat()) is True


def test_edit_window_not_expired() -> None:
    """Повідомлення в межах вікна редагування треба оновлювати."""
    recent: datetime = datetime.now(tz=timezone.utc) - timedelta(hours=47)
    assert main._is_edit_window_expired(recent.isoformat()) is False


def test_edit_window_invalid_timestamp() -> None:
    """Невалідні значення не мають блокувати оновлення."""
    assert main._is_edit_window_expired('not-a-date') is False
