"""Protocol contract checks use SDK models and replace only the network call."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Bot as OneBotBot
from nonebot.adapters.qq import Adapter as QQAdapter
from nonebot.adapters.qq import Bot as QQBot
from nonebot.adapters.qq.config import BotInfo, Config as QQConfig
from nonebot.adapters.qq.models import QQReplyMessage

from nonebot.adapters.wind import (
    GroupBatchOperationError,
    GroupMessage,
    GroupMemberMute,
    MessageGroup,
    MessageSender,
    ProtocolAdapterError,
    UnsupportedProtocolCapabilityError,
    get_group_blacklist,
    get_group_info,
    get_group_join_requests,
    get_group_member,
    get_group_members,
    remove_group_members,
    set_group_blacklist,
    set_group_members_mute,
)
from nonebot.adapters.wind.qq import _convert_reference
from nonebot.adapters.wind.api import recall_group_message


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


def unified_group(bot):
    return SimpleNamespace(
        _bot=bot,
        protocol="qq",
        group=SimpleNamespace(id="group"),
        sender=SimpleNamespace(id="actor", name="操作者", role="member"),
        _event=object(),
    )


@pytest.fixture
def onebot():
    adapter = SimpleNamespace(_call_api=AsyncMock())
    return OneBotBot(adapter, "123")


def test_qq_group_info_uses_real_request_and_preserves_group_fields(qq_bot):
    qq_bot._request.return_value = {
        "group_openid": "group", "group_name": "测试群", "group_member_num": 12,
        "group_finger_memo": "", "group_class_text": "", "group_tags": [],
    }
    result = asyncio.run(get_group_info(unified_group(qq_bot)))
    request = qq_bot._request.call_args.args[0]
    assert result.id == "group"
    assert result.name == "测试群" and result.member_count == 12
    assert request.method == "GET"
    assert str(request.url) == "https://api.bot.qq.com/v2/groups/group/info"


def test_qq_member_lookup_uses_direct_endpoint_and_sender_shortcut(qq_bot):
    qq_bot._request.return_value = {
        "member_openid": "member", "username": "成员", "member_role": "admin", "bot": False,
    }
    result = asyncio.run(get_group_member(unified_group(qq_bot), "member"))
    assert result.id == "member" and result.role == "admin"
    assert qq_bot._request.call_args.args[0].url.path.endswith("/groups/group/members/member")

    sender = asyncio.run(get_group_member(unified_group(qq_bot)))
    assert sender.id == "actor" and sender.role == "member"
    assert qq_bot._request.await_count == 1


def test_qq_member_cursor_pagination_preserves_unknown_role(qq_bot):
    qq_bot._request.side_effect = [
        {"members": [{"member_openid": "a", "member_role": "member", "bot": False}], "next_cursor": "next"},
        {"members": [{"member_openid": "b", "member_role": None, "bot": False}], "next_cursor": ""},
    ]
    result = asyncio.run(get_group_members(unified_group(qq_bot)))
    assert [member.id for member in result] == ["a", "b"]
    assert result[1].role == "unknown"
    assert qq_bot._request.call_args_list[1].args[0].url.query["cursor"] == "next"


def test_malformed_page_and_repeated_cursor_are_protocol_errors(qq_bot):
    qq_bot._request.return_value = {"unexpected": []}
    with pytest.raises(ProtocolAdapterError):
        asyncio.run(get_group_members(unified_group(qq_bot)))

    qq_bot._request.reset_mock()
    qq_bot._request.return_value = {"members": [], "next_cursor": "repeat"}
    with pytest.raises(ProtocolAdapterError):
        asyncio.run(get_group_members(unified_group(qq_bot)))
    assert qq_bot._request.await_count == 2


def test_join_page_preserves_platform_request_ids_and_cursor(qq_bot):
    qq_bot._request.return_value = {"list": [{
        "join_request_id": "request", "member_openid": "member", "username": "申请者",
        "apply_at": "2026-10-02T10:00:00+08:00", "apply_source": "invited", "invited_by": "inviter",
        "verify_info": {"method": "admin_review_qa", "review_qa_list": [
            {"question": "问题", "answer": "回答"},
        ]},
    }], "next_cursor": "next"}
    page = asyncio.run(get_group_join_requests(qq_bot, "group", cursor="cursor", limit=20))
    request = qq_bot._request.call_args.args[0]
    assert page.requests[0].request_id == "request"
    assert page.requests[0].review_answers == (("问题", "回答"),)
    assert page.next_cursor == "next" and request.url.query["cursor"] == "cursor"


def test_onebot_missing_join_api_is_explicit(onebot):
    with pytest.raises(UnsupportedProtocolCapabilityError):
        asyncio.run(get_group_join_requests(onebot, "456"))
    onebot.adapter._call_api.assert_not_awaited()


def test_qq_reference_without_optional_ids_keeps_content():
    reference = _convert_reference(QQReplyMessage(content="引用正文"))
    assert reference.text == "引用正文"
    assert reference.reference_id is None


def test_qq_blacklist_reads_identity_and_returns_partial_write_failures(qq_bot):
    qq_bot._request.return_value = {
        "users": [{"member_openid": "user", "bot": False}], "next_cursor": "next",
    }
    page = asyncio.run(get_group_blacklist(qq_bot, "group"))
    assert page.members[0].user_id == "user" and page.members[0].nickname is None
    assert page.next_cursor == "next"

    qq_bot._request.return_value = {"fail_openids": ["second"]}
    failures = asyncio.run(set_group_blacklist(qq_bot, "group", ["first", "second"], add=True))
    assert failures == ("second",)
    assert qq_bot._request.call_args.args[0].json == {
        "op": "add", "member_openids": ["first", "second"],
    }


def test_qq_remove_reports_confirmed_outcome_and_blacklist_failure(qq_bot):
    qq_bot._request.return_value = {
        "remove_members_result": "success", "add_to_member_blacklist_fail_openids": ["b"],
    }
    result = asyncio.run(remove_group_members(
        qq_bot, "group", ["a", "b"], add_to_blacklist=True,
    ))
    assert result.removed is True and result.blacklist_failed_ids == ("b",)

    qq_bot._request.return_value = {}
    with pytest.raises(ProtocolAdapterError, match="未确认"):
        asyncio.run(remove_group_members(qq_bot, "group", ["a"]))


@pytest.mark.parametrize("operation", ["remove", "mute"])
def test_onebot_batch_failure_keeps_completed_items_without_replay(onebot, operation):
    onebot.adapter._call_api.side_effect = [None, TimeoutError("uncertain result")]
    if operation == "remove":
        action = remove_group_members(onebot, "789", ["1", "2", "3"])
    else:
        action = set_group_members_mute(
            onebot, "789", [GroupMemberMute(user_id, "del") for user_id in ("1", "2", "3")],
        )
    with pytest.raises(GroupBatchOperationError) as caught:
        asyncio.run(action)
    assert caught.value.completed_ids == ("1",)
    assert caught.value.failed_id == "2"
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert onebot.adapter._call_api.await_count == 2


def test_invalid_group_batch_is_rejected_before_network(qq_bot):
    with pytest.raises(ValueError):
        asyncio.run(remove_group_members(qq_bot, "group", ["same", "same"]))
    qq_bot._request.assert_not_awaited()


@pytest.mark.parametrize("operation", ["add", "update", "del"])
def test_mute_payload_and_onebot_duration_keep_platform_semantics(qq_bot, onebot, operation):
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    entries = [GroupMemberMute("456", operation, expiry if operation != "del" else None)]
    asyncio.run(set_group_members_mute(qq_bot, "group", entries))
    request = qq_bot._request.call_args.args[0]
    payload = request.json["members"][0]
    assert payload["member_openid"] == "456" and payload["op"] == operation
    if operation == "del":
        assert "mute_expire_at" not in payload
    else:
        assert payload["mute_expire_at"] == expiry.isoformat()

    asyncio.run(set_group_members_mute(onebot, "789", entries))
    call = onebot.adapter._call_api.call_args
    assert call.args[1] == "set_group_ban"
    assert call.kwargs["group_id"] == 789 and call.kwargs["user_id"] == 456
    if operation == "del":
        assert call.kwargs["duration"] == 0
    else:
        assert 590 <= call.kwargs["duration"] <= 600


def test_qq_group_recall_uses_current_message_id_and_propagates_expiry(qq_bot):
    from nonebot.adapters.qq.exception import ActionFailed
    from nonebot.drivers import Response

    message = GroupMessage(
        protocol="qq", transport="webhook", message_id="incoming-message",
        text="body", raw_text="body", is_to_me=False,
        sender=MessageSender(id="member", name="name"),
        group=MessageGroup(id="group", name=None),
        _bot=qq_bot, _event=object(), _matcher=None,
    )
    asyncio.run(recall_group_message(message))
    request = qq_bot._request.call_args.args[0]
    assert request.method == "DELETE"
    assert request.url.path.endswith("/messages/incoming-message")

    qq_bot._request.side_effect = ActionFailed(
        Response(400, content='{"code":40064004,"message":"expired"}')
    )
    with pytest.raises(ActionFailed):
        asyncio.run(recall_group_message(message))
