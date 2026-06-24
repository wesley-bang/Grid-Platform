from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOP_LEVEL_KEYS = {"schema_version", "pack_id", "name", "image_spec", "sprites"}
IMAGE_SPEC_KEYS = {"width", "height", "pixel_format", "bytes_per_sprite"}
SPRITE_KEYS = {"position", "id", "name", "tags", "image_data"}

SCHEMA_SQL = """
PRAGMA user_version = 1;

CREATE TABLE pack_info (
    singleton      INTEGER PRIMARY KEY CHECK (singleton = 1),
    source_pack_id INTEGER NOT NULL,
    name           TEXT NOT NULL,
    exported_at    TEXT NOT NULL,
    width          INTEGER NOT NULL CHECK (width = 32),
    height         INTEGER NOT NULL CHECK (height = 32),
    pixel_format   TEXT NOT NULL CHECK (pixel_format = 'RGBA8888')
);

CREATE TABLE sprites (
    position         INTEGER PRIMARY KEY CHECK (position >= 0),
    source_sprite_id INTEGER NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    tags             TEXT NOT NULL DEFAULT '',
    image_data       BLOB NOT NULL CHECK (length(image_data) = 4096)
);

CREATE INDEX idx_assets_sprites_name ON sprites(name);
"""


class ExportValidationError(ValueError):
    pass


def require_exact_keys(value: dict[str, Any], expected: set[str], location: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        raise ExportValidationError(f"{location} 缺少欄位：{', '.join(missing)}")
    if extra:
        raise ExportValidationError(f"{location} 包含未知欄位：{', '.join(extra)}")


def require_int(value: Any, location: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExportValidationError(f"{location} 必須是整數")
    if minimum is not None and value < minimum:
        raise ExportValidationError(f"{location} 不可小於 {minimum}")
    return value


def require_string(value: Any, location: str) -> str:
    if not isinstance(value, str):
        raise ExportValidationError(f"{location} 必須是字串")
    return value


def decode_image_data(value: Any, location: str) -> bytes:
    text = require_string(value, location)
    try:
        encoded = text.encode("ascii")
        raw = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ExportValidationError(f"{location} 必須是標準 Base64 ASCII 字串") from exc
    if len(raw) != 4096:
        raise ExportValidationError(f"{location} 解碼後必須恰好為 4096 bytes")
    return raw


def validate_export(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ExportValidationError("JSON 頂層必須是物件")
    require_exact_keys(data, TOP_LEVEL_KEYS, "頂層")

    if require_int(data["schema_version"], "schema_version") != 1:
        raise ExportValidationError("schema_version 必須等於 1")
    pack_id = require_int(data["pack_id"], "pack_id", minimum=1)
    name = require_string(data["name"], "name")

    image_spec = data["image_spec"]
    if not isinstance(image_spec, dict):
        raise ExportValidationError("image_spec 必須是物件")
    require_exact_keys(image_spec, IMAGE_SPEC_KEYS, "image_spec")
    expected_spec = {
        "width": 32,
        "height": 32,
        "pixel_format": "RGBA8888",
        "bytes_per_sprite": 4096,
    }
    for key, expected in expected_spec.items():
        if image_spec[key] != expected or type(image_spec[key]) is not type(expected):
            raise ExportValidationError(f"image_spec.{key} 必須等於 {expected!r}")

    sprites = data["sprites"]
    if not isinstance(sprites, list):
        raise ExportValidationError("sprites 必須是陣列")

    validated_sprites: list[dict[str, Any]] = []
    positions: set[int] = set()
    sprite_ids: set[int] = set()
    for index, sprite in enumerate(sprites):
        location = f"sprites[{index}]"
        if not isinstance(sprite, dict):
            raise ExportValidationError(f"{location} 必須是物件")
        require_exact_keys(sprite, SPRITE_KEYS, location)
        position = require_int(sprite["position"], f"{location}.position", minimum=0)
        sprite_id = require_int(sprite["id"], f"{location}.id", minimum=1)
        if position in positions:
            raise ExportValidationError(f"{location}.position 重複")
        if sprite_id in sprite_ids:
            raise ExportValidationError(f"{location}.id 重複")
        positions.add(position)
        sprite_ids.add(sprite_id)
        validated_sprites.append(
            {
                "position": position,
                "id": sprite_id,
                "name": require_string(sprite["name"], f"{location}.name"),
                "tags": require_string(sprite["tags"], f"{location}.tags"),
                "image_data": decode_image_data(sprite["image_data"], f"{location}.image_data"),
            }
        )

    expected_positions = set(range(len(validated_sprites)))
    if positions != expected_positions:
        raise ExportValidationError("sprites.position 必須從 0 開始、連續且不重複")
    validated_sprites.sort(key=lambda item: item["position"])
    return {"pack_id": pack_id, "name": name, "sprites": validated_sprites}


def utc_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_assets_db(export: dict[str, Any], output_path: Path) -> None:
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f"{output_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary_path)
        connection.executescript(SCHEMA_SQL)
        connection.execute("BEGIN")
        connection.execute(
            """
            INSERT INTO pack_info (
                singleton, source_pack_id, name, exported_at, width, height, pixel_format
            ) VALUES (1, ?, ?, ?, 32, 32, 'RGBA8888')
            """,
            (export["pack_id"], export["name"], utc_iso_z()),
        )
        connection.executemany(
            """
            INSERT INTO sprites (
                position, source_sprite_id, name, tags, image_data
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    sprite["position"],
                    sprite["id"],
                    sprite["name"],
                    sprite["tags"],
                    sqlite3.Binary(sprite["image_data"]),
                )
                for sprite in export["sprites"]
            ],
        )
        connection.commit()
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result != ("ok",):
            raise RuntimeError(f"PRAGMA quick_check 失敗：{result!r}")
        connection.close()
        connection = None
        os.replace(temporary_path, output_path)
    except Exception:
        if connection is not None:
            connection.rollback()
            connection.close()
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="將 Grid++ 素材包匯出 JSON 安全轉換為 assets.db"
    )
    parser.add_argument("input_json", type=Path, help="素材包匯出 JSON 路徑")
    parser.add_argument("output_db", type=Path, nargs="?", help="輸出 SQLite 路徑")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path: Path = args.input_json
    output_path: Path = args.output_db or input_path.with_name("assets.db")
    try:
        with input_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        export = validate_export(data)
        build_assets_db(export, output_path)
    except (OSError, json.JSONDecodeError, ExportValidationError, sqlite3.Error, RuntimeError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    print(f"已建立：{output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

