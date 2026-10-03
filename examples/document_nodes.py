"""本地渲染统一文档，不启动 NoneBot，也不连接平台。"""

from io import BytesIO
from PIL import Image

from nonebot.adapters.wind import (
    ButtonModal,
    ImageContent,
    RichContent,
    bold,
    button_row,
    button_table,
    callback_button,
    code_block,
    command_button,
    document,
    heading,
    link,
    list_item,
    mention,
    ordered_list,
    paragraph,
    render_markdown,
    render_plain_text,
    table,
    text,
    unordered_list,
)


def main() -> None:
    report = document(
        heading("查询结果"),
        paragraph("状态：", bold("正常"), "；用户输入：", text("**按原文显示**", literal=True)),
        paragraph("负责人：", mention("123456789")),
        paragraph(link("NoneBot 文档", "https://nonebot.dev/")),
        unordered_list(
            "普通步骤",
            list_item("子步骤", ordered_list("第一项", "第二项")),
        ),
        table(("服务", "状态"), (("QQ", "已连接"), ("OneBot", "等待连接"))),
        code_block("print('ready')", language="python"),
        button_table(
            button_row(
                command_button("重试", "/查询", enter=True, reply=True),
                callback_button("查看详情", "detail", modal=ButtonModal(content="确认查看？")),
            )
        ),
    )
    print("=== Markdown (QQ) ===")
    print(render_markdown(report).text)
    print("=== 纯文本 (OneBot 降级) ===")
    print(render_plain_text(report).text)

    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    image_report = RichContent(
        document=document(paragraph("图片说明")),
        images=(ImageContent("https://example.com/result.png", "result.png"),),
        images_first=True,
        footer=document(paragraph("图下注释")),
    )
    print("=== RichContent 本地结构 ===")
    print(image_report)


if __name__ == "__main__":
    main()
