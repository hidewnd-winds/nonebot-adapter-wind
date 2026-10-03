"""群状态错误分类和限流重试测试，不连接宿主服务或真实网络。"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.adapters.qq import ActionFailed
from nonebot.adapters.qq import Adapter as QQAdapter
from nonebot.adapters.qq import Bot as QQBot
from nonebot.adapters.qq.config import BotInfo, Config as QQConfig
from nonebot.adapters.qq.exception import ApiNotAvailable
from nonebot.drivers import Response
from yarl import URL

from nonebot.adapters.wind.qq import QQGroupStateClient, get_qq_group_state_failure

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init(_env_file=None)


@pytest.fixture
def qq_bot(monkeypatch):
    adapter = object.__new__(QQAdapter)
    adapter.qq_config = QQConfig()
    bot = QQBot(adapter, "test-bot", BotInfo(id="test-bot", secret="test-secret"))
    monkeypatch.setattr(adapter, "get_api_base", lambda: URL("https://example.invalid/"))
    monkeypatch.setattr(bot, "_request", AsyncMock())
    return bot


def error(code: object, *, field: str = "err_code", status: int = 400) -> ActionFailed:
    return ActionFailed(Response(status, content=json.dumps({field: code, "message": "test error"})))


@pytest.mark.parametrize(
    "code, action, is_admin",
    [
        (11281, "retry", None), (11252, "retry", None), (11263, "retry", None), (11242, "retry", None),
        (11293, "skip", False), (40011026, "skip", False), (11255, "skip", False),
        (40011028, "skip", False), (11282, "skip", False), (11264, "skip", None),
        (11274, "skip", None),
        (11253, "stop", None), (11254, "stop", None), (11265, "stop", None),
        (10001, "stop", None), (11251, "stop", None), (11261, "stop", None),
        (11275, "stop", None), (11241, "stop", None), (11243, "stop", None),
        (11262, "stop", None), (11273, "stop", None), (11301, "stop", None),
        (11302, "stop", None), (12002, "error", None), (304023, "error", None),
        (99999, "error", None),
    ],
)
@pytest.mark.parametrize("field", ["code", "err_code"])
def test_error_policy_covers_documented_new_and_legacy_codes(code, action, is_admin, field):
    failure = get_qq_group_state_failure(error(code, field=field))
    assert failure.action == action
    assert failure.code == code
    assert failure.is_admin is is_admin


@pytest.mark.parametrize("status", [401, 404, 405, 429, 500, 504])
def test_http_failures_stop(status):
    failure = get_qq_group_state_failure(ActionFailed(Response(status)))
    assert failure.action == "stop"
    assert failure.is_admin is None


@pytest.mark.parametrize(
    "new_code, legacy_code, expected_action",
    [(11253, 11293, "stop"), (40011026, 11253, "skip"), (40011028, 11242, "skip"), (11242, 11255, "retry")],
)
def test_new_error_code_precedes_legacy_code(new_code, legacy_code, expected_action):
    response = Response(400, content=json.dumps({"err_code": new_code, "code": legacy_code}))
    failure = get_qq_group_state_failure(ActionFailed(response))
    assert failure.action == expected_action
    assert failure.code == new_code


@pytest.mark.parametrize("legacy_code", ["11293", True, None, 99999])
def test_unknown_new_code_does_not_guess_from_invalid_or_unknown_legacy(legacy_code):
    response = Response(400, content=json.dumps({"err_code": 987654, "code": legacy_code}))
    failure = get_qq_group_state_failure(ActionFailed(response))
    assert failure.action == "error"
    assert failure.code == 987654
    assert failure.is_admin is None


@pytest.mark.parametrize("value", ["11293", True])
@pytest.mark.parametrize("legacy", [True, False])
def test_malformed_codes_never_revoke_admin(value, legacy):
    body: dict[str, object] = {"err_code": value}
    if legacy:
        body["code"] = 11293
    failure = get_qq_group_state_failure(ActionFailed(Response(400, content=json.dumps(body))))
    assert failure.action == "error"
    assert failure.is_admin is None


@pytest.mark.parametrize("legacy", [True, False])
def test_null_new_code_uses_legacy_only_when_present(legacy):
    body: dict[str, object] = {"err_code": None}
    if legacy:
        body["code"] = 11293
    failure = get_qq_group_state_failure(ActionFailed(Response(400, content=json.dumps(body))))
    assert failure.action == ("skip" if legacy else "error")
    assert failure.is_admin is (False if legacy else None)


def test_api_unavailable_stops():
    assert get_qq_group_state_failure(ApiNotAvailable()).action == "stop"


@pytest.mark.parametrize("code", [11281, 11252, 11263, 11242])
@pytest.mark.parametrize("recover", [True, False])
def test_query_retries_transient_error_at_most_once_and_obeys_spacing(
    qq_bot, monkeypatch, code, recover,
):
    client = QQGroupStateClient()
    clock = iter(float(index) / 10 for index in range(20))
    sleeps = AsyncMock()
    monkeypatch.setattr("nonebot.adapters.wind.qq.monotonic", lambda: next(clock))
    monkeypatch.setattr("nonebot.adapters.wind.qq.asyncio.sleep", sleeps)
    transient = error(code)
    state = {"allow_proactive_msg": True, "recv_msg_setting": "all"}
    qq_bot._request.side_effect = [transient, state if recover else transient]

    if recover:
        assert asyncio.run(client.query(qq_bot, "group")).allow_proactive_msg is True
    else:
        with pytest.raises(ActionFailed) as caught:
            asyncio.run(client.query(qq_bot, "group"))
        assert caught.value is transient
    assert qq_bot._request.await_count == 2
    sleeps.assert_awaited_once()
    assert 0 < sleeps.await_args.args[0] <= 2.1


@pytest.mark.parametrize("code, status", [(11253, 400), (11293, 400), (40011028, 400), (11242, 401), (99999, 429), (99999, 500)])
def test_query_does_not_retry_permanent_or_http_failures(qq_bot, monkeypatch, code, status):
    client = QQGroupStateClient()
    sleeps = AsyncMock()
    monkeypatch.setattr("nonebot.adapters.wind.qq.asyncio.sleep", sleeps)
    qq_bot._request.side_effect = ActionFailed(
        Response(status, content=json.dumps({"err_code": code}))
    )
    with pytest.raises(ActionFailed):
        asyncio.run(client.query(qq_bot, "group"))
    qq_bot._request.assert_awaited_once()
    sleeps.assert_not_awaited()


def test_query_does_not_retry_cancellation(qq_bot, monkeypatch):
    client = QQGroupStateClient()
    sleeps = AsyncMock()
    monkeypatch.setattr("nonebot.adapters.wind.qq.asyncio.sleep", sleeps)
    qq_bot._request.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.query(qq_bot, "group"))
    qq_bot._request.assert_awaited_once()
    sleeps.assert_not_awaited()
