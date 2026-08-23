#!/bin/bash
# End-to-end smoke test in an isolated Xvfb + D-Bus + XDG sandbox.
# Artifacts (screenshots, logs, transcript) land in /tmp/clipd-smoke.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ART=/tmp/clipd-smoke
rm -rf "$ART"
mkdir -p "$ART/xdg-data" "$ART/xdg-config"

XDG_DATA_HOME="$ART/xdg-data" XDG_CONFIG_HOME="$ART/xdg-config" \
GSK_RENDERER=cairo CLIPD_ROOT="$ROOT" CLIPD_ART="$ART" \
xvfb-run -a -s "-screen 0 1280x800x24" \
    dbus-run-session -- bash "$ROOT/smoke/inner.sh"
status=$?
echo "== artifacts =="
ls -la "$ART"
exit $status
