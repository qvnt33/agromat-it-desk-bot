"""Periodically archives inactive issues in Telegram."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from agromat_it_desk_bot.config import (
    ARCHIVE_IDLE_THRESHOLD_SECONDS,
    ARCHIVE_SCAN_INTERVAL_SECONDS,
    YT_BASE_URL,
)
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.storage import fetch_stale_issue_messages, mark_issue_archived
from agromat_it_desk_bot.telegram.telegram_sender import TelegramSender
from agromat_it_desk_bot.utils import format_telegram_message, normalize_issue_summary, strip_html
from agromat_it_desk_bot.youtrack.youtrack_service import fetch_issue_details

logger: logging.Logger = logging.getLogger(__name__)


class IssueArchiverWorker:
    """Find messages that should be marked as archived."""

    def __init__(self, sender: TelegramSender) -> None:
        self._sender = sender
        self._interval: float = float(ARCHIVE_SCAN_INTERVAL_SECONDS)
        self._idle_delta: timedelta = timedelta(seconds=ARCHIVE_IDLE_THRESHOLD_SECONDS)
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
            await self._process_batch()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue

    async def _process_batch(self) -> None:
        cutoff = datetime.now(tz=timezone.utc) - self._idle_delta
        records = await asyncio.to_thread(fetch_stale_issue_messages, cutoff.isoformat())
        if not records:
            return
        for record in records:
            await self._archive_issue(record['issue_id'], record['chat_id'], record['message_id'])

    async def _archive_issue(self, issue_id: str, chat_id_raw: str, message_id: int) -> None:
        details = await asyncio.to_thread(fetch_issue_details, issue_id)
        if details is None:
            logger.warning('Не вдалося отримати деталі задачі %s для архівації', issue_id)
            return
        summary = normalize_issue_summary(details.summary)
        description = strip_html(details.description or '')
        status = render(Msg.STATUS_ARCHIVED)
        message = format_telegram_message(
            issue_id,
            summary,
            description,
            _build_issue_url(issue_id),
            assignee=details.assignee,
            status=status,
            author=details.author,
        )
        chat_id: int | str = _resolve_chat_id(chat_id_raw)
        try:
            await self._sender.edit_message_text(
                chat_id,
                message_id,
                message,
                parse_mode='HTML',
                reply_markup=None,
                disable_web_page_preview=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning('Не вдалося оновити повідомлення задачі %s під час архівації: %s', issue_id, exc)
            return
        await asyncio.to_thread(mark_issue_archived, issue_id)
        logger.info('Задачу %s позначено як Архівовано через неактивність', issue_id)


def _resolve_chat_id(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _build_issue_url(issue_id: str) -> str:
    if YT_BASE_URL and issue_id and issue_id != render(Msg.YT_ISSUE_NO_ID):
        return f'{YT_BASE_URL}/issue/{issue_id}'
    return render(Msg.ERR_YT_ISSUE_NO_URL)


__all__ = ['IssueArchiverWorker']
