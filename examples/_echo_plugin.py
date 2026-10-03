"""共享的统一消息演示处理器。导入不会连接平台或发送消息。"""

from nonebot import on_message
from nonebot.params import Depends

from nonebot.adapters.wind import (
    GroupMessage,
    UnifiedMessage,
    document,
    get_unified_message,
    heading,
    paragraph,
    send_message,
)

echo = on_message()


@echo.handle()
async def handle_echo(
    message: UnifiedMessage = Depends(get_unified_message),
) -> None:
    content = document(
        heading("Wind 收到消息"),
        paragraph("协议：", message.protocol),
        paragraph("场景：", message.scene),
        paragraph("发送者：", message.sender.name or message.sender.id),
        paragraph("正文：", message.text or "（无文本）"),
    )
    if isinstance(message, GroupMessage):
        content.append(paragraph("群：", message.group.name or message.group.id))
    await send_message(message, content)
