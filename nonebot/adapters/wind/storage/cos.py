"""Optional Tencent COS publisher with per-adapter state and lazy SDK loading."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import quote, urlparse

from ..config import CosSettings
from ..media import detect_image_format


class TencentCosStorageError(RuntimeError):
    """COS configuration, object lookup, or upload failed."""


class CosClientProtocol(Protocol):
    """Subset of the COS SDK used by this integration."""

    def upload_file(self, **kwargs: object) -> object: ...

    def put_object(self, **kwargs: object) -> object: ...

    def object_exists(self, **kwargs: object) -> bool: ...


class TencentCosStorage:
    """An explicitly configured COS image publisher; create one per adapter."""

    def __init__(
        self,
        settings: CosSettings | None = None,
        *,
        client: CosClientProtocol | None = None,
    ) -> None:
        self._settings = CosSettings()
        self._client: CosClientProtocol | None = None
        self._public_base_url = ""
        self._uploaded_urls: dict[str, str] = {}
        if settings is not None:
            self.configure(settings, client=client)

    def configure(
        self,
        settings: CosSettings,
        *,
        client: CosClientProtocol | None = None,
    ) -> None:
        """Configure this instance. Disabled settings never import or create the SDK."""

        self.reset()
        self._settings = settings
        if not settings.enabled:
            if client is not None:
                raise ValueError("不能为已关闭的 COS 配置客户端")
            return
        if client is None:
            # Keep the optional dependency out of normal imports and non-COS installs.
            try:
                from qcloud_cos import CosConfig, CosS3Client
            except ImportError as exc:
                raise TencentCosStorageError(
                    "COS 已启用，请安装 nonebot-adapter-wind[cos]"
                ) from exc
            assert settings.secret_id is not None
            assert settings.secret_key is not None
            assert settings.region is not None
            client = cast(
                CosClientProtocol,
                CosS3Client(
                    CosConfig(
                        Region=settings.region,
                        SecretId=settings.secret_id.get_secret_value(),
                        SecretKey=settings.secret_key.get_secret_value(),
                        Scheme="https",
                    )
                ),
            )
        self._client = client
        self._public_base_url = (
            settings.public_base_url
            or f"https://{settings.bucket}.cos.{settings.region}.myqcloud.com"
        ).rstrip("/")

    def reset(self) -> None:
        """Release references to the runtime client and cached URLs."""

        self._settings = CosSettings()
        self._client = None
        self._public_base_url = ""
        self._uploaded_urls.clear()

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def is_published_image_url(self, value: str) -> bool:
        """Check whether a URL points inside this COS image prefix."""

        if not self.enabled:
            return False
        parsed, base = urlparse(value), urlparse(self._public_base_url)
        prefix = (
            f"{base.path.rstrip('/')}/"
            f"{quote(self._settings.object_prefix.strip('/'), safe='/')}"
        ).rstrip("/") + "/"
        return (
            parsed.scheme == base.scheme
            and parsed.netloc == base.netloc
            and parsed.path.startswith(prefix)
            and len(parsed.path) > len(prefix)
            and not parsed.query
            and not parsed.fragment
        )

    async def resolve_image_url(self, value: str) -> str:
        """Pass through public URLs or publish a local image file."""

        if urlparse(value).scheme in {"http", "https"}:
            return value
        if not self.enabled:
            raise TencentCosStorageError("本地图片需要启用 COS 或注入其他 ImagePublisher")
        path = Path(value).expanduser()
        try:
            data = await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise TencentCosStorageError(f"无法读取本地图像: {path.name}") from exc
        detected = detect_image_format(data)
        if detected is None:
            raise TencentCosStorageError(f"本地资源不是受支持的图像: {path.name}")
        return await self.publish_image(data, path.name)

    async def get_cached_image_url(self, cache_key: str) -> str | None:
        """Look up an object by key, including the configured object prefix."""

        if not self.enabled:
            return None
        client, bucket = self._ready()
        object_key = self._object_key(cache_key, "")
        try:
            exists = await asyncio.to_thread(
                client.object_exists, Bucket=bucket, Key=object_key
            )
        except Exception as exc:
            raise TencentCosStorageError(
                f"COS image existence check failed: {cache_key}"
            ) from exc
        return (
            f"{self._public_base_url}/{quote(object_key, safe='/')}" if exists else None
        )

    async def publish_image(self, image_data: bytes, file_name: str) -> str:
        """Upload image bytes, deduplicating objects by their content hash."""

        if not self.enabled:
            raise TencentCosStorageError("COS 图像发布未启用")
        return await asyncio.to_thread(self._upload_image_bytes, image_data, file_name)

    def _ready(self) -> tuple[CosClientProtocol, str]:
        client, bucket = self._client, self._settings.bucket
        if client is None or bucket is None:
            raise TencentCosStorageError("COS 服务尚未完成初始化")
        return client, bucket

    def _upload_image_bytes(self, image_data: bytes, file_name: str) -> str:
        detected = detect_image_format(image_data)
        content_type = detected[0] if detected else mimetypes.guess_type(file_name)[0]
        if content_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
            raise TencentCosStorageError(f"生成资源不是受支持的图像: {file_name}")
        suffix = detected[1] if detected else Path(file_name).suffix.lower()
        digest = hashlib.sha256(image_data).hexdigest()
        object_key = self._object_key(digest, suffix)
        cached_url = self._uploaded_urls.get(object_key)
        if cached_url is not None:
            return cached_url
        client, bucket = self._ready()
        public_url = f"{self._public_base_url}/{quote(object_key, safe='/')}"
        try:
            if client.object_exists(Bucket=bucket, Key=object_key):
                self._uploaded_urls[object_key] = public_url
                return public_url
        except Exception as exc:
            raise TencentCosStorageError(
                f"COS image existence check failed: {file_name}"
            ) from exc
        try:
            client.put_object(
                Bucket=bucket,
                Key=object_key,
                Body=image_data,
                ContentType=content_type,
                EnableMD5=True,
            )
        except Exception as exc:
            raise TencentCosStorageError(f"COS image upload failed: {file_name}") from exc
        self._uploaded_urls[object_key] = public_url
        return public_url

    def _object_key(self, digest: str, suffix: str) -> str:
        prefix = self._settings.object_prefix.strip("/")
        return f"{prefix}/{digest}{suffix}" if prefix else f"{digest}{suffix}"


__all__ = ["CosClientProtocol", "TencentCosStorage", "TencentCosStorageError"]
