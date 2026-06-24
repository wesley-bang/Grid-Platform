from __future__ import annotations

from tests.helpers import auth, image_bytes, login, register, upload_sprite


def setup_user(client):
    register(client)
    return login(client)


def test_upload_normalizes_name_tags_and_scales_to_rgba(client):
    token = setup_user(client)
    response = upload_sprite(
        client,
        token,
        "  幽靈  ",
        " Player, player ,CHARACTER ",
        image_bytes((64, 32), (255, 0, 0, 255)),
    )
    assert response.status_code == 201, response.text
    sprite = response.json()
    assert sprite["name"] == "幽靈"
    assert sprite["tags"] == "player,character"

    raw = client.get(sprite["image_url"])
    assert raw.status_code == 200
    assert raw.headers["content-type"] == "application/octet-stream"
    assert raw.headers["content-length"] == "4096"
    assert len(raw.content) == 4096
    pixels = raw.content
    assert pixels[:4] == bytes((0, 0, 0, 0))
    center_start = (8 * 32) * 4
    assert pixels[center_start:center_start + 4] == bytes((255, 0, 0, 255))
    bottom_start = (24 * 32) * 4
    assert pixels[bottom_start:bottom_start + 4] == bytes((0, 0, 0, 0))


def test_image_declarations_must_match_and_extra_form_is_rejected(client):
    token = setup_user(client)
    mismatch = upload_sprite(
        client,
        token,
        "bad",
        content=image_bytes(),
        filename="sprite.jpg",
        content_type="image/jpeg",
    )
    assert mismatch.status_code == 415
    assert mismatch.json()["error"]["code"] == "INVALID_IMAGE_FORMAT"

    extra = client.post(
        "/sprites",
        headers=auth(token),
        data={"name": "valid", "tags": "", "unexpected": "x"},
        files={"file": ("sprite.png", image_bytes(), "image/png")},
    )
    assert extra.status_code == 422
    assert extra.json()["error"]["details"][0]["code"] == "EXTRA_FIELD"


def test_name_tag_validation_and_file_limit(client):
    token = setup_user(client)
    invalid = upload_sprite(client, token, "bad\nname", "a,,b")
    assert invalid.status_code == 422
    codes = {item["code"] for item in invalid.json()["error"]["details"]}
    assert {"NAME_CONTROL_CHARACTER", "TAG_REQUIRED"} <= codes

    too_large = upload_sprite(
        client,
        token,
        "large",
        content=b"x" * (5 * 1024 * 1024 + 1),
    )
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_search_escapes_like_wildcards_and_stable_pagination(client):
    token = setup_user(client)
    assert upload_sprite(client, token, "100% hero", "enemy").status_code == 201
    assert upload_sprite(client, token, "plain hero", "enemy").status_code == 201
    assert upload_sprite(client, token, "under_score", "friend").status_code == 201

    percent = client.get("/sprites", params={"name": "%", "sort": "name_asc"})
    assert [item["name"] for item in percent.json()["items"]] == ["100% hero"]
    underscore = client.get("/sprites", params={"name": "_"})
    assert [item["name"] for item in underscore.json()["items"]] == ["under_score"]
    beyond = client.get("/sprites", params={"page": 9, "page_size": 2})
    assert beyond.status_code == 200
    assert beyond.json()["items"] == []

    extra = client.get("/sprites", params={"unknown": "x"})
    assert extra.status_code == 422


def test_multi_tag_and_or_search(client):
    token = setup_user(client)
    upload_sprite(client, token, "both", "enemy,character")
    upload_sprite(client, token, "enemy", "enemy")
    upload_sprite(client, token, "friend", "friend")
    and_result = client.get(
        "/sprites", params={"tags": "enemy,character", "tag_mode": "and"}
    )
    assert [item["name"] for item in and_result.json()["items"]] == ["both"]
    or_result = client.get(
        "/sprites", params={"tags": "character,friend", "tag_mode": "or", "sort": "name_asc"}
    )
    assert [item["name"] for item in or_result.json()["items"]] == ["both", "friend"]


def test_only_owner_can_delete_sprite(client):
    token = setup_user(client)
    sprite = upload_sprite(client, token, "owned").json()
    register(client, "other@example.com")
    other = login(client, "other@example.com")
    forbidden = client.delete(f"/sprites/{sprite['id']}", headers=auth(other))
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "SPRITE_FORBIDDEN"
