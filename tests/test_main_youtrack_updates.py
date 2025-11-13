"""Перевіряє оновлення Telegram-повідомлення після змін у YouTrack."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods.base import TelegramMethod
from fastapi import Request

import agromat_it_desk_bot.config as config
from agromat_it_desk_bot import main
from agromat_it_desk_bot.messages import Msg, render
from tests.conftest import FakeTelegramSender


class _StubRequest:
    """Мінімальний запит FastAPI для тестування webhook."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.headers: dict[str, str] = {}

    async def json(self) -> dict[str, object]:
        return self._payload


class _DummyMethod(TelegramMethod[bool]):
    """Мінімальна реалізація Telegram методу для створення помилок."""

    __returning__ = bool
    __api_method__ = 'editMessageText'


def _issue_payload(status: str, assignee: str) -> dict[str, object]:
    """Формує тестовий payload вебхука YouTrack."""
    return {
        'idReadable': 'SUP-1',
        'summary': 'Заявка тестова',
        'description': '<div dir="ltr">Опис заявки<div><br></div></div>',
        'author': 'Reporter',
        'status': status,
        'assignee': assignee,
        'url': 'https://yt.example/issue/SUP-1',
    }


@pytest.mark.asyncio
async def test_youtrack_webhook_updates_existing_message(
    monkeypatch: pytest.MonkeyPatch,
    fake_sender: FakeTelegramSender,
) -> None:
    """Повторний вебхук змінює текст існуючого повідомлення."""
    assert hasattr(fake_sender, 'sent_messages')
    monkeypatch.setattr(main, 'YT_WEBHOOK_SECRET', None, raising=False)
    monkeypatch.setattr(main, '_TELEGRAM_CHAT_ID_RESOLVED', 777_001, raising=False)

    first_request = _StubRequest(_issue_payload('Open', '[не призначено]'))
    await main.youtrack_webhook(cast(Request, first_request))

    assert len(fake_sender.sent_messages) == 1
    message = fake_sender.sent_messages[0]
    assert 'Open' in str(message['text'])
    assert message['reply_markup'] is not None

    monkeypatch.setattr(
        main,
        'fetch_issue_details',
        lambda _issue_id: SimpleNamespace(
            summary='Заявка тестова',
            description='Опис заявки',
            assignee='New User',
            status='Closed',
            author='Reporter',
        ),
        raising=False,
    )
    partial_payload: dict[str, object] = {'idReadable': 'SUP-1', 'changes': ['summary', 'State']}
    await main.youtrack_update(cast(Request, _StubRequest(partial_payload)))

    assert len(fake_sender.sent_messages) == 1, 'Очікували редагування без нового повідомлення'
    assert fake_sender.edited_text, 'Повідомлення має бути оновлене'
    edited_payload = fake_sender.edited_text[-1]
    assert 'Closed' in str(edited_payload['text'])
    assert 'New User' in str(edited_payload['text'])
    assert edited_payload['reply_markup'] is None


def _custom_fields_payload(status: str, assignee: str) -> dict[str, object]:
    """Формує payload, де значення містяться лише у customFields."""
    return {
        'idReadable': 'SUP-2',
        'summary': 'Заявка з кастомними полями',
        'description': 'Опис заявки',
        'url': 'https://yt.example/issue/SUP-2',
        'customFields': [
            {
                'name': 'Статус',
                'value': {'name': status},
            },
            {
                'name': 'Виконавець',
                'value': {'fullName': assignee},
            },
        ],
    }


@pytest.mark.asyncio
async def test_youtrack_webhook_reads_custom_fields(
    monkeypatch: pytest.MonkeyPatch,
    fake_sender: FakeTelegramSender,
) -> None:
    """Якщо статус і виконавець надходять лише з customFields, повідомлення підставляє їх."""
    monkeypatch.setattr(main, 'YT_WEBHOOK_SECRET', None, raising=False)
    monkeypatch.setattr(main, '_TELEGRAM_CHAT_ID_RESOLVED', 777_001, raising=False)

    request = _StubRequest(_custom_fields_payload('In Progress', 'Agent Smith'))
    await main.youtrack_webhook(cast(Request, request))

    assert len(fake_sender.sent_messages) == 1
    message = fake_sender.sent_messages[0]
    assert 'In Progress' in str(message['text'])
    assert 'Agent Smith' in str(message['text'])


@pytest.mark.asyncio
async def test_youtrack_update_ignores_not_modified_error(
    monkeypatch: pytest.MonkeyPatch,
    fake_sender: FakeTelegramSender,
) -> None:
    """Якщо Telegram повертає 'message is not modified', вебхук завершується успіхом."""
    monkeypatch.setattr(main, 'YT_WEBHOOK_SECRET', None, raising=False)
    monkeypatch.setattr(main, '_TELEGRAM_CHAT_ID_RESOLVED', 777_001, raising=False)

    first_request = _StubRequest(_issue_payload('Open', '[не призначено]'))
    await main.youtrack_webhook(cast(Request, first_request))

    fake_sender.raise_on_edit = [
        TelegramBadRequest(method=_DummyMethod(), message='Bad Request: message is not modified'),
        TelegramBadRequest(method=_DummyMethod(), message='Bad Request: message is not modified'),
    ]

    # REST повертає ті самі дані, тому повторне редагування не потрібне
    refresh_calls: list[str] = []

    def _details_stub(issue_id: str) -> SimpleNamespace:
        refresh_calls.append(issue_id)
        return SimpleNamespace(
            summary='Заявка тестова',
            description='Опис заявки',
            assignee='[не призначено]',
            status='Open',
            author='Reporter',
        )

    monkeypatch.setattr(main, 'fetch_issue_details', _details_stub, raising=False)
    payload: dict[str, object] = {'idReadable': 'SUP-1', 'changes': ['status']}
    response = await main.youtrack_update(cast(Request, _StubRequest(payload)))

    assert response == {'ok': True}
    assert not fake_sender.edited_text, 'Не очікували фактичних оновлень повідомлення'
    assert refresh_calls, 'Очікували звернення до REST'


@pytest.mark.asyncio
async def test_youtrack_update_retries_with_rest_data(
    monkeypatch: pytest.MonkeyPatch,
    fake_sender: FakeTelegramSender,
) -> None:
    """Якщо REST повертає нові дані, повторна спроба має оновити повідомлення."""
    monkeypatch.setattr(main, 'YT_WEBHOOK_SECRET', None, raising=False)
    monkeypatch.setattr(main, '_TELEGRAM_CHAT_ID_RESOLVED', 777_001, raising=False)

    first_request = _StubRequest(_issue_payload('Open', '[не призначено]'))
    await main.youtrack_webhook(cast(Request, first_request))

    fake_sender.raise_on_edit = [
        TelegramBadRequest(method=_DummyMethod(), message='Bad Request: message is not modified'),
    ]
    monkeypatch.setattr(
        main,
        'fetch_issue_details',
        lambda _issue_id: SimpleNamespace(
            summary='Заявка тестова',
            description='Опис заявки',
            assignee='New User',
            status='Closed',
            author='Reporter',
        ),
        raising=False,
    )
    payload: dict[str, object] = {'idReadable': 'SUP-1', 'changes': ['status']}
    response = await main.youtrack_update(cast(Request, _StubRequest(payload)))

    assert response == {'ok': True}
    assert fake_sender.edited_text, 'Очікували повторного редагування'
    edited_payload = fake_sender.edited_text[-1]
    assert 'Closed' in str(edited_payload['text'])
    assert 'New User' in str(edited_payload['text'])


@pytest.mark.asyncio
async def test_youtrack_update_archives_message_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
    fake_sender: FakeTelegramSender,
) -> None:
    """Після 48 годин бот не редагує повідомлення, а публікує архівний варіант."""
    monkeypatch.setattr(main, 'YT_WEBHOOK_SECRET', None, raising=False)
    monkeypatch.setattr(main, '_TELEGRAM_CHAT_ID_RESOLVED', 777_001, raising=False)

    first_request = _StubRequest(_issue_payload('Open', '[не призначено]'))
    await main.youtrack_webhook(cast(Request, first_request))

    archived_timestamp: str = (datetime.now(tz=timezone.utc) - timedelta(hours=49)).isoformat()
    with sqlite3.connect(str(config.DATABASE_PATH)) as connection:
        connection.execute(
            'UPDATE issue_messages SET updated_at = ? WHERE issue_id = ?',
            (archived_timestamp, 'SUP-1'),
        )
        connection.commit()

    payload: dict[str, object] = {
        'idReadable': 'SUP-1',
        'summary': 'Заявка тестова',
        'description': 'Оновлений опис',
        'status': 'Closed',
        'assignee': 'Agent Smith',
        'author': 'Reporter',
        'changes': ['status'],
    }
    response = await main.youtrack_update(cast(Request, _StubRequest(payload)))

    assert response == {'ok': True}
    assert len(fake_sender.sent_messages) == 1, 'Не очікували нових повідомлень'
    assert not fake_sender.edited_text, 'Редагувань бути не повинно'


@pytest.mark.asyncio
async def test_youtrack_webhook_triggers_summary_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Порожня тема має замінюватися у YouTrack через ensure_summary_placeholder."""
    monkeypatch.setattr(main, 'YT_WEBHOOK_SECRET', None, raising=False)
    monkeypatch.setattr(main, '_TELEGRAM_CHAT_ID_RESOLVED', 777_001, raising=False)

    placeholder_calls: list[tuple[str, str, str | None]] = []

    def fake_ensure(issue_id: str, summary: str, internal_id: str | None = None) -> None:
        placeholder_calls.append((issue_id, summary, internal_id))

    monkeypatch.setattr(main, 'ensure_summary_placeholder', fake_ensure, raising=False)

    payload: dict[str, object] = {
        'idReadable': 'SUP-EMAIL',
        'summary': 'Проблема з електронним листом від someone',
        'description': '<div>HTML</div>',
        'url': 'https://yt.example/issue/SUP-EMAIL',
        'author': 'Reporter',
        'status': 'Нова',
        'assignee': '',
    }
    await main.youtrack_webhook(cast(Request, _StubRequest(payload)))

    assert placeholder_calls
    issue_id, summary, internal_id = placeholder_calls[-1]
    assert issue_id == 'SUP-EMAIL'
    assert summary == render(Msg.YT_EMAIL_SUBJECT_MISSING)
    assert internal_id is None
