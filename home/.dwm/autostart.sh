#!/bin/bash

(
	source $HOME/.rc
	source $HOME/.colors
	feh --bg-scale $HOME/wall.jpg
	picom &
	slstatus &
	nm-applet &
	dunst &
	flameshot &
	albert &
) 2>&1 >/tmp/dwm.log
