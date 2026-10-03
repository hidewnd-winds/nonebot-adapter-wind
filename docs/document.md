# 统一 Document

Document 用结构化节点表达文本和排版，不解析 Markdown 源字符串。发送端按平台渲染：QQ 使用原生 Markdown 和可选键盘；OneBot V11 输出纯文本并保留真实 `at` 消息段。构造器和渲染器由 `nonebot.adapters.wind` 导出。

```python
from nonebot.adapters.wind import (
    bold, document, heading, link, paragraph, unordered_list,
)

content = document(
    heading("查询结果"),
    paragraph("状态：", bold("正常")),
    unordered_list("第一项", "第二项"),
    paragraph(link("项目主页", "https://example.com")),
)
```

## 行内节点

| 构造器 | 参数与用途 | QQ Markdown | OneBot 纯文本 |
|---|---|---|---|
| `text(content, literal=False)` | 文本节点；显式设置 `literal=True` 时转义 Markdown 标点并转义 HTML 字符 | 原样/字面转义 | 文本原样显示 |
| `bold(*content)`、`italic(*content)` | 粗体、斜体 | Markdown 样式 | 去掉样式，保留文字 |
| `bold_italic(*content)` | 粗斜体 | Markdown 样式 | 纯文本 |
| `underline(*content)`、`strike(*content)` | 下划线、删除线 | Markdown 样式 | 纯文本 |
| `inline_code(content)` | 行内代码 | 反引号 | 代码原文 |
| `link(label, url, show_url_in_plain=True)` | 链接；可隐藏纯文本 URL | `[label](url)` | 标签（URL），或仅标签 |
| `image(alt, url, width=None, height=None)` | 远程 Markdown 图片 | QQ 图片语法及尺寸 | 图片说明与 URL |
| `mention(user_id)` | 真实用户标识的提及节点 | QQ 提及语法 | OneBot 真实 `at` 段 |

`text(..., literal=True)` 只表示把该节点内容当字面文字显示，避免其中的 Markdown 结构或提及标签被解释。默认 `literal=False` 允许作者明确写入 Markdown 语法字符。两者都不校验 URL；不可信 URL 仍须在业务边界校验。

## 块级节点

| 构造器 | 行为与限制 |
|---|---|
| `heading(*content, level=1)` | 标题级别 1–6，否则抛 `ValueError` |
| `paragraph(*content)` | 独立段落 |
| `quote(*content)` | 引用块 |
| `divider()` | 分隔线 |
| `unordered_list(*items)`、`ordered_list(*items)` | 可接受字符串、行内节点和 `ListItem` |
| `list_item(*parts)` | 混合行内内容与嵌套列表 |
| `code_block(code, language="")` | 代码块；纯文本降级保留代码 |
| `table(headers, rows)` | 表头必须非空，每行列数必须与表头一致 |

```python
from nonebot.adapters.wind import list_item, ordered_list, unordered_list

content = unordered_list(
    "普通项",
    list_item("有子项", ordered_list("子项一", "子项二")),
)
```

`document(*parts)` 保留节点插入顺序。`Document.append_text(content)` 追加不带换行的文字；`append_line(content="")` 追加带换行的一行，省略内容时追加空行；`append(node)` 追加行内或块级节点。`render_markdown(doc)` 和 `render_plain_text(doc)` 返回 `RenderedDocument(text, button_table)`，便于查看正文渲染；发送 API 通常会自行调用平台渲染器。

为避免 Markdown 客户端把样式结束符与后续正文连成歧义标记，渲染器在前一个样式节点以标点/符号收尾、下一个文本节点以普通非空白字符开头时，会在两节点之间插入一个空格。这只影响渲染后的 Markdown，不改变 Document 节点和 OneBot 纯文本。

## 按钮表

单个 Document 最多包含一个 `button_table()`。每行通过 `button_row()` 构造：

```python
from nonebot.adapters.wind import (
    button_row, button_table, command_button, document, link_button,
    paragraph,
)

content = document(
    paragraph("请选择操作："),
    button_table(button_row(
        command_button("重新查询", "查询", enter=True, reply=False),
        link_button("使用帮助", "https://example.com/help"),
    )),
)
```

支持 `link_button(label, url, ...)`、`command_button(label, command, ...)`、`callback_button(label, data, ...)`。公用选项包括 `style=1`、`permission="all"`（可选值为 `"all"`、`"manager"`、`"specified"`）、`specified_user_ids=()`、`visited_label=None`、`group_id=None` 和 `modal=None`。指定权限必须提供非空 `specified_user_ids`。`ButtonModal` 字段为 `content=None`、`confirm_text=None`、`cancel_text=None`。命令按钮另有 `enter=True`、`reply=False`。OneBot 不执行 QQ 键盘动作：链接和命令显示文字说明，回调仅显示标签。按钮可见权限不能替代处理回调时的服务端权限检查。

## 图像与复合内容

`image()` 是 Document 内的远程 Markdown 图片。二进制或平台媒体附件用 `ImageContent(data, file_name="image.png", alt_text="图片")`；data 为图片 bytes 或 URL。

`RichContent(document=None, images=(), images_first=False, footer=None, single_message=False)` 组合正文、图片和独立尾注。`images_first` 控制正文和图片的顺序，`footer` 始终在正文及图片之后。`single_message=True` 要求平台一次发送全部内容；不能合并时应在发送前抛出异常，不静默拆分。OneBot 与 QQ 的原生消息构造不同，请参照[能力矩阵](capabilities.md)。

`OrderedContent(parts=(...))` 用于保留来自用户原文的文本、图片顺序及空白，不执行 Markdown 格式化。其 `parts` 必须非空且至少包含一个非空白字符串或 `ImageContent`。它没有合并/单消息选项；`single_message` 仅属于 `RichContent`。

## 错误与安全约束

- 空 `RichContent`、空 `OrderedContent`、空按钮行/表或重复按钮表会抛出验证异常。
- 表格列数或标题级别不合法会抛 `ValueError`。
- OneBot 下样式会纯文本降级；不要把重要信息只表达为颜色或按钮回调。
- Mention 节点必须使用平台用户标识；不要把昵称当用户 ID。
- Document 不会为普通文本解析 URL，也不会代替应用校验外部链接。

## 动态追加、样式和完整节点类型

```python
from nonebot.adapters.wind import Document, bold, paragraph, text

report = Document()
report.append_text("任务状态")
report.append_line()  # 不带内容时追加空行；各 append 方法返回 None
report.append(paragraph(bold("结果："), "完成"))
report.append(text("用户输入中的 * 和 <@123>", literal=True))
```

动态追加保留顺序；`append_text` 默认仍是 `literal=False`，不能用它替代对不可信正文的显式字面转义。Markdown 样式末尾为标点/符号且后接普通文字时，渲染器插入必要空格，例如 `bold("结果：")` 后接 `完成` 得到 `**结果：** 完成`；纯文本渲染不会增加这个 Markdown 分隔空格。样式构造器可嵌套行内节点，不接收段落或列表等块级节点。代码节点保留原文，不承担任意 Markdown 源码解析或围栏转义。

节点的实际类型均保留在 `nonebot.adapters.wind.document`：`Text`、`StyledText`、`InlineCode`、`Link`、`Image`、`Mention`、`Heading`、`Paragraph`、`Quote`、`Divider`、`ListItem`、`ListBlock`、`CodeBlock`、`Table`、`ButtonSpec`、`ButtonRow`、`ButtonTable`，以及标记基类 `Inline`、`Block`。推荐使用本页的构造器；未在根 `__all__` 中的类型使用子模块导入，不新增根导出。

## 按钮参数详解

| 参数 | 默认值 | 含义 |
|---|---|---|
| `style` | `1` | 平台按钮样式值，最终展示由 QQ 客户端决定 |
| `permission` | `"all"` | `"all"` 所有人、`"manager"` 管理员、`"specified"` 指定用户 |
| `specified_user_ids` | `()` | 指定用户的平台 ID 元组；指定用户权限下不可为空 |
| `visited_label` | `None` | 访问后的标签；缺省由平台渲染使用原标签 |
| `group_id` | `None` | 限定按钮动作的目标群，按 QQ 字段传递 |
| `enter` | `True`（仅命令按钮） | 是否自动发送命令 |
| `reply` | `False`（仅命令按钮） | 是否按平台机制引用回复 |
| `modal` | `None` | `ButtonModal(content=None, confirm_text=None, cancel_text=None)`，均为可选弹窗文案 |

链接和回调按钮的 `enter/reply` 模型字段为 `None`，构造器不接受这两个参数。按钮表最多一个的约束在渲染阶段检查；各行/表不能为空。不额外发明平台允许的最大按钮数量，平台具体配额和功能开放范围由账号与客户端决定。

## 图片、尾注和单消息的组合

| 内容 | QQ | OneBot V11 |
|---|---|---|
| 普通字符串 | 原生文本；进入 Markdown 响应上下文后按既有规则转换 | 文本 |
| Document 的公网 `image` | Markdown 图片；可传宽高 | 文本中的图片说明/地址，不自动上传附件 |
| Document 的本地 `image` | 发送时调用注入发布器或 COS 获取 URL；缺配置报错 | 按纯文本规则显示节点，不自动发布 |
| 独立 ImageContent | SDK 媒体发送；bytes 或公网 URL | 原生图片消息段 |
| RichContent + 公网 URL/发布器 | 尺寸识别后尽可能合到 Markdown，宽度最大按 960 等比缩放 | 正文/图片/尾注合到有序 Message |
| RichContent + 无发布器的 bytes | 保留媒体组合降级；首图可与无按钮正文、尾注合并，多图可能分条 | 原生图片段，无需公网发布器 |
| `images_first=True` | Markdown 图片置前；原生媒体降级保留其既有组合路径 | 图片段在正文前 |
| `footer` | 在正文与图片之后；能合并则合并，否则独立发送 | 最后追加尾注 |
| `single_message=True` | 严格要求可一次发送；bytes 没有发布器时会提前报错，不尝试普通媒体拆分 | 单个 RichContent 合为一条 Message |

这里的“合到 Markdown”要求图片能取得有效地址与尺寸；上传失败会抛错，不等价于未配置发布器。对于单个 RichContent，会先完成其渲染/合并检查，再发出内容；这不保证前后多个内容组成的发送序列具备事务回滚。`OrderedContent` 本身没有 `single_message` 参数，保持用户原文的文字/图片相对顺序；在 QQ 上可能分条发送。

[`examples/message_flows.py`](../examples/message_flows.py) 接受真实图片 bytes，可演示 `images_first`、`footer` 和 `single_message`。本地图片应先读取二进制传给 `ImageContent`，而不是将路径传作 URL。`prefer_markdown_response` 对请求摘要、结果摘要和图片说明的完整规则见[消息 API](messaging.md)。

主要异常：模型空内容用 `InvalidMessageContentError`，构造器参数错误用 `ValueError`，未知节点用 `TypeError`；QQ 发送边界可能把渲染/平台异常包装为 `MessageSendError` 并保留 `__cause__`。不要要求所有调用层抛出同一个异常类别。
