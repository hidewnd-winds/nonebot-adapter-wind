"""入站命令首行的空格容错，保留原始消息与多行正文。"""
from __future__ import annotations

import re
from typing import TypeVar

from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from nonebot.adapters.onebot.v11 import Message as OneBotMessage
from nonebot.adapters.qq import Message as QQMessage
from nonebot.adapters.qq.event import C2CMessageCreateEvent, GroupMessageCreateEvent
from nonebot.message import event_preprocessor

CommandMessage = TypeVar("CommandMessage", OneBotMessage, QQMessage)


def _collapse_message_spaces(message: CommandMessage) -> CommandMessage:
    """只折叠首行词语间的 2–3 个半角空格，不改变其他分隔符。"""
    replacements: dict[int, str] = {}
    for index, segment in enumerate(message):
        if segment.type != "text":
            continue
        text = segment.data.get("text")
        if not isinstance(text, str):
            continue
        newline = re.search(r"[\r\n]", text)
        end = newline.start() if newline is not None else len(text)
        collapsed = re.sub(r"(?<=\S) {2,3}(?=\S)", " ", text[:end]) + text[end:]
        if collapsed != text:
            replacements[index] = collapsed
        # 后续段可能携带自由文本；首次换行后连缩进和空行也必须原样保留。
        if newline is not None:
            break
    if not replacements:
        return message
    prepared = message.copy()
    for index, text in replacements.items():
        prepared[index].data["text"] = text
    return prepared


def collapse_command_spaces(event: Event) -> None:
    """仅替换协议命令视图，深拷贝避免连带修改 original_message。"""
    if isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
        event.message = _collapse_message_spaces(event.get_message())
    elif isinstance(event, (GroupMessageCreateEvent, C2CMessageCreateEvent)):
        event.message = _collapse_message_spaces(event.get_message())


async def prepare_command_message(bot: Bot, event: Event) -> None:
    """只处理 Wind Bot；转换入口也读取同一实例配置。"""
    from .onebot_v11 import ProjectOneBotV11Adapter
    from .qq import ProjectQQAdapter, _prepare_qq_command_message

    if isinstance(bot.adapter, ProjectQQAdapter):
        _prepare_qq_command_message(event, bot.adapter.wind_config)
    elif isinstance(bot.adapter, ProjectOneBotV11Adapter):
        if bot.adapter.wind_config.wind_collapse_command_spaces:
            collapse_command_spaces(event)


def register_command_preprocessor() -> None:
    """复用框架注册表，避免另建全局状态或重复注册依赖对象。"""
    from nonebot.message import _event_preprocessors

    if not any(item.call is prepare_command_message for item in _event_preprocessors):
        event_preprocessor(prepare_command_message)
