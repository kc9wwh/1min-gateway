/**
 * macOS service registration: a per-user LaunchAgent plist in
 * ~/Library/LaunchAgents/, loaded with launchctl.
 */

import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { Shell, LAUNCHD_LABEL } from "./common.js";

function plistPath(): string {
  return path.join(os.homedir(), "Library", "LaunchAgents", `${LAUNCHD_LABEL}.plist`);
}

function plistContents(pythonExe: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${pythonExe}</string>
    <string>-m</string>
    <string>onemin_gateway</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${path.join(os.homedir(), "Library", "Logs", "onemin-gateway.log")}</string>
  <key>StandardErrorPath</key>
  <string>${path.join(os.homedir(), "Library", "Logs", "onemin-gateway.err.log")}</string>
</dict>
</plist>
`;
}

export async function registerMacService($: Shell, pythonExe: string): Promise<void> {
  const target = plistPath();
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.writeFile(target, plistContents(pythonExe), "utf-8");

  // Unload first (idempotent re-install) then load, ignoring errors if it
  // wasn't loaded yet.
  await $`launchctl unload ${target}`.quiet().nothrow();
  await $`launchctl load -w ${target}`.quiet().nothrow();
}

export async function isMacServiceRegistered(): Promise<boolean> {
  try {
    await fs.access(plistPath());
    return true;
  } catch {
    return false;
  }
}

export async function unregisterMacService($: Shell): Promise<void> {
  const target = plistPath();
  await $`launchctl unload ${target}`.quiet().nothrow();
  await fs.rm(target, { force: true });
}
