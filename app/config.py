from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_database_url() -> str:
    return f"sqlite:///{(PROJECT_ROOT / 'grid_platform.db').as_posix()}"


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    cors_origins: tuple[str, ...]


@lru_cache
def get_settings() -> Settings:
    """Load and validate process-level application settings."""
    secret = os.getenv("JWT_SECRET")
    if secret is None:
        raise RuntimeError("JWT_SECRET 環境變數為必填")
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET 必須至少為 32 bytes")

    origins = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    )
    if "*" in origins:
        raise RuntimeError("CORS_ORIGINS 不可使用萬用來源 *")

    return Settings(
        database_url=os.getenv("DATABASE_URL", default_database_url()),
        jwt_secret=secret,
        cors_origins=origins,
    )
