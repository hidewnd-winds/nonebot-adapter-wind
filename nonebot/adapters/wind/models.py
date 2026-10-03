"""统一聊天协议适配器的公共数据模型与异常。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from abc import ABC, abstractmethod
from typing import ClassVar, Literal, TypeAlias

from nonebot.adapters import Bot, Event
from nonebot.matcher import Matcher
from pydantic import ConfigDict

from .document import Document, render_plain_text

ProtocolName: TypeAlias = Literal["onebot_v11", "qq"]
TransportName: TypeAlias = Literal["websocket", "webhook"]
MessageScene: TypeAlias = Literal["group", "private"]
GroupRole: TypeAlias = Literal["owner", "admin", "member", "unknown"]


class ProtocolAdapterError(Exception):
    """统一聊天协议适配器错误基类。"""


class UnsupportedProtocolEventError(ProtocolAdapterError):
    """事件不属于已支持的平台消息类型。"""


class UnsupportedProtocolCapabilityError(ProtocolAdapterError):
    """当前平台不具备请求的消息或群能力。"""


class InvalidMessageContentError(ProtocolAdapterError):
    """业务传入的统一消息内容不合法。"""


class InvalidMessageContextError(ProtocolAdapterError):
    """当前消息缺少调用所需的群或用户上下文。"""


class MessageSendError(ProtocolAdapterError):
    """平台消息发送失败。"""


class MessageReferenceResolveError(ProtocolAdapterError):
    """平台引用消息存在，但其原消息内容无法解析。"""


class UserFacingError(Exception):
    """可直接转换为统一消息内容的用户可见业务异常。"""

    def __init__(self, message: str | Document) -> None:
        self.message = message
        # 消息发送保留引用和按钮，异常文本仍用于日志及纯文本框架入口。
        super().__init__(render_plain_text(message).text if isinstance(message, Document) else message)


@dataclass(frozen=True)
class GroupMemberChange:
    """成员实际进退群事件，不代表入群申请或机器人自身生命周期。"""

    protocol: ProtocolName
    group_id: str
    user_id: str
    kind: Literal["join", "leave"]
    timestamp: datetime
    event_id: str | None = None


@dataclass(frozen=True)
class MessageSender:
    """消息发送者的稳定业务字段。"""

    id: str
    """平台用户标识，业务层始终使用字符串。"""

    name: str | None
    """平台事件中可直接获得的显示名称。"""

    role: GroupRole = "unknown"
    """群聊中的统一角色；私聊或平台未提供时为 unknown。"""

    avatar_url: str | None = None
    """协议层提供的用户头像地址；业务层不拼接平台 URL。"""


@dataclass(frozen=True)
class MessageGroup:
    """当前群聊的稳定业务字段。"""

    id: str
    """平台群标识，业务层始终使用字符串。"""

    name: str | None
    """平台事件中可直接获得的群名称。"""


@dataclass(frozen=True)
class UnifiedMessage(ABC):
    """平台无关的入站消息和当前响应会话。

    允许 Bot、Event、Matcher 等框架对象通过 NoneBot 的 Pydantic 依赖校验。
    """

    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(
        arbitrary_types_allowed=True
    )

    protocol: ProtocolName
    """消息所属平台协议。"""

    transport: TransportName
    """消息进入项目时使用的传输方式。"""

    message_id: str | None
    """平台消息标识。"""

    text: str
    """用于命令解析和业务处理的纯文本。"""

    raw_text: str
    """平台事件提供的原始文本。"""

    is_to_me: bool
    """消息是否指向当前机器人。"""

    sender: MessageSender
    """当前消息发送者。"""

    _bot: Bot
    """仅供协议模块调用平台 API。"""

    _event: Event
    """仅供协议模块回复原始事件。"""

    _matcher: Matcher | None
    """当前 Matcher；权限预检阶段尚未创建时为 None。"""

    images: tuple[InboundImage, ...] = field(
        default_factory=tuple,
        kw_only=True,
    )
    """用户消息中携带的图片列表。"""

    content_parts: tuple[str | InboundImage, ...] = field(default=(), kw_only=True)
    """平台提供的原始文本与图片顺序；正文空白不参与命令归一化。"""

    mentioned_user_ids: tuple[str, ...] = field(
        default_factory=tuple,
        kw_only=True,
    )
    """消息段中真实提及的平台用户标识；不解析手写昵称。"""

    mentions_everyone: bool = field(default=False, kw_only=True)
    """平台消息中是否包含真实的全体成员提及。"""

    message_index: str | None = field(default=None, kw_only=True)
    """平台引用索引，与当前消息 ID 分开保存。"""

    original_plaintext: str | None = field(default=None, kw_only=True)
    """原消息真实文本段，不含引用正文、提及标签、图片地址或命令归一化。"""

    reference_id: str | None = field(default=None, kw_only=True)
    """平台明确声明的被引用消息索引；缺失时不得猜测。"""

    references: tuple[ReferencedMessage, ...] = field(default=(), kw_only=True)
    """平台随事件内联的关联消息，保留各自索引用于精确匹配。"""

    @property
    def has_image(self) -> bool:
        """判断用户消息是否携带图片。"""

        return bool(self.images)

    @property
    def is_text_only(self) -> bool:
        """判断用户消息是否仅为纯文本（无图片附件）。"""

        return not self.images

    @property
    @abstractmethod
    def scene(self) -> MessageScene:
        """消息场景，明确区分群聊和私聊。"""
        raise NotImplementedError

    def get_plaintext(self) -> str:
        """返回供 NoneBot 规则和业务解析使用的纯文本。"""

        return self.text


@dataclass(frozen=True)
class GroupMessage(UnifiedMessage):
    """统一群聊消息，始终携带非空群资料。"""

    group: MessageGroup
    """当前群聊资料。"""

    @property
    def scene(self) -> MessageScene:
        """群聊消息的场景标识。"""
        return "group"


@dataclass(frozen=True)
class PrivateMessage(UnifiedMessage):
    """统一私聊消息，不暴露群聊字段。"""

    @property
    def scene(self) -> MessageScene:
        """私聊消息的场景标识。"""
        return "private"


@dataclass(frozen=True)
class InboundImage:
    """入站消息中携带的图片信息。"""

    url: str
    """图片可访问的远程 URL。"""

    content_type: str | None = None
    """平台声明的 MIME 类型，仅作为下载前提示。"""

    filename: str | None = None
    """平台声明的原始文件名。"""

    size: int | None = None
    """平台声明的图片字节数。"""


@dataclass(frozen=True)
class ReferencedMessage:
    """当前消息明确引用的原消息内容。"""

    reference_id: str | None
    """协议提供的引用标识，未提供时为 None，不保证跨会话全局唯一。"""

    text: str
    """被引用消息的纯文本。"""

    images: tuple[InboundImage, ...] = ()
    """被引用消息直接携带的图片。"""

    sender_id: str | None = None
    """平台内联的原消息作者标识，不用于当前消息授权。"""

    sender_name: str | None = None
    """平台提供的原消息作者名称，缺少身份标识时仍可用于展示。"""


@dataclass(frozen=True)
class ImageContent:
    """待发送的二进制图片或远程图片。"""

    data: bytes | str
    """图片二进制内容或远程 URL。"""

    file_name: str = "image.png"
    """平台上传二进制图片时使用的基础文件名。"""

    alt_text: str = "图片"
    """远程图片无法展示时使用的平台无关说明。"""


@dataclass(frozen=True)
class RichContent:
    """结构化正文与图片附件组成的统一图文消息。"""

    document: Document | None = None
    """可选的结构化正文。"""

    images: tuple[ImageContent, ...] = ()
    """按业务顺序发送的图片附件。"""

    images_first: bool = False
    """是否在结构化正文之前展示图片。"""

    footer: Document | None = None
    """在正文和全部图片之后展示的独立说明。"""

    single_message: bool = False
    """要求全部内容在一条消息中发送；平台无法合并时在发送前报错。"""

    def __post_init__(self) -> None:
        """拒绝无法生成任何平台消息段的空内容。"""

        if self.document is None and not self.images and self.footer is None:
            raise InvalidMessageContentError("rich content requires document, image or footer")


@dataclass(frozen=True)
class OrderedContent:
    """需逐段保留空白与图文顺序的用户原文，不执行 Markdown 格式化。"""

    parts: tuple[str | ImageContent, ...]

    def __post_init__(self) -> None:
        if not self.parts or not any(isinstance(part, ImageContent) or part.strip() for part in self.parts):
            raise InvalidMessageContentError("ordered content cannot be empty")


OutboundContent: TypeAlias = str | Document | ImageContent | RichContent | OrderedContent


@dataclass(frozen=True)
class MessageReceipt:
    """平台消息发送成功后的统一回执。"""

    message_id: str | None
    """平台返回的消息标识；平台不返回时为 None。"""


@dataclass(frozen=True)
class GroupInfo:
    """业务侧可稳定使用的群资料。"""

    id: str
    """平台群标识。"""

    name: str | None
    """平台可提供的群名称。"""

    member_count: int | None
    """平台可提供的当前成员数量。"""

    max_member_count: int | None
    """平台可提供的成员数量上限。"""

    avatar_url: str | None = None
    """平台可提供的群头像地址；没有可靠来源时为空。"""


@dataclass(frozen=True)
class GroupMember:
    """业务侧可稳定使用的群成员资料。"""

    id: str
    """平台用户标识。"""

    nickname: str | None
    """平台用户昵称。"""

    card: str | None
    """群名片；平台不支持时为 None。"""

    role: GroupRole
    """统一后的群主、管理员、成员或未知角色。"""

    is_bot: bool | None = None
    joined_at: datetime | None = None
    union_id: str | None = None

    @property
    def display_name(self) -> str:
        """优先返回群名片，其次返回昵称和用户标识。"""

        return self.card or self.nickname or self.id


@dataclass(frozen=True)
class GroupBotState:
    """平台未提供的权限保持 None，不能当作授权或拒绝。"""

    role: GroupRole
    allow_proactive_msg: bool | None = None
    recv_msg_setting: str | None = None


@dataclass(frozen=True)
class GroupMuteSchedule:
    task_id: str
    start_at: datetime
    end_at: datetime
    enabled: bool


@dataclass(frozen=True)
class GroupMuteRecurringRule:
    task_id: str
    weekdays: tuple[int, ...]
    start_time: time
    end_time: time
    enabled: bool


@dataclass(frozen=True)
class GroupMuteRule:
    mode: Literal["none", "always", "schedule"]
    schedule_rules: tuple[GroupMuteSchedule, ...]
    recurring_rules: tuple[GroupMuteRecurringRule, ...]


@dataclass(frozen=True)
class GroupMemberMute:
    """禁言修改；绝对到期时间必须带时区，解除时无需时间。"""

    user_id: str
    op: Literal["add", "update", "del"]
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.user_id or self.op not in ("add", "update", "del"):
            raise ValueError("禁言操作缺少用户或操作类型无效")
        if self.op != "del" and (self.expires_at is None or self.expires_at.utcoffset() is None):
            raise ValueError("禁言到期时间必须包含时区")


@dataclass(frozen=True)
class GroupMutedMember:
    user_id: str
    expires_at: datetime
    nickname: str
    union_id: str | None = None


@dataclass(frozen=True)
class GroupMuteSettings:
    global_rule: GroupMuteRule
    members: tuple[GroupMutedMember, ...]


@dataclass(frozen=True)
class GroupJoinRequest:
    """真实平台申请；request_id 在 OneBot 中为事件 flag。"""

    request_id: str
    user_id: str
    nickname: str | None = None
    applied_at: datetime | None = None
    source: str | None = None
    invited_by: str | None = None
    is_bot: bool | None = None
    risk_tips: str | None = None
    union_id: str | None = None
    verify_method: str | None = None
    verify_message: str | None = None
    review_answers: tuple[tuple[str, str], ...] = ()
    sub_type: Literal["add", "invite"] = "add"


@dataclass(frozen=True)
class GroupJoinRequestPage:
    requests: tuple[GroupJoinRequest, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class GroupBlacklistedMember:
    user_id: str
    nickname: str | None
    is_bot: bool
    banned_at: datetime | None = None
    union_id: str | None = None


@dataclass(frozen=True)
class GroupBlacklistPage:
    members: tuple[GroupBlacklistedMember, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class GroupMemberRemovalResult:
    """保留平台移除结果和附带拉黑失败名单，不把空结果当成功。"""

    removed: bool
    blacklist_failed_ids: tuple[str, ...] = ()


class GroupBatchOperationError(ProtocolAdapterError):
    """逐人执行中断；已确认成功的用户不能因整体重试再次执行。"""

    def __init__(self, completed_ids: tuple[str, ...], failed_id: str):
        self.completed_ids = completed_ids
        self.failed_id = failed_id
        super().__init__(f"群批量操作中断，已完成 {len(completed_ids)} 人；失败目标 {failed_id}")
