# displayd

A single user-level display management daemon. It runs a tray icon and an
arandr-style layout editor on a GTK main loop, while a background thread
watches udev (hotplug), logind (resume, session lock/unlock) and UPower
(lid state) and automatically applies the matching saved profile whenever
the monitor topology changes. No root daemon, no socket.

## Install

```sh
make install
```

Upgrading from the old split setup (root `displayd-watcher` + session
`displayd-agent`)? Clean up the old units and processes first:

```sh
sudo make migrate
```

## Start

Pick **one** of the two methods. Either from dwm's `autostart.sh`:

```sh
nohup displayd >>/tmp/displayd.log 2>&1 &
```

or via the systemd user unit (requires a managed `graphical-session.target`
and `systemctl --user import-environment DISPLAY`):

```sh
systemctl --user enable --now displayd
```

A file lock in `$XDG_RUNTIME_DIR` guarantees a single instance per user;
a second invocation prints "displayd is already running" and exits 0, so
restarting dwm (which re-runs `autostart.sh`) is harmless.

## Profiles

Profiles live in `~/.config/displayd/profiles`, one JSON file per profile,
keyed by a hash of the connected monitors (EDID identity plus lid state).

## Commands

- `displayd` — run the daemon (tray icon plus auto-apply).
  - `--no-tray` — run headless, auto-apply only.
  - `--editor` — open the layout editor window directly.
- `displayd-ctl` — one-shot control commands:
  - `status` — show matched profile and sync state.
  - `show` — show current display topology.
  - `sync` — apply the matched profile to the current topology.
  - `save NAME` — save the current layout as a profile.
  - `list` — list saved profiles.
  - `delete NAME` — delete a saved profile.
