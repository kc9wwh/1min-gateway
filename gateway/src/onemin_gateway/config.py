"""Configuration loading for the gateway.

Config lives in a cross-platform location so both the gateway (run as a
background service) and the OpenCode plugin (which writes/reads it during
install) can agree on where to find it:

- Windows: ``%APPDATA%\\1min-gateway\\config.json``
- macOS / Linux: ``~/.config/1min-gateway/config.json``

The gateway is otherwise stateless between requests; the only other file it
touches is the usage/cost log (see ``cost.py``), which lives next to the
config file so both survive restarts.

Never hardcode path separators -- everything goes through ``pathlib.Path``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def config_dir() -> Path:
    """Return the cross-platform config directory, creating it if needed."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        root = Path(xdg) if xdg else Path.home() / ".config"
    directory = root / "1min-gateway"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def config_path() -> Path:
    return config_dir() / "config.json"


def usage_path() -> Path:
    return config_dir() / "usage.json"


@dataclass
class ModelPricing:
    """Price per 1M tokens. Units are whatever the user's config uses
    (credits, USD, etc.) -- the gateway is unit-agnostic and just multiplies.
    """

    input: float = 0.0
    output: float = 0.0


@dataclass
class GatewayConfig:
    # Which backend to call: "oneminai" (default) or "relay".
    backend: str = "oneminai"

    # 1min.ai backend.
    oneminai_api_key: str = ""
    oneminai_base_url: str = "https://api.1min.ai"
    oneminai_chat_endpoint: str = "/api/chat-with-ai"

    # User's own OpenAI-compatible relay, used when backend == "relay".
    relay_base_url: str = "http://192.168.50.206:5001/v1"
    relay_api_key: str = ""

    # Network.
    host: str = "127.0.0.1"
    port: int = 8765

    # Per-model pricing, keyed by model id, price per 1,000,000 tokens.
    pricing: dict[str, ModelPricing] = field(default_factory=dict)

    # If a model isn't in `pricing`, fall back to this (defaults to free/0
    # so an unknown model never silently produces a misleading non-zero
    # cost).
    default_pricing: ModelPricing = field(default_factory=ModelPricing)

    # Retry the model once with a corrective prompt if it fails to emit a
    # parseable tool_call/plain-text response.
    tool_call_retry: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> "GatewayConfig":
        path = path or config_path()
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return cfg
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GatewayConfig":
        pricing_raw = raw.get("pricing", {})
        pricing = {
            model: ModelPricing(
                input=float(p.get("input", 0)), output=float(p.get("output", 0))
            )
            for model, p in pricing_raw.items()
        }
        default_pricing_raw = raw.get("default_pricing", {})
        default_pricing = ModelPricing(
            input=float(default_pricing_raw.get("input", 0)),
            output=float(default_pricing_raw.get("output", 0)),
        )
        return cls(
            backend=raw.get("backend", "oneminai"),
            oneminai_api_key=raw.get("oneminai_api_key", ""),
            oneminai_base_url=raw.get("oneminai_base_url", "https://api.1min.ai"),
            oneminai_chat_endpoint=raw.get("oneminai_chat_endpoint", "/api/chat-with-ai"),
            relay_base_url=raw.get("relay_base_url", "http://192.168.50.206:5001/v1"),
            relay_api_key=raw.get("relay_api_key", ""),
            host=raw.get("host", "127.0.0.1"),
            port=int(raw.get("port", 8765)),
            pricing=pricing,
            default_pricing=default_pricing,
            tool_call_retry=bool(raw.get("tool_call_retry", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "oneminai_api_key": self.oneminai_api_key,
            "oneminai_base_url": self.oneminai_base_url,
            "oneminai_chat_endpoint": self.oneminai_chat_endpoint,
            "relay_base_url": self.relay_base_url,
            "relay_api_key": self.relay_api_key,
            "host": self.host,
            "port": self.port,
            "pricing": {
                model: {"input": p.input, "output": p.output}
                for model, p in self.pricing.items()
            },
            "default_pricing": {
                "input": self.default_pricing.input,
                "output": self.default_pricing.output,
            },
            "tool_call_retry": self.tool_call_retry,
        }

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def pricing_for(self, model: str) -> ModelPricing:
        return self.pricing.get(model, self.default_pricing)
