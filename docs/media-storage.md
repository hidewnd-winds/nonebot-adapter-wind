# 图片与存储

## 图片类型

- Document 的 `image(alt, url, width=None, height=None)` 表示远程 Markdown 图片，宽高仅用于 QQ Markdown 表达。
- `ImageContent(data, file_name="image.png", alt_text="图片")` 表示二进制图片 bytes 或图片 URL，交由平台 Adapter 转为媒体内容。
- `RichContent(document=..., images=(...), images_first=False, footer=..., single_message=False)` 用于图文组合。
- `OrderedContent(parts=(...))` 用于按原顺序发送文本和图片，不按 Markdown 解释。

本地文件路径不是公网图片 URL。若 Document 中的 Markdown 需要引用本地图片，QQ 发送端会使用已配置发布器上传本地 `image(..., url=本地路径)`；没有发布器时抛错。普通 `ImageContent` 的字符串表示 URL，本地文件应先读为 bytes 再构造，不能把路径当作媒体 URL。

## 图片发布器接口

QQ Adapter 接受可选关键字参数 `image_publisher=`。发布器提供异步方法 `publish_image(data: bytes, file_name: str) -> str`，返回可被 QQ Markdown 访问的公网 HTTP(S) 地址。发布动作只在调用发送 API 需要该图片时发生。

可运行实现见 [`examples/image_publisher.py`](../examples/image_publisher.py)，它向显式配置的 HTTP 上传接口提交 multipart 文件，并检查返回的 `public_url`。接入方法：

```python
from examples.image_publisher import ApplicationImagePublisher
from nonebot.adapters.wind.qq import register as register_qq

# 在已初始化的应用中调用：
def register_with_images(driver):
    register_qq(driver, image_publisher=ApplicationImagePublisher())
```

通过注册辅助函数注入：`register_qq(driver, image_publisher=publisher)`。注册函数会将额外关键字传给 QQ Adapter 构造器。不要在发布器内部吞掉上传异常或返回虚构 URL。

若没有发布器，普通 `ImageContent` 可使用平台原生媒体发送；需要嵌入 Markdown 的本地图片不能伪装成公网链接。若明确配置的发布器上传失败，发送必须暴露失败；`allow_fallback` 控制回复凭据等发送降级，不会把发布器上传失败变成成功的媒体发送。要求 `single_message=True` 但无法合并时必须报错。

## 腾讯 COS 可选实现

安装 `nonebot-adapter-wind[cos]` 后可启用内置 COS。默认关闭，基础消息功能不依赖 COS。COS 子配置属于 `Config.wind_cos` 的 `CosSettings`，含 `enabled`、`secret_id`、`secret_key`、`region`、`bucket`、可选 `public_base_url` 和默认 `object_prefix="markdown"`；启用时必须提供完整配置，密钥由 `SecretStr` 保护。不要在配置说明、日志或 issue 中粘贴 secret。

COS 路径为适配器运行时实例服务，支持按内容复用上传结果并缓存发布地址。对象存储仍须配置适当的访问策略、生命周期和费用告警。使用自定义 `image_publisher` 时不能同时启用内置 COS，以免同一图片有两个不明确的发布后端。

## 入站图片安全

入站图片 URL、MIME、文件名和大小来自平台事件，不能单独作为信任证明。`download_remote_image` 默认限制 20 MiB、30 秒请求超时及最多 5 次重定向，检查声明长度、响应长度和实际流字节数，并识别 PNG/JPEG/GIF/WebP 文件签名。失败返回 `None` 并记录日志；尺寸读取失败返回 `None`，QQ Markdown 图文组合会明确报错。当前工具没有私网地址拦截功能；需要此策略的宿主应在自己的下载入口实施，不能把字节限制当作地址授权。


COS 独立调用示例为 [`examples/cos_storage.py`](../examples/cos_storage.py)。显式运行 `uv run --no-editable --extra cos python -m examples.cos_storage /实际图片路径` 才上传；该独立示例读取进程环境中的 `WIND_COS`，不会自动加载 `.env.dev`。应用使用内置 Adapter COS 时则由 NoneBot 加载配置。缓存归实例拥有、关闭清理；对象存在查询失败或上传失败均抛 `TencentCosStorageError`，不将失败写入成功缓存。
