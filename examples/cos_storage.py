"""显式运行时发布一张图片；环境变量 WIND_COS 为完整 COS JSON 配置。"""
from __future__ import annotations

import asyncio
import os
import sys

from nonebot.adapters.wind.config import CosSettings
from nonebot.adapters.wind.storage.cos import TencentCosStorage


async def publish_file(path: str, settings: CosSettings) -> str:
    storage = TencentCosStorage(settings)
    try:
        return await storage.resolve_image_url(path)
    finally:
        storage.reset()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m examples.cos_storage IMAGE_PATH")
    settings = CosSettings.model_validate_json(os.environ["WIND_COS"])
    print(asyncio.run(publish_file(sys.argv[1], settings)))


if __name__ == "__main__":
    main()
