"""Console entry point: `1min-gateway`.

Runs the FastAPI app with uvicorn, bound to the host/port from config (the
plugin's installer picks a free port and writes it into config.json before
registering the service that runs this).
"""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from .config import GatewayConfig, config_dir


def _redirect_stdio_to_log() -> None:
    """When run under pythonw.exe, sys.stdout/sys.stderr are None and any
    write to them raises (or, on Windows, causes the process to exit with a
    silent code 1). Redirect them to a log file so the gateway can run as a
    truly windowless background service with no console and no wrapper."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = config_dir() / "gateway.log"
    stream = open(log_path, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> None:
    _redirect_stdio_to_log()

    parser = argparse.ArgumentParser(prog="1min-gateway")
    parser.add_argument("--host", default=None, help="Override config host")
    parser.add_argument("--port", type=int, default=None, help="Override config port")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level.upper())

    config = GatewayConfig.load()
    host = args.host or config.host
    port = args.port or config.port

    uvicorn.run("onemin_gateway.app:app", host=host, port=port, log_level=args.log_level)


if __name__ == "__main__":
    main()
