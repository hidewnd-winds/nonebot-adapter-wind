"""双协议入群申请身份与自动拒绝请求配额。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from time import monotonic
from typing import Literal
from urllib.parse import quote

from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import Bot as OneBot
from nonebot.adapters.onebot.v11.event import GroupRequestEvent
from nonebot.adapters.qq import Bot as QQBot
from nonebot.adapters.qq.event import GroupJoinRequestEvent
from nonebot.exception import MatcherException

from .log import log

from .models import GroupJoinRequest


@dataclass(frozen=True)
class GroupJoinApplication:
    protocol: Literal["qq", "onebot_v11"]
    group_id: str
    user_id: str
    request_id: str
    nickname: str = ""
    qq_number: str = ""
    avatar_url: str = ""
    already_approved: bool = False

    def __post_init__(self) -> None:
        if not self.group_id or not self.user_id or not self.request_id:
            raise ValueError("入群申请缺少群、用户或申请标识")


async def get_group_join_application(bot: Bot, event: Event) -> GroupJoinApplication | None:
    if isinstance(bot, QQBot) and isinstance(event, GroupJoinRequestEvent):
        return GroupJoinApplication("qq", event.group_openid, event.member_openid, event.join_request_id,
                                    nickname=event.username,
                                    avatar_url=f"https://q.qlogo.cn/qqapp/{bot.self_id}/{quote(event.member_openid, safe='')}/640",
                                    already_approved=event.auto_approved is not None)
    if not isinstance(bot, OneBot) or not isinstance(event, GroupRequestEvent) or event.sub_type != "add":
        return None
    nickname = ""
    try:
        user = await bot.get_stranger_info(user_id=event.user_id, no_cache=True)
        name = user.get("nickname")
        if isinstance(name, str):
            nickname = name
    except MatcherException:
        raise
    except Exception as error:
        # QQ 号已来自真实事件；昵称查询失败不能伪造昵称，也不妨碍按 QQ 号判断。
        log("ERROR", f"申请人昵称查询失败，仅使用真实 QQ 号：{error}", error)
    return GroupJoinApplication("onebot_v11", str(event.group_id), str(event.user_id), event.flag,
                                nickname=nickname, qq_number=str(event.user_id),
                                avatar_url=f"https://q1.qlogo.cn/g?b=qq&nk={event.user_id}&s=640")


class GroupJoinApprover:
    """拥有审批请求配额；与 bot_state 的独立配额分开，按 Bot 串行拒绝。"""
    def __init__(self) -> None:
        self.slots: dict[str, tuple[asyncio.Lock, float]] = {}

    @asynccontextmanager
    async def request_slot(self, bot: Bot) -> AsyncIterator[None]:
        """先等待配额，再由业务检查最新权限和配置，锁内发送避免检查后重新排队。"""
        if not isinstance(bot, QQBot):
            yield
            return
        lock, _ = self.slots.setdefault(bot.self_id, (asyncio.Lock(), 0.0))
        async with lock:
            delay = self.slots[bot.self_id][1] - monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                yield
            finally:
                self.slots[bot.self_id] = (lock, monotonic() + 1.1)

    async def reject(self, bot: Bot, application: GroupJoinApplication, *, reason: str | None) -> None:
        from .api import approve_group_join_request
        if not (
            isinstance(bot, OneBot) and application.protocol == "onebot_v11"
            or isinstance(bot, QQBot) and application.protocol == "qq"
        ):
            raise TypeError("申请协议与当前 Bot 不一致")
        await approve_group_join_request(
            bot, application.group_id,
            GroupJoinRequest(request_id=application.request_id, user_id=application.user_id),
            approve=False, reason=reason, add_to_blacklist=False,
        )

    def clear(self) -> None:
        self.slots.clear()


def get_group_join_approver(bot: Bot) -> GroupJoinApprover:
    """取得当前 Wind Adapter 的审批配额，连接替换不会重置额度。"""
    from .onebot_v11 import ProjectOneBotV11Adapter
    from .qq import ProjectQQAdapter

    if not isinstance(bot.adapter, (ProjectOneBotV11Adapter, ProjectQQAdapter)):
        raise TypeError("审批配额需要 Wind Adapter")
    return bot.adapter.group_join_approver
