"""FastAPI app: the OpenAI-compatible surface OpenCode talks to.

This is the only place that knows about HTTP. Everything else (protocol
translation, backend calls, cost tracking) is plain, testable functions.

Responsibilities, and only these:
- Expose `POST /v1/chat/completions` (streaming + non-streaming) and
  `GET /v1/models`.
- Run ONE round of the translation loop per request: flatten the incoming
  messages + tools into a prompt, call the configured backend, parse the
  result for a tool_call, and translate it back into OpenAI's native shape.
- Track cost/usage.

It does NOT execute tools, does NOT loop multiple tool calls itself (that's
OpenCode's job -- it calls this endpoint again with the tool result appended
to `messages` for each step), and does NOT do model routing.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from . import protocol
from .backends import BackendError, call_backend
from .config import GatewayConfig, usage_path
from .cost import UsageTracker, estimate_tokens
from .models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    FunctionCall,
    Model,
    ModelList,
    ToolCall,
    Usage,
    new_id,
    now,
)

logger = logging.getLogger("onemin_gateway")

app = FastAPI(title="1min.ai Agent Gateway", version="0.1.0")

# Loaded once at process start. The gateway is stateless *between requests*
# except for config + usage tracking, both of which live here.
config = GatewayConfig.load()
usage_tracker = UsageTracker(usage_path(), config)

# Header OpenCode's plugin sets (via the `chat.headers` hook) so the gateway
# can attribute cost/usage to a session without OpenCode's `sessionID`
# otherwise being present anywhere in the OpenAI wire format.
SESSION_HEADER = "x-opencode-session-id"


def _session_id(request: Request, body: ChatCompletionRequest) -> str:
    if body.session_id:
        return body.session_id
    header_val = request.headers.get(SESSION_HEADER)
    return header_val or "default"


async def _run_one_round(
    body: ChatCompletionRequest, session_id: str
) -> tuple[ChatCompletionResponse, str]:
    """Run exactly one prompt -> backend -> parse round, with the one
    corrective retry described in PROMPT.md. Returns the response plus the
    raw backend text actually used (for logging)."""
    tools = body.tools or []
    prompt = protocol.build_prompt(body.messages, tools)

    try:
        result = await call_backend(prompt, body.model, config)
    except BackendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    parsed, remaining_text = protocol.parse_tool_call(result.text)

    if parsed is None and tools and config.tool_call_retry:
        stripped = result.text.strip()
        looks_like_failed_attempt = stripped.startswith("{") or "tool_call" in (
            stripped.lower()
        )
        if looks_like_failed_attempt:
            logger.info(
                "Malformed tool_call from model, retrying once with correction"
            )
            retry_prompt = (
                prompt + "\n" + result.text + "\n\nHuman: " + protocol.RETRY_CORRECTION_PROMPT
            )
            try:
                result = await call_backend(retry_prompt, body.model, config)
            except BackendError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            parsed, remaining_text = protocol.parse_tool_call(result.text)

    # Token accounting: prefer real usage from the backend, fall back to a
    # character-based estimate.
    if result.prompt_tokens is not None and result.completion_tokens is not None:
        prompt_tokens = result.prompt_tokens
        completion_tokens = result.completion_tokens
    else:
        prompt_tokens = estimate_tokens(prompt)
        completion_tokens = estimate_tokens(result.text)

    usage_tracker.record(session_id, body.model, prompt_tokens, completion_tokens)
    usage = Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )

    if parsed is not None:
        tool_call = ToolCall(
            id=new_id("call"),
            function=FunctionCall(
                name=parsed.name, arguments=json.dumps(parsed.arguments)
            ),
        )
        choice = Choice(
            message=ChoiceMessage(content=None, tool_calls=[tool_call]),
            finish_reason="tool_calls",
        )
    else:
        # No tool call found (either none was needed, or both attempts
        # failed to produce one) -- return the text as-is so the loop
        # doesn't hang, per PROMPT.md's robustness requirement.
        choice = Choice(
            message=ChoiceMessage(content=result.text or remaining_text),
            finish_reason="stop",
        )

    response = ChatCompletionResponse(model=body.model, choices=[choice], usage=usage)
    return response, result.text


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    payload = await request.json()
    body = ChatCompletionRequest.model_validate(payload)
    session_id = _session_id(request, body)

    response, _ = await _run_one_round(body, session_id)

    if not body.stream:
        return response.model_dump(exclude_none=True)

    return StreamingResponse(
        _fake_sse_stream(response), media_type="text/event-stream"
    )


async def _fake_sse_stream(response: ChatCompletionResponse) -> AsyncIterator[bytes]:
    """Emit `response` as an OpenAI-compatible SSE stream.

    The gateway always calls the backend non-streaming internally (see
    backends.py for why), so this "streams" the already-complete response as
    a couple of chunks rather than token-by-token. OpenCode's AI SDK client
    accumulates chunks the same way regardless of how many there are.
    """
    choice = response.choices[0]
    base = {
        "id": response.id,
        "object": "chat.completion.chunk",
        "created": now(),
        "model": response.model,
    }

    # First chunk: role.
    yield _sse(
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
    )

    if choice.message.tool_calls:
        for i, call in enumerate(choice.message.tool_calls):
            delta = {
                "tool_calls": [
                    {
                        "index": i,
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                ]
            }
            yield _sse({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
    elif choice.message.content:
        yield _sse(
            {
                **base,
                "choices": [
                    {"index": 0, "delta": {"content": choice.message.content}, "finish_reason": None}
                ],
            }
        )

    yield _sse(
        {
            **base,
            "choices": [{"index": 0, "delta": {}, "finish_reason": choice.finish_reason}],
            "usage": response.usage.model_dump(),
        }
    )
    yield b"data: [DONE]\n\n"


def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj)}\n\n".encode("utf-8")


@app.get("/v1/models")
async def list_models() -> dict:
    model_ids = sorted(config.pricing.keys())
    return ModelList(data=[Model(id=m) for m in model_ids]).model_dump()


@app.get("/v1/usage")
async def usage(request: Request) -> dict:
    session_id = request.headers.get(SESSION_HEADER)
    payload = usage_tracker.snapshot()
    if session_id:
        payload["current_session"] = usage_tracker.session_snapshot(session_id)
    return payload


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "backend": config.backend}
