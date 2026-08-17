from __future__ import annotations

from jose import jwt

from app.config import get_settings
from tests.helpers import auth, login, register


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_register_normalizes_email_and_returns_z_time(client):
    response = register(client, "  User@Example.COM  ", "長密碼" * 32)
    assert response.status_code == 201
    assert response.json()["username"] == "User"
    assert response.json()["email"] == "user@example.com"
    assert response.json()["created_at"].endswith("Z")
    assert "password_hash" not in response.json()

    token = login(client, "USER@example.com", "長密碼" * 32)
    payload = jwt.decode(
        token,
        get_settings().jwt_secret,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )
    assert {"sub", "jti", "iat", "exp"} <= payload.keys()
    assert isinstance(payload["jti"], str) and payload["jti"]
    assert payload["exp"] - payload["iat"] == 3600


def test_duplicate_email_and_login_do_not_disclose_account_state(client):
    assert register(client).status_code == 201
    duplicate = register(client, username="different-name")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"

    duplicate_username = register(
        client,
        "another@example.com",
        username="USER",
    )
    assert duplicate_username.status_code == 409
    assert duplicate_username.json()["error"]["code"] == "USERNAME_ALREADY_REGISTERED"

    missing = client.post(
        "/auth/login",
        json={"email": "missing@example.com", "password": "password123"},
    )
    wrong = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "nottherightone"},
    )
    assert missing.status_code == wrong.status_code == 401
    assert missing.json()["error"]["code"] == wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert missing.json()["error"]["message"] == wrong.json()["error"]["message"]


def test_json_media_type_extra_fields_and_malformed_json(client):
    wrong_media = client.post(
        "/auth/register",
        content='{"username":"a","email":"a@example.com","password":"password123"}',
        headers={"Content-Type": "text/plain"},
    )
    assert wrong_media.status_code == 415
    assert wrong_media.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"

    extra = client.post(
        "/auth/register",
        json={
            "username": "a",
            "email": "a@example.com",
            "password": "password123",
            "admin": True,
        },
    )
    assert extra.status_code == 422
    assert extra.json()["error"]["details"][0]["code"] == "EXTRA_FIELD"

    malformed = client.post(
        "/auth/register",
        content='{"email":',
        headers={"Content-Type": "application/json"},
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "JSON_INVALID"


def test_logout_requires_valid_token_and_has_no_body(client):
    missing = client.post("/auth/logout")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "AUTH_TOKEN_MISSING"

    register(client)
    token = login(client)
    response = client.post("/auth/logout", headers=auth(token))
    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["x-request-id"].startswith("req_")


def test_logout_revokes_only_that_access_token(client):
    register(client)
    first = login(client)
    second = login(client)

    revoked = client.post("/auth/logout", headers=auth(first))
    assert revoked.status_code == 204
    again = client.post("/auth/logout", headers=auth(first))
    assert again.status_code == 204

    rejected = client.get("/users/me", headers=auth(first))
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "AUTH_TOKEN_INVALID"

    mine = client.get("/sprites", params={"mine": "true"}, headers=auth(first))
    assert mine.status_code == 401
    assert mine.json()["error"]["code"] == "AUTH_TOKEN_INVALID"

    remaining = client.get("/users/me", headers=auth(second))
    assert remaining.status_code == 200
    assert remaining.json()["email"] == "user@example.com"


def test_access_token_without_jti_is_rejected(client):
    register(client)
    token = login(client)
    payload = jwt.decode(
        token,
        get_settings().jwt_secret,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )
    del payload["jti"]
    forged = jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")

    response = client.get("/users/me", headers=auth(forged))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_TOKEN_INVALID"
