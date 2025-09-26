"""Валідує допоміжні функції керування user_map.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from agromat_it_desk_bot import utils
from agromat_it_desk_bot.messages import Msg, render


@pytest.fixture()
def tmp_user_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path: Path = tmp_path / 'user_map.json'
    # Переспрямовують шляхи на тимчасовий user_map для тесту
    monkeypatch.setattr(utils, 'USER_MAP_FILE', path)
    return path


def test_is_login_taken_detects_existing(tmp_user_map: Path) -> None:
    """Переконується, що ``is_login_taken`` знаходить зайнятий логін."""
    data: dict[str, dict[str, str]] = {'100': {'login': 'support', 'id': 'YT-1'}}
    tmp_user_map.write_text(json.dumps(data, ensure_ascii=False))

    assert utils.is_login_taken('support') is True
    assert utils.is_login_taken('support', exclude_tg_user_id=100) is False
    assert utils.is_login_taken('another') is False


def test_upsert_user_map_entry_blocks_duplicate_login(tmp_user_map: Path) -> None:
    """Гарантує помилку при спробі привʼязати чужий логін."""
    data: dict[str, dict[str, str]] = {'100': {'login': 'support', 'id': 'YT-1'}}
    tmp_user_map.write_text(json.dumps(data, ensure_ascii=False))

    expected_message: str = render(Msg.ERR_LOGIN_TAKEN)

    with pytest.raises(ValueError, match=re.escape(expected_message)):
        utils.upsert_user_map_entry(200, login='support')


def test_upsert_user_map_entry_allows_same_user_update(tmp_user_map: Path) -> None:
    """Перевіряє успішне оновлення даних для того самого Telegram користувача."""
    utils.upsert_user_map_entry(100, login='support', yt_user_id='YT-1')
    utils.upsert_user_map_entry(100, login='support', email='user@example.com', yt_user_id='YT-1')

    stored: Any = json.loads(tmp_user_map.read_text())
    assert stored == {'100': {'login': 'support', 'email': 'user@example.com', 'id': 'YT-1'}}
