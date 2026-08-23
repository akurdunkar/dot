"""XEmbed system tray icon, compatible with dwm's systray patch.

GTK4 dropped XEmbed entirely, so this speaks the freedesktop system-tray
protocol directly on its own X connection and thread: create a plain
default-depth window, request a dock from the _NET_SYSTEM_TRAY_S<n> owner,
redraw on Expose/resize, and re-dock when a MANAGER message announces a
(re)started tray. The icon is a cairo-drawn clipboard glyph alpha-composited
over whatever the bar paints beneath us (ParentRelative + XGetImage), so it
blends with any bar colour. Clicks are marshalled to the GLib main loop.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import cairo
from gi.repository import GLib
from Xlib import X
from Xlib.display import Display
from Xlib.error import ConnectionClosedError
from Xlib.protocol import event as xevent

from clipd import log

_LOG = log.get(__name__)

_SYSTEM_TRAY_REQUEST_DOCK = 0
_XEMBED_MAPPED = 1
_GLYPH_RGB = (0.92, 0.92, 0.92)  # light grey: legible on dark bars


def _glyph(size: int) -> bytes:
    """Render a clipboard glyph; returns premultiplied BGRA (cairo native)."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    ctx.set_source_rgba(*_GLYPH_RGB, 1.0)
    ctx.set_line_width(max(size / 12.0, 1.0))
    s = float(size)

    def rounded(x: float, y: float, w: float, h: float, r: float) -> None:
        ctx.new_sub_path()
        ctx.arc(x + w - r, y + r, r, -1.5708, 0)
        ctx.arc(x + w - r, y + h - r, r, 0, 1.5708)
        ctx.arc(x + r, y + h - r, r, 1.5708, 3.1416)
        ctx.arc(x + r, y + r, r, 3.1416, 4.7124)
        ctx.close_path()

    rounded(s * 0.18, s * 0.14, s * 0.64, s * 0.78, s * 0.10)  # board
    ctx.stroke()
    rounded(s * 0.36, s * 0.04, s * 0.28, s * 0.16, s * 0.05)  # clip tab
    ctx.fill()
    for frac in (0.42, 0.58, 0.74):  # text lines
        ctx.move_to(s * 0.32, s * frac)
        ctx.line_to(s * 0.68, s * frac)
        ctx.stroke()
    surface.flush()
    return bytes(surface.get_data())


def _composite(bg_bgrx: bytes, fg_bgra: bytes, npix: int) -> bytes:
    """Premultiplied OVER of the glyph onto the grabbed background."""
    out = bytearray(npix * 4)
    for i in range(npix):
        o = i * 4
        a = fg_bgra[o + 3]
        if a == 0:
            out[o : o + 4] = bg_bgrx[o : o + 4]
            continue
        inv = 255 - a
        out[o] = fg_bgra[o] + (bg_bgrx[o] * inv) // 255
        out[o + 1] = fg_bgra[o + 1] + (bg_bgrx[o + 1] * inv) // 255
        out[o + 2] = fg_bgra[o + 2] + (bg_bgrx[o + 2] * inv) // 255
        out[o + 3] = 255
    return bytes(out)


class TrayIcon:
    """on_click(button) is invoked on the GLib main loop (1=left, 3=right)."""

    def __init__(self, on_click: Callable[[int], None]) -> None:
        self._on_click = on_click
        self._size = 22

    def start(self) -> None:
        threading.Thread(target=self._run, name="clipd-tray", daemon=True).start()

    # -- tray thread -------------------------------------------------------

    def _run(self) -> None:
        try:
            self._dpy = Display()
        except Exception as err:
            _LOG.warning("tray disabled: cannot open display (%s)", err)
            return
        dpy = self._dpy
        screen = dpy.screen()
        self._selection = dpy.intern_atom(f"_NET_SYSTEM_TRAY_S{dpy.get_default_screen()}")
        self._opcode = dpy.intern_atom("_NET_SYSTEM_TRAY_OPCODE")
        self._manager = dpy.intern_atom("MANAGER")

        self._win = screen.root.create_window(
            0, 0, self._size, self._size, 0, screen.root_depth,
            window_class=X.InputOutput,
            background_pixmap=X.ParentRelative,
            event_mask=X.ExposureMask | X.StructureNotifyMask | X.ButtonPressMask,
        )
        xembed_info = dpy.intern_atom("_XEMBED_INFO")
        self._win.change_property(xembed_info, xembed_info, 32, [0, _XEMBED_MAPPED])
        self._win.set_wm_name("clipd-tray")  # aids debugging and tests
        self._win.set_wm_class("clipd-tray", "clipd")
        self._gc = self._win.create_gc()

        # Watch for MANAGER announcements *before* probing, to close the race
        # between "no owner yet" and the tray starting up.
        screen.root.change_attributes(event_mask=X.StructureNotifyMask)
        dpy.flush()
        if not self._dock():
            _LOG.info("no system tray yet; waiting for MANAGER announcement")

        while True:
            try:
                ev = dpy.next_event()
                self._dispatch(ev)
            except ConnectionClosedError:
                _LOG.info("X connection closed; tray thread exiting")
                return
            except Exception as err:
                _LOG.debug("tray event error: %s", err)

    def _dock(self) -> bool:
        owner = self._dpy.get_selection_owner(self._selection)
        # Runtime returns a Window resource, or the int X.NONE when unowned;
        # python-xlib's (absent) types make pyright think this is always int.
        if isinstance(owner, int) or owner is None:  # pyright: ignore[reportUnnecessaryIsInstance]
            return False
        message = xevent.ClientMessage(
            window=owner,
            client_type=self._opcode,
            data=(32, [X.CurrentTime, _SYSTEM_TRAY_REQUEST_DOCK, self._win.id, 0, 0]),
        )
        owner.send_event(message)
        self._dpy.flush()
        _LOG.info("docked into system tray")
        return True

    def _dispatch(self, ev: Any) -> None:
        if ev.type == X.ClientMessage and getattr(ev, "client_type", None) == self._manager:
            if ev.data[1][1] == self._selection:
                self._dock()
        elif ev.type == X.ConfigureNotify and ev.window.id == self._win.id:
            self._size = max(min(ev.width, ev.height), 8)
            self._draw()
        elif ev.type == X.Expose and ev.window.id == self._win.id and ev.count == 0:
            self._draw()
        elif ev.type == X.ButtonPress and ev.window.id == self._win.id:
            button = int(ev.detail)
            _LOG.debug("tray click button=%d", button)
            GLib.idle_add(self._on_click, button)
        elif ev.type == X.ReparentNotify and ev.window.id == self._win.id:
            root = self._dpy.screen().root
            if ev.parent.id == root.id:
                _LOG.info("tray went away; waiting for a new one")

    def _draw(self) -> None:
        size = self._size
        self._win.clear_area(width=size, height=size)  # paint inherited background
        try:
            bg = self._win.get_image(0, 0, size, size, X.ZPixmap, 0xFFFFFFFF).data
        except Exception:  # not viewable yet, or tray mid-restart
            bg = bytes([0x22, 0x22, 0x22, 0x00] * (size * size))
        pixels = _composite(bg, _glyph(size), size * size)
        self._win.put_image(
            self._gc, 0, 0, size, size, X.ZPixmap, self._dpy.screen().root_depth, 0, pixels
        )
        self._dpy.flush()
