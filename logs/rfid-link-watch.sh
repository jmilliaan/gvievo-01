#!/bin/bash
# Soaks the LAN1 <-> RFID reader link and records every carrier flap, error-counter
# tick and reachability loss. Vibration-induced faults only appear while the vehicle
# is MOVING, so run this during real driving, not on a bench at standstill.
# Readable without root.
OUT=/home/gvipc-evo-01/agv_can/logs/rfid-link-watch.log
IF=enp2s0
READER=192.168.1.200
PORT=2022

err_sum() {   # total of every non-zero error/drop/discard counter
  ethtool -S "$IF" 2>/dev/null | awk -F: '
    /error|drop|discard|crc|fail|miss|no_buffer|collision/ {
      gsub(/ /,"",$2); if ($2 ~ /^[0-9]+$/) s+=$2 } END {print s+0}'
}

snap() {
  local carrier speed rtt tcp
  carrier=$(cat /sys/class/net/$IF/carrier 2>/dev/null || echo "-")
  speed=$(cat /sys/class/net/$IF/speed 2>/dev/null || echo "-")
  rtt=$(ping -c 1 -W 1 -I "$IF" "$READER" 2>/dev/null \
        | awk -F'time=' '/time=/{print $2+0; exit}')
  [ -z "$rtt" ] && rtt="LOSS"
  if timeout 1 bash -c "echo >/dev/tcp/$READER/$PORT" 2>/dev/null; then tcp=ok; else tcp=REFUSED; fi
  printf "%s up=%s carrier=%s speed=%s rtt_ms=%s tcp=%s errs=%s %s\n" \
    "$(date -Is)" "$(awk '{printf "%.0f",$1}' /proc/uptime)" \
    "$carrier" "$speed" "$rtt" "$tcp" "$(err_sum)" "$1"
}

trap 'snap "<<< SIGTERM - watcher stopping >>>" >> "$OUT"; sync; exit 0' TERM INT

echo "=== rfid-link-watch started $(date -Is) boot=$(cat /proc/sys/kernel/random/boot_id) ===" >> "$OUT"
prev_carrier=""; prev_errs=""
while :; do
  line=$(snap)
  c=$(sed -n 's/.*carrier=\([^ ]*\).*/\1/p' <<<"$line")
  e=$(sed -n 's/.*errs=\([^ ]*\).*/\1/p' <<<"$line")
  # Log every sample, but shout on a TRANSITION so a flap is greppable.
  if [ -n "$prev_carrier" ] && [ "$c" != "$prev_carrier" ]; then
    line="$line  *** CARRIER $prev_carrier -> $c ***"
  fi
  if [ -n "$prev_errs" ] && [ "$e" != "$prev_errs" ]; then
    line="$line  *** ERRS $prev_errs -> $e ***"
  fi
  echo "$line" >> "$OUT"
  prev_carrier=$c; prev_errs=$e
  sleep 1
done
