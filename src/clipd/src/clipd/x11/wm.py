"""WM dressing GTK4 no longer exposes: dialog window type and placement.

dwm floats windows whose _NET_WM_WINDOW_TYPE is DIALOG, and honours
configure requests from floating clients, so the popup marks itself a
dialog before mapping and re-centers itself on the monitor holding the
pointer each time it is shown. Degrades to root-screen centering when
Xinerama is unavailable (bare Xvfb).
"""

from __future__ import annotations

from Xlib import X
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

    def focus_target(self) -> str:
        """Classify the current X input focus: 'client', 'root' or 'other'.

        Managed application windows carry WM_STATE (on themselves or an
        ancestor). Screenshot overlays, shell HUDs and grabs are unmanaged
        (no WM_STATE) or leave focus on None — those report 'other', so the
        popup can ignore them instead of dismissing itself.
        """
        try:
            dpy = self._display()
            focus = dpy.get_input_focus().focus
            if isinstance(focus, int):
                # X.NONE, or the PointerRoot revert state left behind by a
                # dying grab/overlay — indeterminate, never a reason to act.
                # (A desktop click under dwm focuses the real root window,
                # which is classified below.)
                return "other"
            root = dpy.screen().root
            if focus.id == root.id:
                return "root"
            wm_state = dpy.intern_atom("WM_STATE")
            window = focus
            for _ in range(16):
                if window.get_full_property(wm_state, X.AnyPropertyType) is not None:
                    return "client"
                parent = window.query_tree().parent
                if isinstance(parent, int) or parent.id == root.id:
                    break
                window = parent
            return "other"
        except Exception as err:
            _LOG.debug("focus inspection failed: %s", err)
            return "other"

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
