"""WM dressing GTK4 no longer exposes: dialog window type and placement.

dwm floats windows whose _NET_WM_WINDOW_TYPE is DIALOG, and honours
configure requests from floating clients, so the popup marks itself a
dialog before mapping and re-centers itself on the monitor holding the
pointer each time it is shown. Degrades to root-screen centering when
Xinerama is unavailable (bare Xvfb).
"""

from __future__ import annotations

from Xlib.display import Display

from clipd import log

_LOG = log.get(__name__)


class WindowDresser:
    def __init__(self) -> None:
        self._dpy: Display | None = None

    def _display(self) -> Display:
        if self._dpy is None:
            self._dpy = Display()
        return self._dpy

    def make_dialog(self, xid: int) -> None:
        try:
            dpy = self._display()
            window = dpy.create_resource_object("window", xid)
            window.change_property(
                dpy.intern_atom("_NET_WM_WINDOW_TYPE"),
                dpy.intern_atom("ATOM"),
                32,
                [dpy.intern_atom("_NET_WM_WINDOW_TYPE_DIALOG")],
            )
            dpy.flush()
        except Exception as err:
            _LOG.warning("dialog hint failed: %s", err)

    def _pointer_monitor(self) -> tuple[int, int, int, int]:
        dpy = self._display()
        screen = dpy.screen()
        pointer = screen.root.query_pointer()
        px, py = pointer.root_x, pointer.root_y
        try:
            for mon in dpy.xinerama_query_screens().screens:
                if mon.x <= px < mon.x + mon.width and mon.y <= py < mon.y + mon.height:
                    return mon.x, mon.y, mon.width, mon.height
        except Exception:
            pass
        return 0, 0, screen.width_in_pixels, screen.height_in_pixels

    def center(self, xid: int, width: int, height: int) -> None:
        """Center the (mapped) window on the monitor containing the pointer."""
        try:
            dpy = self._display()
            mx, my, mw, mh = self._pointer_monitor()
            window = dpy.create_resource_object("window", xid)
            window.configure(x=mx + (mw - width) // 2, y=my + max((mh - height) // 3, 0))
            dpy.flush()
        except Exception as err:
            _LOG.warning("centering failed: %s", err)

    def place_near_pointer(self, xid: int, width: int, height: int) -> None:
        """Put a (mapped) window next to the pointer, clamped to its monitor."""
        try:
            dpy = self._display()
            pointer = dpy.screen().root.query_pointer()
            mx, my, mw, mh = self._pointer_monitor()
            x = min(max(pointer.root_x - width // 2, mx), mx + mw - width)
            y = pointer.root_y + 8
            if y + height > my + mh:  # pointer near the bottom edge: open upwards
                y = pointer.root_y - height - 8
            window = dpy.create_resource_object("window", xid)
            window.configure(x=x, y=max(y, my))
            dpy.flush()
        except Exception as err:
            _LOG.warning("menu placement failed: %s", err)
