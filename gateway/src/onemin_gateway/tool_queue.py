"""In-memory, per-session FIFO of tool calls parsed from a single 1min.ai
response but not yet dispensed to OpenCode.

Purely transient: no persistence, no TTL. `pop_next` deletes a session's
entry once its queue drains, so memory is bounded to sessions with a
currently non-empty queue.
"""

from __future__ import annotations

from .protocol import ParsedToolCall


class ToolCallQueue:
    def __init__(self) -> None:
        self._queues: dict[str, list[ParsedToolCall]] = {}

    def extend(self, session_id: str, calls: list[ParsedToolCall]) -> None:
        if not calls:
            return
        self._queues.setdefault(session_id, []).extend(calls)

    def pop_next(self, session_id: str) -> ParsedToolCall | None:
        queue = self._queues.get(session_id)
        if not queue:
            return None
        call = queue.pop(0)
        if not queue:
            del self._queues[session_id]
        return call

    def pending_count(self, session_id: str) -> int:
        return len(self._queues.get(session_id, ()))
