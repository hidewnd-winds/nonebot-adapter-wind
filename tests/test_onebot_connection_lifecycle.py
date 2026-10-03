"""Reverse-WebSocket ownership checks without starting a real driver or network."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Bot
from nonebot.exception import WebSocketClosed
from nonebot.internal.driver.abstract import Driver

from nonebot.adapters.wind import onebot_v11


try:
    nonebot.get_driver()
except ValueError:
    nonebot.init(_env_file=None)


class Socket:
    def __init__(self, headers=None):
        self.request = SimpleNamespace(headers={"x-self-id": "123", **(headers or {})})
        self.accept = AsyncMock()
        self.closed = asyncio.Event()
        self.receiving = asyncio.Event()
        self.close = AsyncMock(side_effect=self.finish)

    async def finish(self, *_args):
        self.closed.set()

    async def receive(self):
        self.receiving.set()
        await self.closed.wait()
        raise WebSocketClosed(1000)


def make_adapter():
    instance = object.__new__(onebot_v11.ProjectOneBotV11Adapter)
    driver = SimpleNamespace(_bots={}, _bot_connection_hook=(), _bot_disconnection_hook=())
    driver._bot_connect = lambda bot: Driver._bot_connect(driver, bot)
    driver._bot_disconnect = lambda bot: Driver._bot_disconnect(driver, bot)
    instance.driver = driver
    instance.bots = {}
    instance.connections = {}
    instance.tasks = set()
    instance._check_access_token = Mock(return_value=None)
    instance.json_to_event = Mock(return_value=None)
    return instance


def test_replacement_keeps_new_owner_when_old_connection_finishes():
    async def run():
        instance = make_adapter()
        old_ws, new_ws = Socket(), Socket()
        old_task = asyncio.create_task(instance._handle_ws(old_ws))
        await old_ws.receiving.wait()
        old_bot = instance.bots["123"]

        new_task = asyncio.create_task(instance._handle_ws(new_ws))
        await new_ws.receiving.wait()
        await old_task

        new_bot = instance.bots["123"]
        assert new_bot is not old_bot
        assert instance.driver._bots["123"] is new_bot
        assert instance.connections["123"] is new_ws

        await new_ws.close()
        await new_task
        assert not instance.bots
        assert not instance.connections
        assert not instance.driver._bots

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["auth", "accept", "transport"])
def test_rejected_connection_does_not_displace_existing_owner(mode):
    async def run():
        instance = make_adapter()
        old_ws, new_ws = Socket(), Socket()
        old_bot = (
            Bot(instance, "123")
            if mode == "transport"
            else onebot_v11._ReverseWebSocketBot(instance, "123")
        )
        instance.bot_connect(old_bot)
        instance.connections["123"] = old_ws

        if mode == "auth":
            instance._check_access_token.return_value = SimpleNamespace(content="Invalid token")
        elif mode == "accept":
            new_ws.accept.side_effect = RuntimeError("Handshake failed")

        if mode == "accept":
            with pytest.raises(RuntimeError, match="Handshake failed"):
                await instance._handle_ws(new_ws)
        else:
            await instance._handle_ws(new_ws)

        assert instance.bots["123"] is old_bot
        assert instance.driver._bots["123"] is old_bot
        assert instance.connections["123"] is old_ws
        old_ws.close.assert_not_awaited()
        if mode == "auth":
            new_ws.accept.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("failure", [RuntimeError("close failed"), TimeoutError("close timed out")])
def test_failure_closing_replaced_socket_does_not_break_new_connection(failure):
    async def run():
        instance = make_adapter()
        old_ws, new_ws = Socket(), Socket()
        old_ws.close.side_effect = failure
        old_bot = onebot_v11._ReverseWebSocketBot(instance, "123")
        instance.bot_connect(old_bot)
        instance.connections["123"] = old_ws

        task = asyncio.create_task(instance._handle_ws(new_ws))
        await new_ws.receiving.wait()
        assert instance.bots["123"] is not old_bot
        await new_ws.close()
        await task

    asyncio.run(run())
