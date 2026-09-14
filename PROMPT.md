# PROJECT: 1min.ai Agent Gateway + OpenCode Plugin

You are building a new project from scratch. Create it in a new directory at
`C:\Users\Knott\dev\1min-gateway` (create the directory if needed).

## What this is

A cross-platform system that lets OpenCode (and other OpenAI-compatible coding
agents) do REAL tool calling — including MCP tools — while using 1min.ai as the
model backend. 1min.ai's API has NO native tool-calling support (its
`UNIFY_CHAT_WITH_AI` endpoint takes a flat prompt string and returns text). So
this gateway EMULATES tool calling using a JSON protocol: it injects tool
definitions into the prompt, parses JSON tool calls out of the model's text,
and translates them into native OpenAI `tool_calls` that OpenCode executes.

## Architecture (two deliverables)

1. **Gateway** — a Python service (FastAPI) that is a PURE, STATELESS
   translation layer. It does NOT execute tools itself. It:
   - Exposes `POST /v1/chat/completions` (streaming + non-streaming) and
     `GET /v1/models`.
   - Accepts native OpenAI `tools` (JSON schemas) and `messages` from OpenCode.
   - Translates the conversation + tool definitions into a JSON tool-call
     prompt protocol for 1min.ai.
   - Parses the model's JSON tool-call decision out of the returned text.
   - Returns a native OpenAI `tool_calls` response (with `id`,
     `type: "function"`, `function.name`, `function.arguments`) and
     `finish_reason: "tool_calls"` so OpenCode executes the tool.
   - When the model is done (no tool call), returns a normal completion.

2. **OpenCode plugin** — a thin plugin that:
   - Registers a custom provider pointing OpenCode at the gateway's
     `http://localhost:<port>/v1`.
   - On first activation (or an explicit "Install gateway" command), installs
     the gateway: bootstraps Python via `uv`, creates a venv, installs deps,
     registers the gateway as a background service, starts it, and writes the
     port/URL into OpenCode's config.
   - Does NOT kill the gateway on exit (the service manager keeps it alive).

## CRITICAL: who executes tools

**OpenCode executes ALL tools** — its built-in tools (read/write/edit files,
run commands) AND any MCP tools the user has connected. The gateway NEVER
executes tools and has NO filesystem access. This is essential so that MCP
servers keep working exactly as they do today: OpenCode owns tool execution,
permissions, and the approval UI. The gateway is only the "brain" that decides
WHICH tool to call.

The loop is:

```
OpenCode sends: messages + tools (built-ins + MCP)
      │
      ▼
Gateway: injects tools into prompt as JSON spec, calls 1min.ai
      │
      ▼
1min.ai returns text (may contain a JSON tool_call object)
      │
      ▼
Gateway: parses the JSON tool_call, returns native tool_calls to OpenCode
      │
      ▼
OpenCode: executes the tool (built-in or MCP), sends result back as
          role: "tool" message
      │
      ▼
(repeat until the model returns text with no tool_call)
```

## Tool-call protocol (JSON, not XML)

Inject into the system prompt a block like:

```
You have access to the following tools. To use a tool, respond with ONLY a
JSON object in this exact format, on its own line, nothing else:
{"tool_call": {"name": "<tool_name>", "arguments": {<json args>}}}
When you are finished, respond normally without a tool_call object.

Available tools:
<JSON array of {name, description, parameters JSON schema}>
```

Parse the model's response for a `{"tool_call": ...}` object. If found:
- Translate it into a native OpenAI `tool_calls` entry with a generated `id`.
- Return `finish_reason: "tool_calls"`.
If no tool_call found, return the text as the final assistant message with
`finish_reason: "stop"`.

**Robustness (important):** if the model emits malformed JSON or describes the
tool call in prose instead of emitting the JSON object, retry once with a
corrective prompt ("You must respond with a JSON tool_call object in the exact
format specified"). If it still fails, return the text as-is with
`finish_reason: "stop"` so the loop does not hang.

## Model selection (NO routing in the gateway)

The gateway does NOT do model routing. OpenCode handles per-agent model
selection natively: each subagent can carry its own `model:` override, so the
user configures their tiered strategy (cheap Qwen for the main coder, Grok for
the orchestrator, DeepSeek for reviewers) entirely in OpenCode's agent config.

The gateway simply reads the `model` field from each incoming request and calls
that model on 1min.ai. No routing table, no mode hint, no custom header. The
gateway is a pure translation shim.

The user's intended hierarchy (GVS5H-style) is configured in OpenCode as named
subagents, e.g.:

- `code` subagent -> `qwen3-8b` (cheap main coder)
- `architect` subagent -> `deepseek-v4-pro`
- `debug` subagent -> `deepseek-v4-flash`
- `review` subagent -> `grok-4-fast-non-reasoning`
- `orchestrator` (primary) -> `grok-4-fast-non-reasoning`

This is all OpenCode config, NOT gateway code. The gateway must simply pass the
requested model through to 1min.ai unchanged.

## 1min.ai backend

- The gateway calls 1min.ai's `UNIFY_CHAT_WITH_AI` endpoint
  (`https://api.1min.ai/api/chat-with-ai`) with the API key held in the
  gateway's config (NOT per-request).
- Support an alternative backend: the user's own relay at
  `http://192.168.50.206:5001/v1` (an OpenAI-compatible endpoint). The gateway
  should be able to call EITHER 1min.ai directly OR the relay, configurable.
- Flatten the OpenAI `messages` array into the prompt string 1min.ai expects
  (System:/Human:/Assistant:/Tool: lines), preserving tool results.

## Cost tracking

- Track tokens and cost per session. The gateway should compute cost using
  per-model pricing from its config (input/output price per 1M tokens).
- Expose a `GET /v1/usage` endpoint returning per-session and cumulative
  token/cost stats, and log each model call with its cost.
- Emit accurate `usage` (prompt_tokens, completion_tokens, total_tokens) in
  every response so OpenCode's cost plugins can compute real costs.

## Cross-platform install (the plugin's job)

The plugin must install the gateway on Windows, macOS, and Linux:

- **Python bootstrap**: use `uv` if available (it can install a pinned Python
  and manage the venv). Fall back to system `python3` + `venv` if `uv` is
  absent. Detect and report missing Python clearly.
- **Service registration** (isolate per-platform logic):
  - Windows: scheduled task at logon (or NSSM if present).
  - macOS: LaunchAgent plist in `~/Library/LaunchAgents/`.
  - Linux: systemd user unit in `~/.config/systemd/user/`.
- **Port selection**: default `8765`; if taken, find a free port and persist it.
- **Config location**: store gateway config (API key, relay URL, pricing) in a
  cross-platform location (`~/.config/1min-gateway/config.json`, with the
  Windows equivalent).
- Use `pathlib` everywhere; never hardcode path separators.

## Tech stack

- Gateway: Python 3.11+, FastAPI + uvicorn, `httpx` for outbound calls,
  `pydantic` for models. Keep dependencies minimal.
- Plugin: OpenCode plugin (TypeScript), following OpenCode's plugin API for
  registering a custom provider.

## ⚠️ VERIFY EARLY

1. **OpenCode plugin API for registering a custom provider** — the one piece
   that depends on OpenCode's internals and is most likely to have changed
   recently. Confirm the current plugin/provider API BEFORE writing the plugin
   half of the project.

2. **Per-subagent model routing flows through to the gateway.** Confirm that
   when a subagent has a `model:` override, OpenCode sends that model name in
   the request body to the gateway (so the gateway can pass it to 1min.ai).
   Known OpenCode caveats to document in the README:
   - Built-in subagents (`general`, `explore`) IGNORE model overrides — the
     user must define their own named subagents, not override the built-ins.
   - Adding a subagent to `opencode.json` just to set its model can silently
     drop `mode: subagent` — the JSON entry must explicitly include
     `"mode": "subagent"` alongside the model override.

## Deliverables

1. Working gateway: stateless translation layer with the JSON tool-call loop,
   cost tracking, and 1min.ai + relay backends. NO model routing, NO local tool
   execution, NO filesystem access, NO safety gates (OpenCode owns all of
   that).
2. Working OpenCode plugin that installs the gateway cross-platform and
   registers the provider.
3. A README.md explaining: what it does, how to install (plugin + gateway),
   how to configure (API key, pricing), how to set up tiered subagents in
   OpenCode (with the two caveats above), and how another 1min.ai user would
   use it.
4. Tests for the gateway's core logic (tool-call parsing, message flattening,
   cost calculation). Use pytest.
5. A sample config file with the pricing filled in from the values below.

## Reference pricing (for the sample config)

- grok-4-fast-non-reasoning: input 600, output 1502 (per 1M tokens)
- deepseek-v4-pro: input 1305, output 2612
- qwen3-8b: input 0, output 0 (free tier)
- qwen3.7-flash: input 90, output 390
- deepseek-v4-flash: input 420, output 840
- grok-4.3: input 3752, output 7505
- us.anthropic.claude-sonnet-5: input 6603, output 33017

## Constraints

- The gateway is STATELESS between requests except for config and usage
  tracking (persist usage to a file so it survives restarts).
- Do not over-engineer. Get the translation loop working end-to-end first, then
  add cost tracking.
- Write clean, well-commented code. This may be open-sourced later.
- The gateway must be a single installable unit (a Python package with a
  `pyproject.toml` and a console entry point like `1min-gateway`).

Start by scaffolding the project structure, then implement the gateway core
(translation loop + 1min.ai backend), then cost tracking, then the plugin, then
tests and README. Report progress as you complete each phase.