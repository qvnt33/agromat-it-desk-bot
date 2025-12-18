"""One-off migration script: copy data from SQLite into MySQL."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

import pymysql  # type: ignore[import-untyped]
from dotenv import load_dotenv

import agromat_help_desk_bot.config as config
from agromat_help_desk_bot.storage.database import migrate

load_dotenv()


def _sqlite_rows(connection: sqlite3.Connection, query: str) -> Iterable[Mapping[str, Any]]:
    """Yield rows from SQLite query with dict-like access."""
    cursor = connection.execute(query)
    for row in cursor.fetchall():
        yield row


def _connect_sqlite() -> sqlite3.Connection:
    """Return connection to source SQLite database."""
    path_env: str | None = os.getenv('DATABASE_PATH')
    sqlite_path: Path = Path(path_env) if path_env else config.DATABASE_PATH
    connection = sqlite3.connect(str(sqlite_path))
    connection.row_factory = cast(Any, sqlite3.Row)
    return connection


def _connect_mysql() -> pymysql.Connection:
    """Return connection to target MySQL database."""
    if config.MYSQL_USER is None or config.MYSQL_PASSWORD is None:
        raise RuntimeError('MYSQL_USER та MYSQL_PASSWORD обовʼязкові для міграції')
    return pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset=config.MYSQL_CHARSET,
        autocommit=False,
    )


def _copy_users(sqlite_conn: sqlite3.Connection, mysql_conn: pymysql.Connection) -> None:
    """Copy users from SQLite to MySQL."""
    with mysql_conn.cursor() as cursor:
        for row in _sqlite_rows(sqlite_conn, 'SELECT * FROM users'):
            cursor.execute(
                """
                INSERT INTO users(
                    tg_user_id, yt_user_id, yt_login, yt_email, token_hash,
                    token_created_at, token_encrypted, is_active, last_seen_at,
                    registered_at, created_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    yt_user_id=VALUES(yt_user_id),
                    yt_login=VALUES(yt_login),
                    yt_email=VALUES(yt_email),
                    token_hash=VALUES(token_hash),
                    token_created_at=VALUES(token_created_at),
                    token_encrypted=VALUES(token_encrypted),
                    is_active=VALUES(is_active),
                    last_seen_at=VALUES(last_seen_at),
                    registered_at=VALUES(registered_at),
                    updated_at=VALUES(updated_at)
                """,
                (
                    row['tg_user_id'],
                    row['yt_user_id'],
                    row['yt_login'],
                    row['yt_email'],
                    row['token_hash'],
                    row['token_created_at'],
                    row['token_encrypted'],
                    int(row['is_active'] or 0),
                    row['last_seen_at'],
                    row['registered_at'],
                    row['created_at'],
                    row['updated_at'],
                ),
            )


def _copy_issue_messages(sqlite_conn: sqlite3.Connection, mysql_conn: pymysql.Connection) -> None:
    """Copy issue message mappings from SQLite to MySQL."""
    with mysql_conn.cursor() as cursor:
        for row in _sqlite_rows(sqlite_conn, 'SELECT * FROM issue_messages'):
            cursor.execute(
                """
                INSERT INTO issue_messages(issue_id, chat_id, message_id, updated_at, archived)
                VALUES (%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    chat_id=VALUES(chat_id),
                    message_id=VALUES(message_id),
                    updated_at=VALUES(updated_at),
                    archived=VALUES(archived)
                """,
                (
                    row['issue_id'],
                    str(row['chat_id']),
                    row['message_id'],
                    row['updated_at'],
                    int(row['archived'] or 0),
                ),
            )


def _copy_issue_alerts(sqlite_conn: sqlite3.Connection, mysql_conn: pymysql.Connection) -> None:
    """Copy issue alert schedules from SQLite to MySQL."""
    with mysql_conn.cursor() as cursor:
        for row in _sqlite_rows(sqlite_conn, 'SELECT * FROM issue_alerts'):
            cursor.execute(
                """
                INSERT INTO issue_alerts(issue_id, alert_index, chat_id, message_id, send_after, sent_at)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    chat_id=VALUES(chat_id),
                    message_id=VALUES(message_id),
                    send_after=VALUES(send_after),
                    sent_at=VALUES(sent_at)
                """,
                (
                    row['issue_id'],
                    row['alert_index'],
                    str(row['chat_id']),
                    row['message_id'],
                    row['send_after'],
                    row['sent_at'],
                ),
            )


def _copy_settings(sqlite_conn: sqlite3.Connection, mysql_conn: pymysql.Connection) -> None:
    """Copy settings key-value pairs from SQLite to MySQL."""
    with mysql_conn.cursor() as cursor:
        for row in _sqlite_rows(sqlite_conn, 'SELECT * FROM settings'):
            cursor.execute(
                """
                INSERT INTO settings(`key`, value, updated_at)
                VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE value=VALUES(value), updated_at=VALUES(updated_at)
                """,
                (row['key'], row['value'], row['updated_at']),
            )


def main() -> None:
    """Run migration: ensure schema, copy tables from SQLite to MySQL."""
    migrate()  # make sure MySQL schema exists
    sqlite_conn = _connect_sqlite()
    mysql_conn = _connect_mysql()
    try:
        _copy_users(sqlite_conn, mysql_conn)
        _copy_issue_messages(sqlite_conn, mysql_conn)
        _copy_issue_alerts(sqlite_conn, mysql_conn)
        _copy_settings(sqlite_conn, mysql_conn)
        mysql_conn.commit()
        print('Migration completed')
    finally:
        sqlite_conn.close()
        mysql_conn.close()


if __name__ == '__main__':
    main()
