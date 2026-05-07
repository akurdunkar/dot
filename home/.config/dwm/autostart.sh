#!/bin/bash
(
	source $HOME/.rc
	source $HOME/.colors
	feh --bg-scale $HOME/wall.jpg
	slstatus &
	pasystray &
	nm-applet &
	blueman-applet &
	dunst --startup-notification true &
	albert &
	copyq &
	gsimplecal &
	if [ -n "$DISPLAY" ]; then
		pgrep -xa "displayd-agent" | grep displayd-agent 2>&1 >/dev/null || (nohup displayd-agent >>/tmp/displayd-agent.log 2>&1 &)
		displayd-ctl sync
	fi
) 2>&1 >/tmp/dwm.log
