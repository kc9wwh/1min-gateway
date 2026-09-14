/**
 * Read/write the gateway's config.json, mirroring
 * gateway/src/onemin_gateway/config.py's shape. Reads are merge-safe: an
 * existing config (in particular the user's pasted API key) is never
 * clobbered by a re-install -- only missing fields are filled in.
 */

import { promises as fs } from "node:fs";
import path from "node:path";

export interface ModelPricing {
  input: number;
  output: number;
}

export interface GatewayFileConfig {
  backend: "oneminai" | "relay";
  oneminai_api_key: string;
  oneminai_base_url: string;
  oneminai_chat_endpoint: string;
  relay_base_url: string;
  relay_api_key: string;
  host: string;
  port: number;
  tool_call_retry: boolean;
  pricing: Record<string, ModelPricing>;
  default_pricing: ModelPricing;
}

// Kept in sync with PROMPT.md's reference pricing and
// gateway/config.sample.json.
export const DEFAULT_PRICING: Record<string, ModelPricing> = {
  "grok-4-fast-non-reasoning": { input: 600, output: 1502 },
  "deepseek-v4-pro": { input: 1305, output: 2612 },
  "qwen3-8b": { input: 0, output: 0 },
  "qwen3.7-flash": { input: 90, output: 390 },
  "deepseek-v4-flash": { input: 420, output: 840 },
  "grok-4.3": { input: 3752, output: 7505 },
  "us.anthropic.claude-sonnet-5": { input: 6603, output: 33017 },
};

export function defaultConfig(port: number): GatewayFileConfig {
  return {
    backend: "oneminai",
    oneminai_api_key: "",
    oneminai_base_url: "https://api.1min.ai",
    oneminai_chat_endpoint: "/api/chat-with-ai",
    relay_base_url: "http://192.168.50.206:5001/v1",
    relay_api_key: "",
    host: "127.0.0.1",
    port,
    tool_call_retry: true,
    pricing: DEFAULT_PRICING,
    default_pricing: { input: 0, output: 0 },
  };
}

export async function readConfig(filePath: string): Promise<GatewayFileConfig | null> {
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    return JSON.parse(raw) as GatewayFileConfig;
  } catch {
    return null;
  }
}

export async function writeConfig(filePath: string, config: GatewayFileConfig): Promise<void> {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, JSON.stringify(config, null, 2), "utf-8");
}

/**
 * Ensure a config file exists, preserving anything already there (API key,
 * backend choice, custom pricing edits) and only filling in what's missing.
 * Returns the effective config actually on disk after this call.
 */
export async function ensureConfig(filePath: string, preferredPort: number): Promise<GatewayFileConfig> {
  const existing = await readConfig(filePath);
  if (existing) {
    return existing;
  }
  const fresh = defaultConfig(preferredPort);
  await writeConfig(filePath, fresh);
  return fresh;
}
