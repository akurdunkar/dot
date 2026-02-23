#!/bin/bash

(
	source $HOME/.rc
	source $HOME/.colors
	feh --bg-scale $HOME/wall.jpg
	picom --daemon
	slstatus &
	nm-applet &
	blueman-applet &
	dunst &
	flameshot &
	albert &
) 2>&1 >/tmp/dwm.log
