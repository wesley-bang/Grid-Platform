from __future__ import annotations

import io
import math
import warnings
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.errors import ApiError


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_DIMENSION = 4096
MAX_PIXELS = 16_777_216
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def _declared_family(filename: str | None, content_type: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    extension_family = {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
    }.get(suffix)
    mime_family = {
        "image/png": "PNG",
        "image/jpeg": "JPEG",
        "image/jpg": "JPEG",
    }.get((content_type or "").split(";", 1)[0].strip().lower())
    if extension_family is None or mime_family is None or extension_family != mime_family:
        raise ApiError(415, "INVALID_IMAGE_FORMAT")
    return extension_family


def _check_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if (
        width < 1
        or height < 1
        or width > MAX_DIMENSION
        or height > MAX_DIMENSION
        or width * height > MAX_PIXELS
    ):
        raise ApiError(
            422,
            "IMAGE_DIMENSIONS_TOO_LARGE",
            details={"width": width, "height": height, "max_pixels": MAX_PIXELS},
        )


async def process_upload(upload: UploadFile) -> bytes:
    declared_family = _declared_family(upload.filename, upload.content_type)
    raw = await upload.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE")
    if not raw:
        raise ApiError(415, "INVALID_IMAGE_FORMAT")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            first = Image.open(io.BytesIO(raw))
            actual_family = first.format
            if actual_family not in {"PNG", "JPEG"} or actual_family != declared_family:
                raise ApiError(415, "INVALID_IMAGE_FORMAT")
            first.verify()

            image = Image.open(io.BytesIO(raw))
            if image.format != declared_family:
                raise ApiError(415, "INVALID_IMAGE_FORMAT")
            if getattr(image, "n_frames", 1) != 1:
                raise ApiError(415, "ANIMATED_IMAGE_NOT_SUPPORTED")
            _check_dimensions(image)
            image.load()
            image = ImageOps.exif_transpose(image)
            _check_dimensions(image)
    except ApiError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ApiError(422, "IMAGE_DIMENSIONS_TOO_LARGE") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ApiError(415, "INVALID_IMAGE_FORMAT") from exc

    rgba = image.convert("RGBA")
    width, height = rgba.size
    scale = min(32 / width, 32 / height)
    new_width = max(1, math.floor(width * scale + 0.5))
    new_height = max(1, math.floor(height * scale + 0.5))
    resized = rgba.resize((new_width, new_height), Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    left = (32 - new_width) // 2
    top = (32 - new_height) // 2
    canvas.paste(resized, (left, top))
    image_data = canvas.tobytes("raw", "RGBA")
    if canvas.size != (32, 32) or len(image_data) != 4096:
        raise ApiError(500, "INTERNAL_SERVER_ERROR")
    return image_data

