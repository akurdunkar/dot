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
) 2>&1 >/tmp/dwm.log
