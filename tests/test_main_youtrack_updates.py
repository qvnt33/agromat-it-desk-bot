"""Перевіряє оновлення Telegram-повідомлення після змін у YouTrack."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import Request

from agromat_it_desk_bot import main
from tests.conftest import FakeTelegramSender


class _StubRequest:
    """Мінімальний запит FastAPI для тестування webhook."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.headers: dict[str, str] = {}

    async def json(self) -> dict[str, object]:
        return self._payload


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

    second_request = _StubRequest(_issue_payload('Closed', 'New User'))
    await main.youtrack_update(cast(Request, second_request))

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
