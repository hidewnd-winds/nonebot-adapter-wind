"""不同聊天平台实现统一业务能力时必须满足的接口。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from nonebot.adapters import Bot, Event
from nonebot.matcher import Matcher

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
    MessageReceipt,
    OutboundContent,
    ProtocolName,
    ReferencedMessage,
    UnifiedMessage,
)


class ProtocolAdapter(Protocol):
    """统一适配器要求各平台实现的能力。"""

    @property
    def protocol(self) -> ProtocolName:
        """当前实现对应的平台协议。"""

        ...

    def supports_event(self, event: Event) -> bool:
        """判断当前实现是否支持该平台事件。"""

        ...

    def get_group_member_change(self, bot: Bot, event: Event) -> GroupMemberChange | None:
        """转换普通成员变动，其他事件与机器人自身事件返回 None。"""
        ...

    def create_message(
        self,
        bot: Bot,
        event: Event,
        matcher: Matcher | None,
    ) -> UnifiedMessage:
        """将平台事件转换为统一消息。"""

        ...

    def clone_event(
        self,
        message: UnifiedMessage,
        text: str,
    ) -> Event:
        """克隆当前平台消息事件并替换为新的纯文本内容。"""

        ...

    async def get_referenced_message(
        self,
        message: UnifiedMessage,
    ) -> ReferencedMessage | None:
        """解析当前事件明确引用的原消息。"""

        ...

    async def send(
        self,
        message: UnifiedMessage,
        contents: Sequence[OutboundContent],
        *, reply_to_source: bool = False, allow_fallback: bool = True,
    ) -> list[MessageReceipt]:
        """转换并回复一组统一内容。"""

        ...

    async def recall_group_message(self, message: GroupMessage) -> None:
        """撤回指定入站群消息；失败必须交由业务处理。"""
        ...

    async def send_to_group(
        self,
        message: UnifiedMessage,
        group_id: str,
        contents: Sequence[OutboundContent],
    ) -> list[MessageReceipt]:
        """向指定平台群发送一组统一内容。"""

        ...

    async def send_proactive(
        self, bot: Bot, target_id: str, contents: Sequence[OutboundContent], *, private: bool,
    ) -> list[MessageReceipt]:
        """不依赖入站事件的主动发送。"""
        ...

    async def get_group_info(
        self,
        message: GroupMessage,
        group_id: str,
    ) -> GroupInfo | None:
        """查询并转换平台群资料。"""

        ...

    async def get_groups(
        self,
        message: UnifiedMessage,
    ) -> list[GroupInfo]:
        """查询当前 Bot 已加入的群列表。"""

        ...

    async def get_group_member(
        self,
        message: GroupMessage | Bot,
        group_id: str,
        user_id: str,
        *, fresh: bool = False,
    ) -> GroupMember | None:
        """查询并转换平台群成员资料。"""

        ...

    async def get_group_members(
        self,
        message: GroupMessage,
        group_id: str,
    ) -> list[GroupMember]:
        """查询并转换平台群成员列表。"""

        ...

    async def get_group_bot_state(self, bot: Bot, group_id: str) -> GroupBotState:
        """查询 Bot 的群角色及平台可提供的独立权限。"""
        ...

    async def get_group_mute_settings(self, bot: Bot, group_id: str) -> GroupMuteSettings:
        """查询群禁言设置；平台没有查询能力时显式报错。"""
        ...

    async def set_group_members_mute(
        self, bot: Bot, group_id: str, members: Sequence[GroupMemberMute],
    ) -> None:
        """修改成员禁言，不自动重试写入。"""
        ...

    async def get_group_join_requests(
        self, bot: Bot, group_id: str, *, cursor: str | None, limit: int | None,
    ) -> GroupJoinRequestPage:
        """拉取一页真实平台入群申请。"""
        ...

    async def approve_group_join_request(
        self, bot: Bot, group_id: str, request: GroupJoinRequest, *, approve: bool,
        reason: str | None, add_to_blacklist: bool,
    ) -> None:
        """审批真实申请，OneBot 使用原事件 flag 和 sub_type。"""
        ...

    async def remove_group_members(
        self, bot: Bot, group_id: str, user_ids: Sequence[str], *, add_to_blacklist: bool,
    ) -> GroupMemberRemovalResult:
        """移除成员；OneBot 附带拒绝再次入群，不具备独立黑名单接口。"""
        ...

    async def get_group_blacklist(
        self, bot: Bot, group_id: str, *, cursor: str | None, limit: int | None,
    ) -> GroupBlacklistPage:
        """查询一页平台群黑名单。"""
        ...

    async def set_group_blacklist(
        self, bot: Bot, group_id: str, user_ids: Sequence[str], *, add: bool,
    ) -> tuple[str, ...]:
        """增删平台群黑名单，返回平台明确报告失败的用户标识。"""
        ...
