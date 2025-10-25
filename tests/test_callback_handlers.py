"""Перевіряє обробку callback'ів прийняття задачі."""

from __future__ import annotations

from typing import Any

import pytest

import agromat_it_desk_bot.callback_handlers as handlers


def test_handle_accept_assigns_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Авторизований користувач має призначати задачу та отримувати підтвердження."""
    payloads: list[dict[str, Any]] = []

    monkeypatch.setattr(handlers, 'assign_issue', lambda *_: True)
    monkeypatch.setattr(handlers, 'get_authorized_yt_user', lambda _tg_user_id: ('login', 'mail', 'YT-1'))

    def fake_call_api(method: str, payload: dict[str, Any]) -> None:
        payloads.append({'method': method, 'payload': payload})

    monkeypatch.setattr(handlers, 'call_api', fake_call_api)
    monkeypatch.setattr(handlers, 'remove_keyboard', lambda *_: None)

    context = handlers.CallbackContext('cb-1', 200, 300, 'accept|SUP-1', 555)
    handlers.handle_accept('SUP-1', context)

    answers = [entry for entry in payloads if entry['method'] == 'answerCallbackQuery']
    assert answers, 'Очікував відповідь answerCallbackQuery'
    assert any(payload['payload'].get('text') == 'Прийнято ✅' for payload in answers)


def test_handle_accept_fails_for_unknown_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """Якщо користувача не знайдено, бот показує помилку."""
    captured: list[dict[str, Any]] = []

    monkeypatch.setattr(handlers, 'assign_issue', lambda *_: True)
    monkeypatch.setattr(handlers, 'get_authorized_yt_user', lambda _tg_user_id: (None, None, None))

    def fake_call_api(method: str, payload: dict[str, Any]) -> None:
        captured.append({'method': method, 'payload': payload})

    monkeypatch.setattr(handlers, 'call_api', fake_call_api)

    context = handlers.CallbackContext('cb-2', 201, 301, 'accept|SUP-2', 556)
    handlers.handle_accept('SUP-2', context)

    errors = [entry for entry in captured if entry['method'] == 'answerCallbackQuery']
    assert errors, 'Очікував повідомлення про помилку'
    assert any(entry['payload'].get('text') == 'Помилка: не вдалось прийняти' for entry in errors)
