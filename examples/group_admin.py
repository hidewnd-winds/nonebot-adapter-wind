"""群管理 API 示例；函数仅在显式调用时查询或修改平台状态。"""

from datetime import datetime, timedelta, timezone

from nonebot.adapters import Bot
from nonebot.adapters.wind import (
    GroupMemberMute,
    get_group_bot_state,
    get_group_mute_settings,
    set_group_members_mute,
)


async def inspect_group(bot: Bot, group_id: str) -> None:
    state = await get_group_bot_state(bot, group_id)
    settings = await get_group_mute_settings(bot, group_id)
    print("Bot 群状态：", state)
    print("禁言设置：", settings)


async def mute_member_after_authorization(
    bot: Bot,
    group_id: str,
    user_id: str,
    *,
    operator_is_authorized: bool,
) -> None:
    # 示例把业务授权作为显式前置条件；真实应用应在此执行自己的权限检查。
    if not operator_is_authorized:
        raise PermissionError("操作者无权修改群成员")
    await set_group_members_mute(
        bot,
        group_id,
        (GroupMemberMute(
            user_id=user_id,
            op="add",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        ),),
    )
