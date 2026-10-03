from __future__ import annotations

import pytest

from nonebot.adapters.wind.document import (
    ButtonModal,
    bold,
    callback_button,
    button_row,
    button_table,
    command_button,
    document,
    heading,
    link_button,
    list_item,
    ordered_list,
    paragraph,
    render_markdown,
    render_plain_text,
    table,
    text,
    unordered_list,
)


def test_document_renders_structured_blocks_and_nested_lists_in_order():
    value = document(
        heading("运行状态", level=2),
        paragraph("服务 ", text("运行中", literal=True)),
        unordered_list(
            list_item("第一项", ordered_list("子项一", "子项二")),
            "第二项",
        ),
        table(("名称", "状态"), (("worker", "ready"),)),
    )

    markdown = render_markdown(value).text
    assert markdown.startswith("## 运行状态\n服务 ")
    assert "- 第一项\n    1. 子项一\n    2. 子项二\n- 第二项\n" in markdown
    assert "| 名称 | 状态 |\n| --- | --- |\n| worker | ready |" in markdown
    assert "运行中" in render_plain_text(value).text


def test_literal_text_escapes_markdown_and_html_sensitive_characters():
    rendered = render_markdown(document(text("<@123> *原文*", literal=True))).text
    assert rendered == "&lt;@123&gt; \\*原文\\*"


def test_styled_punctuation_gets_safe_separator():
    rendered = render_markdown(document(paragraph("结果：", text("通过")))).text
    assert rendered == "结果：通过\n"
    styled = render_markdown(document(paragraph(bold("结果："), "通过"))).text
    assert styled == "**结果：** 通过\n"


def test_button_table_is_returned_separately_and_only_once():
    table_node = button_table(button_row(
        command_button("确认", "/confirm", reply=True),
        callback_button("取消", "cancel", modal=ButtonModal(content="确定取消？")),
    ))
    rendered = render_markdown(document(paragraph("请选择"), table_node))
    assert rendered.text == "请选择\n"
    assert rendered.button_table == table_node
    with pytest.raises(ValueError, match="only one button table"):
        render_markdown(document(table_node, table_node))


def test_document_rejects_invalid_table_and_empty_button_shapes():
    with pytest.raises(ValueError, match="match header count"):
        table(("a", "b"), (("only one",),))
    with pytest.raises(ValueError, match="at least one"):
        button_row()
    with pytest.raises(ValueError, match="at least one"):
        button_table()
    with pytest.raises(ValueError, match="specified button permission"):
        link_button("仅限指定用户", "https://example.test", permission="specified")
    with pytest.raises(ValueError, match="between 1 and 6"):
        heading("invalid", level=7)


def test_qq_nested_document_resolution_preserves_image_publish_order(monkeypatch):
    import asyncio
    from nonebot.adapters.wind import image
    from nonebot.adapters.wind import qq

    published = []
    publisher = object()

    async def resolve(value, actual_publisher):
        assert actual_publisher is publisher
        published.append(value)
        return "https://images.example.test/" + value

    monkeypatch.setattr(qq, "resolve_image_url", resolve)
    source = document(
        table((image("head", "header.png"), "title"), (
            (image("first", "first.png"), "1"),
            ("2", image("second", "second.png")),
        )),
        unordered_list(
            list_item(image("top", "top.png"), ordered_list(
                image("nested", "nested.png"),
            )),
            image("last", "last.png"),
        ),
    )

    async def render():
        return [await qq._resolve_markdown_node(node, publisher) for node in source.parts]

    resolved = document(*asyncio.run(render()))
    assert published == ["header.png", "first.png", "second.png", "top.png", "nested.png", "last.png"]
    expected = render_markdown(source).text
    for name in published:
        expected = expected.replace("(" + name + ")", "(https://images.example.test/" + name + ")")
    assert render_markdown(resolved).text == expected
    # 转换返回新节点，不能改写用户复用的原 Document。
    assert "https://images.example.test/" not in render_markdown(source).text
