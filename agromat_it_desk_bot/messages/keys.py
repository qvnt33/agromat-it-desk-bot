from __future__ import annotations

from enum import Enum


class Msg(str, Enum):
    """Описує ключі локалізованих повідомлень.

    Кожен елемент відповідає шаблону у словнику локалі. Значення формуються
    нижнім регістром, де перший знак підкреслення замінено крапкою для кращої
    групування повідомлень.
    """

    # Інформаційні повідомлення
    HELP_REGISTER = 'help.register'
    REGISTER_ALREADY = 'register.already'
    REGISTER_PROMPT_CONFIRM = 'register.prompt_confirm'
    REGISTER_SAVED = 'register.saved'
    REGISTER_UPDATED_NOTE = 'register.updated_note'
    AUTH_WELCOME = 'auth.welcome'
    AUTH_HELP = 'auth.help'
    AUTH_BUTTON_TEXT = 'auth.button_text'
    AUTH_EXPECTS_TOKEN = 'auth.expects_token'
    AUTH_LINK_SUCCESS = 'auth.link_success'
    AUTH_REQUIRED = 'auth.required'
    AUTH_NOTHING_TO_UNLINK = 'auth.nothing_to_unlink'
    AUTH_UNLINK_DONE = 'auth.unlink_done'
    AUTH_LINK_FAILURE = 'auth.link_failure'
    AUTH_LINK_TEMPORARY = 'auth.link_temporary'
    AUTH_LINK_CONFIG = 'auth.link_config'
    CALLBACK_ACCEPTED = 'callback.accepted'
    TG_BTN_ACCEPT_ISSUE = 'tg.btn_accept_issue'
    YT_ISSUE_NO_ID = 'utils.issue_no_id'
    CONNECT_START_NEW = 'connect.start_new'
    CONNECT_START_REGISTERED = 'connect.start_registered'
    CONNECT_GUIDE_BUTTON = 'connect.guide_button'
    CONNECT_HELP = 'connect.help'
    CONNECT_EXPECTS_TOKEN = 'connect.expects_token'
    CONNECT_SUCCESS_NEW = 'connect.success_new'
    CONNECT_SUCCESS_UPDATED = 'connect.success_updated'
    CONNECT_CONFIRM_PROMPT = 'connect.confirm_prompt'
    CONNECT_CONFIRM_YES_BUTTON = 'connect.confirm_yes_button'
    CONNECT_CONFIRM_NO_BUTTON = 'connect.confirm_no_button'
    CONNECT_CANCELLED = 'connect.cancelled'
    CONNECT_NEEDS_START = 'connect.needs_start'
    CONNECT_SHORTCUT_PROMPT = 'connect.shortcut_prompt'
    CONNECT_FAILURE_INVALID = 'connect.failure_invalid'
    CONNECT_ALREADY_LINKED = 'connect.already_linked'
    CONNECT_ALREADY_CONNECTED = 'connect.already_connected'
    UNLINK_CONFIRM_PROMPT = 'unlink.confirm_prompt'
    UNLINK_CONFIRM_YES_BUTTON = 'unlink.confirm_yes_button'
    UNLINK_CONFIRM_NO_BUTTON = 'unlink.confirm_no_button'
    UNLINK_CANCELLED = 'unlink.cancelled'

    # Помилки та попередження
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
    ERR_YT_ISSUE_NO_URL = 'err.yt_issue_no_url'
    ERR_YT_DESCRIPTION_EMPTY = 'err.yt_description_empty'
    ERR_CALLBACK_RIGHTS = 'err.callback_rights'
    ERR_CALLBACK_UNKNOWN = 'err.callback_unknown'
    ERR_CALLBACK_ASSIGN_FAILED = 'err.callback_assign_failed'
    ERR_CALLBACK_ASSIGN_ERROR = 'err.callback_assign_error'
    ERR_STORAGE_GENERIC = 'err.storage_generic'
