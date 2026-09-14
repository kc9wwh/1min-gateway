/**
 * Windows service registration: a Scheduled Task that runs the gateway at
 * logon. Uses `schtasks` (built into every Windows install) rather than
 * NSSM, since we can't assume NSSM is present; NSSM support can be added
 * later as a nicer-behaved alternative when detected on PATH.
 */

import { Shell, SERVICE_NAME } from "./common.js";

export async function registerWindowsService(
  $: Shell,
  pythonExe: string,
): Promise<void> {
  // /TR takes a single command-line string. Because the python path itself
  // may contain spaces (e.g. under "Program Files"), it needs its own
  // inner quotes, and the whole thing needs outer quotes as the /TR value.
  // `{ raw: ... }` bypasses Bun's automatic escaping so these literal
  // quotes reach schtasks unmangled.
  const trArg = `"\\"${pythonExe}\\" -m onemin_gateway"`;
  await $`schtasks /Create /TN ${SERVICE_NAME} /TR ${{ raw: trArg }} /SC ONLOGON /RL LIMITED /F`
    .quiet()
    .nothrow();
  await $`schtasks /Run /TN ${SERVICE_NAME}`.quiet().nothrow();
}

export async function isWindowsServiceRegistered($: Shell): Promise<boolean> {
  const result = await $`schtasks /Query /TN ${SERVICE_NAME}`.quiet().nothrow();
  return result.exitCode === 0;
}

export async function unregisterWindowsService($: Shell): Promise<void> {
  await $`schtasks /Delete /TN ${SERVICE_NAME} /F`.quiet().nothrow();
}
