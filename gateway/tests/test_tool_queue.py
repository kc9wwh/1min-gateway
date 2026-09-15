from onemin_gateway.protocol import ParsedToolCall
from onemin_gateway.tool_queue import ToolCallQueue


def make_call(name: str) -> ParsedToolCall:
    return ParsedToolCall(name=name, arguments={})


class TestToolCallQueue:
    def test_pop_next_on_unknown_session_returns_none(self):
        queue = ToolCallQueue()
        assert queue.pop_next("session-1") is None

    def test_pending_count_on_unknown_session_is_zero(self):
        queue = ToolCallQueue()
        assert queue.pending_count("session-1") == 0

    def test_extend_with_empty_list_is_a_noop(self):
        queue = ToolCallQueue()
        queue.extend("session-1", [])
        assert queue.pending_count("session-1") == 0
        assert queue.pop_next("session-1") is None

    def test_fifo_order(self):
        queue = ToolCallQueue()
        queue.extend("session-1", [make_call("a"), make_call("b"), make_call("c")])
        assert queue.pop_next("session-1").name == "a"
        assert queue.pop_next("session-1").name == "b"
        assert queue.pop_next("session-1").name == "c"
        assert queue.pop_next("session-1") is None

    def test_pending_count_reflects_remaining_items(self):
        queue = ToolCallQueue()
        queue.extend("session-1", [make_call("a"), make_call("b")])
        assert queue.pending_count("session-1") == 2
        queue.pop_next("session-1")
        assert queue.pending_count("session-1") == 1

    def test_popping_last_item_removes_the_session_entry(self):
        queue = ToolCallQueue()
        queue.extend("session-1", [make_call("a")])
        queue.pop_next("session-1")
        assert "session-1" not in queue._queues

    def test_queues_are_isolated_per_session(self):
        queue = ToolCallQueue()
        queue.extend("session-1", [make_call("a")])
        queue.extend("session-2", [make_call("b")])
        assert queue.pop_next("session-1").name == "a"
        assert queue.pop_next("session-2").name == "b"

    def test_extend_appends_to_existing_queue(self):
        queue = ToolCallQueue()
        queue.extend("session-1", [make_call("a")])
        queue.extend("session-1", [make_call("b")])
        assert queue.pending_count("session-1") == 2
        assert queue.pop_next("session-1").name == "a"
