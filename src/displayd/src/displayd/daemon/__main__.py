"""``python -m displayd.daemon`` -- launch the system watcher daemon."""

from __future__ import annotations

import argparse
import asyncio
import logging

from ..log import setup_logging
from .service import WatcherDaemon


def main() -> None:
    ap = argparse.ArgumentParser(description="displayd system watcher daemon")
    ap.add_argument(
        "--debounce",
        type=float,
        default=2.0,
        help="Debounce window in seconds (default: %(default)s)",
    )
    ap.add_argument(
        "--settle",
        type=float,
        default=3.0,
        help="Hardware settle delay in seconds (default: %(default)s)",
    )
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--json-log", action="store_true")
    args = ap.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging("displayd", level=level, json_format=args.json_log)

    daemon = WatcherDaemon(debounce=args.debounce, settle=args.settle)
    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
