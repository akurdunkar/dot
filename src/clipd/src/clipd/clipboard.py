"""Clipboard capture and re-copy on top of Gdk.Clipboard.

GDK's clipboard already speaks XFixes, INCR and MIME/target negotiation, so
this stays a thin policy layer: watch the "changed" signal, coalesce the
burst of notifications a single copy produces (an owner change fires once
before TARGETS arrive and once after), then read the best representation:
image > file list > text. Copying back hands GDK a content provider, which
keeps serving the selection for as long as the daemon lives.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject

from clipd import log
from clipd.config import Config
from clipd.store import KIND_IMAGE, KIND_TEXT, KIND_URIS, Entry, Store

_LOG = log.get(__name__)
_COALESCE_MS = 90
_THUMB_MAX = 256  # px, longest side
_PASSWORD_HINT = "x-kde-passwordManagerHint"

OnEntry = Callable[[Entry, bool], None]  # (entry, created)


def _text_value(text: str) -> GObject.Value:
    """Build a GObject.Value explicitly (the stubs reject the shorthand ctor)."""
    boxed = GObject.Value()
    boxed.init(str)
    boxed.set_string(text)
    return boxed


def _object_value(gtype: type, obj: GObject.Object) -> GObject.Value:
    boxed = GObject.Value()
    boxed.init(gtype)
    boxed.set_object(obj)
    return boxed


def _thumbnail(png: bytes) -> bytes | None:
    """Downscale PNG bytes to a small PNG thumbnail; None if it fails or is tiny."""
    try:
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(png)
        loader.close()
        pixbuf = loader.get_pixbuf()
        if pixbuf is None:
            return None
        w, h = pixbuf.get_width(), pixbuf.get_height()
        scale = _THUMB_MAX / max(w, h)
        if scale < 1.0:
            pixbuf = pixbuf.scale_simple(
                max(int(w * scale), 1), max(int(h * scale), 1), GdkPixbuf.InterpType.BILINEAR
            )
            if pixbuf is None:
                return None
        ok, buf = pixbuf.save_to_bufferv("png", [], [])
        return bytes(buf) if ok else None
    except GLib.Error as err:
        _LOG.warning("thumbnail failed: %s", err.message)
        return None


class ClipboardService:
    def __init__(
        self, clipboard: Gdk.Clipboard, store: Store, config: Config, on_entry: OnEntry
    ) -> None:
        self._clipboard = clipboard
        self._store = store
        self._config = config
        self._on_entry = on_entry
        self._pending: int = 0  # GLib source id of the coalescing timer

    def start(self) -> None:
        self._clipboard.connect("changed", self._on_changed)

    # -- capture ---------------------------------------------------------

    def _on_changed(self, clipboard: Gdk.Clipboard) -> None:
        if clipboard.is_local():
            return  # our own set_content; already stored
        if self._pending:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(_COALESCE_MS, self._capture)

    def _capture(self) -> bool:
        self._pending = 0
        if self._clipboard.is_local():
            return False  # we took ownership while the timer was pending
        formats = self._clipboard.get_formats()
        if formats.contain_mime_type(_PASSWORD_HINT):
            _LOG.debug("skipping clipboard content marked as secret")
        elif formats.contain_mime_type("image/png") or formats.contain_gtype(Gdk.Texture):
            if self._config.capture_images:
                self._clipboard.read_texture_async(None, self._texture_read)
        elif formats.contain_mime_type("text/uri-list"):
            self._clipboard.read_value_async(
                Gdk.FileList, GLib.PRIORITY_DEFAULT, None, self._uris_read
            )
        else:
            self._clipboard.read_text_async(None, self._text_read)
        return False

    def _text_read(self, clipboard: Gdk.Clipboard, result: Gio.AsyncResult) -> None:
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error as err:
            _LOG.warning("text read failed: %s", err.message)
            return
        if text is None or not text.strip():
            return
        if len(text.encode()) > self._config.max_text_bytes:
            _LOG.info("ignoring oversized text (> %d bytes)", self._config.max_text_bytes)
            return
        self._ingest(KIND_TEXT, text=text)

    def _uris_read(self, clipboard: Gdk.Clipboard, result: Gio.AsyncResult) -> None:
        try:
            value = clipboard.read_value_finish(result)
            uris = [f.get_uri() for f in value.get_files()]
        except GLib.Error as err:
            _LOG.debug("uri read failed (%s); falling back to text", err.message)
            clipboard.read_text_async(None, self._text_read)
            return
        if uris:
            self._ingest(KIND_URIS, text="\n".join(uris))

    def _texture_read(self, clipboard: Gdk.Clipboard, result: Gio.AsyncResult) -> None:
        try:
            texture = clipboard.read_texture_finish(result)
        except GLib.Error as err:
            _LOG.warning("image read failed: %s", err.message)
            return
        if texture is None:
            return
        png = texture.save_to_png_bytes().get_data()
        if png is None or len(png) > self._config.max_image_bytes:
            _LOG.info("ignoring oversized image (> %d bytes)", self._config.max_image_bytes)
            return
        png = bytes(png)
        self._ingest(
            KIND_IMAGE,
            data=png,
            thumb=_thumbnail(png),
            width=texture.get_width(),
            height=texture.get_height(),
        )

    def _ingest(
        self,
        kind: str,
        *,
        text: str = "",
        data: bytes | None = None,
        thumb: bytes | None = None,
        width: int = 0,
        height: int = 0,
    ) -> None:
        entry, created = self._store.add(
            kind, text=text, data=data, thumb=thumb, width=width, height=height
        )
        if created:
            self._store.prune(self._config.history_cap)
        _LOG.debug("%s %s #%d", "captured" if created else "bumped", kind, entry.id)
        self._on_entry(entry, created)

    # -- re-copy ---------------------------------------------------------

    def copy_entry(self, entry: Entry) -> bool:
        """Own the clipboard with the entry's content. Returns False if gone."""
        if entry.kind == KIND_IMAGE:
            data = self._store.data(entry.id)
            if data is None:
                return False
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            provider = Gdk.ContentProvider.new_for_value(_object_value(Gdk.Texture, texture))
        elif entry.kind == KIND_URIS:
            uri_text = entry.text.replace("\n", "\r\n") + "\r\n"
            paths = "\n".join(
                Gio.File.new_for_uri(u).get_path() or u for u in entry.text.splitlines()
            )
            provider = Gdk.ContentProvider.new_union(
                [
                    Gdk.ContentProvider.new_for_bytes(
                        "text/uri-list", GLib.Bytes.new(uri_text.encode())
                    ),
                    Gdk.ContentProvider.new_for_bytes(
                        "x-special/gnome-copied-files",
                        GLib.Bytes.new(b"copy\n" + entry.text.encode()),
                    ),
                    Gdk.ContentProvider.new_for_value(_text_value(paths)),
                ]
            )
        else:
            provider = Gdk.ContentProvider.new_for_value(_text_value(entry.text))
        if not self._clipboard.set_content(provider):
            _LOG.warning("failed to claim clipboard for #%d", entry.id)
            return False
        self._store.touch(entry.id)
        return True
