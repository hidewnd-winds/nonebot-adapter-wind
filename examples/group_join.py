"""入群申请身份提取与审批配额；审批前由宿主明确检查权限。"""

from nonebot.adapters import Bot, Event
from nonebot.adapters.wind.group_join import get_group_join_application, get_group_join_approver


async def reject_if_authorized(
    bot: Bot,
    event: Event,
    *,
    reject_is_authorized: bool,
    reason: str | None,
) -> bool:
    application = await get_group_join_application(bot, event)
    if application is None or not reject_is_authorized:
        return False
    approver = get_group_join_approver(bot)
    async with approver.request_slot(bot):
        await approver.reject(bot, application, reason=reason)
    return True
