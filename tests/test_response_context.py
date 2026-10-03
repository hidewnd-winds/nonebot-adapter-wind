from __future__ import annotations

import asyncio

from nonebot.adapters.wind.api import (
    _format_markdown_contents,
    _markdown_response,
    _receipt_observer,
    observe_message_receipts,
    prefer_markdown_response,
)
from nonebot.adapters.wind.models import ImageContent, OrderedContent, RichContent


def test_response_contexts_are_isolated_between_concurrent_tasks():
    async def request(label: str) -> tuple[str | None, bool]:
        observed = []
        with prefer_markdown_response(label, result_summary=f"result:{label}"):
            with observe_message_receipts(observed.append):
                await asyncio.sleep(0)
                presentation = _markdown_response.get()
                receipt_observer = _receipt_observer.get()
                return (
                    presentation.request_summary if presentation else None,
                    receipt_observer is not None,
                )

    async def run():
        return await asyncio.gather(request("first"), request("second"))

    assert asyncio.run(run()) == [("first", True), ("second", True)]
    assert _markdown_response.get() is None
    assert _receipt_observer.get() is None


def test_markdown_context_formats_plain_text_and_image_captions():
    with prefer_markdown_response("request", result_summary="result"):
        presentation = _markdown_response.get()
        assert presentation is not None
        result = _format_markdown_contents(
            ("hello", ImageContent(data="https://example.test/image.png")),
            presentation,
            markdown=True,
        )
    assert len(result) == 2
    assert isinstance(result[1], RichContent)
    assert result[1].images[0].data == "https://example.test/image.png"


def test_ordered_content_preserves_text_and_image_positions():
    first = ImageContent(data=b"first", file_name="first.png")
    second = ImageContent(data=b"second", file_name="second.png")
    content = OrderedContent(("before  ", first, "\nafter", second))
    assert content.parts == ("before  ", first, "\nafter", second)
