#!/bin/bash

batteryPercentage=$(cat /sys/class/power_supply/BAT0/capacity)
charging=$(acpi | awk '{print $3}')
NFILE="$HOME/scripts/nfile"
minValue=20

[[ $batteryPercentage -lt $minValue ]] && ! [[ -e "$NFILE" ]] && touch "$NFILE" && notify-send -u critical Low\ Battery! Please\ Plugin\ The\ Charge

! [[ $batteryPercentage -lt $minValue ]] && rm "$NFILE"

printf " ^c$YELLOW_COLOR^  $batteryPercentage $([ $charging == "Charging," ] && echo " ")"
