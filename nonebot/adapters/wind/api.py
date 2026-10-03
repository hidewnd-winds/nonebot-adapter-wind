"""业务侧统一使用的消息、发送和群资料 API。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TypeAlias
from urllib.parse import quote

from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import Bot as OneBot
from nonebot.adapters.qq import Bot as QQBot
from nonebot.matcher import Matcher


from .base import ProtocolAdapter
from .document import Document, document, paragraph, quote as blockquote
from .models import (
    GroupBlacklistPage,
    GroupBotState,
    GroupJoinRequest,
    GroupJoinRequestPage,
    GroupMemberMute,
    GroupMemberRemovalResult,
    GroupMuteSettings,
    GroupInfo,
    GroupMember,
    GroupMemberChange,
    GroupMessage,
    ImageContent,
    InvalidMessageContentError,
    InvalidMessageContextError,
    MessageReceipt,
    OutboundContent,
    OrderedContent,
    ProtocolName,
    ReferencedMessage,
    RichContent,
    UnifiedMessage,
    UnsupportedProtocolEventError,
    UserFacingError,
)
from .onebot_v11 import OneBotV11ProtocolAdapter
from .qq import QQProtocolAdapter

_PROTOCOL_ADAPTERS: tuple[ProtocolAdapter, ...] = (
    OneBotV11ProtocolAdapter(),
    QQProtocolAdapter(),
)

CommandResult: TypeAlias = OutboundContent | Sequence[OutboundContent]
"""所有插件命令均可返回的统一响应内容。"""

CommandAction: TypeAlias = Callable[[], Awaitable[CommandResult]]
"""返回统一响应内容的异步业务动作。"""

@dataclass(frozen=True)
class _ResponsePresentation:
    """一次响应链的需求引用与经模型核对的结果摘要。"""
    request_summary: str
    result_summary: str


_markdown_response: ContextVar[_ResponsePresentation | None] = ContextVar("markdown_response", default=None)
_receipt_observer: ContextVar[Callable[[list[MessageReceipt]], None] | None] = ContextVar("receipt_observer", default=None)


@contextmanager
def observe_message_receipts(observer: Callable[[list[MessageReceipt]], None]) -> Iterator[None]:
    """请求调用方可收集实际发送回执；不观察其他并发请求。"""
    token = _receipt_observer.set(observer)
    try:
        yield
    finally:
        _receipt_observer.reset(token)


@contextmanager
def prefer_markdown_response(request_summary: str = "", *, result_summary: str = "") -> Iterator[None]:
    """当前响应链在 QQ 优先使用结构化图文，可给图片附加需求引用。"""
    token = _markdown_response.set(_ResponsePresentation(request_summary, result_summary))
    try:
        yield
    finally:
        _markdown_response.reset(token)


def _format_markdown_contents(
    contents: tuple[OutboundContent, ...], presentation: _ResponsePresentation, *, markdown: bool,
) -> tuple[OutboundContent, ...]:
    """将普通响应接入既有文档与 COS 图文渲染，保留业务已构造的文档。"""
    formatted: list[OutboundContent] = []
    for content in contents:
        if isinstance(content, str) and markdown:
            formatted.append(document(paragraph(content)))
        elif isinstance(content, ImageContent) and (markdown or presentation.result_summary):
            caption = Document()
            if markdown and presentation.request_summary:
                caption.append(blockquote(presentation.request_summary))
            if presentation.result_summary:
                caption.append(paragraph(presentation.result_summary))
            formatted.append(RichContent(
                document=caption if caption.parts else None,
                images=(content,),
            ))
        elif isinstance(content, RichContent) and content.images and presentation.result_summary:
            caption = document(paragraph(presentation.result_summary))
            if content.document is not None:
                caption.parts.extend(content.document.parts)
            formatted.append(replace(content, document=caption))
        else:
            formatted.append(content)
    return tuple(formatted)


def get_user_avatar_url(message: UnifiedMessage, user_id: str | None = None) -> str | None:
    """取得发送者或真实提及用户的头像；QQ OpenID 不当作 QQ 号码使用。"""
    if user_id is None or user_id == message.sender.id:
        return message.sender.avatar_url
    if message.protocol == "onebot_v11":
        return f"https://q1.qlogo.cn/g?b=qq&nk={quote(user_id, safe='')}&s=640"
    return f"https://q.qlogo.cn/qqapp/{message._bot.self_id}/{quote(user_id, safe='')}/640"


def get_bot_protocol(bot: Bot) -> ProtocolName:
    """主动推送按实际在线 Bot 类型选择协议。"""
    if isinstance(bot, OneBot):
        return "onebot_v11"
    if isinstance(bot, QQBot):
        return "qq"
    raise UnsupportedProtocolEventError("unsupported bot protocol")


def get_group_member_change(bot: Bot, event: Event) -> GroupMemberChange | None:
    """按真实 Bot 协议解析成员变动，不创建虚假的消息上下文。"""
    return _get_adapter_by_protocol(get_bot_protocol(bot)).get_group_member_change(bot, event)


async def send_proactive_message(
    bot: Bot, target_id: str, content: OutboundContent | Sequence[OutboundContent], *, private: bool = False,
) -> list[MessageReceipt]:
    """发送群推送或管理员私聊，不创建虚假的入站消息。"""
    adapter = _get_adapter_by_protocol(get_bot_protocol(bot))
    receipts = await adapter.send_proactive(bot, target_id, _normalize_contents(content), private=private)
    return receipts


def _normalize_contents(
    content: OutboundContent | Sequence[OutboundContent],
) -> tuple[OutboundContent, ...]:
    """把单个内容和内容序列规范为非空元组。"""

    if isinstance(content, (str, Document, ImageContent, RichContent, OrderedContent)):
        return (content,)
    contents = tuple(content)
    if not contents:
        raise InvalidMessageContentError("message content sequence cannot be empty")
    if not all(
        isinstance(item, (str, Document, ImageContent, RichContent, OrderedContent))
        for item in contents
    ):
        raise InvalidMessageContentError("unsupported message content type")
    return contents


def _get_adapter_by_protocol(protocol: ProtocolName) -> ProtocolAdapter:
    """根据统一消息中记录的平台协议选择实现。"""

    for adapter in _PROTOCOL_ADAPTERS:
        if adapter.protocol == protocol:
            return adapter
    raise UnsupportedProtocolEventError(f"unsupported message protocol: {protocol}")


def get_unified_message(
    bot: Bot,
    event: Event,
    matcher: Matcher,
) -> UnifiedMessage:
    """将当前 NoneBot 会话转换成业务统一消息。"""

    for adapter in _PROTOCOL_ADAPTERS:
        if adapter.supports_event(event):
            return adapter.create_message(bot, event, matcher)
    raise UnsupportedProtocolEventError(
        f"unsupported message event: {type(event).__name__}"
    )


def try_get_unified_message(
    bot: Bot,
    event: Event,
    matcher: Matcher | None = None,
) -> UnifiedMessage | None:
    """尝试转换统一消息，供 Matcher 创建前的权限和规则阶段使用。"""

    for adapter in _PROTOCOL_ADAPTERS:
        if adapter.supports_event(event):
            return adapter.create_message(bot, event, matcher)
    return None


def clone_message_event(
    message: UnifiedMessage,
    text: str,
) -> Event:
    """按消息来源协议克隆事件并替换文本，供项目内部命令重放。"""

    adapter = _get_adapter_by_protocol(message.protocol)
    return adapter.clone_event(message, text)


async def get_referenced_message(
    message: UnifiedMessage,
) -> ReferencedMessage | None:
    """按消息来源协议解析其明确引用的原消息。"""

    adapter = _get_adapter_by_protocol(message.protocol)
    return await adapter.get_referenced_message(message)


async def send_message(
    message: UnifiedMessage,
    content: OutboundContent | Sequence[OutboundContent],
    *,
    finish: bool = True,
    reply_to_source: bool = False,
    allow_fallback: bool = True,
) -> list[MessageReceipt]:
    """发送统一内容；不结束 Matcher 时返回回执，供调用方管理已发送消息。"""

    matcher = message._matcher
    if finish and matcher is None:
        raise InvalidMessageContextError(
            "finishing a message requires matcher context"
        )
    contents = _normalize_contents(content)
    presentation = _markdown_response.get()
    if presentation is not None:
        contents = _format_markdown_contents(contents, presentation, markdown=message.protocol == "qq")
    adapter = _get_adapter_by_protocol(message.protocol)
    receipts = (await adapter.send(message, contents, reply_to_source=reply_to_source, allow_fallback=allow_fallback)
                if reply_to_source or not allow_fallback else await adapter.send(message, contents))
    observer = _receipt_observer.get()
    if observer is not None:
        observer(receipts)
    if finish:
        # finish 通过框架异常终止事件处理，必须在平台发送成功后原样抛出。
        assert matcher is not None
        await matcher.finish()
    return receipts


async def finish_command_action(
    message: UnifiedMessage,
    action: CommandAction,
    *,
    finish: bool = True,
) -> None:
    """执行命令动作，并通过统一适配器返回成功或业务失败结果。"""

    try:
        content = await action()
    except UserFacingError as exc:
        content = exc.message
    await send_message(message, content, finish=finish)


async def send_group_message(
    message: UnifiedMessage,
    group_id: str,
    content: OutboundContent | Sequence[OutboundContent],
) -> list[MessageReceipt]:
    """使用当前平台 Bot 向指定群发送统一内容。"""

    contents = _normalize_contents(content)
    adapter = _get_adapter_by_protocol(message.protocol)
    target_group_id = str(group_id)
    receipts = await adapter.send_to_group(message, target_group_id, contents)
    return receipts


async def get_group_info(
    message: GroupMessage,
    group_id: str | None = None,
) -> GroupInfo | None:
    """查询指定群资料；省略群标识时使用当前消息群。"""

    target_group_id = str(group_id) if group_id is not None else message.group.id
    adapter = _get_adapter_by_protocol(message.protocol)
    return await adapter.get_group_info(message, target_group_id)


async def get_groups(message: UnifiedMessage) -> list[GroupInfo]:
    """查询当前平台 Bot 已加入的群列表。"""

    adapter = _get_adapter_by_protocol(message.protocol)
    return await adapter.get_groups(message)


async def get_group_member(
    message: GroupMessage | Bot,
    user_id: str | None = None,
    group_id: str | None = None,
    *, fresh: bool = False,
) -> GroupMember | None:
    """查询群成员；Bot 调用须明确群和用户，消息调用仍可省略标识。"""

    if isinstance(message, Bot):
        if not group_id or not user_id:
            raise InvalidMessageContextError("Bot 查询群成员必须提供 group_id 和 user_id")
        adapter = _get_adapter_by_protocol(get_bot_protocol(message))
        return await adapter.get_group_member(message, group_id, user_id, fresh=fresh)

    target_group_id = str(group_id) if group_id is not None else message.group.id
    target_user_id = str(user_id) if user_id is not None else message.sender.id
    adapter = _get_adapter_by_protocol(message.protocol)
    return await adapter.get_group_member(
        message,
        target_group_id,
        target_user_id,
        fresh=fresh,
    )


async def get_group_members(
    message: GroupMessage,
    group_id: str | None = None,
) -> list[GroupMember]:
    """查询群成员列表；省略群标识时使用当前消息群。"""

    target_group_id = str(group_id) if group_id is not None else message.group.id
    adapter = _get_adapter_by_protocol(message.protocol)
    return await adapter.get_group_members(message, target_group_id)


async def recall_group_message(message: GroupMessage) -> None:
    """撤回原始消息，平台 ID 与 QQ 引用索引不可互换。"""
    if not message.message_id:
        raise InvalidMessageContextError("撤回缺少消息 ID")
    await _get_adapter_by_protocol(message.protocol).recall_group_message(message)


async def get_group_bot_state(bot: Bot, group_id: str) -> GroupBotState:
    """查询当前 Bot 的群角色及消息权限，不推断平台未提供的字段。"""
    return await _get_adapter_by_protocol(get_bot_protocol(bot)).get_group_bot_state(bot, group_id)


async def get_group_mute_settings(bot: Bot, group_id: str) -> GroupMuteSettings:
    """查询平台禁言设置，不用本地缓存伪装平台状态。"""
    return await _get_adapter_by_protocol(get_bot_protocol(bot)).get_group_mute_settings(bot, group_id)


async def set_group_members_mute(
    bot: Bot, group_id: str, members: Sequence[GroupMemberMute],
) -> None:
    """单批修改禁言，调用方负责业务授权；写入失败不自动重试。

    OneBot 逐人执行，中途失败通过 GroupBatchOperationError 保留已完成名单。
    """
    _validate_group_member_batch([item.user_id for item in members])
    now = datetime.now(timezone.utc)
    for item in members:
        if item.op != "del":
            if item.expires_at is None or not 0 < (item.expires_at - now).total_seconds() <= 30 * 86400:
                raise ValueError("禁言到期时间必须在未来 30 天内")
    await _get_adapter_by_protocol(get_bot_protocol(bot)).set_group_members_mute(bot, group_id, members)


async def get_group_join_requests(
    bot: Bot, group_id: str, *, cursor: str | None = None, limit: int | None = None,
) -> GroupJoinRequestPage:
    """查询一页入群申请；游标由调用方原样传回，不保存业务待审批队列。"""
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 50):
        raise ValueError("入群申请每页数量必须在 1 到 50 之间")
    return await _get_adapter_by_protocol(get_bot_protocol(bot)).get_group_join_requests(
        bot, group_id, cursor=cursor, limit=limit,
    )


async def approve_group_join_request(
    bot: Bot, group_id: str, request: GroupJoinRequest, *, approve: bool,
    reason: str | None = None, add_to_blacklist: bool = False,
) -> None:
    """审批真实平台申请；业务权限、并发领取及限流由原业务入口负责。"""
    if not group_id or not request.request_id or not request.user_id:
        raise ValueError("入群申请缺少群、申请或用户标识")
    if approve and (add_to_blacklist or reason is not None):
        raise ValueError("同意申请时不能同时指定拒绝理由或拉黑")
    if request.sub_type not in ("add", "invite"):
        raise ValueError("入群申请类型无效")
    await _get_adapter_by_protocol(get_bot_protocol(bot)).approve_group_join_request(
        bot, group_id, request, approve=approve, reason=reason, add_to_blacklist=add_to_blacklist,
    )


async def remove_group_members(
    bot: Bot, group_id: str, user_ids: Sequence[str], *, add_to_blacklist: bool = False,
) -> GroupMemberRemovalResult:
    """单批移除成员；OneBot 的附带选项对应 reject_add_request。

    OneBot 中途失败通过 GroupBatchOperationError 保留已完成名单，不能整体重试。
    """
    _validate_group_member_batch(user_ids)
    return await _get_adapter_by_protocol(get_bot_protocol(bot)).remove_group_members(
        bot, group_id, user_ids, add_to_blacklist=add_to_blacklist,
    )


async def get_group_blacklist(
    bot: Bot, group_id: str, *, cursor: str | None = None, limit: int | None = None,
) -> GroupBlacklistPage:
    """查询平台黑名单，与本地业务避雷名单无关。"""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("黑名单每页数量必须是正整数")
    return await _get_adapter_by_protocol(get_bot_protocol(bot)).get_group_blacklist(
        bot, group_id, cursor=cursor, limit=limit,
    )


async def set_group_blacklist(
    bot: Bot, group_id: str, user_ids: Sequence[str], *, add: bool,
) -> tuple[str, ...]:
    """单批增删平台黑名单，返回失败名单，不隐式踢人或修改本地避雷记录。"""
    _validate_group_member_batch(user_ids)
    return await _get_adapter_by_protocol(get_bot_protocol(bot)).set_group_blacklist(
        bot, group_id, user_ids, add=add,
    )


def _validate_group_member_batch(user_ids: Sequence[str]) -> None:
    """在公开写接口边界校验单批限制，拒绝重复目标而非静默归一化。"""
    if isinstance(user_ids, (str, bytes)) or not 1 <= len(user_ids) <= 20:
        raise ValueError("每批需要 1 到 20 个群成员")
    if any(not isinstance(user_id, str) or not user_id for user_id in user_ids):
        raise ValueError("群成员标识必须是非空字符串")
    if len(set(user_ids)) != len(user_ids):
        raise ValueError("群成员标识不能重复")
