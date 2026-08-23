#!/bin/bash
# Runs inside Xvfb+dbus. Drives clipd end to end and screenshots the UI.
set -u
FAIL=0
say() { echo "== $*"; }
check() { # check <label> <expected> <actual>
    if [ "$2" = "$3" ]; then say "PASS: $1"; else say "FAIL: $1 (expected [$2] got [$3])"; FAIL=1; fi
}
shot() { import -window root "$CLIPD_ART/$1.png" 2>/dev/null; say "shot $1"; }

clipd() { PYTHONPATH="$CLIPD_ROOT/src" python3 -c 'import sys; from clipd.app import main; sys.exit(main())' "$@"; }

wait_daemon() { # poll the bus name: never spawns a competing primary instance
    for _ in $(seq 1 50); do
        out=$(gdbus call --session --dest org.freedesktop.DBus \
            --object-path /org/freedesktop/DBus \
            --method org.freedesktop.DBus.NameHasOwner org.clipd.Clipd 2>/dev/null)
        [ "$out" = "(true,)" ] && return 0
        sleep 0.2
    done
    say "FAIL: daemon never appeared on the bus"; FAIL=1; return 1
}

focus_popup() {
    WID=$(xdotool search --name '^clipd$' | head -1)
    xdotool windowfocus --sync "$WID" 2>/dev/null
    sleep 0.3
}

say "starting daemon"
clipd > "$CLIPD_ART/daemon.log" 2>&1 &
DAEMON=$!
wait_daemon

say "feeding clipboard entries via xclip"
printf 'alpha bravo charlie' | xclip -selection clipboard; sleep 0.4
printf 'def fzf_match(query: str) -> int:\n    return 42' | xclip -selection clipboard; sleep 0.4
printf 'https://wiki.archlinux.org/title/Clipboard' | xclip -selection clipboard; sleep 0.4
printf 'unicode caf\xc3\xa9 \xf0\x9f\x8e\x89 snippet' | xclip -selection clipboard; sleep 0.4
convert -size 200x120 gradient:tomato-navy "$CLIPD_ART/src.png"
xclip -selection clipboard -t image/png -i "$CLIPD_ART/src.png"; sleep 0.6

say "CLI: list"
clipd list | tee "$CLIPD_ART/list.txt"
count=$(wc -l < "$CLIPD_ART/list.txt")
check "5 entries captured" 5 "$count"

say "CLI: dedupe bump (recopy alpha)"
printf 'alpha bravo charlie' | xclip -selection clipboard; sleep 0.5
count=$(clipd list | wc -l)
check "still 5 entries after dup" 5 "$count"
top=$(clipd list | head -1 | cut -f4)
check "alpha bumped to top" "alpha bravo charlie" "$top"

say "CLI: pin + get + copy roundtrip"
url_id=$(clipd list | awk -F'\t' '$4 ~ /archlinux/ {print $1}')
clipd pin "$url_id"
pin_flag=$(clipd list | awk -F'\t' -v id="$url_id" '$1 == id {print $2}')
check "pin flag set" "*" "$pin_flag"
first=$(clipd list | head -1 | cut -f1)
check "pinned entry listed first" "$url_id" "$first"
clipd copy "$url_id"; sleep 0.4
check "copy roundtrip via xclip -o" "https://wiki.archlinux.org/title/Clipboard" "$(xclip -selection clipboard -o)"
alpha_id=$(clipd list | awk -F'\t' '$4 ~ /alpha/ {print $1}')
check "get returns full text" "alpha bravo charlie" "$(clipd get "$alpha_id")"

say "CLI: image save"
img_id=$(clipd list | awk -F'\t' '$3 == "image" {print $1}')
clipd save "$img_id" "$CLIPD_ART/saved.png"
dims=$(identify -format '%wx%h' "$CLIPD_ART/saved.png" 2>/dev/null)
check "image roundtrip dimensions" "200x120" "$dims"

say "GUI: popup + screenshots"
clipd show; sleep 1.2
shot 01-popup
focus_popup
xdotool type --delay 60 'fzf'; sleep 0.8
shot 02-search-highlight
xdotool key ctrl+p; sleep 0.4    # pin the selected (code snippet) row
shot 03-pinned-row
clipd hide; sleep 0.3
clipd show; sleep 0.8            # fresh popup, empty query
shot 04-popup-fresh
focus_popup
xdotool type --delay 60 'zzzqqq'; sleep 0.8
shot 05-no-matches
xdotool key BackSpace BackSpace BackSpace BackSpace BackSpace BackSpace; sleep 0.6

say "GUI: Enter copies selected entry"
vis=$(xdotool search --onlyvisible --name '^clipd$' 2>/dev/null | wc -l)
check "popup visible before enter" 1 "$vis"
xdotool type --delay 60 'unicode'; sleep 0.8
xdotool key Return; sleep 0.8
check "enter copied entry" "unicode café 🎉 snippet" "$(xclip -selection clipboard -o)"
vis=$(xdotool search --onlyvisible --name '^clipd$' 2>/dev/null | wc -l)
check "popup hidden after enter" 0 "$vis"

say "persistence: restart daemon"
clipd quit; sleep 1
kill -0 $DAEMON 2>/dev/null && { say "FAIL: daemon still alive after quit"; FAIL=1; }
clipd > "$CLIPD_ART/daemon2.log" 2>&1 &
wait_daemon
clipd list | tee "$CLIPD_ART/list-after-restart.txt"
count=$(wc -l < "$CLIPD_ART/list-after-restart.txt")
check "entries persisted" 5 "$count"
first=$(clipd list | head -1 | cut -f2)
check "pins persisted and sort first" "*" "$first"
clipd quit; sleep 0.5

say "done (FAIL=$FAIL)"
exit $FAIL
