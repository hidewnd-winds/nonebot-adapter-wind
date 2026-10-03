"""Wind adapter configuration."""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator


class CosSettings(BaseModel):
    """Optional Tencent COS settings for publishing local Markdown images."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    secret_id: SecretStr | None = None
    secret_key: SecretStr | None = None
    region: str | None = None
    bucket: str | None = None
    public_base_url: str | None = None
    object_prefix: str = "markdown"

    @model_validator(mode="after")
    def validate_enabled_config(self) -> "CosSettings":
        if not self.enabled:
            return self
        missing = [
            name
            for name, value in (
                ("secret_id", self.secret_id),
                ("secret_key", self.secret_key),
                ("region", self.region),
                ("bucket", self.bucket),
            )
            if value is None
            or (isinstance(value, str) and not value.strip())
            or (
                isinstance(value, SecretStr)
                and not value.get_secret_value().strip()
            )
        ]
        if missing:
            raise ValueError(f"启用 COS 时配置不完整: {', '.join(missing)}")
        if self.public_base_url is not None:
            parsed = urlparse(self.public_base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("COS 公网访问域名必须是有效的 HTTP(S) URL")
        return self


class Config(BaseModel):
    """NoneBot 插件配置中的 Wind 扩展项。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    wind_collapse_command_spaces: bool = True
    wind_qq_strip_command_slash: bool = True
    wind_qq_group_members: bool = True
    wind_qq_initialize_webhook_bots: bool = True
    wind_cos: CosSettings = CosSettings()
