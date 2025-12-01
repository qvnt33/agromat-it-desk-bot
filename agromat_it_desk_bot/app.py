"""Creates and configures the FastAPI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from fastapi import FastAPI

from agromat_it_desk_bot.alerts.archiver import IssueArchiverWorker
from agromat_it_desk_bot.alerts.new_status import build_new_status_alert_worker
from agromat_it_desk_bot.api.telegram import router as telegram_router
from agromat_it_desk_bot.api.youtrack import router as youtrack_router
from agromat_it_desk_bot.config import BOT_TOKEN
from agromat_it_desk_bot.schedule import (
    DailyReminder,
    SchedulePublisher,
    build_daily_reminder,
    build_schedule_publisher,
)
from agromat_it_desk_bot.telegram import telegram_aiogram, telegram_commands
from agromat_it_desk_bot.telegram.telegram_sender import AiogramTelegramSender
from agromat_it_desk_bot.utils import configure_logging

logger: logging.Logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Builds FastAPI app with routers and lifespan attached."""
    configure_logging()
    app = FastAPI(lifespan=_lifespan)
    app.include_router(youtrack_router)
    app.include_router(telegram_router)
    return app


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown of the FastAPI application."""
    if not BOT_TOKEN:
        raise RuntimeError('BOT_TOKEN не налаштовано')

    bot: Bot = Bot(token=BOT_TOKEN)
    dispatcher: Dispatcher = Dispatcher()
    sender = AiogramTelegramSender(bot)
    telegram_commands.configure_sender(sender)
    telegram_aiogram.configure(bot, dispatcher)
    schedule_publisher: SchedulePublisher | None = build_schedule_publisher(sender)
    if schedule_publisher is not None:
        schedule_publisher.start()
    daily_reminder: DailyReminder | None = build_daily_reminder(sender)
    if daily_reminder is not None:
        daily_reminder.start()
    status_alert_worker = build_new_status_alert_worker(sender)
    if status_alert_worker is not None:
        status_alert_worker.start()
    issue_archiver = IssueArchiverWorker(sender)
    issue_archiver.start()

    try:
        yield
    finally:
        if issue_archiver is not None:
            await issue_archiver.stop()
        if status_alert_worker is not None:
            await status_alert_worker.stop()
        if daily_reminder is not None:
            await daily_reminder.stop()
        if schedule_publisher is not None:
            await schedule_publisher.stop()
        await telegram_aiogram.shutdown()
