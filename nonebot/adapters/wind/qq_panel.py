"""QQ 指令面板接口；复用 SDK 的请求、鉴权及 Token 刷新。"""

from __future__ import annotations

from typing import Literal

from nonebot.adapters.qq import Bot
from nonebot.drivers import Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self


class QQPanelItem(BaseModel):
    """平台面板元素，保留影响展示与点击行为的字段。"""

    model_config = ConfigDict(frozen=True)

    type: Literal["command", "link"]
    name: str
    desc: str = ""
    only_admin: bool = False
    link: str | None = None


class QQPanel(BaseModel):
    """可编辑内容；平台版本号不参与内容比较与写入。"""

    model_config = ConfigDict(frozen=True)

    items: tuple[QQPanelItem, ...] = ()
    remark: str = ""


class QQPanelRecord(BaseModel):
    """平台面板身份与作用范围。"""

    panel_id: str = Field(min_length=1)
    scope: str
    target_type: str
    panel: QQPanel


class QQPanelPage(BaseModel):
    """末页允许平台省略空字段，非末页仍要求完整分页信息。"""

    records: list[QQPanelRecord] = Field(default_factory=list)
    next_cursor: str = ""
    is_end: bool

    @model_validator(mode="after")
    def validate_page_fields(self) -> Self:
        # QQ 空列表实测只返回 is_end=true；不能把非末页缺字段也当作空列表。
        if not self.is_end and not {"records", "next_cursor"} <= self.model_fields_set:
            raise ValueError("QQ 指令面板非末页缺少 records 或 next_cursor")
        return self


class QQPanelCreated(BaseModel):
    """创建成功的面板标识。"""

    panel_id: str = Field(min_length=1)


class QQPanelUpdated(BaseModel):
    """更新成功后的平台版本号。"""

    version: int


async def list_qq_group_panels(bot: Bot) -> list[QQPanelRecord]:
    """读取完整群聊面板列表，分页异常时停止，避免误创建。"""
    records: list[QQPanelRecord] = []
    cursor = ""
    seen_cursors: set[str] = set()
    while True:
        params: dict[str, str | int] = {"scope": "group", "limit": 50}
        if cursor:
            params["cursor"] = cursor
        request = Request(
            "GET", bot.adapter.get_api_base().joinpath("v2", "panels"),
            params=params, timeout=15,
        )
        page = QQPanelPage.model_validate(await bot._request(request))
        records.extend(page.records)
        if page.is_end or not page.next_cursor:
            return records
        if page.next_cursor in seen_cursors:
            raise ValueError("QQ 指令面板分页游标重复")
        cursor = page.next_cursor
        seen_cursors.add(cursor)


async def create_qq_group_panel(bot: Bot, panel: QQPanel) -> str:
    """创建群聊全局面板；不重试结果不确定的写入。"""
    request = Request(
        "POST", bot.adapter.get_api_base().joinpath("v2", "panels"),
        json={"scope": "group", "target_type": "all",
              "panel": panel.model_dump(mode="json", exclude_none=True)},
        timeout=15,
    )
    return QQPanelCreated.model_validate(await bot._request(request)).panel_id


async def update_qq_panel(bot: Bot, panel_id: str, panel: QQPanel) -> int:
    """更新已识别的面板内容，不修改关联对象。"""
    request = Request(
        "PUT", bot.adapter.get_api_base().joinpath("v2", "panels", panel_id),
        json={"panel": panel.model_dump(mode="json", exclude_none=True)},
        timeout=15,
    )
    return QQPanelUpdated.model_validate(await bot._request(request)).version
