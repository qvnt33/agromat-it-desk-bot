"""Перевіряє форматування повідомлення з розкладом."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from agromat_it_desk_bot.schedule.weekly import (
    DailyReminder,
    ExchangeSourceConfig,
    ReminderConfig,
    ScheduleConfig,
    SchedulePublisher,
    ShiftEntry,
)


class _DummySender:
    async def send_message(  # noqa: D401
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = 'HTML',
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool = True,
        reply_to_message_id: int | None = None,
    ) -> int:
        del chat_id, text, parse_mode, reply_markup, disable_web_page_preview, reply_to_message_id
        raise AssertionError('send_message не повинен викликатися у тесті')

    async def delete_message(self, chat_id: int | str, message_id: int) -> None:  # noqa: D401
        del chat_id, message_id
        raise AssertionError('delete_message не повинен викликатися у тесті')

    async def answer_callback(  # noqa: D401
        self,
        callback_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        del callback_id, text, show_alert
        raise AssertionError('answer_callback не повинен викликатися у тесті')

    async def edit_reply_markup(  # noqa: D401
        self,
        chat_id: int | str,
        message_id: int,
        reply_markup: dict[str, Any] | None,
    ) -> None:
        del chat_id, message_id, reply_markup
        raise AssertionError('edit_reply_markup не повинен викликатися у тесті')

    async def edit_message_text(  # noqa: D401
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = 'HTML',
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool = True,
    ) -> None:
        del chat_id, message_id, text, parse_mode, reply_markup, disable_web_page_preview
        raise AssertionError('edit_message_text не повинен викликатися у тесті')

    async def pin_message(  # noqa: D401
        self,
        chat_id: int | str,
        message_id: int,
        *,
        disable_notification: bool = True,
    ) -> None:
        del chat_id, message_id, disable_notification
        raise AssertionError('pin_message не повинен викликатися у тесті')


@pytest.fixture
def source_config() -> ExchangeSourceConfig:
    return ExchangeSourceConfig(
        email='user@example.com',
        username='user@example.com',
        password='secret',
        server=None,
        calendar_name=None,
        timezone='UTC',
    )


@pytest.fixture
def publisher(source_config: ExchangeSourceConfig) -> SchedulePublisher:
    """Створює інстанс публікатора з тестовою часовою зоною."""
    config = ScheduleConfig(
        chat_id=123,
        source=source_config,
        send_weekday=6,
        send_time=time(9, 0),
        pin_message=False,
    )
    return SchedulePublisher(_DummySender(), config)


@pytest.fixture
def reminder(source_config: ExchangeSourceConfig) -> DailyReminder:
    config = ReminderConfig(
        chat_id=123,
        source=source_config,
        send_time=time(18, 0),
    )
    return DailyReminder(_DummySender(), config)


def test_format_message_without_shifts(publisher: SchedulePublisher) -> None:
    """Коли змін немає – повідомлення містить заголовок та попередження."""
    tz = ZoneInfo('UTC')
    start = datetime(2025, 1, 6, tzinfo=tz)
    end = start + timedelta(days=7)

    result = publisher._format_message(start, end, [])

    assert '<b>06.01–12.01</b>' in result
    assert '<code>N/A</code>' in result


def test_format_message_with_shifts(publisher: SchedulePublisher) -> None:
    """Зміни форматуються з датою, часом та назвою."""
    tz = ZoneInfo('UTC')
    start = datetime(2025, 1, 6, tzinfo=tz)
    end = start + timedelta(days=7)
    shifts = [
        ShiftEntry(
            subject='Белоус',
            start=start.replace(hour=0),
            end=start.replace(hour=23, minute=59),
            categories=('Друга зміна',),
        ),
        ShiftEntry(
            subject='Навроцький',
            start=start.replace(day=11, hour=0),
            end=start.replace(day=11, hour=23, minute=59),
            categories=('Черговий',),
        ),
    ]

    result = publisher._format_message(start, end, shifts)

    assert '🕗 <b>Будні</b>\n<b>Пн (06.01) — </b><code>Белоус</code>' in result
    assert '🚨 <b>Вихідні</b>\n<b>Сб (11.01) — </b><code>Навроцький</code>' in result


def test_daily_reminder_without_shifts(reminder: DailyReminder) -> None:
    """Повідомлення для нагадування має містити текст про відсутність змін."""
    target_day = date(2025, 1, 6)
    result = reminder._format_message(target_day, [])

    assert result == '🔔 <b>Завтра, Пн (06.01):</b> <code>N/A</code>'


def test_daily_reminder_with_shifts(reminder: DailyReminder) -> None:
    """Нагадування відображає чергового та тип зміни."""
    target_day = date(2025, 1, 6)
    shifts = [
        ShiftEntry(
            subject='Белоус',
            start=datetime(2025, 1, 6, 0, 0, tzinfo=ZoneInfo('UTC')),
            end=datetime(2025, 1, 6, 23, 59, tzinfo=ZoneInfo('UTC')),
            categories=('Друга зміна',),
        ),
        ShiftEntry(
            subject='Попередній день',
            start=datetime(2025, 1, 5, 0, 0, tzinfo=ZoneInfo('UTC')),
            end=datetime(2025, 1, 5, 23, 59, tzinfo=ZoneInfo('UTC')),
            categories=('Черговий',),
        ),
    ]

    result = reminder._format_message(target_day, shifts)

    assert result == '🔔 <b>Завтра, Пн (06.01):</b> <code>Белоус</code>'
