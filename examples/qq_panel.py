"""显式创建 QQ 全局群聊帮助面板；导入不会写入平台。"""

from nonebot.adapters.qq import Bot
from nonebot.adapters.wind.qq_panel import (
    QQPanel,
    QQPanelItem,
    create_qq_group_panel,
    list_qq_group_panels,
    update_qq_panel,
)


async def create_panel_after_operator_action(bot: Bot) -> str:
    # 写操作必须由已经完成权限检查的管理操作显式调用。
    panel = QQPanel(
        items=(
            QQPanelItem(type="command", name="帮助", desc="显示可用命令"),
            QQPanelItem(type="link", name="项目文档", link="https://nonebot.dev/"),
        ),
        remark="由应用管理员显式创建",
    )
    return await create_qq_group_panel(bot, panel)


async def read_panels(bot: Bot):
    return await list_qq_group_panels(bot)


async def update_panel_after_operator_action(bot: Bot, panel_id: str, panel: QQPanel) -> int:
    # 传入查询到的真实面板 ID；由已授权管理操作显式触发，不自动重试。
    return await update_qq_panel(bot, panel_id, panel)
