"""Notice brightness changes made by something other than brightd.

The kernel raises ``POLLPRI`` on ``actual_brightness`` whenever the backlight
moves, so a GLib fd watch keeps the slider honest when the user changes
brightness with a hotkey, ``brightd-ctl``, or any other tool -- with no polling
timer, no thread, and no udev dependency.

Three details make or break this watch, all of them silent failures:

* ``G_IO_ERR`` is *always* reported alongside ``G_IO_PRI`` on a sysfs
  attribute.  Treating it as fatal removes the source on the very first event.
* The descriptor must be re-read to EOF on every wakeup or ``poll()`` reports
  ready forever and spins a core.
* The callback must return ``True``, or the watch is removed after one event.
"""

from __future__ import annotations

import logging

from gi.repository import GLib

from .backends.sysfs import SysfsBacklight
from .controller import Controller

log = logging.getLogger(__name__)


class BacklightWatcher:
    """Watches one kernel backlight for externally applied changes."""

    def __init__(self, backlight: SysfsBacklight, controller: Controller) -> None:
        self._backlight = backlight
        self._controller = controller
        self._fd: int | None = None
        self._source_id: int | None = None

    def start(self) -> bool:
        """Begin watching.  Returns ``False`` if the device cannot be polled."""
        try:
            self._fd = self._backlight.open_change_watch()
        except OSError as exc:
            log.warning("Cannot watch %s for changes: %s", self._backlight.info.id, exc)
            return False
        self._source_id = GLib.unix_fd_add_full(
            GLib.PRIORITY_DEFAULT,
            self._fd,
            GLib.IOCondition.PRI | GLib.IOCondition.ERR,
            self._on_ready,
        )
        log.debug("Watching %s for external brightness changes", self._backlight.info.id)
        return True

    def _on_ready(self, fd: int, _condition: GLib.IOCondition) -> bool:
        try:
            SysfsBacklight.drain_change_watch(fd)
            raw = self._backlight.read_raw()
        except OSError as exc:
            log.warning("Backlight watch read failed: %s", exc)
            return True  # keep the source: a transient read error is not fatal
        if self._backlight.is_own_echo(raw):
            return True
        percent = self._backlight.percent_of(raw)
        log.debug("External brightness change: raw=%d (%.1f%%)", raw, percent)
        self._controller.note_external_change(self._backlight.info.id, percent)
        return True

    def stop(self) -> None:
        if self._source_id is not None:
            GLib.source_remove(self._source_id)
            self._source_id = None
        if self._fd is not None:
            import os

            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
