# da

A tray calendar. The icon is a calendar page showing today's date; click it and
a month grid drops out of the tray, which you can page through with the arrows,
the keyboard or the scroll wheel.

Nothing in it is selectable. There is no date to pick, no event to add and no
IPC — it exists to answer "what's the date, and what day does the 19th fall
on?" and then get out of the way.

Statically typed end to end and checked with `pyright --strict`.

## Why it is built this way

Three constraints from this machine drove the design, and they are documented at
length in the modules they affect:

- **dwm tiles everything it manages.** The panel is a `Gtk.WindowType.POPUP` —
  an override-redirect window that dwm's `maprequest()` skips entirely.
  `_NET_WM_WINDOW_TYPE_DOCK`, `UTILITY` and `POPUP_MENU` are all ignored by this
  dwm build and get tiled. Because the panel is unmanaged it is never focused,
  so keyboard and click-outside dismissal come from an explicit `Gdk.Seat` grab
  with `owner_events=True` — with `False` the grab still succeeds but the arrow
  buttons receive no events and clicking them silently does nothing.
- **The tray only speaks XEmbed.** `Gtk.StatusIcon` is deprecated and is the
  only thing dwm's systray patch will display; AppIndicator icons never appear.
- **The grid is always six rows, even for a four-row February.** The panel is
  positioned from its own size, so a grid whose height followed the month would
  resize the window and move it under the pointer somewhere between February and
  August. Fixed rows also mean the widgets are built once and only ever
  relabelled — which matters because rebuilding them while the panel holds the
  seat grab would destroy the widgets the grab lives on. See `month.py`.

## Install

```sh
make install     # installs da and a systemd user unit
make dev         # editable install + pytest + PyGObject type stubs
make test        # 157 tests, no X server needed
make typecheck
```

## Run

Pick **one** method. Either from dwm's autostart:

```sh
nohup da >>/tmp/da.log 2>&1 &
```

or via the systemd user unit (requires a managed `graphical-session.target` and
`systemctl --user import-environment DISPLAY`):

```sh
systemctl --user enable --now da
```

A file lock in `$XDG_RUNTIME_DIR` guarantees one instance per user — a second
invocation prints "da is already running" and exits 0, so re-running
`autostart.sh` is harmless. Without it you get two identical tray icons, and
whichever panel grabs second silently receives no input.

### Options

- `--week-start sunday` — start the week on Sunday instead of Monday.
- `--week-numbers` — add a left-hand column of ISO week numbers.
- `--verbose`, `--json-log`

## Using it

```
«  ‹   August 2026   ›  »
```

Years bracket months in the header, and the doubled glyph takes the coarser
step — at 234px the nesting and the stroke count are the only things telling the
two apart.

| | |
|---|---|
| Click the icon | open / close the panel |
| `‹` `›`, `←` `→`, `PgUp` `PgDn`, `h` `l` | previous / next month |
| `«` `»`, `↑` `↓`, `k` `j` | previous / next year |
| Scroll wheel | previous / next month |
| `Home`, `t`, `.` | back to today |
| Click the month title | back to today |
| `Esc`, `q`, click outside | close |

The panel always opens on the current month rather than wherever you last paged
to — a tray calendar showing August because that is where you left it three days
ago is a small lie about the date.

The tooltip carries the long form and the ISO week:

```
Monday, 3 August 2026
2026-08-03 · week 32
```

### Day rollover

The icon and the highlight follow the local date without a restart. The timer
re-checks at least hourly rather than sleeping straight to midnight, because
GLib timers run on the monotonic clock — a suspend across midnight, an NTP step
or a timezone change would otherwise leave yesterday on screen until something
else woke the process. If the panel is open at midnight it follows into the new
month, unless you have paged away, in which case it leaves you where you are.

## No keybinding

The panel opens by clicking the tray icon and by nothing else. A `MODKEY`
toggle would mean a socket or a signal handler and a second entry point to keep
alive, for a window that is already one click away in the corner it lives in.
If that turns out to be wrong, the hook is `TrayIcon._on_activate`.

## Layout

```
src/da/
├── month.py       # the grid: pure, no GTK, no clock -- most of the tests
├── clock.py       # day rollover
├── log.py
├── app.py         # instance lock, argument parsing, GTK main loop
└── ui/
    ├── geometry.py  # where the panel lands, pure
    ├── icon.py      # the tray glyph, Cairo
    ├── popup.py     # the panel, the seat grab
    └── tray.py      # Gtk.StatusIcon
```
