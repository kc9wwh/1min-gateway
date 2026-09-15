/**
 * OpenCode plugin: installs the 1min.ai Agent Gateway on first activation
 * and registers it as a custom OpenAI-compatible provider.
 *
 * Verified against @opencode-ai/plugin 1.18.x:
 * - Providers are registered by writing into `Config.provider[<id>]` from
 *   the `config` hook, using the `npm: "@ai-sdk/openai-compatible"` wrapper
 *   (the same mechanism OpenCode's own docs use for custom OpenAI-compatible
 *   endpoints) with `options.baseURL` pointing at the gateway.
 * - A plugin's exported member just needs to match the `Plugin` type
 *   (`(input, options) => Promise<Hooks>`); OpenCode's own bundled example
 *   plugin exports it as a named `const`, which this follows.
 */

import type { Hooks, Plugin, PluginInput } from "@opencode-ai/plugin";

import { configFilePath } from "./config-paths.js";
import { readConfig } from "./gateway-config.js";
import { installGateway } from "./install.js";

const PROVIDER_ID = "1min-gateway";
const SESSION_HEADER = "x-opencode-session-id";

function log(message: string): void {
  console.log(`[1min-gateway] ${message}`);
}

export const OneMinGatewayPlugin: Plugin = async (input: PluginInput) => {
  let installedPort: number | null = null;

  try {
    const result = await installGateway(input.$, log);
    installedPort = result.port;
  } catch (error) {
    // Never throw out of plugin activation -- OpenCode would fail to start.
    // Log and let the `config` hook fall back to whatever is on disk (or
    // the default port), so the user can fix the install and retry.
    log(`install failed: ${(error as Error).message}`);
  }

  const hooks: Hooks = {
    // Deliberately NOT exposing `restart_gateway` as an agent tool: the
    // gateway restart is intentionally a human-only action, triggered via
    // the `/restart-gateway` slash command (global, in
    // ~/.config/opencode/commands/), not something the orchestrator or any
    // subagent can invoke on its own. `restartGateway()` in install.ts is
    // still there for the command's underlying script to call.
    config: async (config) => {
      const fileConfig = await readConfig(configFilePath());
      const port = installedPort ?? fileConfig?.port ?? 8765;
      const baseUrl = `http://127.0.0.1:${port}/v1`;
      const pricing = fileConfig?.pricing ?? {};

      config.provider = config.provider ?? {};
      config.provider[PROVIDER_ID] = {
        npm: "@ai-sdk/openai-compatible",
        name: "1min.ai Gateway",
        options: {
          baseURL: baseUrl,
          // The gateway itself doesn't check this -- it holds the real
          // 1min.ai key in its own config -- but the AI SDK's
          // openai-compatible client requires *some* value to be set.
          apiKey: "not-needed",
        },
        models: Object.fromEntries(
          Object.entries(pricing).map(([modelId, price]) => [
            modelId,
            {
              name: modelId,
              tool_call: true,
              cost: { input: price.input, output: price.output },
            },
          ]),
        ),
      };
    },

    // Tag every request with the OpenCode session ID via a header, since
    // it otherwise never appears in the OpenAI wire format the gateway
    // speaks. The gateway reads this to attribute cost/usage per session.
    "chat.headers": async (input, output) => {
      output.headers[SESSION_HEADER] = input.sessionID ?? "default";
    },
  };

  return hooks;
};
