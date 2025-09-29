from __future__ import annotations

from enum import Enum


class Msg(str, Enum):
    """Описує ключі локалізованих повідомлень.

    Кожен елемент відповідає шаблону у словнику локалі. Значення формуються
    нижнім регістром, де перший знак підкреслення замінено крапкою для кращої
    групування повідомлень.
    """

    # Групують інформаційні повідомлення
    HELP_REGISTER = 'help.register'
    REGISTER_ALREADY = 'register.already'
    REGISTER_PROMPT_CONFIRM = 'register.prompt_confirm'
    REGISTER_SAVED = 'register.saved'
    REGISTER_UPDATED_NOTE = 'register.updated_note'
    CALLBACK_ACCEPTED = 'callback.accepted'
    CALLBACK_ACCEPT_BUTTON = 'callback.accept_button'
    UTILS_ISSUE_NO_ID = 'utils.issue_no_id'

    # HTTP відповіді
    HTTP_INVALID_PAYLOAD = 'http.invalid_payload'
    HTTP_FORBIDDEN = 'http.forbidden'

    # Telegram служби
    ERR_TELEGRAM_CREDENTIALS = 'err.telegram_credentials'
    ERR_TELEGRAM_TOKEN = 'err.telegram_token'
    ERR_TELEGRAM_API = 'err.telegram_api'

    # Групують помилки та попередження
    ERR_REGISTER_FORMAT = 'err.register_format'
    ERR_CONFIRM_FORMAT = 'err.confirm_format'
    ERR_TG_ID_UNAVAILABLE = 'err.tg_id_unavailable'
    ERR_LOGIN_TAKEN = 'err.login_taken'
    ERR_CONFIRM_MISMATCH = 'err.confirm_mismatch'
    ERR_NO_PENDING = 'err.no_pending'
    ERR_STORAGE = 'err.storage'
    ERR_UNKNOWN = 'err.unknown'
    ERR_YT_NOT_CONFIGURED = 'err.yt_not_configured'
    ERR_YT_TOKEN_MISSING = 'err.yt_token_missing'
    ERR_YT_FETCH = 'err.yt_fetch'
    ERR_YT_USER_NOT_FOUND = 'err.yt_user_not_found'
    ERR_CALLBACK_RIGHTS = 'err.callback_rights'
    ERR_CALLBACK_UNKNOWN = 'err.callback_unknown'
    ERR_CALLBACK_ASSIGN_FAILED = 'err.callback_assign_failed'
    ERR_CALLBACK_ASSIGN_ERROR = 'err.callback_assign_error'
    ERR_STORAGE_GENERIC = 'err.storage_generic'
    ERR_USER_MAP_INPUT_REQUIRED = 'err.user_map_input_required'
    ERR_USER_MAP_EMPTY = 'err.user_map_empty'
    ERR_USER_MAP_YT_TAKEN = 'err.user_map_yt_taken'

    # YouTrack
    ERR_YT_ISSUE_NO_URL = 'err.yt_issue_no_url'
    ERR_YT_DESCRIPTION_EMPTY = 'err.yt_description_empty'
