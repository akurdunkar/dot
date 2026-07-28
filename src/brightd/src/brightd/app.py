"""``brightd`` -- tray brightness control for internal and DDC/CI displays."""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import sys
from pathlib import Path
from typing import IO

from .backends.base import Backlight
from .backends.sysfs import DEFAULT_MIN_FRACTION
from .controller import Controller
from .displays import build_backlights, external_backlights
from .log import setup_logging
from .types import DdcAvailability

log = logging.getLogger(__name__)


def _acquire_instance_lock() -> IO[str]:
    """Take an exclusive advisory lock so only one brightd runs per user.

    Two instances would each hold a write fd and each suppress only its *own*
    echo, so every write by one would look like an external change to the
    other -- and the two would fight each other into a write loop.

    The returned file object must stay referenced for the process lifetime.
    ``brightd-ctl`` deliberately does not take this lock.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        lock_path = Path(runtime_dir) / "brightd.lock"
    else:
        lock_path = Path(f"/tmp/brightd-{os.getuid()}.lock")

    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Exit 0: an already-running daemon is a satisfied start request, and a
        # non-zero status would make the systemd user unit restart-loop.
        print("brightd is already running", file=sys.stderr)
        sys.exit(0)
    return lock_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brightd",
        description="Screen brightness tray applet with a slider panel",
    )
    parser.add_argument(
        "--min-fraction",
        type=float,
        default=DEFAULT_MIN_FRACTION,
        help="Floor as a fraction of maximum, so 0%% is dim rather than black "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--device",
        help="Backlight device name under /sys/class/backlight (default: auto-detect)",
    )
    parser.add_argument(
        "--no-ddc",
        action="store_true",
        help="Skip external monitors entirely; control the internal panel only",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json-log", action="store_true")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    setup_logging(
        "brightd",
        level=logging.DEBUG if args.verbose else logging.INFO,
        json_format=args.json_log,
    )

    lock_file = _acquire_instance_lock()

    backlights, availability = build_backlights(
        min_fraction=args.min_fraction,
        device_name=args.device,
        enable_ddc=not args.no_ddc,
    )
    if not backlights:
        log.error("No controllable displays found; nothing to do")
        sys.exit(1)
    if availability is not DdcAvailability.OK and not args.no_ddc:
        log.info("External monitors: %s", availability.message)
    log.info("Controlling %d display(s): %s", len(backlights), ", ".join(b.info.id for b in backlights))

    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    from .ui.tray import TrayIcon
    from .watcher import BacklightWatcher

    controller = Controller(backlights)

    def _quit() -> bool:
        log.info("Shutting down")
        Gtk.main_quit()
        # SOURCE_CONTINUE, not None: a handler returning a falsy value removes
        # its own source, so a second signal would go unhandled.
        return GLib.SOURCE_CONTINUE

    def _rescan() -> None:
        """Re-detect external monitors, keeping the internal panel as-is."""
        if args.no_ddc:
            return
        internal = controller.internal
        combined: list[Backlight] = [internal] if internal is not None else []
        external, reason = external_backlights()
        combined.extend(external)
        controller.set_backlights(combined)
        tray.rebuild_rows()
        log.info("Rescan found %d external display(s) (%s)", len(external), reason.message)

    tray = TrayIcon(controller, on_quit=Gtk.main_quit, on_rescan=_rescan)

    watcher: BacklightWatcher | None = None
    kernel_backlight = controller.sysfs_backlight
    if kernel_backlight is not None:
        watcher = BacklightWatcher(kernel_backlight, controller)
        watcher.start()

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _quit)

    log.info("Entering GTK main loop")
    try:
        Gtk.main()
    finally:
        # The tray shutdown must run first and unconditionally: if the panel
        # still holds its seat grab, the pointer and keyboard stay captured for
        # the whole X session after we exit.
        tray.shutdown()
        if watcher is not None:
            watcher.stop()
        controller.close()
        lock_file.close()


if __name__ == "__main__":
    main()
