"""FastAPI routes for YouTrack webhook."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from agromat_it_desk_bot.alerts.new_status import cancel_new_status_alerts, schedule_new_status_alerts
from agromat_it_desk_bot.config import TELEGRAM_CHAT_ID
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.models import YouTrackUpdatePayload, YouTrackWebhookPayload
from agromat_it_desk_bot.services.youtrack_webhook import (
    build_issue_url,
    build_log_entry,
    is_edit_window_expired,
    prepare_issue_payload,
    prepare_payload_for_logging,
    render_telegram_message,
)
from agromat_it_desk_bot.storage import fetch_issue_message, upsert_issue_message
from agromat_it_desk_bot.telegram import context as telegram_context
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
from agromat_it_desk_bot.youtrack.youtrack_service import IssueDetails, ensure_summary_placeholder, fetch_issue_details

logger: logging.Logger = logging.getLogger(__name__)
router = APIRouter()


def _webhook_secret() -> str | None:
    from agromat_it_desk_bot import main

    return getattr(main, 'YT_WEBHOOK_SECRET', None)


def _chat_id() -> int | str:
    from agromat_it_desk_bot import main

    return getattr(main, '_TELEGRAM_CHAT_ID_RESOLVED', TELEGRAM_CHAT_ID or '')


def _get_callable(name: str, default: Any) -> Any:
    from agromat_it_desk_bot import main

    return getattr(main, name, default)


@router.post('/youtrack')
async def youtrack_webhook(request: Request) -> dict[str, bool]:  # noqa: C901
    """Handle YouTrack webhook and notify Telegram."""
    payload_raw: Any = await request.json()
    try:
        payload_model = YouTrackWebhookPayload.model_validate(payload_raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail='Некоректний формат тіла запиту') from exc

    webhook_secret = _webhook_secret()
    if webhook_secret:
        auth_header: str | None = request.headers.get('Authorization')
        expected: str = f'Bearer {webhook_secret}'
        if auth_header != expected:
            logger.warning('Невірний секрет YouTrack вебхука')
            raise HTTPException(status_code=403, detail='Доступ заборонено')

    issue_payload: dict[str, object] = dict(payload_model.issue_mapping())

    (
        issue_id,
        summary,
        description,
        url_val,
        assignee_text,
        status_text,
        author_text,
    ) = prepare_issue_payload(issue_payload)
    internal_id_obj: object | None = issue_payload.get('id')
    internal_id: str | None = str(internal_id_obj) if isinstance(internal_id_obj, str) else None
    if summary == render(Msg.YT_EMAIL_SUBJECT_MISSING):
        ensure_placeholder = _get_callable('ensure_summary_placeholder', ensure_summary_placeholder)
        await asyncio.to_thread(ensure_placeholder, issue_id, summary, internal_id)

    payload_for_logging = prepare_payload_for_logging(payload_model.model_dump(mode='python'))
    logger.info('Отримано вебхук YouTrack: %s', build_log_entry(payload_for_logging))

    telegram_msg: str = render_telegram_message(
        issue_id,
        summary,
        description,
        url_val,
        assignee=assignee_text,
        status=status_text,
        author=author_text,
    )

    reply_markup: dict[str, object] | None = None
    issue_id_unknown_msg: str = render(Msg.YT_ISSUE_NO_ID)
    if issue_id and issue_id != issue_id_unknown_msg:
        button_text: str = render(Msg.TG_BTN_ACCEPT_ISSUE)
        reply_markup = {
            'inline_keyboard': [[{'text': button_text, 'callback_data': f'accept|{issue_id}'}]],
        }

    sender = telegram_context.get_sender()
    message_id: int = await sender.send_message(
        _chat_id(),
        telegram_msg,
        parse_mode='HTML',
        reply_markup=reply_markup,
        disable_web_page_preview=False,
    )
    chat_id_value = _chat_id()
    await asyncio.to_thread(upsert_issue_message, issue_id, chat_id_value, message_id)
    await schedule_new_status_alerts(issue_id, status_text, chat_id_value, message_id)
    return {'ok': True}


@router.post('/youtrack/update')
async def youtrack_update(request: Request) -> dict[str, bool]:  # noqa: C901
    """Update existing Telegram message after YouTrack issue changes."""
    payload_raw: Any = await request.json()
    try:
        payload_model = YouTrackUpdatePayload.model_validate(payload_raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail='Некоректний формат тіла запиту') from exc

    webhook_secret = _webhook_secret()
    if webhook_secret:
        auth_header: str | None = request.headers.get('Authorization')
        expected: str = f'Bearer {webhook_secret}'
        if auth_header != expected:
            logger.warning('Невірний секрет YouTrack вебхука (update)')
            raise HTTPException(status_code=403, detail='Доступ заборонено')

    issue_mapping: dict[str, object] = dict(payload_model.issue_mapping())
    issue_id: str = extract_issue_id(issue_mapping)

    changes_list: list[str] = payload_model.changes or []
    changes_text: str = ', '.join(changes_list) if changes_list else 'невідомі поля'

    logger.info('Оновлення задачі %s через update вебхук (зміни: %s)', issue_id, changes_text)

    summary_payload: str = normalize_issue_summary(get_str(issue_mapping, 'summary'))
    description_payload_raw: str = get_str(issue_mapping, 'description')
    description_payload: str = strip_html(description_payload_raw)
    author_payload: str | None = extract_issue_author(issue_mapping)
    if not author_payload:
        reporter_obj: object | None = issue_mapping.get('reporter')
        if isinstance(reporter_obj, dict):
            author_payload = str(
                reporter_obj.get('fullName')
                or reporter_obj.get('login')
                or reporter_obj.get('name')
                or '',
            ).strip() or None

    status_payload: str | None = extract_issue_status(issue_mapping)
    assignee_payload: str | None = extract_issue_assignee(issue_mapping)

    needs_details: bool = not (
        summary_payload
        and description_payload
        and author_payload
        and status_payload
        and assignee_payload
    )

    details: IssueDetails | None = None
    if needs_details:
        fetch_details = _get_callable('fetch_issue_details', fetch_issue_details)
        details = await asyncio.to_thread(fetch_details, issue_id)

    fallback_summary: str = normalize_issue_summary(str(details.summary or '')) if details else ''
    fallback_description: str = strip_html(str(details.description or '')) if details else ''
    summary: str = summary_payload or fallback_summary
    description: str = description_payload or fallback_description
    author_text: str | None = author_payload or (details.author if details else None)
    status_text: str | None = status_payload or (details.status if details else None)
    assignee_text: str | None = assignee_payload or (details.assignee if details else None)
    url_val: str = get_str(issue_mapping, 'url') or build_issue_url(issue_id)
    await cancel_new_status_alerts(issue_id, status_text)

    payload_for_logging = prepare_payload_for_logging(payload_model.model_dump(mode='python'))
    logger.debug('Параметри update вебхука: %s', payload_for_logging)

    record = await asyncio.to_thread(fetch_issue_message, issue_id)
    if record is None:
        logger.info('Повідомлення для задачі %s не знайдено, пропускаю update', issue_id)
        return {'ok': False}

    updated_at_raw: object | None = record.get('updated_at')
    updated_at_text: str | None = updated_at_raw if isinstance(updated_at_raw, str) else None
    chat_id_raw: str = str(record['chat_id'])
    chat_id: int | str
    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        chat_id = chat_id_raw
    message_id: int = int(record['message_id'])
    sender = telegram_context.get_sender()
    if is_edit_window_expired(updated_at_text):
        archived_status: str = render(Msg.STATUS_ARCHIVED)
        logger.info(
            'Повідомлення задачі %s не оновлено: перевищено ліміт 48 годин (статус: %s)',
            issue_id,
            archived_status,
        )
        return {'ok': True}

    telegram_msg: str = format_telegram_message(
        issue_id,
        summary,
        description,
        url_val,
        assignee=assignee_text,
        status=status_text,
        author=author_text,
    )

    try:
        await sender.edit_message_text(
            chat_id,
            message_id,
            telegram_msg,
            parse_mode='HTML',
            reply_markup=None,
            disable_web_page_preview=False,
        )
    except TelegramBadRequest as exc:
        error_text: str = str(exc).lower()
        if 'message is not modified' in error_text:
            logger.info(
                'Telegram відхилив оновлення для задачі %s: повідомлення без змін, пробую оновити з REST',
                issue_id,
            )
            await asyncio.sleep(0.3)
            fetch_details_retry = _get_callable('fetch_issue_details', fetch_issue_details)
            refreshed_details: IssueDetails | None = await asyncio.to_thread(fetch_details_retry, issue_id)
            if refreshed_details is None:
                logger.info(
                    'Не вдалося оновити повідомлення задачі %s: REST повернув порожні дані',
                    issue_id,
                )
                return {'ok': True}
            refreshed_summary: str = normalize_issue_summary(refreshed_details.summary)
            refreshed_description: str = strip_html(refreshed_details.description or '')
            refreshed_author: str | None = refreshed_details.author
            refreshed_status: str | None = refreshed_details.status
            refreshed_assignee: str | None = refreshed_details.assignee

            refreshed_message: str = format_telegram_message(
                issue_id,
                refreshed_summary,
                refreshed_description,
                url_val,
                assignee=refreshed_assignee,
                status=refreshed_status,
                author=refreshed_author,
            )
            if refreshed_message == telegram_msg:
                logger.info(
                    'Повідомлення задачі %s вже актуальне після повторної перевірки',
                    issue_id,
                )
                return {'ok': True}
            try:
                await sender.edit_message_text(
                    chat_id,
                    message_id,
                    refreshed_message,
                    parse_mode='HTML',
                    reply_markup=None,
                    disable_web_page_preview=False,
                )
                logger.info('Повідомлення задачі %s оновлено після повторної спроби', issue_id)
                return {'ok': True}
            except TelegramBadRequest as retry_exc:
                if 'message is not modified' in str(retry_exc).lower():
                    logger.info(
                        'Telegram вдруге відхилив оновлення для задачі %s: змін все ще немає',
                        issue_id,
                    )
                    return {'ok': True}
                raise
        raise
    await asyncio.to_thread(upsert_issue_message, issue_id, chat_id_raw, message_id)
    return {'ok': True}
