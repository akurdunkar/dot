"""Logging setup: stderr, journald-friendly (no timestamps; journald adds them)."""

import logging
import os


def setup() -> None:
    level = logging.DEBUG if os.environ.get("CLIPD_DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


def get(name: str) -> logging.Logger:
    return logging.getLogger(name.removeprefix("clipd."))
