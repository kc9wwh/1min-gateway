"""Token/cost tracking.

1min.ai's `chat-with-ai` endpoint does not return token usage, so token
counts are approximated (character-count heuristic: ~4 chars/token, the same
rough approximation commonly used for English text with GPT-style
tokenizers). If a backend *does* return real usage (e.g. the user's relay,
if it's a genuine OpenAI-compatible server), that is used instead.

Usage is persisted to a JSON file next to the config file so cumulative
stats survive gateway restarts. The gateway itself stays otherwise
stateless between requests.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .config import GatewayConfig

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Rough token estimate when a backend doesn't report real usage."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass
class CallRecord:
    session_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost: float


@dataclass
class SessionStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    calls: int = 0

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
            "calls": self.calls,
        }


class UsageTracker:
    """Thread-safe usage/cost tracker, persisted to a JSON file.

    One process serves all sessions, so a simple in-memory dict guarded by a
    lock is enough; persistence happens synchronously on every recorded call
    (call volume is low relative to human-driven coding sessions, so this
    isn't a bottleneck).
    """

    def __init__(self, path: Path, config: GatewayConfig):
        self._path = path
        self._config = config
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionStats] = {}
        self._cumulative = SessionStats()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for session_id, stats in raw.get("sessions", {}).items():
            self._sessions[session_id] = SessionStats(**stats)
        if "cumulative" in raw:
            self._cumulative = SessionStats(**raw["cumulative"])

    def _persist_locked(self) -> None:
        payload = {
            "sessions": {sid: s.to_dict() for sid, s in self._sessions.items()},
            "cumulative": self._cumulative.to_dict(),
        }
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def compute_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        pricing = self._config.pricing_for(model)
        return (prompt_tokens / 1_000_000) * pricing.input + (
            completion_tokens / 1_000_000
        ) * pricing.output

    def record(
        self,
        session_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> CallRecord:
        cost = self.compute_cost(model, prompt_tokens, completion_tokens)
        with self._lock:
            session = self._sessions.setdefault(session_id, SessionStats())
            for stats in (session, self._cumulative):
                stats.prompt_tokens += prompt_tokens
                stats.completion_tokens += completion_tokens
                stats.total_tokens += prompt_tokens + completion_tokens
                stats.cost += cost
                stats.calls += 1
            self._persist_locked()
        return CallRecord(
            session_id=session_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
        )

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "sessions": {sid: s.to_dict() for sid, s in self._sessions.items()},
                "cumulative": self._cumulative.to_dict(),
            }

    def session_snapshot(self, session_id: str) -> dict:
        with self._lock:
            session = self._sessions.get(session_id, SessionStats())
            return session.to_dict()
