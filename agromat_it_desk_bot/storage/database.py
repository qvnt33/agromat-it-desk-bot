"""Забезпечує доступ до локального сховища користувачів Telegram."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from agromat_it_desk_bot.config import DATABASE_PATH


class DatabaseError(RuntimeError):
    """Вказує на збій під час роботи з локальною БД."""


class ProjectConfigurationError(RuntimeError):
    """Сигналізує про проблеми з конфігурацією проєкту YouTrack."""


class UserRecord(TypedDict, total=False):
    """Описує запис користувача у локальній БД."""

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
    """Описує нагадування для задачі в статусі ``Нова``."""

    issue_id: str
    alert_index: int
    chat_id: str
    message_id: int
    send_after: str


class IssueMessageRecord(TypedDict):
    """Описує Telegram-повідомлення, пов'язане із заявкою."""

    issue_id: str
    chat_id: str
    message_id: int
    updated_at: str


def migrate() -> None:
    """Створює таблицю ``users`` у БД, якщо вона ще не існує."""
    path: Path = DATABASE_PATH
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
        connection.commit()
        _ensure_columns(connection)
        _ensure_issue_message_columns(connection)
        _backfill_registered_at(connection)
        _ensure_unique_index(connection)


def _ensure_columns(connection: sqlite3.Connection) -> None:
    """Гарантує наявність обовʼязкових полів у таблиці users."""
    cursor = connection.cursor()
    cursor.execute('PRAGMA table_info(users)')
    columns: set[str] = {str(row['name']) for row in cursor.fetchall()}

    if 'registered_at' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN registered_at TEXT')
    if 'updated_at' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN updated_at TEXT')
    if 'token_encrypted' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN token_encrypted TEXT')
    connection.commit()


def _ensure_issue_message_columns(connection: sqlite3.Connection) -> None:
    """Гарантує наявність поля archived у таблиці issue_messages."""
    cursor = connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='issue_messages'")
    if cursor.fetchone() is None:
        return
    cursor.execute('PRAGMA table_info(issue_messages)')
    columns: set[str] = {str(row['name']) for row in cursor.fetchall()}
    if 'archived' not in columns:
        cursor.execute('ALTER TABLE issue_messages ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')
    connection.commit()


def _backfill_registered_at(connection: sqlite3.Connection) -> None:
    """Заповнює поле registered_at для наявних записів."""
    now: str = _utcnow()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE users
        SET registered_at = COALESCE(
            registered_at,
            created_at,
            token_created_at,
            last_seen_at,
            updated_at,
            ?
        )
        WHERE registered_at IS NULL
            OR registered_at = ''
        """,
        (now,),
    )
    cursor.execute(
        """
        UPDATE users
        SET updated_at = COALESCE(updated_at, last_seen_at, registered_at, created_at, ?)
        WHERE updated_at IS NULL
            OR updated_at = ''
        """,
        (now,),
    )
    connection.commit()


def _ensure_unique_index(connection: sqlite3.Connection) -> None:
    """Додає унікальний індекс на ``yt_user_id`` та перевіряє відсутність дублікатів."""
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT yt_user_id, COUNT(*) AS cnt
        FROM users
        GROUP BY yt_user_id
        HAVING cnt > 1
        """,
    )
    duplicates: list[sqlite3.Row] = cursor.fetchall()
    if duplicates:
        offenders: str = ', '.join(str(row['yt_user_id']) for row in duplicates)
        raise DatabaseError(
            'Виявлено дублікати YouTrack-акаунтів: '
            f'{offenders}. Видаліть або обʼєднайте записи перед запуском бота.',
        )

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
    """Додає або оновлює користувача в БД.

    :param record: Дані користувача для збереження.
    :raises DatabaseError: Якщо операція завершилася помилкою.
    """
    _assert_required(record, ('tg_user_id', 'yt_user_id', 'yt_login'))
    now: str = _utcnow()
    tg_user_id: int = int(record['tg_user_id'])

    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, registered_at, created_at FROM users WHERE tg_user_id = ?
            """,
            (tg_user_id,),
        )
        existing: sqlite3.Row | None = cursor.fetchone()
        cursor.execute(
            """
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
            WHERE yt_user_id = ?
            """,
            (record['yt_user_id'],),
        )
        existing_by_yt: sqlite3.Row | None = cursor.fetchone()
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
                    tg_user_id = :tg_user_id,
                    yt_user_id = :yt_user_id,
                    yt_login = :yt_login,
                    yt_email = :yt_email,
                    token_hash = :token_hash,
                    token_created_at = :token_created_at,
                    token_encrypted = :token_encrypted,
                    is_active = :is_active,
                    last_seen_at = :last_seen_at,
                    registered_at = :registered_at,
                    updated_at = :updated_at
                WHERE yt_user_id = :yt_user_id
                """,
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
                    :tg_user_id,
                    :yt_user_id,
                    :yt_login,
                    :yt_email,
                    :token_hash,
                    :token_created_at,
                    :token_encrypted,
                    :is_active,
                    :last_seen_at,
                    :registered_at,
                    :created_at,
                    :updated_at
                )
                """,
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
                    yt_user_id = :yt_user_id,
                    yt_login = :yt_login,
                    yt_email = :yt_email,
                    token_hash = :token_hash,
                    token_created_at = :token_created_at,
                    token_encrypted = :token_encrypted,
                    is_active = :is_active,
                    last_seen_at = :last_seen_at,
                    registered_at = :registered_at,
                    updated_at = :updated_at
                WHERE tg_user_id = :tg_user_id
                """,
                payload,
            )
        connection.commit()


def fetch_user_by_tg_id(tg_user_id: int) -> UserRecord | None:
    """Повертає активного користувача за Telegram ID."""
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
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
            WHERE tg_user_id = ?
            """,
            (tg_user_id,),
        )
        row: sqlite3.Row | None = cursor.fetchone()
        if row is None:
            return None
        return _row_to_record(row)


def fetch_user_by_yt_id(yt_user_id: str) -> UserRecord | None:
    """Повертає користувача за YouTrack ID."""
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
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
            WHERE yt_user_id = ?
              AND is_active = 1
            """,
            (yt_user_id,),
        )
        row: sqlite3.Row | None = cursor.fetchone()
        if row is None:
            return None
        return _row_to_record(row)


def deactivate_user(tg_user_id: int) -> None:
    """Деактивує користувача та видаляє хеш токена."""
    now: str = _utcnow()
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE users
            SET
                is_active = 0,
                token_hash = NULL,
                token_created_at = NULL,
                token_encrypted = NULL,
                updated_at = ?,
                last_seen_at = ?
            WHERE tg_user_id = ?
            """,
            (now, now, tg_user_id),
        )
        connection.commit()


def upsert_issue_message(issue_id: str, chat_id: int | str, message_id: int) -> None:
    """Зберігає або оновлює зв'язок між задачею та повідомленням Telegram."""
    now: str = _utcnow()
    chat_value: str = str(chat_id)
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_message_columns(connection)
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
    """Повертає інформацію про повідомлення Telegram для задачі."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_message_columns(connection)
        cursor.execute(
            """
            SELECT issue_id, chat_id, message_id, updated_at
            FROM issue_messages
            WHERE issue_id = ?
            """,
            (issue_id,),
        )
        row: sqlite3.Row | None = cursor.fetchone()
        if row is None:
            return None
        return {
            'issue_id': str(row['issue_id']),
            'chat_id': str(row['chat_id']),
            'message_id': int(row['message_id']),
            'updated_at': str(row['updated_at']),
        }


def fetch_stale_issue_messages(older_than_iso: str) -> list[IssueMessageRecord]:
    """Повертає повідомлення, які потребують архівації."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_message_columns(connection)
        cursor.execute(
            """
            SELECT issue_id, chat_id, message_id, updated_at
            FROM issue_messages
            WHERE archived = 0
              AND updated_at <= ?
            """,
            (older_than_iso,),
        )
        rows: list[sqlite3.Row] = cursor.fetchall()
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
    """Зберігає графік сповіщень про статус ``Нова``."""
    if not alerts:
        clear_issue_alerts(issue_id)
        return
    chat_value: str = str(chat_id)
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_alerts_table(cursor)
        cursor.execute('DELETE FROM issue_alerts WHERE issue_id = ?', (issue_id,))
        cursor.executemany(
            """
            INSERT INTO issue_alerts(issue_id, alert_index, chat_id, message_id, send_after, sent_at)
            VALUES(?, ?, ?, ?, ?, NULL)
            """,
            [(issue_id, index, chat_value, message_id, send_after) for index, send_after in alerts],
        )
        connection.commit()


def clear_issue_alerts(issue_id: str) -> None:
    """Видаляє всі нагадування для задачі."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_alerts_table(cursor)
        cursor.execute('DELETE FROM issue_alerts WHERE issue_id = ?', (issue_id,))
        connection.commit()


def fetch_due_issue_alerts(limit: int, upper_bound_iso: str) -> list[IssueAlertRecord]:
    """Повертає нагадування, час яких настав."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_alerts_table(cursor)
        cursor.execute(
            """
            SELECT issue_id, alert_index, chat_id, message_id, send_after
            FROM issue_alerts
            WHERE sent_at IS NULL
                AND send_after <= ?
            ORDER BY send_after ASC
            LIMIT ?
            """,
            (upper_bound_iso, limit),
        )
        rows: list[sqlite3.Row] = cursor.fetchall()
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
    """Позначає нагадування як надіслане."""
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_alerts_table(cursor)
        cursor.execute(
            """
            UPDATE issue_alerts
            SET sent_at = ?
            WHERE issue_id = ?
                AND alert_index = ?
            """,
            (_utcnow(), issue_id, alert_index),
        )
        connection.commit()


def mark_issue_archived(issue_id: str) -> None:
    """Позначає повідомлення як архівоване."""
    now: str = _utcnow()
    with _connect() as connection:
        cursor = connection.cursor()
        _ensure_issue_message_columns(connection)
        cursor.execute(
            """
            UPDATE issue_messages
            SET archived = 1,
                updated_at = ?
            WHERE issue_id = ?
            """,
            (now, issue_id),
        )
        connection.commit()


def _ensure_issue_alerts_table(cursor: sqlite3.Cursor) -> None:
    """Гарантує наявність таблиці issue_alerts."""
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


def touch_last_seen(tg_user_id: int) -> None:
    """Оновлює поле ``last_seen_at`` для користувача."""
    now: str = _utcnow()
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE users
            SET last_seen_at = ?, updated_at = ?
            WHERE tg_user_id = ?
            """,
            (now, now, tg_user_id),
        )
        connection.commit()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Створює підключення до бази даних."""
    connection = sqlite3.connect(
        str(DATABASE_PATH),
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    except sqlite3.Error as exc:
        connection.rollback()
        raise DatabaseError(f'Помилка SQLite: {exc}') from exc
    finally:
        connection.close()


def _row_to_record(row: sqlite3.Row) -> UserRecord:
    """Перетворює рядок SQLite на ``UserRecord``."""
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
    """Повертає поточний момент часу в ISO-форматі."""
    return datetime.now(tz=timezone.utc).isoformat()


def _assert_required(record: UserRecord, fields: tuple[str, ...]) -> None:
    """Перевіряє наявність обовʼязкових полів у записі."""
    missing: tuple[str, ...] = tuple(field for field in fields if field not in record)
    if missing:
        names: str = ', '.join(missing)
        raise DatabaseError(f'Відсутні обовʼязкові поля: {names}')
