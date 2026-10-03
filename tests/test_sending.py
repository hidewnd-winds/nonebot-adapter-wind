"""Outbound protocol semantics using real SDK event and message models."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Bot as OneBotBot
from nonebot.adapters.qq import Adapter as QQAdapter
from nonebot.adapters.qq import Bot as QQBot
from nonebot.adapters.qq.config import BotInfo, Config as QQConfig
from nonebot.adapters.qq.event import GroupMessageCreateEvent
from nonebot.adapters.qq.exception import ActionFailed
from nonebot.drivers import Response

from nonebot.adapters.wind import (
    GroupMessage,
    ImageContent,
    MessageGroup,
    MessageSender,
    OrderedContent,
    PrivateMessage,
    RichContent,
    document,
    paragraph,
    send_proactive_message,
)
from nonebot.adapters.wind import onebot_v11, qq
from nonebot.adapters.wind.models import MessageSendError


try:
    nonebot.get_driver()
except ValueError:
    nonebot.init(_env_file=None)


@pytest.fixture
def qq_bot(monkeypatch):
    adapter = object.__new__(QQAdapter)
    adapter.qq_config = QQConfig()
    bot = QQBot(adapter, "test-bot", BotInfo(id="test-bot", secret="test-secret"))
    monkeypatch.setattr(bot, "_request", AsyncMock(return_value={"id": "response-id"}))
    return bot


@pytest.fixture
def onebot():
    adapter = SimpleNamespace(_call_api=AsyncMock(return_value={"message_id": 123}))
    return OneBotBot(adapter, "123")


def qq_group_message(bot, *, timestamp=None):
    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    event = GroupMessageCreateEvent.model_validate({
        "id": "incoming-id", "event_id": "event-id", "content": "hello",
        "timestamp": timestamp, "group_id": "group", "group_openid": "group",
        "author": {"id": "actor", "member_openid": "actor", "member_role": "member", "bot": False},
        "msg_idx": "REFIDX_original",
    })
    return GroupMessage(
        protocol="qq", transport="webhook", message_id=event.id,
        text="hello", raw_text="hello", is_to_me=False,
        sender=MessageSender(id="actor", name="actor", role="member"),
        group=MessageGroup(id="group", name=None),
        message_index=event.msg_idx,
        _bot=bot, _event=event, _matcher=None,
    )


def onebot_group_message(bot):
    return GroupMessage(
        protocol="onebot_v11", transport="websocket", message_id="10",
        text="hello", raw_text="hello", is_to_me=False,
        sender=MessageSender(id="456", name="member"),
        group=MessageGroup(id="789", name="group"),
        _bot=bot, _event=object(), _matcher=None,
    )


def test_onebot_group_multi_content_uses_forward_nodes(onebot):
    message = onebot_group_message(onebot)
    receipts = asyncio.run(onebot_v11.OneBotV11ProtocolAdapter().send(
        message, ("first", "second"),
    ))
    call = onebot.adapter._call_api.call_args
    assert call.args[1] == "send_group_forward_msg"
    assert call.kwargs["group_id"] == 789
    nodes = call.kwargs["messages"]
    assert [node.data["content"].extract_plain_text() for node in nodes] == ["first", "second"]
    assert receipts[0].message_id == "123"


def test_onebot_private_multi_content_sends_sequentially(onebot, monkeypatch):
    sent = []

    async def send(_event, message):
        sent.append(message)
        return {"message_id": str(len(sent))}

    monkeypatch.setattr(onebot, "send", send)
    message = PrivateMessage(
        protocol="onebot_v11", transport="websocket", message_id="10",
        text="hello", raw_text="hello", is_to_me=False,
        sender=MessageSender(id="456", name="member"),
        _bot=onebot, _event=object(), _matcher=None,
    )
    receipts = asyncio.run(onebot_v11.OneBotV11ProtocolAdapter().send(message, ("first", "second")))
    assert [item.extract_plain_text() for item in sent] == ["first", "second"]
    assert [receipt.message_id for receipt in receipts] == ["1", "2"]


def test_onebot_proactive_content_is_combined_in_one_api_call(onebot):
    receipts = asyncio.run(send_proactive_message(onebot, "789", ("first", "second")))
    call = onebot.adapter._call_api.call_args
    assert call.args[1] == "send_group_msg"
    assert call.kwargs["group_id"] == 789
    assert call.kwargs["message"].extract_plain_text() == "firstsecond"
    assert len(receipts) == 1


def test_qq_expired_passive_reply_falls_back_once_to_active_group_send(qq_bot, monkeypatch):
    message = qq_group_message(qq_bot)
    expired = ActionFailed(Response(400, content='{"code":40034005,"message":"expired"}'))
    monkeypatch.setattr(qq_bot, "send", AsyncMock(side_effect=expired))
    monkeypatch.setattr(qq_bot, "send_to_group", AsyncMock(return_value={"id": "active-id"}))

    receipts = asyncio.run(qq.QQProtocolAdapter().send(message, ("warning",)))
    qq_bot.send.assert_awaited_once_with(message._event, qq.QQMessage("warning"))
    qq_bot.send_to_group.assert_awaited_once()
    kwargs = qq_bot.send_to_group.call_args.kwargs
    assert kwargs["group_openid"] == "group"
    assert "msg_id" not in kwargs and "msg_seq" not in kwargs
    assert receipts[0].message_id == "active-id"


def test_qq_disallowed_fallback_does_not_issue_active_send(qq_bot, monkeypatch):
    message = qq_group_message(qq_bot)
    monkeypatch.setattr(qq_bot, "send", AsyncMock(side_effect=RuntimeError("failure")))
    monkeypatch.setattr(qq_bot, "send_to_group", AsyncMock())
    with pytest.raises(MessageSendError):
        asyncio.run(qq.QQProtocolAdapter().send(message, ("warning",), allow_fallback=False))
    qq_bot.send.assert_awaited_once()
    qq_bot.send_to_group.assert_not_awaited()


def test_same_group_send_uses_msg_seq_then_drops_expired_credentials(qq_bot, monkeypatch):
    message = qq_group_message(qq_bot)
    expired = ActionFailed(Response(400, content='{"code":40034031,"message":"expired"}'))
    monkeypatch.setattr(qq_bot, "send_to_group", AsyncMock(
        side_effect=[expired, {"id": "active-id"}],
    ))
    receipts = asyncio.run(qq.QQProtocolAdapter().send_to_group(message, "group", ("notice",)))
    calls = qq_bot.send_to_group.await_args_list
    assert calls[0].kwargs["msg_id"] == "incoming-id"
    assert calls[0].kwargs["msg_seq"] == 1
    assert "msg_id" not in calls[1].kwargs and "msg_seq" not in calls[1].kwargs
    assert receipts[0].message_id == "active-id"


def test_qq_interaction_acknowledgement_and_reply_use_event_id(qq_bot, monkeypatch):
    from nonebot.adapters.wind.qq import (
        ProjectQQInteractionCreateEvent,
        acknowledge_qq_interaction,
        create_qq_interaction_group_message,
        send_qq_interaction_response,
    )

    event = ProjectQQInteractionCreateEvent.model_validate({
        "id": "payload-id", "event_id": "callback-event-id", "type": 11,
        "version": 1, "timestamp": "2026-10-04T10:00:00+08:00", "scene": "group",
        "chat_type": 1, "group_openid": "group", "group_member_openid": "actor",
        "data": {"resolved": {"user_id": "actor", "message_id": "original-message"}},
    })
    put_interaction = AsyncMock()
    send_to_group = AsyncMock(return_value={"id": "sent"})
    monkeypatch.setattr(qq_bot, "put_interaction", put_interaction, raising=False)
    monkeypatch.setattr(qq_bot, "send_to_group", send_to_group, raising=False)

    asyncio.run(acknowledge_qq_interaction(qq_bot, event, 0))
    put_interaction.assert_awaited_once_with(interaction_id="payload-id", code=0)
    message = create_qq_interaction_group_message(qq_bot, event)
    assert message.message_id == "original-message"
    assert asyncio.run(qq.QQProtocolAdapter().send(message, ("reply",)))
    kwargs = send_to_group.call_args.kwargs
    assert kwargs["event_id"] == "callback-event-id"
    assert kwargs["group_openid"] == "group"
    assert "msg_id" not in kwargs


def test_qq_callback_private_response_uses_c2c_openid(qq_bot, monkeypatch):
    from nonebot.adapters.wind.qq import ProjectQQInteractionCreateEvent, send_qq_interaction_response

    event = ProjectQQInteractionCreateEvent.model_validate({
        "id": "payload-id", "event_id": "callback-event-id", "type": 11,
        "version": 1, "timestamp": "2026-10-04T10:00:00+08:00", "scene": "c2c",
        "chat_type": 2, "user_openid": "private-user",
        "data": {"resolved": {"user_id": "private-user"}},
    })
    send_to_c2c = AsyncMock(return_value={"id": "sent"})
    monkeypatch.setattr(qq_bot, "send_to_c2c", send_to_c2c, raising=False)
    asyncio.run(send_qq_interaction_response(qq_bot, event, "reply"))
    assert send_to_c2c.call_args.kwargs["openid"] == "private-user"
    assert send_to_c2c.call_args.kwargs["event_id"] == "callback-event-id"


def test_qq_interaction_result_recall_ignores_only_expired_result(qq_bot, monkeypatch):
    expired = ActionFailed(Response(400, content='{"code":40064004,"message":"expired"}'))
    delete = AsyncMock(side_effect=expired)
    monkeypatch.setattr(qq_bot, "delete_group_message", delete, raising=False)
    asyncio.run(qq.delete_qq_group_message(qq_bot, "group", "old-message"))
    delete.assert_awaited_once_with(group_openid="group", message_id="old-message")

    delete.side_effect = RuntimeError("real failure")
    with pytest.raises(RuntimeError, match="real failure"):
        asyncio.run(qq.delete_qq_group_message(qq_bot, "group", "old-message"))


def test_qq_ordered_content_preserves_split_order_and_single_message_constraint(monkeypatch):
    monkeypatch.setattr(qq, "_render_image", lambda image: qq.QQMessageSegment.image(image.data))
    content = OrderedContent(("before  ", ImageContent(data=b"image"), "\nafter"))
    rendered = asyncio.run(qq._render_content(content))
    assert [message.extract_plain_text() for message in rendered] == ["before  ", "", "\nafter"]
    assert rendered[1][0].type == "image"

    rich = RichContent(
        document=document(paragraph("caption")),
        images=(ImageContent(data=b"image"),),
        footer=document(paragraph("footer")),
        single_message=True,
    )
    with pytest.raises(qq.InvalidMessageContentError, match="图片发布失败"):
        asyncio.run(qq._render_content(rich))

    class Publisher:
        async def publish_image(self, image_data: bytes, file_name: str) -> str:
            assert image_data == b"image" and file_name == "image.png"
            return "https://cdn.example.test/image.png"

    monkeypatch.setattr(qq, "read_image_dimensions", lambda _data: (1200, 600))
    rendered_rich = asyncio.run(qq._render_content(rich, Publisher()))
    assert len(rendered_rich) == 1
    markdown = rendered_rich[0][0].data["markdown"].content
    assert "cdn.example.test/image.png" in markdown
    assert "caption" in markdown
    assert "footer" in markdown
