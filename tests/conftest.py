"""Загальні фікстури для тестів авторизації."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import agromat_it_desk_bot.auth.service as auth_service
import agromat_it_desk_bot.config as config
import agromat_it_desk_bot.storage.database as db
import agromat_it_desk_bot.telegram.telegram_commands as telegram_commands
from agromat_it_desk_bot.telegram.telegram_sender import TelegramSender


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Направляє всі операції з БД у тимчасовий файл.

    Забезпечує, що тести не торкаються робочого середовища користувача.
    """
    db_path: Path = tmp_path / 'bot.sqlite3'
    monkeypatch.setattr(config, 'DATABASE_PATH', db_path, raising=False)
    monkeypatch.setattr(db, 'DATABASE_PATH', db_path, raising=False)
    monkeypatch.setattr(auth_service, '_migrated', False, raising=False)
    yield


class FakeTelegramSender(TelegramSender):
    """Фіктивний відправник, що накопичує всі виклики."""

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.deleted_messages: list[dict[str, object]] = []
        self.callback_answers: list[dict[str, object]] = []
        self.edited_markup: list[dict[str, object]] = []

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = 'HTML',
        reply_markup: dict[str, object] | None = None,
        disable_web_page_preview: bool = True,
    ) -> None:
        self.sent_messages.append({
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'reply_markup': reply_markup,
            'disable_web_page_preview': disable_web_page_preview,
        })

    async def delete_message(self, chat_id: int | str, message_id: int) -> None:
        self.deleted_messages.append({'chat_id': chat_id, 'message_id': message_id})

    async def answer_callback(
        self,
        callback_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        self.callback_answers.append({'callback_id': callback_id, 'text': text, 'show_alert': show_alert})

    async def edit_reply_markup(
        self,
        chat_id: int | str,
        message_id: int,
        reply_markup: dict[str, object] | None,
    ) -> None:
        self.edited_markup.append({'chat_id': chat_id, 'message_id': message_id, 'reply_markup': reply_markup})


@pytest.fixture(autouse=True)
def fake_sender() -> FakeTelegramSender:
    """Надає тестовий TelegramSender для всіх тестів."""
    sender = FakeTelegramSender()
    telegram_commands.configure_sender(sender)
    return sender
