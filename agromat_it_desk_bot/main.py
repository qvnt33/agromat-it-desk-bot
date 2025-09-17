import logging
from html import escape
from typing import Any, Mapping, Optional, cast

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from agromat_it_desk_bot.config import (
    ALLOWED_TG_USER_IDS,
    BOT_TOKEN,
    DESCRIPTION_MAX_LEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_WEBHOOK_SECRET,
    USER_MAP_FILE,
    YOUTRACK_ASSIGNEE_FIELD_NAME,
    YOUTRACK_STATE_FIELD_NAME,
    YOUTRACK_STATE_IN_PROGRESS,
    YT_BASE_URL,
    YT_TOKEN,
)

logging.basicConfig(level=logging.INFO)

logger: logging.Logger = logging.getLogger(__name__)

app = FastAPI()


@app.post('/youtrack')
async def youtrack_webhook(request: Request) -> dict[str, bool]:
    """Обробити вебхук від YouTrack.

    Зчитати JSON-пейлоад, дістати ідентифікатор задачі, заголовок,
    опис та посилання, сформувати повідомлення й надіслати його до Telegram.
    Якщо відомий ID задачі, додати кнопку «Прийняти» для швидкого призначення.

    :param request: Обʼєкт запиту FastAPI.
    :type request: Request
    :returns: Ознака успішної обробки.
    :rtype: dict[str, bool]
    :raises HTTPException: 400, якщо пейлоад некоректний.
    """
    try:
        # Зчитати тіло запиту як JSON і переконатися, що вхідні дані є словником
        obj: Any = await request.json()
        if not isinstance(obj, dict):
            raise HTTPException(status_code=400, detail='Invalid payload shape')

        raw: dict[str, object] = cast(dict[str, object], obj)
        data: Mapping[str, object] = raw
        logger.debug('Отримано вебхук YouTrack: %s', data)

        # Взяти вкладене поле issue, якщо YouTrack обгорнув дані задачі
        issue_field: object | None = data.get('issue')
        if isinstance(issue_field, dict):
            issue: Mapping[str, object] = cast(Mapping[str, object], issue_field)
        else:
            issue = data

        # Дістати ключові поля задачі для подальшого форматування повідомлення
        id_readable: str = _extract_issue_id(issue)
        summary: str = _get_str(issue, 'summary')
        description: str = _get_str(issue, 'description')

        url_val: Optional[str] = None
        url_field: object | None = issue.get('url')

        # Сформувати посилання на задачу, якщо його немає в початкових даних
        if isinstance(url_field, str) and url_field:
            url_val = url_field
        elif YT_BASE_URL and id_readable and id_readable != '(без ID)':
            url_val = f'{YT_BASE_URL}/issue/{id_readable}'

        message: str = _format_message(id_readable, summary, description, url_val)

        # Зібрати клавіатуру з кнопкою «Прийняти», якщо відомий читабельний ID
        reply_markup: Optional[dict[str, Any]] = None
        if id_readable and id_readable != '(без ID)':
            reply_markup = {
                'inline_keyboard': [
                    [
                        {
                            'text': 'Прийняти',
                            'callback_data': f'accept|{id_readable}',
                        },
                    ],
                ],
            }

        # Надіслати повідомлення у пулі потоків, щоб не блокувати event loop FastAPI
        logger.info('Підготовано повідомлення для задачі %s', id_readable or '(без ID)')
        await run_in_threadpool(_send_to_telegram, message, reply_markup)
        return {'ok': True}
    except HTTPException:
        # Не перекривати статуси, які вже визначено вище
        raise
    except Exception as e:
        logger.exception('Помилка під час обробки вебхука YouTrack: %s', e)
        raise HTTPException(status_code=400, detail='Invalid request') from None


def _send_to_telegram(text: str, reply_markup: Optional[dict[str, Any]] = None) -> None:
    """Надіслати повідомлення у Telegram.

    :param text: Текст повідомлення.
    :type text: str
    :param reply_markup: Inline‑клавіатура (опційно).
    :type reply_markup: dict[str, Any] | None
    :raises HTTPException: 500 або 502 у разі проблем із відправкою.
    """
    # Переконатися, що задано обовʼязкові облікові дані для бота
    if not BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(status_code=500, detail='Telegram credentials are not configured')

    # Зібрати тіло запиту до Bot API з текстом і клавіатурою
    payload: dict[str, Any] = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'disable_web_page_preview': True,
        'parse_mode': 'HTML',
    }
    if reply_markup is not None:
        payload['reply_markup'] = reply_markup

    # Відправити повідомлення та обробити можливу помилку від API
    resp: requests.Response = requests.post(
        f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
        json=payload,
        timeout=10,
    )
    if not resp.ok:
        logger.error('Telegram повернув помилку під час надсилання повідомлення: %s', resp.text)
        raise HTTPException(status_code=502, detail=f'Telegram error: {resp.text}')
    logger.info('Надіслано повідомлення в Telegram чат %s', TELEGRAM_CHAT_ID)


@app.post('/telegram')
async def telegram_webhook(request: Request) -> dict[str, bool]:  # noqa: C901
    """Обробити оновлення Telegram.

    Прийняти ``callback_query`` для кнопки «Прийняти», перевірити дозволи й
    виконати призначення у YouTrack з подальшою зміною статусу.

    :param request: Обʼєкт запиту FastAPI.
    :type request: Request
    :returns: Ознака успішної обробки (завжди ``{"ok": true}``).
    :rtype: dict[str, bool]
    """
    logger.info('Отримано вебхук Telegram')

    # Перевірити, чи збігається секретний токен вебхука з очікуваним значенням
    if TELEGRAM_WEBHOOK_SECRET is not None:
        secret: str | None = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if secret != TELEGRAM_WEBHOOK_SECRET:
            logger.warning('Невірний секрет Telegram вебхука')
            raise HTTPException(status_code=403, detail='Forbidden')

    # Зчитати тіло запиту та переконатися, що маємо словник з оновленням Telegram
    obj: Any = await request.json()
    if not isinstance(obj, dict):
        return {'ok': True}
    data: Mapping[str, object] = cast(Mapping[str, object], obj)

    # Витягти інформацію про callback_query; ігнорувати несумісні події
    cb_map: Mapping[str, object] | None = _as_mapping(data.get('callback_query'))
    if cb_map is None:
        return {'ok': True}

    cb_id_obj: object | None = cb_map.get('id')
    cb_id: Optional[str] = str(cb_id_obj) if isinstance(cb_id_obj, (str, int)) else None

    from_user_map: Mapping[str, object] | dict[str, object] = _as_mapping(cb_map.get('from')) or {}
    tg_user_id_obj: object | None = from_user_map.get('id')
    tg_user_id: Optional[int] = tg_user_id_obj if isinstance(tg_user_id_obj, int) else None

    message_map: Mapping[str, object] | dict[str, object] = _as_mapping(cb_map.get('message')) or {}
    chat_map: Mapping[str, object] | dict[str, object] = _as_mapping(message_map.get('chat')) or {}

    chat_id_obj: object | None = chat_map.get('id')
    chat_id: Optional[int] = chat_id_obj if isinstance(chat_id_obj, int) else None

    msg_id_obj: object | None = message_map.get('message_id')
    msg_id: Optional[int] = msg_id_obj if isinstance(msg_id_obj, int) else None

    data_field: object | None = cb_map.get('data')
    payload: str = str(data_field) if isinstance(data_field, (str, int)) else ''

    if not (cb_id and chat_id and msg_id):
        return {'ok': True}

    # Перевірити, чи користувач має право натискати кнопку «Прийняти»
    if ALLOWED_TG_USER_IDS and (tg_user_id is None or tg_user_id not in ALLOWED_TG_USER_IDS):
        _tg_api(
            'answerCallbackQuery',
            {
                'callback_query_id': cb_id,
                'text': 'Недостатньо прав',
                'show_alert': True,
            },
        )
        return {'ok': True}

    # Розпарсити дію з callback_data і переконатися, що це прийняття задачі
    action, _, issue_id_readable = str(payload).partition('|')
    if action != 'accept' or not issue_id_readable:
        _tg_api(
            'answerCallbackQuery',
            {
                'callback_query_id': cb_id,
                'text': 'Невідома дія',
            },
        )
        return {'ok': True}
    logger.info('Натиснуто кнопку "Прийняти" для задачі %s користувачем %s', issue_id_readable, tg_user_id)

    # Спробувати знайти користувача у YouTrack і призначити йому задачу
    try:
        if not (YT_BASE_URL and YT_TOKEN):
            raise RuntimeError('YouTrack не сконфігуровано')

        assignee_login, assignee_email, assignee_id = _resolve_youtrack_account(tg_user_id)
        if not assignee_login and not assignee_email and not assignee_id:
            raise RuntimeError('Не знайдено мапінг користувача')

        ok = _yt_assign_issue(issue_id_readable, assignee_login, assignee_email, assignee_id)
        if ok:
            # Спробувати оновити стан задачі на конфігуроване значення
            try:
                if YOUTRACK_STATE_IN_PROGRESS:
                    _yt_set_state(issue_id_readable, YOUTRACK_STATE_IN_PROGRESS)
            except Exception as se:  # noqa: BLE001
                logger.debug('Не вдалося оновити стан після прийняття: %s', se)
            _tg_api(
                'answerCallbackQuery',
                {
                    'callback_query_id': cb_id,
                    'text': 'Прийнято ✅',
                },
            )
            # Прибрати кнопку
            _tg_api(
                'editMessageReplyMarkup',
                {
                    'chat_id': chat_id,
                    'message_id': msg_id,
                    'reply_markup': {},
                },
            )
        else:
            _tg_api(
                'answerCallbackQuery',
                {
                    'callback_query_id': cb_id,
                    'text': 'Не вдалося призначити',
                    'show_alert': True,
                },
            )
    except Exception as e:  # noqa: BLE001
        logger.exception('Не вдалося обробити прийняття: %s', e)
        _tg_api(
            'answerCallbackQuery',
            {
                'callback_query_id': cb_id,
                'text': 'Помилка: не вдалось прийняти',
                'show_alert': True,
            },
        )

    return {'ok': True}


@app.post('/telegram/webhook')
async def telegram_webhook_alias(request: Request) -> dict[str, bool]:
    """Проксувати запит на основний обробник ``/telegram``.

    :param request: Обʼєкт запиту FastAPI.
    :type request: Request
    :returns: Відповідь основного обробника.
    :rtype: dict[str, bool]
    """
    return await telegram_webhook(request)


def _get_str(obj: Mapping[str, object], key: str) -> str:
    """Повернути значення ключа як рядок без зайвих пробілів.

    :param obj: Вхідний словник.
    :type obj: Mapping[str, object]
    :param key: Ключ.
    :type key: str
    :returns: Обрізане рядкове значення або порожній рядок.
    :rtype: str
    """
    val: object | None = obj.get(key)

    return '' if val is None else str(val).strip()


def _extract_issue_id(issue: Mapping[str, object]) -> str:
    """Отримати читабельний ID задачі з різних полів.

    :param issue: Дані задачі.
    :type issue: Mapping[str, object]
    :returns: ``ID-123`` або ``(без ID)``.
    :rtype: str
    """
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

    logger.warning('Не знайдено читабельного ID у пейлоаді YouTrack. Ключі: %s', list(issue.keys()))
    return '(без ID)'


def _format_message(id_readable: str, summary_raw: str, description_raw: str, url: Optional[str]) -> str:
    """Сформувати текст повідомлення для Telegram.

    Екрануй HTML, додай посилання та обріжи опис до
    ``DESCRIPTION_MAX_LEN``.

    :param id_readable: Читабельний ID задачі.
    :type id_readable: str
    :param summary_raw: Заголовок.
    :type summary_raw: str
    :param description_raw: Опис.
    :type description_raw: str
    :param url: Посилання на задачу (опційно).
    :type url: str | None
    :returns: Готовий текст для Telegram.
    :rtype: str
    """
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


def _tg_api(method: str, payload: dict[str, Any]) -> None:
    """Звернутися до Telegram Bot API.

    :param method: Метод Bot API (наприклад, ``sendMessage``).
    :type method: str
    :param payload: Тіло запиту.
    :type payload: dict[str, Any]
    :raises HTTPException: 500, якщо токен не заданий.
    """
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail='Telegram token not configured')
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/{method}'
    # Надіслати запит до Bot API з таймаутом, щоб уникати зависань
    resp = requests.post(url, json=payload, timeout=10)
    if not resp.ok:
        logger.error('Помилка Telegram API (%s): %s', method, resp.text)


def _resolve_youtrack_account(tg_user_id: Optional[int]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Знайти користувача YouTrack за Telegram ID.

    Підтримати формат ``user_map.json``:

    - ``"<tg_id>": "login"``
    - ``"<tg_id>": {"login": "...", "email": "..."}``
    - ``"<tg_id>": {"id": "<yt_user_id>", "login": "...", "email": "..."}``

    :param tg_user_id: Telegram ID користувача.
    :type tg_user_id: int | None
    :returns: Кортеж ``(login, email, yt_user_id)``.
    :rtype: tuple[str | None, str | None, str | None]
    """
    login: Optional[str] = None
    email: Optional[str] = None
    yt_user_id: Optional[str] = None

    # Прочитати дані зі вказаного файлу мапи користувачів
    try:
        target_file = USER_MAP_FILE
        # Якщо у змінній оточення вказали директорію (наприклад, '.') — шукаємо у ній user_map.json
        if target_file.is_dir():
            candidate = target_file / 'user_map.json'
            if candidate.exists():
                target_file = candidate
            else:
                logger.error('USER_MAP_PATH вказує на директорію (%s), user_map.json не знайдено всередині', target_file)
                target_file = None  # Явно позначити, що читати нічого

        if target_file and target_file.exists():
            import json

            mapping: dict[str, object] = cast(
                dict[str, object], json.loads(target_file.read_text(encoding='utf-8')),
            )
            key = str(tg_user_id)
            entry = mapping.get(key)
            if isinstance(entry, dict):
                entry_map: dict[str, object] = cast(dict[str, object], entry)
                login_val: object | None = entry_map.get('login')
                email_val: object | None = entry_map.get('email')
                id_val: object | None = entry_map.get('id')
                login = login_val if isinstance(login_val, str) else None
                email = email_val if isinstance(email_val, str) else None
                yt_user_id = id_val if isinstance(id_val, str) else None
            elif isinstance(entry, str):
                # Якщо значення — просто login
                login = entry
        else:
            logger.error('Файл мапи користувачів не знайдено за шляхом: %s', USER_MAP_FILE)
    except Exception as e:  # noqa: BLE001
        logger.exception('Не вдалося прочитати USER_MAP_FILE: %s', e)

    # Інші стратегії можна розширити: email|login будувати з профілю TG тощо
    return login, email, yt_user_id


def _yt_assign_issue(issue_id_readable: str,  # noqa: C901
                     login: Optional[str],
                     email: Optional[str],
                     user_id: Optional[str]) -> bool:  # noqa: C901
    """Призначити задачу в YouTrack на користувача через ``customFields``.

    Отримати внутрішній ID користувача (із мапи або пошуку) і встановити поле «Виконавець».

    :param issue_id_readable: Читабельний ID задачі (``ID-123``).
    :type issue_id_readable: str
    :param login: Логін користувача YouTrack (опційно).
    :type login: str | None
    :param email: Email користувача YouTrack (опційно).
    :type email: str | None
    :param user_id: Внутрішній ID користувача YouTrack (якщо відомо).
    :type user_id: str | None
    :returns: ``True`` у разі успіху.
    :rtype: bool
    """
    try:
        assert YT_BASE_URL and YT_TOKEN
        headers = {
            'Authorization': f'Bearer {YT_TOKEN}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

        # Знайти внутрішній ID задачі, щоб працювати з REST API YouTrack
        r = requests.get(
            f'{YT_BASE_URL}/api/issues',
            params={'query': issue_id_readable, 'fields': 'id,idReadable'},
            headers=headers,
            timeout=10,
        )
        if not r.ok:
            logger.error('Помилка пошуку задачі в YouTrack: %s', r.text)
            return False
        items = cast(list[dict[str, object]], r.json() or [])
        issue: Optional[dict[str, object]] = next(
            (it for it in items if it.get('idReadable') == issue_id_readable),
            None,
        )
        if issue is None:
            logger.error('Задачу %s не знайдено у YouTrack', issue_id_readable)
            return False
        issue_id_obj = issue.get('id')
        issue_id: Optional[str] = issue_id_obj if isinstance(issue_id_obj, str) else None
        if not issue_id:
            return False

        # Визначити внутрішній ID користувача YouTrack за логіном або email
        yt_user_id: Optional[str] = user_id
        if not yt_user_id and (login or email):
            ur = requests.get(
                f'{YT_BASE_URL}/api/users',
                params={'query': (login or email or ''), 'fields': 'id,login,email'},
                headers=headers,
                timeout=10,
            )
            if ur.ok:
                users = cast(list[dict[str, object]], ur.json() or [])
                cand = None
                if login:
                    cand = next((u for u in users if u.get('login') == login), None)
                if cand is None and email:
                    cand = next((u for u in users if u.get('email') == email), None)
                if isinstance(cand, dict):
                    id_obj = cand.get('id')
                    yt_user_id = id_obj if isinstance(id_obj, str) else None
        if not yt_user_id:
            logger.error('Не вдалося визначити ID користувача (login=%s, email=%s)', login, email)
            return False

        # Оновити поле «Виконавець» у задачі через REST для customFields
        try:
            fr = requests.get(
                f'{YT_BASE_URL}/api/issues/{issue_id}',
                params={
                    'fields': 'id,customFields(id,name,projectCustomField(id,field(id,name)),value(id,login,email))',
                },
                headers=headers,
                timeout=10,
            )
            if fr.ok:
                issue_full = cast(dict[str, object], fr.json() or {})
                cfs = cast(list[dict[str, object]], issue_full.get('customFields') or [])
                assignee_cf_id: Optional[str] = None
                desired_names = {
                    YOUTRACK_ASSIGNEE_FIELD_NAME.lower(),
                    'assignee',
                }
                # Знайти поле «Виконавець» серед кастомних полів задачі
                for cf in cfs:
                    pcf_map = _as_mapping(cf.get('projectCustomField')) or {}
                    field_map = _as_mapping(pcf_map.get('field')) or {}
                    field_name_obj = field_map.get('name')
                    if isinstance(field_name_obj, str) and field_name_obj.lower() in desired_names:
                        pcf_id_obj = pcf_map.get('id')
                        if isinstance(pcf_id_obj, str):
                            assignee_cf_id = pcf_id_obj
                            break
                if assignee_cf_id:
                    # Підготувати значення для поля на основі знайденого користувача
                    value_payload: dict[str, object] = {'id': yt_user_id, '$type': 'User'}
                    if login:
                        value_payload['login'] = login
                    if email:
                        value_payload['email'] = email
                    payload = {'value': value_payload}
                    ur = requests.post(
                        f'{YT_BASE_URL}/api/issues/{issue_id}/customFields/{assignee_cf_id}',
                        params={'fields': 'id'},
                        json=payload,
                        headers=headers,
                        timeout=10,
                    )
                    if ur.ok:
                        logger.info('Задачу %s призначено на користувача id=%s login=%s',
                                     issue_id_readable,
                                     yt_user_id,
                                     login)
                        return True
                    logger.debug('YouTrack customFields повернув помилку під час призначення: %s', ur.text)
            else:
                logger.debug('Не вдалося отримати customFields задачі %s: %s', issue_id_readable, fr.text)
        except Exception as ee:  # noqa: BLE001
            logger.debug('Виняток під час призначення через customFields: %s', ee)
        logger.error('Не вдалося призначити виконавця через customFields')
        return False
    except Exception as e:  # noqa: BLE001
        logger.exception('Виняток під час призначення виконавця: %s', e)
        return False


def _as_mapping(obj: object | None) -> Optional[Mapping[str, object]]:
    """Повернути ``Mapping``, якщо ``obj`` — ``dict``.

    :param obj: Будь-який обʼєкт.
    :type obj: object | None
    :returns: ``Mapping`` або ``None``.
    :rtype: Mapping[str, object] | None
    """
    if isinstance(obj, dict):
        return cast(Mapping[str, object], obj)
    return None


def _yt_find_issue(issue_id_readable: str) -> Optional[str]:
    """Знайти внутрішній ID задачі за читабельним ID.

    :param issue_id_readable: Значення ``ID-123``.
    :type issue_id_readable: str
    :returns: Внутрішній ID ``"3-118"`` або ``None``.
    :rtype: str | None
    """
    assert YT_BASE_URL and YT_TOKEN
    headers = {
        'Authorization': f'Bearer {YT_TOKEN}',
        'Accept': 'application/json',
    }
    r = requests.get(
        f'{YT_BASE_URL}/api/issues',
        params={'query': issue_id_readable, 'fields': 'id,idReadable'},
        headers=headers,
        timeout=10,
    )
    if not r.ok:
        logger.debug('Не вдалося знайти задачу для оновлення стану: %s', r.text)
        return None
    # Перебрати результати пошуку та повернути внутрішній ID потрібної задачі
    items = cast(list[dict[str, object]], r.json() or [])
    issue = next((it for it in items if it.get('idReadable') == issue_id_readable), None)
    if not issue:
        return None
    iid = issue.get('id')
    return iid if isinstance(iid, str) else None


def _yt_set_state(issue_id_readable: str, desired_state: str) -> bool:  # noqa: C901
    """Встановити статус задачі через ``customFields``.

    :param issue_id_readable: Читабельний ID задачі.
    :type issue_id_readable: str
    :param desired_state: Назва стану в бандлі (наприклад, «В роботі»).
    :type desired_state: str
    :returns: ``True`` у разі успіху.
    :rtype: bool
    """
    try:
        assert YT_BASE_URL and YT_TOKEN
        issue_id = _yt_find_issue(issue_id_readable)
        if not issue_id:
            logger.error('Не знайдено задачу %s під час оновлення стану', issue_id_readable)
            return False
        headers = {
            'Authorization': f'Bearer {YT_TOKEN}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

        # Отримати перелік кастомних полів задачі та знайти поле стану
        fr = requests.get(
            f'{YT_BASE_URL}/api/issues/{issue_id}',
            params={
                'fields': 'customFields(id,name,projectCustomField(id,field(id,name),bundle(values(id,name))))',
            },
            headers=headers,
            timeout=10,
        )
        if not fr.ok:
            logger.warning('Не вдалося отримати customFields задачі %s для оновлення стану: %s', issue_id_readable, fr.text)
            return False
        issue_full = cast(dict[str, object], fr.json() or {})
        cfs = cast(list[dict[str, object]], issue_full.get('customFields') or [])
        desired_names = {YOUTRACK_STATE_FIELD_NAME.lower(), 'state'}
        pcf_id: Optional[str] = None
        value_id: Optional[str] = None
        for cf in cfs:
            pcf_map = _as_mapping(cf.get('projectCustomField')) or {}
            field_map = _as_mapping(pcf_map.get('field')) or {}
            field_name_obj = field_map.get('name')
            if isinstance(field_name_obj, str) and field_name_obj.lower() in desired_names:
                pcf_id_obj = pcf_map.get('id')
                if isinstance(pcf_id_obj, str):
                    pcf_id = pcf_id_obj
                    bundle_map = _as_mapping(pcf_map.get('bundle')) or {}
                    values = cast(list[dict[str, object]], bundle_map.get('values') or [])
                    for v in values:
                        name = v.get('name')
                        if isinstance(name, str) and name == desired_state:
                            vid = v.get('id')
                            if isinstance(vid, str):
                                value_id = vid
                                break
                break
        if pcf_id and value_id:
            # Записати вибране значення у поле стану задачі
            ur = requests.post(
                f'{YT_BASE_URL}/api/issues/{issue_id}/customFields/{pcf_id}',
                params={'fields': 'id'},
                json={'value': {'id': value_id}},
                headers=headers,
                timeout=10,
            )
            if ur.ok:
                logger.info('Оновлено стан задачі %s на "%s"', issue_id_readable, desired_state)
                return True
            logger.debug('YouTrack customFields повернув помилку під час оновлення стану: %s', ur.text)
        else:
            logger.debug('Поле стану або значення не знайдено (field=%s, value=%s)',
                         YOUTRACK_STATE_FIELD_NAME,
                         desired_state)

        # Без командного API — лише customFields, щоб уникнути затримок
        return False
    except Exception as e:  # noqa: BLE001
        logger.debug('Виняток під час оновлення стану: %s', e)
        return False
