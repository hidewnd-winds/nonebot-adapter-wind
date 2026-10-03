"""图文顺序、回执、引用和主动消息示例。所有请求只在函数显式调用后执行。"""

from collections.abc import Sequence
from typing import Protocol

from nonebot.adapters import Bot
from nonebot.adapters.wind import (
    ImageContent,
    MessageReceipt,
    OrderedContent,
    RichContent,
    UnifiedMessage,
    document,
    get_referenced_message,
    observe_message_receipts,
    paragraph,
    send_message,
    send_proactive_message,
)


class ReceiptArchive(Protocol):
    async def save_outbound(
        self, message: UnifiedMessage, receipts: Sequence[MessageReceipt]
    ) -> None: ...


async def reply_with_ordered_content(
    message: UnifiedMessage,
    archive: ReceiptArchive,
    image_data: bytes,
) -> list[MessageReceipt]:
    ordered = OrderedContent((
        "结果图片：\n",
        ImageContent(image_data, file_name="result.png"),
        "\n处理完成",
    ))
    observed: list[list[MessageReceipt]] = []
    with observe_message_receipts(observed.append):
        receipts = await send_message(message, ordered, finish=False, reply_to_source=True)
    await archive.save_outbound(message, receipts)
    assert observed == [receipts]
    return receipts


async def reply_with_rich_content(
    message: UnifiedMessage, image_data: bytes, *, single_message: bool = False
) -> list[MessageReceipt]:
    content = RichContent(
        document=document(paragraph("图文报告")),
        images=(ImageContent(image_data, file_name="result.png"),),
        images_first=True,
        footer=document(paragraph("图片下方说明")),
        single_message=single_message,
    )
    return await send_message(message, content, finish=False)


async def reply_to_explicit_reference(message: UnifiedMessage) -> None:
    referenced = await get_referenced_message(message)
    if referenced is not None:
        await send_message(message, f"引用内容：{referenced.text}", finish=False, reply_to_source=True)


async def send_proactive_notice(bot: Bot, user_id: str) -> list[MessageReceipt]:
    return await send_proactive_message(bot, user_id, "后台任务已完成", private=True)
