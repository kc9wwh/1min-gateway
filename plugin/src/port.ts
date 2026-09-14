/**
 * Port selection: try the default (8765), fall back to the next free port.
 * The chosen port is persisted into config.json by the caller so restarts
 * reuse the same one instead of drifting.
 */

import net from "node:net";

export function isPortFree(port: number, host = "127.0.0.1"): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, host);
  });
}

export async function findFreePort(preferred = 8765, host = "127.0.0.1"): Promise<number> {
  if (await isPortFree(preferred, host)) return preferred;
  for (let port = preferred + 1; port < preferred + 200; port++) {
    if (await isPortFree(port, host)) return port;
  }
  throw new Error(`No free port found starting from ${preferred}`);
}

export async function isGatewayHealthy(baseUrl: string): Promise<boolean> {
  try {
    const res = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(1500) });
    return res.ok;
  } catch {
    return false;
  }
}
