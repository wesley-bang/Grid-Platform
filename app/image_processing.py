from __future__ import annotations

import io
import math
import warnings
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from app.errors import ApiError


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_DIMENSION = 4096
MAX_PIXELS = 16_777_216
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    logical_width: int
    logical_height: int
    content_width: int
    content_height: int
    max_crop_x: int
    max_crop_y: int
    pixel_grid_detected: bool


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


def _fit_on_canvas(
    image: Image.Image,
    *,
    resample: Image.Resampling = Image.Resampling.NEAREST,
) -> Image.Image:
    """Scale an image into a centered transparent square canvas."""
    width, height = image.size
    scale = min(32 / width, 32 / height)
    new_width = max(1, math.floor(width * scale + 0.5))
    new_height = max(1, math.floor(height * scale + 0.5))
    if resample == Image.Resampling.LANCZOS:
        resized = (
            image.convert("RGBa")
            .resize((new_width, new_height), resample)
            .convert("RGBA")
        )
    else:
        resized = image.resize((new_width, new_height), resample)
    canvas = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    left = (32 - new_width) // 2
    top = (32 - new_height) // 2
    canvas.paste(resized, (left, top))
    return canvas


def _trim_transparent_border(image: Image.Image) -> tuple[Image.Image, bool]:
    """Crop a PNG to its visible alpha bounds when transparent padding exists."""
    bounds = image.getchannel("A").getbbox()
    if bounds is None or bounds == (0, 0, image.width, image.height):
        return image, False
    return image.crop(bounds), True


def _exact_pixel_ratio(left: Image.Image, right: Image.Image) -> float:
    difference = ImageChops.difference(left, right)
    red, green, blue, alpha = difference.split()
    combined = ImageChops.lighter(
        ImageChops.lighter(red, green),
        ImageChops.lighter(blue, alpha),
    )
    return combined.histogram()[0] / (left.width * left.height)


def _detect_pixel_grid(image: Image.Image) -> tuple[Image.Image, bool]:
    """Recover a small logical grid from strongly enlarged nearest-neighbor art."""
    largest_dimension = max(image.size)
    if largest_dimension <= 64:
        return image, False

    bounds = image.getchannel("A").getbbox()
    analysis = image.crop(bounds) if bounds is not None else image
    analysis_largest = max(analysis.size)
    sample = analysis.copy()
    sample.thumbnail((512, 512), Image.Resampling.NEAREST)
    scores: list[tuple[int, tuple[int, int], float]] = []
    for logical_max in range(8, 65):
        ratio = logical_max / analysis_largest
        candidate_size = (
            max(1, round(analysis.width * ratio)),
            max(1, round(analysis.height * ratio)),
        )
        candidate = sample.resize(candidate_size, Image.Resampling.NEAREST)
        restored = candidate.resize(sample.size, Image.Resampling.NEAREST)
        scores.append(
            (logical_max, candidate_size, float(_exact_pixel_ratio(sample, restored)))
        )

    peaks: list[tuple[float, float, tuple[int, int]]] = []
    for index in range(2, len(scores) - 2):
        _, candidate_size, score = scores[index]
        left_average = (scores[index - 2][2] + scores[index - 1][2]) / 2
        right_average = (scores[index + 1][2] + scores[index + 2][2]) / 2
        prominence = score - max(left_average, right_average)
        if score >= 0.9 and prominence >= 0.04:
            peaks.append((prominence, score, candidate_size))

    if not peaks:
        return image, False
    _, _, detected_content_size = max(peaks)
    scale_x = analysis.width / detected_content_size[0]
    scale_y = analysis.height / detected_content_size[1]
    detected_size = (
        max(1, round(image.width / scale_x)),
        max(1, round(image.height / scale_y)),
    )
    if max(detected_size) > 64:
        return image, False
    return image.resize(detected_size, Image.Resampling.NEAREST), True


def _pixel_crop(
    image: Image.Image,
    focus_x: float,
    focus_y: float,
) -> tuple[Image.Image, int, int]:
    """Place logical pixels 1:1 and crop overflow around the selected focus."""
    max_crop_x = max(0, image.width - 32)
    max_crop_y = max(0, image.height - 32)
    crop_x = math.floor(max_crop_x * focus_x + 0.5)
    crop_y = math.floor(max_crop_y * focus_y + 0.5)
    visible_width = min(32, image.width)
    visible_height = min(32, image.height)
    visible = image.crop(
        (crop_x, crop_y, crop_x + visible_width, crop_y + visible_height)
    )
    canvas = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    canvas.paste(
        visible,
        ((32 - visible_width) // 2, (32 - visible_height) // 2),
    )
    return canvas, max_crop_x, max_crop_y


async def process_upload(
    upload: UploadFile,
    *,
    image_mode: str = "pixel",
    trim_transparent: bool = True,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
) -> ProcessedImage:
    """Validate and convert an uploaded image to 32x32 RGBA bytes."""
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
    pixel_grid_detected = False
    logical = rgba
    if image_mode == "pixel":
        logical, pixel_grid_detected = _detect_pixel_grid(rgba)

    content = logical
    if declared_family == "PNG" and trim_transparent:
        content, _ = _trim_transparent_border(content)

    if image_mode == "pixel" and (
        pixel_grid_detected or max(logical.size) <= 64
    ):
        canvas, max_crop_x, max_crop_y = _pixel_crop(content, focus_x, focus_y)
    else:
        resample = (
            Image.Resampling.LANCZOS
            if image_mode == "smooth"
            else Image.Resampling.NEAREST
        )
        canvas = _fit_on_canvas(content, resample=resample)
        max_crop_x = 0
        max_crop_y = 0

    image_data = canvas.tobytes("raw", "RGBA")
    if canvas.size != (32, 32) or len(image_data) != 4096:
        raise ApiError(500, "INTERNAL_SERVER_ERROR")
    return ProcessedImage(
        data=image_data,
        logical_width=logical.width,
        logical_height=logical.height,
        content_width=content.width,
        content_height=content.height,
        max_crop_x=max_crop_x,
        max_crop_y=max_crop_y,
        pixel_grid_detected=pixel_grid_detected,
    )
