# 消息 API

## 入站统一消息

```python
from nonebot.params import Depends
from nonebot.adapters.wind import GroupMessage, UnifiedMessage, get_unified_message

async def handle(message: UnifiedMessage = Depends(get_unified_message)) -> None:
    if isinstance(message, GroupMessage):
        group_id = message.group.id
    print(message.protocol, message.scene, message.sender.id, message.text)
```

`text` 供命令与业务处理使用，`raw_text` 保留协议原始文本。`content_parts` 表示文本与图片顺序；`images` 只列出图片。真实提及由消息段提取，文本中的 `@昵称` 不会被当作提及。引用 ID 与消息 ID 分开保存；需要读取原消息时调用 `get_referenced_message(message)`，无明确引用返回 `None`。

`clone_message_event(message, text)` 按来源协议克隆事件并替换正文，供明确的命令重放场景使用。它不应被用于制造授权身份。

## 回复、主动发送和回执

```python
from nonebot.adapters.wind import (
    ImageContent,
    MessageReceipt,
    RichContent,
    document,
    observe_message_receipts,
    paragraph,
    send_message,
)

async def handle(message, image_data: bytes):
    observed: list[list[MessageReceipt]] = []
    with observe_message_receipts(observed.append):
        receipts = await send_message(
            message,
            RichContent(
                document=document(paragraph("查询完成")),
                images=(ImageContent(image_data, "result.png"),),
            ),
            finish=False,
            reply_to_source=True,
        )
    # receipts 是本次发送的真实平台回执；平台可能不给 message_id。
```

`send_message(message, content, finish=True, reply_to_source=False, allow_fallback=True)` 支持字符串、`Document`、`ImageContent`、`RichContent`、`OrderedContent` 或这些内容的非空序列。`finish=True` 在发送成功后结束当前 Matcher；若没有 Matcher 上下文会抛 `InvalidMessageContextError`。要继续执行或检查回执，设 `finish=False`。

`reply_to_source=True` 请求引用原消息；OneBot 使用可用的消息段引用，QQ 受回包凭据时效限制。引用无法使用时，允许降级才可以改用普通发送。设置 `allow_fallback=False` 可禁止该路径。

`observe_message_receipts(callback)` 是基于异步任务上下文的观察器，回调接收 `list[MessageReceipt]`。它不代替返回值，也不负责持久化。`send_group_message(message, group_id, content)` 使用当前 Bot 主动向指定群发送。

## 显式业务异常和 Markdown 响应

`finish_command_action(message, action, finish=True)` 执行异步 action；捕获 `UserFacingError` 后向当前会话发送其消息。其他异常继续传播。它用于将预期业务错误转换为用户回复，不应吞掉系统错误。

```python
from nonebot.adapters.wind import prefer_markdown_response

with prefer_markdown_response("正在查找", result_summary="结果如下"):
    await send_message(message, "普通字符串正文", finish=False)
```

`prefer_markdown_response` 只影响作用域内的统一发送：QQ 将正文按 Markdown 形式处理；OneBot 输出可读纯文本。没有进入该上下文的普通字符串始终是纯文本，不会因星号或链接语法自动解释为 Markdown。

## 会话和事件辅助

- `get_bot_protocol(bot)` 从实际 Bot 类型识别协议。
- `get_user_avatar_url(message, user_id=None)` 返回协议层可提供的头像地址；不存在则为 `None`。
- `get_group_member_change(bot, event)` 仅转换普通成员进退群事件，不构造消息上下文。
- `try_get_unified_message(bot, event, matcher=None)` 适合 Matcher 前阶段，无法转换时返回 `None`。

平台调用失败时检查 `ProtocolAdapterError` 子类：不支持事件、能力、消息内容、会话上下文、发送失败、引用解析失败分别有不同异常。不要捕获基类后将失败伪装为空消息。

## 上下文作用范围和持久化

`prefer_markdown_response(request_summary="", result_summary="")` 对 QQ 普通字符串构造 Document；对单张 `ImageContent`，QQ 的请求摘要作为引用块，结果摘要作为正文。OneBot 只在有结果摘要时组合图片说明。已有 RichContent 带图片时，会把结果摘要放在原正文前；已有 Document、OrderedContent 保留业务结构。该上下文与回执观察均用 ContextVar 隔离并发任务。

这两个上下文当前作用于 `send_message` 的会话回复；`send_group_message`、`send_proactive_message`、QQ 专用交互 API 返回自己的回执，不自动经过该观察器。归档这些路径时直接消费返回值。

[`examples/observability.py`](../examples/observability.py) 提供真实 JSONL 回执保存实现及 `install_matcher_statistics(archive)`，后者在应用明确调用后才注册 NoneBot Matcher 钩子。和 [`reply_with_ordered_content`](../examples/message_flows.py) 搭配即可先 `finish=False` 发送，再保存真实回执。Matcher 统计仅表示处理器是否无异常结束，不等同于所有平台动作成功；业务仍应保存实际回执和异常结果。
