import json

import pytest

from onemin_gateway import backends
from onemin_gateway.config import GatewayConfig


class FakeHTTPXResponse:
    def __init__(self, status_code: int, json_data: dict):
        self.status_code = status_code
        self._json = json_data
        self.text = json.dumps(json_data)

    def json(self):
        return self._json


class FakeAsyncClient:
    """Stand-in for httpx.AsyncClient that records the request and returns a
    canned response, so backend tests don't touch the network."""

    def __init__(self, response: FakeHTTPXResponse, captured: dict):
        self._response = response
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, headers=None, json=None):
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["json"] = json
        return self._response


def install_fake_client(monkeypatch, response: FakeHTTPXResponse) -> dict:
    captured: dict = {}

    def factory(*args, **kwargs):
        return FakeAsyncClient(response, captured)

    monkeypatch.setattr(backends.httpx, "AsyncClient", factory)
    return captured


@pytest.fixture
def config():
    cfg = GatewayConfig()
    cfg.oneminai_api_key = "test-key"
    return cfg


class TestCallOneMinAi:
    async def test_request_shape(self, monkeypatch, config):
        response = FakeHTTPXResponse(
            200,
            {"aiRecord": {"aiRecordDetail": {"resultObject": ["hello back"]}}},
        )
        captured = install_fake_client(monkeypatch, response)

        result = await backends.call_oneminai("Human: hi\n\nAssistant:", "grok-4.3", config)

        assert result.text == "hello back"
        assert captured["url"] == "https://api.1min.ai/api/chat-with-ai"
        assert captured["headers"]["API-KEY"] == "test-key"
        assert captured["json"]["type"] == "UNIFY_CHAT_WITH_AI"
        assert captured["json"]["model"] == "grok-4.3"
        assert captured["json"]["promptObject"]["prompt"] == "Human: hi\n\nAssistant:"

    async def test_missing_api_key_raises(self, config):
        config.oneminai_api_key = ""
        with pytest.raises(backends.BackendError):
            await backends.call_oneminai("hi", "grok-4.3", config)

    async def test_error_status_raises(self, monkeypatch, config):
        response = FakeHTTPXResponse(500, {"error": "boom"})
        install_fake_client(monkeypatch, response)
        with pytest.raises(backends.BackendError):
            await backends.call_oneminai("hi", "grok-4.3", config)

    async def test_falls_back_to_content_field(self, monkeypatch, config):
        response = FakeHTTPXResponse(200, {"content": "fallback text"})
        install_fake_client(monkeypatch, response)
        result = await backends.call_oneminai("hi", "grok-4.3", config)
        assert result.text == "fallback text"

    async def test_real_usage_is_extracted(self, monkeypatch, config):
        response = FakeHTTPXResponse(
            200,
            {
                "aiRecord": {
                    "aiRecordDetail": {"resultObject": ["hi"]},
                    "metadata": {"inputToken": 10, "outputToken": 20, "totalToken": 30},
                }
            },
        )
        install_fake_client(monkeypatch, response)
        result = await backends.call_oneminai("hi", "grok-4.3", config)
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20

    async def test_all_zero_usage_is_treated_as_unreported(self, monkeypatch, config):
        response = FakeHTTPXResponse(
            200,
            {
                "aiRecord": {
                    "aiRecordDetail": {"resultObject": ["hi"]},
                    "metadata": {"inputToken": 0, "outputToken": 0, "totalToken": 0},
                }
            },
        )
        install_fake_client(monkeypatch, response)
        result = await backends.call_oneminai("hi", "grok-4.3", config)
        assert result.prompt_tokens is None
        assert result.completion_tokens is None

    async def test_no_metadata_means_no_usage(self, monkeypatch, config):
        response = FakeHTTPXResponse(
            200, {"aiRecord": {"aiRecordDetail": {"resultObject": ["hi"]}}}
        )
        install_fake_client(monkeypatch, response)
        result = await backends.call_oneminai("hi", "grok-4.3", config)
        assert result.prompt_tokens is None


class TestCallRelay:
    async def test_request_and_response_shape(self, monkeypatch, config):
        config.backend = "relay"
        config.relay_base_url = "http://192.168.50.206:5001/v1"
        response = FakeHTTPXResponse(
            200,
            {
                "choices": [{"message": {"content": "relay says hi"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7},
            },
        )
        captured = install_fake_client(monkeypatch, response)

        result = await backends.call_relay("Human: hi\n\nAssistant:", "qwen3-8b", config)

        assert result.text == "relay says hi"
        assert result.prompt_tokens == 5
        assert result.completion_tokens == 7
        assert captured["url"] == "http://192.168.50.206:5001/v1/chat/completions"
        assert captured["json"]["messages"] == [
            {"role": "user", "content": "Human: hi\n\nAssistant:"}
        ]
        assert captured["json"]["stream"] is False

    async def test_missing_usage_returns_none(self, monkeypatch, config):
        response = FakeHTTPXResponse(200, {"choices": [{"message": {"content": "x"}}]})
        install_fake_client(monkeypatch, response)
        result = await backends.call_relay("hi", "qwen3-8b", config)
        assert result.prompt_tokens is None
        assert result.completion_tokens is None

    async def test_error_status_raises(self, monkeypatch, config):
        response = FakeHTTPXResponse(404, {})
        install_fake_client(monkeypatch, response)
        with pytest.raises(backends.BackendError):
            await backends.call_relay("hi", "qwen3-8b", config)


class TestCallBackendDispatch:
    async def test_dispatches_to_oneminai_by_default(self, monkeypatch, config):
        response = FakeHTTPXResponse(
            200, {"aiRecord": {"aiRecordDetail": {"resultObject": ["ok"]}}}
        )
        captured = install_fake_client(monkeypatch, response)
        result = await backends.call_backend("hi", "grok-4.3", config)
        assert result.text == "ok"
        assert "chat-with-ai" in captured["url"]

    async def test_dispatches_to_relay_when_configured(self, monkeypatch, config):
        config.backend = "relay"
        response = FakeHTTPXResponse(200, {"choices": [{"message": {"content": "ok"}}]})
        captured = install_fake_client(monkeypatch, response)
        result = await backends.call_backend("hi", "qwen3-8b", config)
        assert result.text == "ok"
        assert "chat/completions" in captured["url"]
