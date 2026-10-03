"""OneBot V11 的统一协议实现与项目自定义连接适配器。"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from datetime import datetime, timezone
from math import ceil
from collections.abc import Sequence
from typing import Any, Literal, cast

from nonebot import get_plugin_config
from nonebot.adapters import Bot, Event
from nonebot.drivers import Driver
from .config import Config
from .inbound import register_command_preprocessor
from nonebot.adapters.onebot.v11 import Adapter as BaseAdapter
from nonebot.adapters.onebot.v11 import Bot as OneBotBot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from nonebot.adapters.onebot.v11 import Message as OneBotMessage
from nonebot.adapters.onebot.v11 import MessageSegment as OneBotMessageSegment
from nonebot.adapters.onebot.v11.event import GroupIncreaseNoticeEvent, GroupDecreaseNoticeEvent
from nonebot.drivers import WebSocket
from nonebot.exception import WebSocketClosed
from nonebot.matcher import Matcher
from nonebot.exception import MatcherException
from nonebot.utils import escape_tag
from .log import log

from .document import (
    Block,
    ButtonTable,
    CodeBlock,
    Divider,
    Document,
    Heading,
    Image,
    Inline,
    InlineCode,
    Link,
    ListBlock,
    ListItem,
    Mention,
    Paragraph,
    Quote,
    StyledText,
    Table,
    Text,
    render_plain_text,
)
from .inbound import collapse_command_spaces
from .models import (
    GroupBatchOperationError,
    GroupBlacklistPage,
    GroupBotState,
    GroupJoinRequest,
    GroupJoinRequestPage,
    GroupMemberMute,
    GroupMemberRemovalResult,
    GroupMuteSettings,
    GroupInfo,
    GroupMessage,
    GroupMember,
    GroupMemberChange,
    ImageContent,
    InboundImage,
    InvalidMessageContextError,
    MessageReferenceResolveError,
    MessageGroup,
    MessageReceipt,
    MessageSender,
    MessageSendError,
    OutboundContent,
    OrderedContent,
    PrivateMessage,
    ReferencedMessage,
    RichContent,
    UnifiedMessage,
    UnsupportedProtocolCapabilityError,
)


def _message_id(response: object) -> str | None:
    """从不同 OneBot API 返回结构中提取消息标识。"""

    if isinstance(response, dict):
        value = response.get("message_id") or response.get("id")
    else:
        value = getattr(response, "message_id", None) or getattr(response, "id", None)
    return str(value) if isinstance(value, (str, int)) else None


def _numeric_id(value: str, field_name: str) -> int:
    """在真实 OneBot API 边界将业务字符串标识转换为数字。"""

    try:
        return int(value)
    except ValueError as exc:
        raise InvalidMessageContextError(
            f"OneBot {field_name} must be numeric: {value}"
        ) from exc


def _render_content(content: OutboundContent) -> OneBotMessage:
    """将统一内容转换为 OneBot V11 消息。"""

    if isinstance(content, OrderedContent):
        message = OneBotMessage()
        for part in content.parts:
            message += OneBotMessageSegment.text(part) if isinstance(part, str) else OneBotMessageSegment.image(part.data)
        return message
    if isinstance(content, str):
        return OneBotMessage(OneBotMessageSegment.text(content))
    if isinstance(content, Document):
        return _render_document(content)
    if isinstance(content, ImageContent):
        return OneBotMessage(OneBotMessageSegment.image(content.data))

    message = OneBotMessage()
    if content.images_first:
        for image in content.images:
            message += OneBotMessageSegment.image(image.data)
    if content.document is not None:
        message += _render_document(content.document)
    if not content.images_first:
        for image in content.images:
            message += OneBotMessageSegment.image(image.data)
    if content.footer is not None:
        message += _render_document(content.footer)
    return message


def _render_document(document: Document) -> OneBotMessage:
    """渲染 OneBot 文档，并把 Mention 节点保留为真实 at 消息段。"""

    mentions: dict[str, str] = {}
    marked_parts = [
        _mark_document_node(part, mentions)
        for part in document.parts
    ]
    rendered = render_plain_text(Document(marked_parts)).text
    if not mentions:
        return OneBotMessage(OneBotMessageSegment.text(rendered))

    pattern = "(" + "|".join(re.escape(token) for token in mentions) + ")"
    message = OneBotMessage()
    for part in re.split(pattern, rendered):
        if not part:
            continue
        user_id = mentions.get(part)
        if user_id is not None:
            message += OneBotMessageSegment.at(user_id)
        else:
            message += OneBotMessageSegment.text(part)
    return message


def _mark_document_node(
    node: Inline | Block,
    mentions: dict[str, str],
) -> Inline | Block:
    """用内部文本标记替换 Mention，交由纯文本渲染器保持原有排版。"""

    if isinstance(node, Inline):
        return _mark_inline(node, mentions)
    if isinstance(node, Heading):
        return Heading(node.level, _mark_inlines(node.children, mentions))
    if isinstance(node, Paragraph):
        return Paragraph(_mark_inlines(node.children, mentions))
    if isinstance(node, Quote):
        return Quote(_mark_inlines(node.children, mentions))
    if isinstance(node, ListBlock):
        return _mark_list_block(node, mentions)
    if isinstance(node, Table):
        return Table(
            headers=tuple(
                _mark_inlines(cell, mentions)
                for cell in node.headers
            ),
            rows=tuple(
                tuple(
                    _mark_inlines(cell, mentions)
                    for cell in row
                )
                for row in node.rows
            ),
        )
    if isinstance(node, (Divider, CodeBlock, ButtonTable)):
        return node
    raise TypeError(f"unsupported document node: {type(node).__name__}")


def _mark_inline(
    node: Inline,
    mentions: dict[str, str],
) -> Inline:
    """递归替换行内 Mention 节点。"""

    if isinstance(node, Mention):
        token = f"\ue000mention-{len(mentions)}\ue001"
        mentions[token] = node.user_id
        return Text(token)
    if isinstance(node, StyledText):
        return StyledText(
            node.style,
            _mark_inlines(node.children, mentions),
        )
    if isinstance(node, Link):
        return Link(
            _mark_inlines(node.label, mentions),
            node.url,
            node.show_url_in_plain,
        )
    if isinstance(node, (Text, InlineCode, Image)):
        return node
    raise TypeError(f"unsupported inline node: {type(node).__name__}")


def _mark_inlines(
    nodes: tuple[Inline, ...],
    mentions: dict[str, str],
) -> tuple[Inline, ...]:
    """递归转换一组行内节点。"""

    return tuple(_mark_inline(node, mentions) for node in nodes)


def _mark_list_item(
    item: ListItem,
    mentions: dict[str, str],
) -> ListItem:
    """递归转换列表项正文及嵌套列表。"""

    return ListItem(
        children=_mark_inlines(item.children, mentions),
        nested=tuple(
            _mark_list_block(nested, mentions)
            for nested in item.nested
        ),
    )


def _mark_list_block(
    block: ListBlock,
    mentions: dict[str, str],
) -> ListBlock:
    """递归转换列表及其所有列表项。"""

    return ListBlock(
        block.ordered,
        tuple(_mark_list_item(item, mentions) for item in block.items),
    )


def _extract_inbound_images(message: OneBotMessage) -> tuple[InboundImage, ...]:
    """从 OneBot 消息段中提取所有图片 URL。"""

    images: list[InboundImage] = []
    for segment in message:
        if segment.type != "image":
            continue
        url = segment.data.get("url") or segment.data.get("file")
        if not url:
            continue
        size = segment.data.get("size")
        content_type = segment.data.get("content_type")
        filename = segment.data.get("file")
        images.append(
            InboundImage(
                url=str(url),
                content_type=(
                    str(content_type)
                    if isinstance(content_type, str) and content_type
                    else None
                ),
                filename=(
                    str(filename)
                    if isinstance(filename, str) and filename
                    else None
                ),
                size=size if isinstance(size, int) and not isinstance(size, bool) else None,
            )
        )
    return tuple(images)


def _extract_content_parts(message: OneBotMessage) -> tuple[str | InboundImage, ...]:
    """原始消息只提取真实文本和图片，不将 @、回复或 CQ 编码变成正文。"""
    parts: list[str | InboundImage] = []
    for segment in message:
        if segment.type == "text":
            parts.append(str(segment.data["text"]))
        elif segment.type == "image":
            parts.extend(_extract_inbound_images(OneBotMessage(segment)))
    return tuple(parts)


def _extract_inbound_mentions(
    message: OneBotMessage,
    excluded_user_id: str | None = None,
) -> tuple[str, ...]:
    """提取 OneBot at 消息段，忽略全体成员标记。"""

    user_ids: list[str] = []
    for segment in message:
        if segment.type != "at":
            continue
        user_id = str(segment.data.get("qq", ""))
        if (
            not user_id
            or user_id == "all"
            or user_id == excluded_user_id
            or user_id in user_ids
        ):
            continue
        user_ids.append(user_id)
    return tuple(user_ids)


class OneBotV11ProtocolAdapter:
    """把 OneBot V11 事件和 API 转换为项目统一协议能力。"""

    protocol: Literal["onebot_v11"] = "onebot_v11"

    def supports_event(self, event: Event) -> bool:
        """判断事件是否为 OneBot V11 群聊或私聊消息。"""

        return isinstance(event, (GroupMessageEvent, PrivateMessageEvent))

    def get_group_member_change(self, bot: Bot, event: Event) -> GroupMemberChange | None:
        if not isinstance(event, (GroupIncreaseNoticeEvent, GroupDecreaseNoticeEvent)):
            return None
        if str(event.user_id) == bot.self_id:
            return None
        return GroupMemberChange(
            protocol=self.protocol, group_id=str(event.group_id), user_id=str(event.user_id),
            kind="join" if isinstance(event, GroupIncreaseNoticeEvent) else "leave",
            timestamp=datetime.fromtimestamp(event.time, timezone.utc),
        )

    def create_message(
        self,
        bot: Bot,
        event: Event,
        matcher: Matcher | None,
    ) -> UnifiedMessage:
        """将 OneBot V11 消息事件转换为统一消息。"""

        # 预处理器并发执行，统一消息被提前读取时也应采用相同命令视图。
        if isinstance(bot.adapter, ProjectOneBotV11Adapter) and bot.adapter.wind_config.wind_collapse_command_spaces:
            collapse_command_spaces(event)
        if isinstance(event, GroupMessageEvent):
            return GroupMessage(
                protocol=self.protocol,
                transport="websocket",
                message_id=str(event.message_id),
                text=event.get_plaintext(),
                raw_text=event.raw_message,
                original_plaintext=event.original_message.extract_plain_text(),
                is_to_me=event.to_me,
                sender=MessageSender(
                    id=str(event.user_id),
                    name=event.sender.card or event.sender.nickname,
                    avatar_url=f"https://q1.qlogo.cn/g?b=qq&nk={event.user_id}&s=640",
                    role=_group_role(event.sender.role),
                ),
                group=MessageGroup(id=str(event.group_id), name=None),
                mentions_everyone=any(
                    segment.type == "at" and segment.data.get("qq") == "all"
                    for segment in event.message
                ),
                images=_extract_inbound_images(event.message),
                content_parts=_extract_content_parts(event.original_message),
                mentioned_user_ids=_extract_inbound_mentions(
                    event.message,
                    str(getattr(bot, "self_id", event.self_id)),
                ),
                _bot=bot,
                _event=event,
                _matcher=matcher,
            )
        if isinstance(event, PrivateMessageEvent):
            return PrivateMessage(
                protocol=self.protocol,
                transport="websocket",
                message_id=str(event.message_id),
                text=event.get_plaintext(),
                raw_text=event.raw_message,
                original_plaintext=event.original_message.extract_plain_text(),
                is_to_me=event.to_me,
                sender=MessageSender(
                    id=str(event.user_id),
                    name=event.sender.nickname,
                    avatar_url=f"https://q1.qlogo.cn/g?b=qq&nk={event.user_id}&s=640",
                ),
                images=_extract_inbound_images(event.message),
                content_parts=_extract_content_parts(event.original_message),
                mentioned_user_ids=_extract_inbound_mentions(
                    event.message,
                    str(getattr(bot, "self_id", event.self_id)),
                ),
                _bot=bot,
                _event=event,
                _matcher=matcher,
            )
        raise InvalidMessageContextError(
            f"unsupported OneBot event: {type(event).__name__}"
        )

    def clone_event(
        self,
        message: UnifiedMessage,
        text: str,
    ) -> Event:
        """克隆 OneBot 消息事件，仅替换命令内容并保留会话身份。"""

        event = message._event
        if not isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
            raise InvalidMessageContextError(
                f"unsupported OneBot event clone: {type(event).__name__}"
            )
        cloned_message = OneBotMessage()
        reply = next((segment for segment in event.message if segment.type == "reply"), None)
        if reply is not None:
            cloned_message += reply
        cloned_message += OneBotMessageSegment.text(text)
        for segment in event.message:
            if segment.type == "image":
                cloned_message += segment
            elif segment.type == "at" and str(segment.data.get("qq")) in message.mentioned_user_ids:
                # 只保留原消息真实用户提及，模型生成的正文不能新增目标身份。
                cloned_message += segment
        return event.model_copy(
            update={
                "message": cloned_message,
                "original_message": cloned_message,
                "raw_message": text,
                "to_me": True,
            }
        )

    async def get_referenced_message(
        self,
        message: UnifiedMessage,
    ) -> ReferencedMessage | None:
        """通过 reply 段和 get_msg 获取 OneBot 原消息。"""

        event = message._event
        if not isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
            raise InvalidMessageContextError(
                f"unsupported OneBot reference context: {type(event).__name__}"
            )
        reply = next((segment for segment in event.message if segment.type == "reply"), None)
        if reply is None:
            return None
        reference_id = str(reply.data.get("id", "")).strip()
        if not reference_id:
            raise MessageReferenceResolveError("OneBot reply segment has no message id")
        try:
            response = await _call_capability(
                message._bot,
                "get_msg",
                message_id=_numeric_id(reference_id, "message_id"),
            )
            if not isinstance(response, dict) or "message" not in response:
                raise ValueError("get_msg response has no message")
            referenced = OneBotMessage(response["message"])
        except Exception as exc:
            raise MessageReferenceResolveError(
                "OneBot referenced message lookup failed"
            ) from exc
        return ReferencedMessage(
            reference_id=reference_id,
            text=referenced.extract_plain_text(),
            images=_extract_inbound_images(referenced),
        )

    def _forward_nodes(
        self,
        message: UnifiedMessage,
        contents: Sequence[OutboundContent],
    ) -> list[OneBotMessageSegment]:
        """把多项统一内容构造成 OneBot 合并转发节点。"""

        user_id = _numeric_id(message.sender.id, "user_id")
        sender_name = message.sender.name or message.sender.id
        return [
            OneBotMessageSegment.node_custom(
                user_id,
                sender_name,
                _render_content(content),
            )
            for content in contents
        ]

    async def send(
        self,
        message: UnifiedMessage,
        contents: Sequence[OutboundContent],
        *, reply_to_source: bool = False, allow_fallback: bool = True,
    ) -> list[MessageReceipt]:
        """回复当前 OneBot 事件；群聊多段合并转发，私聊按顺序逐段发送。"""

        try:
            if reply_to_source:
                rendered = OneBotMessage()
                if message.message_id:
                    rendered += OneBotMessageSegment.reply(_numeric_id(message.message_id, "message_id"))
                else:
                    log("WARNING", "引用警告缺少 OneBot 消息 ID，仅发送正文")
                for content in contents:
                    rendered += _render_content(content)
                responses = [await message._bot.send(message._event, rendered)]
            elif len(contents) == 1:
                responses = [
                    await message._bot.send(
                        message._event,
                        _render_content(contents[0]),
                    )
                ]
            elif isinstance(message, GroupMessage):
                responses = [
                    await message._bot.call_api(
                        "send_group_forward_msg",
                        group_id=_numeric_id(message.group.id, "group_id"),
                        messages=self._forward_nodes(message, contents),
                    )
                ]
            else:
                responses = [
                    await message._bot.send(
                        message._event,
                        _render_content(content),
                    )
                    for content in contents
                ]
        except (InvalidMessageContextError, MatcherException):
            raise
        except Exception as exc:
            raise MessageSendError("OneBot message send failed") from exc
        return [MessageReceipt(_message_id(response)) for response in responses]

    async def send_to_group(
        self,
        message: UnifiedMessage,
        group_id: str,
        contents: Sequence[OutboundContent],
    ) -> list[MessageReceipt]:
        """主动向指定 OneBot 群发送统一内容。"""

        try:
            if len(contents) == 1:
                response = await message._bot.call_api(
                    "send_group_msg",
                    group_id=_numeric_id(group_id, "group_id"),
                    message=_render_content(contents[0]),
                )
            else:
                response = await message._bot.call_api(
                    "send_group_forward_msg",
                    group_id=_numeric_id(group_id, "group_id"),
                    messages=self._forward_nodes(message, contents),
                )
        except (InvalidMessageContextError, MatcherException):
            raise
        except Exception as exc:
            raise MessageSendError("OneBot group message send failed") from exc
        return [MessageReceipt(_message_id(response))]

    async def send_proactive(
        self, bot: Bot, target_id: str, contents: Sequence[OutboundContent], *, private: bool,
    ) -> list[MessageReceipt]:
        """无入站会话的主动发送，图文保持在同一条消息中。"""
        combined = OneBotMessage()
        for content in contents:
            combined += _render_content(content)
        try:
            response = await bot.call_api(
                "send_private_msg" if private else "send_group_msg",
                **{"user_id" if private else "group_id": _numeric_id(target_id, "target_id")},
                message=combined,
            )
        except MatcherException:
            raise
        except Exception:
            raise MessageSendError("OneBot proactive message send failed") from None
        return [MessageReceipt(_message_id(response))]

    async def get_group_info(
        self,
        message: GroupMessage,
        group_id: str,
    ) -> GroupInfo | None:
        """查询并转换 OneBot 群资料。"""

        result = await _call_capability(
            message._bot,
            "get_group_info",
            group_id=_numeric_id(group_id, "group_id"),
        )
        if not isinstance(result, dict):
            return None
        return GroupInfo(
            id=str(result.get("group_id", group_id)),
            name=result.get("group_name"),
            member_count=result.get("member_count"),
            max_member_count=result.get("max_member_count"),
            avatar_url=f"https://p.qlogo.cn/gh/{group_id}/{group_id}/640",
        )

    async def get_groups(
        self,
        message: UnifiedMessage,
    ) -> list[GroupInfo]:
        """查询并转换当前 OneBot 账号已加入的群列表。"""

        result = await _call_capability(message._bot, "get_group_list")
        if not isinstance(result, list):
            return []
        groups: list[GroupInfo] = []
        for value in result:
            if not isinstance(value, dict):
                continue
            group_id = value.get("group_id")
            if not isinstance(group_id, (str, int)):
                continue
            groups.append(
                GroupInfo(
                    id=str(group_id),
                    name=value.get("group_name"),
                    member_count=value.get("member_count"),
                    max_member_count=value.get("max_member_count"),
                )
            )
        return groups

    async def get_group_member(
        self,
        message: GroupMessage | Bot,
        group_id: str,
        user_id: str,
        *, fresh: bool = False,
    ) -> GroupMember | None:
        """查询并转换 OneBot 群成员资料。"""

        result = await _call_capability(
            message if isinstance(message, Bot) else message._bot,
            "get_group_member_info",
            group_id=_numeric_id(group_id, "group_id"),
            user_id=_numeric_id(user_id, "user_id"),
            no_cache=fresh,
        )
        return _group_member(result, user_id)

    async def get_group_members(
        self,
        message: GroupMessage,
        group_id: str,
    ) -> list[GroupMember]:
        """查询并转换 OneBot 群成员列表。"""

        result = await _call_capability(
            message._bot,
            "get_group_member_list",
            group_id=_numeric_id(group_id, "group_id"),
        )
        if not isinstance(result, list):
            return []
        return [
            member
            for item in result
            if (member := _group_member(item, str(item.get("user_id", ""))))
            is not None
        ]


    async def recall_group_message(self, message: GroupMessage) -> None:
        if message.message_id is None:
            raise InvalidMessageContextError("撤回缺少消息 ID")
        await cast(OneBotBot, message._bot).delete_msg(message_id=_numeric_id(message.message_id, "message_id"))

    async def get_group_bot_state(self, bot: Bot, group_id: str) -> GroupBotState:
        result = await cast(OneBotBot, bot).get_group_member_info(
            group_id=_numeric_id(group_id, "group_id"),
            user_id=_numeric_id(bot.self_id, "user_id"), no_cache=True,
        )
        return GroupBotState(role=_group_role(result.get("role")))

    async def get_group_mute_settings(self, bot: Bot, group_id: str) -> GroupMuteSettings:
        raise UnsupportedProtocolCapabilityError("OneBot v11 不支持查询群禁言规则")

    async def set_group_members_mute(
        self, bot: Bot, group_id: str, members: Sequence[GroupMemberMute],
    ) -> None:
        target_group = _numeric_id(group_id, "group_id")
        targets = [_numeric_id(item.user_id, "user_id") for item in members]
        completed: list[str] = []
        for item, target in zip(members, targets):
            # OneBot 使用相对秒数；排队期间过期不能变成 duration=0 而误解禁。
            duration = 0
            if item.op != "del":
                assert item.expires_at is not None
                duration = ceil((item.expires_at - datetime.now(timezone.utc)).total_seconds())
                if duration <= 0:
                    raise GroupBatchOperationError(tuple(completed), item.user_id)
            try:
                await cast(OneBotBot, bot).set_group_ban(
                    group_id=target_group, user_id=target, duration=duration,
                )
            except MatcherException:
                raise
            except Exception as exc:
                raise GroupBatchOperationError(tuple(completed), item.user_id) from exc
            completed.append(item.user_id)

    async def get_group_join_requests(
        self, bot: Bot, group_id: str, *, cursor: str | None, limit: int | None,
    ) -> GroupJoinRequestPage:
        raise UnsupportedProtocolCapabilityError("OneBot v11 不支持拉取入群申请列表，请使用真实申请事件")

    async def approve_group_join_request(
        self, bot: Bot, group_id: str, request: GroupJoinRequest, *, approve: bool,
        reason: str | None, add_to_blacklist: bool,
    ) -> None:
        if add_to_blacklist:
            raise UnsupportedProtocolCapabilityError("OneBot v11 入群审批不支持加入平台黑名单")
        await cast(OneBotBot, bot).set_group_add_request(
            flag=request.request_id, sub_type=request.sub_type, approve=approve,
            reason=reason or "",
        )

    async def remove_group_members(
        self, bot: Bot, group_id: str, user_ids: Sequence[str], *, add_to_blacklist: bool,
    ) -> GroupMemberRemovalResult:
        target_group = _numeric_id(group_id, "group_id")
        targets = [_numeric_id(user_id, "user_id") for user_id in user_ids]
        completed: list[str] = []
        for user_id, target in zip(user_ids, targets):
            try:
                await cast(OneBotBot, bot).set_group_kick(
                    group_id=target_group, user_id=target,
                    reject_add_request=add_to_blacklist,
                )
            except MatcherException:
                raise
            except Exception as exc:
                raise GroupBatchOperationError(tuple(completed), user_id) from exc
            completed.append(user_id)
        return GroupMemberRemovalResult(True)

    async def get_group_blacklist(
        self, bot: Bot, group_id: str, *, cursor: str | None, limit: int | None,
    ) -> GroupBlacklistPage:
        raise UnsupportedProtocolCapabilityError("OneBot v11 不支持查询平台群黑名单")

    async def set_group_blacklist(
        self, bot: Bot, group_id: str, user_ids: Sequence[str], *, add: bool,
    ) -> tuple[str, ...]:
        raise UnsupportedProtocolCapabilityError("OneBot v11 不支持独立增删平台群黑名单")


def _group_member(value: object, fallback_id: str) -> GroupMember | None:
    """把 OneBot 群成员字典转换为统一成员模型。"""

    if not isinstance(value, dict):
        return None
    return GroupMember(
        id=str(value.get("user_id", fallback_id)),
        nickname=value.get("nickname"),
        card=value.get("card"),
        role=_group_role(value.get("role")),
    )


def _group_role(value: object) -> Literal["owner", "admin", "member", "unknown"]:
    """把 OneBot 角色字段收窄为统一群角色。"""

    if value == "owner":
        return "owner"
    if value == "admin":
        return "admin"
    if value == "member":
        return "member"
    return "unknown"


async def _call_capability(
    bot: Bot,
    method_name: str,
    **kwargs: object,
) -> object:
    """调用 OneBot 动态 API，并显式识别能力缺失。"""

    method = getattr(bot, method_name, None)
    if not callable(method):
        raise UnsupportedProtocolCapabilityError(
            f"OneBot bot does not support {method_name}"
        )
    result = method(**kwargs)
    if not inspect.isawaitable(result):
        raise UnsupportedProtocolCapabilityError(
            f"OneBot capability is not async: {method_name}"
        )
    return await result


class _ReverseWebSocketBot(OneBotBot):
    """标记反向 WebSocket 的 Bot 所有权，避免替换主动连接或 HTTP Bot。"""


class ProjectOneBotV11Adapter(BaseAdapter):
    """允许相同 self_id 的新连接替换旧连接的项目 OneBot Adapter。"""

    def __init__(self, driver: Driver, **kwargs: Any) -> None:
        from .group_join import GroupJoinApprover

        self.wind_config = get_plugin_config(Config)
        self.group_join_approver = GroupJoinApprover()
        super().__init__(driver, **kwargs)
        register_command_preprocessor()

    async def _stop(self) -> None:
        try:
            await super()._stop()
        finally:
            self.group_join_approver.clear()

    async def _handle_ws(self, websocket: WebSocket) -> None:
        self_id = websocket.request.headers.get("x-self-id")
        if not self_id:
            log("WARNING", "Missing X-Self-ID Header")
            await websocket.close(1008, "Missing X-Self-ID Header")
            return

        response = self._check_access_token(websocket.request)
        if response is not None:
            await websocket.close(1008, cast(str, response.content))
            return

        await websocket.accept()
        old_bot = self.bots.get(self_id)
        if old_bot is not None and not isinstance(old_bot, _ReverseWebSocketBot):
            log("WARNING", f"Bot {escape_tag(self_id)} is managed by another transport, ignored")
            await websocket.close(1008, "Duplicate X-Self-ID from another transport")
            return
        bot = _ReverseWebSocketBot(self, self_id)
        old_ws = self.connections.get(self_id)
        # 握手成功后同步转移所有权，期间不让旧连接的 finally 插入执行。
        if old_bot is not None:
            self.bot_disconnect(old_bot)
        self.bot_connect(bot)
        self.connections[self_id] = websocket

        log("INFO", f"<y>Bot {escape_tag(self_id)}</y> connected")
        try:
            if old_ws is not None:
                try:
                    await asyncio.wait_for(old_ws.close(), timeout=5)
                except Exception as exc:
                    log("WARNING", f"Closing replaced Bot {escape_tag(self_id)} WebSocket failed", exc)
            while self.bots.get(self_id) is bot:
                data = await websocket.receive()
                # 关闭旧连接期间仍可能收到消息，过时连接不再产生业务任务。
                if self.bots.get(self_id) is not bot:
                    break
                if event := self.json_to_event(json.loads(data)):
                    task = asyncio.create_task(bot.handle_event(event))
                    task.add_done_callback(self.tasks.discard)
                    self.tasks.add(task)
        except WebSocketClosed:
            log("WARNING", f"WebSocket for Bot {escape_tag(self_id)} closed by peer")
        except Exception as exc:
            log("ERROR", f"Error processing WebSocket for Bot {escape_tag(self_id)}", exc)
        finally:
            # 先按对象身份解除自己的注册，异步关闭不能删除后来的同号连接。
            if self.connections.get(self_id) is websocket:
                self.connections.pop(self_id)
            if self.bots.get(self_id) is bot:
                self.bot_disconnect(bot)
            try:
                await asyncio.wait_for(websocket.close(), timeout=5)
            except Exception as exc:
                log("WARNING", f"Closing Bot {escape_tag(self_id)} WebSocket failed", exc)


Adapter = ProjectOneBotV11Adapter


def register(driver: Driver, **kwargs: Any) -> None:
    """校验后注册，防止框架静默忽略同名官方适配器。"""
    if Adapter.get_name() in driver._adapters:
        raise RuntimeError("OneBot V11 已注册，不能重复注册 Wind 或官方适配器")
    driver.register_adapter(Adapter, **kwargs)
