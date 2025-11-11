"""Забезпечує FastAPI застосунок для обробки вебхуків YouTrack та Telegram."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from fastapi import FastAPI, HTTPException, Request

from agromat_it_desk_bot.callback_handlers import verify_telegram_secret
from agromat_it_desk_bot.config import BOT_TOKEN, TELEGRAM_CHAT_ID, YT_BASE_URL, YT_WEBHOOK_SECRET
from agromat_it_desk_bot.messages import Msg, render
from agromat_it_desk_bot.storage import fetch_issue_message, upsert_issue_message
from agromat_it_desk_bot.telegram import context as telegram_context
from agromat_it_desk_bot.telegram import telegram_aiogram, telegram_commands
from agromat_it_desk_bot.telegram.telegram_sender import AiogramTelegramSender
from agromat_it_desk_bot.utils import (
    configure_logging,
    extract_issue_assignee,
    extract_issue_author,
    extract_issue_id,
    extract_issue_status,
    format_telegram_message,
    get_str,
    normalize_issue_summary,
    strip_html,
)
from agromat_it_desk_bot.youtrack.youtrack_service import IssueDetails, fetch_issue_details

configure_logging()
logger: logging.Logger = logging.getLogger(__name__)


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


def _looks_like_email_description(description: str) -> bool:
    """Визначає, чи HTML-опис схожий на згенерований поштовим клієнтом."""
    normalized: str = description.casefold()
    if 'gmail' in normalized or 'cid:' in normalized:
        return True
    score: int = sum(1 for marker in _EMAIL_HTML_MARKERS if marker in normalized)
    return score >= 2


def _normalize_email_description(description: str) -> str:
    """Очищає HTML-опис, видаляючи службові атрибути та зайві теги."""
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


def _prepare_payload_for_logging(payload: Mapping[str, object]) -> dict[str, object]:
    """Повертає копію payload із очищеним description для поштових заявок."""
    payload_copy: dict[str, object] = deepcopy(dict(payload))

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


_TELEGRAM_CHAT_ID_RESOLVED: int | str
if TELEGRAM_CHAT_ID is None:
    raise RuntimeError('TELEGRAM_CHAT_ID не налаштовано')
try:
    _TELEGRAM_CHAT_ID_RESOLVED = int(TELEGRAM_CHAT_ID)
except ValueError:
    _TELEGRAM_CHAT_ID_RESOLVED = TELEGRAM_CHAT_ID


def _prepare_issue_payload(  # noqa: C901
    issue: Mapping[str, object],
) -> tuple[str, str, str, str, str | None, str | None, str | None]:
    issue_id: str = extract_issue_id(issue)
    summary: str = normalize_issue_summary(get_str(issue, 'summary'))
    description: str = strip_html(get_str(issue, 'description'))

    author_raw: str = get_str(issue, 'author')
    if not author_raw:
        reporter_obj = issue.get('reporter')
        if isinstance(reporter_obj, Mapping):
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
            if not isinstance(field, Mapping):
                continue
            name_value: object | None = field.get('name')
            name_lower: str | None = str(name_value) if isinstance(name_value, str) else None
            if name_lower in {'статус', 'state'} and not status_raw:
                field_value = field.get('value')
                if isinstance(field_value, Mapping):
                    status_candidate: object | None = field_value.get('name')
                    if isinstance(status_candidate, str) and status_candidate:
                        status_raw = status_candidate
            if (
                name_lower in {'assignee', 'assignees', 'виконавець', 'виконавці'}
                and assignee_label == render(Msg.NOT_ASSIGNED)
            ):
                field_value = field.get('value')
                names: list[str] = []
                if isinstance(field_value, Mapping):
                    extracted = field_value.get('fullName') or field_value.get('login') or field_value.get('name')
                    if isinstance(extracted, str) and extracted:
                        names = [extracted]
                elif isinstance(field_value, list):
                    for candidate in field_value:
                        if isinstance(candidate, Mapping):
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


def _unwrap_issue(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Повертає вкладений опис задачі з payload або сам payload."""
    issue_obj: object | None = payload.get('issue')
    if isinstance(issue_obj, Mapping):
        return issue_obj
    return payload


def _build_issue_url(issue_id: str) -> str:
    """Формує URL задачі або повертає повідомлення про його відсутність."""
    if YT_BASE_URL and issue_id and issue_id != render(Msg.YT_ISSUE_NO_ID):
        return f'{YT_BASE_URL}/issue/{issue_id}'
    return render(Msg.ERR_YT_ISSUE_NO_URL)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Керує запуском та завершенням FastAPI застосунку.

    :param _app: Поточний екземпляр FastAPI.
    :yields: ``None`` протягом роботи застосунку.
    """
    if not BOT_TOKEN:
        raise RuntimeError('BOT_TOKEN не налаштовано')

    bot: Bot = Bot(token=BOT_TOKEN)
    dispatcher: Dispatcher = Dispatcher()
    sender = AiogramTelegramSender(bot)
    telegram_commands.configure_sender(sender)
    telegram_aiogram.configure(bot, dispatcher)

    try:
        yield
    finally:
        # Закривають HTTP-сесію бота Aiogram при виході
        await telegram_aiogram.shutdown()


app = FastAPI(lifespan=_lifespan)

# Перехідні псевдоніми для збереження сумісності тестів/імпортів
PendingTokenUpdate = telegram_commands.PendingTokenUpdate
pending_token_updates = telegram_commands.pending_token_updates
# Сумісність зі старим API
PendingLoginChange = PendingTokenUpdate
pending_login_updates = pending_token_updates
handle_start_command = telegram_commands.handle_start_command
handle_unlink_command = telegram_commands.handle_unlink_command
handle_connect_command = telegram_commands.handle_connect_command
handle_reconnect_command = telegram_commands.handle_connect_command  # зворотна сумісність
handle_confirm_reconnect = telegram_commands.handle_confirm_reconnect
handle_reconnect_shortcut = telegram_commands.handle_reconnect_shortcut


@app.post('/youtrack')
async def youtrack_webhook(request: Request) -> dict[str, bool]:  # noqa: C901
    """Обробляє вебхук від YouTrack та повідомляє Telegram."""
    payload: Any = await request.json()

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Некоректний формат тіла запиту')

    if YT_WEBHOOK_SECRET is not None:
        auth_header: str | None = request.headers.get('Authorization')
        expected: str = f'Bearer {YT_WEBHOOK_SECRET}'
        if auth_header != expected:
            logger.warning('Невірний секрет YouTrack вебхука')
            raise HTTPException(status_code=403, detail='Доступ заборонено')

    issue_candidate: object | None = payload.get('issue')
    issue: Mapping[str, object] = issue_candidate if isinstance(issue_candidate, dict) else payload

    issue_id, summary, description, url_val, assignee_text, status_text, author_text = _prepare_issue_payload(issue)

    payload_for_logging = _prepare_payload_for_logging(payload)
    logger.info('Отримано вебхук YouTrack: %s', payload_for_logging)

    telegram_msg: str = format_telegram_message(
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
        _TELEGRAM_CHAT_ID_RESOLVED,
        telegram_msg,
        parse_mode='HTML',
        reply_markup=reply_markup,
        disable_web_page_preview=False,
    )
    await asyncio.to_thread(upsert_issue_message, issue_id, _TELEGRAM_CHAT_ID_RESOLVED, message_id)
    return {'ok': True}


@app.post('/youtrack/update')
async def youtrack_update(request: Request) -> dict[str, bool]:  # noqa: C901
    """Оновлює наявне повідомлення Telegram після змін у задачі YouTrack."""
    payload: Any = await request.json()

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Некоректний формат тіла запиту')

    if YT_WEBHOOK_SECRET is not None:
        auth_header: str | None = request.headers.get('Authorization')
        expected: str = f'Bearer {YT_WEBHOOK_SECRET}'
        if auth_header != expected:
            logger.warning('Невірний секрет YouTrack вебхука (update)')
            raise HTTPException(status_code=403, detail='Доступ заборонено')

    issue_mapping: Mapping[str, object] = _unwrap_issue(payload)
    issue_id: str = extract_issue_id(issue_mapping)

    changes_raw: object | None = payload.get('changes')
    changes_list: list[str] = (
        [str(item) for item in changes_raw if isinstance(item, str)]
        if isinstance(changes_raw, list)
        else []
    )
    changes_text: str = ', '.join(changes_list) if changes_list else 'невідомі поля'

    logger.info('Оновлення задачі %s через update вебхук (зміни: %s)', issue_id, changes_text)

    summary_payload: str = normalize_issue_summary(get_str(issue_mapping, 'summary'))
    description_payload_raw: str = get_str(issue_mapping, 'description')
    description_payload: str = strip_html(description_payload_raw)
    author_payload: str | None = extract_issue_author(issue_mapping)
    if not author_payload:
        reporter_obj: object | None = issue_mapping.get('reporter')
        if isinstance(reporter_obj, Mapping):
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
        details = await asyncio.to_thread(fetch_issue_details, issue_id)

    summary: str = summary_payload or (details.summary if details else '')
    description: str = description_payload or (details.description if details else '')
    author_text: str | None = author_payload or (details.author if details else None)
    status_text: str | None = status_payload or (details.status if details else None)
    assignee_text: str | None = assignee_payload or (details.assignee if details else None)
    url_val: str = get_str(issue_mapping, 'url') or _build_issue_url(issue_id)

    payload_for_logging = _prepare_payload_for_logging(payload)
    logger.debug('Параметри update вебхука: %s', payload_for_logging)

    record = await asyncio.to_thread(fetch_issue_message, issue_id)
    if record is None:
        logger.info('Повідомлення для задачі %s не знайдено, пропускаю update', issue_id)
        return {'ok': False}

    chat_id_raw: str = str(record['chat_id'])
    chat_id: int | str
    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        chat_id = chat_id_raw
    message_id: int = int(record['message_id'])

    telegram_msg: str = format_telegram_message(
        issue_id,
        summary,
        description,
        url_val,
        assignee=assignee_text,
        status=status_text,
        author=author_text,
    )

    sender = telegram_context.get_sender()
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
            refreshed_details: IssueDetails | None = await asyncio.to_thread(fetch_issue_details, issue_id)
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


@app.post('/telegram')
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Обробляє webhook від Telegram та делегує Aiogram-логіку."""
    logger.info('Отримано вебхук Telegram')

    verify_telegram_secret(request)  # Перевірка секрету вебхука Телеграм

    payload: Any = await request.json()
    if not isinstance(payload, dict):
        # Ігнорування невідомих оновлень, щоб не зривати роботу бота
        logger.warning('Отримано некоректний payload від Telegram: %r', payload)
        return {'ok': True}

    try:
        # Передати оновлення у диспетчер Aiogram для маршрутизації
        await telegram_aiogram.process_update(payload)
        logger.debug('Telegram webhook передано до Aiogram успішно')
    except Exception as err:  # noqa: BLE001
        # Фіксування помилки, але не відповідати користувачу повторно
        logger.exception('Помилка обробки Telegram update: %s', err)

    return {'ok': True}


@app.post('/telegram/webhook')
async def telegram_webhook_alias(request: Request) -> dict[str, bool]:
    """Переадресовує запит на основний обробник ``/telegram`` (запасний маршрут)."""
    return await telegram_webhook(request)


def main() -> None:
    """Запускає Uvicorn сервер для FastAPI застосунку."""
    uvicorn.run(app, host='0.0.0.0', port=8080)


if __name__ == '__main__':
    main()
