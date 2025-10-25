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
    Msg.TG_BTN_ACCEPT_ISSUE: 'Прийняти',
    Msg.YT_ISSUE_NO_ID: '(без ID)',
    Msg.CONNECT_START_NEW: (
        'Привіт! Щоб користуватись ботом, підключи свій персональний токен YouTrack.\n'
        'Використай команду `/connect <токен>.`'
    ),
    Msg.CONNECT_START_REGISTERED: (
        'Ти вже підключений як:\n'
        '• **Login**: {login}\n'
        '• **Email**: {email}\n'
        '• **Project**: {project_key}\n\n'
        'Щоб оновити токен, надішли `/connect <новий токен>`. Для відʼєднання скористайся `/unlink`.'
    ),
    Msg.CONNECT_GUIDE_BUTTON: 'Як отримати токен',
    Msg.CONNECT_HELP: 'Щоб користуватись ботом, підключи свій YouTrack токен командою /connect <токен>.',
    Msg.CONNECT_EXPECTS_TOKEN: 'Формат: /connect <токен>.',
    Msg.CONNECT_SUCCESS_NEW: '✅ Успішно! Ти підключений до YouTrack.',
    Msg.CONNECT_SUCCESS_UPDATED: '🔄 Токен успішно оновлено.',
    Msg.CONNECT_CONFIRM_PROMPT: 'Ти вже підключений як {login} ({email}).\nХочеш оновити токен?',
    Msg.CONNECT_CONFIRM_YES_BUTTON: '✅ Так, оновити',
    Msg.CONNECT_CONFIRM_NO_BUTTON: '🚫 Скасувати',
    Msg.CONNECT_CANCELLED: 'Оновлення токена скасовано.',
    Msg.CONNECT_NEEDS_START: 'Щоб користуватись ботом, почни зі /start.',
    Msg.CONNECT_SHORTCUT_PROMPT: 'Для оновлення токена надішли /connect <новий токен> і підтвердь дію.',
    Msg.CONNECT_FAILURE_INVALID: '❌ Недійсний токен або користувач не входить до проєкту.',
    Msg.CONNECT_ALREADY_LINKED: '❌ Цей YouTrack-акаунт уже привʼязаний до іншого Telegram. Підключення заборонено.',
    Msg.CONNECT_ALREADY_CONNECTED: 'Ти вже підключений до цього YouTrack-акаунта. Змінювати нічого не потрібно.',
    Msg.UNLINK_CONFIRM_PROMPT: 'Відʼєднати цей YouTrack-акаунт від бота?',
    Msg.UNLINK_CONFIRM_YES_BUTTON: '✅ Так, відʼєднати',
    Msg.UNLINK_CONFIRM_NO_BUTTON: '🚫 Залишити як є',
    Msg.UNLINK_CANCELLED: 'Відʼєднання скасовано.',

    Msg.AUTH_WELCOME: (
        'Вітаємо! Щоб отримати доступ до функцій бота, натисни кнопку '
        '“Надіслати YT токен” і відправ свій персональний токен YouTrack.'
    ),
    Msg.AUTH_HELP: 'Для підключення надішли команду /connect <токен>.',
    Msg.AUTH_BUTTON_TEXT: 'Надіслати YT токен',
    Msg.AUTH_EXPECTS_TOKEN: 'Формат: /connect <токен YouTrack>.',
    Msg.AUTH_LINK_SUCCESS: '✅ Доступ активовано: {login} · {email} · {yt_id}',
    Msg.AUTH_LINK_FAILURE: '❌ Недійсний токен або користувач не входить до проєкту.',
    Msg.AUTH_LINK_TEMPORARY: 'YouTrack тимчасово недоступний. Спробуй пізніше.',
    Msg.AUTH_LINK_CONFIG: 'Помилка конфігурації сервера. Звернись до адміністратора.',
    Msg.AUTH_REQUIRED: 'Щоб користуватись ботом, спершу переглянь довідку через /start.',
    Msg.AUTH_NOTHING_TO_UNLINK: 'Доступ ще не активовано, тому нічого відʼєднувати.',
    Msg.AUTH_UNLINK_DONE: 'Доступ скасовано. Щоб повернути його – виконай /connect знову.',

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
    Msg.ERR_YT_ISSUE_NO_URL: 'Невідомо URL заявки.',
    Msg.ERR_YT_DESCRIPTION_EMPTY: 'Заявка не має опису.',
    Msg.ERR_CALLBACK_RIGHTS: 'Недостатньо прав',
    Msg.ERR_CALLBACK_UNKNOWN: 'Невідома дія',
    Msg.ERR_CALLBACK_ASSIGN_FAILED: 'Не вдалося призначити',
    Msg.ERR_CALLBACK_ASSIGN_ERROR: 'Помилка: не вдалось прийняти',
    Msg.ERR_STORAGE_GENERIC: 'Не вдалося зберегти дані.',
}
