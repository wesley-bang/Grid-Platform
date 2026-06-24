from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from create_assets import ExportValidationError, build_assets_db, validate_export


def valid_export():
    image = base64.b64encode(bytes(range(256)) * 16).decode("ascii")
    return {
        "schema_version": 1,
        "pack_id": 7,
        "name": "角色素材",
        "image_spec": {
            "width": 32,
            "height": 32,
            "pixel_format": "RGBA8888",
            "bytes_per_sprite": 4096,
        },
        "sprites": [
            {
                "position": 0,
                "id": 3,
                "name": "ghost",
                "tags": "enemy",
                "image_data": image,
            }
        ],
    }


def test_build_assets_database_exact_schema_and_blob(tmp_path):
    output = tmp_path / "assets.db"
    build_assets_db(validate_export(valid_export()), output)
    with sqlite3.connect(output) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        pack = connection.execute(
            "SELECT singleton, source_pack_id, name, width, height, pixel_format FROM pack_info"
        ).fetchone()
        assert pack == (1, 7, "角色素材", 32, 32, "RGBA8888")
        sprite = connection.execute(
            "SELECT position, source_sprite_id, name, tags, length(image_data) FROM sprites"
        ).fetchone()
        assert sprite == (0, 3, "ghost", "enemy", 4096)


def test_strict_unknown_fields_and_invalid_base64_do_not_touch_existing_db(tmp_path):
    output = tmp_path / "assets.db"
    output.write_bytes(b"existing")
    data = valid_export()
    data["unexpected"] = True
    with pytest.raises(ExportValidationError):
        validate_export(data)
    assert output.read_bytes() == b"existing"

    data = valid_export()
    data["sprites"][0]["image_data"] = "not base64!"
    with pytest.raises(ExportValidationError):
        validate_export(data)
    assert output.read_bytes() == b"existing"


def test_positions_must_be_contiguous_but_input_may_be_unsorted():
    data = valid_export()
    second = dict(data["sprites"][0])
    second.update({"position": 1, "id": 4, "name": "player"})
    data["sprites"] = [second, data["sprites"][0]]
    validated = validate_export(data)
    assert [item["position"] for item in validated["sprites"]] == [0, 1]

    data["sprites"][0]["position"] = 2
    with pytest.raises(ExportValidationError):
        validate_export(data)


def test_cli_uses_assets_db_next_to_input_by_default(tmp_path):
    input_path = tmp_path / "pack.json"
    input_path.write_text(json.dumps(valid_export(), ensure_ascii=False), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "create_assets.py"
    result = subprocess.run(
        [sys.executable, str(script), str(input_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "assets.db").exists()
    assert not (tmp_path / "assets.db.tmp").exists()
