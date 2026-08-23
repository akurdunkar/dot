# clipd

Clipboard daemon for X11/dwm: fuzzy-searchable history with pins, image
support, a tray icon and a keyboard-first popup. GTK4 + libadwaita, one
resident process, instant summon.

```
dwm Super+V ──spawns──▶ clipd toggle ──D-Bus──▶ ┌────────────── clipd daemon ──────────────┐
                                                │ GApplication (single instance, CLI)      │
xclip / any app ──X11 clipboard──▶ Gdk.Clipboard│ watcher ▶ SQLite store (dedupe, pins)    │
                                                │ popup (ListView + fuzzy matcher)         │
dwm systray ◀──XEmbed── tray icon (python-xlib) │ XTEST auto-paste into the focused window │
                                                └───────────────────────────────────────────┘
```

## Behaviour

- Everything persists across boots in `~/.local/share/clipd/history.sqlite3`.
  Pinned entries never expire; unpinned history is capped (default 500).
- Re-copying known content bumps it instead of duplicating it (sha256 dedupe).
- Text, images (stored as PNG, thumbnailed in the list) and copied files
  (`text/uri-list`, pasteable back into file managers) are captured.
  Content flagged `x-kde-passwordManagerHint` is ignored.
- Selecting an entry copies it and, by default, auto-pastes into the window
  that regains focus — Ctrl+Shift+V when that window is a terminal.
- The popup follows the system dark/light preference via libadwaita.

## Popup keys

Type anywhere to search (fuzzy, smart-case, space-separated AND terms;
matches highlighted). `↑/↓` or `Ctrl+K/J` move, `Enter` copies + pastes,
`Ctrl+P` pins, `Ctrl+D` deletes, `Esc` or focus loss dismisses.

## CLI

The daemon is the CLI: later invocations are routed to it over D-Bus.

```
clipd                 start the daemon
clipd toggle          show/hide the popup (bind this in dwm)
clipd list            id, pin, kind, preview — tab-separated
clipd get/copy/pin/unpin/rm ID
clipd save ID f.png   write an image entry to disk
clipd clear           drop unpinned history
clipd settings | quit | version | help
```

## Install

```
make install          # pip install + user systemd unit
make dev              # editable install + pytest + GTK4-flavoured stubs
make test             # unit tests (matcher, store)
make smoke            # full E2E inside Xvfb: xclip in, CLI out, screenshots
make typecheck        # pyright strict (x11/ at reduced strength)
```

dwm integration (`config.h`):

```c
{ Super, XK_v, spawn, SHCMD("clipd toggle") },
```

The popup sets `_NET_WM_WINDOW_TYPE_DIALOG` before mapping, so stock dwm
floats and centers it without any rules. Start the daemon from dwm's
autostart (`nohup clipd &`) or `systemctl --user enable --now clipd`
(import `DISPLAY` and `DBUS_SESSION_BUS_ADDRESS` first). Pick one method.

## Layout

```
src/clipd/
  app.py           GApplication glue: daemon lifecycle + CLI dispatch
  clipboard.py     capture/re-copy policy on top of Gdk.Clipboard
  store.py         SQLite history (dedupe, pins, prune, lazy blobs)
  config.py        flat INI config, ~/.config/clipd/config.ini
  search/matcher.py fzf-style scorer: windowed forward/backward scan
  ui/window.py     popup (search entry + recycling ListView)
  ui/row.py        row widget + Pango match highlighting
  ui/settings.py   Adw preferences dialog
  ui/menu.py       tray context menu
  x11/tray.py      XEmbed tray icon (dwm systray patch)
  x11/paste.py     XTEST Ctrl(+Shift)+V injection
  x11/wm.py        dialog hint, centering, menu placement
```

Swappable seams: the watcher is confined to `clipboard.py` (a Wayland
`ext-data-control` backend could replace it), the matcher is pure Python
with a two-method surface, and everything Xlib lives under `x11/`.
