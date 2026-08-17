from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Pack, PackSprite, Sprite, User


def test_database_checks_foreign_keys_and_delete_actions(db_session):
    user = User(username="owner", email="owner@example.com", password_hash="hash")
    db_session.add(user)
    db_session.flush()
    sprite = Sprite(
        name="sprite",
        tags="",
        image_data=b"\x00" * 4096,
        owner_id=user.id,
    )
    pack = Pack(name="pack", owner_id=user.id)
    db_session.add_all([sprite, pack])
    db_session.flush()
    db_session.add(PackSprite(pack_id=pack.id, sprite_id=sprite.id, position=0))
    db_session.commit()

    db_session.delete(user)
    db_session.commit()
    db_session.refresh(sprite)
    db_session.refresh(pack)
    assert sprite.owner_id is None
    assert pack.owner_id is None

    db_session.delete(sprite)
    db_session.commit()
    assert db_session.query(PackSprite).count() == 0


def test_sqlite_enables_wal_and_busy_timeout(tmp_path):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{(tmp_path / 'grid.db').as_posix()}")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_database_rejects_invalid_blob_and_negative_position(db_session):
    invalid_sprite = Sprite(name="bad", tags="", image_data=b"x")
    db_session.add(invalid_sprite)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    sprite = Sprite(name="ok", tags="", image_data=b"\x00" * 4096)
    pack = Pack(name="pack")
    db_session.add_all([sprite, pack])
    db_session.flush()
    db_session.add(PackSprite(pack_id=pack.id, sprite_id=sprite.id, position=-1))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
