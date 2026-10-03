# 配置

Wind 扩展配置模型是 `nonebot.adapters.wind.config.Config`。NoneBot 会将应用配置注入适配器；生产部署按本工程实际配置字段写入 NoneBot 所读的环境变量或配置文件。不要把令牌和密钥写入源码。

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `wind_collapse_command_spaces` | `bool` | `True` | 折叠命令首行词语间连续 2–3 个半角空格；不修改换行后的缩进和空白 |
| `wind_qq_strip_command_slash` | `bool` | `True` | 仅 QQ 命令视图移除开头的一个 `/` |
| `wind_qq_group_members` | `bool` | `True` | 启用 QQ 群成员进退群事件 |
| `wind_qq_initialize_webhook_bots` | `bool` | `True` | 在 QQ Webhook 首次回调前尝试认证并建立 Bot |
| `wind_cos` | `CosSettings` | `CosSettings(enabled=False)` | 内置腾讯 COS 图片发布选项；需安装 `[cos]` 扩展 |

`CosSettings` 字段为 `enabled=False`、`secret_id`、`secret_key`、`region`、`bucket`、可选 `public_base_url` 和默认 `object_prefix="markdown"`。启用时 `secret_id`、`secret_key`、`region`、`bucket` 必填；密钥使用 Pydantic `SecretStr`。`public_base_url` 若提供必须为有效 HTTP(S) URL。QQ 凭据、OneBot 连接等上游选项使用各自官方适配器的配置项。图片发布器通过 QQ Adapter 的 `image_publisher=` 关键字参数注入；自定义发布器与已启用的内置 COS 同时提供会被拒绝，避免选择歧义。

可以直接实例化模型验证默认值（不会连接平台）：

```python
from nonebot.adapters.wind.config import Config, CosSettings

assert Config().wind_qq_initialize_webhook_bots is True
cos = CosSettings(enabled=False)
```

## 命令文本处理

空间折叠仅针对首行命令视图中 2–3 个 ASCII 空格，消息原件和多行正文保持不变。QQ 的斜杠配置仅处理首个开头字符，不会改正文中间的 `/`。停用某项时，事件预处理和统一消息转换必须保持一致。

## QQ 事件及预初始化

`wind_qq_group_members=False` 可停止扩展群成员进退群事件；不会禁用消息事件。Webhook 提前初始化只处理当前 QQ Adapter 的配置 Bot。认证失败应在日志中可见，Webhook 仍可按连接回调流程建立 Bot；此时不应将未认证 Bot 报告为在线。

## COS 和图片发布器

内置 COS 默认为关闭，不需要 COS 环境变量即可使用基础 Document 和平台媒体发送能力。配置图片发布器时请参考[媒体与存储](media-storage.md)。密钥由配置模型保密字段承载，日志和示例不得输出明文。

## 环境变量示例

```dotenv
WIND_COLLAPSE_COMMAND_SPACES=false
WIND_QQ_STRIP_COMMAND_SLASH=false
WIND_QQ_GROUP_MEMBERS=true
WIND_QQ_INITIALIZE_WEBHOOK_BOTS=true
WIND_COS='{"enabled":false}'
```

启用 COS 时在本地配置中把 `WIND_COS` 设置为含 `enabled: true`、`secret_id`、`secret_key`、`region`、`bucket` 的 JSON 对象；可附加 `public_base_url` 和 `object_prefix`。该 JSON 通过 NoneBot 的配置加载器进入 `CosSettings`，不是一组 `COS_*` 独立变量。自定义发布器用 `register_qq(driver, image_publisher=ApplicationImagePublisher())`，参见实际[发布器示例](../examples/image_publisher.py)。
