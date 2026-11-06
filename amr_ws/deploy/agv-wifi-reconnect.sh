#!/bin/bash
# Keeps agv_field and the path to the station's broker working (alpha-setup 2.3).
# Installed as /usr/local/sbin/agv-wifi-reconnect by install.sh and run as root by
# agv-wifi-reconnect.service: NetworkManager's polkit policy refuses scan requests
# from the operator account, and reloading the driver needs root.
#
# The vehicle runs without Wi-Fi. Nothing here touches the wired ports, CAN or amr.service,
# and nothing in the motion stack reads what this does.
#
# 1. Rejoin. Left alone, NetworkManager gives up on an activation ~15 s after the AP vanishes,
#    can end it as a false "no-secrets" (2026-11-06, 16:04:59), and then only rejoins when one
#    of its background scans sees the SSID; those back off to ~2 min apart. Here, while
#    unassociated, we scan every few seconds and bring the profile up the moment the SSID is heard.
# 2. Repair, with back-off, every action logged. Out of range nothing fires: going out of range
#    happens on every far trip, and neither action can help.
#      associated, broker path dead 30 s      nmcli con up
#      AP heard, cannot associate for 60 s    reload iwlwifi
#      device unavailable, or activating
#      without end, or no network heard
#      at all, for 60 s                       reload iwlwifi
#    The broker is also the gateway, and a powered-off station PC looks like a dead path. So
#    associated with a dead path never reloads the driver, and "connection refused" (the PC
#    answers, its broker does not) is not a Wi-Fi problem and repairs nothing.
set -uo pipefail

IFACE=${WIFI_IFACE:-wlp1s0}
CON=${WIFI_CON:-agv-net}
SSID=${WIFI_SSID:-agv_field}
SCAN_EVERY=${WIFI_SCAN_EVERY:-3}   # s between scans while out of range
# NM signal %, 0-100. Below this an attempt usually times out at the edge of range and
# holds the device in "connecting" for ~20 s, delaying the next, better attempt.
MIN_SIGNAL=${WIFI_MIN_SIGNAL:-25}
OPER=${WIFI_OPER:-/sys/class/net/$IFACE/operstate}
BROKER=${WIFI_BROKER:-192.168.2.5}
BROKER_PORT=${WIFI_BROKER_PORT:-1883}
PROBE_EVERY=${WIFI_PROBE_EVERY:-5}       # s between broker checks while associated
CONUP_AFTER=${WIFI_CONUP_AFTER:-30}      # s of a dead broker path before nmcli con up
RELOAD_AFTER=${WIFI_RELOAD_AFTER:-60}    # s of a stuck radio before reloading the driver
CONUP_GAP_MAX=${WIFI_CONUP_GAP_MAX:-600} # the con up back-off doubles from CONUP_AFTER to this
RELOAD_GAP=${WIFI_RELOAD_GAP:-300}       # first gap between reloads; doubles
RELOAD_GAP_MAX=${WIFI_RELOAD_GAP_MAX:-3600}
TICK=${WIFI_TICK:-1}
CONNECT_WAIT=${WIFI_CONNECT_WAIT:-30}    # nmcli --wait
MAX_LOOPS=${WIFI_MAX_LOOPS:-0}           # tests only; 0 = run forever

SECONDS=1  # 0 means "not set" in the timers below
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

# ok: connected. refused: the host answered, its broker did not. dead: no answer at all.
probe_broker() {
  if [[ -n ${WIFI_PROBE_CMD:-} ]]; then
    $WIFI_PROBE_CMD
    return
  fi
  local err
  if err=$(timeout 3 bash -c "exec 3<>/dev/tcp/$BROKER/$BROKER_PORT" 2>&1); then
    echo ok
  elif [[ $err == *refused* ]]; then
    echo refused
  else
    echo dead
  fi
}

reload_at=0 reload_gap=$RELOAD_GAP
reload_driver() {  # <why>
  local now=$SECONDS
  if (( reload_at > 0 && now - reload_at < reload_gap )); then
    say hold "$1: holding the reload, next one in $(( reload_gap - (now - reload_at) )) s"
    return 1
  fi
  echo "$1: reloading iwlwifi"
  if modprobe -r iwlmvm iwlwifi 2>&1 && modprobe iwlwifi 2>&1; then
    echo "iwlwifi reloaded"
  else
    echo "iwlwifi reload failed"
  fi
  if (( reload_at > 0 )); then
    reload_gap=$(( reload_gap * 2 > RELOAD_GAP_MAX ? RELOAD_GAP_MAX : reload_gap * 2 ))
  fi
  reload_at=$SECONDS
  stuck_since=0 heard_fail_since=0 deaf_since=0
  last=""
  return 0
}

path_dead_since=0 conup_at=0 conup_gap=$CONUP_AFTER probe_at=-$PROBE_EVERY
heard_fail_since=0 stuck_since=0 deaf_since=0

# Associated: check the path to the broker, and repair a dead one with con up only.
watch_path() {
  (( SECONDS - probe_at < PROBE_EVERY )) && return
  probe_at=$SECONDS
  case $(probe_broker) in
    ok)
      if (( path_dead_since > 0 )); then
        echo "broker path back after $(( SECONDS - path_dead_since )) s"
      fi
      path_dead_since=0 conup_gap=$CONUP_AFTER
      say up "associated, broker reachable"
      ;;
    refused)
      path_dead_since=0 conup_gap=$CONUP_AFTER
      say refused "associated, $BROKER answers but its broker refuses: not a Wi-Fi problem"
      ;;
    *)
      (( path_dead_since == 0 )) && { path_dead_since=$SECONDS; echo "associated, no answer from $BROKER"; }
      local dead=$(( SECONDS - path_dead_since ))
      if (( dead >= CONUP_AFTER && SECONDS - conup_at >= conup_gap )); then
        echo "no answer from $BROKER for $dead s: nmcli con up (next no sooner than $conup_gap s)"
        conup_at=$SECONDS
        out=$(nmcli --wait "$CONNECT_WAIT" con up "$CON" ifname "$IFACE" 2>&1) || echo "con up failed: ${out//$'\n'/ }"
        conup_gap=$(( conup_gap * 2 > CONUP_GAP_MAX ? CONUP_GAP_MAX : conup_gap * 2 ))
      fi
      ;;
  esac
}

# 1 when `since` has been set for RELOAD_AFTER seconds; sets it on first sight.
overdue() {  # <name of the since variable>
  local -n since=$1
  (( since == 0 )) && since=$SECONDS
  (( SECONDS - since >= RELOAD_AFTER ))
}

echo "watching $IFACE for $SSID (profile $CON, broker $BROKER:$BROKER_PORT, scan every ${SCAN_EVERY}s, min signal $MIN_SIGNAL%)"
loops=0
while :; do
  if (( MAX_LOOPS > 0 )); then
    (( ++loops > MAX_LOOPS )) && exit 0
  fi
  if associated; then
    stuck_since=0 heard_fail_since=0 deaf_since=0 reload_gap=$RELOAD_GAP
    watch_path
    sleep "$TICK"
    continue
  fi
  path_dead_since=0 conup_gap=$CONUP_AFTER

  state=$(nm_state)
  if (( state >= 40 && state < 100 )); then
    # NM is already connecting; a second "con up" would restart it. Unless it never ends.
    overdue stuck_since && reload_driver "NM activating for over $RELOAD_AFTER s (state $state)"
    sleep "$TICK"
    continue
  fi
  stuck_since=0
  if (( state < 30 )); then
    if [[ $(nmcli -t radio wifi 2>/dev/null) == disabled ]]; then
      # Someone switched it off (tools/wifi_recovery_test.sh does): that is not a hung driver.
      say radiooff "Wi-Fi radio switched off in NetworkManager: leaving it alone"
      deaf_since=0
    else
      say unavail "$IFACE unavailable (NM state $state: device missing or driver hung)"
      overdue deaf_since && reload_driver "$IFACE unavailable for over $RELOAD_AFTER s"
    fi
    sleep "$SCAN_EVERY"
    continue
  fi

  # --rescan yes blocks until the scan completes (~2-4 s on the 7260, both bands).
  scan=$(nmcli -t -f SSID,SIGNAL dev wifi list ifname "$IFACE" --rescan yes 2>/dev/null) || scan=""
  signal=$(awk -F: -v s="$SSID" '$1 == s && $2 > m { m = $2 } END { print m + 0 }' <<<"$scan")
  if (( signal == 0 )); then
    say gone "$SSID out of range, scanning"
    heard_fail_since=0
    # Out of range still hears other networks. Hearing nothing at all is a deaf radio.
    if [[ -n ${scan//[[:space:]]/} ]]; then
      deaf_since=0
    else
      overdue deaf_since && reload_driver "no network heard at all for over $RELOAD_AFTER s"
    fi
    sleep "$SCAN_EVERY"
    continue
  fi
  deaf_since=0
  if (( signal < MIN_SIGNAL )); then
    say weak "$SSID heard at ${signal}% (< $MIN_SIGNAL%), waiting for a usable signal"
    heard_fail_since=0
    sleep "$SCAN_EVERY"
    continue
  fi

  # NM autoconnects off fresh scan results by itself; give it a moment before forcing.
  sleep "${WIFI_SETTLE:-2}"
  associated && continue
  state=$(nm_state)
  (( state >= 40 && state < 100 )) && continue

  echo "$SSID at ${signal}%, bringing up $CON"
  if out=$(nmcli --wait "$CONNECT_WAIT" con up "$CON" ifname "$IFACE" 2>&1); then
    last=""
    heard_fail_since=0
  else
    last=""   # log the next attempt too
    echo "con up failed: ${out//$'\n'/ }"
    overdue heard_fail_since && reload_driver "$SSID heard, cannot associate for over $RELOAD_AFTER s"
    sleep "$SCAN_EVERY"
  fi
done
