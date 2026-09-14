/**
 * Shared types for the per-platform service registration modules.
 *
 * `Shell` is derived from `PluginInput["$"]` rather than importing
 * `BunShell` directly, since only `PluginInput` is re-exported from the
 * package root.
 */

import type { PluginInput } from "@opencode-ai/plugin";

export type Shell = PluginInput["$"];

export const SERVICE_NAME = "OneMinGateway";
export const LAUNCHD_LABEL = "com.oneminai.gateway";
export const SYSTEMD_UNIT = "onemin-gateway.service";
