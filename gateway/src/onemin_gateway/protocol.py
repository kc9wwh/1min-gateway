"""The JSON tool-call emulation protocol.

1min.ai's `chat-with-ai` endpoint takes a flat prompt string and returns
text -- there is no `tools` parameter and no structured `tool_calls` in the
response. This module is the translation core:

1. ``build_prompt`` -- takes OpenCode's native `messages` + `tools` and
   flattens them into a single prompt string, injecting a JSON tool-call
   protocol block so the model knows how to "call" a tool.
2. ``parse_tool_call`` -- takes the model's raw text response and extracts a
   ``{"tool_call": {"name": ..., "arguments": {...}}}`` object if present.

Nothing here executes tools or touches the filesystem -- it is pure string
translation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .models import ChatMessage, ToolDef

TOOL_PROTOCOL_HEADER = (
    "You have access to the following tools. You have NO filesystem access "
    "and CANNOT run code or shell commands yourself -- you can only act by "
    "emitting a tool_call object, which will be executed for you and the "
    "result sent back to you. NEVER write PowerShell, bash, Python, or any "
    "other code or file contents directly in your response.\n"
    "\n"
    "To use a tool, respond with ONLY a JSON object in this exact format, on "
    "its own line, valid JSON, and nothing else -- no prose, no code, no "
    "explanation:\n"
    '{"tool_call": {"name": "<tool_name>", "arguments": {<json args>}}}\n'
    "\n"
    "Examples:\n"
    'Read a file: {"tool_call": {"name": "read_file", "arguments": '
    '{"path": "src/app.py"}}}\n'
    'List a directory: {"tool_call": {"name": "list_dir", "arguments": '
    '{"path": "."}}}\n'
    'Run a command: {"tool_call": {"name": "run_command", "arguments": '
    '{"command": "pytest -q"}}}\n'
    "\n"
    "Do not narrate or describe what you are about to do (e.g. \"let me...\", "
    "\"first I will...\") -- just emit the tool_call object for the single "
    "next action. Many tasks require several tool calls in a row: a single "
    "successful tool result does NOT mean the task is done. After each tool "
    "result, check whether every part of the original request is complete. "
    "If not, immediately emit the next tool_call -- do not stop to report "
    "partial progress. Only respond with plain text and no tool_call object "
    "once the entire task is finished.\n"
    "\n"
    "Available tools:\n"
)

RETRY_CORRECTION_PROMPT = (
    "Your previous response did not follow the required tool-call format. "
    "Do not write code or shell commands. Do not describe what you will do. "
    "Respond with ONLY the JSON tool_call object for the single next action, "
    'in the exact format: {"tool_call": {"name": "<tool_name>", "arguments": '
    "{<json args>}}}."
)

# Phrases that indicate the model is narrating intent in prose instead of
# emitting a tool_call object (e.g. "First, let me verify the directory
# exists.").
#
# Deliberately limited to first-person-future, action-oriented phrasing --
# i.e. the model announcing it is *about to act*. Broader words like "first"
# or "verify" are intentionally excluded: they show up constantly in ordinary
# prose and legitimate final answers (e.g. "First, run the tests, then
# deploy." or "I verified the fix works.") and would cause false-positive
# retries that waste a round-trip for no benefit.
_NARRATED_INTENT_PHRASES = (
    "let me",
    "i'll",
    "i will",
    "i need to",
    "i should",
    "let's",
)

# Signals that the model wrote raw code/shell instead of a tool_call object
# (e.g. DeepSeek emitting `if (Test-Path ...) { ... }`).
_RAW_CODE_SIGNALS = (
    "test-path",
    "new-item",
    "if (",
    "#!/",
    "import ",
    "def ",
    "function ",
    "mkdir",
    "touch ",
    "echo ",
    "write-file",
    "read-file",
    "```",
)


def looks_like_failed_attempt(text: str) -> bool:
    """True if `text` looks like the model tried to act but did not emit a
    valid ``{"tool_call": ...}`` object -- either malformed JSON, narrated
    intent in prose, or raw code/shell.

    This is used to decide whether to fire the one corrective retry; it is
    intentionally permissive (biased toward retrying) since the alternative
    is a silently hung agent loop.
    """
    stripped = text.strip()
    if not stripped:
        return False
    lowered = stripped.lower()

    # Malformed/partial tool_call JSON.
    if stripped.startswith("{") or "tool_call" in lowered:
        return True

    # Narrated intent in prose.
    if any(phrase in lowered for phrase in _NARRATED_INTENT_PHRASES):
        return True

    # Raw code or shell written directly instead of a tool call.
    if any(signal in lowered for signal in _RAW_CODE_SIGNALS):
        return True

    return False


def _tool_spec_json(tools: list[ToolDef]) -> str:
    spec = [
        {
            "name": t.function.name,
            "description": t.function.description or "",
            "parameters": t.function.parameters or {},
        }
        for t in tools
    ]
    return json.dumps(spec, indent=2)


def build_tool_block(tools: list[ToolDef] | None) -> str:
    """Build the system-prompt block describing available tools.

    Returns an empty string if there are no tools (nothing to inject).
    """
    if not tools:
        return ""
    return TOOL_PROTOCOL_HEADER + _tool_spec_json(tools)


def _stringify_content(content: Any) -> str:
    """OpenAI content can be a plain string or a list of content parts
    (e.g. `[{"type": "text", "text": "..."}]`). Flatten to plain text.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(part.get("text", ""))
                elif "text" in part:
                    parts.append(str(part["text"]))
                else:
                    parts.append(json.dumps(part))
            else:
                parts.append(str(part))
        return "\n".join(p for p in parts if p)
    return str(content)


def flatten_messages(messages: list[ChatMessage]) -> str:
    """Flatten an OpenAI-style message list into 1min.ai's expected
    System:/Human:/Assistant:/Tool: line format, preserving tool call
    round-trips so the model has full context of what it already tried.
    """
    lines: list[str] = []
    # Map tool_call_id -> function name, so `role: "tool"` results can be
    # rendered with the name of the tool they came from.
    call_id_to_name: dict[str, str] = {}

    for msg in messages:
        role = msg.role
        text = _stringify_content(msg.content)

        if role == "system":
            lines.append(f"System: {text}")

        elif role == "user":
            lines.append(f"Human: {text}")

        elif role == "assistant":
            if msg.tool_calls:
                for call in msg.tool_calls:
                    call_id_to_name[call.id] = call.function.name
                    try:
                        args = json.loads(call.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = call.function.arguments
                    tool_call_obj = {
                        "tool_call": {"name": call.function.name, "arguments": args}
                    }
                    lines.append(f"Assistant: {json.dumps(tool_call_obj)}")
            elif text:
                lines.append(f"Assistant: {text}")

        elif role == "tool":
            name = call_id_to_name.get(msg.tool_call_id or "", "unknown_tool")
            lines.append(f"Tool ({name}): {text}")

        else:
            # Unknown role (e.g. "function") -- pass through best-effort.
            lines.append(f"{role.capitalize()}: {text}")

    return "\n".join(lines)


# Reinserted immediately before the generation cue on every round (not just
# once at the top of the prompt, alongside TOOL_PROTOCOL_HEADER). The model
# reliably follows instructions placed right before it starts generating;
# a rule stated only once at the top of a long, growing conversation gets
# diluted ("lost in the middle") after several tool round-trips. This is
# what specifically targets the "one successful tool call and the model
# reports back as if done" degradation pattern.
TASK_PERSISTENCE_REMINDER = (
    "Reminder: this task may need more than one tool call. Do not treat the "
    "most recent tool result as the end of the task. If any part of the "
    "original request is still unfinished, respond now with the next "
    "tool_call -- do not describe remaining work in prose. Only respond "
    "with plain text, with no tool_call object, once the entire task is "
    "completely finished."
)


def build_prompt(messages: list[ChatMessage], tools: list[ToolDef] | None) -> str:
    """Build the full flat prompt to send to 1min.ai / the relay."""
    tool_block = build_tool_block(tools)
    conversation = flatten_messages(messages)
    sections = [s for s in (tool_block, conversation) if s]
    prompt = "\n\n".join(sections)
    if tools:
        prompt += "\n\n" + TASK_PERSISTENCE_REMINDER
    return prompt + "\n\nAssistant:"


@dataclass
class ParsedToolCall:
    name: str
    arguments: dict[str, Any]


def _find_balanced_json(text: str, start: int) -> str | None:
    """Given the index of an opening `{`, return the substring up to its
    matching closing `}`, respecting string literals, or None if unbalanced.
    """
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_tool_call(text: str) -> tuple[ParsedToolCall | None, str]:
    """Try to extract a `{"tool_call": {...}}` object from the model's raw
    text response.

    Returns (parsed_call_or_none, remaining_text). `remaining_text` is the
    original text with the tool_call JSON removed (used as a fallback
    display string; normally unused when a tool_call is found since we
    return finish_reason="tool_calls" with no content).
    """
    stripped = text.strip()
    if not stripped:
        return None, text

    # Fast path: the entire response is exactly the JSON object.
    candidates: list[tuple[str, int]] = [(stripped, 0)]

    # Slow path: search for `"tool_call"` anywhere in the text and try to
    # extract a balanced JSON object starting at the nearest `{` at or
    # before that point.
    idx = stripped.find('"tool_call"')
    if idx != -1:
        brace_start = stripped.rfind("{", 0, idx)
        if brace_start != -1:
            balanced = _find_balanced_json(stripped, brace_start)
            if balanced:
                candidates.append((balanced, brace_start))

    for candidate, start in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("tool_call"), dict):
            call = obj["tool_call"]
            name = call.get("name")
            arguments = call.get("arguments", {})
            if isinstance(name, str):
                if not isinstance(arguments, dict):
                    arguments = {}
                end = start + len(candidate)
                remaining = (stripped[:start] + stripped[end:]).strip()
                return ParsedToolCall(name=name, arguments=arguments), remaining

    return None, text
