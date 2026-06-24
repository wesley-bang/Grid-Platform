from __future__ import annotations

from tests.helpers import auth, login, register, upload_sprite


def setup_sprites(client):
    register(client)
    token = login(client)
    sprites = [
        upload_sprite(client, token, name, "character").json()
        for name in ("alpha", "beta", "gamma")
    ]
    return token, sprites


def test_create_update_list_and_export_pack(client):
    token, sprites = setup_sprites(client)
    created = client.post(
        "/packs",
        headers=auth(token),
        json={"name": " 角色素材 ", "sprite_ids": [sprites[2]["id"], sprites[0]["id"]]},
    )
    assert created.status_code == 201, created.text
    pack = created.json()
    assert [item["position"] for item in pack["sprites"]] == [0, 1]
    assert [item["id"] for item in pack["sprites"]] == [sprites[2]["id"], sprites[0]["id"]]

    listing = client.get("/packs", headers=auth(token), params={"mine": "true"})
    assert listing.status_code == 200
    assert listing.json()["items"][0]["sprite_count"] == 2

    updated = client.patch(
        f"/packs/{pack['id']}",
        headers=auth(token),
        json={"name": "新版", "sprite_ids": [sprites[1]["id"]]},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "新版"
    assert [item["id"] for item in updated.json()["sprites"]] == [sprites[1]["id"]]

    exported = client.get(f"/packs/{pack['id']}/export")
    assert exported.status_code == 200
    data = exported.json()
    assert data["schema_version"] == 1
    assert data["sprites"][0]["position"] == 0
    assert len(data["sprites"][0]["image_data"]) > 4096


def test_duplicate_and_missing_sprite_ids_roll_back(client):
    token, sprites = setup_sprites(client)
    duplicate = client.post(
        "/packs",
        headers=auth(token),
        json={"name": "bad", "sprite_ids": [sprites[0]["id"], sprites[0]["id"]]},
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["details"][0]["code"] == "DUPLICATE_SPRITE_IN_PACK"

    missing = client.post(
        "/packs",
        headers=auth(token),
        json={"name": "bad", "sprite_ids": [99999]},
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["details"][0]["code"] == "SPRITE_IDS_NOT_FOUND"
    assert client.get("/packs").json()["pagination"]["total_items"] == 0


def test_empty_patch_is_400_and_non_owner_is_forbidden(client):
    token, _sprites = setup_sprites(client)
    pack = client.post(
        "/packs", headers=auth(token), json={"name": "pack", "sprite_ids": []}
    ).json()
    empty = client.patch(f"/packs/{pack['id']}", headers=auth(token), json={})
    assert empty.status_code == 400

    register(client, "other@example.com")
    other = login(client, "other@example.com")
    forbidden = client.patch(
        f"/packs/{pack['id']}", headers=auth(other), json={"name": "stolen"}
    )
    assert forbidden.status_code == 403


def test_deleting_sprite_reindexes_every_affected_pack(client):
    token, sprites = setup_sprites(client)
    first = client.post(
        "/packs",
        headers=auth(token),
        json={"name": "first", "sprite_ids": [item["id"] for item in sprites]},
    ).json()
    second = client.post(
        "/packs",
        headers=auth(token),
        json={"name": "second", "sprite_ids": [sprites[1]["id"], sprites[2]["id"]]},
    ).json()

    deleted = client.delete(f"/sprites/{sprites[1]['id']}", headers=auth(token))
    assert deleted.status_code == 204, deleted.text
    first_after = client.get(f"/packs/{first['id']}").json()
    second_after = client.get(f"/packs/{second['id']}").json()
    assert [(item["position"], item["id"]) for item in first_after["sprites"]] == [
        (0, sprites[0]["id"]),
        (1, sprites[2]["id"]),
    ]
    assert [(item["position"], item["id"]) for item in second_after["sprites"]] == [
        (0, sprites[2]["id"])
    ]


def test_mine_requires_token_and_invalid_optional_token_is_rejected(client):
    assert client.get("/packs", params={"mine": "true"}).status_code == 401
    invalid = client.get(
        "/packs",
        params={"mine": "false"},
        headers={"Authorization": "Bearer invalid"},
    )
    assert invalid.status_code == 401

