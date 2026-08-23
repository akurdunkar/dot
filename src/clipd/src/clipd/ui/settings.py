"""Preferences dialog: edits Config fields in place, saves on every change."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from clipd.config import Config


def _switch(title: str, subtitle: str, value: bool, setter: Callable[[bool], None]) -> Adw.SwitchRow:
    row = Adw.SwitchRow(title=title, subtitle=subtitle, active=value)

    def on_toggle(widget: Adw.SwitchRow, _pspec: object) -> None:
        setter(widget.get_active())

    row.connect("notify::active", on_toggle)
    return row


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(
        self,
        config: Config,
        on_change: Callable[[], None],
        on_clear: Callable[[], None],
    ) -> None:
        super().__init__(title="Preferences")
        self._config = config
        self._on_change = on_change

        def changed(apply: Callable[[], None]) -> None:
            apply()
            config.save()
            on_change()

        page = Adw.PreferencesPage()

        history = Adw.PreferencesGroup(title="History")
        cap = Adw.SpinRow.new_with_range(50, 10_000, 50)
        cap.set_title("History size")
        cap.set_subtitle("Unpinned entries kept; pinned ones never expire")
        cap.set_value(config.history_cap)

        def on_cap(widget: Adw.SpinRow, _pspec: object) -> None:
            changed(lambda: setattr(config, "history_cap", int(widget.get_value())))

        cap.connect("notify::value", on_cap)
        history.add(cap)
        history.add(
            _switch(
                "Capture images",
                "Store copied images, not just text",
                config.capture_images,
                lambda v: changed(lambda: setattr(config, "capture_images", v)),
            )
        )
        clear = Adw.ActionRow(title="Clear history", subtitle="Remove all unpinned entries")
        button = Gtk.Button(label="Clear", valign=Gtk.Align.CENTER)
        button.add_css_class("destructive-action")
        button.connect("clicked", lambda *_: on_clear())
        clear.add_suffix(button)
        history.add(clear)
        page.add(history)

        paste = Adw.PreferencesGroup(title="Paste")
        paste.add(
            _switch(
                "Auto-paste on select",
                "Send a paste keystroke to the focused window after copying",
                config.auto_paste,
                lambda v: changed(lambda: setattr(config, "auto_paste", v)),
            )
        )
        paste.add(
            _switch(
                "Terminal-aware paste",
                "Use Ctrl+Shift+V when a terminal is focused",
                config.terminal_shift_paste,
                lambda v: changed(lambda: setattr(config, "terminal_shift_paste", v)),
            )
        )
        page.add(paste)

        behaviour = Adw.PreferencesGroup(title="Behaviour")
        behaviour.add(
            _switch(
                "Hide on focus loss",
                "Dismiss the popup when it loses focus",
                config.hide_on_focus_loss,
                lambda v: changed(lambda: setattr(config, "hide_on_focus_loss", v)),
            )
        )
        shortcut = Adw.ActionRow(
            title="Global shortcut",
            subtitle="Super+V \u2014 bound in dwm's config.h, spawning \u201cclipd toggle\u201d",
        )
        shortcut.add_suffix(Gtk.Image.new_from_icon_name("input-keyboard-symbolic"))
        behaviour.add(shortcut)
        page.add(behaviour)

        self.add(page)
