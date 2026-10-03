from __future__ import annotations

import asyncio
import builtins
from io import BytesIO

import pytest
from PIL import Image

from nonebot.adapters.wind.config import CosSettings
from nonebot.adapters.wind.media import (
    detect_image_format,
    read_image_dimensions,
    resolve_image_url,
)
from nonebot.adapters.wind.storage.cos import TencentCosStorage


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (3, 2), "white").save(output, format="PNG")
    return output.getvalue()


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str]] = []

    async def publish_image(self, image_data: bytes, file_name: str) -> str:
        self.calls.append((image_data, file_name))
        return f"https://images.example.test/{file_name}"


class InvalidPublisher:
    async def publish_image(self, image_data: bytes, file_name: str) -> str:
        return "local/path.png"


class FakeCosClient:
    def __init__(self) -> None:
        self.objects: set[tuple[str, str]] = set()
        self.upload_count = 0

    def object_exists(self, **kwargs: object) -> bool:
        return (str(kwargs["Bucket"]), str(kwargs["Key"])) in self.objects

    def put_object(self, **kwargs: object) -> None:
        self.upload_count += 1
        self.objects.add((str(kwargs["Bucket"]), str(kwargs["Key"])))

    def upload_file(self, **kwargs: object) -> None:
        raise AssertionError("byte publisher should use put_object")


def _settings() -> CosSettings:
    from pydantic import SecretStr

    return CosSettings(
        enabled=True,
        secret_id=SecretStr("id"),
        secret_key=SecretStr("secret"),
        region="ap-shanghai",
        bucket="wind-test",
        public_base_url="https://images.example.test",
        object_prefix="markdown",
    )


def test_image_format_and_dimensions() -> None:
    data = _png_bytes()
    assert detect_image_format(data) == ("image/png", ".png")
    assert read_image_dimensions(data) == (3, 2)
    assert read_image_dimensions(b"not image") is None


def test_local_path_requires_publisher(tmp_path) -> None:
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(_png_bytes())
    with pytest.raises(RuntimeError, match="ImagePublisher"):
        asyncio.run(resolve_image_url(str(image_path)))


def test_local_path_is_published_and_public_url_passes_through(tmp_path) -> None:
    image_path = tmp_path / "sample.png"
    data = _png_bytes()
    image_path.write_bytes(data)
    publisher = FakePublisher()

    assert asyncio.run(resolve_image_url(str(image_path), publisher)) == (
        "https://images.example.test/sample.png"
    )
    assert publisher.calls == [(data, "sample.png")]
    assert asyncio.run(resolve_image_url("https://cdn.example.test/a.png", publisher)) == (
        "https://cdn.example.test/a.png"
    )


def test_publisher_must_return_public_http_url(tmp_path) -> None:
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(_png_bytes())
    with pytest.raises(ValueError, match=r"valid HTTP\(S\) URL"):
        asyncio.run(resolve_image_url(str(image_path), InvalidPublisher()))


def test_cos_publishes_and_deduplicates_image_bytes() -> None:
    client = FakeCosClient()
    storage = TencentCosStorage(_settings(), client=client)
    data = _png_bytes()

    first = asyncio.run(storage.publish_image(data, "image.png"))
    second = asyncio.run(storage.publish_image(data, "other.png"))

    assert first == second
    assert first.startswith("https://images.example.test/markdown/")
    assert client.upload_count == 1
    assert storage.is_published_image_url(first)
    assert asyncio.run(storage.get_cached_image_url("known-key")) is None


def test_disabled_cos_does_not_import_optional_sdk(monkeypatch) -> None:
    original_import = builtins.__import__

    def import_without_cos(name: str, *args: object, **kwargs: object) -> object:
        if name == "qcloud_cos":
            raise AssertionError("disabled COS must not import its SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_cos)
    storage = TencentCosStorage(CosSettings())
    assert storage.enabled is False
