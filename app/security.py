from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import ulid
from fastapi import Request
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import RevokedAccessToken, utc_now_naive


ALGORITHM = "HS256"
ACCESS_TOKEN_SECONDS = 3600
_MAX_JTI_LENGTH = 64


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: int
    jti: str
    expires_at: int


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
        "jti": str(ulid.new()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ACCESS_TOKEN_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> AccessTokenClaims:
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

    if not {"sub", "jti", "iat", "exp"}.issubset(payload):
        raise ApiError(401, "AUTH_TOKEN_INVALID")
    jti = payload["jti"]
    if not isinstance(jti, str) or not jti.strip() or len(jti) > _MAX_JTI_LENGTH:
        raise ApiError(401, "AUTH_TOKEN_INVALID")
    try:
        user_id = int(payload["sub"])
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
    except (TypeError, ValueError) as exc:
        raise ApiError(401, "AUTH_TOKEN_INVALID") from exc
    if user_id < 1 or expires_at <= issued_at:
        raise ApiError(401, "AUTH_TOKEN_INVALID")
    return AccessTokenClaims(user_id=user_id, jti=jti.strip(), expires_at=expires_at)


def token_from_request(request: Request, required: bool) -> AccessTokenClaims | None:
    header = request.headers.get("Authorization")
    if not header:
        if required:
            raise ApiError(401, "AUTH_TOKEN_MISSING")
        return None
    scheme, separator, token = header.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "AUTH_TOKEN_INVALID")
    return decode_access_token(token.strip())


def reject_revoked_token(db: Session, jti: str) -> None:
    if db.get(RevokedAccessToken, jti) is not None:
        raise ApiError(401, "AUTH_TOKEN_INVALID")


def revoke_access_token(db: Session, claims: AccessTokenClaims) -> None:
    db.execute(
        delete(RevokedAccessToken).where(RevokedAccessToken.expires_at <= utc_now_naive())
    )
    db.add(
        RevokedAccessToken(
            jti=claims.jti,
            expires_at=datetime.fromtimestamp(
                claims.expires_at, timezone.utc
            ).replace(tzinfo=None),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
