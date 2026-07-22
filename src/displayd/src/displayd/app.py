"""``displayd`` -- single-process display management daemon with tray UI."""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import IO

from .engine import Engine
from .log import setup_logging

log = logging.getLogger(__name__)

DEFAULT_PROFILE_DIR = Path(
    os.environ.get(
        "DISPLAYD_PROFILE_DIR",
        os.path.expanduser("~/.config/displayd/profiles"),
    )
)


def _acquire_instance_lock() -> IO[str]:
    """Take an exclusive advisory lock so only one displayd runs per user.

    The returned file object must stay referenced for the process lifetime.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        lock_path = Path(runtime_dir) / "displayd.lock"
    else:
        lock_path = Path(f"/tmp/displayd-{os.getuid()}.lock")

    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Exit 0: an already-running daemon is a satisfied start request, and
        # a non-zero status would make the systemd user unit restart-loop.
        print("displayd is already running", file=sys.stderr)
        sys.exit(0)
    return lock_file


def _run_headless(engine: Engine) -> None:
    stop = threading.Event()

    def _handler(signum: int, frame: object) -> None:
        log.info("Received signal %d; shutting down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
    log.info("Running headless (no tray)")
    stop.wait()


def _run_tray(engine: Engine, *, open_editor: bool) -> None:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    from .ui.editor import LayoutEditorWindow
    from .ui.tray import TrayIcon

    def _quit() -> None:
        Gtk.main_quit()

    tray = TrayIcon(engine, on_quit=_quit)
    if open_editor:
        LayoutEditorWindow.open(engine)

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _quit)

    log.info("Entering GTK main loop (tray=%r)", type(tray).__name__)
    Gtk.main()


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="displayd",
        description="Display management daemon with tray icon and layout editor",
    )
    ap.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Profile directory (default: %(default)s)",
    )
    ap.add_argument(
        "--cooldown",
        type=float,
        default=30.0,
        help="Manual-change cooldown seconds (default: %(default)s)",
    )
    ap.add_argument(
        "--retries",
        type=int,
        default=5,
        help="Max apply retries (default: %(default)s)",
    )
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
    ap.add_argument(
        "--no-tray",
        action="store_true",
        help="Run the engine headless without any GTK UI",
    )
    ap.add_argument(
        "--editor",
        action="store_true",
        help="Open the layout editor window at startup",
    )
    args = ap.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging("displayd", level=level, json_format=args.json_log)

    lock_file = _acquire_instance_lock()

    engine = Engine(
        profile_dir=args.profile_dir,
        cooldown=args.cooldown,
        retries=args.retries,
        debounce=args.debounce,
        settle=args.settle,
    )
    engine.start()
    try:
        if args.no_tray:
            _run_headless(engine)
        else:
            _run_tray(engine, open_editor=args.editor)
    finally:
        engine.stop()
        lock_file.close()


if __name__ == "__main__":
    main()
