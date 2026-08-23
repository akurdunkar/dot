"""Synthetic paste keystrokes via XTEST, terminal-aware.

After the popup hides, focus returns to the target window; a fake
Ctrl+V (or Ctrl+Shift+V for terminals, which treat Ctrl+V as a literal)
pastes the selection there. Runs on the GLib main thread with its own
short-lived-safe Display connection.
"""

from __future__ import annotations

from Xlib import X, XK
from Xlib.display import Display
from Xlib.ext import xtest

from clipd import log

_LOG = log.get(__name__)

_TERMINAL_CLASSES = frozenset(
    {
        "st", "st-256color", "alacritty", "kitty", "xterm", "urxvt", "rxvt",
        "wezterm", "org.wezfurlong.wezterm", "gnome-terminal-server",
        "xfce4-terminal", "konsole", "terminator", "tilix", "eterm",
    }
)


class Paster:
    def __init__(self) -> None:
        self._dpy: Display | None = None

    def _display(self) -> Display:
        if self._dpy is None:
            self._dpy = Display()
        return self._dpy

    def focused_is_terminal(self) -> bool:
        try:
            dpy = self._display()
            window = dpy.get_input_focus().focus
            for _ in range(16):  # climb to the window that carries WM_CLASS
                if window in (X.NONE, X.PointerRoot) or window == dpy.screen().root:
                    return False
                wm_class = window.get_wm_class()
                if wm_class:
                    return any(part.lower() in _TERMINAL_CLASSES for part in wm_class)
                window = window.query_tree().parent
        except Exception as err:  # X errors must never break a paste
            _LOG.debug("focus inspection failed: %s", err)
        return False

    def paste(self, shift: bool) -> None:
        try:
            dpy = self._display()
            keycode_v = dpy.keysym_to_keycode(XK.string_to_keysym("v"))
            keycode_ctrl = dpy.keysym_to_keycode(XK.string_to_keysym("Control_L"))
            keycode_shift = dpy.keysym_to_keycode(XK.string_to_keysym("Shift_L"))
            mods = [keycode_ctrl] + ([keycode_shift] if shift else [])
            for code in mods:
                xtest.fake_input(dpy, X.KeyPress, code)
            xtest.fake_input(dpy, X.KeyPress, keycode_v)
            xtest.fake_input(dpy, X.KeyRelease, keycode_v)
            for code in reversed(mods):
                xtest.fake_input(dpy, X.KeyRelease, code)
            dpy.flush()
        except Exception as err:
            _LOG.warning("XTEST paste failed: %s", err)
            self._dpy = None  # reconnect next time
