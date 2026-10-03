"""Shared test setup for the standalone namespace package."""

from __future__ import annotations

import sys
from pathlib import Path
from nonebot import adapters

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ADAPTERS = ROOT / "nonebot" / "adapters"
if str(ADAPTERS) not in adapters.__path__:
    adapters.__path__.insert(0, str(ADAPTERS))
