import json

import pytest

from onemin_gateway.config import GatewayConfig, ModelPricing
from onemin_gateway.cost import UsageTracker, estimate_tokens


@pytest.fixture
def config():
    cfg = GatewayConfig()
    cfg.pricing = {
        "grok-4-fast-non-reasoning": ModelPricing(input=600, output=1502),
        "qwen3-8b": ModelPricing(input=0, output=0),
    }
    cfg.default_pricing = ModelPricing(input=0, output=0)
    return cfg


@pytest.fixture
def tracker(tmp_path, config):
    return UsageTracker(tmp_path / "usage.json", config)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string_rounds_up_to_one(self):
        assert estimate_tokens("hi") == 1

    def test_roughly_four_chars_per_token(self):
        text = "a" * 400
        assert estimate_tokens(text) == 100


class TestComputeCost:
    def test_known_model_priced_correctly(self, tracker):
        # 1,000,000 prompt tokens * 600 + 1,000,000 completion tokens * 1502
        cost = tracker.compute_cost("grok-4-fast-non-reasoning", 1_000_000, 1_000_000)
        assert cost == pytest.approx(600 + 1502)

    def test_free_model_is_zero(self, tracker):
        assert tracker.compute_cost("qwen3-8b", 500_000, 500_000) == 0

    def test_unknown_model_falls_back_to_default_pricing(self, tracker):
        assert tracker.compute_cost("some-unknown-model", 1_000_000, 1_000_000) == 0

    def test_unknown_model_uses_nonzero_default(self, tmp_path, config):
        config.default_pricing = ModelPricing(input=100, output=200)
        tracker = UsageTracker(tmp_path / "usage.json", config)
        cost = tracker.compute_cost("mystery-model", 1_000_000, 1_000_000)
        assert cost == pytest.approx(300)


class TestUsageTracker:
    def test_record_updates_session_and_cumulative(self, tracker):
        record = tracker.record("session-a", "grok-4-fast-non-reasoning", 1000, 2000)
        assert record.prompt_tokens == 1000
        assert record.completion_tokens == 2000

        session = tracker.session_snapshot("session-a")
        assert session["prompt_tokens"] == 1000
        assert session["completion_tokens"] == 2000
        assert session["total_tokens"] == 3000
        assert session["calls"] == 1

        cumulative = tracker.snapshot()["cumulative"]
        assert cumulative["total_tokens"] == 3000

    def test_multiple_sessions_are_isolated_but_aggregate(self, tracker):
        tracker.record("session-a", "qwen3-8b", 100, 100)
        tracker.record("session-b", "qwen3-8b", 200, 200)

        assert tracker.session_snapshot("session-a")["total_tokens"] == 200
        assert tracker.session_snapshot("session-b")["total_tokens"] == 400
        assert tracker.snapshot()["cumulative"]["total_tokens"] == 600

    def test_unknown_session_returns_zeroed_stats(self, tracker):
        stats = tracker.session_snapshot("never-seen")
        assert stats["total_tokens"] == 0
        assert stats["calls"] == 0

    def test_persists_to_disk_and_survives_reload(self, tmp_path, config):
        path = tmp_path / "usage.json"
        tracker1 = UsageTracker(path, config)
        tracker1.record("session-a", "qwen3-8b", 50, 50)

        assert path.exists()
        raw = json.loads(path.read_text())
        assert raw["cumulative"]["total_tokens"] == 100

        tracker2 = UsageTracker(path, config)
        assert tracker2.session_snapshot("session-a")["total_tokens"] == 100

    def test_cost_accumulates_across_calls(self, tracker):
        tracker.record("session-a", "grok-4-fast-non-reasoning", 1_000_000, 0)
        tracker.record("session-a", "grok-4-fast-non-reasoning", 1_000_000, 0)
        session = tracker.session_snapshot("session-a")
        assert session["cost"] == pytest.approx(1200)
