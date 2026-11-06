#!/bin/bash
# How long the Wi-Fi and the station link take to come back. Run as root, detached, with the AGV idle at
# home and no call queued. It cuts Wi-Fi, so it also cuts SSH and the station's link:
#
#   sudo systemd-run --unit=wifi-recovery-test --collect /home/gvipc-evo-01/agv_can/tools/wifi_recovery_test.sh
#   results:  ~/.amr/logs/wifi-recovery-<date>.csv     progress: journalctl -u wifi-recovery-test
#   stop it:  sudo systemctl stop wifi-recovery-test   (Wi-Fi comes back on)
#
# Radio off for 30 s, 2 min and 10 min, 3 times each, then one driver reload: about 45 min. --quick does
# one 30 s cut and one reload. It stops before the next cut if the AGV stops being idle, and it sends
# nothing to the vehicle. A radio cut next to the AP does not reproduce walking out of range: that needs
# the AP powered off, or a real far trip (journalctl -u agv-wifi-reconnect, and STATION_LINK_* events).
set -uo pipefail

LOG_DIR=${WIFI_TEST_LOGS:-/home/gvipc-evo-01/.amr/logs}
BROKER=${WIFI_BROKER:-192.168.2.5}
PORT=${WIFI_BROKER_PORT:-1883}
LIMIT=${WIFI_TEST_LIMIT:-300}     # s to wait for each recovery before calling it failed
SETTLE=${WIFI_TEST_SETTLE:-30}    # s between tests
CUTS=(30 30 30 120 120 120 600 600 600)
RELOADS=1
if [[ ${1:-} == --quick ]]; then
  CUTS=(30)
fi

CSV="$LOG_DIR/wifi-recovery-$(date +%Y%m%d-%H%M%S).csv"
echo "test,off_s,s_to_associated,s_to_broker_tcp,s_to_mqtt_session,result" >"$CSV"
chown --reference="$LOG_DIR" "$CSV" 2>/dev/null

failsafe=""
radio_on() { nmcli radio wifi on; }
finish() {
  [[ -n $failsafe ]] && kill "$failsafe" 2>/dev/null
  radio_on
}
trap finish EXIT
trap 'echo "stopped"; exit 1' INT TERM

idle() {  # 0 when parked at home, not running, nothing queued. Prints why not.
  curl -s -m 3 http://localhost:5001/api/state | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit("no reply from the web service")
l, w = d.get("line") or {}, d.get("wheels") or {}
why = []
if l.get("state") not in (0, 4):
    why.append(f"line state {l.get(\"state\")}")
if l.get("drive_power"):
    why.append("drives powered")
if abs(w.get("v_mps") or 0.0) > 0.001:
    why.append("wheels moving")
if l.get("trip"):
    why.append(f"trip {l[\"trip\"]}")
sys.exit("; ".join(why) or 0)
'
}

service_mark() { systemctl show amr.service -p ActiveEnterTimestamp -p NRestarts -p MainPID | tr '\n' ' '; }

associated() { [[ $(nmcli -g GENERAL.STATE dev show wlp1s0 2>/dev/null) == 100* ]]; }
broker_tcp() { timeout 3 bash -c "exec 3<>/dev/tcp/$BROKER/$PORT" 2>/dev/null; }
mqtt_session() { [[ -n $(ss -Htn state established dst "$BROKER" dport = :"$PORT" 2>/dev/null) ]]; }

# Seconds from now to each stage. The MQTT session is the bridge's own connection: the old one has to be
# gone first, which the cut guarantees.
measure() {  # <name> <off_s>
  local t0=$SECONDS a="" b="" m="" result=ok
  while (( SECONDS - t0 < LIMIT )); do
    [[ -z $a ]] && associated && a=$(( SECONDS - t0 ))
    [[ -n $a && -z $b ]] && broker_tcp && b=$(( SECONDS - t0 ))
    [[ -n $b && -z $m ]] && mqtt_session && m=$(( SECONDS - t0 ))
    [[ -n $m ]] && break
    sleep 1
  done
  [[ -n $m ]] || result=FAILED
  echo "$1,$2,${a:-},${b:-},${m:-},$result" >>"$CSV"
  echo "$1 off ${2} s: associated ${a:--} s, broker ${b:--} s, MQTT session ${m:--} s: $result"
}

before=$(service_mark)
echo "amr.service before: $before"
if ! why=$(idle 2>&1); then
  echo "not idle, nothing done: $why"
  exit 2
fi

n=0
for off in "${CUTS[@]}"; do
  n=$(( n + 1 ))
  if ! why=$(idle 2>&1); then
    echo "stopping before cut $n: not idle: $why"
    exit 3
  fi
  echo "cut $n: radio off for $off s"
  nmcli radio wifi off
  # If this script dies during a cut, Wi-Fi still comes back.
  ( sleep $(( off + 60 )); nmcli radio wifi on ) &
  failsafe=$!
  sleep "$off"
  radio_on
  kill "$failsafe" 2>/dev/null
  failsafe=""
  measure "cut$n" "$off"
  sleep "$SETTLE"
done

for (( r = 1; r <= RELOADS; r++ )); do
  if ! why=$(idle 2>&1); then
    echo "stopping before the reload: not idle: $why"
    exit 3
  fi
  echo "driver reload $r"
  modprobe -r iwlmvm iwlwifi && modprobe iwlwifi
  measure "reload$r" 0
  sleep "$SETTLE"
done

after=$(service_mark)
echo "amr.service after: $after"
if [[ $before == "$after" ]]; then
  echo "amr.service did not restart"
else
  echo "amr.service CHANGED: before [$before] after [$after]"
fi
echo "results: $CSV"
