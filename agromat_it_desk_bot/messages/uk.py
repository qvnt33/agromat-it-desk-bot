"""Містить україномовні шаблони повідомлень."""

from __future__ import annotations

from collections.abc import Mapping

from .keys import Msg

# Зберігають сталі текстові шаблони для локалі ``uk``
UK: Mapping[Msg, str] = {
    # Інформаційні повідомлення
    Msg.HELP_REGISTER: (
        'Щоб додати себе до списку дозволених, надішліть команду\n'
        '/register <логін>. Бот підставить решту даних автоматично.'
    ),
    Msg.REGISTER_ALREADY: (
        'Ви вже зареєстровані як {login}.\nЯкщо потрібно змінити логін – надіслати /register {suggested}.'
    ),
    Msg.REGISTER_PROMPT_CONFIRM: 'Запит отримано. Підтвердити зміну: /confirm_login {login}',
    Msg.REGISTER_SAVED: '✅ Дані збережено: {login} · {email} · {yt_id}',
    Msg.REGISTER_UPDATED_NOTE: 'Логін оновлено з {previous} на {current}.',
    Msg.CALLBACK_ACCEPTED: 'Прийнято ✅',
    Msg.CALLBACK_ACCEPT_BUTTON: 'Прийняти',
    Msg.UTILS_ISSUE_NO_ID: '(без ID)',
    Msg.HTTP_INVALID_PAYLOAD: 'Некоректний формат тіла запиту',
    Msg.HTTP_FORBIDDEN: 'Доступ заборонено',
    Msg.ERR_TELEGRAM_CREDENTIALS: 'Конфігурація Telegram відсутня',
    Msg.ERR_TELEGRAM_TOKEN: 'Telegram токен не налаштовано',
    Msg.ERR_TELEGRAM_API: 'Помилка Telegram API: {error}',
    Msg.ERR_STORAGE_GENERIC: 'Не вдалося зберегти дані.',
    Msg.ERR_USER_MAP_INPUT_REQUIRED: 'Потрібно надати принаймні одне з полів: login, email або yt_user_id',
    Msg.ERR_USER_MAP_EMPTY: 'Надано порожні дані для оновлення мапи користувачів',
    Msg.ERR_USER_MAP_YT_TAKEN: 'Цей YouTrack акаунт вже привʼязаний до іншого користувача.',
    # Помилки та попередження
    Msg.ERR_REGISTER_FORMAT: 'Формат команди: /register <логін>',
    Msg.ERR_CONFIRM_FORMAT: 'Формат команди: /confirm_login <логін>',
    Msg.ERR_TG_ID_UNAVAILABLE: 'Не вдалося визначити ваш Telegram ID. Спробуйте пізніше.',
    Msg.ERR_LOGIN_TAKEN: 'Цей логін вже закріплено за іншим користувачем.',
    Msg.ERR_CONFIRM_MISMATCH: 'Очікується підтвердження для логіна {expected}, а не {actual}.',
    Msg.ERR_NO_PENDING: 'Немає запиту на підтвердження логіна для цього користувача.',
    Msg.ERR_STORAGE: 'Сталася помилка при збереженні даних. Адміністратори вже в курсі.',
    Msg.ERR_UNKNOWN: 'Сталася непередбачувана помилка. Спробуйте пізніше.',
    Msg.ERR_YT_NOT_CONFIGURED: 'YouTrack інтеграція не налаштована. Зверніться до адміністратора.',
    Msg.ERR_YT_TOKEN_MISSING: 'YouTrack токен не налаштовано. Зверніться до адміністратора.',
    Msg.ERR_YT_FETCH: 'Не вдалося отримати дані з YouTrack. Спробуйте пізніше.',
    Msg.ERR_YT_USER_NOT_FOUND: 'Користувача з таким логіном у YouTrack не знайдено.',
    Msg.ERR_CALLBACK_RIGHTS: 'Недостатньо прав',
    Msg.ERR_CALLBACK_UNKNOWN: 'Невідома дія',
    Msg.ERR_CALLBACK_ASSIGN_FAILED: 'Не вдалося призначити',
    Msg.ERR_CALLBACK_ASSIGN_ERROR: 'Помилка: не вдалось прийняти',
}
