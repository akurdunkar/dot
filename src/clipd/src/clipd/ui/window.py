"""Search popup: a hidden, always-alive window so summoning it is instant.

Keyboard-first: every printable key lands in the search entry no matter
what has focus (set_key_capture_widget), arrows or Ctrl+J/K move the
selection, Enter activates, Ctrl+P pins, Ctrl+D deletes, Escape or focus
loss dismisses. The list is a recycling Gtk.ListView over a Gio.ListStore
of pre-wrapped EntryObjects: a keystroke only re-scores and splices, it
never rebuilds widgets.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkX11", "4.0")
from gi.repository import Adw, Gdk, GdkX11, Gio, GLib, Gtk

from clipd import log
from clipd.config import Config
from clipd.search import Matcher
from clipd.store import Entry, Store
from clipd.ui.row import EntryObject, EntryRow
from clipd.x11.wm import WindowDresser

_LOG = log.get(__name__)


class ClipWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        app: Adw.Application,
        store: Store,
        config: Config,
        dresser: WindowDresser,
        on_activate: Callable[[Entry], None],
        on_settings: Callable[[], None],
    ) -> None:
        super().__init__(application=app, title="clipd")
        self._store = store
        self._config = config
        self._dresser = dresser
        self._on_activate_cb = on_activate
        self._all: list[EntryObject] = []
        self._matcher = Matcher("")
        self._active_seen = False  # guards against stale FocusOut on re-show
        self.connect("realize", self._on_realize)

        self.set_default_size(config.window_width, config.window_height)
        self.set_decorated(False)
        self.set_hide_on_close(True)

        self._entry = Gtk.SearchEntry(placeholder_text="Fuzzy search\u2026")
        self._entry.set_search_delay(50)  # default 150ms feels laggy in a popup
        self._entry.set_margin_top(10)
        self._entry.set_margin_start(10)
        self._entry.set_margin_end(10)
        self._entry.set_key_capture_widget(self)
        self._entry.connect("search-changed", lambda *_: self._refilter())
        self._entry.connect("activate", lambda *_: self._activate_selected())
        self._entry.connect("stop-search", lambda *_: self.dismiss())

        self._model = Gio.ListStore.new(EntryObject)
        self._selection = Gtk.SingleSelection.new(self._model)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._row_setup)
        factory.connect("bind", self._row_bind)
        self._list = Gtk.ListView.new(self._selection, factory)
        self._list.set_single_click_activate(True)
        self._list.add_css_class("navigation-sidebar")
        self._list.connect("activate", self._on_row_activated)

        scroller = Gtk.ScrolledWindow(vexpand=True, child=self._list)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._status = Adw.StatusPage(icon_name="edit-paste-symbolic", vexpand=True)
        self._stack = Gtk.Stack()
        self._stack.add_named(scroller, "list")
        self._stack.add_named(self._status, "empty")

        self._count = Gtk.Label()
        self._count.add_css_class("dim-label")
        self._count.add_css_class("caption")
        hints = Gtk.Label(label="\u21b5 paste   ^P pin   ^D delete   Esc close", hexpand=True)
        hints.add_css_class("dim-label")
        hints.add_css_class("caption")
        gear = Gtk.Button.new_from_icon_name("emblem-system-symbolic")
        gear.add_css_class("flat")
        gear.connect("clicked", lambda *_: on_settings())
        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bottom.set_margin_start(12)
        bottom.set_margin_end(6)
        bottom.set_margin_bottom(4)
        bottom.append(self._count)
        bottom.append(hints)
        bottom.append(gear)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.append(self._entry)
        root.append(self._stack)
        root.append(bottom)
        self.set_content(root)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("notify::is-active", self._on_active_changed)

    # -- rows ---------------------------------------------------------------

    def _row_setup(self, _factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        item.set_child(EntryRow())

    def _row_bind(self, _factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        row = item.get_child()
        obj = item.get_item()
        assert isinstance(row, EntryRow) and isinstance(obj, EntryObject)
        row.bind(obj, self._matcher)

    # -- filtering ------------------------------------------------------------

    def refresh(self) -> None:
        """Re-pull from the store, keeping the current query and selection."""
        selected = self._selected_entry()
        self._all = [EntryObject(e) for e in self._store.entries()]
        self._refilter(reselect_id=selected.id if selected else None)

    def _refilter(self, reselect_id: int | None = None) -> None:
        self._matcher = matcher = Matcher(self._entry.get_text())
        if matcher.empty:
            items = self._all  # store order: pinned first, then recency
        else:
            scored = [
                (score, obj)
                for obj in self._all
                if (score := matcher.score(obj.hay, pinned=obj.entry.pinned)) is not None
            ]
            scored.sort(key=lambda pair: (-pair[0], -pair[1].entry.last_used_at))
            items = [obj for _, obj in scored]
        self._model.splice(0, self._model.get_n_items(), items)

        self._count.set_text(f"{len(items)}/{len(self._all)}")
        if items:
            self._stack.set_visible_child_name("list")
            position = 0
            if reselect_id is not None:
                position = next(
                    (i for i, o in enumerate(items) if o.entry.id == reselect_id), 0
                )
            self._selection.set_selected(position)
            self._list.scroll_to(position, Gtk.ListScrollFlags.NONE)
        else:
            self._status.set_title("No matches" if not matcher.empty else "History is empty")
            self._status.set_description(
                None if not matcher.empty else "Copy something and it will show up here."
            )
            self._stack.set_visible_child_name("empty")

    # -- actions ----------------------------------------------------------

    def _selected_entry(self) -> Entry | None:
        obj = self._selection.get_selected_item()
        return obj.entry if isinstance(obj, EntryObject) else None

    def _on_row_activated(self, _list: Gtk.ListView, position: int) -> None:
        obj = self._model.get_item(position)
        if isinstance(obj, EntryObject):
            self._on_activate_cb(obj.entry)

    def _activate_selected(self) -> None:
        entry = self._selected_entry()
        if entry is not None:
            self._on_activate_cb(entry)

    def _move_selection(self, delta: int) -> None:
        total = self._model.get_n_items()
        if total == 0:
            return
        current = self._selection.get_selected()
        if current == Gtk.INVALID_LIST_POSITION:
            current = 0 if delta > 0 else total - 1
        else:
            current = max(0, min(current + delta, total - 1))
        self._selection.set_selected(current)
        self._list.scroll_to(current, Gtk.ListScrollFlags.NONE)

    def _on_key(
        self, _ctrl: Gtk.EventControllerKey, keyval: int, _keycode: int, state: Gdk.ModifierType
    ) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if keyval == Gdk.KEY_Escape:
            self.dismiss()
        elif keyval == Gdk.KEY_Down or (ctrl and keyval in (Gdk.KEY_j, Gdk.KEY_n)):
            self._move_selection(+1)
        elif keyval == Gdk.KEY_Up or (ctrl and keyval == Gdk.KEY_k):
            self._move_selection(-1)
        elif ctrl and keyval == Gdk.KEY_p:
            self._toggle_pin()
        elif ctrl and keyval == Gdk.KEY_d:
            self._delete_selected()
        else:
            return False
        return True

    def _toggle_pin(self) -> None:
        entry = self._selected_entry()
        if entry is not None:
            self._store.set_pinned(entry.id, not entry.pinned)
            self.refresh()

    def _delete_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        position = self._selection.get_selected()
        self._store.delete(entry.id)
        self._all = [o for o in self._all if o.entry.id != entry.id]
        self._refilter()
        if self._model.get_n_items():
            clamped = min(position, self._model.get_n_items() - 1)
            self._selection.set_selected(clamped)

    # -- visibility ----------------------------------------------------------

    def popup(self) -> None:
        self._entry.set_text("")
        self.refresh()
        self._active_seen = False
        self.present()
        self._entry.grab_focus()
        GLib.idle_add(self._dress_and_center)

    def dismiss(self) -> None:
        self.set_visible(False)

    def toggle(self) -> None:
        if self.get_visible() and self.props.is_active:
            self.dismiss()
        else:
            self.popup()

    def _on_realize(self, *_args: object) -> None:
        surface = self.get_surface()
        if isinstance(surface, GdkX11.X11Surface):
            # Property lands before GTK maps the window, so dwm sees a
            # dialog at manage time and floats it.
            self._dresser.make_dialog(surface.get_xid())

    def _dress_and_center(self) -> bool:
        surface = self.get_surface()
        if isinstance(surface, GdkX11.X11Surface):
            width = self.get_width() or self._config.window_width
            height = self.get_height() or self._config.window_height
            self._dresser.center(surface.get_xid(), width, height)
        return False

    def _on_active_changed(self, *_args: object) -> None:
        # A FocusOut from the previous unmap can arrive just after a fresh
        # present(); only honour focus loss once focus was gained this time.
        if self.props.is_active:
            self._active_seen = True
        elif (
            self._active_seen
            and self._config.hide_on_focus_loss
            and self.get_visible()
        ):
            self.dismiss()
