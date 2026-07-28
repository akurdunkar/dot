# brightd

A tray brightness controller. Click the tray icon and a small panel appears
with one slider per display — the built-in panel via the kernel backlight, and
external monitors via DDC/CI. Scroll on the icon to adjust without opening it.

Statically typed end to end and checked with `pyright --strict`.

## Why it is built this way

Three constraints from this machine drove most of the design, and they are
documented at length in the modules they affect:

- **dwm tiles everything it manages.** The slider panel is a
  `Gtk.WindowType.POPUP` — an override-redirect window that dwm's `maprequest()`
  skips entirely. `_NET_WM_WINDOW_TYPE_DOCK`, `UTILITY` and `POPUP_MENU` are all
  ignored by this dwm build and get tiled. Because the panel is unmanaged it is
  never focused, so keyboard and click-outside dismissal come from an explicit
  `Gdk.Seat` grab with `owner_events=True` — with `False` the grab still
  succeeds but the sliders receive no events and dragging silently does nothing.
- **The tray only speaks XEmbed.** `Gtk.StatusIcon` is deprecated and is the
  only thing dwm's systray patch will display; AppIndicator icons never appear.
- **The backlight register is linear in luminance, not in perception.** A 0-100
  slider mapped linearly puts a comfortable 19200/192000 at 9% of travel, where
  a pixel of drag is a huge jump. brightd maps through CIE L\*, which puts the
  same setting at 36% — see `curve.py`.

## Install

```sh
make install     # installs brightd, brightd-ctl and a systemd user unit
make dev         # editable install + pytest + PyGObject type stubs
```

## Run

Pick **one** method. Either from dwm's autostart:

```sh
nohup brightd >>/tmp/brightd.log 2>&1 &
```

or via the systemd user unit (requires a managed `graphical-session.target` and
`systemctl --user import-environment DISPLAY`):

```sh
systemctl --user enable --now brightd
```

A file lock in `$XDG_RUNTIME_DIR` guarantees one instance per user — a second
invocation prints "brightd is already running" and exits 0, so re-running
`autostart.sh` is harmless. This matters more than it looks: two instances would
each treat the other's writes as external changes and fight into a write loop.

### Options

- `--no-ddc` — control the internal panel only, skipping all DDC probing.
- `--min-fraction 0.01` — the floor, as a fraction of maximum. 0% on the slider
  means "dimmest safe", never black: the kernel accepts a raw 0 and blanks the
  panel, and with the brightness hotkeys dead there would be no way back.
- `--device intel_backlight` — override backlight auto-detection.
- `--verbose`, `--json-log`

## brightd-ctl

Deliberately has no IPC with the daemon: it writes the hardware directly, and a
running brightd notices through its `POLLPRI` watch on `actual_brightness`. So
it behaves identically whether or not the daemon is running.

```sh
brightd-ctl list          # eDP-1   36.2%  internal  Built-in display
brightd-ctl get           # 36
brightd-ctl set 60
brightd-ctl up 10
brightd-ctl down 10
brightd-ctl -d DP-1 set 80
```

### dwm keybindings

`xbacklight` is a silent no-op on modern i915 — there is no RandR `BACKLIGHT`
property for it to set — so the existing bindings in `dwm/config.h` do nothing
at all. Replace them with:

```c
{ 0, XF86XK_MonBrightnessUp,   spawn, SHCMD("brightd-ctl up 5")   },
{ 0, XF86XK_MonBrightnessDown, spawn, SHCMD("brightd-ctl down 5") },
```

## External monitors (DDC/CI)

Nothing below is needed for the built-in panel, which works out of the box.

`ddcutil` is not installed on this machine and `/dev/i2c-*` is currently
root-only, so **the DDC path has not been exercised against real hardware** —
there was no external monitor attached to test it with. It is unit-tested
against a fake runner, and it degrades quietly: with no `ddcutil` the module is
never used and the UI never mentions it.

One-time setup, **then log out and back in** (the uaccess ACL and the
supplementary group are both applied at login):

```sh
sudo apt install ddcutil
sudo usermod -aG i2c $USER
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=i2c-dev --action=change
# verify: getfacl /dev/i2c-16   should show user:$USER:rw-
```

Monitors are addressed by I2C bus number read from `/sys/class/drm/*/ddc`, not
by `ddcutil --display N`: display numbers are reassigned on every hotplug, so a
number captured at startup can later point at a different monitor. `ddcutil
detect` is never used in the hot path — it takes seconds.

The internal panel is never driven over DDC even though it does expose a bus
and a valid EDID, because the kernel backlight already owns it.

## Development

```sh
make test        # 89 tests, no hardware required
make typecheck   # pyright --strict, asserts a nonzero file count
```

The whole suite runs against fake sysfs trees and an injected command runner, so
it passes with no monitors attached and no ddcutil installed. `make typecheck`
checks that pyright actually analysed something — with unresolvable include
paths it reports zero files and zero errors, which otherwise reads as a pass.

Type stubs are installed by `make dev` rather than declared as a dependency:
`pygobject-stubs` needs `PYGOBJECT_STUB_CONFIG=Gtk3,Gdk3` set at install time or
pip selects the GTK4 stubs, which contain no `Gtk.StatusIcon` at all, and it is
pinned `<2.17` to stay compatible with the distro's PyGObject 3.48.

## Layout

| Module | Role |
| --- | --- |
| `curve.py` | CIE L\* ↔ raw mapping. Pure, GTK-free, shared with the CLI. |
| `backends/sysfs.py` | Kernel backlight: persistent write fd, `POLLPRI` watch, three-tier write fallback. |
| `backends/ddc.py` | External monitors via `ddcutil`, serialised per I2C bus. |
| `backends/discovery.py` | Connector → bus → EDID map straight from sysfs. |
| `worker.py` | One thread per display, latest-value-wins coalescing. |
| `controller.py` | Display registry and optimistic state. No GTK. |
| `ui/popup.py` | The override-redirect slider panel and its seat grab. |
| `ui/tray.py` | `Gtk.StatusIcon`, scroll handling, embed retry. |
| `watcher.py` | GLib `POLLPRI` watch so external changes update the slider. |
