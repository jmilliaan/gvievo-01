#!/bin/bash
# P8: cheap deployment validation. No service state or hardware is changed.
set -euo pipefail

DEPLOY_DIR=$(cd "$(dirname "$0")" && pwd)
WORKSPACE=$(cd "$DEPLOY_DIR/.." && pwd)
UNITS=(amr.service)

for path in \
  "$DEPLOY_DIR/amr-supervisor.sh" \
  "$DEPLOY_DIR/install.sh" \
  "$DEPLOY_DIR/amr-orphan-stop.sh" \
  "$DEPLOY_DIR/amr-orphan-stop.py" \
  "$DEPLOY_DIR/amr-stop-post.sh" \
  "$DEPLOY_DIR/amr-failed.py" \
  "$DEPLOY_DIR/70-canable.rules.in" \
  "$WORKSPACE/install/setup.bash" \
  "$WORKSPACE/env/vehicle.sh"; do
  [[ -f "$path" ]] || { echo "missing required path: $path" >&2; exit 1; }
done

bash -n "$DEPLOY_DIR/amr-supervisor.sh" "$DEPLOY_DIR/install.sh" "$DEPLOY_DIR/trim-services.sh"
bash -n "$DEPLOY_DIR/agv-wifi-reconnect.sh"
bash -n "$DEPLOY_DIR/amr-orphan-stop.sh" "$DEPLOY_DIR/amr-stop-post.sh" "$DEPLOY_DIR/platform/freeze.sh"
python3 - "$DEPLOY_DIR/amr-orphan-stop.py" "$DEPLOY_DIR/amr-failed.py" <<'PY'
import sys
for p in sys.argv[1:]:
    compile(open(p, encoding="utf-8").read(), p, "exec")
PY
for x in amr-orphan-stop.sh amr-stop-post.sh amr-supervisor.sh; do
  [[ -x "$DEPLOY_DIR/$x" ]] || { echo "$x is not executable (amr.service runs it directly)" >&2; exit 1; }
done
# amr.service names amr-failed.service (OnFailure) and canable@can0 (WantedBy): verify them
# together, the template through an instance copy.
verify_tmp=$(mktemp -d)
cp "$DEPLOY_DIR/canable@.service" "$verify_tmp/canable@can0.service"
systemd-analyze verify "$DEPLOY_DIR/amr.service" "$DEPLOY_DIR/amr-failed.service" "$verify_tmp/canable@can0.service"
rm -rf "$verify_tmp"
for unit in cpu-freq-cap.service cpu-power-limit.service; do
  systemd-analyze verify "$DEPLOY_DIR/$unit"
done
if command -v visudo >/dev/null; then
  visudo -cqf "$DEPLOY_DIR/amr-web.sudoers" || { echo "amr-web.sudoers does not parse (visudo -cf)" >&2; exit 1; }
fi

# Every ${VAR} a unit's Exec lines use must be defined by that unit's EnvironmentFile
# (or Environment=). Found 2026-09-16: amr.env lost AMR_MAP_ID while the (since
# retired) amr_nav.service still used it, and the installed unit restart-looped.
for unit in "${UNITS[@]}"; do
  envfile=$(sed -n 's/^EnvironmentFile=-\{0,1\}//p' "$DEPLOY_DIR/$unit" | head -1)
  envfile_local="$DEPLOY_DIR/$(basename "${envfile:-/nonexistent}")"
  defined=$( { [[ -f "$envfile_local" ]] && sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' "$envfile_local"; \
               sed -n 's/^Environment=\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' "$DEPLOY_DIR/$unit"; } | sort -u)
  for var in $(grep -E '^Exec' "$DEPLOY_DIR/$unit" | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*\}' | tr -d '${}' | sort -u); do
    if ! grep -qx "$var" <<<"$defined"; then
      echo "$unit uses \${$var} but $(basename "${envfile:-<no EnvironmentFile>}") does not define it" >&2
      exit 1
    fi
  done
done

if grep -Eq '^[[:space:]]*systemctl[[:space:]]+(enable|disable|start|stop|restart)' \
  "$DEPLOY_DIR/install.sh"; then
  echo "installer must not change service enable/run state" >&2
  exit 1
fi

# The vehicle library must be where env/vehicle.sh puts it on PYTHONPATH.
# Without agv_core every amr_base node dies on its first import, and the unit
# restart-loops with a traceback that names no unit file - so check it here,
# where the message can say what is actually wrong.
REPO_ROOT=$(cd "$DEPLOY_DIR/../.." && pwd)
for required in "agv_core/__init__.py" "agv_core/config.py" "profiles"; do
  if [[ ! -e "$REPO_ROOT/$required" ]]; then
    echo "vehicle library incomplete: $REPO_ROOT/$required is missing" >&2
    echo "env/vehicle.sh puts the repo root on PYTHONPATH; agv_core must live there" >&2
    exit 1
  fi
done

# The watchdog is only real if the unit asks for it AND the process is told the
# timeout: Type=notify without WatchdogSec is a no-op, and sdnotify.py then pings
# nothing (power-loss plan W5).
for unit in "${UNITS[@]}"; do
  if grep -q '^Type=notify' "$DEPLOY_DIR/$unit"; then
    grep -q '^WatchdogSec=' "$DEPLOY_DIR/$unit" || {
      echo "$unit is Type=notify but sets no WatchdogSec: the watchdog does nothing" >&2; exit 1; }
    grep -q '^NotifyAccess=' "$DEPLOY_DIR/$unit" || {
      echo "$unit is Type=notify but sets no NotifyAccess" >&2; exit 1; }
  fi
done
if [[ -f /etc/systemd/system/amr.service ]]; then
  live=$(systemctl show -p WatchdogUSec --value amr.service 2>/dev/null || echo 0)
  case "$live" in
    0|""|0s) echo "note: installed amr.service has no watchdog yet (run install.sh, then restart)";;
    *) echo "watchdog armed on the installed unit: $live";;
  esac
fi

# Journal size (W7): persistent and uncapped is how a root filesystem fills up.
if command -v journalctl >/dev/null; then
  usage=$(journalctl --disk-usage 2>/dev/null | grep -oE '[0-9.]+[KMG]' | head -1 || true)
  if [[ -n "$usage" ]]; then
    mb=$(awk -v u="$usage" 'BEGIN{n=u+0; s=substr(u,length(u));
         print (s=="G")? n*1024 : (s=="K")? n/1024 : n}')
    if (( $(awk -v m="$mb" 'BEGIN{print (m>400)}') )); then
      echo "warning: journal is $usage (cap is 300M); install journald-amr.conf and" >&2
      echo "         run: sudo journalctl --vacuum-size=300M" >&2
    else
      echo "journal on disk: $usage"
    fi
  fi
fi

# The kiosk scripts run from /usr/local/bin and are installed by hand; the copies here
# are the versioned ones (unified plan WP-0E). Say when they differ, either way round.
for f in "$DEPLOY_DIR"/kiosk/*; do
  live="/usr/local/bin/$(basename "$f")"
  if [[ ! -f "$live" ]]; then
    echo "note: $live is not installed (copy of $f)"
  elif ! cmp -s "$f" "$live"; then
    echo "note: $live differs from deploy/kiosk/$(basename "$f"); install it with:" \
         "sudo install -m 0755 $f $live"
  fi
done
live_watch="$REPO_ROOT/logs/pwrbtn-watch.sh"
if [[ -f "$live_watch" ]] && ! cmp -s "$DEPLOY_DIR/pwrbtn-watch.sh" "$live_watch"; then
  echo "note: logs/pwrbtn-watch.sh differs from deploy/pwrbtn-watch.sh (the cron job runs the logs/ copy)"
fi

# Which vehicle (manuals/agv-02-plan.md R2, R3): the profile the service will load, from the service
# user's vehicle.env (this runs under sudo, so not from $HOME), checked against the host name.
state_dir=$(sed -n 's/^AMR_STATE_DIR=//p' "$DEPLOY_DIR/amr.env" | tail -n 1)
AGV_PROFILE=$(unset AGV_PROFILE; AMR_STATE_DIR="$state_dir"; source "$WORKSPACE/env/vehicle.sh" >/dev/null
              echo "${AGV_PROFILE:-}")
export AGV_PROFILE
[[ -n "$AGV_PROFILE" ]] || unset AGV_PROFILE
PYTHONPATH="$REPO_ROOT" python3 -m agv_core.identity || exit 1

# Station calling (manuals/station-call-plan.md P5): only when the profile turns it on. Silent otherwise.
station_on=$(python3 - "$REPO_ROOT" <<'PY'
import json, os, sys
name = os.environ.get("AGV_PROFILE") or "agv-01"
with open(os.path.join(sys.argv[1], "profiles", f"{name}.json")) as fh:
    print("yes" if json.load(fh)["station"]["enabled"] else "no")
PY
)
if [[ "$station_on" == "yes" ]]; then
  python3 -c "import paho.mqtt.client" 2>/dev/null || {
    echo "station.enabled: paho-mqtt is missing (alpha-setup.md section 5.2)" >&2; exit 1; }
  creds="${AMR_STATE_DIR:-$HOME/.amr}/station-mqtt.json"
  [[ -f "$creds" ]] || { echo "station.enabled: $creds is missing" >&2; exit 1; }
  [[ "$(stat -c %a "$creds")" == "600" ]] || { echo "station.enabled: $creds must be mode 600" >&2; exit 1; }
fi

# Scanner links (unified plan WP-P10): the driver binds the profile's host_ip, so the port the
# scanner is cabled to must carry it. Front: enp3s0 (alpha-setup.md 2.2). Rear: once fitted
# (rear.source scanner), on whichever port the owner gives it. Warnings: a bench PC has no scanner.
read -r lidar_host lidar_sensor rear_source rear_host <<<"$(python3 - "$REPO_ROOT" <<'PY'
import json, os, sys
name = os.environ.get("AGV_PROFILE") or "agv-01"
with open(os.path.join(sys.argv[1], "profiles", f"{name}.json")) as fh:
    p = json.load(fh)
print(p["lidar"]["host_ip"], p["lidar"]["sensor_ip"], p["rear"]["source"], p["rear"]["host_ip"])
PY
)"
if command -v ip >/dev/null; then
  ip -4 -o addr show dev enp3s0 2>/dev/null | grep -qF " $lidar_host/" || \
    echo "warning: enp3s0 does not carry lidar.host_ip $lidar_host: the front scanner ($lidar_sensor) sends to it (alpha-setup.md 2.2)" >&2
  if [[ "$rear_source" == scanner ]]; then
    ip -4 -o addr show 2>/dev/null | grep -qF " $rear_host/" || \
      echo "warning: no interface carries rear.host_ip $rear_host: the rear scanner sends to it" >&2
  fi
fi

# The HMI server (unified plan WP-E5, 2026-11-16). Missing is a warning: serve.py falls back.
python3 -c "import waitress" 2>/dev/null || \
  echo "warning: waitress missing: the HMI runs on the werkzeug dev server (alpha-setup.md 5.2)" >&2
# Wi-Fi power save off on the vehicle connection (WP-E5 delta: set per connection, by hand).
ps=$(nmcli -g 802-11-wireless.powersave con show agv-net 2>/dev/null || true)
[[ "$ps" == 2* || "$ps" == *disable* ]] || \
  echo "warning: agv-net Wi-Fi power save is '${ps:-unknown}', not disable (nmcli con mod agv-net 802-11-wireless.powersave 2)" >&2
# The CPU caps are installed by install.sh and enabled once per unit by hand (WP-P11, O-4).
for unit in cpu-power-limit.service cpu-freq-cap.service; do
  [[ "$(systemctl is-enabled "$unit" 2>/dev/null || true)" == enabled ]] || \
    echo "warning: $unit is not enabled: sudo systemctl enable --now $unit" >&2
done

# Clock steps (unified plan WP-A5): chrony may step the clock only at start. A makestep with
# a limit of -1 steps at any time, under a running vehicle.
if [[ -d /etc/chrony ]]; then
  if grep -rhsE '^[[:space:]]*makestep[[:space:]]+[0-9.]+[[:space:]]+-1' /etc/chrony/chrony.conf /etc/chrony/conf.d >/dev/null; then
    echo "warning: chrony may step the clock at any time (makestep ... -1); install chrony-amr.conf" >&2
  fi
  [[ -f /etc/chrony/conf.d/amr.conf ]] || echo "note: chrony-amr.conf is not installed (run install.sh)"
fi

# Foxglove is retired (unified plan WP-0A): the supervisor has no foxglove parameter,
# so a leftover AMR_FOXGLOVE line does nothing - say so rather than let it mislead.
if grep -q '^AMR_FOXGLOVE=' "$DEPLOY_DIR/amr.env"; then
  echo "warning: amr.env still sets AMR_FOXGLOVE; Foxglove is retired and it does nothing" >&2
fi

# Where the state lives (W8). Not a failure on the bench - the data volume is
# optional - but a vehicle should not keep its maps on the root filesystem.
STATE_DIR=$(sed -n 's/^AMR_STATE_DIR=//p' "$DEPLOY_DIR/amr.env" | head -1)
STATE_DIR=${STATE_DIR/#\~/$HOME}
if [[ -n "$STATE_DIR" ]] && command -v findmnt >/dev/null; then
  src=$(findmnt -no TARGET --target "$STATE_DIR" 2>/dev/null || echo /)
  opts=$(findmnt -no OPTIONS --target "$STATE_DIR" 2>/dev/null || echo "")
  if [[ "$src" == "/" ]]; then
    echo "note: AMR_STATE_DIR ($STATE_DIR) is on the root filesystem; see RUNBOOK section 5 (data volume)"
  elif [[ "$opts" != *data=journal* ]]; then
    echo "note: $src is a separate mount but not data=journal"
  else
    echo "state on $src with data=journal"
  fi
fi

# Units left failed (H-P1-4: StartLimitBurst parks a crash loop in "failed"). Warnings only.
for unit in amr.service amr-failed.service canable@can0.service agv-wifi-reconnect.service \
            cpu-power-limit.service cpu-freq-cap.service; do
  if systemctl is-failed --quiet "$unit" 2>/dev/null; then
    echo "warning: $unit is failed: systemctl status $unit; journalctl -u $unit -b" >&2
  fi
done
# The installed copies are the repo's (WP-H5, WP-P3)?
for unit in amr.service amr-failed.service canable@.service; do
  live="/etc/systemd/system/$unit"
  if [[ ! -f "$live" ]]; then
    echo "note: $unit is not installed (run install.sh)"
  elif ! cmp -s <(tr -d '\r' <"$DEPLOY_DIR/$unit") <(tr -d '\r' <"$live"); then
    echo "note: installed $unit differs from deploy/$unit (run install.sh)"
  fi
done
if [[ -f /usr/local/sbin/amr-failed ]] && ! cmp -s "$DEPLOY_DIR/amr-failed.py" /usr/local/sbin/amr-failed; then
  echo "note: /usr/local/sbin/amr-failed differs from deploy/amr-failed.py (run install.sh)"
fi
# CANable rule: the serial the installed rule matches, against this unit's profile (WP-P3).
can_serial=$(python3 - "$REPO_ROOT" <<'PY'
import json, os, sys
name = os.environ.get("AGV_PROFILE") or "agv-01"
with open(os.path.join(sys.argv[1], "profiles", f"{name}.json")) as fh:
    print(json.load(fh)["can"]["adapter_serial"])
PY
)
live_serial=$(grep -o 'ATTRS{serial}=="[^"]*"' /etc/udev/rules.d/70-canable.rules 2>/dev/null | head -1 | cut -d'"' -f2 || true)
if [[ -z "$can_serial" ]]; then
  echo "warning: profile ${AGV_PROFILE:-agv-01} has no can.adapter_serial; install.sh refuses until it has" \
       "${live_serial:+(the installed rule matches $live_serial)}" >&2
elif [[ -n "$live_serial" && "$live_serial" != "$can_serial" ]]; then
  echo "warning: 70-canable.rules matches serial $live_serial, the profile says $can_serial" >&2
fi
if [[ "$(systemctl is-enabled amr.service 2>/dev/null || true)" == enabled && \
      ! -e /etc/systemd/system/canable@can0.service.wants/amr.service ]]; then
  echo "note: a CAN re-plug does not bring amr back yet (WantedBy=canable@can0): witnessed, sudo systemctl reenable amr.service"
fi

# Hardware watchdog (WP-P5). Notes only: it arms at the reboot after install.sh --watchdog.
if [[ -f /etc/systemd/system.conf.d/60-amr-watchdog.conf ]]; then
  [[ -e /dev/watchdog ]] || echo "note: watchdog drop-in installed but no /dev/watchdog (lsmod | grep -i iTCO; wdctl)"
  rt=$(systemctl show -p RuntimeWatchdogUSec --value 2>/dev/null || echo "")
  case "$rt" in
    0|""|0s|infinity) echo "note: systemd is not petting a hardware watchdog yet (reboot after install.sh --watchdog)";;
    *) echo "hardware watchdog: systemd pets it, timeout $rt";;
  esac
fi

# Platform freeze (WP-P1). Warnings only: a bench PC may be unfrozen on purpose.
if command -v apt-cache >/dev/null; then
  snap_uri=$(sed -n 's/^URIs:[[:space:]]*//p' "$DEPLOY_DIR/platform/ros2-snapshot.sources" | head -1)
  policy=$(apt-cache policy 2>/dev/null || true)
  if ! grep -qF "${snap_uri%/}" <<<"$policy"; then
    echo "warning: ROS does not come from $snap_uri: sudo deploy/platform/freeze.sh --go (RUNBOOK section 5)" >&2
  fi
  live_ros=$(grep -E '^[[:space:]]*-?[0-9]+[[:space:]]+https?://packages\.ros\.org' <<<"$policy" || true)
  if [[ -n "$live_ros" ]] && grep -vqE '^[[:space:]]*-1[[:space:]]' <<<"$live_ros"; then
    echo "warning: the live packages.ros.org is not pinned to -1 (apt-cache policy)" >&2
  fi
  holds=$(apt-mark showhold 2>/dev/null || true)
  for p in linux-generic-hwe-22.04 linux-image-generic-hwe-22.04; do
    grep -qx "$p" <<<"$holds" || echo "warning: $p is not held (apt-mark showhold); freeze.sh --go" >&2
  done
  for t in apt-daily.timer apt-daily-upgrade.timer; do
    if [[ "$(systemctl is-enabled "$t" 2>/dev/null || true)" == enabled ]]; then
      echo "warning: $t is enabled: unattended apt runs under the vehicle" >&2
    fi
  done
fi
snap_time=$(snap refresh --time 2>/dev/null || true)
if command -v snap >/dev/null && ! grep -q '^hold:' <<<"$snap_time"; then
  echo "warning: snap refreshes are not held (snap refresh --time); freeze.sh --go" >&2
fi
echo "kernel $(uname -r)"

echo "deployment validation passed"
