"""Перевіряє нагадування для заявок у статусі ``Нова``."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import agromat_it_desk_bot.config as config
from agromat_it_desk_bot.alerts import new_status
from agromat_it_desk_bot.storage import fetch_due_issue_alerts
from tests.conftest import FakeTelegramSender


@pytest.mark.asyncio
async def test_schedule_new_status_alerts_persists_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """Для статусу ``Нова`` мають створюватися записи у БД."""
    step = config.StatusAlertStep(index=1, minutes=1, message='Alert текст')
    monkeypatch.setattr(new_status, '_ALERT_ENABLED', True, raising=False)
    monkeypatch.setattr(new_status, '_ALERT_TARGET', 'нова', raising=False)
    monkeypatch.setattr(new_status, '_ALERT_STEPS', (step,), raising=False)
    monkeypatch.setattr(new_status, '_ALERT_MESSAGES', {1: step.message}, raising=False)

    await new_status.schedule_new_status_alerts('SUP-42', 'Нова', 123_456, 777)

    future = (datetime.now(tz=timezone.utc) + timedelta(minutes=2)).isoformat()
    records = await asyncio.to_thread(fetch_due_issue_alerts, 5, future)

    assert records, 'Очікували бодай одне нагадування'
    record = records[0]
    assert record['issue_id'] == 'SUP-42'
    assert record['alert_index'] == 1
    assert record['message_id'] == 777


@pytest.mark.asyncio
async def test_alert_worker_sends_reply(monkeypatch: pytest.MonkeyPatch, fake_sender: FakeTelegramSender) -> None:
    """Воркери мають відповідати на вихідне повідомлення заявки."""
    step = config.StatusAlertStep(index=1, minutes=0, message='Рядок 1<br>Рядок 2')
    monkeypatch.setattr(new_status, '_ALERT_ENABLED', True, raising=False)
    monkeypatch.setattr(new_status, '_ALERT_TARGET', 'нова', raising=False)
    monkeypatch.setattr(new_status, '_ALERT_STEPS', (step,), raising=False)
    monkeypatch.setattr(new_status, '_ALERT_MESSAGES', {1: step.message}, raising=False)

    await new_status.schedule_new_status_alerts('SUP-99', 'Нова', 555_001, 901)

    worker = new_status.NewStatusAlertWorker(fake_sender, poll_seconds=0.05, batch_limit=5)
    worker.start()
    await asyncio.sleep(0.1)
    await worker.stop()

    assert fake_sender.sent_messages, 'Очікували надсилання бодай одного нагадування'
    payload = fake_sender.sent_messages[-1]
    assert payload['reply_to_message_id'] == 901
    assert payload['text'] == 'Рядок 1\nРядок 2'
