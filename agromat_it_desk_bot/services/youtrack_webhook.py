"""Contains helper logic for processing YouTrack webhooks."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from agromat_it_desk_bot.config import YT_BASE_URL
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.utils import (
    extract_issue_assignee,
    extract_issue_author,
    extract_issue_id,
    extract_issue_status,
    format_telegram_message,
    get_str,
    normalize_issue_summary,
    strip_html,
)

_EMAIL_HTML_MARKERS: tuple[str, ...] = (
    'gmail',
    'cid:',
    'scrollbar-width',
    'object-fit',
    'border-image',
)
_ATTR_STYLE_DOUBLE_RE = re.compile(r'\sstyle="[^"]*"', re.IGNORECASE)
_ATTR_STYLE_SINGLE_RE = re.compile(r"\sstyle='[^']*'", re.IGNORECASE)
_ATTR_CLASS_RE = re.compile(r"\sclass=([\"']).*?\1", re.IGNORECASE)
_ATTR_DIR_RE = re.compile(r"\sdir=([\"']).*?\1", re.IGNORECASE)
_ATTR_MISC_PREFIX_RE = re.compile(
    r"\s(?:data|aria|background|color|lang|width|height|align|valign|border|cellpadding|cellspacing)[^=]*=([\"']).*?\1",
    re.IGNORECASE,
)
_SPAN_TAG_RE = re.compile(r'</?span\b[^>]*>', re.IGNORECASE)
_FONT_TAG_RE = re.compile(r'</?font\b[^>]*>', re.IGNORECASE)
_WHITESPACE_TAGS_RE = re.compile(r'>\s+<')
_MULTISPACE_RE = re.compile(r'[ \t]{2,}')
_IMG_TAG_RE = re.compile(r'<img\b[^>]*?>', re.IGNORECASE)
_EMPTY_PARAGRAPH_RE = re.compile(r'<p>\s*</p>', re.IGNORECASE)
_TELEGRAM_EDIT_TTL: timedelta = timedelta(hours=48)


def prepare_issue_payload(  # noqa: C901
    issue: dict[str, object],
) -> tuple[str, str, str, str, str | None, str | None, str | None]:
    """Return issue data used to build Telegram message."""
    issue_id: str = extract_issue_id(issue)
    summary: str = normalize_issue_summary(get_str(issue, 'summary'))
    description: str = strip_html(get_str(issue, 'description'))

    author_raw: str = get_str(issue, 'author')
    if not author_raw:
        reporter_obj = issue.get('reporter')
        if isinstance(reporter_obj, dict):
            extracted_author: str = str(
                reporter_obj.get('fullName')
                or reporter_obj.get('login')
                or reporter_obj.get('name')
                or '',
            )
            author_raw = extracted_author

    status_raw: str = get_str(issue, 'status')
    assignee_label: str = get_str(issue, 'assignee') or render(Msg.NOT_ASSIGNED)

    custom_fields_obj: object | None = issue.get('customFields')
    if (not status_raw or assignee_label == render(Msg.YT_ISSUE_NO_ID)) and isinstance(custom_fields_obj, list):
        for field in custom_fields_obj:
            if not isinstance(field, dict):
                continue
            name_value: object | None = field.get('name')
            name_lower: str | None = str(name_value) if isinstance(name_value, str) else None
            if name_lower in {'статус', 'state'} and not status_raw:
                field_value = field.get('value')
                if isinstance(field_value, dict):
                    status_candidate: object | None = field_value.get('name')
                    if isinstance(status_candidate, str) and status_candidate:
                        status_raw = status_candidate
            if (
                name_lower in {'assignee', 'assignees', 'виконавець', 'виконавці'}
                and assignee_label == render(Msg.NOT_ASSIGNED)
            ):
                field_value = field.get('value')
                names: list[str] = []
                if isinstance(field_value, dict):
                    extracted = field_value.get('fullName') or field_value.get('login') or field_value.get('name')
                    if isinstance(extracted, str) and extracted:
                        names = [extracted]
                elif isinstance(field_value, list):
                    for candidate in field_value:
                        if isinstance(candidate, dict):
                            val = candidate.get('fullName') or candidate.get('login') or candidate.get('name')
                            if isinstance(val, str) and val:
                                names.append(val)
                if names:
                    assignee_label = ', '.join(names)

    issue_id_unknown_msg: str = render(Msg.YT_ISSUE_NO_ID)
    url_field: object | None = issue.get('url')
    url_val: str
    if isinstance(url_field, str) and url_field:
        url_val = url_field
    elif issue_id and issue_id != issue_id_unknown_msg and YT_BASE_URL:
        url_val = f'{YT_BASE_URL}/issue/{issue_id}'
    else:
        url_val = render(Msg.ERR_YT_ISSUE_NO_URL)

    status_text: str | None = extract_issue_status(issue) or status_raw or None
    assignee_text: str | None = extract_issue_assignee(issue)
    if not assignee_text:
        assignee_candidate: str = assignee_label.strip()
        if assignee_candidate and assignee_candidate != render(Msg.NOT_ASSIGNED):
            assignee_text = assignee_candidate
    author_text: str | None = extract_issue_author(issue) or author_raw.strip() or None

    return issue_id, summary, description, url_val, assignee_text, status_text, author_text


def prepare_payload_for_logging(payload: dict[str, object]) -> dict[str, object]:
    """Return payload copy with cleaned description for email issues."""
    payload_copy: dict[str, object] = deepcopy(payload)

    def _sanitize_description(container: object) -> None:
        if not isinstance(container, dict):
            return
        description_obj: object | None = container.get('description')
        if not isinstance(description_obj, str):
            return
        if not _looks_like_email_description(description_obj):
            return
        container['description'] = _normalize_email_description(description_obj)

    def _normalize_summary(container: object) -> None:
        if not isinstance(container, dict):
            return
        summary_obj: object | None = container.get('summary')
        if summary_obj is None:
            return
        container['summary'] = normalize_issue_summary(str(summary_obj))

    _sanitize_description(payload_copy)
    _normalize_summary(payload_copy)
    issue_obj: object | None = payload_copy.get('issue')
    if isinstance(issue_obj, dict):
        _sanitize_description(issue_obj)
        _normalize_summary(issue_obj)

    return payload_copy


def build_log_entry(payload: dict[str, object]) -> dict[str, object]:
    """Build concise log entry without extra HTML."""
    issue_obj: object | None = payload.get('issue')
    issue: dict[str, object] = issue_obj if isinstance(issue_obj, dict) else payload
    log_entry: dict[str, object] = {}
    for key in ('idReadable', 'summary', 'status', 'assignee', 'author', 'url'):
        value: object | None = issue.get(key)
        if value is None:
            continue
        text_value: str = str(value) if isinstance(value, (int, float, bool)) else str(value).strip()
        if key == 'summary':
            text_value = normalize_issue_summary(text_value)
        log_entry[key] = text_value
    description_obj: object | None = issue.get('description')
    if isinstance(description_obj, str):
        description_text: str = strip_html(description_obj).strip()
        if description_text:
            log_entry['description'] = description_text
    return log_entry


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Convert ISO string to timezone-aware ``datetime``."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_edit_window_expired(updated_at: str | None) -> bool:
    """Determine whether Telegram edit window has expired."""
    baseline: datetime | None = parse_iso_datetime(updated_at)
    if baseline is None:
        return False
    now: datetime = datetime.now(tz=timezone.utc)
    return now - baseline > _TELEGRAM_EDIT_TTL


def build_issue_url(issue_id: str) -> str:
    """Compose issue URL or return fallback message."""
    if YT_BASE_URL and issue_id and issue_id != render(Msg.YT_ISSUE_NO_ID):
        return f'{YT_BASE_URL}/issue/{issue_id}'
    return render(Msg.ERR_YT_ISSUE_NO_URL)


def looks_like_email_description(description: str) -> bool:
    """Determine whether HTML description looks email-generated."""
    normalized: str = description.casefold()
    if 'gmail' in normalized or 'cid:' in normalized:
        return True
    score: int = sum(1 for marker in _EMAIL_HTML_MARKERS if marker in normalized)
    return score >= 2


def normalize_email_description(description: str) -> str:
    """Clean HTML description removing service attributes and extra tags."""
    cleaned: str = description.replace('\xa0', ' ')
    cleaned = _ATTR_STYLE_DOUBLE_RE.sub('', cleaned)
    cleaned = _ATTR_STYLE_SINGLE_RE.sub('', cleaned)
    cleaned = _ATTR_CLASS_RE.sub('', cleaned)
    cleaned = _ATTR_DIR_RE.sub('', cleaned)
    cleaned = _ATTR_MISC_PREFIX_RE.sub('', cleaned)
    cleaned = _SPAN_TAG_RE.sub('', cleaned)
    cleaned = _FONT_TAG_RE.sub('', cleaned)
    cleaned = _IMG_TAG_RE.sub('', cleaned)
    cleaned = _MULTISPACE_RE.sub(' ', cleaned)
    cleaned = _WHITESPACE_TAGS_RE.sub('>\n<', cleaned)
    cleaned = _EMPTY_PARAGRAPH_RE.sub('', cleaned)
    return cleaned.strip()


def render_telegram_message(
    issue_id: str,
    summary: str,
    description: str,
    url_val: str,
    assignee: str | None,
    status: str | None,
    author: str | None,
) -> str:
    """Build HTML message for Telegram."""
    return format_telegram_message(
        issue_id,
        summary,
        description,
        url_val,
        assignee=assignee,
        status=status,
        author=author,
    )


def _looks_like_email_description(description: str) -> bool:
    return looks_like_email_description(description)


def _normalize_email_description(description: str) -> str:
    return normalize_email_description(description)
