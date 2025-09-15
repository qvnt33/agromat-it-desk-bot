import logging
from html import escape
from typing import Any, Mapping, Optional, cast

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from agromat_it_desk_bot.config import BOT_TOKEN, DESCRIPTION_MAX_LEN, TELEGRAM_CHAT_ID, YT_BASE_URL

logging.basicConfig(level=logging.INFO)

app = FastAPI()


@app.post('/youtrack')
async def youtrack_webhook(request: Request) -> dict[str, bool]:
    """Обробити вебхук від YouTrack.

    :param request: Прийняти обʼєкт запиту з даними вебхука.
    :type request: Request
    :returns: Повернути результат обробки вебхука.
    :rtype: dict[str, bool]
    :raises HTTPException: Повернути 400 у разі некоректного запиту.

    Отримати дані з вебхука YouTrack, витягти деталі задачі: ідентифікатор, заголовок, опис, URL.
    Сформувати повідомлення та надіслати його до Telegram.
    У разі помилки — залогувати деталі.
    """
    try:
        obj: Any = await request.json()
        if not isinstance(obj, dict):
            raise HTTPException(status_code=400, detail='Invalid payload shape')

        raw: dict[str, object] = cast(dict[str, object], obj)
        data: Mapping[str, object] = raw
        logging.info(f'Received data: {data}')

        issue_field: object | None = data.get('issue')
        if isinstance(issue_field, dict):
            issue: Mapping[str, object] = cast(Mapping[str, object], issue_field)
        else:
            issue = data

        id_readable: str = _extract_issue_id(issue)
        summary: str = _get_str(issue, 'summary')
        description: str = _get_str(issue, 'description')

        url_val: Optional[str] = None
        url_field: object | None = issue.get('url')

        if isinstance(url_field, str) and url_field:
            url_val = url_field
        elif YT_BASE_URL and id_readable and id_readable != '(без ID)':
            url_val = f'{YT_BASE_URL}/issue/{id_readable}'

        message: str = _format_message(id_readable, summary, description, url_val)

        # Відправити у threadpool, щоб не блокувати event loop
        await run_in_threadpool(_send_to_telegram, message)
        return {'ok': True}
    except HTTPException:
        # Не перекривати статуси, які вже визначено вище
        raise
    except Exception as e:
        logging.error(f'Error processing request: {e}')
        raise HTTPException(status_code=400, detail='Invalid request') from None


def _send_to_telegram(text: str) -> None:
    """Надіслати повідомлення у Telegram.

    :param text: Передати текст повідомлення.
    :raises HTTPException: Повернути помилку, якщо Telegram відповів некоректно.
    """
    if not BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(status_code=500, detail='Telegram credentials are not configured')

    resp: requests.Response = requests.post(
        f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
        json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': text,
            'disable_web_page_preview': True,
            'parse_mode': 'HTML',
        },
        timeout=10,
    )
    if not resp.ok:
        raise HTTPException(status_code=502, detail=f'Telegram error: {resp.text}')


def _get_str(obj: Mapping[str, object], key: str) -> str:
    """Дістати значення як рядок і обрізати пробіли"""
    val: object | None = obj.get(key)

    return '' if val is None else str(val).strip()


def _extract_issue_id(issue: Mapping[str, object]) -> str:
    """Отримати читабельний ID задачі з різних полів"""
    id_readable: str = _get_str(issue, 'idReadable') or _get_str(issue, 'id')
    if id_readable:
        return id_readable

    number: object | None = issue.get('numberInProject')
    project: object | None = issue.get('project')
    project_short: Optional[str] = None
    if isinstance(project, dict):
        project_map: dict[str, object] = cast(dict[str, object], project)
        short_name: object | None = project_map.get('shortName')
        name: object | None = project_map.get('name')
        if isinstance(short_name, str) and short_name:
            project_short = short_name
        elif isinstance(name, str) and name:
            project_short = name

    if project_short is not None and isinstance(number, (str, int)):
        return f'{project_short}-{number}'

    logging.warning('No issue ID found in payload. Available keys: %s', list(issue.keys()))
    return '(без ID)'


def _format_message(id_readable: str, summary_raw: str, description_raw: str, url: Optional[str]) -> str:
    """Сформатувати повідомлення для Telegram з екрануванням HTML"""
    summary: str = escape(summary_raw)
    description: str = escape(description_raw)
    parts: list[str] = [f'<b>{escape(str(id_readable))}</b> — {summary}']

    if url:
        parts.append(url)
    if description:
        short: str = (
            description[:DESCRIPTION_MAX_LEN] + '…'
            if len(description) > DESCRIPTION_MAX_LEN
            else description
        )
        parts.append(short)
    return '\n'.join(parts)
