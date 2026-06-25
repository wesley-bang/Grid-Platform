from __future__ import annotations

import sqlite3

from alembic import command
from alembic.config import Config


def test_favorites_migration_creates_constraints_and_triggers(tmp_path, monkeypatch):
    database = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    config = Config("alembic.ini")
    command.upgrade(config, "head")

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"favorite_folders", "favorite_folder_sprites"} <= tables
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        assert {
            "trg_favorite_folders_limit",
            "trg_favorite_folder_sprites_limit",
        } <= triggers
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
