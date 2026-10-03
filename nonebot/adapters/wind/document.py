"""平台无关的结构化消息节点、构造接口与基础渲染器。"""

from __future__ import annotations

import unicodedata
import re
from html import escape
from dataclasses import dataclass, field
from typing import Literal

ButtonActionKind = Literal["link", "command", "callback"]
ButtonPermission = Literal["all", "manager", "specified"]
TextStyle = Literal["bold", "italic", "bold_italic", "underline", "strike"]


class Inline:
    """行内消息节点标记。"""


class Block:
    """块级消息节点标记。"""


@dataclass(frozen=True)
class Text(Inline):
    content: str
    literal: bool = False
    """明确作为文字显示，在 Markdown 平台转义语法及提及标签。"""


@dataclass(frozen=True)
class StyledText(Inline):
    style: TextStyle
    children: tuple[Inline, ...]


@dataclass(frozen=True)
class InlineCode(Inline):
    code: str


@dataclass(frozen=True)
class Link(Inline):
    label: tuple[Inline, ...]
    url: str
    show_url_in_plain: bool = True


@dataclass(frozen=True)
class Image(Inline):
    alt: str
    url: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class Mention(Inline):
    """协议无关的用户提及节点。"""

    user_id: str
    """待提及的平台用户标识。"""


@dataclass(frozen=True)
class Heading(Block):
    level: int
    children: tuple[Inline, ...]


@dataclass(frozen=True)
class Paragraph(Block):
    children: tuple[Inline, ...]


@dataclass(frozen=True)
class Quote(Block):
    children: tuple[Inline, ...]


@dataclass(frozen=True)
class Divider(Block):
    pass


@dataclass(frozen=True)
class ListItem:
    children: tuple[Inline, ...]
    nested: tuple[ListBlock, ...] = ()


@dataclass(frozen=True)
class ListBlock(Block):
    ordered: bool
    items: tuple[ListItem, ...]


@dataclass(frozen=True)
class CodeBlock(Block):
    code: str
    language: str = ""


@dataclass(frozen=True)
class Table(Block):
    headers: tuple[tuple[Inline, ...], ...]
    rows: tuple[tuple[tuple[Inline, ...], ...], ...]


@dataclass(frozen=True)
class ButtonModal:
    """支持弹窗的平台可使用的按钮确认文案，不替代服务端权限校验。"""

    content: str | None = None
    confirm_text: str | None = None
    cancel_text: str | None = None


@dataclass(frozen=True)
class ButtonSpec:
    label: str
    action: ButtonActionKind
    data: str
    style: int = 1
    permission: ButtonPermission = "all"
    specified_user_ids: tuple[str, ...] = ()
    visited_label: str | None = None
    enter: bool | None = None
    reply: bool | None = None
    group_id: str | None = None
    modal: ButtonModal | None = None


@dataclass(frozen=True)
class ButtonRow:
    buttons: tuple[ButtonSpec, ...]


@dataclass(frozen=True)
class ButtonTable(Block):
    rows: tuple[ButtonRow, ...]


@dataclass(frozen=True)
class RenderedDocument:
    """渲染后的正文及可选按钮表格。"""

    text: str
    button_table: ButtonTable | None = None


@dataclass
class Document:
    """保持内容插入顺序的可变消息容器。"""

    parts: list[Inline | Block] = field(default_factory=list)

    def append_text(self, content: str) -> None:
        """追加纯文本节点，不自动添加换行。"""
        self.parts.append(Text(content))

    def append_line(self, content: str = "") -> None:
        """追加一行文本；省略内容时追加空行。"""
        self.parts.append(Text(f"{content}\n"))

    def append(self, node: Inline | Block) -> None:
        """按原顺序追加行内节点或块级节点。"""
        self.parts.append(node)


def _inline(value: str | Inline) -> Inline:
    """将字符串包装为文本节点，已有行内节点保持不变。"""
    return Text(value) if isinstance(value, str) else value


def _inlines(values: tuple[str | Inline, ...]) -> tuple[Inline, ...]:
    """按输入顺序将字符串与行内节点转换为行内节点元组。"""
    return tuple(_inline(value) for value in values)


def document(*parts: str | Inline | Block) -> Document:
    """按给定顺序创建文档，将字符串包装为文本节点。"""
    return Document(
        [Text(part) if isinstance(part, str) else part for part in parts]
    )


def text(content: str, *, literal: bool = False) -> Text:
    """创建纯文本节点，保留原始内容。"""
    return Text(content, literal=literal)


def heading(*content: str | Inline, level: int = 1) -> Heading:
    """创建标题节点，并将标题级别限制在一至六级。"""
    if not 1 <= level <= 6:
        raise ValueError("heading level must be between 1 and 6")
    return Heading(level=level, children=_inlines(content))


def paragraph(*content: str | Inline) -> Paragraph:
    """将字符串与行内节点组合为段落，渲染时在末尾换行。"""
    return Paragraph(children=_inlines(content))


def quote(*content: str | Inline) -> Quote:
    """创建引用块，引用样式由对应渲染器处理。"""
    return Quote(children=_inlines(content))


def divider() -> Divider:
    """创建分隔线节点。"""
    return Divider()


def _styled(
    style: TextStyle,
    content: tuple[str | Inline, ...],
) -> StyledText:
    """将行内内容组合为指定样式的文本节点。"""
    return StyledText(style=style, children=_inlines(content))


def bold(*content: str | Inline) -> StyledText:
    """创建加粗文本节点。"""
    return _styled("bold", content)


def italic(*content: str | Inline) -> StyledText:
    """创建斜体文本节点。"""
    return _styled("italic", content)


def bold_italic(*content: str | Inline) -> StyledText:
    """创建同时加粗和倾斜的文本节点。"""
    return _styled("bold_italic", content)


def underline(*content: str | Inline) -> StyledText:
    """创建下划线样式节点，具体效果取决于协议渲染。"""
    return _styled("underline", content)


def strike(*content: str | Inline) -> StyledText:
    """创建删除线文本节点。"""
    return _styled("strike", content)


def inline_code(content: str) -> InlineCode:
    """创建行内代码节点，保留代码原文。"""
    return InlineCode(code=content)


def link(
    label: str | Inline,
    url: str,
    *,
    show_url_in_plain: bool = True,
) -> Link:
    """创建链接节点；show_url_in_plain 控制纯文本渲染时是否附带网址。"""
    return Link(
        label=(_inline(label),),
        url=url,
        show_url_in_plain=show_url_in_plain,
    )


def image(
    alt: str,
    url: str,
    *,
    width: int | None = None,
    height: int | None = None,
) -> Image:
    """创建图片链接节点，可附带像素宽高供 Markdown 渲染使用。"""
    return Image(alt=alt, url=url, width=width, height=height)


def mention(user_id: str | int) -> Mention:
    """创建协议无关的用户提及节点。"""

    return Mention(user_id=str(user_id))


def list_item(*parts: str | Inline | ListBlock) -> ListItem:
    """创建列表项，将行内正文与嵌套列表分别收集并保留各自顺序。"""
    children = tuple(
        _inline(part)
        for part in parts
        if not isinstance(part, ListBlock)
    )
    nested = tuple(
        part
        for part in parts
        if isinstance(part, ListBlock)
    )
    return ListItem(children=children, nested=nested)


def _list(
    ordered: bool,
    items: tuple[str | Inline | ListItem, ...],
) -> ListBlock:
    """创建指定有序性的列表，将普通行内内容包装为列表项。"""
    normalized = tuple(
        item if isinstance(item, ListItem) else list_item(item)
        for item in items
    )
    return ListBlock(ordered=ordered, items=normalized)


def unordered_list(*items: str | Inline | ListItem) -> ListBlock:
    """创建无序列表，支持普通行内内容和嵌套列表项。"""
    return _list(False, items)


def ordered_list(*items: str | Inline | ListItem) -> ListBlock:
    """创建有序列表，序号由渲染器按列表项顺序生成。"""
    return _list(True, items)


def code_block(code: str, *, language: str = "") -> CodeBlock:
    """创建代码块，可指定用于 Markdown 代码围栏的语言标记。"""
    return CodeBlock(code=code, language=language)


def table(
    headers: tuple[str | Inline, ...],
    rows: tuple[tuple[str | Inline, ...], ...],
) -> Table:
    """创建表格，要求表头非空且每行单元格数量与表头一致。"""
    if not headers:
        raise ValueError("table headers are required")
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("table row must match header count")
    return Table(
        headers=tuple((_inline(cell),) for cell in headers),
        rows=tuple(
            tuple((_inline(cell),) for cell in row)
            for row in rows
        ),
    )


def button_row(*buttons: ButtonSpec) -> ButtonRow:
    """创建按钮行，至少包含一个按钮。"""
    if not buttons:
        raise ValueError("button row requires at least one button")
    return ButtonRow(buttons=buttons)


def button_table(*rows: ButtonRow) -> ButtonTable:
    """创建按钮表，至少包含一行按钮。"""
    if not rows:
        raise ValueError("button table requires at least one row")
    return ButtonTable(rows=rows)


def _button(
    label: str,
    action: ButtonActionKind,
    data: str,
    *,
    style: int,
    permission: ButtonPermission,
    specified_user_ids: tuple[str, ...],
    visited_label: str | None,
    enter: bool | None,
    reply: bool | None,
    group_id: str | None = None,
    modal: ButtonModal | None = None,
) -> ButtonSpec:
    """构造按钮规格；指定用户权限时必须提供用户标识，实际权限由调用方及平台校验。"""
    if permission == "specified" and not specified_user_ids:
        raise ValueError("specified button permission requires user ids")
    return ButtonSpec(
        label=label,
        action=action,
        data=data,
        style=style,
        permission=permission,
        specified_user_ids=specified_user_ids,
        visited_label=visited_label,
        enter=enter,
        reply=reply,
        group_id=group_id,
        modal=modal,
    )


def link_button(
    label: str,
    url: str,
    *,
    style: int = 1,
    permission: ButtonPermission = "all",
    specified_user_ids: tuple[str, ...] = (),
    visited_label: str | None = None,
    group_id: str | None = None,
    modal: ButtonModal | None = None,
) -> ButtonSpec:
    """创建跳转链接按钮，按钮数据使用目标网址。"""
    return _button(
        label,
        "link",
        url,
        style=style,
        permission=permission,
        specified_user_ids=specified_user_ids,
        visited_label=visited_label,
        enter=None,
        reply=None,
        group_id=group_id,
        modal=modal,
    )


def command_button(
    label: str,
    command: str,
    *,
    style: int = 1,
    permission: ButtonPermission = "all",
    specified_user_ids: tuple[str, ...] = (),
    enter: bool = True,
    reply: bool = False,
    visited_label: str | None = None,
    group_id: str | None = None,
    modal: ButtonModal | None = None,
) -> ButtonSpec:
    """创建命令按钮；enter 与 reply 分别指定是否自动发送和引用回复，由协议层解释。"""
    return _button(
        label,
        "command",
        command,
        style=style,
        permission=permission,
        specified_user_ids=specified_user_ids,
        visited_label=visited_label,
        enter=enter,
        reply=reply,
        group_id=group_id,
        modal=modal,
    )


def callback_button(
    label: str,
    data: str,
    *,
    style: int = 1,
    permission: ButtonPermission = "all",
    specified_user_ids: tuple[str, ...] = (),
    visited_label: str | None = None,
    group_id: str | None = None,
    modal: ButtonModal | None = None,
) -> ButtonSpec:
    """创建回调按钮，携带交互数据供业务回调处理。"""
    return _button(
        label,
        "callback",
        data,
        style=style,
        permission=permission,
        specified_user_ids=specified_user_ids,
        visited_label=visited_label,
        enter=None,
        reply=None,
        group_id=group_id,
        modal=modal,
    )


_STYLE_MARKERS = {
    "bold": "**",
    "italic": "*",
    "bold_italic": "***",
    "underline": "__",
    "strike": "~~",
}


def _is_markdown_punctuation(char: str) -> bool:
    """根据 Unicode 分类判断字符是否属于标点或符号。"""
    return unicodedata.category(char)[0] in {"P", "S"}


def _needs_markdown_separator(
    previous: Inline,
    previous_text: str,
    current_text: str,
) -> bool:
    """判断样式末尾标点与后续正文之间是否需要空格，避免结束标记解析歧义。"""
    if not isinstance(previous, StyledText) or not current_text:
        return False
    marker = _STYLE_MARKERS[previous.style]
    if len(previous_text) <= len(marker) * 2:
        return False
    previous_char = previous_text[-len(marker) - 1]
    current_char = current_text[0]
    return (
        _is_markdown_punctuation(previous_char)
        and not current_char.isspace()
        and not _is_markdown_punctuation(current_char)
    )


def _render_markdown_inlines(nodes: tuple[Inline, ...]) -> str:
    """为样式结束符补充跨客户端稳定解析所需的最小分隔。"""
    parts: list[str] = []
    previous: Inline | None = None
    previous_text = ""
    for node in nodes:
        current_text = _render_markdown_inline(node)
        if (
            previous is not None
            and _needs_markdown_separator(previous, previous_text, current_text)
        ):
            parts.append(" ")
        parts.append(current_text)
        previous = node
        previous_text = current_text
    return "".join(parts)


def _render_markdown_inline(node: Inline) -> str:
    """将单个行内节点渲染为 Markdown；不支持的节点类型直接报错。"""
    if isinstance(node, Text):
        if node.literal:
            return re.sub(r"([\\`*_{}\[\]()#+.!|~>-])", r"\\\1", escape(node.content, quote=False))
        return node.content
    if isinstance(node, StyledText):
        marker = _STYLE_MARKERS[node.style]
        body = _render_markdown_inlines(node.children)
        return f"{marker}{body}{marker}"
    if isinstance(node, InlineCode):
        return f"`{node.code}`"
    if isinstance(node, Link):
        label = _render_markdown_inlines(node.label)
        return f"[{label}]({node.url})"
    if isinstance(node, Image):
        size = ""
        if node.width is not None:
            size += f" #{node.width}px"
        if node.height is not None:
            size += f" #{node.height}px"
        return f"![{node.alt}{size}]({node.url})"
    if isinstance(node, Mention):
        return f"<@{node.user_id}>"
    raise TypeError(f"unsupported inline node: {type(node).__name__}")


def _render_markdown_list(node: ListBlock, depth: int = 0) -> str:
    """递归渲染 Markdown 列表，每层嵌套增加四个空格缩进。"""
    lines: list[str] = []
    indent = "    " * depth
    for index, item in enumerate(node.items, start=1):
        marker = f"{index}. " if node.ordered else "- "
        body = _render_markdown_inlines(item.children)
        lines.append(f"{indent}{marker}{body}\n")
        for nested in item.nested:
            lines.append(_render_markdown_list(nested, depth + 1))
    return "".join(lines)


def _render_markdown_block(node: Block) -> str:
    """按块类型渲染 Markdown，保留换行、代码围栏和表格结构。"""
    if isinstance(node, Heading):
        body = _render_markdown_inlines(node.children)
        return f"{'#' * node.level} {body}\n"
    if isinstance(node, Paragraph):
        return _render_markdown_inlines(node.children) + "\n"
    if isinstance(node, Quote):
        body = _render_markdown_inlines(node.children)
        return "".join(f"> {line}\n" for line in (body.splitlines() or [""]))
    if isinstance(node, Divider):
        return "***\n"
    if isinstance(node, ListBlock):
        return _render_markdown_list(node)
    if isinstance(node, CodeBlock):
        suffix = "" if node.code.endswith("\n") else "\n"
        return f"```{node.language}\n{node.code}{suffix}```\n"
    if isinstance(node, Table):
        header = "| " + " | ".join(
            _render_markdown_inlines(cell)
            for cell in node.headers
        ) + " |\n"
        separator = "| " + " | ".join("---" for _ in node.headers) + " |\n"
        rows = "".join(
            "| "
            + " | ".join(
                _render_markdown_inlines(cell)
                for cell in row
            )
            + " |\n"
            for row in node.rows
        )
        return header + separator + rows
    raise TypeError(f"unsupported block node: {type(node).__name__}")


def render_markdown(document: Document) -> RenderedDocument:
    """按文档顺序渲染 Markdown 正文，单独返回按钮表；文档最多包含一个按钮表。"""
    parts: list[str] = []
    buttons: ButtonTable | None = None
    previous: Inline | None = None
    previous_text = ""
    for part in document.parts:
        if isinstance(part, ButtonTable):
            if buttons is not None:
                raise ValueError("document supports only one button table")
            buttons = part
        elif isinstance(part, Inline):
            current_text = _render_markdown_inline(part)
            if (
                previous is not None
                and _needs_markdown_separator(
                    previous,
                    previous_text,
                    current_text,
                )
            ):
                parts.append(" ")
            parts.append(current_text)
            previous = part
            previous_text = current_text
        else:
            parts.append(_render_markdown_block(part))
            previous = None
            previous_text = ""
    return RenderedDocument(text="".join(parts), button_table=buttons)


def _render_plain_inline(node: Inline) -> str:
    """将行内节点转换为纯文本，去除样式并保留链接、图片和提及的文字表示。"""
    if isinstance(node, Text):
        return node.content
    if isinstance(node, StyledText):
        return "".join(_render_plain_inline(child) for child in node.children)
    if isinstance(node, InlineCode):
        return node.code
    if isinstance(node, Link):
        label = "".join(_render_plain_inline(child) for child in node.label)
        return f"{label}（{node.url}）" if node.show_url_in_plain else label
    if isinstance(node, Image):
        return f"图片：{node.alt}（{node.url}）"
    if isinstance(node, Mention):
        return f"@{node.user_id}"
    raise TypeError(f"unsupported inline node: {type(node).__name__}")


def _render_plain_list(node: ListBlock, depth: int = 0) -> str:
    """递归渲染纯文本列表，每层嵌套增加两个空格缩进。"""
    lines: list[str] = []
    indent = "  " * depth
    for index, item in enumerate(node.items, start=1):
        marker = f"{index}. " if node.ordered else "· "
        body = "".join(_render_plain_inline(child) for child in item.children)
        lines.append(f"{indent}{marker}{body}\n")
        for nested in item.nested:
            lines.append(_render_plain_list(nested, depth + 1))
    return "".join(lines)


def _render_plain_buttons(node: ButtonTable) -> str:
    """将按钮转换为文字说明；链接和命令显示数据，回调按钮仅显示标签。"""
    lines: list[str] = []
    for row in node.rows:
        for button in row.buttons:
            if button.action in ("link", "command"):
                lines.append(f"{button.label}：{button.data}\n")
            else:
                lines.append(f"{button.label}\n")
    return "".join(lines)


def _render_plain_block(node: Block) -> str:
    """将块级节点转换为纯文本，表格列以制表符分隔。"""
    if isinstance(node, (Heading, Paragraph, Quote)):
        return (
            "".join(_render_plain_inline(child) for child in node.children)
            + "\n"
        )
    if isinstance(node, Divider):
        return "--------------------\n"
    if isinstance(node, ListBlock):
        return _render_plain_list(node)
    if isinstance(node, CodeBlock):
        return node.code + ("" if node.code.endswith("\n") else "\n")
    if isinstance(node, Table):
        header = "\t".join(
            "".join(_render_plain_inline(child) for child in cell)
            for cell in node.headers
        ) + "\n"
        rows = "".join(
            "\t".join(
                "".join(_render_plain_inline(child) for child in cell)
                for cell in row
            )
            + "\n"
            for row in node.rows
        )
        return header + rows
    if isinstance(node, ButtonTable):
        return _render_plain_buttons(node)
    raise TypeError(f"unsupported block node: {type(node).__name__}")


def render_plain_text(document: Document) -> RenderedDocument:
    """按文档顺序渲染纯文本并保留按钮表，按钮同时输出文字说明且最多出现一组。"""
    parts: list[str] = []
    buttons: ButtonTable | None = None
    for part in document.parts:
        if isinstance(part, ButtonTable):
            if buttons is not None:
                raise ValueError("document supports only one button table")
            buttons = part
            parts.append(_render_plain_buttons(part))
        elif isinstance(part, Inline):
            parts.append(_render_plain_inline(part))
        else:
            parts.append(_render_plain_block(part))
    return RenderedDocument(text="".join(parts), button_table=buttons)
