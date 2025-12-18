"""Manage reminders for issues staying long in ``New`` status."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from agromat_help_desk_bot.config import (
    NEW_STATUS_ALERT_ENABLED,
    NEW_STATUS_ALERT_POLL_SECONDS,
    NEW_STATUS_ALERT_STATE_NAME,
    NEW_STATUS_ALERT_STEPS,
    NEW_STATUS_ALERT_SUFFIX_DEFAULT,
)
from agromat_help_desk_bot.storage import (
    clear_issue_alerts,
    fetch_alert_suffix,
    fetch_due_issue_alerts,
    mark_issue_alert_sent,
    upsert_issue_alerts,
)
from agromat_help_desk_bot.telegram.telegram_sender import TelegramSender, escape_html

logger: logging.Logger = logging.getLogger(__name__)

_ALERT_TARGET: str = NEW_STATUS_ALERT_STATE_NAME.casefold()
_ALERT_STEPS = NEW_STATUS_ALERT_STEPS
_ALERT_BASE_MESSAGES = {step.index: step.message for step in _ALERT_STEPS}
_ALERT_ENABLED: bool = NEW_STATUS_ALERT_ENABLED and bool(_ALERT_STEPS)
_POLL_SECONDS: float = max(float(NEW_STATUS_ALERT_POLL_SECONDS), 30.0)
_BATCH_LIMIT: int = 20
_SUFFIX_POSITIONS: tuple[int, ...] = (2, 3)
_ALERT_MESSAGES = _ALERT_BASE_MESSAGES


def _is_target_status(status: str | None) -> bool:
    return bool(status and status.strip().casefold() == _ALERT_TARGET)


async def _compose_alert_message(alert_index: int) -> str | None:
    base_messages: dict[int, str] = globals().get('_ALERT_MESSAGES', _ALERT_BASE_MESSAGES)  # allow tests to patch
    base_message: str | None = base_messages.get(alert_index)
    if base_message is None:
        return None
    try:
        suffix: str = await asyncio.to_thread(fetch_alert_suffix, NEW_STATUS_ALERT_SUFFIX_DEFAULT)
    except Exception:
        suffix = NEW_STATUS_ALERT_SUFFIX_DEFAULT
    if suffix and alert_index in _SUFFIX_POSITIONS:
        normalized_suffix: str = suffix.strip()
        if not normalized_suffix:
            return base_message
        trimmed_suffix: str = normalized_suffix.removeprefix('<br><br>')
        safe_suffix: str = escape_html(trimmed_suffix)
        return f'{base_message}<br><br>{safe_suffix}'
    return base_message


async def schedule_new_status_alerts(
    issue_id: str,
    status: str | None,
    chat_id: int | str,
    message_id: int,
) -> None:
    """Create scheduled alerts if issue is in ``New`` status."""
    if not _ALERT_ENABLED:
        return
    if not issue_id or not _is_target_status(status):
        return
    now = datetime.now(tz=timezone.utc)
    alerts: list[tuple[int, str]] = []
    for step in _ALERT_STEPS:
        send_after = (now + timedelta(minutes=step.minutes)).isoformat()
        alerts.append((step.index, send_after))
    if not alerts:
        return
    await asyncio.to_thread(upsert_issue_alerts, issue_id, chat_id, message_id, tuple(alerts))


async def cancel_new_status_alerts(issue_id: str, status: str | None) -> None:
    """Cancel alerts if status differs from ``New``."""
    if not _ALERT_ENABLED or not issue_id or status is None:
        return
    if _is_target_status(status):
        return
    await asyncio.to_thread(clear_issue_alerts, issue_id)


def build_new_status_alert_worker(sender: TelegramSender) -> NewStatusAlertWorker | None:
    """Return worker for sending alerts if enabled."""
    if not _ALERT_ENABLED:
        return None
    return NewStatusAlertWorker(sender)


class NewStatusAlertWorker:
    """Periodically check and send reminders about ``New`` status."""

    def __init__(
        self,
        sender: TelegramSender,
        *,
        poll_seconds: float | None = None,
        batch_limit: int = _BATCH_LIMIT,
    ) -> None:
        self._sender = sender
        self._poll_seconds: float = poll_seconds or _POLL_SECONDS
        self._batch_limit: int = batch_limit
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            await self._process_due_alerts()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                continue

    async def _process_due_alerts(self) -> None:
        now = datetime.now(tz=timezone.utc)
        alerts = await asyncio.to_thread(
            fetch_due_issue_alerts,
            self._batch_limit,
            now.isoformat(),
        )
        if not alerts:
            return
        for record in alerts:
            await self._send_alert(record['issue_id'], record['alert_index'], record['chat_id'], record['message_id'])

    async def _send_alert(self, issue_id: str, alert_index: int, chat_id_raw: str, message_id: int) -> None:
        message_template: str | None = await _compose_alert_message(alert_index)
        if not message_template:
            await asyncio.to_thread(mark_issue_alert_sent, issue_id, alert_index)
            return
        sanitized_text: str = _sanitize_alert_text(message_template)
        chat_id: int | str = _resolve_chat_id(chat_id_raw)
        try:
            await self._sender.send_message(
                chat_id,
                sanitized_text,
                reply_to_message_id=message_id,
                disable_web_page_preview=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning('Не вдалося надіслати нагадування для %s (ступінь %s): %s', issue_id, alert_index, exc)
            return
        logger.info('Нагадування для задачі %s (ступінь %s) надіслано', issue_id, alert_index)
        await asyncio.to_thread(mark_issue_alert_sent, issue_id, alert_index)


def _resolve_chat_id(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _sanitize_alert_text(text: str) -> str:
    """Replace `br` with newline to support parse_mode=HTML."""
    return text.replace('<br/>', '\n').replace('<br>', '\n')


__all__ = [
    'NewStatusAlertWorker',
    'build_new_status_alert_worker',
    'cancel_new_status_alerts',
    'schedule_new_status_alerts',
]
