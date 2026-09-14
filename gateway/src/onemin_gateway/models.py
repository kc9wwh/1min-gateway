"""Pydantic models for the OpenAI-compatible surface the gateway exposes.

These intentionally mirror the subset of the OpenAI Chat Completions schema
that OpenCode actually sends/expects. Kept permissive (`extra = "allow"`)
because OpenCode/the AI SDK may include fields we don't need to act on.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FunctionDef(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolDef(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["function"] = "function"
    function: FunctionDef


class FunctionCall(BaseModel):
    name: str
    arguments: str  # JSON-encoded string, per OpenAI wire format


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[ChatMessage]
    tools: list[ToolDef] | None = None
    tool_choice: Any = None
    stream: bool = False
    session_id: str | None = None  # not part of OpenAI spec; used if present


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def now() -> int:
    return int(time.time())


class ChoiceMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: Literal["stop", "tool_calls"]


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: new_id("chatcmpl"))
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=now)
    model: str
    choices: list[Choice]
    usage: Usage


class Model(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = Field(default_factory=now)
    owned_by: str = "1min-gateway"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[Model]
