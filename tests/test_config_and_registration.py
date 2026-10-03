from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nonebot.adapters.wind.config import Config, CosSettings
from nonebot.adapters.wind.onebot_v11 import Adapter as OneBotAdapter
from nonebot.adapters.wind.onebot_v11 import register as register_onebot
from nonebot.adapters.wind.qq import Adapter as QQAdapter
from nonebot.adapters.wind.qq import register as register_qq


@pytest.mark.parametrize("name", [
    "wind_collapse_command_spaces",
    "wind_qq_strip_command_slash",
    "wind_qq_group_members",
    "wind_qq_initialize_webhook_bots",
])
def test_command_and_lifecycle_extensions_keep_enabled_defaults(name):
    assert getattr(Config(), name) is True


def test_cos_is_optional_but_enabled_configuration_must_be_complete():
    assert CosSettings().enabled is False
    with pytest.raises(ValueError, match="配置不完整"):
        CosSettings(enabled=True)
    settings = CosSettings(
        enabled=True,
        secret_id="id",
        secret_key="key",
        region="region",
        bucket="bucket",
    )
    assert settings.secret_key.get_secret_value() == "key"


@pytest.mark.parametrize(("register", "adapter"), [
    (register_qq, QQAdapter),
    (register_onebot, OneBotAdapter),
])
def test_duplicate_protocol_registration_is_rejected_before_framework_silent_skip(register, adapter):
    driver = SimpleNamespace(_adapters={adapter.get_name(): object()}, register_adapter=Mock())
    with pytest.raises(RuntimeError):
        register(driver)
    driver.register_adapter.assert_not_called()


@pytest.mark.parametrize(("register", "adapter"), [
    (register_qq, QQAdapter),
    (register_onebot, OneBotAdapter),
])
def test_protocol_register_helper_uses_real_adapter_class(register, adapter):
    driver = SimpleNamespace(_adapters={}, register_adapter=Mock())
    register(driver)
    driver.register_adapter.assert_called_once_with(adapter)
