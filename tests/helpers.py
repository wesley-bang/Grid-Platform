from __future__ import annotations

import io

from PIL import Image


def register(client, email: str = "user@example.com", password: str = "password123"):
    return client.post("/auth/register", json={"email": email, "password": password})


def login(client, email: str = "user@example.com", password: str = "password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def image_bytes(
    size: tuple[int, int] = (32, 32),
    color: tuple[int, int, int, int] = (255, 0, 0, 255),
    fmt: str = "PNG",
) -> bytes:
    image = Image.new("RGBA", size, color)
    if fmt == "JPEG":
        image = image.convert("RGB")
    output = io.BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def upload_sprite(
    client,
    token: str,
    name: str,
    tags: str = "",
    content: bytes | None = None,
    filename: str = "sprite.png",
    content_type: str = "image/png",
):
    return client.post(
        "/sprites",
        headers=auth(token),
        data={"name": name, "tags": tags},
        files={"file": (filename, content or image_bytes(), content_type)},
    )

