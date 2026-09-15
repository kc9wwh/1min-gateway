from unittest.mock import AsyncMock

import pytest

from onemin_gateway import app as app_module
from onemin_gateway.backends import BackendResult
from onemin_gateway.cost import UsageTracker
from onemin_gateway.models import ChatCompletionRequest, ChatMessage
from onemin_gateway.tool_queue import ToolCallQueue


@pytest.fixture(autouse=True)
def isolate_app_state(tmp_path, monkeypatch):
    """Prevent tests from touching the real per-user config/usage files on
    disk (`app.py`'s module-level `usage_tracker` is loaded once at import
    time from the real config dir) and from leaking queued tool calls
    between tests (`tool_call_queue` is also a module-level singleton)."""
    monkeypatch.setattr(
        app_module, "usage_tracker", UsageTracker(tmp_path / "usage.json", app_module.config)
    )
    monkeypatch.setattr(app_module, "tool_call_queue", ToolCallQueue())


def multi_call_text(*names: str) -> str:
    return "\n\n".join(
        f'{{"tool_call": {{"name": "{name}", "arguments": {{}}}}}}' for name in names
    )


def make_backend_result(text: str) -> BackendResult:
    return BackendResult(text=text)


def make_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="grok-4.3",
        messages=[ChatMessage(role="user", content="do the thing")],
        tools=[],
    )


class TestRunOneRoundQueuesExtraToolCalls:
    async def test_multiple_tool_calls_are_queued_and_dispensed_without_backend_calls(
        self, monkeypatch
    ):
        backend = AsyncMock(return_value=make_backend_result(multi_call_text("a", "b", "c")))
        monkeypatch.setattr(app_module, "call_backend", backend)

        r1, _ = await app_module._run_one_round(make_request(), "session-1")
        assert backend.await_count == 1
        assert r1.choices[0].message.tool_calls[0].function.name == "a"
        assert r1.choices[0].finish_reason == "tool_calls"

        r2, _ = await app_module._run_one_round(make_request(), "session-1")
        assert backend.await_count == 1  # backend NOT called again
        assert r2.choices[0].message.tool_calls[0].function.name == "b"

        r3, _ = await app_module._run_one_round(make_request(), "session-1")
        assert backend.await_count == 1
        assert r3.choices[0].message.tool_calls[0].function.name == "c"

        backend.return_value = make_backend_result("all done")
        r4, _ = await app_module._run_one_round(make_request(), "session-1")
        assert backend.await_count == 2  # queue empty -- backend called again
        assert r4.choices[0].finish_reason == "stop"

    async def test_single_tool_call_response_does_not_queue_anything(self, monkeypatch):
        backend = AsyncMock(return_value=make_backend_result(multi_call_text("a")))
        monkeypatch.setattr(app_module, "call_backend", backend)

        await app_module._run_one_round(make_request(), "session-1")
        assert app_module.tool_call_queue.pending_count("session-1") == 0

    async def test_queues_are_isolated_per_session(self, monkeypatch):
        backend = AsyncMock(return_value=make_backend_result(multi_call_text("a", "b")))
        monkeypatch.setattr(app_module, "call_backend", backend)

        await app_module._run_one_round(make_request(), "session-1")

        backend.return_value = make_backend_result(multi_call_text("x", "y"))
        r2, _ = await app_module._run_one_round(make_request(), "session-2")
        assert r2.choices[0].message.tool_calls[0].function.name == "x"

        # session-1's queued "b" is still there, unaffected by session-2.
        r3, _ = await app_module._run_one_round(make_request(), "session-1")
        assert r3.choices[0].message.tool_calls[0].function.name == "b"

    async def test_dispensed_queued_call_records_zero_usage_and_no_backend_call(
        self, monkeypatch
    ):
        backend = AsyncMock(return_value=make_backend_result(multi_call_text("a", "b")))
        monkeypatch.setattr(app_module, "call_backend", backend)

        await app_module._run_one_round(make_request(), "session-1")
        before = app_module.usage_tracker.session_snapshot("session-1")

        r2, _ = await app_module._run_one_round(make_request(), "session-1")
        after = app_module.usage_tracker.session_snapshot("session-1")

        assert r2.usage.total_tokens == 0
        assert after == before  # dispensing from the queue didn't record usage
