"""指令面板测试只替换 QQ SDK 的网络请求边界。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.adapters.qq import Adapter as QQAdapter
from nonebot.adapters.qq import Bot as QQBot
from nonebot.adapters.qq.config import BotInfo, Config as QQConfig
from pydantic import ValidationError

from nonebot.adapters.wind.qq_panel import (
    QQPanel,
    QQPanelItem,
    create_qq_group_panel,
    list_qq_group_panels,
    update_qq_panel,
)

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init(_env_file=None)


@pytest.fixture
def qq_bot(monkeypatch):
    adapter = object.__new__(QQAdapter)
    adapter.qq_config = QQConfig()
    bot = QQBot(adapter, "test-bot", BotInfo(id="test-bot", secret="test-secret"))
    monkeypatch.setattr(bot, "_request", AsyncMock())
    return bot


def panel(panel_id: str = "p1") -> dict[str, object]:
    return {
        "panel_id": panel_id,
        "scope": "group",
        "target_type": "all",
        "panel": {"items": [{"type": "command", "name": "help"}], "remark": "menu"},
    }


def test_list_panels_follows_cursors_until_end(qq_bot) -> None:
    qq_bot._request.side_effect = [
        {"records": [panel("p1")], "next_cursor": "page-2", "is_end": False},
        {"records": [panel("p2")], "next_cursor": "", "is_end": True},
    ]

    result = asyncio.run(list_qq_group_panels(qq_bot))

    assert [record.panel_id for record in result] == ["p1", "p2"]
    first, second = [call.args[0] for call in qq_bot._request.await_args_list]
    assert first.method == second.method == "GET"
    assert dict(first.url.query) == {"scope": "group", "limit": "50"}
    assert dict(second.url.query) == {
        "scope": "group",
        "limit": "50",
        "cursor": "page-2",
    }
    assert first.url.path == "/v2/panels"


def test_empty_final_page_may_omit_records_and_cursor(qq_bot) -> None:
    qq_bot._request.return_value = {"is_end": True}
    assert asyncio.run(list_qq_group_panels(qq_bot)) == []
    qq_bot._request.assert_awaited_once()


@pytest.mark.parametrize(
    "page",
    [
        {},
        {"records": [], "is_end": False},
        {"next_cursor": "next", "is_end": False},
        {"records": [], "next_cursor": "next"},
    ],
)
def test_list_panels_rejects_malformed_page(qq_bot, page) -> None:
    qq_bot._request.return_value = page
    with pytest.raises(ValidationError):
        asyncio.run(list_qq_group_panels(qq_bot))
    qq_bot._request.assert_awaited_once()


def test_list_panels_rejects_repeated_cursor(qq_bot) -> None:
    qq_bot._request.side_effect = [
        {"records": [panel()], "next_cursor": "repeat", "is_end": False},
        {"records": [], "next_cursor": "repeat", "is_end": False},
    ]
    with pytest.raises(ValueError, match="游标重复"):
        asyncio.run(list_qq_group_panels(qq_bot))
    assert qq_bot._request.await_count == 2


def test_create_panel_sends_one_post_and_returns_id(qq_bot) -> None:
    qq_bot._request.return_value = {"panel_id": "created"}
    item = QQPanelItem(type="command", name="help")

    result = asyncio.run(create_qq_group_panel(qq_bot, QQPanel(items=(item,))))

    assert result == "created"
    request = qq_bot._request.await_args.args[0]
    assert request.method == "POST"
    assert str(request.url).endswith("/v2/panels")
    assert request.json == {
        "scope": "group",
        "target_type": "all",
        "panel": {"items": [{"type": "command", "name": "help", "desc": "", "only_admin": False}], "remark": ""},
    }


@pytest.mark.parametrize("operation", ["create", "update"])
def test_panel_write_does_not_retry(qq_bot, operation) -> None:
    error = RuntimeError("ambiguous write outcome")
    qq_bot._request.side_effect = error
    item = QQPanelItem(type="link", name="docs", link="https://example.test")
    panel_data = QQPanel(items=(item,))

    with pytest.raises(RuntimeError, match="ambiguous write outcome") as caught:
        if operation == "create":
            asyncio.run(create_qq_group_panel(qq_bot, panel_data))
        else:
            asyncio.run(update_qq_panel(qq_bot, "panel-id", panel_data))

    assert caught.value is error
    qq_bot._request.assert_awaited_once()


def test_update_panel_sends_one_put_and_returns_version(qq_bot) -> None:
    qq_bot._request.return_value = {"version": 7}
    item = QQPanelItem(type="link", name="docs", link="https://example.test")

    assert asyncio.run(update_qq_panel(qq_bot, "panel-id", QQPanel(items=(item,)))) == 7
    request = qq_bot._request.await_args.args[0]
    assert request.method == "PUT"
    assert str(request.url).endswith("/v2/panels/panel-id")
