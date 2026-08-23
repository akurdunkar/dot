"""List row widget, built for Gtk.ListView recycling.

One row layout serves every entry kind: a pin marker, an optional image
thumbnail, and a single-line label. bind() reconfigures all of it, so
recycled rows never leak state. Fuzzy-match positions are painted with
Pango attributes (bold + accent colour); attribute indices are byte
offsets into the UTF-8 text, hence the cumulative encoding below.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk, Pango

from clipd.search import Matcher
from clipd.store import KIND_IMAGE, KIND_URIS, Entry

_PREVIEW_CHARS = 240
_THUMB_HEIGHT = 64
# Accent for match highlighting, per style (Adwaita blues, 16-bit channels).
_ACCENT_DARK = (0x78 * 257, 0xAE * 257, 0xED * 257)
_ACCENT_LIGHT = (0x1A * 257, 0x5F * 257, 0xB4 * 257)

_FLATTEN = str.maketrans({"\n": " ", "\r": " ", "\t": " "})


class EntryObject(GObject.Object):
    """Store row wrapped for Gio.ListStore, with lazy-decoded thumbnail."""

    def __init__(self, entry: Entry) -> None:
        super().__init__()
        self.entry = entry
        self.hay = entry.preview  # fuzzy-search haystack == what the row displays
        self._texture: Gdk.Texture | None = None

    def texture(self) -> Gdk.Texture | None:
        if self._texture is None and self.entry.thumb is not None:
            try:
                self._texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(self.entry.thumb))
            except GLib.Error:
                return None
        return self._texture


def _highlight(text: str, positions: list[int]) -> Pango.AttrList | None:
    if not positions:
        return None
    dark = Adw.StyleManager.get_default().get_dark()
    red, green, blue = _ACCENT_DARK if dark else _ACCENT_LIGHT
    # Cumulative char->byte offsets (Pango attributes index UTF-8 bytes).
    offsets = [0]
    for ch in text:
        offsets.append(offsets[-1] + len(ch.encode()))
    attrs = Pango.AttrList()
    # Coalesce consecutive positions into runs: fewer attributes, faster layout.
    runs: list[tuple[int, int]] = []
    for pos in positions:
        if pos >= len(text):
            break
        if runs and runs[-1][1] == pos:
            runs[-1] = (runs[-1][0], pos + 1)
        else:
            runs.append((pos, pos + 1))
    for start, end in runs:
        for attr in (
            Pango.attr_weight_new(Pango.Weight.BOLD),
            Pango.attr_foreground_new(red, green, blue),
        ):
            attr.start_index = offsets[start]
            attr.end_index = offsets[end]
            attrs.insert(attr)
    return attrs


class EntryRow(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_top(5)
        self.set_margin_bottom(5)

        self._pin = Gtk.Image.new_from_icon_name("view-pin-symbolic")
        self._pin.add_css_class("accent")
        self._picture = Gtk.Picture()
        self._picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._picture.set_size_request(-1, _THUMB_HEIGHT)
        self._picture.add_css_class("card")
        self._kind = Gtk.Image()
        self._label = Gtk.Label(xalign=0.0, hexpand=True)
        self._label.set_ellipsize(Pango.EllipsizeMode.END)
        self._label.set_single_line_mode(True)

        self.append(self._pin)
        self.append(self._kind)
        self.append(self._picture)
        self.append(self._label)

    def bind(self, obj: EntryObject, matcher: Matcher) -> None:
        entry = obj.entry
        self._pin.set_visible(entry.pinned)
        display = obj.hay.translate(_FLATTEN)[:_PREVIEW_CHARS]

        texture = obj.texture() if entry.kind == KIND_IMAGE else None
        self._picture.set_visible(texture is not None)
        self._picture.set_paintable(texture)
        self._kind.set_visible(entry.kind == KIND_URIS)
        if entry.kind == KIND_URIS:
            self._kind.set_from_icon_name("folder-symbolic")

        self._label.set_text(display)
        positions = [] if matcher.empty else matcher.positions(obj.hay)
        self._label.set_attributes(_highlight(display, positions))
        if entry.kind == KIND_IMAGE:
            self._label.add_css_class("dim-label")
        else:
            self._label.remove_css_class("dim-label")
