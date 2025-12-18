"""Provides access to local storage of Telegram users."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TypedDict

import pymysql  # type: ignore[import-untyped]
from pymysql.cursors import DictCursor  # type: ignore[import-untyped]

import agromat_help_desk_bot.config as config


class DatabaseError(RuntimeError):
    """Indicates a failure when working with local DB."""


class ProjectConfigurationError(RuntimeError):
    """Signals issues with YouTrack project configuration."""


class UserRecord(TypedDict, total=False):
    """Describes a user record in local DB."""

    id: int
    tg_user_id: int
    yt_user_id: str
    yt_login: str
    yt_email: str | None
    token_hash: str | None
    token_created_at: str | None
    token_encrypted: str | None
    is_active: bool
    last_seen_at: str | None
    registered_at: str | None
    created_at: str
    updated_at: str


class IssueAlertRecord(TypedDict):
    """Describes alert for issue in ``New`` status."""

    issue_id: str
    alert_index: int
    chat_id: str
    message_id: int
    send_after: str


class IssueMessageRecord(TypedDict):
    """Describes Telegram message linked to issue."""

    issue_id: str
    chat_id: str
    message_id: int
    updated_at: str


def _is_mysql() -> bool:
    """Check whether MySQL backend is configured."""
    return config.DATABASE_BACKEND == 'mysql'


def _placeholder() -> str:
    """Return parameter placeholder for active backend."""
    return '%s' if _is_mysql() else '?'


def _named_placeholder(name: str) -> str:
    """Return named placeholder for active backend."""
    return f'%({name})s' if _is_mysql() else f':{name}'


def _migrate_sqlite() -> None:
    """Create tables for SQLite backend."""
    path: Path = config.DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id INTEGER NOT NULL UNIQUE,
                yt_user_id TEXT NOT NULL,
                yt_login TEXT NOT NULL,
                yt_email TEXT,
                token_hash TEXT,
                token_created_at TEXT,
                token_encrypted TEXT,
                is_active INTEGER NOT NULL DEFAULT 0,
                last_seen_at TEXT,
                registered_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS issue_messages (
                issue_id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            )
            """,
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS issue_alerts (
                issue_id TEXT NOT NULL,
                alert_index INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                send_after TEXT NOT NULL,
                sent_at TEXT,
                PRIMARY KEY(issue_id, alert_index)
            )
            """,
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_issue_alerts_due
            ON issue_alerts(send_after)
            """,
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        )
        connection.commit()
        _ensure_columns(connection)
        _ensure_issue_message_columns(connection)
        _backfill_registered_at(connection)
        _ensure_unique_index(connection)


def _migrate_mysql() -> None:
    """Create tables for MySQL backend."""
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                tg_user_id BIGINT NOT NULL UNIQUE,
                yt_user_id VARCHAR(64) NOT NULL UNIQUE,
                yt_login VARCHAR(255) NOT NULL,
                yt_email VARCHAR(255),
                token_hash CHAR(64),
                token_created_at VARCHAR(64),
                token_encrypted TEXT,
                is_active TINYINT(1) NOT NULL DEFAULT 0,
                last_seen_at VARCHAR(64),
                registered_at VARCHAR(64) NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                INDEX idx_users_last_seen (last_seen_at)
            )
            """,
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS issue_messages (
                issue_id VARCHAR(255) PRIMARY KEY,
                chat_id VARCHAR(64) NOT NULL,
                message_id BIGINT NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                archived TINYINT(1) NOT NULL DEFAULT 0
            )
            """,
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS issue_alerts (
                issue_id VARCHAR(255) NOT NULL,
                alert_index INT NOT NULL,
                chat_id VARCHAR(64) NOT NULL,
                message_id BIGINT NOT NULL,
                send_after VARCHAR(64) NOT NULL,
                sent_at VARCHAR(64),
                PRIMARY KEY(issue_id, alert_index),
                INDEX idx_issue_alerts_due (send_after)
            )
            """,
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                `key` VARCHAR(255) PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            )
            """,
        )
        connection.commit()
        _ensure_columns(connection)
        _ensure_issue_message_columns(connection)
        _backfill_registered_at(connection)
        _ensure_unique_index(connection)
def migrate() -> None:
    """Create ``users`` table in DB if it does not exist."""
    if _is_mysql():
        _migrate_mysql()
    else:
        _migrate_sqlite()


def _ensure_columns(connection: Any) -> None:
    """Ensure required columns exist in users table."""
    cursor = connection.cursor()
    if _is_mysql():
        cursor.execute('SHOW COLUMNS FROM users')
        columns: set[str] = {str(row['Field']) for row in cursor.fetchall()}
        if 'registered_at' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN registered_at VARCHAR(64) NOT NULL DEFAULT \'\'')
        if 'updated_at' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN updated_at VARCHAR(64) NOT NULL DEFAULT \'\'')
        if 'token_encrypted' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN token_encrypted TEXT')
    else:
        cursor.execute('PRAGMA table_info(users)')
        columns = {str(row['name']) for row in cursor.fetchall()}

        if 'registered_at' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN registered_at TEXT')
        if 'updated_at' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN updated_at TEXT')
        if 'token_encrypted' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN token_encrypted TEXT')
    connection.commit()


def _ensure_issue_message_columns(connection: Any) -> None:
    """Ensure archived column exists in issue_messages table."""
    cursor = connection.cursor()
    if _is_mysql():
        cursor.execute("SHOW TABLES LIKE 'issue_messages'")
        if cursor.fetchone() is None:
            return
        cursor.execute('SHOW COLUMNS FROM issue_messages')
        columns: set[str] = {str(row['Field']) for row in cursor.fetchall()}
        if 'archived' not in columns:
            cursor.execute('ALTER TABLE issue_messages ADD COLUMN archived TINYINT(1) NOT NULL DEFAULT 0')
    else:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='issue_messages'")
        if cursor.fetchone() is None:
            return
        cursor.execute('PRAGMA table_info(issue_messages)')
        columns = {str(row['name']) for row in cursor.fetchall()}
        if 'archived' not in columns:
            cursor.execute('ALTER TABLE issue_messages ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')
    connection.commit()


def _backfill_registered_at(connection: Any) -> None:
    """Populate registered_at for existing records."""
    now: str = _utcnow()
    cursor = connection.cursor()
    placeholder: str = _placeholder()
    cursor.execute(
        """
        UPDATE users
        SET registered_at = COALESCE(
            registered_at,
            created_at,
            token_created_at,
            last_seen_at,
            updated_at,
            {ph}
        )
        WHERE registered_at IS NULL
            OR registered_at = ''
        """.format(ph=placeholder),
        (now,),
    )
    cursor.execute(
        """
        UPDATE users
        SET updated_at = COALESCE(updated_at, last_seen_at, registered_at, created_at, {ph})
        WHERE updated_at IS NULL
            OR updated_at = ''
        """.format(ph=placeholder),
        (now,),
    )
    connection.commit()


def _ensure_unique_index(connection: Any) -> None:
    """Add unique index on ``yt_user_id`` and check duplicates."""
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT yt_user_id, COUNT(*) AS cnt
        FROM users
        GROUP BY yt_user_id
        HAVING cnt > 1
        """,
    )
    duplicates: list[Mapping[str, Any]] = cursor.fetchall()
    if duplicates:
        offenders: str = ', '.join(str(row['yt_user_id']) for row in duplicates)
        raise DatabaseError(
            'Виявлено дублікати YouTrack-акаунтів: '
            f'{offenders}. Видаліть або обʼєднайте записи перед запуском бота.',
        )
    if _is_mysql():
        cursor.execute("SHOW INDEX FROM users WHERE Key_name = 'idx_users_yt_user_id'")
        if cursor.fetchall():
            cursor.execute('DROP INDEX idx_users_yt_user_id ON users')
        cursor.execute("SHOW INDEX FROM users WHERE Key_name = 'idx_users_yt_user_id_unique'")
        if not cursor.fetchall():
            cursor.execute('CREATE UNIQUE INDEX idx_users_yt_user_id_unique ON users(yt_user_id)')
    else:
        cursor.execute("PRAGMA index_list('users')")
        existing_indexes: set[str] = {str(row['name']) for row in cursor.fetchall()}
        if 'idx_users_yt_user_id' in existing_indexes:
            cursor.execute('DROP INDEX idx_users_yt_user_id')
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_yt_user_id_unique
            ON users(yt_user_id)
            """,
        )
    connection.commit()


def upsert_user(record: UserRecord) -> None:
    """Insert or update user in DB.

    :param record: User data to persist.
    :raises DatabaseError: If operation fails.
    """
    _assert_required(record, ('tg_user_id', 'yt_user_id', 'yt_login'))
    now: str = _utcnow()
    tg_user_id: int = int(record['tg_user_id'])
    placeholder: str = _placeholder()

    with _connect() as connection:
        cursor = connection.cursor()
        named = _named_placeholder
        cursor.execute(
            f"""
            SELECT id, registered_at, created_at FROM users WHERE tg_user_id = {placeholder}
            """,
            (tg_user_id,),
        )
        existing: Mapping[str, Any] | None = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT
                id,
                tg_user_id,
                yt_user_id,
                yt_login,
                yt_email,
                token_hash,
                token_created_at,
                token_encrypted,
                is_active,
                last_seen_at,
                registered_at,
                created_at,
                updated_at
            FROM users
            WHERE yt_user_id = {placeholder}
            """,
            (record['yt_user_id'],),
        )
        existing_by_yt: Mapping[str, Any] | None = cursor.fetchone()
        payload: dict[str, object] = {
            'tg_user_id': tg_user_id,
            'yt_user_id': record['yt_user_id'],
            'yt_login': record['yt_login'],
            'yt_email': record.get('yt_email'),
            'token_hash': record.get('token_hash'),
            'token_created_at': record.get('token_created_at'),
            'token_encrypted': record.get('token_encrypted'),
            'is_active': 1 if record.get('is_active', True) else 0,
            'last_seen_at': record.get('last_seen_at'),
            'registered_at': record.get('registered_at'),
            'updated_at': now,
        }

        if existing is None and existing_by_yt is not None and int(existing_by_yt['tg_user_id']) != tg_user_id:
            if payload['registered_at'] is None:
                fallback_registered = existing_by_yt['registered_at'] or existing_by_yt['created_at']
                payload['registered_at'] = str(fallback_registered or now)
            cursor.execute(
                """
                UPDATE users
                SET
                    tg_user_id = {tg_user_id},
                    yt_user_id = {yt_user_id},
                    yt_login = {yt_login},
                    yt_email = {yt_email},
                    token_hash = {token_hash},
                    token_created_at = {token_created_at},
                    token_encrypted = {token_encrypted},
                    is_active = {is_active},
                    last_seen_at = {last_seen_at},
                    registered_at = {registered_at},
                    updated_at = {updated_at}
                WHERE yt_user_id = {yt_user_id}
                """.format(
                    tg_user_id=named('tg_user_id'),
                    yt_user_id=named('yt_user_id'),
                    yt_login=named('yt_login'),
                    yt_email=named('yt_email'),
                    token_hash=named('token_hash'),
                    token_created_at=named('token_created_at'),
                    token_encrypted=named('token_encrypted'),
                    is_active=named('is_active'),
                    last_seen_at=named('last_seen_at'),
                    registered_at=named('registered_at'),
                    updated_at=named('updated_at'),
                ),
                payload,
            )
            connection.commit()
            return

        if existing is None:
            registered_at: str = str(payload['registered_at'] or record.get('created_at') or now)
            payload['registered_at'] = registered_at
            payload['created_at'] = record.get('created_at', registered_at)
            cursor.execute(
                """
                INSERT INTO users(
                    tg_user_id,
                    yt_user_id,
                    yt_login,
                    yt_email,
                    token_hash,
                    token_created_at,
                    token_encrypted,
                    is_active,
                    last_seen_at,
                    registered_at,
                    created_at,
                    updated_at
                ) VALUES (
                    {tg_user_id},
                    {yt_user_id},
                    {yt_login},
                    {yt_email},
                    {token_hash},
                    {token_created_at},
                    {token_encrypted},
                    {is_active},
                    {last_seen_at},
                    {registered_at},
                    {created_at},
                    {updated_at}
                )
                """.format(
                    tg_user_id=named('tg_user_id'),
                    yt_user_id=named('yt_user_id'),
                    yt_login=named('yt_login'),
                    yt_email=named('yt_email'),
                    token_hash=named('token_hash'),
                    token_created_at=named('token_created_at'),
                    token_encrypted=named('token_encrypted'),
                    is_active=named('is_active'),
                    last_seen_at=named('last_seen_at'),
                    registered_at=named('registered_at'),
                    created_at=named('created_at'),
                    updated_at=named('updated_at'),
                ),
                payload,
            )
        else:
            existing_keys = existing.keys()
            existing_registered: object | None = (
                existing['registered_at'] if 'registered_at' in existing_keys else None
            )
            if payload['registered_at'] is None:
                registered_source: object | None = existing_registered or existing['created_at']
                payload['registered_at'] = str(registered_source or now)
            cursor.execute(
                """
                UPDATE users
                SET
                    yt_user_id = {yt_user_id},
                    yt_login = {yt_login},
                    yt_email = {yt_email},
                    token_hash = {token_hash},
                    token_created_at = {token_created_at},
                    token_encrypted = {token_encrypted},
                    is_active = {is_active},
                    last_seen_at = {last_seen_at},
                    registered_at = {registered_at},
                    updated_at = {updated_at}
                WHERE tg_user_id = {tg_user_id}
                """.format(
                    yt_user_id=named('yt_user_id'),
                    yt_login=named('yt_login'),
                    yt_email=named('yt_email'),
                    token_hash=named('token_hash'),
                    token_created_at=named('token_created_at'),
                    token_encrypted=named('token_encrypted'),
                    is_active=named('is_active'),
                    last_seen_at=named('last_seen_at'),
                    registered_at=named('registered_at'),
                    updated_at=named('updated_at'),
                    tg_user_id=named('tg_user_id'),
                ),
                payload,
            )
        connection.commit()


def fetch_user_by_tg_id(tg_user_id: int) -> UserRecord | None:
    """Return active user by Telegram ID."""
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            f"""
            SELECT
                id,
                tg_user_id,
                yt_user_id,
                yt_login,
                yt_email,
                token_hash,
                token_created_at,
                token_encrypted,
                is_active,
                last_seen_at,
                registered_at,
                created_at,
                updated_at
            FROM users
            WHERE tg_user_id = {_placeholder()}
            """,
            (tg_user_id,),
        )
        row: Mapping[str, Any] | None = cursor.fetchone()
        if row is None:
            return None
        return _row_to_record(row)


def fetch_user_by_yt_id(yt_user_id: str) -> UserRecord | None:
    """Return user by YouTrack ID."""
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            f"""
            SELECT
                id,
                tg_user_id,
                yt_user_id,
                yt_login,
                yt_email,
                token_hash,
                token_created_at,
                token_encrypted,
                is_active,
                last_seen_at,
                registered_at,
                created_at,
                updated_at
            FROM users
            WHERE yt_user_id = {_placeholder()}
              AND is_active = 1
            """,
            (yt_user_id,),
        )
        row: Mapping[str, Any] | None = cursor.fetchone()
        if row is None:
            return None
        return _row_to_record(row)


def deactivate_user(tg_user_id: int) -> None:
    """Deactivate user and clear token hash."""
    now: str = _utcnow()
    with _connect() as connection:
        cursor = connection.cursor()
        placeholder: str = _placeholder()
        cursor.execute(
            f"""
            UPDATE users
            SET
                is_active = 0,
                token_hash = NULL,
                token_created_at = NULL,
                token_encrypted = NULL,
                updated_at = {placeholder},
                last_seen_at = {placeholder}
            WHERE tg_user_id = {placeholder}
            """,
            (now, now, tg_user_id),
        )
        connection.commit()


def upsert_issue_message(issue_id: str, chat_id: int | str, message_id: int) -> None:
    """Store or update mapping between issue and Telegram message."""
    now: str = _utcnow()
    chat_value: str = str(chat_id)
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_message_columns(connection)
        if _is_mysql():
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS issue_messages (
                    issue_id VARCHAR(255) PRIMARY KEY,
                    chat_id VARCHAR(64) NOT NULL,
                    message_id BIGINT NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    archived TINYINT(1) NOT NULL DEFAULT 0
                )
                """,
            )
            cursor.execute(
                """
                INSERT INTO issue_messages(issue_id, chat_id, message_id, updated_at, archived)
                VALUES(%s, %s, %s, %s, 0)
                ON DUPLICATE KEY UPDATE
                    chat_id = VALUES(chat_id),
                    message_id = VALUES(message_id),
                    updated_at = VALUES(updated_at),
                    archived = 0
                """,
                (issue_id, chat_value, message_id, now),
            )
        else:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS issue_messages (
                    issue_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                )
                """,
            )
            cursor.execute(
                """
                INSERT INTO issue_messages(issue_id, chat_id, message_id, updated_at, archived)
                VALUES(?, ?, ?, ?, 0)
                ON CONFLICT(issue_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    message_id = excluded.message_id,
                    updated_at = excluded.updated_at,
                    archived = 0
                """,
                (issue_id, chat_value, message_id, now),
            )
        connection.commit()


def fetch_issue_message(issue_id: str) -> dict[str, str | int] | None:
    """Return Telegram message info for issue."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_message_columns(connection)
        cursor.execute(
            f"""
            SELECT issue_id, chat_id, message_id, updated_at
            FROM issue_messages
            WHERE issue_id = {_placeholder()}
            """,
            (issue_id,),
        )
        row: Mapping[str, Any] | None = cursor.fetchone()
        if row is None:
            return None
        return {
            'issue_id': str(row['issue_id']),
            'chat_id': str(row['chat_id']),
            'message_id': int(row['message_id']),
            'updated_at': str(row['updated_at']),
        }


def fetch_stale_issue_messages(older_than_iso: str) -> list[IssueMessageRecord]:
    """Return messages that need archiving."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_message_columns(connection)
        cursor.execute(
            f"""
            SELECT issue_id, chat_id, message_id, updated_at
            FROM issue_messages
            WHERE archived = 0
              AND updated_at <= {_placeholder()}
            """,
            (older_than_iso,),
        )
        rows: list[Mapping[str, Any]] = cursor.fetchall()
        return [
            IssueMessageRecord(
                issue_id=str(row['issue_id']),
                chat_id=str(row['chat_id']),
                message_id=int(row['message_id']),
                updated_at=str(row['updated_at']),
            )
            for row in rows
        ]


def upsert_issue_alerts(
    issue_id: str,
    chat_id: int | str,
    message_id: int,
    alerts: Sequence[tuple[int, str]],
) -> None:
    """Save alert schedule for ``New`` status."""
    if not alerts:
        clear_issue_alerts(issue_id)
        return
    chat_value: str = str(chat_id)
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_alerts_table(cursor)
        placeholder: str = _placeholder()
        cursor.execute(f'DELETE FROM issue_alerts WHERE issue_id = {placeholder}', (issue_id,))
        cursor.executemany(
            f"""
            INSERT INTO issue_alerts(issue_id, alert_index, chat_id, message_id, send_after, sent_at)
            VALUES({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, NULL)
            """,
            [(issue_id, index, chat_value, message_id, send_after) for index, send_after in alerts],
        )
        connection.commit()


def clear_issue_alerts(issue_id: str) -> None:
    """Remove all alerts for issue."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_alerts_table(cursor)
        cursor.execute(f'DELETE FROM issue_alerts WHERE issue_id = {_placeholder()}', (issue_id,))
        connection.commit()


def fetch_due_issue_alerts(limit: int, upper_bound_iso: str) -> list[IssueAlertRecord]:
    """Return alerts whose time has come."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_alerts_table(cursor)
        cursor.execute(
            f"""
            SELECT issue_id, alert_index, chat_id, message_id, send_after
            FROM issue_alerts
            WHERE sent_at IS NULL
                AND send_after <= {_placeholder()}
            ORDER BY send_after ASC
            LIMIT {_placeholder()}
            """,
            (upper_bound_iso, limit),
        )
        rows: list[Mapping[str, Any]] = cursor.fetchall()
        records: list[IssueAlertRecord] = []
        for row in rows:
            records.append({
                'issue_id': str(row['issue_id']),
                'alert_index': int(row['alert_index']),
                'chat_id': str(row['chat_id']),
                'message_id': int(row['message_id']),
                'send_after': str(row['send_after']),
            })
        return records


def mark_issue_alert_sent(issue_id: str, alert_index: int) -> None:
    """Mark alert as sent."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_alerts_table(cursor)
        placeholder: str = _placeholder()
        cursor.execute(
            f"""
            UPDATE issue_alerts
            SET sent_at = {placeholder}
            WHERE issue_id = {placeholder}
                AND alert_index = {placeholder}
            """,
            (_utcnow(), issue_id, alert_index),
        )
        connection.commit()


def mark_issue_archived(issue_id: str) -> None:
    """Mark message as archived."""
    now: str = _utcnow()
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_message_columns(connection)
        placeholder: str = _placeholder()
        cursor.execute(
            f"""
            UPDATE issue_messages
            SET archived = 1,
                updated_at = {placeholder}
            WHERE issue_id = {placeholder}
            """,
            (now, issue_id),
        )
        connection.commit()


def fetch_setting(key: str) -> str | None:
    """Return stored setting value by key or ``None``."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_settings_table(cursor)
        cursor.execute(
            f"""
            SELECT value
            FROM settings
            WHERE `key` = {_placeholder()}
            LIMIT 1
            """,
            (key,),
        )
        row: Mapping[str, Any] | None = cursor.fetchone()
        return str(row['value']) if row else None


def upsert_setting(key: str, value: str) -> None:
    """Insert or update setting value."""
    now: str = _utcnow()
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_settings_table(cursor)
        placeholder: str = _placeholder()
        if _is_mysql():
            cursor.execute(
                f"""
                INSERT INTO settings(`key`, value, updated_at)
                VALUES ({placeholder}, {placeholder}, {placeholder})
                ON DUPLICATE KEY UPDATE value = VALUES(value), updated_at = VALUES(updated_at)
                """,
                (key, value, now),
            )
        else:
            cursor.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )
        connection.commit()


def delete_setting(key: str) -> None:
    """Remove setting by key if exists."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_settings_table(cursor)
        cursor.execute(f'DELETE FROM settings WHERE `key` = {_placeholder()}', (key,))
        connection.commit()


def fetch_alert_suffix(default: str) -> str:
    """Return alert suffix stored in DB or fallback to ``default``."""
    stored: str | None = fetch_setting('alert_suffix')
    if stored is None:
        return default
    return stored


def update_alert_suffix(value: str) -> None:
    """Persist alert suffix value."""
    if value.strip() == '':
        delete_setting('alert_suffix')
        return
    upsert_setting('alert_suffix', value)


def _ensure_issue_alerts_table(cursor: Any) -> None:
    """Ensure issue_alerts table exists."""
    if _is_mysql():
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS issue_alerts (
                issue_id VARCHAR(255) NOT NULL,
                alert_index INT NOT NULL,
                chat_id VARCHAR(64) NOT NULL,
                message_id BIGINT NOT NULL,
                send_after VARCHAR(64) NOT NULL,
                sent_at VARCHAR(64),
                PRIMARY KEY(issue_id, alert_index)
            )
            """,
        )
        cursor.execute("SHOW INDEX FROM issue_alerts WHERE Key_name = 'idx_issue_alerts_due'")
        existing_indexes: list[Mapping[str, Any]] = cursor.fetchall()
        if not existing_indexes:
            cursor.execute('CREATE INDEX idx_issue_alerts_due ON issue_alerts(send_after)')
    else:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS issue_alerts (
                issue_id TEXT NOT NULL,
                alert_index INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                send_after TEXT NOT NULL,
                sent_at TEXT,
                PRIMARY KEY(issue_id, alert_index)
            )
            """,
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_issue_alerts_due
            ON issue_alerts(send_after)
            """,
        )


def _ensure_settings_table(cursor: Any) -> None:
    """Ensure settings table exists."""
    if _is_mysql():
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                `key` VARCHAR(255) PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            )
            """,
        )
    else:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        )


def touch_last_seen(tg_user_id: int) -> None:
    """Update user's ``last_seen_at`` field."""
    now: str = _utcnow()
    with _connect() as connection:
        cursor = connection.cursor()
        placeholder: str = _placeholder()
        cursor.execute(
            f"""
            UPDATE users
            SET last_seen_at = {placeholder}, updated_at = {placeholder}
            WHERE tg_user_id = {placeholder}
            """,
            (now, now, tg_user_id),
        )
        connection.commit()


@contextmanager
def _connect() -> Iterator[Any]:
    """Create database connection."""
    if _is_mysql():
        if config.MYSQL_USER is None or config.MYSQL_PASSWORD is None:
            raise DatabaseError('Налаштуйте MYSQL_USER та MYSQL_PASSWORD')
        connection = pymysql.connect(
            host=config.MYSQL_HOST,
            port=config.MYSQL_PORT,
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            database=config.MYSQL_DATABASE,
            charset=config.MYSQL_CHARSET,
            cursorclass=DictCursor,
            autocommit=False,
        )
        error_class = pymysql.MySQLError
    else:
        path: Path = config.DATABASE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        error_class = sqlite3.Error
    try:
        yield connection
    except error_class as exc:
        connection.rollback()
        prefix: str = 'MySQL' if _is_mysql() else 'SQLite'
        raise DatabaseError(f'Помилка {prefix}: {exc}') from exc
    finally:
        connection.close()


def _row_to_record(row: Mapping[str, Any]) -> UserRecord:
    """Convert SQLite row to ``UserRecord``."""
    result: UserRecord = {
        'id': int(row['id']),
        'tg_user_id': int(row['tg_user_id']),
        'yt_user_id': str(row['yt_user_id']),
        'yt_login': str(row['yt_login']),
        'yt_email': row['yt_email'],
        'token_hash': row['token_hash'],
        'token_created_at': row['token_created_at'],
        'token_encrypted': row['token_encrypted'],
        'is_active': bool(row['is_active']),
        'last_seen_at': row['last_seen_at'],
        'registered_at': row['registered_at'],
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }
    return result


def _utcnow() -> str:
    """Return current time in ISO format."""
    return datetime.now(tz=timezone.utc).isoformat()


def _assert_required(record: UserRecord, fields: tuple[str, ...]) -> None:
    """Check presence of required fields in record."""
    missing: tuple[str, ...] = tuple(field for field in fields if field not in record)
    if missing:
        names: str = ', '.join(missing)
        raise DatabaseError(f'Відсутні обовʼязкові поля: {names}')
