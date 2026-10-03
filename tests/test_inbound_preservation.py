"""Inbound normalization preserves real SDK identity and original message data."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import nonebot
from nonebot.adapters.onebot.v11 import Bot as OneBotBot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message as OneBotMessage
from nonebot.adapters.onebot.v11 import MessageSegment as OneBotSegment
from nonebot.adapters.qq import Adapter as QQAdapter
from nonebot.adapters.qq import Bot as QQBot
from nonebot.adapters.qq.config import BotInfo, Config as QQConfig
from nonebot.adapters.qq.event import GroupMessageCreateEvent
from nonebot.adapters.qq import Message as QQMessage
from nonebot.adapters.qq import MessageSegment as QQSegment

from nonebot.adapters.wind import clone_message_event, get_referenced_message
from nonebot.adapters.wind.onebot_v11 import OneBotV11ProtocolAdapter
from nonebot.adapters.wind.qq import QQProtocolAdapter


try:
    nonebot.get_driver()
except ValueError:
    nonebot.init(_env_file=None)


def qq_bot():
    adapter = object.__new__(QQAdapter)
    adapter.qq_config = QQConfig()
    return QQBot(adapter, "wind-bot", BotInfo(id="wind-bot", secret="secret"))


def onebot():
    return OneBotBot(SimpleNamespace(_call_api=AsyncMock()), "100")


def test_onebot_real_user_and_everyone_mentions_and_original_text_survive_clone():
    bot = onebot()
    event = GroupMessageEvent.model_validate({
        "time": 1234, "self_id": 100, "post_type": "message", "sub_type": "normal",
        "message_type": "group", "message_id": 77, "user_id": 456, "group_id": 789,
        "message": "[CQ:reply,id=51][CQ:at,qq=456][CQ:at,qq=all]原文  两空格[CQ:image,file=https://img.example.test/a.png]",
        "raw_message": "[CQ:reply,id=51][CQ:at,qq=456][CQ:at,qq=all]原文  两空格[CQ:image,file=https://img.example.test/a.png]",
        "font": 0, "sender": {"user_id": 456, "role": "member", "nickname": "成员"},
    })
    message = OneBotV11ProtocolAdapter().create_message(bot, event, None)
    assert message.mentioned_user_ids == ("456",)
    assert message.mentions_everyone is True
    assert message.raw_text == event.raw_message
    assert message.original_plaintext == "原文  两空格"
    assert message.message_id == "77"

    cloned = clone_message_event(message, "查询 @999 [CQ:at,qq=999]")
    types = [segment.type for segment in cloned.message]
    assert types[0] == "reply" and cloned.message[0].data["id"] == "51"
    assert [str(segment.data["qq"]) for segment in cloned.message if segment.type == "at"] == ["456"]
    assert any(segment.type == "image" for segment in cloned.message)
    assert cloned.get_plaintext() == "查询 @999 [CQ:at,qq=999]"


def test_qq_real_mentions_and_raw_text_do_not_gain_synthetic_identities():
    bot = qq_bot()
    event = GroupMessageCreateEvent.model_validate({
        "id": "incoming", "content": "<@!wind-bot> 原文  两空格", "timestamp": "2026-10-04T10:00:00+08:00",
        "group_id": "group", "group_openid": "group",
        "author": {"id": "member", "member_openid": "member", "member_role": "member", "bot": False},
    })
    event.message = QQMessage(QQSegment.mention_user("wind-bot") + QQSegment.text("原文  两空格") + QQSegment.mention_user("actual-user"))
    event.original_message = event.message.copy()

    message = QQProtocolAdapter().create_message(bot, event, None)
    assert message.mentioned_user_ids == ("actual-user",)
    assert message.raw_text == event.content
    assert message.original_plaintext == "原文  两空格"

    cloned = clone_message_event(message, "结果 <@!invented-user>")
    assert [segment.data["user_id"] for segment in cloned.message if segment.type == "mention_user"] == ["actual-user"]
    assert cloned.content == "结果 &lt;@!invented-user&gt;"


def test_qq_message_index_reference_id_and_inline_reference_are_distinct():
    bot = qq_bot()
    event = GroupMessageCreateEvent.model_validate({
        "id": "incoming", "content": "当前正文", "timestamp": "2026-10-04T10:00:00+08:00",
        "group_id": "group", "group_openid": "group", "msg_idx": "current-index",
        "message_scene": {"ext": ["ref_msg_idx=quoted-index"], "source": "reply"},
        "author": {"id": "member", "member_openid": "member", "member_role": "member", "bot": False},
        "msg_elements": [{"type": "reply", "content": "引用内容", "msg_idx": "inline-index"}],
        "reply": {"content": "被引用内容", "msg_idx": "inline-index"},
    })
    event.original_message = event.get_message().copy()
    message = QQProtocolAdapter().create_message(bot, event, None)
    assert message.message_index == "current-index"
    assert message.reference_id == "quoted-index"
    assert message.references[0].reference_id == "inline-index"
    assert message.references[0].text == "引用内容"
    resolved = asyncio.run(get_referenced_message(message))
    assert resolved.reference_id == "inline-index"
    assert resolved.text == "被引用内容"


def test_onebot_explicit_reply_id_is_resolved_without_using_current_id():
    bot = onebot()
    bot.adapter._call_api.return_value = {
        "message_id": 51,
        "message": OneBotMessage(OneBotSegment.text("被引用的原文")),
    }
    event = GroupMessageEvent.model_validate({
        "time": 1234, "self_id": 100, "post_type": "message", "sub_type": "normal",
        "message_type": "group", "message_id": 77, "user_id": 456, "group_id": 789,
        "message": "[CQ:reply,id=51]当前正文", "raw_message": "[CQ:reply,id=51]当前正文",
        "font": 0, "sender": {"user_id": 456, "role": "member"},
    })
    message = OneBotV11ProtocolAdapter().create_message(bot, event, None)
    assert message.message_id == "77"
    assert asyncio.run(get_referenced_message(message)).reference_id == "51"
    bot.adapter._call_api.assert_awaited_once_with(bot, "get_msg", message_id=51)
