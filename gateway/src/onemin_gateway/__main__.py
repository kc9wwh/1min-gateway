"""Console entry point: `1min-gateway`.

Runs the FastAPI app with uvicorn, bound to the host/port from config (the
plugin's installer picks a free port and writes it into config.json before
registering the service that runs this).
"""

from __future__ import annotations

import argparse
import logging

import uvicorn

from .config import GatewayConfig


def main() -> None:
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
