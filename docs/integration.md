# 安装与接入

## 安装

当前交付为本地 `0.1.0` 工程，尚未发布到 PyPI。在工程根目录使用 `uv`：

```bash
uv sync --locked --no-editable
uv run --locked --no-editable python -m examples.document_nodes
# 需要 COS 时：
uv sync --locked --no-editable --extra cos
```

部署到另一个虚拟环境时安装构建后的 wheel 及所需 Driver：

```bash
uv build
python -m pip install dist/nonebot_adapter_wind-0.1.0-py3-none-any.whl 'nonebot2[fastapi,httpx,websockets]>=2.5,<2.6'
# 可选 COS：将 wheel 参数替换为以下带 extra 的路径
python -m pip install 'dist/nonebot_adapter_wind-0.1.0-py3-none-any.whl[cos]'
```

这里的 `python` 应指向应用自己的虚拟环境。正式发布后才使用 `pip install nonebot-adapter-wind` 或 `pip install 'nonebot-adapter-wind[cos]'`。NoneBot 的 Driver 由宿主按传输需求安装，基础库不会强制选择服务器。

本工程的命名空间布局使用普通 wheel/非 editable 安装；`uv sync` 和 `uv run` 请带 `--no-editable`，避免已安装的 `nonebot` 包遮蔽开发目录。

## 初始化与注册

注册 QQ、OneBot 或二者。推荐通过 Wind 的 `register` 函数注册；它检测同名 Adapter 并在冲突时抛出 `RuntimeError`。NoneBot 的 `driver.register_adapter()` 对同名 Adapter 可能直接忽略，因此直接调用不能提供可靠冲突诊断。

```python
import nonebot
from nonebot.adapters.wind.qq import register as register_qq
from nonebot.adapters.wind.onebot_v11 import register as register_onebot

nonebot.init(_env_file=".env.dev", driver="~fastapi+~httpx+~websockets")
driver = nonebot.get_driver()
register_qq(driver)
register_onebot(driver)
nonebot.run()
```

如果只使用一种协议，只调用对应的注册函数。Wind QQ 与官方 QQ Adapter 使用相同注册名称；OneBot 同理。不要在同一 Driver 上混用同协议 Wind Adapter 和官方原版。

QQ 适配器继承官方 QQ Adapter 的配置和传输机制；Webhook Bot 项须提供 `id` 和 `secret`，并设置 `use_websocket=false`。例如在 `.env.dev` 中替换以下占位值：

```dotenv
HOST=127.0.0.1
PORT=8080
QQ_BOTS='[{"id":"YOUR_APP_ID","secret":"YOUR_APP_SECRET","use_websocket":false,"intent":{"c2c_group_at_messages":true,"interaction":true}}]'
```

OneBot 反向 WebSocket 由 NoneBot Driver 在 `/onebot/v11/ws` 接收；OneBot 端主动连接 `ws://<bot-host>:<port>/onebot/v11/ws`。需要 token 时使用 `ONEBOT_V11_ACCESS_TOKEN`，OneBot 端须使用相同凭据。OneBot 正向 WebSocket 使用上游 `ONEBOT_V11_WS_URLS`。QQ WebSocket 需要上游支持的 gateway 配置及对应 Driver mixin；Webhook 示例不能替代该方式。Wind 保留反向连接接管行为，不复制另一套协议连接栈。

## 插件中取得统一消息

```python
from nonebot import on_message
from nonebot.params import Depends
from nonebot.adapters.wind import UnifiedMessage, get_unified_message, send_message

handler = on_message()

@handler.handle()
async def handle(message: UnifiedMessage = Depends(get_unified_message)) -> None:
    await send_message(message, f"收到：{message.text}")
```

`get_unified_message` 要求事件为当前实现支持的消息事件，并且调用位于 Matcher 上下文。若代码运行于 Matcher 尚未创建的规则或预处理阶段，使用 `try_get_unified_message(bot, event, matcher=None)`；不支持的事件返回 `None`。不要假定所有上游通知事件均可转换为 `UnifiedMessage`。

群聊消息为 `GroupMessage`，具有 `group`；私聊消息为 `PrivateMessage`，不含群字段。两者都提供协议、传输、消息文本、原文、发送者、附件、提及和引用信息。原始事件和 Bot 是内部响应上下文，不应在业务代码中自行拼接平台 API。

## 无 Matcher 主动发送

定时任务等没有入站会话时，使用 Bot 和目标平台 ID：

```python
from nonebot.adapters import Bot
from nonebot.adapters.wind import send_proactive_message

async def notify(bot: Bot, group_id: str) -> None:
    receipts = await send_proactive_message(bot, group_id, "任务已完成")
```

`private=True` 表示 `target_id` 是用户标识；默认按群目标处理。平台可能不返回消息 ID，具体看回执的 `message_id`。

## 行为边界

- 两个适配器继承上游的传输、认证、路由与原生 Bot API；统一层只转换明确支持的事件和能力。
- 命令预处理默认折叠首行 2–3 个半角空格，QQ 另外移除一个命令开头的 `/`。开关关闭后，统一消息转换也不会重新执行对应变换。参见[配置](configuration.md)。
- QQ Webhook Bot 提前初始化默认启用，用于在首个回调前建立 Bot 状态；关闭后由正常 Webhook 流程创建。不得同时运行官方同名适配器。
- 日志进入 NoneBot logger。消息归档、命令统计、业务权限和固定 QQ 菜单由宿主项目负责；包不连接 wind-bot 数据库。
- 结束 Matcher 的 `send_message` 默认 `finish=True`；主动发送和群管理不会自动进行业务权限判断。

## 传输与启动说明

OneBot 反向 WebSocket 的最小 `.env.dev` 可以只包含 `HOST=127.0.0.1`、`PORT=8080`、`ONEBOT_V11_ACCESS_TOKEN=替换为你的令牌`；服务端启动后，让 OneBot 实现连接 `/onebot/v11/ws`，并发送真实的 `X-Self-ID` 与认证信息。跨主机部署需按实际入口调整监听地址。

QQ Webhook 使用上游默认 `/qq/webhook` 路由，平台回调 URL 指向应用可访问的 HTTPS 入口并完成平台验证。预初始化不会替代回调地址配置、验签或平台权限申请。上游 QQ WebSocket、OneBot 正向 WebSocket/HTTP 配置继续有效；本次离线验收没有实际连接任何传输方式。

可直接运行单协议或双协议入口：`uv run --no-editable python -m examples.qq`、`examples.onebot`、`examples.both`。这些入口明确调用 `nonebot.load_plugin("examples._echo_plugin")`；自己的工程应替换为自己的插件模块。入口运行后才启动 Driver，QQ 的预初始化可能在此时访问平台；仅导入模块不会启动。

初始化时只注册一次命令预处理器，且仅处理对应 Wind Bot。QQ 的认证、令牌刷新和传输任务归上游管理；关闭时 Wind 额外清理实例的 Bot 注册、限流及 COS 缓存，迟到认证结果不会重新建立连接。业务归档和统计接入见[示例索引](examples.md)。

命名空间和 Adapter 编写方式参考 [NoneBot 编写适配器](https://nonebot.dev/docs/developer/adapter-writing)；上游配置请查阅 [QQ Adapter](https://github.com/nonebot/adapter-qq) 和 [OneBot Adapter](https://github.com/nonebot/adapter-onebot) 对应固定版本。
