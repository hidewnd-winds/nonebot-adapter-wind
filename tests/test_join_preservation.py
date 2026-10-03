"""Join identity, approval routing, protocol guards, and per-Bot QQ pacing."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Bot as OneBotBot
from nonebot.adapters.onebot.v11.event import GroupRequestEvent
from nonebot.adapters.qq import Adapter as QQAdapter
from nonebot.adapters.qq import Bot as QQBot
from nonebot.adapters.qq.config import BotInfo, Config as QQConfig
from nonebot.adapters.qq.event import GroupJoinRequestEvent

from nonebot.adapters.wind.group_join import (
    GroupJoinApplication,
    GroupJoinApprover,
    get_group_join_application,
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
    monkeypatch.setattr(bot, "_request", AsyncMock(return_value={}))
    return bot


@pytest.fixture
def onebot():
    adapter = SimpleNamespace(_call_api=AsyncMock(return_value={"user_id": 456, "nickname": "成员"}))
    return OneBotBot(adapter, "123")


def test_onebot_request_uses_real_flag_and_subtype_for_rejection(onebot):
    event = GroupRequestEvent.model_validate({
        "time": 1234, "self_id": 123, "post_type": "request", "request_type": "group",
        "sub_type": "add", "group_id": 789, "user_id": 456,
        "flag": "real-request-flag", "comment": "请审核",
    })
    application = asyncio.run(get_group_join_application(onebot, event))
    assert application.protocol == "onebot_v11"
    assert application.group_id == "789" and application.user_id == "456"
    assert application.request_id == "real-request-flag"
    assert application.qq_number == "456" and application.nickname == "成员"

    onebot.adapter._call_api.reset_mock()
    asyncio.run(GroupJoinApprover().reject(onebot, application, reason="请联系管理员"))
    onebot.adapter._call_api.assert_awaited_once_with(
        onebot,
        "set_group_add_request",
        flag="real-request-flag",
        sub_type="add",
        approve=False,
        reason="请联系管理员",
    )


def test_qq_join_application_keeps_real_request_and_auto_approval_state(qq_bot):
    event = GroupJoinRequestEvent.model_validate({
        "event_id": "callback-id", "join_request_id": "qq-request", "group_openid": "qq-group",
        "member_openid": "member-openid", "username": "申请者",
        "apply_at": "2026-10-04T10:00:00+08:00", "apply_source": "self_apply",
        "auto_approved": {"strategy_id": "strategy"},
    })
    application = asyncio.run(get_group_join_application(qq_bot, event))
    assert application.protocol == "qq"
    assert application.request_id == "qq-request"
    assert application.user_id == "member-openid" and application.group_id == "qq-group"
    assert application.nickname == "申请者" and application.already_approved is True
    assert application.avatar_url.endswith("/member-openid/640")

    asyncio.run(GroupJoinApprover().reject(qq_bot, application, reason="请补充申请信息"))
    request = qq_bot._request.call_args.args[0]
    assert request.url.path.endswith("/groups/qq-group/approval_join_request/member-openid")
    assert request.json == {
        "op": "decline",
        "join_request_id": "qq-request",
        "reject_reason": "请补充申请信息",
        "add_to_member_blacklist": False,
    }


def test_non_add_onebot_request_is_ignored(onebot):
    event = GroupRequestEvent.model_validate({
        "time": 1234, "self_id": 123, "post_type": "request", "request_type": "group",
        "sub_type": "invite", "group_id": 789, "user_id": 456, "flag": "invite-flag",
    })
    assert asyncio.run(get_group_join_application(onebot, event)) is None
    onebot.adapter._call_api.assert_not_awaited()


def test_approval_rejects_protocol_mismatch_before_remote_call(qq_bot, onebot):
    application = GroupJoinApplication("qq", "group", "member", "request")
    with pytest.raises(TypeError, match="协议与当前 Bot 不一致"):
        asyncio.run(GroupJoinApprover().reject(onebot, application, reason="理由"))
    onebot.adapter._call_api.assert_not_awaited()


def test_qq_approval_slots_serialize_and_clear_with_virtual_time(monkeypatch, qq_bot):
    from nonebot.adapters.wind import group_join

    now = [100.0]
    sleeps = []

    def monotonic():
        return now[0]

    async def advance(delay):
        sleeps.append(delay)
        now[0] += delay

    monkeypatch.setattr(group_join, "monotonic", monotonic)
    monkeypatch.setattr(group_join.asyncio, "sleep", advance)
    approver = GroupJoinApprover()
    entered = asyncio.Event()
    release = asyncio.Event()
    starts = []

    async def first_request():
        async with approver.request_slot(qq_bot):
            starts.append(now[0])
            entered.set()
            await release.wait()

    async def second_request():
        await entered.wait()
        async with approver.request_slot(qq_bot):
            starts.append(now[0])

    async def run():
        first = asyncio.create_task(first_request())
        second = asyncio.create_task(second_request())
        await entered.wait()
        release.set()
        await asyncio.gather(first, second)

    asyncio.run(run())
    assert starts == [100.0, 101.1]
    assert sleeps == [pytest.approx(1.1)]
    assert "test-bot" in approver.slots
    approver.clear()
    assert approver.slots == {}
