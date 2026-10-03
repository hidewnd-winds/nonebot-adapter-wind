# QQ 交互和指令面板

QQ 回调事件和键盘属于 QQ 专有能力，OneBot 不能执行这些回调动作。统一 Document 可以描述按钮，但业务仍须在 QQ 回调处理器中验证操作权限。

## 回调事件

扩展模型 `ProjectQQInteractionCreateEvent` 包含交互用户、会话场景及授权数据。QQ Adapter 在自己的事件解析路径识别此模型，其他事件继续委托官方 QQ Adapter。推荐通过插件按事件类型注册处理器，依照官方 QQ Adapter 的事件分发机制运行。

群交互可用 `create_qq_interaction_group_message(bot, event)` 建立统一群聊上下文。用 `acknowledge_qq_interaction(bot, event, code=0)` 确认平台回调，再用 `send_qq_interaction_response(bot, event, content)` 向原群聊/私聊回复。`send_qq_group_event_response(bot, event, document)` 单独处理真实的 `GroupAddRobotEvent`，不能传入交互回调。调用这些函数必须来自对应的真实 QQ 事件；不要构造伪造的用户或会话标识。精确参数以公开函数签名为准。

`delete_qq_group_message(bot, group_id, message_id)` 为 QQ 群事件结果提供撤回入口，并对已经过期的旧交互结果按接口语义容错。通用 `recall_group_message(message)` 撤回原始入站群消息，失败会继续抛出；这两个撤回接口异常语义不同。

## 指令面板

包提供模型和 API：`QQPanelItem`、`QQPanel`、`QQPanelRecord`、`QQPanelPage`、`list_qq_group_panels(bot)`、`create_qq_group_panel(bot, panel)`、`update_qq_panel(bot, panel_id, panel)`。这些操作不会在包初始化时执行。

读取接口自行检查分页游标，检测重复游标时抛错；非末页缺少 `records` 或 `next_cursor` 也会报错。创建和更新是写操作，不自动重试结果不确定的请求。宿主项目须由明确管理动作触发同步，并先确认现有状态。

示例：

```python
from nonebot.adapters.wind.qq_panel import (
    QQPanel, QQPanelItem, create_qq_group_panel,
)

async def create_help_panel(bot):
    panel = QQPanel(items=(
        QQPanelItem(type="command", name="帮助", desc="查看命令"),
        QQPanelItem(type="link", name="文档", link="https://example.com/docs"),
    ))
    return await create_qq_group_panel(bot, panel)
```

示例函数只有在业务授权且明确调用后才执行。它不会在 import 时创建平台资源。
