#!/bin/bash
# Rejoins agv_field as soon as the vehicle is back in range (alpha-setup 2.3).
# Installed as /usr/local/sbin/agv-wifi-reconnect by install.sh and run as root by
# agv-wifi-reconnect.service: NetworkManager's polkit policy refuses scan requests
# from the operator account.
#
# Left alone, NetworkManager gives up on an activation ~15 s after the AP vanishes
# and then only rejoins when one of its background scans sees the SSID; those back
# off to ~2 min apart while disconnected. Here, while unassociated, we scan every few
# seconds and bring the profile up the moment the SSID is heard.
#
# While associated the loop only reads sysfs (no fork), so it costs nothing in range.
# The vehicle runs without Wi-Fi; nothing here touches the wired ports or amr.service.
set -uo pipefail

IFACE=${WIFI_IFACE:-wlp1s0}
CON=${WIFI_CON:-agv-net}
SSID=${WIFI_SSID:-agv_field}
SCAN_EVERY=${WIFI_SCAN_EVERY:-3}   # s between scans while out of range
# NM signal %, 0-100. Below this an attempt usually times out at the edge of range and
# holds the device in "connecting" for ~20 s, delaying the next, better attempt.
MIN_SIGNAL=${WIFI_MIN_SIGNAL:-25}
OPER=/sys/class/net/$IFACE/operstate

last=""
say() {  # <key> <message>: log transitions only, not every loop
  [[ "$1" == "$last" ]] && return
  last=$1
  echo "$2"
}

nm_state() {  # NM device state number: 30 disconnected, 40-90 activating, 100 connected
  local s
  s=$(nmcli -g GENERAL.STATE dev show "$IFACE" 2>/dev/null) || s=""
  s=${s%% *}
  [[ $s =~ ^[0-9]+$ ]] && echo "$s" || echo 0
}

associated() {
  local op
  read -r op 2>/dev/null <"$OPER" || return 1
  [[ $op == up ]]
}

echo "watching $IFACE for $SSID (profile $CON, scan every ${SCAN_EVERY}s, min signal $MIN_SIGNAL%)"
while :; do
  if associated; then
    say up "associated"
    sleep 1
    continue
  fi

  state=$(nm_state)
  if (( state >= 40 && state < 100 )); then
    sleep 1   # NM is already connecting; a second "con up" would restart it
    continue
  fi
  if (( state < 30 )); then
    say unavail "$IFACE unavailable (NM state $state: radio off or device missing)"
    sleep "$SCAN_EVERY"
    continue
  fi

  # --rescan yes blocks until the scan completes (~2-4 s on the 7260, both bands).
  signal=$(nmcli -t -f SSID,SIGNAL dev wifi list ifname "$IFACE" --rescan yes 2>/dev/null |
           awk -F: -v s="$SSID" '$1 == s && $2 > m { m = $2 } END { print m + 0 }')
  if (( signal == 0 )); then
    say gone "$SSID out of range, scanning"
    sleep "$SCAN_EVERY"
    continue
  fi
  if (( signal < MIN_SIGNAL )); then
    say weak "$SSID heard at ${signal}% (< $MIN_SIGNAL%), waiting for a usable signal"
    sleep "$SCAN_EVERY"
    continue
  fi

  # NM autoconnects off fresh scan results by itself; give it a moment before forcing.
  sleep 2
  associated && continue
  state=$(nm_state)
  (( state >= 40 && state < 100 )) && continue

  echo "$SSID at ${signal}%, bringing up $CON"
  if out=$(nmcli --wait 30 con up "$CON" ifname "$IFACE" 2>&1); then
    say up "associated"
  else
    last=""   # log the next attempt too
    echo "con up failed: ${out//$'\n'/ }"
    sleep "$SCAN_EVERY"
  fi
done
