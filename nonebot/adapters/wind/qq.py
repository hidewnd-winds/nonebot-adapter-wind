"""QQ 官方协议的统一实现与项目事件扩展。"""

from __future__ import annotations

from collections.abc import Sequence
import asyncio
import re
from datetime import datetime
from dataclasses import dataclass
from time import monotonic
from html import escape
import inspect
from typing import Any, Literal, cast
from urllib.parse import quote, urlparse

from nonebot import get_adapters, get_plugin_config
from nonebot.compat import type_validate_python
from nonebot.exception import MatcherException
from nonebot.adapters import Bot, Event
from nonebot.adapters.qq import Adapter as QQAdapter, Bot as QQBot
from nonebot.adapters.qq import Message as QQMessage
from nonebot.adapters.qq import MessageSegment as QQMessageSegment
from nonebot.adapters.qq.exception import ActionFailed, ApiNotAvailable
from nonebot.adapters.qq.event import (
    C2CMessageCreateEvent,
    EventType,
    GroupAtMessageCreateEvent,
    GroupAddRobotEvent,
    GroupMemberAddEvent,
    GroupMemberRemoveEvent,
    GroupMessageCreateEvent,
    NoticeEvent,
)
from nonebot.adapters.qq.models import (
    Action,
    Button,
    InlineKeyboard,
    InlineKeyboardRow,
    MessageKeyboard,
    MessageMarkdown,
    Modal,
    Permission,
    QQReplyMessage,
    RenderData,
    GroupMemberInfo,
    SetMemberMuteState,
)
from nonebot.drivers import Driver, Request, Response
from nonebot.matcher import Matcher
from pydantic import BaseModel, Field
from typing_extensions import override

from .log import log
from .media import ImagePublisher, get_png_dimensions, read_image_dimensions, resolve_image_url
from .config import Config
from .inbound import register_command_preprocessor
from nonebot.adapters.qq.models import Dispatch

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
    image as markdown_image,
    render_markdown,
    render_plain_text,
)
from .inbound import collapse_command_spaces
from .models import (
    GroupBlacklistPage,
    GroupBlacklistedMember,
    GroupBotState,
    GroupJoinRequest,
    GroupJoinRequestPage,
    GroupMemberMute,
    GroupMemberRemovalResult,
    GroupMutedMember,
    GroupMuteRecurringRule,
    GroupMuteRule,
    GroupMuteSchedule,
    GroupMuteSettings,
    GroupInfo,
    GroupMessage,
    GroupMember,
    GroupMemberChange,
    ImageContent,
    InboundImage,
    InvalidMessageContentError,
    InvalidMessageContextError,
    MessageGroup,
    MessageReceipt,
    MessageSender,
    MessageSendError,
    OutboundContent,
    OrderedContent,
    PrivateMessage,
    ProtocolAdapterError,
    ReferencedMessage,
    RichContent,
    UnifiedMessage,
    UnsupportedProtocolCapabilityError,
)

_ACTION_TYPES = {"link": 0, "callback": 1, "command": 2}
_PERMISSION_TYPES = {"specified": 0, "manager": 1, "all": 2}


def _group_role(
    value: object,
) -> Literal["owner", "admin", "member", "unknown"]:
    """把 QQ 官方群角色字段收窄为统一角色。"""

    if value == "owner":
        return "owner"
    if value == "admin":
        return "admin"
    if value == "member":
        return "member"
    return "unknown"


def _message_id(response: object) -> str | None:
    """从 QQ SDK 返回模型或字典中提取消息标识。"""

    if isinstance(response, dict):
        value = response.get("message_id") or response.get("id")
    else:
        value = getattr(response, "message_id", None) or getattr(response, "id", None)
    return str(value) if isinstance(value, (str, int)) else None


def _group_reply_expired(event: GroupMessageCreateEvent) -> bool:
    """按原始消息时间判断两分钟回复期限，避免排队或重投递延长凭据寿命。"""

    created_at = datetime.fromisoformat(event.timestamp)
    return (datetime.now(created_at.tzinfo) - created_at).total_seconds() > 120


async def _log_send_failure(error: Exception, action: str) -> str | None:
    """记录 QQ 发送失败，并返回平台响应中的错误码说明。"""

    if not isinstance(error, ActionFailed):
        log("ERROR", f"{action}: {error}", error)
        return None

    code = error.code if error.code is not None else error.status_code
    description = error.message or "平台未返回错误描述"
    log("ERROR", f"{action} code={code} message={description} trace_id={error.trace_id}: {error}", error)
    return f"QQ 消息发送失败（错误码 {code}）：{description}"


def _build_keyboard(table: ButtonTable) -> MessageKeyboard:
    """把通用按钮表映射为 QQ 官方键盘。"""

    rows: list[InlineKeyboardRow] = []
    for row in table.rows:
        buttons: list[Button] = []
        for spec in row.buttons:
            buttons.append(
                Button(
                    group_id=spec.group_id,
                    render_data=RenderData(
                        label=spec.label,
                        visited_label=spec.visited_label,
                        style=spec.style,
                    ),
                    action=Action(
                        type=_ACTION_TYPES[spec.action],
                        permission=Permission(
                            type=_PERMISSION_TYPES[spec.permission],
                            specify_user_ids=list(spec.specified_user_ids) or None,
                        ),
                        data=spec.data,
                        enter=spec.enter,
                        reply=spec.reply,
                        modal=Modal(
                            content=spec.modal.content,
                            confirm_text=spec.modal.confirm_text,
                            cancel_text=spec.modal.cancel_text,
                        ) if spec.modal is not None else None,
                    ),
                )
            )
        rows.append(InlineKeyboardRow(buttons=buttons))
    return MessageKeyboard(content=InlineKeyboard(rows=rows))


def _image_file_name(file_name: str) -> str:
    """为 QQ 图片文件名添加时间前缀，避免短期同名缓存。"""

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"{timestamp}-{file_name}"


def _render_image(content: ImageContent) -> QQMessageSegment:
    """按图片来源生成 QQ 远程图片或本地附件消息段。"""

    if isinstance(content.data, str):
        return QQMessageSegment.image(content.data)
    return QQMessageSegment.file_image(
        content.data,
        file_name=_image_file_name(content.file_name),
    )


async def _render_document(content: Document, publisher: ImagePublisher | None = None) -> QQMessage:
    """把结构化文档转换为 QQ Markdown 与可选键盘。"""

    resolved_content = Document(
        [await _resolve_markdown_node(part, publisher) for part in content.parts]
    )
    rendered = render_markdown(resolved_content)
    message = QQMessage(
        QQMessageSegment.markdown(MessageMarkdown(content=rendered.text))
    )
    if rendered.button_table is not None:
        message += QQMessageSegment.keyboard(
            _build_keyboard(rendered.button_table)
        )
    return message


async def _resolve_markdown_node(node: Inline | Block, publisher: ImagePublisher | None = None) -> Inline | Block:
    """递归发布 Markdown 中的本地图像，并保持文档结构不变。"""

    if isinstance(node, Inline):
        return await _resolve_markdown_inline(node, publisher)
    if isinstance(node, Heading):
        return Heading(node.level, await _resolve_markdown_inlines(node.children, publisher))
    if isinstance(node, Paragraph):
        return Paragraph(await _resolve_markdown_inlines(node.children, publisher))
    if isinstance(node, Quote):
        return Quote(await _resolve_markdown_inlines(node.children, publisher))
    if isinstance(node, ListBlock):
        return await _resolve_markdown_list(node, publisher)
    if isinstance(node, Table):
        headers = tuple(
            [await _resolve_markdown_inlines(cell, publisher) for cell in node.headers]
        )
        # Python 3.10 不支持此处嵌套的异步推导式；显式逐行处理保留发布顺序。
        rows: list[tuple[tuple[Inline, ...], ...]] = []
        for row in node.rows:
            rows.append(tuple(
                [await _resolve_markdown_inlines(cell, publisher) for cell in row]
            ))
        return Table(headers=headers, rows=tuple(rows))
    if isinstance(node, (Divider, CodeBlock, ButtonTable)):
        return node
    raise TypeError(f"unsupported document node: {type(node).__name__}")


async def _resolve_markdown_inline(node: Inline, publisher: ImagePublisher | None = None) -> Inline:
    if isinstance(node, Image):
        return Image(
            alt=node.alt,
            url=await resolve_image_url(node.url, publisher),
            width=node.width,
            height=node.height,
        )
    if isinstance(node, StyledText):
        return StyledText(
            node.style,
            await _resolve_markdown_inlines(node.children, publisher),
        )
    if isinstance(node, Link):
        return Link(
            await _resolve_markdown_inlines(node.label, publisher),
            node.url,
            node.show_url_in_plain,
        )
    if isinstance(node, Mention):
        # QQ 官方文本交互使用新的 @ 标签；仅在 QQ 边界转换，保留 OneBot 原生提及。
        return Text(f'<qqbot-at-user id="{escape(node.user_id, quote=True)}" />')
    if isinstance(node, (Text, InlineCode)):
        return node
    raise TypeError(f"unsupported inline node: {type(node).__name__}")


async def _resolve_markdown_inlines(
    nodes: tuple[Inline, ...], publisher: ImagePublisher | None = None,
) -> tuple[Inline, ...]:
    return tuple([await _resolve_markdown_inline(node, publisher) for node in nodes])


async def _resolve_markdown_list(block: ListBlock, publisher: ImagePublisher | None = None) -> ListBlock:
    # 与表格一致，按原顺序等待每项及子列表，兼容 Python 3.10。
    items: list[ListItem] = []
    for item in block.items:
        children = await _resolve_markdown_inlines(item.children, publisher)
        nested = tuple(
            [await _resolve_markdown_list(child, publisher) for child in item.nested]
        )
        items.append(ListItem(children=children, nested=nested))
    return ListBlock(ordered=block.ordered, items=tuple(items))


async def _render_content(content: OutboundContent, publisher: ImagePublisher | None = None) -> tuple[QQMessage, ...]:
    """把统一内容转换为一个或多个 QQ 官方消息。"""

    if isinstance(content, OrderedContent):
        # QQ 每条媒体消息只支持一张图且没有片段位置，必须按顺序拆发。
        messages: list[QQMessage] = []
        pending_text = ""
        for part in content.parts:
            if isinstance(part, str):
                pending_text += part
                continue
            if pending_text:
                messages.append(QQMessage(QQMessageSegment.text(pending_text)))
                pending_text = ""
            messages.append(QQMessage(_render_image(part)))
        if pending_text:
            messages.append(QQMessage(QQMessageSegment.text(pending_text)))
        return tuple(messages)
    if isinstance(content, str):
        return (QQMessage(QQMessageSegment.text(content)),)
    if isinstance(content, Document):
        return (await _render_document(content, publisher),)
    if isinstance(content, ImageContent):
        return (QQMessage(_render_image(content)),)
    document = (
        Document(list(content.document.parts))
        if content.document is not None
        else None
    )
    attachments: list[ImageContent] = []
    leading_markdown_images: list[Paragraph] = []
    has_markdown_image = False
    for image in content.images:
        if isinstance(image.data, str):
            image_url = image.data
            dimensions = await get_png_dimensions(image_url)
        else:
            image_url = (await publisher.publish_image(image.data, image.file_name) if publisher is not None else None)
            if publisher is not None and (
                not isinstance(image_url, str)
                or urlparse(image_url).scheme not in {"http", "https"}
                or not urlparse(image_url).netloc
            ):
                raise InvalidMessageContentError("图片发布器必须返回有效的 HTTP(S) URL")
            dimensions = read_image_dimensions(image.data)
        if image_url is None:
            if content.single_message:
                raise InvalidMessageContentError("QQ 图文图片发布失败，请检查图片发布服务")
            attachments.append(image)
            continue
        if dimensions is None:
            raise InvalidMessageContentError(
                "QQ Markdown image dimensions lookup failed"
            )
        width, height = dimensions
        scale = min(1, 960 / width)
        if document is None:
            document = Document()
        rendered_image = markdown_image(
            image.alt_text,
            image_url,
            width=round(width * scale),
            height=round(height * scale),
        )
        if content.images_first:
            leading_markdown_images.append(Paragraph((rendered_image,)))
        else:
            document.append(rendered_image)
        has_markdown_image = True

    if document is not None and leading_markdown_images:
        document.parts[:0] = leading_markdown_images

    footer = content.footer
    if document is not None and not attachments and footer is not None:
        document.parts.extend(footer.parts)
        footer = None

    messages: list[QQMessage] = []
    has_buttons = (
        document is not None
        and render_markdown(document).button_table is not None
    )
    if document is not None and attachments and not has_markdown_image and not has_buttons:
        # QQ 本地图片走媒体上传；正文与首张图片合成一条媒体消息，避免图文拆发。
        first_image = _render_image(attachments.pop(0))
        text_segment = QQMessageSegment.text(render_plain_text(document).text)
        combined = QQMessage(first_image if content.images_first else text_segment)
        combined += text_segment if content.images_first else first_image
        # 无按钮的末尾说明可与单张原生媒体合并；其他情况在全部图片后独立发送。
        if not attachments and footer is not None and render_markdown(footer).button_table is None:
            combined += QQMessageSegment.text(render_plain_text(footer).text)
            footer = None
        messages.append(combined)
        document = None
    if document is not None:
        messages.append(await _render_document(document, publisher))
    messages.extend(QQMessage(_render_image(image)) for image in attachments)
    if footer is not None:
        messages.append(await _render_document(footer, publisher))
    if content.single_message and len(messages) != 1:
        # 在任何消息发出之前检查，避免多图发布失败后拆发出部分攻略。
        raise InvalidMessageContentError("QQ 图文无法合并为单条消息，请检查图片发布服务")
    return tuple(messages)


def _extract_images_from_attachments(attachments: Sequence[object]) -> tuple[InboundImage, ...]:
    """把 QQ 附件中的图片转换为统一模型。"""

    images: list[InboundImage] = []
    for attachment in attachments:
        content_type = str(getattr(attachment, "content_type", "") or "")
        url = getattr(attachment, "url", None)
        if not url or not content_type.lower().startswith("image/"):
            continue
        size = getattr(attachment, "size", None)
        images.append(
            InboundImage(
                url=str(url),
                content_type=content_type,
                filename=getattr(attachment, "filename", None),
                size=size if isinstance(size, int) and not isinstance(size, bool) else None,
            )
        )
    return tuple(images)


def _extract_inbound_images(event: Event) -> tuple[InboundImage, ...]:
    """从 QQ 原始附件提取图片元数据，消息段仅作兼容回退。"""

    images = _extract_images_from_attachments(
        getattr(event, "attachments", None) or ()
    )
    if images:
        return images

    fallback: list[InboundImage] = []
    for segment in event.get_message():
        seg_type = getattr(segment, "type", "")
        if seg_type != "image":
            continue
        data = getattr(segment, "data", {})
        url = data.get("url")
        if not url:
            continue
        fallback.append(InboundImage(url=str(url)))
    return tuple(fallback)


def _extract_inbound_mentions(
    event: Event,
    excluded_user_id: str | None = None,
) -> tuple[str, ...]:
    """从 QQ 官方 mention_user 消息段提取真实用户 OpenID。"""

    user_ids: list[str] = []
    for segment in event.get_message():
        if getattr(segment, "type", "") != "mention_user":
            continue
        data = getattr(segment, "data", {})
        user_id = data.get("user_id")
        if (
            user_id
            and str(user_id) != excluded_user_id
            and str(user_id) not in user_ids
        ):
            user_ids.append(str(user_id))
    return tuple(user_ids)


async def initialize_qq_webhook_bots() -> list[Bot]:
    """显式初始化所有已注册 Wind QQ 实例，不触碰官方适配器。"""
    ready: list[Bot] = []
    for adapter in get_adapters().values():
        if isinstance(adapter, ProjectQQAdapter):
            ready.extend(await adapter.initialize_webhook_bots())
    return ready


def _convert_reference(element: QQReplyMessage) -> ReferencedMessage:
    """把 QQ 内联引用投影为可归档的内容与作者，不携带原始事件或额外身份字段。"""
    author = element.author
    return ReferencedMessage(
        reference_id=element.msg_idx,
        text=element.content,
        images=_extract_images_from_attachments(element.attachments or ()),
        sender_id=(author.member_openid or author.user_openid or author.id) if author else None,
        sender_name=author.username if author else None,
    )


def _prepare_qq_command_message(event: Event, config: Config) -> None:
    """统一 QQ 命令视图，保留 content 与 original_message 作为原始消息。"""
    if not isinstance(event, (GroupMessageCreateEvent, GroupAtMessageCreateEvent, C2CMessageCreateEvent)):
        return
    if config.wind_collapse_command_spaces:
        collapse_command_spaces(event)
    if not config.wind_qq_strip_command_slash:
        return
    message = event.get_message()
    if not message or message[0].type != "text":
        return
    text = message[0].data.get("text")
    if not isinstance(text, str) or re.match(r"^/[^/\s]", text) is None:
        return
    # 只去掉命令开头的一个斜杠，不改参数中的路径/URL，也不改原消息段。
    event.message = message.copy()
    event.message[0] = QQMessageSegment.text(text[1:])


async def prepare_qq_command_message(bot: Bot, event: Event) -> None:
    """在 NoneBot 命令树和原生 fullmatch/regex 匹配前处理面板前缀。"""
    if isinstance(bot.adapter, ProjectQQAdapter):
        _prepare_qq_command_message(event, bot.adapter.wind_config)


class QQProtocolAdapter:
    """把 QQ 官方事件和 API 转换为项目统一协议能力。"""

    protocol: Literal["qq"] = "qq"

    def supports_event(self, event: Event) -> bool:
        """判断事件是否为 QQ 群聊、群 @ 或 C2C 消息。"""

        return isinstance(
            event,
            (
                GroupAtMessageCreateEvent,
                GroupMessageCreateEvent,
                C2CMessageCreateEvent,
            ),
        )

    def get_group_member_change(self, bot: Bot, event: Event) -> GroupMemberChange | None:
        # QQ 自身进退群由 GroupAddRobot/GroupDelRobot 事件处理，不混用两类身份。
        if not isinstance(event, (GroupMemberAddEvent, GroupMemberRemoveEvent)):
            return None
        return GroupMemberChange(
            protocol=self.protocol, group_id=event.group_openid, user_id=event.member_openid,
            kind="join" if isinstance(event, GroupMemberAddEvent) else "leave",
            timestamp=event.timestamp, event_id=event.event_id,
        )

    def create_message(
        self,
        bot: Bot,
        event: Event,
        matcher: Matcher | None,
    ) -> UnifiedMessage:
        """将 QQ 官方消息事件转换为统一消息。"""

        # 其他预处理器也会读取统一消息，不依赖并发预处理器的执行顺序。
        if isinstance(bot.adapter, ProjectQQAdapter):
            _prepare_qq_command_message(event, bot.adapter.wind_config)
        message_index = None
        reference_id = None
        references: tuple[ReferencedMessage, ...] = ()
        if isinstance(event, (GroupMessageCreateEvent, C2CMessageCreateEvent)):
            message_index = event.msg_idx
            if event.message_scene is not None:
                for item in event.message_scene.ext:
                    key, _, value = item.partition("=")
                    if key == "msg_idx" and message_index is None:
                        message_index = value
                    elif key == "ref_msg_idx":
                        reference_id = value
            # 归档直接保留 SDK 已建模的内联元素，不能依赖 reply 是否匹配成功。
            references = tuple(_convert_reference(item) for item in event.msg_elements or ())
        if isinstance(event, (GroupAtMessageCreateEvent, GroupMessageCreateEvent)):
            # 标题命令携带 @ 时，纯文本可能残留分隔空白；统一入口处理，确保规则与 handler 一致。
            text = (event.get_message().extract_plain_text() or event.content).strip()
            return GroupMessage(
                protocol=self.protocol,
                transport="webhook",
                message_id=event.id,
                text=text,
                raw_text=event.content,
                original_plaintext=event.original_message.extract_plain_text(),
                message_index=message_index,
                reference_id=reference_id,
                references=references,
                is_to_me=event.to_me,
                sender=MessageSender(
                    id=event.author.member_openid,
                    name=event.author.username,
                    avatar_url=f"https://q.qlogo.cn/qqapp/{bot.self_id}/{quote(event.author.member_openid, safe='')}/640",
                    role=_group_role(
                        getattr(event.author, "member_role", None)
                    ),
                ),
                group=MessageGroup(id=event.group_openid, name=None),
                mentions_everyone=(
                    any(segment.type == "mention_everyone" for segment in event.get_message())
                    or re.search(r"<qqbot-at-everyone\s*/>", event.content) is not None
                ),
                images=_extract_inbound_images(event),
                content_parts=(re.sub(rf"^(\s*)<@!?{re.escape(str(bot.self_id))}>", r"\1", event.content), *_extract_inbound_images(event)),
                mentioned_user_ids=_extract_inbound_mentions(
                    event,
                    str(bot_id) if (bot_id := getattr(bot, "self_id", None)) else None,
                ),
                _bot=bot,
                _event=event,
                _matcher=matcher,
            )
        if isinstance(event, C2CMessageCreateEvent):
            text = event.get_message().extract_plain_text() or event.content
            return PrivateMessage(
                protocol=self.protocol,
                transport="webhook",
                message_id=event.id,
                text=text,
                raw_text=event.content,
                original_plaintext=QQMessage(event.content).extract_plain_text(),
                message_index=message_index,
                reference_id=reference_id,
                references=references,
                is_to_me=event.to_me,
                sender=MessageSender(
                    id=event.author.user_openid,
                    name=event.author.username,
                    avatar_url=f"https://q.qlogo.cn/qqapp/{bot.self_id}/{quote(event.author.user_openid, safe='')}/640",
                ),
                images=_extract_inbound_images(event),
                content_parts=(event.content, *_extract_inbound_images(event)),
                mentioned_user_ids=_extract_inbound_mentions(
                    event,
                    str(bot_id) if (bot_id := getattr(bot, "self_id", None)) else None,
                ),
                _bot=bot,
                _event=event,
                _matcher=matcher,
            )
        raise InvalidMessageContextError(
            f"unsupported QQ event: {type(event).__name__}"
        )

    def clone_event(
        self,
        message: UnifiedMessage,
        text: str,
    ) -> Event:
        """克隆 QQ 消息事件，仅替换命令内容并保留会话身份。"""

        event = message._event
        if not isinstance(
            event,
            (
                GroupAtMessageCreateEvent,
                GroupMessageCreateEvent,
                C2CMessageCreateEvent,
            ),
        ):
            raise InvalidMessageContextError(
                f"unsupported QQ event clone: {type(event).__name__}"
            )
        cloned = event.model_copy(update={"content": escape(text, quote=False), "to_me": True})
        # 模型生成的命令始终作为纯文本；真实 @ 只能来自原消息，不能从生成标签反解析。
        cloned.message = QQMessage(QQMessageSegment.text(text))
        for segment in event.get_message():
            if segment.type == "mention_user" and segment.data.get("user_id") in message.mentioned_user_ids:
                cloned.message += segment
        return cloned

    async def get_referenced_message(
        self,
        message: UnifiedMessage,
    ) -> ReferencedMessage | None:
        """读取 QQ SDK 已解析并内联到事件中的引用消息。"""

        event = message._event
        if not isinstance(
            event,
            (
                GroupAtMessageCreateEvent,
                GroupMessageCreateEvent,
                C2CMessageCreateEvent,
            ),
        ):
            raise InvalidMessageContextError(
                f"unsupported QQ reference context: {type(event).__name__}"
            )
        if event.reply is None:
            return None
        return _convert_reference(event.reply)

    async def send(
        self,
        message: UnifiedMessage,
        contents: Sequence[OutboundContent],
        *, reply_to_source: bool = False, allow_fallback: bool = True,
    ) -> list[MessageReceipt]:
        """按业务顺序回复 QQ 消息或原生交互事件。"""

        receipts: list[MessageReceipt] = []
        if isinstance(message._event, ProjectQQInteractionCreateEvent):
            # 回调使用event_id响应，不能交给SDK普通消息send；仍由公共入口统一观察回执和归档。
            for content in contents:
                receipts.extend(await send_qq_interaction_response(message._bot, message._event, content))
            return receipts
        proactive_group_id: str | None = None
        try:
            for content in contents:
                for rendered_message in await _render_content(content, _image_publisher(message._bot)):
                    if reply_to_source:
                        if message.message_index:
                            rendered_message = QQMessageSegment.reference(message.message_index) + rendered_message
                        else:
                            log("WARNING", "引用警告缺少 QQ 引用索引，仅发送正文")
                    try:
                        if allow_fallback and isinstance(message._event, GroupMessageCreateEvent) and _group_reply_expired(message._event):
                            # 直接群发送默认 msg_id=None；不能改写归档仍需使用的 event.id。
                            proactive_group_id = message._event.group_openid
                        if proactive_group_id is None:
                            response = await message._bot.send(message._event, rendered_message)
                        else:
                            response = await _call_capability(
                                message._bot, "send_to_group",
                                group_openid=proactive_group_id, message=rendered_message,
                            )
                    except ActionFailed as error:
                        if (
                            reply_to_source or not allow_fallback or error.code not in (40034005, 40034031)
                            or proactive_group_id is not None
                            or not isinstance(message._event, GroupMessageCreateEvent)
                        ):
                            raise
                        # SDK send 会自动带回 event.id；过期后本批剩余内容改走主动群发送。
                        proactive_group_id = message._event.group_openid
                        log("WARNING", f"QQ 回复 msg_id 已过期，改为主动群消息重试：code={error.code}, trace_id={error.trace_id}")
                        response = await _call_capability(
                            message._bot, "send_to_group",
                            group_openid=proactive_group_id, message=rendered_message,
                        )
                    receipts.append(MessageReceipt(_message_id(response)))
        except MatcherException:
            raise
        except Exception as exc:
            if reply_to_source or not allow_fallback:
                raise MessageSendError("QQ 引用警告发送失败") from exc
            error_notice = await _log_send_failure(exc, "QQ 消息发送失败")
            if error_notice is not None:
                try:
                    if isinstance(message._event, GroupMessageCreateEvent) and _group_reply_expired(message._event):
                        proactive_group_id = message._event.group_openid
                    if proactive_group_id is None:
                        await message._bot.send(message._event, QQMessage(error_notice))
                    else:
                        await _call_capability(
                            message._bot, "send_to_group",
                            group_openid=proactive_group_id, message=QQMessage(error_notice),
                        )
                except MatcherException:
                    raise
                except Exception as resend_error:
                    log("ERROR", f"QQ 发送失败说明补发失败: {resend_error}", resend_error)
            raise MessageSendError("QQ message send failed") from exc
        return receipts

    async def send_to_group(
        self,
        message: UnifiedMessage,
        group_id: str,
        contents: Sequence[OutboundContent],
    ) -> list[MessageReceipt]:
        """向指定 QQ 群发送消息，同群事件自动按被动回复处理。"""

        receipts: list[MessageReceipt] = []
        reply_event = (
            message._event
            if isinstance(message, GroupMessage)
            and message.group.id == group_id
            and isinstance(message._event, GroupMessageCreateEvent)
            else None
        )
        reply_kwargs: dict[str, object] = {}
        try:
            for content in contents:
                for rendered_message in await _render_content(content, _image_publisher(message._bot)):
                    reply_kwargs = {}
                    if reply_event is not None and _group_reply_expired(reply_event):
                        reply_event = None
                    if reply_event is not None:
                        reply_event._reply_seq += 1
                        reply_kwargs = {
                            "msg_id": reply_event.id,
                            "msg_seq": reply_event._reply_seq,
                        }
                    try:
                        response = await _call_capability(
                            message._bot,
                            "send_to_group",
                            group_openid=group_id,
                            message=rendered_message,
                            **reply_kwargs,
                        )
                    except ActionFailed as error:
                        if error.code not in (40034005, 40034031) or reply_event is None:
                            raise
                        # 仅重试当前失败内容；后续消息和失败说明均不能复用过期凭据。
                        reply_event = None
                        reply_kwargs = {}
                        log("WARNING", f"QQ 回复 msg_id 已过期，改为主动群消息重试：code={error.code}, trace_id={error.trace_id}")
                        response = await _call_capability(
                            message._bot, "send_to_group",
                            group_openid=group_id, message=rendered_message,
                        )
                    receipts.append(MessageReceipt(_message_id(response)))
        except MatcherException:
            raise
        except Exception as exc:
            error_notice = await _log_send_failure(exc, "QQ 群消息发送失败")
            if error_notice is not None:
                try:
                    reply_kwargs = {}
                    if reply_event is not None and _group_reply_expired(reply_event):
                        reply_event = None
                    if reply_event is not None:
                        reply_event._reply_seq += 1
                        reply_kwargs = {
                            "msg_id": reply_event.id,
                            "msg_seq": reply_event._reply_seq,
                        }
                    await _call_capability(
                        message._bot,
                        "send_to_group",
                        group_openid=group_id,
                        message=QQMessage(error_notice),
                        **reply_kwargs,
                    )
                except MatcherException:
                    raise
                except Exception as resend_error:
                    log("ERROR", f"QQ 群消息发送失败说明补发失败: {resend_error}", resend_error)
            raise MessageSendError("QQ group message send failed") from exc
        return receipts

    async def send_proactive(
        self, bot: Bot, target_id: str, contents: Sequence[OutboundContent], *, private: bool,
    ) -> list[MessageReceipt]:
        """主动消息不携带 msg_id、event_id 或旧会话序号。"""
        receipts: list[MessageReceipt] = []
        try:
            for content in contents:
                for rendered in await _render_content(content, _image_publisher(bot)):
                    response = await _call_capability(
                        bot, "send_to_c2c" if private else "send_to_group",
                        **{"openid" if private else "group_openid": target_id},
                        message=rendered,
                    )
                    receipts.append(MessageReceipt(_message_id(response)))
        except MatcherException:
            raise
        except Exception as exc:
            await _log_send_failure(exc, "QQ 主动消息发送失败")
            raise MessageSendError("QQ proactive message send failed") from exc
        return receipts

    async def get_group_info(
        self,
        message: GroupMessage,
        group_id: str,
    ) -> GroupInfo | None:
        """通过 QQ 官方 V2 接口查询并转换群资料。"""

        try:
            result = await cast(QQBot, message._bot).get_group_info(group_id=group_id)
            return GroupInfo(
                id=result.group_openid,
                name=result.group_name,
                member_count=result.group_member_num,
                max_member_count=None,
            )
        except UnsupportedProtocolCapabilityError:
            raise
        except Exception as exc:
            raise ProtocolAdapterError(
                "QQ group info lookup failed"
            ) from exc

    async def get_groups(
        self,
        message: UnifiedMessage,
    ) -> list[GroupInfo]:
        """QQ 官方协议当前没有列出 Bot 所在群的开放能力。"""

        raise UnsupportedProtocolCapabilityError(
            "QQ bot does not support group list lookup"
        )

    async def get_group_member(
        self,
        message: GroupMessage | Bot,
        group_id: str,
        user_id: str,
        *, fresh: bool = False,
    ) -> GroupMember | None:
        """查询并转换 QQ 群成员资料。"""

        if (
            not fresh and not isinstance(message, Bot)
            and message.group.id == group_id and message.sender.id == user_id
            and not isinstance(message._event, ProjectQQInteractionCreateEvent)
        ):
            # QQ 群消息事件已携带当前发送者昵称和角色，无需再扫描成员列表。
            return GroupMember(
                id=message.sender.id,
                nickname=message.sender.name,
                card=None,
                role=message.sender.role,
            )
        # 按钮回调不含成员角色，必须查询平台成员信息，不能把缺失角色当成权限依据。
        try:
            bot = message if isinstance(message, Bot) else message._bot
            result = await cast(QQBot, bot).get_group_member(
                group_openid=group_id, member_openid=user_id,
            )
            return _group_member(result)
        except Exception as exc:
            raise ProtocolAdapterError("QQ group member lookup failed") from exc

    async def get_group_members(
        self,
        message: GroupMessage,
        group_id: str,
    ) -> list[GroupMember]:
        """查询并转换 QQ 群成员列表。"""

        members: list[GroupMember] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        try:
            while True:
                result = await cast(QQBot, message._bot).get_group_members(
                    group_openid=group_id, cursor=cursor,
                )
                members.extend(_group_member(value) for value in result.members)
                if not result.next_cursor:
                    return members
                if result.next_cursor in seen_cursors:
                    raise ProtocolAdapterError("QQ 群成员分页游标重复")
                cursor = result.next_cursor
                seen_cursors.add(cursor)
        except UnsupportedProtocolCapabilityError:
            raise
        except Exception as exc:
            raise ProtocolAdapterError(
                "QQ group members lookup failed"
            ) from exc


    async def recall_group_message(self, message: GroupMessage) -> None:
        # 治理必须向上抛出超时等错误，不能沿用菜单撤回的容错语义。
        if message.message_id is None:
            raise InvalidMessageContextError("撤回缺少消息 ID")
        await cast(QQBot, message._bot).delete_group_message(
            group_openid=message.group.id, message_id=message.message_id,
        )

    async def get_group_bot_state(self, bot: Bot, group_id: str) -> GroupBotState:
        state = await get_qq_group_bot_state(cast(QQBot, bot), group_id)
        return GroupBotState(
            role=_group_role(state.member_role), allow_proactive_msg=state.allow_proactive_msg,
            recv_msg_setting=state.recv_msg_setting,
        )

    async def get_group_mute_settings(self, bot: Bot, group_id: str) -> GroupMuteSettings:
        result = await cast(QQBot, bot).get_group_mute_setting(group_id=group_id)
        rule = result.global_rule
        return GroupMuteSettings(
            global_rule=GroupMuteRule(
                mode=rule.mode,
                schedule_rules=tuple(GroupMuteSchedule(
                    item.task_id, item.start_at, item.end_at, item.enabled,
                ) for item in rule.schedule_rules),
                recurring_rules=tuple(GroupMuteRecurringRule(
                    item.task_id, tuple(item.weekdays), item.start_time, item.end_time, item.enabled,
                ) for item in rule.recurring_rules),
            ),
            members=tuple(GroupMutedMember(
                item.member_openid, item.mute_expire_at, item.username, item.union_openid,
            ) for item in result.members),
        )

    async def set_group_members_mute(
        self, bot: Bot, group_id: str, members: Sequence[GroupMemberMute],
    ) -> None:
        await cast(QQBot, bot).set_group_members_mute(
            group_id=group_id,
            members=[SetMemberMuteState(
                member_openid=item.user_id, op=item.op,
                mute_expire_at=item.expires_at if item.op != "del" else None,
            ) for item in members],
        )

    async def get_group_join_requests(
        self, bot: Bot, group_id: str, *, cursor: str | None, limit: int | None,
    ) -> GroupJoinRequestPage:
        result = await cast(QQBot, bot).get_group_join_request_list(
            group_id=group_id, cursor=cursor, limit=limit,
        )
        requests: list[GroupJoinRequest] = []
        for item in result.list:
            verify = item.verify_info
            requests.append(GroupJoinRequest(
                request_id=item.join_request_id, user_id=item.member_openid,
                nickname=item.username, applied_at=item.apply_at, source=item.apply_source,
                invited_by=item.invited_by, is_bot=item.bot, risk_tips=item.risk_tips,
                union_id=item.union_openid,
                verify_method=verify.method if verify else None,
                verify_message=verify.verify_message if verify else None,
                review_answers=tuple((qa.question, qa.answer) for qa in (verify.review_qa_list or ())) if verify else (),
            ))
        return GroupJoinRequestPage(tuple(requests), result.next_cursor)

    async def approve_group_join_request(
        self, bot: Bot, group_id: str, request: GroupJoinRequest, *, approve: bool,
        reason: str | None, add_to_blacklist: bool,
    ) -> None:
        await cast(QQBot, bot).approval_join_request(
            group_id=group_id, member_openid=request.user_id, join_request_id=request.request_id,
            op="approve" if approve else "decline", reject_reason=reason,
            add_to_member_blacklist=add_to_blacklist,
        )

    async def remove_group_members(
        self, bot: Bot, group_id: str, user_ids: Sequence[str], *, add_to_blacklist: bool,
    ) -> GroupMemberRemovalResult:
        result = await cast(QQBot, bot).batch_remove_group_members(
            group_openid=group_id, member_openids=list(user_ids),
            add_to_member_blacklist=add_to_blacklist,
        )
        if result.remove_members_result != "success":
            raise ProtocolAdapterError("QQ 未确认群成员移除成功")
        return GroupMemberRemovalResult(True, tuple(result.add_to_member_blacklist_fail_openids))

    async def get_group_blacklist(
        self, bot: Bot, group_id: str, *, cursor: str | None, limit: int | None,
    ) -> GroupBlacklistPage:
        result = await cast(QQBot, bot).get_group_member_blacklist(
            group_openid=group_id, cursor=cursor, limit=limit,
        )
        return GroupBlacklistPage(
            tuple(GroupBlacklistedMember(
                item.member_openid, item.username, item.bot, item.banned_at, item.union_openid,
            ) for item in result.users), result.next_cursor,
        )

    async def set_group_blacklist(
        self, bot: Bot, group_id: str, user_ids: Sequence[str], *, add: bool,
    ) -> tuple[str, ...]:
        result = await cast(QQBot, bot).post_group_member_blacklist(
            group_openid=group_id, op="add" if add else "del", member_openids=list(user_ids),
        )
        return tuple(result.fail_openids)


def _group_member(value: GroupMemberInfo) -> GroupMember:
    """只投影 SDK 已校验的字段，缺失角色保持未知。"""
    return GroupMember(
        id=value.member_openid, nickname=value.username, card=None,
        role=_group_role(value.member_role), is_bot=value.bot,
        joined_at=value.joined_at, union_id=value.union_openid,
    )


async def _call_capability(
    bot: Bot,
    method_name: str,
    *args: object,
    **kwargs: object,
) -> object:
    """调用 QQ 动态 API，并显式识别能力缺失。"""

    method = getattr(bot, method_name, None)
    if not callable(method):
        raise UnsupportedProtocolCapabilityError(
            f"QQ bot does not support {method_name}"
        )
    result = method(*args, **kwargs)
    if not inspect.isawaitable(result):
        raise UnsupportedProtocolCapabilityError(
            f"QQ capability is not async: {method_name}"
        )
    return await result


@dataclass(frozen=True)
class QQGroupStateFailure:
    """群状态查询的处置建议；接口不可用不等同于已确认不是管理员。"""

    action: Literal["retry", "skip", "stop", "error"]
    reason: str
    code: int | None = None
    is_admin: bool | None = None


def get_qq_group_state_failure(error: Exception) -> QQGroupStateFailure:
    """仅用于只读 bot_state 查询，不把重试策略套用到发消息或入群审批。

    官方公共错误码：https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html
    11253 另见 autogen/api/v2_groups_group_openid_bot_state.get.html；
    11293（新版 40011026）、11255（新版 40011028）来自实际群状态响应，公共表尚未列出。
    """
    if isinstance(error, ApiNotAvailable):
        return QQGroupStateFailure("stop", "接口或 HTTP 方法不可用，请检查接口地址和 SDK")
    if not isinstance(error, ActionFailed):
        return QQGroupStateFailure("error", "群状态查询失败")
    # 日志优先保留新版 err_code；SDK 的 code 仍可提供公共表中的旧码。
    body = error.body or {}
    code = body.get("err_code")
    if code is None:
        code = error.code
    if type(code) is not int:
        code = None
    # SDK 已对 HTTP 401 刷新 Token 并重试，此处不能再叠加重试。
    if error.status_code == 401:
        return QQGroupStateFailure("stop", "刷新凭证后仍认证失败，请检查应用凭证", code)
    if error.status_code in (404, 405):
        return QQGroupStateFailure("stop", "接口或 HTTP 方法不可用，请检查接口地址和 SDK", code)
    if error.status_code == 429:
        return QQGroupStateFailure("stop", "接口频率受限，停止本轮扫描，等待后续调度", code)
    # 已识别的新码优先；新码未知时才采用同一响应里的已知旧码，不推测新旧数字映射。
    # 无效类型不能作为权限判断依据，也不能通过旧码掩盖格式错误。
    policy_codes = (code,)
    legacy_code = error.code
    if type(code) is int and type(legacy_code) is int and legacy_code != code:
        policy_codes = (code, legacy_code)
    for policy_code in policy_codes:
        match policy_code:
            case 11281 | 11252 | 11263 | 11242:
                return QQGroupStateFailure("retry", "平台鉴权检查暂时失败，最多重试一次", code)
            case 11293 | 40011026:
                return QQGroupStateFailure("skip", "机器人非群成员", code, False)
            case 11255 | 40011028:
                return QQGroupStateFailure("skip", "QQ 群资源不存在", code, False)
            case 11282:
                return QQGroupStateFailure("skip", "管理员权限未授予，请群管理员授权", code, False)
            case 11264 | 11274:
                return QQGroupStateFailure("skip", "群或用户未授予接口权限，请核对群标识并重新授权", code)
            case 11253:
                return QQGroupStateFailure("stop", "应用无 bot_state 接口权限，请联系平台申请白名单", code)
            case 11254 | 11265:
                return QQGroupStateFailure("stop", "应用接口或机器人已被封禁，请联系平台处理", code)
            case 10001 | 11251 | 11261 | 11275 | 11241 | 11243:
                return QQGroupStateFailure("stop", "账号、AppID 或访问凭证异常，请检查应用配置", code)
            case 11262 | 11273 | 11301 | 11302:
                return QQGroupStateFailure("stop", "鉴权方式或 HTTP 请求头无效，请检查接口配置", code)
    if error.status_code in (500, 504):
        return QQGroupStateFailure("stop", "平台服务暂时失败，停止本轮扫描，等待后续调度", code)
    # 未知码和其他接口专属码保留错误；不能仅凭 message 文本撤销权限或假装成功。
    return QQGroupStateFailure("error", error.message or "平台未返回错误描述", code)


class QQGroupBotState(BaseModel, frozen=True):
    """官方群内状态的角色和独立消息权限，缺失角色保留未知。

    SDK 1.7.3 的 GroupBotStateReturn 不接受实际返回的空 recv_msg_setting，
    且要求 member_role/member_openid/joined_at；此处保留已验证的最小兼容边界。
    """

    allow_proactive_msg: bool = Field(strict=True)
    member_role: Literal["member", "admin", "owner"] | None = None
    # 平台实际会返回空字符串；保留原值，由授权刷新入口跳过不明确的状态。
    recv_msg_setting: Literal["", "all", "only_mention", "mention_and_context"]


class QQGroupStateClient:
    """所有群状态调用共用每 Bot 的 30 QPM 配额。"""
    def __init__(self) -> None:
        self.slots: dict[str, tuple[asyncio.Lock, float]] = {}

    async def query(self, bot: QQBot, group_id: str) -> QQGroupBotState:
        lock, _ = self.slots.setdefault(bot.self_id, (asyncio.Lock(), 0.0))
        async with lock:
            retried = False
            while True:
                # 重试也消耗同一 Bot 的配额，不能绕过 30 QPM 限速。
                delay = self.slots[bot.self_id][1] - monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                self.slots[bot.self_id] = (lock, monotonic() + 2.1)
                request = Request("GET", bot.adapter.get_api_base().joinpath("v2", "groups", group_id, "bot_state"))
                try:
                    response = await bot._request(request)
                except ActionFailed as error:
                    failure = get_qq_group_state_failure(error)
                    if retried or failure.action != "retry":
                        raise
                    retried = True
                    log("WARNING", f"QQ 群状态查询重试 bot_id={bot.self_id} group_id={group_id} "
                        f"code={failure.code} 原因={failure.reason}")
                else:
                    return QQGroupBotState.model_validate(response)


def get_qq_group_state_client(bot: QQBot) -> QQGroupStateClient:
    """状态查询配额归属适配器，按 Bot ID 共享而非进程单例。"""
    if not isinstance(bot.adapter, ProjectQQAdapter):
        raise TypeError("群状态查询需要 Wind QQ Adapter")
    return bot.adapter.group_state_client


async def get_qq_group_bot_state(bot: QQBot, group_id: str) -> QQGroupBotState:
    """查询群内权限；复用 SDK 的鉴权、Token 刷新和错误处理。"""
    return await get_qq_group_state_client(bot).query(bot, group_id)


class QQInteractionMessageScene(BaseModel):
    """消息反馈互动携带的消息场景。"""

    ext: list[str]


class QQInteractionAuthorizeData(BaseModel):
    """用户或群授权互动的授权信息。"""

    opt_scene: str
    scope: str


class QQInteractionResolved(BaseModel):
    """QQ 官方互动事件解析后的业务字段。"""

    user_id: str | None = None
    message_id: str | None = None
    feature_id: str | None = None
    button_id: str | None = None
    button_data: str | None = None
    checked: int | None = None
    feedback_opt: str | None = None
    action: str | None = None
    message_scene: QQInteractionMessageScene | None = None
    authorize_data: QQInteractionAuthorizeData | None = None


class QQInteractionData(BaseModel):
    """QQ 官方互动事件的数据载荷。"""

    # type=20 的实际回调可能传入业务子类型（如 2001），按整数原样保留。
    type: int | None = None
    resolved: QQInteractionResolved


class ProjectQQInteractionCreateEvent(NoticeEvent):
    """建模 QQ 官方文档列出的全部互动事件。"""

    __type__ = EventType.INTERACTION_CREATE

    id: str
    type: Literal[11, 12, 13, 14, 15, 16, 18, 19, 20]
    version: int
    timestamp: str
    scene: str
    chat_type: int | None = None
    guild_id: str | None = None
    channel_id: str | None = None
    user_openid: str | None = None
    group_openid: str | None = None
    group_member_openid: str | None = None
    application_id: str | None = None
    data: QQInteractionData

    @override
    def get_user_id(self) -> str:
        if self.chat_type == 0 and self.data.resolved.user_id:
            return self.data.resolved.user_id
        if self.chat_type == 1 and self.group_member_openid:
            return self.group_member_openid
        if self.chat_type == 2 and self.user_openid:
            return self.user_openid
        raise ValueError("Interaction event has no user context")

    @override
    def get_session_id(self) -> str:
        user_id = self.get_user_id()
        if self.chat_type == 0:
            return f"guild_{self.guild_id}_channel_{self.channel_id}_{user_id}"
        if self.chat_type == 1:
            return f"group_{self.group_openid}_{user_id}"
        return f"friend_{user_id}"


def create_qq_interaction_group_message(
    bot: Bot,
    event: ProjectQQInteractionCreateEvent,
) -> GroupMessage:
    """把群聊按钮回调转换为可复用统一上下文。"""

    if event.chat_type != 1 or event.group_openid is None:
        raise InvalidMessageContextError("QQ interaction is not a group callback")
    return GroupMessage(
        protocol="qq",
        transport="webhook",
        message_id=event.data.resolved.message_id,
        text="",
        raw_text="",
        is_to_me=True,
        sender=MessageSender(id=event.get_user_id(), name=None),
        _bot=bot,
        _event=event,
        _matcher=None,
        group=MessageGroup(id=event.group_openid, name=None),
    )


async def acknowledge_qq_interaction(
    bot: Bot,
    event: ProjectQQInteractionCreateEvent,
    code: int,
) -> None:
    """按官方互动响应接口立即结束客户端按钮加载态。"""

    await _call_capability(
        bot,
        "put_interaction",
        interaction_id=event.id,
        code=code,
    )


async def send_qq_group_event_response(
    bot: Bot,
    event: GroupAddRobotEvent,
    content: Document,
) -> MessageReceipt:
    """使用入群事件的真实凭据回复一条 Markdown，不退化为主动发送。"""
    if not event.event_id:
        raise InvalidMessageContextError("QQ 入群事件缺少 event_id，无法发送被动回复")
    try:
        response = await _call_capability(
            bot, "send_to_group", group_openid=event.group_openid,
            event_id=event.event_id, message=await _render_document(content, _image_publisher(bot)),
        )
    except MatcherException:
        raise
    except Exception as exc:
        raise MessageSendError("QQ 入群事件回复失败") from exc
    return MessageReceipt(_message_id(response))


async def send_qq_interaction_response(
    bot: Bot,
    event: ProjectQQInteractionCreateEvent,
    content: OutboundContent | Sequence[OutboundContent],
) -> list[MessageReceipt]:
    """互动确认后向原群聊或私聊发送消息，无需用户二次发命令。"""

    if event.chat_type == 2 and event.user_openid is not None:
        api = "send_to_c2c"
        target = {"openid": event.user_openid}
    elif event.group_openid is not None:
        api = "send_to_group"
        target = {"group_openid": event.group_openid}
    else:
        raise InvalidMessageContextError("QQ interaction has no group or private context")
    contents = (
        (content,)
        if isinstance(content, (str, Document, ImageContent, RichContent, OrderedContent))
        else content
    )
    receipts: list[MessageReceipt] = []
    try:
        for item in contents:
            for message in await _render_content(item, _image_publisher(bot)):
                response = await _call_capability(
                    bot,
                    api,
                    message=message,
                    **({"event_id": event.event_id} if event.event_id is not None else {}),
                    **target,
                )
                receipts.append(MessageReceipt(_message_id(response)))
    except MatcherException:
        raise
    except Exception as exc:
        raise MessageSendError("QQ interaction response failed") from exc
    return receipts


async def delete_qq_group_message(
    bot: Bot,
    group_openid: str,
    message_id: str,
) -> None:
    """撤回上一条 QQ 群互动结果；超过平台撤回时限时保留旧消息。"""

    try:
        await _call_capability(
            bot,
            "delete_group_message",
            group_openid=group_openid,
            message_id=message_id,
        )
    except ActionFailed as error:
        if error.code != 40064004:
            raise
        # 新结果已发送，旧消息过期不可重试，不应中断后续清理或会话更新。
        log("WARNING", f"QQ 群消息超过撤回时限，保留旧消息：message_id={message_id}, code={error.code}")


def _image_publisher(bot: Bot) -> ImagePublisher | None:
    return bot.adapter.image_publisher if isinstance(bot.adapter, ProjectQQAdapter) else None


class ProjectQQAdapter(QQAdapter):
    """复用官方通信栈，局部扩展事件并拥有 Wind 运行期状态。"""

    def __init__(self, driver: Driver, *, image_publisher: ImagePublisher | None = None, **kwargs: Any) -> None:
        from .group_join import GroupJoinApprover

        self.wind_config = get_plugin_config(Config)
        if image_publisher is not None and self.wind_config.wind_cos.enabled:
            raise ValueError("自定义图片发布器不能与内置 COS 同时启用")
        self.image_publisher = image_publisher
        self._cos_storage = None
        if self.wind_config.wind_cos.enabled:
            from .storage.cos import TencentCosStorage

            self._cos_storage = TencentCosStorage()
            self._cos_storage.configure(self.wind_config.wind_cos)
            self.image_publisher = self._cos_storage
        self.group_state_client = QQGroupStateClient()
        self.group_join_approver = GroupJoinApprover()
        self._webhook_locks: dict[str, asyncio.Lock] = {}
        self._closing = False
        super().__init__(driver, **kwargs)
        register_command_preprocessor()

    def setup(self) -> None:
        for info in self.qq_config.qq_bots:
            info.intent.group_members = self.wind_config.wind_qq_group_members
            self._webhook_locks[info.id] = asyncio.Lock()
        super().setup()

    @staticmethod
    def payload_to_event(payload: Dispatch) -> Event:
        if payload.type == EventType.INTERACTION_CREATE:
            data = payload.data if isinstance(payload.data, dict) else {}
            return type_validate_python(ProjectQQInteractionCreateEvent, {"event_id": payload.id, **data})
        return QQAdapter.payload_to_event(payload)

    async def startup(self) -> None:
        await super().startup()
        if self.wind_config.wind_qq_initialize_webhook_bots:
            await self.initialize_webhook_bots()

    async def initialize_webhook_bots(self) -> list[Bot]:
        ready: list[Bot] = []
        if self._closing:
            return ready
        for config in self.qq_config.qq_bots:
            if config.use_websocket:
                continue
            # 提前初始化与首次回调共用锁；认证成功前不暴露在线 Bot。
            async with self._webhook_locks[config.id]:
                if self._closing:
                    break
                existing = self.bots.get(config.id)
                if existing is not None:
                    ready.append(existing)
                    continue
                bot = QQBot(self, config.id, config)
                try:
                    bot.self_info = await asyncio.wait_for(bot.me(), timeout=15)
                    if self._closing:
                        break
                    self.bot_connect(bot)
                except Exception as exc:
                    await _log_send_failure(exc, f"QQ webhook Bot 初始化失败 bot={config.id}")
                    continue
                ready.append(bot)
        return ready

    def bot_connect(self, bot: Bot) -> None:
        # SDK 回调可能正在等待认证；关闭后不得让迟到结果重新注册 Bot。
        if self._closing:
            raise RuntimeError("Wind QQ Adapter 已关闭，不能建立新连接")
        super().bot_connect(bot)

    async def _handle_http(self, request: Request) -> Response:
        if self._closing:
            return Response(503, content="Wind QQ Adapter is closing")
        lock = self._webhook_locks.get(request.headers.get("X-Bot-Appid", ""))
        if lock is None:
            return await super()._handle_http(request)
        async with lock:
            if self._closing:
                return Response(503, content="Wind QQ Adapter is closing")
            return await super()._handle_http(request)

    async def shutdown(self) -> None:
        self._closing = True
        try:
            await super().shutdown()
        finally:
            for bot in list(self.bots.values()):
                if self.bots.get(bot.self_id) is bot:
                    self.bot_disconnect(bot)
            self.group_state_client.slots.clear()
            self.group_join_approver.clear()
            if self._cos_storage is not None:
                self._cos_storage.reset()


Adapter = ProjectQQAdapter


def register(driver: Driver, **kwargs: Any) -> None:
    """校验后注册，防止框架静默忽略同名官方适配器。"""
    if Adapter.get_name() in driver._adapters:
        raise RuntimeError("QQ 已注册，不能重复注册 Wind 或官方适配器")
    driver.register_adapter(Adapter, **kwargs)


def register_qq_extensions() -> None:
    """保留旧调用入口；扩展由 Wind Adapter 局部解析，不再修改 SDK 全局表。"""
