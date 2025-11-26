"""Перевіряє допоміжні операції з issue_messages."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import agromat_it_desk_bot.config as config
import agromat_it_desk_bot.storage.database as db


def _update_issue_message(issue_id: str, *, updated_at: str, archived: int = 0) -> None:
    connection = sqlite3.connect(str(config.DATABASE_PATH))
    connection.execute(
        'UPDATE issue_messages SET updated_at = ?, archived = ? WHERE issue_id = ?',
        (updated_at, archived, issue_id),
    )
    connection.commit()
    connection.close()


def _fetch_archived_flag(issue_id: str) -> int:
    connection = sqlite3.connect(str(config.DATABASE_PATH))
    cursor = connection.execute('SELECT archived FROM issue_messages WHERE issue_id = ?', (issue_id,))
    row = cursor.fetchone()
    connection.close()
    return int(row[0]) if row else -1


def test_fetch_stale_issue_messages_returns_old_records(isolated_database: None) -> None:
    """Якщо останнє оновлення старіше дедлайну – запис повертається."""
    del isolated_database
    db.upsert_issue_message('ID-1', 123, 456)
    old_timestamp = (datetime.now(tz=timezone.utc) - timedelta(days=2)).isoformat()
    _update_issue_message('ID-1', updated_at=old_timestamp)

    cutoff = datetime.now(tz=timezone.utc).isoformat()
    records = db.fetch_stale_issue_messages(cutoff)

    assert records, 'Очікували щонайменше один запис'
    assert records[0]['issue_id'] == 'ID-1'


def test_mark_issue_archived_sets_flag(isolated_database: None) -> None:
    """Позначення архівом виставляє прапорець у issue_messages."""
    del isolated_database
    db.upsert_issue_message('ID-2', 321, 654)
    db.mark_issue_archived('ID-2')

    assert _fetch_archived_flag('ID-2') == 1
