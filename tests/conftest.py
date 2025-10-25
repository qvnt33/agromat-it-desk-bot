"""Загальні фікстури для тестів авторизації."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import agromat_it_desk_bot.auth.service as auth_service
import agromat_it_desk_bot.config as config
import agromat_it_desk_bot.storage.database as db


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Направляє всі операції з БД у тимчасовий файл.

    Забезпечує, що тести не торкаються робочого середовища користувача.
    """
    db_path: Path = tmp_path / 'bot.sqlite3'
    monkeypatch.setattr(config, 'DATABASE_PATH', db_path, raising=False)
    monkeypatch.setattr(db, 'DATABASE_PATH', db_path, raising=False)
    monkeypatch.setattr(auth_service, '_migrated', False, raising=False)
    yield
