"""Model backends: 1min.ai directly, or the user's own OpenAI-compatible relay.

Both backends are called *non-streaming* internally, even when OpenCode asks
for a streamed response: the gateway must see the model's full text before it
can tell whether it contains a `{"tool_call": ...}` object, so there is no
way to usefully stream partial tokens through the tool-call parser anyway.
When the client requested `stream: true`, `app.py` fakes an SSE stream by
emitting the fully-formed response as a single chunk. This keeps the
translation loop simple, per the "don't over-engineer" directive -- real
token-by-token streaming can be layered on later without changing this
interface.

Backend call signature: `call(prompt, model) -> BackendResult`.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import GatewayConfig


class BackendError(Exception):
    """Raised when a backend call fails; message is safe to surface to the
    client as an OpenAI-style error."""


@dataclass
class BackendResult:
    text: str
    # Real usage from the backend, if it reported any (see 1min.ai notes
    # below). None means "the caller should estimate tokens instead".
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


async def call_oneminai(prompt: str, model: str, config: GatewayConfig) -> BackendResult:
    """Call 1min.ai's unified chat endpoint.

    Wire format (validated against a production relay, since this is
    undocumented and not covered by 1min.ai's public docs beyond the
    endpoint name):

    - `POST {base_url}/api/chat-with-ai`
    - headers: `API-KEY: <key>`, `Content-Type: application/json`
    - body: `{"type": "UNIFY_CHAT_WITH_AI", "model": <model>,
      "promptObject": {"prompt": <flat prompt>,
      "settings": {"historySettings": {"isMixed": false},
      "withMemories": false}}}`
    - response text: `aiRecord.aiRecordDetail.resultObject[0]`, falling back
      to a top-level `content` field.
    - response usage (when present): `aiRecord.metadata.{inputToken,
      outputToken,totalToken}`. The upstream sometimes reports an all-zero
      metadata block for a real exchange -- that's treated as "no usage
      reported" so the caller falls back to a local estimate instead of
      recording a confident zero.
    """
    if not config.oneminai_api_key:
        raise BackendError(
            "1min.ai backend selected but no API key configured. Set "
            "'oneminai_api_key' in the gateway config."
        )

    url = f"{config.oneminai_base_url.rstrip('/')}{config.oneminai_chat_endpoint}"
    headers = {
        "API-KEY": config.oneminai_api_key,
        "Content-Type": "application/json",
    }
    body = {
        "type": "UNIFY_CHAT_WITH_AI",
        "model": model,
        "promptObject": {
            "prompt": prompt,
            "settings": {
                "historySettings": {"isMixed": False},
                "withMemories": False,
            },
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise BackendError(f"Network error calling 1min.ai: {exc}") from exc

    if resp.status_code >= 400:
        raise BackendError(
            f"1min.ai returned {resp.status_code}: {resp.text[:500]}"
        )

    data = resp.json()
    ai_record = data.get("aiRecord") or {}
    detail = ai_record.get("aiRecordDetail") or {}
    result_object = detail.get("resultObject") or []
    text = (result_object[0] if result_object else None) or data.get("content") or ""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    metadata = ai_record.get("metadata") or {}
    input_tok = metadata.get("inputToken")
    output_tok = metadata.get("outputToken")
    if isinstance(input_tok, (int, float)) or isinstance(output_tok, (int, float)):
        pt = int(input_tok or 0)
        ct = int(output_tok or 0)
        # A real exchange never costs exactly 0 tokens both ways -- treat an
        # all-zero report as "not accounted for" rather than a confident
        # zero (matches the known upstream quirk).
        if pt != 0 or ct != 0:
            prompt_tokens, completion_tokens = pt, ct

    return BackendResult(
        text=text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )


async def call_relay(prompt: str, model: str, config: GatewayConfig) -> BackendResult:
    """Call the user's own OpenAI-compatible relay as an alternative backend.

    The relay is treated the same way as 1min.ai for consistency and easy
    debugging: the whole conversation (including the injected tool-call
    protocol block) is flattened into a single prompt string and sent as one
    user message, rather than assuming the relay has special handling for a
    multi-turn `messages` array. If real usage comes back in the OpenAI
    `usage` field, it's used; otherwise the caller estimates.
    """
    url = f"{config.relay_base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if config.relay_api_key:
        headers["Authorization"] = f"Bearer {config.relay_api_key}"

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise BackendError(f"Network error calling relay: {exc}") from exc

    if resp.status_code >= 400:
        raise BackendError(f"Relay returned {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    choices = data.get("choices") or []
    text = ""
    if choices:
        message = choices[0].get("message") or {}
        text = message.get("content") or ""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    usage = data.get("usage")
    if isinstance(usage, dict):
        pt = usage.get("prompt_tokens")
        ct = usage.get("completion_tokens")
        if isinstance(pt, int) and isinstance(ct, int):
            prompt_tokens, completion_tokens = pt, ct

    return BackendResult(
        text=text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )


async def call_backend(prompt: str, model: str, config: GatewayConfig) -> BackendResult:
    """Dispatch to whichever backend is configured."""
    if config.backend == "relay":
        return await call_relay(prompt, model, config)
    return await call_oneminai(prompt, model, config)
