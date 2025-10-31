"""Містить україномовні шаблони повідомлень."""

from __future__ import annotations

from collections.abc import Mapping

from .keys import Msg

# Зберігають сталі текстові шаблони для локалі ``uk``
UK: Mapping[Msg, str] = {
    # Інформаційні повідомлення
    Msg.CALLBACK_ACCEPTED: 'Прийнято ✅',
    Msg.TG_BTN_ACCEPT_ISSUE: 'Прийняти',
    Msg.YT_ISSUE_NO_ID: '(без ID)',
    Msg.CONNECT_START_NEW: (
        '👋 Привіт! Щоб користуватись ботом, підключи свій персональний <b>токен YouTrack</b>.\n\n'
        'Використай команду /connect <code>&lt;токен&gt;</code>.'
    ),
    Msg.CONNECT_START_REGISTERED: (
        '🔗 Ти підключений як <b>{login}</b> ({email}).\n\n'
        'Щоб оновити токен – надішли /connect <code>&lt;новий токен&gt;</code>.\n'
        'Для відʼєднання скористайся /unlink.'
    ),
    Msg.CONNECT_GUIDE_BUTTON: 'Як отримати токен',
    Msg.CONNECT_HELP: '👋 Щоб почати роботу, надішли свій <b>YouTrack токен</b> командою /connect <code>&lt;токен&gt;</code>.',
    Msg.CONNECT_EXPECTS_TOKEN: '📋 <b>Формат:</b> /connect <code>&lt;токен&gt;</code>.',
    Msg.CONNECT_SUCCESS_NEW: '🚀 Готово! Тебе підключено до YouTrack',
    Msg.CONNECT_SUCCESS_UPDATED: '🔄 Токен успішно оновлено.',
    Msg.CONNECT_CONFIRM_PROMPT: '🔐 Ти вже підключений як <b>{login}</b> ({email}).\nХочеш оновити токен?',
    Msg.CONNECT_CONFIRM_YES_BUTTON: '✅ Так, онови',
    Msg.CONNECT_CONFIRM_NO_BUTTON: '🚫 Ні, залишити як є',
    Msg.CONNECT_CANCELLED: '❎ Оновлення скасовано.',
    Msg.CONNECT_NEEDS_START: 'ℹ️ Щоб користуватись ботом, почни зі /start.',
    Msg.CONNECT_SHORTCUT_PROMPT: '🔁 Хочеш оновити токен? Просто надішли /connect <code>&lt;новий токен&gt;</code> і підтвердь.',
    Msg.CONNECT_FAILURE_INVALID: '❌ Токен недійсний або користувача немає в проєкті.',
    Msg.CONNECT_ALREADY_LINKED: '🚫 Цей YouTrack-акаунт уже привʼязаний до іншого Telegram.',
    Msg.CONNECT_ALREADY_CONNECTED: '🟢 Ти вже підключений до цього акаунта – нічого змінювати не потрібно.',
    Msg.UNLINK_CONFIRM_PROMPT: '⚙️ Відʼєднати цей YouTrack-акаунт?',
    Msg.UNLINK_CONFIRM_YES_BUTTON: '✅ Так, відʼєднати',
    Msg.UNLINK_CONFIRM_NO_BUTTON: '🚫 Залишити як є',
    Msg.UNLINK_CANCELLED: '❎ Відʼєднання скасовано.',

    Msg.AUTH_LINK_TEMPORARY: '⚠️ YouTrack зараз недоступний. Спробуй трохи пізніше.',
    Msg.AUTH_LINK_CONFIG: '⚙️ Помилка конфігурації сервера.',
    Msg.AUTH_REQUIRED: 'ℹ️ Спершу відкрий довідку через /start.',
    Msg.AUTH_NOTHING_TO_UNLINK: '🙃 Ти ще не підключений, тому відʼєднувати нічого.',
    Msg.AUTH_UNLINK_DONE: '🔓 Доступ відʼєднано. Щоб повернути – виконай /connect <code>&lt;новий токен&gt;</code> знову.',

    # Помилки та попередження
    Msg.ERR_TG_ID_UNAVAILABLE: 'Не вдалося визначити Ваш Telegram ID. Спробуйте пізніше.',
    Msg.ERR_LOGIN_TAKEN: 'Цей логін вже закріплено за іншим користувачем.',
    Msg.ERR_CONFIRM_MISMATCH: 'Очікується підтвердження для логіна {expected}, а не {actual}.',
    Msg.ERR_NO_PENDING: 'Немає запиту на підтвердження логіна для цього користувача.',
    Msg.ERR_STORAGE: 'Сталася помилка при збереженні даних.',
    Msg.ERR_UNKNOWN: 'Сталася непередбачувана помилка. Спробуйте пізніше.',
    Msg.ERR_YT_NOT_CONFIGURED: 'YouTrack інтеграція не налаштована.',
    Msg.ERR_YT_TOKEN_MISSING: 'YouTrack токен не налаштовано.',
    Msg.ERR_YT_FETCH: 'Не вдалося отримати дані з YouTrack. Спробуйте пізніше.',
    Msg.ERR_YT_USER_NOT_FOUND: 'Користувача з таким логіном у YouTrack не знайдено.',
    Msg.ERR_YT_ISSUE_NO_URL: 'Невідомо URL заявки.',
    Msg.ERR_YT_DESCRIPTION_EMPTY: 'Заявка не має опису.',
    Msg.ERR_CALLBACK_RIGHTS: 'Недостатньо прав',
    Msg.ERR_CALLBACK_AUTH_REQUIRED: 'Спершу авторизуйся через /connect та персональний токен YouTrack.',
    Msg.ERR_CALLBACK_UNKNOWN: 'Невідома дія',
    Msg.ERR_CALLBACK_ASSIGN_FAILED: 'Не вдалося призначити',
    Msg.ERR_CALLBACK_ASSIGN_ERROR: 'Помилка: не вдалось прийняти',
    Msg.ERR_STORAGE_GENERIC: 'Не вдалося зберегти дані.',
}
