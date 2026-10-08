import asyncio
import io
import warnings
from typing import Literal, cast

from PIL import Image, UnidentifiedImageError

from backend.contracts.agents import ImageMetadata


def _validate(content: bytes, mime: str, max_bytes: int, max_pixels: int) -> ImageMetadata:
    if not content or len(content) > max_bytes:
        raise ValueError("Image size is invalid")
    formats = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
    if mime not in formats:
        raise ValueError("Unsupported image type")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as picture:
                if picture.format != formats[mime]:
                    raise ValueError("Image content does not match its type")
                width, height = picture.size
                if width * height > max_pixels or max(width, height) > 8192:
                    raise ValueError("Image dimensions exceed limits")
                picture.verify()
            with Image.open(io.BytesIO(content)) as picture:
                picture.load()
        return ImageMetadata(
            mime_type=cast(Literal["image/png", "image/jpeg", "image/webp"], mime),
            size_bytes=len(content),
            width=width,
            height=height,
        )
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("Invalid image content") from exc


async def validate_image(
    content: bytes, mime: str, max_bytes: int = 5_242_880, max_pixels: int = 16_000_000
) -> ImageMetadata:
    return await asyncio.to_thread(_validate, content, mime, max_bytes, max_pixels)
