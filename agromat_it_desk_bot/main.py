"""FastAPI entrypoint and compatibility aliases."""

from __future__ import annotations

import uvicorn

from agromat_it_desk_bot.api.youtrack import youtrack_update, youtrack_webhook  # noqa: F401
from agromat_it_desk_bot.app import create_app
from agromat_it_desk_bot.config import TELEGRAM_CHAT_ID
from agromat_it_desk_bot.services.youtrack_webhook import build_issue_url as _build_issue_url  # noqa: F401
from agromat_it_desk_bot.services.youtrack_webhook import (
    is_edit_window_expired as _is_edit_window_expired,  # noqa: F401
)
from agromat_it_desk_bot.services.youtrack_webhook import prepare_issue_payload as _prepare_issue_payload  # noqa: F401
from agromat_it_desk_bot.services.youtrack_webhook import (
    prepare_payload_for_logging as _prepare_payload_for_logging,  # noqa: F401
)
from agromat_it_desk_bot.telegram import telegram_commands

app = create_app()

__all__ = [
    'app',
    'youtrack_webhook',
    'youtrack_update',
    '_build_issue_url',
    '_is_edit_window_expired',
    '_prepare_issue_payload',
    '_prepare_payload_for_logging',
    'PendingTokenUpdate',
    'pending_token_updates',
    'PendingLoginChange',
    'pending_login_updates',
    'handle_start_command',
    'handle_unlink_command',
    'handle_connect_command',
    'handle_reconnect_command',
    'handle_confirm_reconnect',
    'handle_reconnect_shortcut',
]

_TELEGRAM_CHAT_ID_RESOLVED: int | str
if TELEGRAM_CHAT_ID is None:
    raise RuntimeError('TELEGRAM_CHAT_ID не налаштовано')
try:
    _TELEGRAM_CHAT_ID_RESOLVED = int(TELEGRAM_CHAT_ID)
except ValueError:
    _TELEGRAM_CHAT_ID_RESOLVED = TELEGRAM_CHAT_ID

# Transitional aliases to keep tests/imports compatible
PendingTokenUpdate = telegram_commands.PendingTokenUpdate
pending_token_updates = telegram_commands.pending_token_updates
PendingLoginChange = PendingTokenUpdate
pending_login_updates = pending_token_updates
handle_start_command = telegram_commands.handle_start_command
handle_unlink_command = telegram_commands.handle_unlink_command
handle_connect_command = telegram_commands.handle_connect_command
handle_reconnect_command = telegram_commands.handle_connect_command  # backward compatibility
handle_confirm_reconnect = telegram_commands.handle_confirm_reconnect
handle_reconnect_shortcut = telegram_commands.handle_reconnect_shortcut


def main() -> None:
    """Run Uvicorn server for the FastAPI application."""
    uvicorn.run(app, host='0.0.0.0', port=8080)


if __name__ == '__main__':
    main()
