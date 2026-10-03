from pydantic import SecretStr, ValidationError
import pytest

from nonebot.adapters.wind.config import Config, CosSettings


def test_wind_config_defaults_preserve_existing_behavior() -> None:
    config = Config()
    assert config.wind_collapse_command_spaces is True
    assert config.wind_qq_strip_command_slash is True
    assert config.wind_qq_group_members is True
    assert config.wind_qq_initialize_webhook_bots is True
    assert config.wind_cos.enabled is False


def test_cos_requires_credentials_when_enabled() -> None:
    with pytest.raises(ValidationError, match="配置不完整"):
        CosSettings(enabled=True)


def test_cos_accepts_complete_secret_settings() -> None:
    settings = CosSettings(
        enabled=True,
        secret_id=SecretStr("id"),
        secret_key=SecretStr("secret"),
        region="ap-shanghai",
        bucket="wind-test",
        public_base_url="https://img.example.test",
    )
    assert settings.secret_id is not None
    assert settings.secret_id.get_secret_value() == "id"


def test_cos_rejects_non_http_public_url() -> None:
    with pytest.raises(ValidationError, match=r"HTTP\(S\)"):
        CosSettings(
            enabled=True,
            secret_id=SecretStr("id"),
            secret_key=SecretStr("secret"),
            region="ap-shanghai",
            bucket="wind-test",
            public_base_url="ftp://img.example.test",
        )
