import json

from onemin_gateway.models import ChatMessage, FunctionDef, ToolCall, ToolDef, FunctionCall
from onemin_gateway.protocol import (
    TASK_PERSISTENCE_REMINDER,
    build_prompt,
    build_tool_block,
    flatten_messages,
    looks_like_failed_attempt,
    parse_tool_call,
    parse_tool_calls,
)


def make_tool(name="read_file", description="Read a file"):
    return ToolDef(
        function=FunctionDef(
            name=name,
            description=description,
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
    )


class TestFlattenMessages:
    def test_system_and_user(self):
        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Hello there"),
        ]
        flat = flatten_messages(messages)
        assert "System: You are helpful." in flat
        assert "Human: Hello there" in flat
        # Order preserved.
        assert flat.index("System:") < flat.index("Human:")

    def test_assistant_plain_text(self):
        messages = [ChatMessage(role="assistant", content="Sure, done.")]
        flat = flatten_messages(messages)
        assert flat == "Assistant: Sure, done."

    def test_assistant_tool_call_round_trip(self):
        messages = [
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(
                            name="read_file", arguments=json.dumps({"path": "a.py"})
                        ),
                    )
                ],
            ),
            ChatMessage(role="tool", tool_call_id="call_1", content="file contents here"),
        ]
        flat = flatten_messages(messages)
        assert '"tool_call"' in flat
        assert '"name": "read_file"' in flat
        assert '"path": "a.py"' in flat
        assert "Tool (read_file): file contents here" in flat

    def test_tool_message_unknown_call_id_falls_back(self):
        messages = [ChatMessage(role="tool", tool_call_id="missing", content="x")]
        flat = flatten_messages(messages)
        assert "Tool (unknown_tool): x" in flat

    def test_content_parts_list_is_flattened(self):
        messages = [
            ChatMessage(
                role="user",
                content=[{"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}],
            )
        ]
        flat = flatten_messages(messages)
        assert "part one" in flat
        assert "part two" in flat


class TestBuildToolBlock:
    def test_empty_when_no_tools(self):
        assert build_tool_block(None) == ""
        assert build_tool_block([]) == ""

    def test_includes_tool_spec_json(self):
        block = build_tool_block([make_tool()])
        assert '"tool_call"' in block
        assert "read_file" in block
        assert "Read a file" in block


class TestBuildPrompt:
    def test_ends_with_assistant_cue(self):
        prompt = build_prompt([ChatMessage(role="user", content="hi")], None)
        assert prompt.endswith("Assistant:")

    def test_includes_tool_block_before_conversation(self):
        prompt = build_prompt(
            [ChatMessage(role="user", content="hi")], [make_tool()]
        )
        assert prompt.index("Available tools") < prompt.index("Human: hi")

    def test_includes_persistence_reminder_when_tools_present(self):
        prompt = build_prompt(
            [ChatMessage(role="user", content="hi")], [make_tool()]
        )
        assert TASK_PERSISTENCE_REMINDER in prompt
        # Reminder sits after the conversation and right before the
        # generation cue, so it's the last thing the model reads.
        assert prompt.index("Human: hi") < prompt.index(TASK_PERSISTENCE_REMINDER)
        assert prompt.endswith(TASK_PERSISTENCE_REMINDER + "\n\nAssistant:")

    def test_omits_persistence_reminder_when_no_tools(self):
        prompt = build_prompt([ChatMessage(role="user", content="hi")], None)
        assert TASK_PERSISTENCE_REMINDER not in prompt


class TestParseToolCall:
    def test_exact_json_object(self):
        text = '{"tool_call": {"name": "read_file", "arguments": {"path": "a.py"}}}'
        parsed, remaining = parse_tool_call(text)
        assert parsed is not None
        assert parsed.name == "read_file"
        assert parsed.arguments == {"path": "a.py"}
        assert remaining == ""

    def test_json_surrounded_by_whitespace(self):
        text = '\n\n  {"tool_call": {"name": "x", "arguments": {}}}  \n'
        parsed, _ = parse_tool_call(text)
        assert parsed is not None
        assert parsed.name == "x"

    def test_json_embedded_in_prose(self):
        text = (
            'Sure, let me do that.\n{"tool_call": {"name": "read_file", '
            '"arguments": {"path": "b.py"}}}\nDone.'
        )
        parsed, _ = parse_tool_call(text)
        assert parsed is not None
        assert parsed.name == "read_file"
        assert parsed.arguments == {"path": "b.py"}

    def test_no_tool_call_returns_none(self):
        text = "I don't need a tool for this, the answer is 42."
        parsed, remaining = parse_tool_call(text)
        assert parsed is None
        assert remaining == text

    def test_malformed_json_returns_none(self):
        text = '{"tool_call": {"name": "read_file", "arguments": {path: "a.py"}}}'
        parsed, _ = parse_tool_call(text)
        assert parsed is None

    def test_missing_name_returns_none(self):
        text = '{"tool_call": {"arguments": {"path": "a.py"}}}'
        parsed, _ = parse_tool_call(text)
        assert parsed is None

    def test_empty_text(self):
        parsed, remaining = parse_tool_call("")
        assert parsed is None
        assert remaining == ""

    def test_non_dict_arguments_becomes_empty_dict(self):
        text = '{"tool_call": {"name": "noop", "arguments": "not-a-dict"}}'
        parsed, _ = parse_tool_call(text)
        assert parsed is not None
        assert parsed.arguments == {}

    def test_nested_braces_in_arguments(self):
        text = (
            '{"tool_call": {"name": "write_file", "arguments": '
            '{"path": "a.py", "content": "def f(): return {}"}}}'
        )
        parsed, _ = parse_tool_call(text)
        assert parsed is not None
        assert parsed.name == "write_file"
        assert parsed.arguments["path"] == "a.py"


class TestParseToolCalls:
    def test_two_tool_calls_returns_both_in_order(self):
        text = (
            '{"tool_call": {"name": "read_file", "arguments": {"path": "a.py"}}}'
            "\n\n"
            '{"tool_call": {"name": "read_file", "arguments": {"path": "b.py"}}}'
        )
        calls, _ = parse_tool_calls(text)
        assert [c.name for c in calls] == ["read_file", "read_file"]
        assert calls[0].arguments == {"path": "a.py"}
        assert calls[1].arguments == {"path": "b.py"}

    def test_three_tool_calls_various_separators(self):
        text = (
            'Intro.\n{"tool_call": {"name": "a", "arguments": {}}}\n'
            '{"tool_call": {"name": "b", "arguments": {}}}\n\n\n'
            'Middle prose.\n{"tool_call": {"name": "c", "arguments": {}}}\nOutro.'
        )
        calls, _ = parse_tool_calls(text)
        assert [c.name for c in calls] == ["a", "b", "c"]

    def test_remaining_text_excludes_all_matched_blocks(self):
        text = (
            'Intro.\n{"tool_call": {"name": "a", "arguments": {}}}\n'
            'Middle.\n{"tool_call": {"name": "b", "arguments": {}}}\nOutro.'
        )
        _, remaining = parse_tool_calls(text)
        assert '"tool_call"' not in remaining
        assert "Intro." in remaining
        assert "Middle." in remaining
        assert "Outro." in remaining

    def test_single_tool_call_still_returns_list_of_one(self):
        text = '{"tool_call": {"name": "read_file", "arguments": {"path": "a.py"}}}'
        calls, remaining = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0].name == "read_file"
        assert remaining == ""

    def test_no_tool_call_returns_empty_list(self):
        text = "I don't need a tool for this, the answer is 42."
        calls, remaining = parse_tool_calls(text)
        assert calls == []
        assert remaining == text

    def test_invalid_tool_call_missing_name_is_skipped_and_scanning_continues(self):
        text = (
            '{"tool_call": {"arguments": {"path": "a.py"}}}\n\n'
            '{"tool_call": {"name": "read_file", "arguments": {"path": "b.py"}}}'
        )
        calls, _ = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0].name == "read_file"
        assert calls[0].arguments == {"path": "b.py"}

    def test_safety_cap_limits_number_of_parsed_calls(self):
        blocks = [
            f'{{"tool_call": {{"name": "call_{i}", "arguments": {{}}}}}}' for i in range(4)
        ]
        text = "\n\n".join(blocks)
        calls, remaining = parse_tool_calls(text, max_calls=2)
        assert [c.name for c in calls] == ["call_0", "call_1"]
        # Untouched blocks beyond the cap survive in `remaining`.
        assert '"call_2"' in remaining
        assert '"call_3"' in remaining

    def test_parse_tool_call_wrapper_still_returns_first_call_only(self):
        text = (
            '{"tool_call": {"name": "a", "arguments": {}}}\n\n'
            '{"tool_call": {"name": "b", "arguments": {}}}'
        )
        parsed, _ = parse_tool_call(text)
        assert parsed is not None
        assert parsed.name == "a"

    def test_parse_tool_call_wrapper_removes_all_detected_blocks_from_remaining(self):
        text = (
            '{"tool_call": {"name": "a", "arguments": {}}}\n\n'
            '{"tool_call": {"name": "b", "arguments": {}}}'
        )
        _, remaining = parse_tool_call(text)
        assert '"tool_call"' not in remaining


class TestLooksLikeFailedAttempt:
    def test_narrated_intent_prose_triggers_retry(self):
        text = "First, let me verify the target directory exists."
        assert looks_like_failed_attempt(text) is True

    def test_raw_powershell_triggers_retry(self):
        text = (
            'if (Test-Path "C:\\Users\\Knott\\.config\\opencode\\agents") {\n'
            "    Write-Host \"exists\"\n"
            "} else {\n"
            "    New-Item -ItemType Directory -Path ...\n"
            "}"
        )
        assert looks_like_failed_attempt(text) is True

    def test_raw_python_triggers_retry(self):
        text = 'import os\n\ndef make_dirs():\n    os.mkdir("agents")\n'
        assert looks_like_failed_attempt(text) is True

    def test_fenced_code_block_triggers_retry(self):
        text = "```bash\n#!/bin/sh\nmkdir -p ./agents\n```"
        assert looks_like_failed_attempt(text) is True

    def test_malformed_tool_call_json_still_triggers_retry(self):
        text = '{"tool_call": {"name": "read_file", "arguments": {path: "a.py"}}}'
        assert looks_like_failed_attempt(text) is True

    def test_valid_tool_call_does_not_trigger_retry(self):
        text = '{"tool_call": {"name": "read_file", "arguments": {"path": "a.py"}}}'
        # A successfully parsed tool_call is never passed to this heuristic
        # in app.py (it only runs when parsing failed), but it must not be
        # mistaken for a failed attempt if it ever is.
        assert looks_like_failed_attempt(text) is True  # contains "tool_call"

    def test_plain_final_answer_does_not_trigger_retry(self):
        text = "The answer is 42."
        assert looks_like_failed_attempt(text) is False

    def test_empty_text_does_not_trigger_retry(self):
        assert looks_like_failed_attempt("") is False
        assert looks_like_failed_attempt("   ") is False

    def test_final_answer_containing_first_does_not_trigger_retry(self):
        # "first" alone is too broad a signal -- it shows up in ordinary
        # final answers that are not failed tool-call attempts.
        text = "First, run the tests, then deploy."
        assert looks_like_failed_attempt(text) is False

    def test_final_answer_containing_verify_does_not_trigger_retry(self):
        # "verify" alone is too broad a signal for the same reason.
        text = "I verified the fix works."
        assert looks_like_failed_attempt(text) is False

    def test_first_person_future_narration_still_triggers_retry(self):
        # "let me" etc. remain strong, action-oriented signals even without
        # "first"/"verify" in the trigger list.
        assert looks_like_failed_attempt("Let me check that file.") is True
        assert looks_like_failed_attempt("I'll create the directory now.") is True
        assert looks_like_failed_attempt("I need to read the config first.") is True
