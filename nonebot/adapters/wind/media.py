"""Safe image utilities and the pluggable public image publishing contract."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlparse

import aiohttp
from .log import log
from PIL import Image, UnidentifiedImageError

MAX_REMOTE_IMAGE_BYTES = 20 * 1024 * 1024
MAX_REMOTE_IMAGE_REDIRECTS = 5


@dataclass(frozen=True)
class DownloadedImage:
    """An image whose content and size have been checked."""

    data: bytes
    content_type: str
    suffix: str


class ImagePublisher(Protocol):
    """Publish image bytes to a URL accessible by the target platform."""

    async def publish_image(self, image_data: bytes, file_name: str) -> str: ...


def detect_image_format(image_data: bytes) -> tuple[str, str] | None:
    """Identify supported image formats from their file signatures."""

    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if image_data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if image_data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", ".gif"
    if len(image_data) >= 12 and image_data.startswith(b"RIFF") and image_data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def _safe_url_for_log(image_url: str) -> str:
    parsed = urlparse(image_url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:120]


async def download_remote_image(
    image_url: str,
    *,
    declared_size: int | None = None,
    max_bytes: int = MAX_REMOTE_IMAGE_BYTES,
) -> DownloadedImage | None:
    """Download and validate a remote image, respecting byte and redirect limits."""

    safe_url = _safe_url_for_log(image_url)
    if declared_size is not None and declared_size > max_bytes:
        log("WARNING", f"Image exceeds size limit url={safe_url!r} size={declared_size}")
        return None
    current_url = image_url
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        connector = aiohttp.TCPConnector(use_dns_cache=False)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False, connector=connector) as session:
            for _ in range(MAX_REMOTE_IMAGE_REDIRECTS + 1):
                async with session.get(current_url, allow_redirects=False) as response:
                    if 300 <= response.status < 400:
                        location = response.headers.get("Location")
                        if not location:
                            return None
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > max_bytes:
                        log("WARNING", f"Image response exceeds size limit url={safe_url!r} size={content_length}")
                        return None
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            log("WARNING", f"Image download exceeds size limit url={safe_url!r}")
                            return None
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    detected = detect_image_format(data)
                    if detected is None:
                        log("WARNING", f"Remote resource is not a supported image url={safe_url!r}")
                        return None
                    return DownloadedImage(data, *detected)
            log("WARNING", f"Too many image redirects url={safe_url!r}")
            return None
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
        log("WARNING", f"Image download failed url={safe_url!r} err={error!r}")
        return None


async def get_image_byte_stream(image_url: str) -> BytesIO | None:
    """Download an image and return it as a byte stream."""

    downloaded = await download_remote_image(image_url)
    return BytesIO(downloaded.data) if downloaded is not None else None


async def get_png_dimensions(image_url: str) -> tuple[int, int] | None:
    """Read dimensions from a remotely hosted supported image."""

    downloaded = await download_remote_image(image_url)
    if downloaded is None:
        return None
    dimensions = read_image_dimensions(downloaded.data)
    if dimensions is None:
        log("WARNING", f"Cannot read image dimensions url={_safe_url_for_log(image_url)!r}")
    return dimensions


def read_image_dimensions(image_data: bytes) -> tuple[int, int] | None:
    """Read the original dimensions of a supported PNG, JPEG, GIF, or WebP image."""

    if detect_image_format(image_data) is None:
        return None
    try:
        with Image.open(BytesIO(image_data)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


async def resolve_image_url(value: str, publisher: ImagePublisher | None = None) -> str:
    """Return a public image URL; local paths require an explicit publisher."""

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if parsed.scheme:
        raise ValueError("图片地址仅支持本地文件路径或 HTTP(S) URL")
    path = Path(value).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Image file does not exist: {path}")
    if publisher is None:
        raise RuntimeError("本地图片需要配置 ImagePublisher 才能用于 Markdown")
    data = await asyncio.to_thread(path.read_bytes)
    if detect_image_format(data) is None:
        raise ValueError(f"Local file is not a supported image: {path.name}")
    published_url = await publisher.publish_image(data, path.name)
    published = urlparse(published_url)
    if published.scheme not in {"http", "https"} or not published.netloc:
        raise ValueError("ImagePublisher must return a valid HTTP(S) URL")
    return published_url
