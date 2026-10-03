"""显式接入 JSONL 回执归档和 Matcher 统计；导入时不读写文件或注册钩子。"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from time import monotonic

from nonebot.adapters import Bot, Event
from nonebot.message import run_postprocessor, run_preprocessor
from nonebot.typing import T_State
from nonebot.adapters.wind import MessageReceipt, UnifiedMessage


class JsonlArchive:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def append(self, record: dict[str, object]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write, record)

    def _write(self, record: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def save_outbound(
        self, message: UnifiedMessage, receipts: Sequence[MessageReceipt]
    ) -> None:
        await self.append({
            "kind": "outbound", "protocol": message.protocol,
            "scene": message.scene, "source_message_id": message.message_id,
            "message_ids": [receipt.message_id for receipt in receipts],
        })


def install_matcher_statistics(archive: JsonlArchive) -> None:
    """由应用启动入口显式调用一次；每个 Matcher 的临时状态存于其 state。"""
    @run_preprocessor
    async def start(state: T_State) -> None:
        state["wind_example_started_at"] = monotonic()

    @run_postprocessor
    async def complete(bot: Bot, event: Event, state: T_State, exception: Exception | None) -> None:
        started = state.get("wind_example_started_at")
        if started is None:
            return
        await archive.append({
            "kind": "matcher", "bot_id": bot.self_id,
            "event_type": event.get_type(), "elapsed_seconds": monotonic() - started,
            "completed_without_error": exception is None,
            "exception_type": type(exception).__name__ if exception else None,
        })
