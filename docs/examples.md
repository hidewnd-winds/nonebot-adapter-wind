# 示例索引

代码样例集中在 [`examples/`](../examples/README.md)，本页解释入口与平台表现。示例不在导入时联网或发送消息；执行时按上游适配器配置连接平台。所有含群管理或面板写入的函数都需要明确调用。

| 文件 | 内容 | QQ | OneBot V11 |
|---|---|---|---|
| `examples/onebot.py` | 仅注册 OneBot 并处理统一消息 | 不注册 | 收到文本后回复 |
| `examples/qq.py` | 仅注册 QQ 并处理统一消息 | QQ Markdown 回复 | 不注册 |
| `examples/both.py` | 双协议注册、依赖注入 | Markdown 回复 | 纯文本回复 |
| `examples/document_nodes.py` | Document 节点、按钮和纯文本渲染 | Markdown/键盘 | 文本说明和 at 段 |
| `examples/message_flows.py` | Ordered/Rich 图文、引用、回执与主动消息 | 受回复凭据约束 | 保序消息段和引用 |
| `examples/qq_interaction.py` | 真实交互确认、回复及撤回 | 支持 | 不适用 |
| `examples/group_join.py` | 申请上下文、审批配额和权限检查 | 支持 | 支持 |
| `examples/image_publisher.py` | 自定义 QQ 图片发布器接口 | 上传发布后用于 Markdown | 不注册 |
| `examples/group_admin.py` | 经显式调用查询群资料和禁言设置 | 使用 QQ API | 使用 OneBot 能力，不支持时显式异常 |
| `examples/qq_panel.py` | 显式创建 QQ 帮助面板函数 | 创建面板 | 不适用 |

通过 `uv run --no-editable python examples/document_nodes.py` 可以运行不连接平台的本地示例。完整 bot 示例需先在 `.env.dev` 配置 NoneBot Driver 与对应上游适配器凭据，再以 `python -m examples.qq`、`python -m examples.onebot` 或 `python -m examples.both` 启动。示例模块不包含生产凭据。群管理和面板示例只定义函数，不会被默认消息处理器调用。

## 补充接入实例

- [`observability.py`](../examples/observability.py)：JSONL 回执归档与显式注册 Matcher 统计钩子。`JsonlArchive(Path("./data/receipts.jsonl"))` 创建对象不写文件，调用保存时才落盘；这是示例输出路径，由宿主选择。
- [`cos_storage.py`](../examples/cos_storage.py)：显式读取配置并上传本地图像，基础安装没有 COS SDK 时仍可导入模块，启用时才需要 `[cos]`。
- [`qq_panel.py`](../examples/qq_panel.py)：查询、创建、更新均有实际函数，必须由明确管理操作调用。
- `reply_with_rich_content(message, image_data, single_message=True)` 演示严格单消息：QQ 无发布器的二进制图文会在当前内容发送前失败，OneBot 可将媒体与文字放在同一 Message；`False` 则保留平台现有组合规则。

`document_nodes` 只打印渲染结果，不实际发键盘或 at。QQ/OneBot 的消息示例需传入真实运行时 Bot/UnifiedMessage，不能仅导入后认定平台联调通过。
