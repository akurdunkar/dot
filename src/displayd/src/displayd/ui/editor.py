"""Arandr-style graphical layout editor window."""

from __future__ import annotations

import concurrent.futures
import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from ..types import MonitorIdentity, OutputConfig, Topology
from . import geometry

if TYPE_CHECKING:
    from ..engine import Engine

log = logging.getLogger(__name__)

_ROTATIONS = ("normal", "left", "right", "inverted")
_PARK_GAP = 64
_FALLBACK_MODE = "1024x768"
_FILL_RGBA = (0x3B / 255, 0x6E / 255, 0xA5 / 255, 0.85)
_SELECT_RGB = (0xE0 / 255, 0xA0 / 255, 0x30 / 255)
_DISABLED_RGB = (0.55, 0.55, 0.55)
_COORD_LIMIT = 32768


@dataclass
class _EditorOutput:
    connector: str
    identity: MonitorIdentity
    identity_str: str
    modes: list[str]
    enabled: bool
    mode: str
    x: int
    y: int
    rotation: str
    primary: bool

    @property
    def size(self) -> tuple[int, int]:
        try:
            return geometry.effective_size(self.mode, self.rotation)
        except ValueError:
            return geometry.parse_mode(_FALLBACK_MODE)

    @property
    def rect(self) -> tuple[int, int, int, int]:
        w, h = self.size
        return (self.x, self.y, w, h)


def _build_model(topology: Topology) -> list[_EditorOutput]:
    enabled: list[_EditorOutput] = []
    disabled: list[_EditorOutput] = []
    for output in topology.outputs:
        modes = list(output.modes) or [_FALLBACK_MODE]
        if output.current_mode is not None:
            mode = output.current_mode
            if mode not in modes:
                modes.insert(0, mode)
            enabled.append(
                _EditorOutput(
                    connector=output.connector,
                    identity=output.identity,
                    identity_str=output.identity.stable_id,
                    modes=modes,
                    enabled=True,
                    mode=mode,
                    x=output.current_position[0],
                    y=output.current_position[1],
                    rotation=output.current_rotation,
                    primary=output.is_primary,
                )
            )
        else:
            disabled.append(
                _EditorOutput(
                    connector=output.connector,
                    identity=output.identity,
                    identity_str=output.identity.stable_id,
                    modes=modes,
                    enabled=False,
                    mode=modes[0],
                    x=0,
                    y=0,
                    rotation="normal",
                    primary=False,
                )
            )
    _, _, max_x, _ = geometry.bounding_box([o.rect for o in enabled])
    park_x = max_x + _PARK_GAP
    for item in disabled:
        item.x = park_x
        item.y = 0
        park_x += item.size[0] + _PARK_GAP
    return enabled + disabled


def _rounded_rect(cr, x: float, y: float, w: float, h: float) -> None:
    r = min(8.0, w / 4.0, h / 4.0)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class LayoutEditorWindow(Gtk.Window):
    """Singleton window with a draggable monitor canvas and output controls."""

    _instance: ClassVar[Optional["LayoutEditorWindow"]] = None

    @classmethod
    def open(cls, engine: Engine) -> "LayoutEditorWindow":
        if cls._instance is not None:
            cls._instance.present()
            return cls._instance
        window = cls(engine)
        cls._instance = window
        window.show_all()
        return window

    def __init__(self, engine: Engine) -> None:
        super().__init__(title="displayd — layout editor")
        self.set_default_size(920, 600)
        self._engine = engine
        self._topology: Optional[Topology] = None
        self._outputs: list[_EditorOutput] = []
        self._selected: Optional[_EditorOutput] = None
        self._drag: Optional[tuple[_EditorOutput, float, float]] = None
        self._drag_transform: Optional[tuple[float, float, float]] = None
        self._updating_panel = False
        self.connect("destroy", self._on_destroy)
        self._build_ui()
        state = engine.state
        if state.topology is not None:
            self._set_topology(state.topology)
        self._refresh()

    def _on_destroy(self, _window: Gtk.Window) -> None:
        LayoutEditorWindow._instance = None

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)

        self._infobar = Gtk.InfoBar()
        self._infobar.set_no_show_all(True)
        self._infobar.set_show_close_button(True)
        self._infobar.connect("response", lambda bar, _r: bar.hide())
        self._info_label = Gtk.Label(label="")
        self._info_label.show()
        self._infobar.get_content_area().add(self._info_label)
        vbox.pack_start(self._infobar, False, False, 0)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        vbox.pack_start(hbox, True, True, 0)

        self._canvas = Gtk.DrawingArea()
        self._canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self._canvas.connect("draw", self._on_draw)
        self._canvas.connect("button-press-event", self._on_button_press)
        self._canvas.connect("button-release-event", self._on_button_release)
        self._canvas.connect("motion-notify-event", self._on_motion)
        hbox.pack_start(self._canvas, True, True, 0)

        hbox.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0
        )
        hbox.pack_start(self._build_panel(), False, False, 0)

        action_bar = Gtk.ActionBar()
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        action_bar.pack_start(refresh_btn)
        apply_btn = Gtk.Button(label="Apply")
        apply_btn.connect("clicked", self._on_apply_clicked)
        action_bar.pack_start(apply_btn)
        save_btn = Gtk.Button(label="Save layout…")
        save_btn.connect("clicked", self._on_save_clicked)
        action_bar.pack_start(save_btn)
        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda _b: self.destroy())
        action_bar.pack_end(close_btn)
        vbox.pack_end(action_bar, False, False, 0)

    def _build_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.set_size_request(260, -1)
        panel.set_margin_top(12)
        panel.set_margin_bottom(12)
        panel.set_margin_start(12)
        panel.set_margin_end(12)

        self._lbl_selected = Gtk.Label(label="No output selected")
        self._lbl_selected.set_xalign(0.0)
        self._lbl_selected.set_ellipsize(Pango.EllipsizeMode.END)
        panel.pack_start(self._lbl_selected, False, False, 0)

        enabled_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        enabled_row.pack_start(
            Gtk.Label(label="Enabled", xalign=0.0), True, True, 0
        )
        self._sw_enabled = Gtk.Switch()
        self._sw_enabled.connect("notify::active", self._on_enabled_toggled)
        enabled_row.pack_end(self._sw_enabled, False, False, 0)
        panel.pack_start(enabled_row, False, False, 0)

        panel.pack_start(Gtk.Label(label="Mode", xalign=0.0), False, False, 0)
        self._cmb_mode = Gtk.ComboBoxText()
        self._cmb_mode.connect("changed", self._on_mode_changed)
        panel.pack_start(self._cmb_mode, False, False, 0)

        panel.pack_start(Gtk.Label(label="Rotation", xalign=0.0), False, False, 0)
        self._cmb_rotation = Gtk.ComboBoxText()
        for rotation in _ROTATIONS:
            self._cmb_rotation.append_text(rotation)
        self._cmb_rotation.connect("changed", self._on_rotation_changed)
        panel.pack_start(self._cmb_rotation, False, False, 0)

        self._chk_primary = Gtk.CheckButton(label="Primary")
        self._chk_primary.connect("toggled", self._on_primary_toggled)
        panel.pack_start(self._chk_primary, False, False, 0)

        pos_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pos_row.pack_start(Gtk.Label(label="x"), False, False, 0)
        self._spn_x = Gtk.SpinButton.new_with_range(-_COORD_LIMIT, _COORD_LIMIT, 1)
        self._spn_x.connect("value-changed", self._on_position_changed)
        pos_row.pack_start(self._spn_x, True, True, 0)
        pos_row.pack_start(Gtk.Label(label="y"), False, False, 0)
        self._spn_y = Gtk.SpinButton.new_with_range(-_COORD_LIMIT, _COORD_LIMIT, 1)
        self._spn_y.connect("value-changed", self._on_position_changed)
        pos_row.pack_start(self._spn_y, True, True, 0)
        panel.pack_start(pos_row, False, False, 0)

        self._panel_widgets = (
            self._sw_enabled,
            self._cmb_mode,
            self._cmb_rotation,
            self._chk_primary,
            self._spn_x,
            self._spn_y,
        )
        self._sync_panel()
        return panel

    # ------------------------------------------------------------------
    # Panel <-> model synchronization
    # ------------------------------------------------------------------

    def _sync_panel(self) -> None:
        self._updating_panel = True
        try:
            selected = self._selected
            for widget in self._panel_widgets:
                widget.set_sensitive(selected is not None)
            if selected is None:
                self._lbl_selected.set_text("No output selected")
                return
            self._lbl_selected.set_text(
                f"{selected.connector} — {selected.identity_str}"
            )
            self._sw_enabled.set_active(selected.enabled)
            self._cmb_mode.remove_all()
            for mode in selected.modes:
                self._cmb_mode.append_text(mode)
            if selected.mode in selected.modes:
                self._cmb_mode.set_active(selected.modes.index(selected.mode))
            self._cmb_rotation.set_active(
                _ROTATIONS.index(selected.rotation)
                if selected.rotation in _ROTATIONS
                else 0
            )
            self._chk_primary.set_active(selected.primary)
            self._spn_x.set_value(selected.x)
            self._spn_y.set_value(selected.y)
        finally:
            self._updating_panel = False

    def _sync_panel_position(self) -> None:
        if self._selected is None:
            return
        self._updating_panel = True
        try:
            self._spn_x.set_value(self._selected.x)
            self._spn_y.set_value(self._selected.y)
        finally:
            self._updating_panel = False

    def _on_enabled_toggled(self, switch: Gtk.Switch, _pspec) -> None:
        if self._updating_panel or self._selected is None:
            return
        self._selected.enabled = switch.get_active()
        if not self._selected.enabled:
            self._selected.primary = False
            self._sync_panel()
        self._canvas.queue_draw()

    def _on_mode_changed(self, combo: Gtk.ComboBoxText) -> None:
        if self._updating_panel or self._selected is None:
            return
        text = combo.get_active_text()
        if text:
            self._selected.mode = text
            self._canvas.queue_draw()

    def _on_rotation_changed(self, combo: Gtk.ComboBoxText) -> None:
        if self._updating_panel or self._selected is None:
            return
        text = combo.get_active_text()
        if text:
            self._selected.rotation = text
            self._canvas.queue_draw()

    def _on_primary_toggled(self, check: Gtk.CheckButton) -> None:
        if self._updating_panel or self._selected is None:
            return
        active = check.get_active()
        if active:
            for output in self._outputs:
                output.primary = output is self._selected
        else:
            self._selected.primary = False
        self._canvas.queue_draw()

    def _on_position_changed(self, _spin: Gtk.SpinButton) -> None:
        if self._updating_panel or self._selected is None:
            return
        self._selected.x = self._spn_x.get_value_as_int()
        self._selected.y = self._spn_y.get_value_as_int()
        self._canvas.queue_draw()

    # ------------------------------------------------------------------
    # Canvas
    # ------------------------------------------------------------------

    def _current_transform(self) -> tuple[float, float, float]:
        if self._drag_transform is not None:
            return self._drag_transform
        allocation = self._canvas.get_allocation()
        bounds = geometry.bounding_box([o.rect for o in self._outputs])
        return geometry.compute_scale(bounds, allocation.width, allocation.height)

    def _on_draw(self, _area: Gtk.DrawingArea, cr) -> bool:
        allocation = self._canvas.get_allocation()
        cr.set_source_rgb(0.12, 0.12, 0.13)
        cr.rectangle(0, 0, allocation.width, allocation.height)
        cr.fill()

        scale, offset_x, offset_y = self._current_transform()

        # Subtle crosshair at the virtual origin.
        cr.set_source_rgba(0.6, 0.6, 0.6, 0.35)
        cr.set_line_width(1.0)
        cr.move_to(offset_x - 12, offset_y)
        cr.line_to(offset_x + 12, offset_y)
        cr.move_to(offset_x, offset_y - 12)
        cr.line_to(offset_x, offset_y + 12)
        cr.stroke()

        cr.select_font_face("sans")
        for output in self._outputs:
            vx, vy, vw, vh = output.rect
            x = vx * scale + offset_x
            y = vy * scale + offset_y
            w = vw * scale
            h = vh * scale

            if output.enabled:
                _rounded_rect(cr, x, y, w, h)
                cr.set_source_rgba(*_FILL_RGBA)
                cr.fill()
                text_rgb = (1.0, 1.0, 1.0)
            else:
                _rounded_rect(cr, x, y, w, h)
                cr.set_source_rgb(*_DISABLED_RGB)
                cr.set_line_width(1.5)
                cr.set_dash([6.0, 4.0])
                cr.stroke()
                cr.set_dash([])
                text_rgb = _DISABLED_RGB

            if output is self._selected:
                _rounded_rect(cr, x, y, w, h)
                cr.set_source_rgb(*_SELECT_RGB)
                cr.set_line_width(2.0)
                cr.stroke()

            cr.save()
            _rounded_rect(cr, x, y, w, h)
            cr.clip()
            cr.set_source_rgb(*text_rgb)
            label = output.mode
            if output.primary:
                label += " *"
            cr.set_font_size(12)
            cr.move_to(x + 8, y + 18)
            cr.show_text(output.connector)
            cr.set_font_size(11)
            cr.move_to(x + 8, y + 34)
            cr.show_text(output.identity.model)
            cr.move_to(x + 8, y + 50)
            cr.show_text(label)
            cr.restore()
        return False

    def _on_button_press(self, area: Gtk.DrawingArea, event: Gdk.EventButton) -> bool:
        if event.button != 1:
            return False
        transform = self._current_transform()
        scale, offset_x, offset_y = transform
        vx = (event.x - offset_x) / scale
        vy = (event.y - offset_y) / scale
        for output in reversed(self._outputs):
            x, y, w, h = output.rect
            if x <= vx <= x + w and y <= vy <= y + h:
                self._selected = output
                self._drag = (output, vx - output.x, vy - output.y)
                self._drag_transform = transform
                self._sync_panel()
                area.queue_draw()
                return True
        if self._selected is not None:
            self._selected = None
            self._sync_panel()
            area.queue_draw()
        return True

    def _on_motion(self, area: Gtk.DrawingArea, event: Gdk.EventMotion) -> bool:
        if self._drag is None:
            return False
        output, grab_dx, grab_dy = self._drag
        scale, offset_x, offset_y = self._current_transform()
        vx = (event.x - offset_x) / scale - grab_dx
        vy = (event.y - offset_y) / scale - grab_dy
        w, h = output.size
        others = [o.rect for o in self._outputs if o is not output and o.enabled]
        threshold = max(32, int(24 / scale))
        output.x, output.y = geometry.snap_position(
            int(round(vx)), int(round(vy)), w, h, others, threshold
        )
        self._sync_panel_position()
        area.queue_draw()
        return True

    def _on_button_release(
        self, area: Gtk.DrawingArea, event: Gdk.EventButton
    ) -> bool:
        if event.button != 1 or self._drag is None:
            return False
        self._drag = None
        self._drag_transform = None
        area.queue_draw()
        return True

    # ------------------------------------------------------------------
    # Change assembly
    # ------------------------------------------------------------------

    def _build_changes(self) -> list[tuple[str, OutputConfig]]:
        positions = {o.connector: (o.x, o.y) for o in self._outputs}
        sizes = {o.connector: o.size for o in self._outputs}
        enabled = {o.connector: o.enabled for o in self._outputs}
        normalized = geometry.normalize_positions(positions, sizes, enabled)

        enabled_outputs = [o for o in self._outputs if o.enabled]
        primary_connector: Optional[str] = None
        for output in enabled_outputs:
            if output.primary:
                primary_connector = output.connector
                break
        if primary_connector is None and enabled_outputs:
            primary_connector = enabled_outputs[0].connector

        changes: list[tuple[str, OutputConfig]] = []
        for output in self._outputs:
            if not output.enabled:
                config = OutputConfig(identity=output.identity, enabled=False)
            else:
                config = OutputConfig(
                    identity=output.identity,
                    enabled=True,
                    mode=output.mode,
                    position=normalized[output.connector],
                    rotation=output.rotation,
                    primary=output.connector == primary_connector,
                )
            changes.append((output.connector, config))
        return changes

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_refresh_clicked(self, _button: Gtk.Button) -> None:
        self._refresh()

    def _on_apply_clicked(self, _button: Gtk.Button) -> None:
        changes = self._build_changes()
        if not any(config.enabled for _, config in changes):
            self._show_info("Refusing to apply: no output enabled", error=True)
            return
        future = self._engine.apply_layout(changes)
        future.add_done_callback(
            lambda f: GLib.idle_add(self._on_apply_done, f)
        )

    def _on_apply_done(self, future: concurrent.futures.Future) -> bool:
        try:
            ok = bool(future.result())
        except Exception:
            log.exception("apply_layout failed")
            ok = False
        if ok:
            self._show_info("Layout applied")
            self._refresh()
        else:
            # Keep the user's uncommitted edits so they can adjust and retry.
            self._show_info("Apply failed — check logs", error=True)
        return False

    def _on_save_clicked(self, _button: Gtk.Button) -> None:
        if self._topology is None:
            self._show_info("No topology loaded yet", error=True)
            return
        dialog = Gtk.Dialog(title="Save layout", transient_for=self, modal=True)
        dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("_Save", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        entry = Gtk.Entry()
        entry.set_text(self._engine.state.matched_profile or "layout")
        entry.set_activates_default(True)
        spin = Gtk.SpinButton.new_with_range(0, 100, 1)
        spin.set_value(0)
        grid.attach(Gtk.Label(label="Name", halign=Gtk.Align.END), 0, 0, 1, 1)
        grid.attach(entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Priority", halign=Gtk.Align.END), 0, 1, 1, 1)
        grid.attach(spin, 1, 1, 1, 1)
        dialog.get_content_area().add(grid)
        dialog.show_all()

        response = dialog.run()
        name = entry.get_text().strip() or "layout"
        priority = spin.get_value_as_int()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return

        changes = self._build_changes()
        future = self._engine.save_layout(
            name,
            [config for _, config in changes],
            self._topology.identity_hash,
            priority,
        )
        future.add_done_callback(
            lambda f: GLib.idle_add(self._on_save_done, f, name)
        )

    def _on_save_done(self, future: concurrent.futures.Future, name: str) -> bool:
        try:
            path = future.result()
        except Exception:
            log.exception("save_layout failed")
            self._show_info("Save failed — check logs", error=True)
            return False
        self._show_info(f"Saved layout {name!r} to {path}")
        return False

    # ------------------------------------------------------------------
    # Topology loading
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        future = self._engine.get_topology()
        future.add_done_callback(
            lambda f: GLib.idle_add(self._on_topology_ready, f)
        )

    def _on_topology_ready(self, future: concurrent.futures.Future) -> bool:
        try:
            topology = future.result()
        except Exception:
            log.exception("get_topology failed")
            self._show_info("Failed to read topology — check logs", error=True)
            return False
        self._set_topology(topology)
        return False

    def _set_topology(self, topology: Topology) -> None:
        selected_connector = (
            self._selected.connector if self._selected is not None else None
        )
        self._topology = topology
        self._outputs = _build_model(topology)
        self._selected = next(
            (o for o in self._outputs if o.connector == selected_connector), None
        )
        self._drag = None
        self._drag_transform = None
        self._sync_panel()
        self._canvas.queue_draw()

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def _show_info(self, message: str, *, error: bool = False) -> None:
        self._infobar.set_message_type(
            Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO
        )
        self._info_label.set_text(message)
        self._infobar.show()
