"""``brightd-ctl`` -- one-shot brightness commands.

Deliberately has no IPC with the daemon.  It writes the hardware directly and
the running brightd notices through its ``POLLPRI`` watch, so the CLI works
identically whether or not the daemon is running, and there is no socket or
protocol to keep in step.

This is what dwm's brightness keys should be bound to: ``xbacklight`` is a
silent no-op on modern i915 (there is no RandR ``BACKLIGHT`` property to set),
so the existing bindings do nothing.

Imports no GTK, so the keys stay fast.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .backends.base import Backlight
from .backends.sysfs import DEFAULT_MIN_FRACTION
from .displays import build_backlights
from .types import BacklightError, DisplayKind

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1


def _resolve(backlights: list[Backlight], display_id: str | None) -> Backlight | None:
    """Pick the display to act on: the named one, else the internal panel."""
    if display_id is not None:
        for backlight in backlights:
            if backlight.info.id == display_id:
                return backlight
        return None
    for backlight in backlights:
        if backlight.info.kind is DisplayKind.INTERNAL:
            return backlight
    return backlights[0] if backlights else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brightd-ctl",
        description="Get or set display brightness",
    )
    parser.add_argument(
        "-d",
        "--display",
        help="Display id to act on, e.g. eDP-1 (default: the internal panel)",
    )
    parser.add_argument(
        "--min-fraction",
        type=float,
        default=DEFAULT_MIN_FRACTION,
        help="Floor as a fraction of maximum (default: %(default)s). "
        "Must match the running daemon or the two will disagree about 0%%.",
    )
    parser.add_argument(
        "--no-ddc",
        action="store_true",
        help="Skip external monitors (faster; avoids probing DDC)",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List controllable displays and their levels")
    sub.add_parser("get", help="Print the current brightness percentage")

    set_parser = sub.add_parser("set", help="Set brightness to a percentage")
    set_parser.add_argument("percent", type=float)

    up_parser = sub.add_parser("up", help="Increase brightness")
    up_parser.add_argument("step", type=float, nargs="?", default=5.0)

    down_parser = sub.add_parser("down", help="Decrease brightness")
    down_parser.add_argument("step", type=float, nargs="?", default=5.0)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    # `list` is the only command that benefits from probing DDC when no display
    # was named; the rest act on the internal panel, so skip the slow path.
    want_ddc = not args.no_ddc and (args.command == "list" or args.display is not None)
    backlights, _availability = build_backlights(
        min_fraction=args.min_fraction, enable_ddc=want_ddc
    )
    if not backlights:
        print("brightd-ctl: no controllable displays found", file=sys.stderr)
        return EXIT_ERROR

    try:
        if args.command == "list":
            for backlight in backlights:
                info = backlight.info
                kind = "internal" if info.kind is DisplayKind.INTERNAL else "external"
                print(f"{info.id}\t{backlight.read_percent():5.1f}%\t{kind}\t{info.label}")
            return EXIT_OK

        target = _resolve(backlights, args.display)
        if target is None:
            print(f"brightd-ctl: no such display: {args.display}", file=sys.stderr)
            return EXIT_ERROR

        if args.command == "get":
            print(f"{target.read_percent():.0f}")
            return EXIT_OK

        if args.command == "set":
            percent = args.percent
        else:
            step = args.step if args.command == "up" else -args.step
            percent = target.read_percent() + step

        target.write_percent(max(0.0, min(100.0, percent)))
        print(f"{target.read_percent():.0f}")
        return EXIT_OK
    except BacklightError as exc:
        print(f"brightd-ctl: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        for backlight in backlights:
            backlight.close()


if __name__ == "__main__":
    sys.exit(main())
