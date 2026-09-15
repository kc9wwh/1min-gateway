/**
 * Linux service registration: a systemd user unit in
 * ~/.config/systemd/user/, enabled and started via `systemctl --user`.
 */

import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { Shell, SYSTEMD_UNIT } from "./common.js";

function unitDir(): string {
  const xdgConfig = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config");
  return path.join(xdgConfig, "systemd", "user");
}

function unitPath(): string {
  return path.join(unitDir(), SYSTEMD_UNIT);
}

function unitContents(pythonExe: string): string {
  return `[Unit]
Description=1min.ai Agent Gateway

[Service]
ExecStart=${pythonExe} -m onemin_gateway
Restart=on-failure

[Install]
WantedBy=default.target
`;
}

export async function registerLinuxService($: Shell, pythonExe: string): Promise<void> {
  const target = unitPath();
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.writeFile(target, unitContents(pythonExe), "utf-8");

  await $`systemctl --user daemon-reload`.quiet().nothrow();
  await $`systemctl --user enable --now ${SYSTEMD_UNIT}`.quiet().nothrow();
}

export async function isLinuxServiceRegistered(): Promise<boolean> {
  try {
    await fs.access(unitPath());
    return true;
  } catch {
    return false;
  }
}

export async function unregisterLinuxService($: Shell): Promise<void> {
  await $`systemctl --user disable --now ${SYSTEMD_UNIT}`.quiet().nothrow();
  await fs.rm(unitPath(), { force: true });
}

/**
 * Restart the systemd user unit. Needed after every gateway source code
 * change (see restartWindowsService for why).
 */
export async function restartLinuxService($: Shell): Promise<void> {
  await $`systemctl --user restart ${SYSTEMD_UNIT}`.quiet().nothrow();
}
