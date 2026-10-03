"""验证真实驱动与 SDK 的初始化边界，不连接平台。"""
import asyncio
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.config import Config as FrameworkConfig, Env
from nonebot.drivers import Request, combine_driver
from nonebot.drivers.fastapi import Driver as FastAPI
from nonebot.drivers.httpx import Mixin as HTTPX
from nonebot.adapters.qq import Bot as QQBot
from nonebot.adapters.qq.config import Config as QQConfig, BotInfo
from nonebot.adapters.qq.models import User, Dispatch
from nonebot.adapters.qq.event import EVENT_CLASSES, EventType, GroupMessageCreateEvent
from nonebot.message import _event_preprocessors

from nonebot.adapters.wind import qq, onebot_v11, inbound
from nonebot.adapters.wind.config import Config, CosSettings


@pytest.fixture
def adapter_factory(monkeypatch):
    def make(config=None, **kwargs):
        driver = combine_driver(FastAPI, HTTPX)(Env(), FrameworkConfig())
        driver._adapters = {}
        driver._bot_connection_hook = set()
        driver._bot_disconnection_hook = set()
        monkeypatch.setattr(qq, 'get_plugin_config', lambda cls: config or Config())
        sdk = importlib.import_module('nonebot.adapters.qq.adapter')
        monkeypatch.setattr(sdk, 'get_plugin_config', lambda cls: QQConfig(
            qq_bots=[BotInfo(id='bot', secret='test-secret', use_websocket=False)],
            qq_verify_webhook=False,
        ))
        return qq.Adapter(driver, **kwargs)
    return make


def test_registration_helpers_reject_existing_protocol():
    for module in (qq, onebot_v11):
        driver = SimpleNamespace(_adapters={module.Adapter.get_name(): object()}, register_adapter=Mock())
        with pytest.raises(RuntimeError):
            module.register(driver)
        driver.register_adapter.assert_not_called()


def test_constructors_register_preprocessor_only_once(adapter_factory):
    adapter_factory()
    adapter_factory()
    assert sum(item.call is inbound.prepare_command_message for item in _event_preprocessors) == 1


def test_publisher_and_cos_conflict_before_sdk_initialization(adapter_factory):
    config = Config(wind_cos=CosSettings(enabled=True, secret_id='test', secret_key='test', region='test', bucket='test'))
    with pytest.raises(ValueError, match='同时启用'):
        adapter_factory(config, image_publisher=object())


def test_extension_parser_is_local_and_unknown_data_type_preserved():
    original = EVENT_CLASSES.copy()
    payload = Dispatch.model_validate({'op': 0, 't': 'INTERACTION_CREATE', 'id': 'event', 'd': {
        'id': 'interaction', 'type': 20, 'version': 1, 'timestamp': '1', 'scene': 'group',
        'chat_type': 1, 'group_openid': 'group', 'group_member_openid': 'member',
        'data': {'type': 2001, 'resolved': {'button_data': 'callback'}}}})
    event = qq.Adapter.payload_to_event(payload)
    assert isinstance(event, qq.ProjectQQInteractionCreateEvent)
    assert event.data.type == 2001 and event.get_user_id() == 'member'
    assert event.get_session_id() == 'group_group_member'
    qq.register_qq_extensions()
    assert EVENT_CLASSES == original


def make_event():
    event = GroupMessageCreateEvent.model_validate({
        'id': 'message', 'timestamp': '2026-10-03T00:00:00+00:00',
        'content': '/hello  world\n  body', 'group_openid': 'group',
        'group_id': 'group', 'author': {'member_openid': 'user', 'id': 'user', 'bot': False, 'member_role': 'member'},
    })
    event.original_message = event.get_message().copy()
    return event


@pytest.mark.parametrize('enabled', [False, True])
def test_same_config_controls_preprocessor_and_conversion(adapter_factory, enabled):
    adapter = adapter_factory(Config(wind_collapse_command_spaces=enabled, wind_qq_strip_command_slash=enabled))
    bot = QQBot(adapter, 'bot', adapter.qq_config.qq_bots[0])
    event = make_event()
    original = event.original_message.copy()
    asyncio.run(inbound.prepare_command_message(bot, event))
    message = qq.QQProtocolAdapter().create_message(bot, event, None)
    expected = 'hello world\n  body' if enabled else '/hello  world\n  body'
    assert message.text == expected
    assert event.original_message == original
    # 无预处理器顺序依赖，直接进入统一转换也遵守同一开关。
    assert qq.QQProtocolAdapter().create_message(bot, make_event(), None).text == expected


def test_official_bot_is_not_modified():
    event = make_event()
    bot = QQBot(SimpleNamespace(), 'bot', BotInfo(id='bot', secret='test'))
    original = event.get_message().copy()
    asyncio.run(inbound.prepare_command_message(bot, event))
    assert event.get_message() == original


def webhook_request():
    return Request('POST', 'https://example.test/qq/webhook', headers={'X-Bot-Appid': 'bot'},
                   content=json.dumps({'op': 0, 't': 'UNKNOWN_TEST_EVENT', 'id': 'event', 'd': {}}))


def test_preinit_and_first_callbacks_share_identity(adapter_factory, monkeypatch):
    adapter = adapter_factory()
    me = AsyncMock(return_value=User(id='bot', username='test'))
    monkeypatch.setattr(QQBot, 'me', me)
    received = Mock()
    monkeypatch.setattr(adapter, 'dispatch_event', received)
    async def run():
        ready, first, second = await asyncio.gather(adapter.initialize_webhook_bots(),
            adapter._handle_http(webhook_request()), adapter._handle_http(webhook_request()))
        assert first.status_code == second.status_code == 200
        assert ready[0] is adapter.bots['bot']
        assert all(call.args[0] is ready[0] for call in received.call_args_list)
        again = await adapter.initialize_webhook_bots()
        assert again[0] is ready[0]
        await adapter.shutdown()
        assert not adapter.bots and not adapter.driver.bots
    asyncio.run(run())
    assert me.await_count == 1


def test_preinit_failure_leaves_webhook_recovery_available(adapter_factory, monkeypatch):
    adapter = adapter_factory()
    me = AsyncMock(side_effect=[RuntimeError('offline'), User(id='bot', username='test')])
    monkeypatch.setattr(QQBot, 'me', me)
    monkeypatch.setattr(adapter, 'dispatch_event', Mock())
    async def run():
        assert await adapter.initialize_webhook_bots() == []
        assert not adapter.bots
        response = await adapter._handle_http(webhook_request())
        assert response.status_code == 200 and 'bot' in adapter.bots
        await adapter.shutdown()
    asyncio.run(run())
    assert me.await_count == 2


def test_shutdown_cancels_tasks_and_clears_owned_state(adapter_factory):
    adapter = adapter_factory()
    async def run():
        task = asyncio.create_task(asyncio.Event().wait())
        adapter.tasks.add(task)
        adapter.group_state_client.slots['bot'] = (asyncio.Lock(), 0)
        adapter.group_join_approver.slots['bot'] = (asyncio.Lock(), 0)
        await adapter.shutdown()
        assert task.cancelled()
        assert not adapter.group_state_client.slots and not adapter.group_join_approver.slots
    asyncio.run(run())


@pytest.mark.parametrize('enabled', [False, True])
def test_member_intent_follows_wind_switch(adapter_factory, enabled):
    adapter = adapter_factory(Config(wind_qq_group_members=enabled))
    assert adapter.qq_config.qq_bots[0].intent.group_members is enabled


def test_shutdown_during_preinit_does_not_reconnect(adapter_factory, monkeypatch):
    adapter = adapter_factory()
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def me(*args, **kwargs):
            entered.set()
            await release.wait()
            return User(id='bot', username='test')
        monkeypatch.setattr(QQBot, 'me', me)
        pending = asyncio.create_task(adapter.initialize_webhook_bots())
        await asyncio.wait_for(entered.wait(), 1)
        await adapter.shutdown()
        release.set()
        assert await asyncio.wait_for(pending, 1) == []
        assert not adapter.bots and not adapter.driver.bots
    asyncio.run(run())


def test_closed_adapter_refuses_new_callbacks(adapter_factory):
    adapter = adapter_factory()
    async def run():
        await adapter.shutdown()
        assert await adapter.initialize_webhook_bots() == []
        response = await adapter._handle_http(webhook_request())
        assert response.status_code == 503
        assert not adapter.bots
    asyncio.run(run())
