"""Перевіряє санітизацію payload для логування вебхуків YouTrack."""

from __future__ import annotations

from agromat_it_desk_bot import main
from agromat_it_desk_bot.messages import Msg, render


def test_prepare_payload_for_logging_sanitizes_email_description() -> None:
    """Санітизація має вилучати службові атрибути з HTML, згенерованого поштою."""
    raw_description: str = (
        '<div dir="ltr">\n'
        '<p style="margin:0px;color:#000"><span class="gmail">Добрий день!</span></p>\n'
        '<p style="margin:8px;color:#000"><span class="gmail">Не сканує сканер.</span></p>\n'
        '<p style="margin:8px;color:#000"><span><img width="965" height="768" src="https://example.com/'
        'file" /></span></p>\n'
        '</div>'
    )
    payload: dict[str, object] = {'description': raw_description}

    sanitized = main._prepare_payload_for_logging(payload)

    assert sanitized is not payload
    sanitized_description = sanitized['description']
    assert isinstance(sanitized_description, str)
    assert 'style=' not in sanitized_description
    assert 'class=' not in sanitized_description
    assert 'gmail' not in sanitized_description
    assert '<img' not in sanitized_description
    assert '<p>\n</p>' not in sanitized_description
    assert 'Добрий день!' in sanitized_description
    assert payload['description'] == raw_description


def test_prepare_payload_for_logging_skips_non_email_description() -> None:
    """Опис без поштових маркерів лишається без змін."""
    description: str = '<p>Стандартний опис</p>'
    payload: dict[str, object] = {'description': description}

    sanitized = main._prepare_payload_for_logging(payload)

    assert sanitized['description'] == description
    assert payload['description'] == description


def test_prepare_payload_for_logging_sanitizes_nested_issue() -> None:
    """Санітизація має відбуватися і для вкладеного об'єкта issue."""
    nested_description: str = '<div class="gmail"><p style="color:red">Контент</p></div>'
    payload: dict[str, object] = {'issue': {'description': nested_description}}

    sanitized = main._prepare_payload_for_logging(payload)

    nested = sanitized['issue']
    assert isinstance(nested, dict)
    sanitized_description = nested['description']
    assert isinstance(sanitized_description, str)
    assert 'style=' not in sanitized_description
    assert 'class=' not in sanitized_description
    assert '<img' not in sanitized_description
    assert 'Контент' in sanitized_description


def test_prepare_issue_payload_substitutes_empty_summary() -> None:
    """Порожній summary має замінюватись службовим повідомленням."""
    issue: dict[str, object] = {
        'idReadable': 'ID-1',
        'summary': '',
        'description': 'text',
        'status': 'Нова',
        'assignee': '',
        'author': '',
        'url': 'https://example.com/ID-1',
    }

    _, summary, *_ = main._prepare_issue_payload(issue)

    assert summary == render(Msg.YT_EMAIL_SUBJECT_MISSING)


def test_prepare_issue_payload_substitutes_email_generated_summary() -> None:
    """Summary з шаблону YouTrack про email має замінюватись службовим повідомленням."""
    issue: dict[str, object] = {
        'idReadable': 'ID-2',
        'summary': 'Проблема з електронним листом від name_2_u',
        'description': 'text',
        'status': 'Нова',
        'assignee': '',
        'author': '',
        'url': 'https://example.com/ID-2',
    }

    _, summary, *_ = main._prepare_issue_payload(issue)

    assert summary == render(Msg.YT_EMAIL_SUBJECT_MISSING)


def test_prepare_issue_payload_keeps_regular_summary() -> None:
    """Звичайний summary залишається без змін."""
    issue: dict[str, object] = {
        'idReadable': 'ID-3',
        'summary': 'Несправний сканер',
        'description': 'text',
        'status': 'Нова',
        'assignee': '',
        'author': '',
        'url': 'https://example.com/ID-3',
    }

    _, summary, *_ = main._prepare_issue_payload(issue)

    assert summary == 'Несправний сканер'


def test_prepare_payload_for_logging_normalizes_summary() -> None:
    """Sanitizer має підміняти службовий summary для логів."""
    payload: dict[str, object] = {
        'summary': 'Проблема з електронним листом від name',
        'issue': {'summary': 'Проблема з електронним листом від name'},
    }

    sanitized = main._prepare_payload_for_logging(payload)

    assert sanitized['summary'] == render(Msg.YT_EMAIL_SUBJECT_MISSING)
    issue = sanitized['issue']
    assert isinstance(issue, dict)
    assert issue['summary'] == render(Msg.YT_EMAIL_SUBJECT_MISSING)
