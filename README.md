# 1min.ai Agent Gateway + OpenCode Plugin

A cross-platform system that lets OpenCode (and other OpenAI-compatible
coding agents) do **real tool calling** — including MCP tools — while using
**1min.ai** as the model backend.

## Why this exists

1min.ai's API has **no native tool-calling support**. Its `chat-with-ai`
endpoint (`type: UNIFY_CHAT_WITH_AI`) takes a flat prompt string and returns
text — there is no `tools` parameter to forward, and no structured
`tool_calls` in the response. This breaks every coding agent (Cline, Zoo
Code, OpenCode) that relies on native function calling.

This project solves that by **emulating tool calling at a gateway layer**:

- The gateway exposes a **native OpenAI-compatible `/v1/chat/completions`**
  endpoint with full `tools`/`tool_calls` support.
- Internally, it injects tool definitions into the prompt as a **JSON spec**,
  parses JSON tool calls out of the model's text, and translates them into
  native `tool_calls` that OpenCode executes.
- OpenCode sees a perfectly normal tool-calling endpoint and needs no
  changes to its agent loop.

## Architecture

```
OpenCode (VS Code / TUI / CLI)
      │  native tools + messages (built-ins + MCP)
      ▼
Gateway (Python/FastAPI)              ← PURE translation layer, no tool execution
      │  flat prompt string (no tools)
      ▼
1min.ai  (or your own relay)          ← the "brain", unchanged
```

Two deliverables, both in this repo:

1. **`gateway/`** — a Python (FastAPI) service that translates native tool
   calling ↔ a JSON prompt protocol and tracks cost. It is **stateless**
   between requests (aside from the config and a persisted usage log), does
   **not** execute tools, and does **not** route models.
2. **`plugin/`** — an OpenCode plugin (TypeScript) that installs the gateway
   cross-platform and registers it as a custom provider.

## Install

### 1. Point OpenCode at the plugin

Add the plugin to your (global or per-project) `opencode.json`:

```json
{
  "plugin": ["file:///C:/Users/Knott/dev/1min-gateway/plugin"]
}
```

Build it once first:

```
cd plugin
npm install
npm run build
```

On OpenCode's next start, the plugin:

1. Bootstraps Python (`uv` if available, otherwise system `python3`/`python`
   + `venv`) and does an editable install of the sibling `gateway/` package.
2. Writes a default config to the cross-platform config directory if one
   doesn't already exist (`%APPDATA%\1min-gateway\config.json` on Windows,
   `~/.config/1min-gateway/config.json` on macOS/Linux) — **without**
   clobbering an existing config on later runs.
3. Picks a free port (default `8765`) and registers the gateway as a
   background service: a Scheduled Task on Windows, a LaunchAgent on macOS,
   a systemd user unit on Linux.
4. Registers a `1min-gateway` provider in OpenCode pointing at the running
   gateway.

This is idempotent — it runs (cheaply, via a health check) on every OpenCode
start, and only does real install work the first time or if the service
isn't responding.

### 2. Set your 1min.ai API key

The plugin doesn't have your key, so the first run writes a config with an
empty one. Open the config file it logged and fill in `oneminai_api_key`,
then restart the gateway service (or just restart OpenCode, which restarts
it):

```json
{
  "oneminai_api_key": "sk-...",
  "backend": "oneminai"
}
```

To use your own relay instead of 1min.ai directly, set:

```json
{
  "backend": "relay",
  "relay_base_url": "http://192.168.50.206:5001/v1"
}
```

A filled-in reference is at [`gateway/config.sample.json`](gateway/config.sample.json).

### 3. Configure pricing (optional)

The `pricing` block in config.json drives cost tracking (`GET /v1/usage`
and OpenCode's own cost display, via the `cost` field the plugin writes into
each model's provider config). Units are whatever you use consistently —
1min.ai credits, USD, etc. — the gateway just multiplies
`tokens / 1,000,000 * price`. Reference values (as configured by default):

| Model | Input (per 1M) | Output (per 1M) |
|---|---|---|
| `grok-4-fast-non-reasoning` | 600 | 1502 |
| `deepseek-v4-pro` | 1305 | 2612 |
| `qwen3-8b` | 0 | 0 |
| `qwen3.7-flash` | 90 | 390 |
| `deepseek-v4-flash` | 420 | 840 |
| `grok-4.3` | 3752 | 7505 |
| `us.anthropic.claude-sonnet-5` | 6603 | 33017 |

1min.ai occasionally reports real token usage
(`aiRecord.metadata.{inputToken,outputToken}`); when it doesn't (or reports
an implausible all-zero record), the gateway falls back to a `chars / 4`
estimate.

## Set up tiered subagents in OpenCode

Model selection lives entirely in OpenCode, not the gateway — the gateway
just passes whatever `model` field it receives straight through to 1min.ai.
Configure your tiered strategy as **named subagents** in `opencode.json`:

```json
{
  "agent": {
    "orchestrator": {
      "mode": "primary",
      "model": "1min-gateway/grok-4-fast-non-reasoning"
    },
    "code": {
      "mode": "subagent",
      "model": "1min-gateway/qwen3-8b"
    },
    "architect": {
      "mode": "subagent",
      "model": "1min-gateway/deepseek-v4-pro"
    },
    "debug": {
      "mode": "subagent",
      "model": "1min-gateway/deepseek-v4-flash"
    },
    "review": {
      "mode": "subagent",
      "model": "1min-gateway/grok-4-fast-non-reasoning"
    }
  }
}
```

### ⚠️ Two OpenCode caveats to know about

1. **Built-in subagents (`general`, `explore`) ignore model overrides.**
   Define your own named subagents (as above) instead of trying to override
   the built-ins — an override on `general`/`explore` is silently dropped.
2. **Adding a subagent just to set its model can silently drop
   `mode: "subagent"`.** Always include `"mode": "subagent"` explicitly
   alongside the `model` override in the JSON entry, as shown above — a bare
   `{"model": "..."}` entry can end up running as a primary agent instead.

Each subagent's configured model **does** flow through to the gateway: the
underlying `@ai-sdk/openai-compatible` provider always sends the resolved
model ID as the `model` field in the request body it POSTs to
`/v1/chat/completions`, so the gateway sees exactly which model each
subagent picked and forwards that model ID to 1min.ai unchanged.

## Using this if you're another 1min.ai user

1. Clone this repo, `npm install && npm run build` in `plugin/`.
2. Point your `opencode.json`'s `plugin` array at the built `plugin/`
   directory (see Install above).
3. Start OpenCode once to trigger the install, then edit the generated
   config.json with your own 1min.ai API key.
4. Add named subagents (see above) using whatever models your 1min.ai plan
   includes, with pricing entries matching your actual per-model rates.
5. If you'd rather not run against 1min.ai directly, point `backend` at
   your own OpenAI-compatible relay instead.

## Key design decisions

- **JSON tool-call protocol, not XML.** Grok, DeepSeek, and Qwen all emit
  JSON far more reliably than XML. The gateway defines the exact JSON
  dialect, so it always matches what the models produce.
- **OpenCode owns tool execution (including MCP).** The gateway never
  touches the filesystem and never runs commands. OpenCode executes its
  built-in tools and MCP tools exactly as it always does.
- **The gateway calls the backend non-streaming internally, always.** It
  needs the full text to know whether a `tool_call` object is present
  before it can decide how to respond, so there's no useful way to stream
  partial tokens through the parser. When OpenCode requests a streamed
  response, the gateway fakes an SSE stream with the already-complete
  answer. Real token-level streaming can be added later without changing
  the public interface.
- **Gateway holds the 1min.ai API key**, not OpenCode or the plugin. Paste
  it into the gateway's config once.
- **Cross-platform service registration** via `uv` (preferred) or system
  Python + `venv`, using Scheduled Tasks / LaunchAgents / systemd user
  units per OS.
- **Session cost tracking via a header, not the OpenAI wire format.**
  OpenCode's session ID has no home in a standard `/v1/chat/completions`
  request, so the plugin's `chat.headers` hook adds
  `x-opencode-session-id`, which the gateway reads to attribute usage/cost
  per session (`GET /v1/usage`).

## Repo layout

```
gateway/    Python package (FastAPI service) — pip install -e it, run tests with pytest
plugin/     OpenCode plugin (TypeScript) — npm install && npm run build
PROMPT.md   Original build specification
```

## Development

```
# Gateway
cd gateway
python -m venv .venv
.venv/Scripts/activate        # or source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
pytest

# Plugin
cd plugin
npm install
npm run build
```

## Status

Built per `PROMPT.md`. The two VERIFY EARLY items were confirmed against
the actual published `@opencode-ai/plugin`/`@opencode-ai/sdk` 1.18.x
packages before the plugin was written:

1. Custom providers are registered from the `config` hook by writing
   `Config.provider[<id>] = { npm: "@ai-sdk/openai-compatible", options: {
   baseURL, apiKey }, models: {...} }` — confirmed directly from the SDK's
   generated `ProviderConfig` type.
2. Per-subagent model overrides do flow to the gateway: the
   `@ai-sdk/openai-compatible` client always sends `model: this.modelId` in
   the request body, so whatever model a subagent resolves to is exactly
   what arrives at `/v1/chat/completions`.
