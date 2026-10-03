# 故障排查

## 注册后没有 Wind 行为

Wind 与官方 Adapter 使用相同注册名。`driver.register_adapter()` 对重复名称可能静默忽略。改为使用 `nonebot.adapters.wind.qq.register(driver)` 或 `nonebot.adapters.wind.onebot_v11.register(driver)`，并确保注册调用前没有注册同协议官方 Adapter。

## 无法转换事件

`UnsupportedProtocolEventError` 表示该事件不是统一层支持的消息事件。使用 `try_get_unified_message()` 可在 Matcher 前阶段安全探测；若需要处理 QQ 交互或其他平台通知，应使用其专有事件入口或官方原生事件，不要将它伪装成消息。

## QQ 引用或发送失败

QQ 被动回复凭据有时效和次数限制，过期时可能只能在 `allow_fallback=True` 下发送普通消息。`msg_seq` 和同群被动回复也受平台约束。排查 Bot 是否在线、事件是否来自预期群、请求凭据是否有效，以及错误日志中的平台响应；禁用降级后失败会原样暴露。

## `single_message=True` 失败

平台组合不支持该文档、图片及按钮在同一消息内发送时会明确失败。若业务允许拆分，去掉 `single_message`，或改用平台支持的消息组合；不要捕获异常后声称完整内容已发送。

## 群管理能力或权限未知

平台没有对应 API 时会抛出 `UnsupportedProtocolCapabilityError`。缺字段的角色/权限以 `unknown` 或未提供状态表示。应用应按自身授权策略处理，不要将 unknown 当作 owner/admin。

## 批量操作有部分完成

收到 `GroupBatchOperationError` 时读取其已完成对象和失败对象，只对确认未执行且接口语义允许的项目进行人工恢复。库不会自动重放写操作，应用也不应不加判断地重试整批。

## COS 初始化或上传失败

基础消息功能无需 COS。确认安装了 `[cos]`，配置了全部必填字段，并且没有同时注入自定义 `image_publisher`。已配置发布器的上传异常应按真实失败排查，不能通过伪造远程 URL 绕开。

## 日志和归档

Wind 使用 NoneBot 日志。归档和业务统计不属于独立协议包；调用方可在 `send_message(..., finish=False)` 取得 `MessageReceipt`，使用 `observe_message_receipts()` 做请求内观察，或按自己的 Matcher 生命周期连接持久化。
