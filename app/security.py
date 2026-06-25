from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Request
from jose import ExpiredSignatureError, JWTError, jwt

from app.config import get_settings
from app.errors import ApiError


ALGORITHM = "HS256"
ACCESS_TOKEN_SECONDS = 3600


def _bcrypt_input(password: str) -> bytes:
    # Pre-hash so bcrypt safely supports the full password length.
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_input(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ACCESS_TOKEN_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[ALGORITHM],
            options={"verify_aud": False},
        )
    except ExpiredSignatureError as exc:
        raise ApiError(401, "AUTH_TOKEN_EXPIRED") from exc
    except JWTError as exc:
        raise ApiError(401, "AUTH_TOKEN_INVALID") from exc

    if not {"sub", "iat", "exp"}.issubset(payload):
        raise ApiError(401, "AUTH_TOKEN_INVALID")
    try:
        user_id = int(payload["sub"])
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
    except (TypeError, ValueError) as exc:
        raise ApiError(401, "AUTH_TOKEN_INVALID") from exc
    if user_id < 1 or expires_at <= issued_at:
        raise ApiError(401, "AUTH_TOKEN_INVALID")
    return user_id


def token_from_request(request: Request, required: bool) -> int | None:
    header = request.headers.get("Authorization")
    if not header:
        if required:
            raise ApiError(401, "AUTH_TOKEN_MISSING")
        return None
    scheme, separator, token = header.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "AUTH_TOKEN_INVALID")
    return decode_access_token(token.strip())
