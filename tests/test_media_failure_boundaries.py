"""图片网络与上传失败边界：所有外部请求均由本地替身模拟。"""

from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from PIL import Image
from pydantic import SecretStr

from nonebot.adapters.wind.config import CosSettings
from nonebot.adapters.wind.media import (
    MAX_REMOTE_IMAGE_REDIRECTS,
    download_remote_image,
)
from nonebot.adapters.wind.models import ImageContent, InvalidMessageContentError, RichContent
from nonebot.adapters.wind.qq import _render_content
from nonebot.adapters.wind.storage.cos import TencentCosStorage, TencentCosStorageError


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), "white").save(output, format="PNG")
    return output.getvalue()


class FakeContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read_calls = 0

    async def iter_chunked(self, _size: int):
        for chunk in self.chunks:
            self.read_calls += 1
            yield chunk


class FakeResponse:
    def __init__(self, *, status: int = 200, headers: dict[str, str] | None = None, chunks: list[bytes] | None = None):
        self.status = status
        self.headers = headers or {}
        self.content = FakeContent(chunks or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def get(self, url: str, *, allow_redirects: bool):
        assert allow_redirects is False
        self.urls.append(url)
        return self.responses.pop(0)


@pytest.mark.parametrize(
    "declared_size, headers, chunks",
    [
        (5, {}, [b"12345"]),
        (None, {"Content-Length": "5"}, [b"12345"]),
        (None, {}, [b"123", b"456"]),
    ],
)
def test_remote_download_rejects_declared_and_streamed_oversize(
    monkeypatch, declared_size, headers, chunks,
) -> None:
    response = FakeResponse(headers=headers, chunks=chunks)
    session = FakeSession([response])
    monkeypatch.setattr(
        "nonebot.adapters.wind.media.aiohttp.ClientSession",
        lambda **_kwargs: session,
    )

    result = asyncio.run(
        download_remote_image(
            "https://images.example.test/image.png",
            declared_size=declared_size,
            max_bytes=4,
        )
    )

    assert result is None
    if declared_size is not None:
        assert session.urls == []  # 请求前就能拒绝
    elif headers:
        assert response.content.read_calls == 0
    else:
        assert response.content.read_calls == 2


def test_remote_download_allows_five_redirects_and_rejects_the_sixth(monkeypatch) -> None:
    image = png_bytes()
    allowed_session = FakeSession(
        [
            *[
                FakeResponse(status=302, headers={"Location": f"/hop/{index}"})
                for index in range(MAX_REMOTE_IMAGE_REDIRECTS)
            ],
            FakeResponse(headers={"Content-Length": str(len(image))}, chunks=[image]),
        ]
    )
    monkeypatch.setattr(
        "nonebot.adapters.wind.media.aiohttp.ClientSession",
        lambda **_kwargs: allowed_session,
    )

    downloaded = asyncio.run(download_remote_image("https://images.example.test/start"))

    assert downloaded is not None and downloaded.data == image
    assert len(allowed_session.urls) == MAX_REMOTE_IMAGE_REDIRECTS + 1
    assert allowed_session.urls[-1] == "https://images.example.test/hop/4"

    blocked_session = FakeSession(
        [
            FakeResponse(status=302, headers={"Location": f"/hop/{index}"})
            for index in range(MAX_REMOTE_IMAGE_REDIRECTS + 1)
        ]
    )
    monkeypatch.setattr(
        "nonebot.adapters.wind.media.aiohttp.ClientSession",
        lambda **_kwargs: blocked_session,
    )
    assert asyncio.run(download_remote_image("https://images.example.test/start")) is None
    assert len(blocked_session.urls) == MAX_REMOTE_IMAGE_REDIRECTS + 1


class FakeCosClient:
    def __init__(self) -> None:
        self.fail_exists = False
        self.fail_upload = False
        self.uploads = 0
        self.exists_calls = 0

    def object_exists(self, **_kwargs: object) -> bool:
        self.exists_calls += 1
        if self.fail_exists:
            raise OSError("lookup unavailable")
        return False

    def put_object(self, **_kwargs: object) -> None:
        self.uploads += 1
        if self.fail_upload:
            raise OSError("upload unavailable")

    def upload_file(self, **_kwargs: object) -> None:
        raise AssertionError("byte upload uses put_object")


def cos_settings() -> CosSettings:
    return CosSettings(
        enabled=True,
        secret_id=SecretStr("id"),
        secret_key=SecretStr("secret"),
        region="ap-shanghai",
        bucket="test-bucket",
        public_base_url="https://images.example.test",
    )


@pytest.mark.parametrize("failure", ["exists", "upload"])
def test_cos_failures_raise_and_never_cache_success(failure: str) -> None:
    client = FakeCosClient()
    storage = TencentCosStorage(cos_settings(), client=client)
    if failure == "exists":
        client.fail_exists = True
    else:
        client.fail_upload = True

    with pytest.raises(TencentCosStorageError):
        asyncio.run(storage.publish_image(png_bytes(), "sample.png"))

    assert storage._uploaded_urls == {}
    if failure == "exists":
        assert client.uploads == 0
    else:
        assert client.uploads == 1

    # 第二次同内容调用仍会访问远端并上传，失败从未进入成功缓存。
    client.fail_exists = False
    client.fail_upload = False
    result = asyncio.run(storage.publish_image(png_bytes(), "sample.png"))
    assert result.startswith("https://images.example.test/markdown/")
    assert client.exists_calls == 2
    assert client.uploads == (1 if failure == "exists" else 2)


class FailedPublisher:
    async def publish_image(self, image_data: bytes, file_name: str) -> str:
        raise OSError("publisher unavailable")


class EmptyUrlPublisher:
    async def publish_image(self, image_data: bytes, file_name: str) -> str:
        return ""


@pytest.mark.parametrize("publisher, error", [(FailedPublisher(), OSError), (EmptyUrlPublisher(), InvalidMessageContentError)])
def test_qq_rich_content_publisher_failure_is_not_reported_as_media_success(publisher, error) -> None:
    content = RichContent(images=(ImageContent(png_bytes(), "sample.png"),))

    with pytest.raises(error):
        asyncio.run(_render_content(content, publisher))
