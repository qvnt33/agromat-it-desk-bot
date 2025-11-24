"""Отримує розклад змін з Exchange та надсилає його в Telegram."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from agromat_it_desk_bot.config import (
    SCHEDULE_CALENDAR_NAME,
    SCHEDULE_CHAT_ID,
    SCHEDULE_DAILY_REMINDER_CHAT_ID,
    SCHEDULE_DAILY_REMINDER_ENABLED,
    SCHEDULE_DAILY_REMINDER_HOUR,
    SCHEDULE_DAILY_REMINDER_MINUTE,
    SCHEDULE_ENABLED,
    SCHEDULE_EXCHANGE_EMAIL,
    SCHEDULE_EXCHANGE_PASSWORD,
    SCHEDULE_EXCHANGE_SERVER,
    SCHEDULE_EXCHANGE_USERNAME,
    SCHEDULE_PIN_WEEKLY,
    SCHEDULE_SEND_HOUR,
    SCHEDULE_SEND_MINUTE,
    SCHEDULE_SEND_WEEKDAY,
    SCHEDULE_TIMEZONE,
)
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.telegram.telegram_sender import TelegramSender, escape_html

logger: logging.Logger = logging.getLogger(__name__)
_WEEKDAY_LABELS: tuple[str, ...] = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд')


@dataclass(frozen=True)
class ExchangeSourceConfig:
    """Налаштування підключення до Exchange/Outlook."""

    email: str
    username: str
    password: str
    server: str | None
    calendar_name: str | None
    timezone: str


@dataclass(frozen=True)
class ScheduleConfig:
    """Параметри побудови тижневого розкладу."""

    chat_id: int | str
    source: ExchangeSourceConfig
    send_weekday: int
    send_time: time
    pin_message: bool


@dataclass(frozen=True)
class ReminderConfig:
    """Параметри щоденного нагадування."""

    chat_id: int | str
    source: ExchangeSourceConfig
    send_time: time


@dataclass(frozen=True)
class ShiftEntry:
    """Описує одну зміну у календарі."""

    subject: str
    start: datetime
    end: datetime
    categories: tuple[str, ...]


class ExchangeScheduleClient:
    """Ініціює запити до Exchange/Outlook та повертає список змін."""

    def __init__(self, source: ExchangeSourceConfig) -> None:
        self._source = source

    def fetch_week(self, start: datetime, end: datetime) -> list[ShiftEntry]:
        """Повертає зміни у вказаному діапазоні."""
        return self.fetch_range(start, end)

    def fetch_range(self, start: datetime, end: datetime) -> list[ShiftEntry]:
        """Зчитує події календаря у довільному діапазоні."""
        try:
            from exchangelib import DELEGATE, Account, Configuration, Credentials
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError('exchangelib не встановлено, розклад недоступний') from exc

        credentials = Credentials(username=self._source.username, password=self._source.password)
        if self._source.server:
            exch_config = Configuration(server=self._source.server, credentials=credentials)
            account = Account(
                primary_smtp_address=self._source.email,
                config=exch_config,
                credentials=credentials,
                autodiscover=False,
                access_type=DELEGATE,
            )
        else:
            account = Account(
                primary_smtp_address=self._source.email,
                credentials=credentials,
                autodiscover=True,
                access_type=DELEGATE,
            )

        folder = self._resolve_calendar(account)
        items = folder.view(start=start, end=end).order_by('start').only('subject', 'start', 'end', 'categories')
        shifts: list[ShiftEntry] = []
        for item in items:
            subject = str(getattr(item, 'subject', '') or 'Без назви').strip()
            start_dt = getattr(item, 'start', None)
            end_dt = getattr(item, 'end', None)
            if start_dt is None or end_dt is None:
                continue
            categories_raw = getattr(item, 'categories', None)
            categories: tuple[str, ...] = (
                tuple(str(cat).strip() for cat in categories_raw if str(cat).strip())
                if categories_raw
                else ()
            )
            shifts.append(ShiftEntry(subject=subject or 'Без назви', start=start_dt, end=end_dt, categories=categories))
        return shifts

    def _resolve_calendar(self, account: Any) -> Any:  # noqa: ANN401
        """Знаходить календар за назвою або повертає дефолтний."""
        folder = account.calendar
        if not self._source.calendar_name:
            return folder

        candidate_name: str = self._source.calendar_name.strip()
        try:
            iterator = account.root.walk()
        except Exception as exc:  # noqa: BLE001
            logger.warning('Не вдалося перерахувати календарі %s: %s', candidate_name, exc)
            return folder

        candidate_norm = candidate_name.casefold()
        for entry in iterator:
            folder_name: str = getattr(entry, 'name', '').strip()
            if folder_name.casefold() == candidate_norm:
                logger.info('Знайдено календар %s', folder_name)
                return entry

        logger.warning('Не знайдено календар %s, використовую стандартний', candidate_name)
        return folder


class SchedulePublisher:
    """Запускає фонового робота, що надсилає графік змін раз на тиждень."""

    def __init__(self, sender: TelegramSender, config: ScheduleConfig) -> None:
        self._sender = sender
        self._config = config
        self._client = ExchangeScheduleClient(config.source)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._tz = ZoneInfo(config.source.timezone)

    def start(self) -> None:
        """Створює асинхронний таск для відправки розкладу."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Зупиняє таск та чекає завершення."""
        self._stop_event.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            next_run = self._next_trigger()
            wait_seconds: float = max((next_run - datetime.now(tz=self._tz)).total_seconds(), 0.0)
            logger.info('Наступне оновлення розкладу заплановано на %s', next_run.isoformat())
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                break
            except asyncio.TimeoutError:
                await self._publish_once()

    def _next_trigger(self) -> datetime:
        now = datetime.now(tz=self._tz)
        send_time = datetime.combine(now.date(), self._config.send_time, tzinfo=self._tz)
        delta = (self._config.send_weekday - now.weekday()) % 7
        candidate = send_time + timedelta(days=delta)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    async def _publish_once(self) -> None:
        start, end = self._resolve_week_range()
        logger.info('Формую розклад на тиждень %s - %s', start.date(), (end - timedelta(days=1)).date())
        try:
            shifts = await asyncio.to_thread(self._client.fetch_week, start, end)
        except Exception as exc:  # noqa: BLE001
            logger.exception('Не вдалося отримати розклад змін: %s', exc)
            return
        message = self._format_message(start, end, shifts)
        try:
            message_id = await self._sender.send_message(self._config.chat_id, message)
            if self._config.pin_message:
                try:
                    await self._sender.pin_message(self._config.chat_id, message_id, disable_notification=True)
                except Exception as pin_exc:  # noqa: BLE001
                    logger.exception('Не вдалося закріпити повідомлення розкладу: %s', pin_exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception('Не вдалося надіслати розклад змін: %s', exc)

    def _resolve_week_range(self) -> tuple[datetime, datetime]:
        now = datetime.now(tz=self._tz)
        days_until_monday = (7 - now.weekday()) % 7
        monday = datetime.combine((now + timedelta(days=days_until_monday)).date(), time(0, 0), tzinfo=self._tz)
        end = monday + timedelta(days=7)
        return monday, end

    def _format_message(self, start: datetime, end: datetime, shifts: Sequence[ShiftEntry]) -> str:
        period_end = end - timedelta(days=1)
        start_label: str = start.strftime('%d.%m')
        end_label: str = period_end.strftime('%d.%m')
        weekday_lines: list[str] = []
        weekend_lines: list[str] = []
        schedule_map: dict[date, list[ShiftEntry]] = {}
        for shift in shifts:
            day_key: date = shift.start.astimezone(self._tz).date()
            schedule_map.setdefault(day_key, []).append(shift)

        current_day: date = start.date()
        end_day: date = period_end.date()
        while current_day <= end_day:
            entries: list[ShiftEntry] = sorted(
                schedule_map.get(current_day, []),
                key=lambda item: item.start,
            )
            line = self._format_week_line(current_day, entries)
            if current_day.weekday() < 5:
                weekday_lines.append(line)
            else:
                weekend_lines.append(line)
            current_day += timedelta(days=1)

        body_parts: list[str] = []
        if weekday_lines:
            body_parts.append('🕗 <b>Будні</b>')
            body_parts.extend(weekday_lines)
            if weekend_lines:
                body_parts.append('')
        if weekend_lines:
            body_parts.append('🚨 <b>Вихідні</b>')
            body_parts.extend(weekend_lines)

        body: str = '\n'.join(body_parts)
        return render(Msg.SCHEDULE_WEEKLY_BODY, start=start_label, end=end_label, body=body)

    def _format_week_line(self, day: date, shifts: Sequence[ShiftEntry]) -> str:
        weekday = _WEEKDAY_LABELS[day.weekday()]
        day_label = day.strftime('%d.%m')
        subjects: list[str] = []
        for shift in shifts:
            subjects.append(_format_subject(shift.subject, shift.categories))
        if not subjects:
            subjects.append(_format_subject(None, ()))
        body = ', '.join(subjects)
        return f'<b>{weekday} ({day_label}) – </b>{body}'


class DailyReminder:
    """Надсилає нагадування про завтрашню зміну у вказаний час."""

    def __init__(self, sender: TelegramSender, config: ReminderConfig) -> None:
        self._sender = sender
        self._config = config
        self._client = ExchangeScheduleClient(config.source)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._tz = ZoneInfo(config.source.timezone)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            next_run = self._next_trigger()
            wait_seconds: float = max((next_run - datetime.now(tz=self._tz)).total_seconds(), 0.0)
            logger.info('Наступне щоденне нагадування заплановано на %s', next_run.isoformat())
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                break
            except asyncio.TimeoutError:
                await self._publish_once()

    def _next_trigger(self) -> datetime:
        now = datetime.now(tz=self._tz)
        candidate = datetime.combine(now.date(), self._config.send_time, tzinfo=self._tz)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    async def _publish_once(self) -> None:
        target_date = datetime.now(tz=self._tz).date() + timedelta(days=1)
        start = datetime.combine(target_date, time(0, 0), tzinfo=self._tz)
        end = start + timedelta(days=1)
        try:
            shifts = await asyncio.to_thread(self._client.fetch_range, start, end)
        except Exception as exc:  # noqa: BLE001
            logger.exception('Не вдалося отримати розклад для нагадування: %s', exc)
            return
        message = self._format_message(target_date, shifts)
        try:
            await self._sender.send_message(self._config.chat_id, message)
        except Exception as exc:  # noqa: BLE001
            logger.exception('Не вдалося надіслати щоденне нагадування: %s', exc)

    def _format_message(self, target_date: date, shifts: Sequence[ShiftEntry]) -> str:
        weekday = _WEEKDAY_LABELS[target_date.weekday()]
        date_label: str = target_date.strftime('%d.%m')
        subjects: list[str] = []
        for shift in sorted(shifts, key=lambda item: item.start):
            start_local_date = shift.start.astimezone(self._tz).date()
            if start_local_date != target_date:
                continue
            subjects.append(_format_subject(shift.subject, shift.categories))
        if not subjects:
            subjects.append(_format_subject(None, ()))
        body = ', '.join(subjects)
        return render(Msg.SCHEDULE_DAILY_ENTRY, date=date_label, weekday=weekday, body=body)


def _render_shift_label(categories: Sequence[str]) -> str:
    for category in categories:
        normalized = category.strip()
        if normalized:
            return escape_html(normalized)
    return ''


def _format_subject(name: str | None, categories: Sequence[str]) -> str:
    text_raw: str = name.strip() if isinstance(name, str) else ''
    if not text_raw:
        text_raw = 'N/A'
    subject = f'<code>{escape_html(text_raw)}</code>'
    label = _render_shift_label(categories)
    if label:
        return f'{subject} — {label}'
    return subject


def build_schedule_publisher(sender: TelegramSender) -> SchedulePublisher | None:
    """Створює публікатор розкладу, якщо ввімкнено відповідні налаштування."""
    if not SCHEDULE_ENABLED:
        logger.info('Щотижневий розклад вимкнено через SCHEDULE_ENABLED')
        return None
    if not SCHEDULE_CHAT_ID:
        logger.warning('SCHEDULE_CHAT_ID не налаштовано, пропускаю розклад')
        return None
    source = _build_exchange_source()
    if source is None:
        return None

    chat_id: int | str
    try:
        chat_id = int(SCHEDULE_CHAT_ID)
    except (ValueError, TypeError):
        chat_id = SCHEDULE_CHAT_ID

    weekday = SCHEDULE_SEND_WEEKDAY % 7
    send_time = time(hour=SCHEDULE_SEND_HOUR, minute=SCHEDULE_SEND_MINUTE)
    config = ScheduleConfig(
        chat_id=chat_id,
        source=source,
        send_weekday=weekday,
        send_time=send_time,
        pin_message=SCHEDULE_PIN_WEEKLY,
    )
    logger.info(
        'Щотижневий розклад увімкнено: чат=%s, день=%s час=%s:%s pin=%s',
        chat_id,
        weekday,
        f'{SCHEDULE_SEND_HOUR:02d}',
        f'{SCHEDULE_SEND_MINUTE:02d}',
        SCHEDULE_PIN_WEEKLY,
    )
    return SchedulePublisher(sender, config)


def build_daily_reminder(sender: TelegramSender) -> DailyReminder | None:
    """Створює щоденне нагадування про завтрашню зміну."""
    if not SCHEDULE_DAILY_REMINDER_ENABLED:
        logger.info('Щоденне нагадування вимкнено через SCHEDULE_DAILY_REMINDER_ENABLED')
        return None
    target_chat: str | None = SCHEDULE_DAILY_REMINDER_CHAT_ID
    if not target_chat:
        logger.warning('SCHEDULE_DAILY_REMINDER_CHAT_ID не налаштовано, пропускаю нагадування')
        return None
    source = _build_exchange_source()
    if source is None:
        return None

    chat_id: int | str
    try:
        chat_id = int(target_chat)
    except (ValueError, TypeError):
        chat_id = target_chat

    send_time = time(hour=SCHEDULE_DAILY_REMINDER_HOUR, minute=SCHEDULE_DAILY_REMINDER_MINUTE)
    config = ReminderConfig(chat_id=chat_id, source=source, send_time=send_time)
    logger.info(
        'Щоденне нагадування увімкнено: чат=%s час=%s:%s',
        chat_id,
        f'{SCHEDULE_DAILY_REMINDER_HOUR:02d}',
        f'{SCHEDULE_DAILY_REMINDER_MINUTE:02d}',
    )
    return DailyReminder(sender, config)


def _build_exchange_source() -> ExchangeSourceConfig | None:
    if not (SCHEDULE_EXCHANGE_EMAIL and SCHEDULE_EXCHANGE_PASSWORD):
        logger.warning('Необхідні облікові дані Exchange відсутні, розклад недоступний')
        return None
    username: str = SCHEDULE_EXCHANGE_USERNAME or SCHEDULE_EXCHANGE_EMAIL
    return ExchangeSourceConfig(
        email=SCHEDULE_EXCHANGE_EMAIL,
        username=username,
        password=SCHEDULE_EXCHANGE_PASSWORD,
        server=SCHEDULE_EXCHANGE_SERVER,
        calendar_name=SCHEDULE_CALENDAR_NAME,
        timezone=SCHEDULE_TIMEZONE,
    )
