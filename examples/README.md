# 可运行示例

示例不包含密钥，也不会在 import 时连接或发送消息。开发目录采用 NoneBot 命名空间包布局，uv 默认 editable 安装无法将 Wind 模块合并进已安装的 `nonebot` 命名空间。请先做非 editable 安装：

```bash
uv sync --no-editable
uv run --no-editable python examples/document_nodes.py
```

需要 COS 才执行 `uv sync --no-editable --extra cos`。构建发布包后正常 wheel 安装即可导入。不要对示例添加 `sys.path` 修改。

`onebot.py`、`qq.py`、`both.py` 是 NoneBot 启动入口及消息处理器。按部署所用 Driver 和上游 Adapter 填好 `.env.dev` 后，使用 `python -m examples.onebot`、`python -m examples.qq` 或 `python -m examples.both` 启动。示例入口显式读取 `.env.dev`，并组合 FastAPI、HTTP client 和 WebSocket driver mixin。实际消息发送发生在收到消息之后。

- `document_nodes.py`：纯本地渲染，无平台网络请求。
- `message_flows.py`：Ordered/Rich 图文、引用、回执归档和主动消息。
- `qq_interaction.py`：真实 QQ 交互确认、回复及可选撤回。
- `group_join.py`：申请身份提取、Bot 级审批配额和授权边界。
- `onebot.py`、`qq.py`、`both.py`：不同注册组合及统一消息处理。
- `image_publisher.py`：以 multipart HTTP 上传接口实现自定义发布器；设置 `IMAGE_UPLOAD_URL`（可选 `IMAGE_UPLOAD_TOKEN`）并明确调用才会上传。
- `group_admin.py`、`group_join.py`、`qq_panel.py`：只定义明确调用的业务函数。它们会执行真实平台查询/写入，运行前需自己做权限检查。


- `observability.py`：`JsonlArchive` 保存真实回执；`install_matcher_statistics(archive)` 由启动入口显式调用一次才注册钩子。
- `cos_storage.py`：使用进程环境 `WIND_COS` 的可选 COS 发布示例；只有显式运行或调用才上传。

在安装 Driver 之后，使用 `uv run --no-editable python -m examples.both` 等命令运行入口，避免误用虚拟环境之外的系统 Python。
