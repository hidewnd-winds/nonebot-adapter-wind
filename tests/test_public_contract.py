"""The extraction must preserve the source package's explicit public surface."""
from __future__ import annotations

import json
from pathlib import Path

from nonebot.adapters import wind
from nonebot.adapters.wind.onebot_v11 import Adapter as OneBotAdapter, ProjectOneBotV11Adapter
from nonebot.adapters.wind.qq import Adapter as QQAdapter, ProjectQQAdapter


def test_original_root_exports_remain_importable_in_order():
    expected = json.loads(Path(__file__).with_name("expected_exports.json").read_text(encoding="utf-8"))
    assert len(expected) == 103
    assert list(wind.__all__) == expected
    for name in expected:
        assert getattr(wind, name) is not None


def test_registration_aliases_preserve_original_adapter_identity():
    assert QQAdapter is ProjectQQAdapter
    assert OneBotAdapter is ProjectOneBotV11Adapter
