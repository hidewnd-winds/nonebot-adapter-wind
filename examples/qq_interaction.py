"""QQ 交互确认、回复和撤回；调用者必须提供真实事件并检查权限。"""

from nonebot.adapters import Bot
from nonebot.adapters.wind import document, paragraph
from nonebot.adapters.wind.qq import (
    ProjectQQInteractionCreateEvent,
    acknowledge_qq_interaction,
    create_qq_interaction_group_message,
    delete_qq_group_message,
    send_qq_interaction_response,
)


async def handle_confirmed_interaction(
    bot: Bot,
    event: ProjectQQInteractionCreateEvent,
    *,
    operator_is_authorized: bool,
) -> None:
    if not operator_is_authorized:
        await acknowledge_qq_interaction(bot, event, code=1)
        return
    if event.chat_type == 1:
        message = create_qq_interaction_group_message(bot, event)
        assert message.group.id == event.group_openid
    await acknowledge_qq_interaction(bot, event, code=0)
    receipts = await send_qq_interaction_response(
        bot, event, document(paragraph("已确认操作。"))
    )
    if event.group_openid and receipts and receipts[0].message_id:
        await delete_qq_group_message(bot, event.group_openid, receipts[0].message_id)
