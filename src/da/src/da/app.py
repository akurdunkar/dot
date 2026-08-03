"""``da`` -- a tray calendar you navigate and nothing more."""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import sys
from pathlib import Path
from typing import IO

from .log import setup_logging
from .month import WeekStart

log = logging.getLogger(__name__)


def _acquire_instance_lock() -> IO[str]:
    """Take an exclusive advisory lock so only one da runs per user.

    Two instances put two identical icons in the tray, each with its own panel
    and its own grab -- and whichever one grabs second silently loses input.

    The returned file object must stay referenced for the process lifetime.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        lock_path = Path(runtime_dir) / "da.lock"
    else:
        lock_path = Path(f"/tmp/da-{os.getuid()}.lock")

    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Exit 0: an already-running daemon is a satisfied start request, and a
        # non-zero status would make the systemd user unit restart-loop.
        print("da is already running", file=sys.stderr)
        sys.exit(0)
    return lock_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="da",
        description="Tray calendar: a month grid you can page through",
    )
    parser.add_argument(
        "--week-start",
        choices=("monday", "sunday"),
        default="monday",
        help="Leftmost column of the grid (default: %(default)s)",
    )
    parser.add_argument(
        "--week-numbers",
        action="store_true",
        help="Show a column of ISO week numbers",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json-log", action="store_true")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    setup_logging(
        "da",
        level=logging.DEBUG if args.verbose else logging.INFO,
        json_format=args.json_log,
    )

    lock_file = _acquire_instance_lock()

    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    from .clock import DayWatcher
    from .ui.tray import TrayIcon

    week_start = WeekStart.SUNDAY if args.week_start == "sunday" else WeekStart.MONDAY

    def _quit() -> bool:
        log.info("Shutting down")
        Gtk.main_quit()
        # SOURCE_CONTINUE, not None: a handler returning a falsy value removes
        # its own source, so a second signal would go unhandled.
        return GLib.SOURCE_CONTINUE

    tray = TrayIcon(
        on_quit=Gtk.main_quit,
        week_start=week_start,
        show_week_numbers=args.week_numbers,
    )

    day_watcher = DayWatcher(tray.set_today)
    day_watcher.start()

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _quit)

    log.info("Entering GTK main loop (today is %s)", day_watcher.today.isoformat())
    try:
        Gtk.main()
    finally:
        # The tray shutdown must run first and unconditionally: if the panel
        # still holds its seat grab, the pointer and keyboard stay captured for
        # the whole X session after we exit.
        tray.shutdown()
        day_watcher.stop()
        lock_file.close()


if __name__ == "__main__":
    main()
