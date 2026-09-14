/**
 * Cross-platform config paths, mirroring gateway/src/onemin_gateway/config.py
 * exactly so the plugin and the Python gateway agree on where config lives:
 *
 * - Windows: %APPDATA%\1min-gateway\config.json
 * - macOS / Linux: ~/.config/1min-gateway/config.json
 *
 * Never hardcode path separators -- always go through `node:path`.
 */

import os from "node:os";
import path from "node:path";

export function configDir(): string {
  if (process.platform === "win32") {
    const appData = process.env.APPDATA ?? path.join(os.homedir(), "AppData", "Roaming");
    return path.join(appData, "1min-gateway");
  }
  const xdg = process.env.XDG_CONFIG_HOME;
  const base = xdg && xdg.length > 0 ? xdg : path.join(os.homedir(), ".config");
  return path.join(base, "1min-gateway");
}

export function configFilePath(): string {
  return path.join(configDir(), "config.json");
}

export function usageFilePath(): string {
  return path.join(configDir(), "usage.json");
}

export function venvDir(): string {
  return path.join(configDir(), "venv");
}

export function venvPython(): string {
  return process.platform === "win32"
    ? path.join(venvDir(), "Scripts", "python.exe")
    : path.join(venvDir(), "bin", "python3");
}
