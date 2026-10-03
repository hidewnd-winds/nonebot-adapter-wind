# nonebot-adapter-wind

为 [NoneBot2](https://nonebot.dev/) 提供 QQ 与 OneBot V11 的统一消息能力扩展。项目复用官方适配器的连接、认证和原生 Bot API，并在其上提供统一消息上下文、结构化 Document、发送回执、群管理接口及 QQ 扩展能力。

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

## 注册适配器

根据部署协议注册一个或两个适配器。推荐使用包提供的注册函数：它会在同名官方适配器已经注册时明确报错，避免 NoneBot 将重复名称静默忽略。

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

同一进程不能同时注册 Wind 扩展和相同协议的官方原版适配器。直接调用 `driver.register_adapter(...)` 时，NoneBot 可能静默忽略重复名称；使用上面的注册函数可获得明确错误。

## 最小统一消息插件

```python
from nonebot import on_message
from nonebot.params import Depends
from nonebot.adapters.wind import (
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
    await send_message(
        message,
        document(heading("收到消息"), paragraph(message.text)),
    )
```

完整安装、配置、Document、消息发送、群管理、图片和 QQ 交互说明见 [`docs/README.md`](docs/README.md)。可运行示例从 [`examples/README.md`](examples/README.md) 开始。

## 支持范围

- 声明 Python `>=3.10,<4`；本地已验证 3.12，3.10/3.14 的 CI 矩阵已配置但尚未执行。依赖基线为 NoneBot2 2.5.x、QQ Adapter 1.7.3、OneBot Adapter 2.4.6。
- 统一消息、Document 和通用 API 在两种协议间共享；平台专有能力会明确标出。
- QQ Webhook Bot 预初始化默认启用；可通过 `Config.wind_qq_initialize_webhook_bots` 关闭。
- 不包含 wind-bot 的数据库、业务插件、统计或消息归档服务，也不会自动创建 QQ 指令面板。
- 官方事件仍由官方 Adapter 解析；统一 API 只接受扩展已明确支持的消息事件。请查阅[能力矩阵](docs/capabilities.md)。

## 许可

本项目按 MIT License 发布，依赖的 NoneBot QQ 和 OneBot 适配器各自保留其上游许可，见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
