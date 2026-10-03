# 源码迁移与兼容性记录

## 来源

协议实现基线取自 wind-bot `src/adapter/protocol`，源版本：`fdc0180cecd662160f010903e15964a4c9d0eb5d`。原包有十个 Python 模块；独立工程保留模块职责和扁平平台文件。旧 `src.adapter.protocol` 导入路径不随发行包提供。

## 公共根导出映射

根包保留源基线 `__all__` 的 103 个公开名称。名称按功能映射到新路径 `nonebot.adapters.wind`；适配器注册移到平台模块。

| 功能组 | 根导出名称 |
|---|---|
| 入站消息与身份 | `UnifiedMessage`, `GroupMessage`, `PrivateMessage`, `MessageSender`, `MessageGroup`, `InboundImage`, `ReferencedMessage`, `GroupMemberChange`, `get_unified_message`, `try_get_unified_message`, `get_referenced_message`, `clone_message_event`, `get_bot_protocol`, `get_user_avatar_url` |
| 消息发送 | `send_message`, `send_group_message`, `send_proactive_message`, `MessageReceipt`, `OutboundContent`, `ImageContent`, `RichContent`, `OrderedContent`, `finish_command_action`, `CommandAction`, `CommandResult`, `observe_message_receipts`, `prefer_markdown_response` |
| Document 类型 | `Document`, `RenderedDocument`, `Inline`, `Block`, `Text`, `Heading`, `Paragraph`, `ListItem`, `Mention`, `ButtonModal`, `ButtonSpec`, `ButtonTable` |
| Document 构造和渲染 | `text`, `document`, `heading`, `paragraph`, `quote`, `divider`, `bold`, `italic`, `bold_italic`, `underline`, `strike`, `inline_code`, `link`, `image`, `mention`, `list_item`, `unordered_list`, `ordered_list`, `code_block`, `table`, `button_row`, `button_table`, `link_button`, `command_button`, `callback_button`, `render_markdown`, `render_plain_text` |
| 群查询与管理 | `GroupInfo`, `GroupMember`, `GroupBotState`, `GroupMuteSettings`, `GroupMuteRule`, `GroupMuteSchedule`, `GroupMuteRecurringRule`, `GroupMutedMember`, `GroupMemberMute`, `GroupJoinRequest`, `GroupJoinRequestPage`, `GroupBlacklistPage`, `GroupBlacklistedMember`, `GroupMemberRemovalResult`, `GroupBatchOperationError`, `get_group_info`, `get_groups`, `get_group_member`, `get_group_members`, `get_group_member_change`, `get_group_bot_state`, `get_group_mute_settings`, `set_group_members_mute`, `get_group_join_requests`, `approve_group_join_request`, `remove_group_members`, `get_group_blacklist`, `set_group_blacklist`, `recall_group_message` |
| 异常 | `ProtocolAdapterError`, `UnsupportedProtocolEventError`, `UnsupportedProtocolCapabilityError`, `InvalidMessageContentError`, `InvalidMessageContextError`, `MessageSendError`, `MessageReferenceResolveError`, `UserFacingError` |

QQ 事件/交互类型、QQ 群状态客户端、入群辅助和指令面板原本通过各自模块导入，继续保持平台模块路径，不计入根 `__all__`。子模块公共接口如下：

| 模块 | 对外名称 |
|---|---|
| `qq` | `ProjectQQAdapter`, `Adapter`, `register`, `QQProtocolAdapter`, `QQInteractionMessageScene`, `QQInteractionAuthorizeData`, `QQInteractionResolved`, `QQInteractionData`, `ProjectQQInteractionCreateEvent`, `create_qq_interaction_group_message`, `acknowledge_qq_interaction`, `send_qq_group_event_response`, `send_qq_interaction_response`, `delete_qq_group_message`, `QQGroupStateFailure`, `get_qq_group_state_failure`, `QQGroupBotState`, `QQGroupStateClient`, `get_qq_group_state_client`, `get_qq_group_bot_state`, `initialize_qq_webhook_bots`, `prepare_qq_command_message`, `register_qq_extensions` |
| `onebot_v11` | `ProjectOneBotV11Adapter`, `Adapter`, `register`, `OneBotV11ProtocolAdapter` |
| `group_join` | `GroupJoinApplication`, `get_group_join_application`, `GroupJoinApprover`, `get_group_join_approver` |
| `qq_panel` | `QQPanelItem`, `QQPanel`, `QQPanelRecord`, `QQPanelPage`, `QQPanelCreated`, `QQPanelUpdated`, `list_qq_group_panels`, `create_qq_group_panel`, `update_qq_panel` |
| `config` | `Config`, `CosSettings` |
| `media` | `DownloadedImage`, `ImagePublisher`, `detect_image_format`, `download_remote_image`, `get_image_byte_stream`, `get_png_dimensions`, `read_image_dimensions`, `resolve_image_url` |
| `storage.cos` | `CosClientProtocol`, `TencentCosStorage`, `TencentCosStorageError` |

包根导出顺序与 `tests/expected_exports.json` 一致。完整 103 项名称见该机器可读清单；本文表格提供功能分组和模块级接口索引。

## 有意差异

- 宿主日志替换为 NoneBot logger；数据库归档和命令统计不迁移。发送回执仍可供宿主自行集成。
- 固定 QQ 面板自动同步不迁移；面板读写 API 保留并需显式调用。
- 入群拒绝理由由调用方传入。审批配额和申请身份辅助保留，由 `get_group_join_approver(bot)` 按 Bot 获取实例。
- QQ 群状态客户端由 `get_qq_group_state_client(bot)` 按 Bot 获取实例；`register_qq_extensions()` 保留为弃用无操作函数。
- 命令预处理受 Wind 配置控制；默认行为保持源基线。
- 上游官方 Adapter 同名冲突通过 Wind `register(driver)` 检查；直接调用 NoneBot 注册 API 时的后续重复注册可能被上游静默忽略。
- QQ 交互事件通过 Wind QQ Adapter 局部解析，不污染官方 SDK 全局类表。

## 验证范围

兼容声明以发行版本的接口清单、测试和独立 wheel 安装验证为准。QQ Webhook、真实 OneBot 连接及 COS 需要分别在目标环境联调；静态检查不能代表平台验收。

## 宿主职责和签名变化明细

- `api.record_command_origin` 原本是宿主统计预处理器，已移出独立包；由宿主 Matcher 钩子承担，见[统计示例](../../examples/observability.py)。
- `qq.qq_group_state_client` 与 `group_join.group_join_approver` 进程单例不再导出；分别使用实例访问器 `get_qq_group_state_client(bot)`、`get_group_join_approver(bot)`。
- `GroupJoinApprover.reject` 新增必传关键字 `reason: str | None`，提取原宿主业务理由。
- `inbound.prepare_command_message`、`qq.prepare_qq_command_message` 增加 `bot` 参数，用于检查实例与配置；只在适配器初始化阶段幂等注册预处理器。
- `ProjectQQAdapter` 新增可选 `image_publisher`；`Adapter` 是原类的别名，`register(driver, **kwargs)` 为冲突检查入口，不增加替代类。
- `initialize_qq_webhook_bots()` 只处理已注册的 Wind QQ 实例；实例方法负责认证、锁、重复初始化与关闭检查。
- 所有十个原模块中的其余非私有函数/类声明保留；未因存在公开样式名称而将内部辅助类型加入包根 `__all__`。`document.py`、`models.py`、`base.py`、`qq_panel.py` 与来源文件保持一致。
