#!/bin/bash
# P8: cheap deployment validation. No service state or hardware is changed.
set -euo pipefail

DEPLOY_DIR=$(cd "$(dirname "$0")" && pwd)
WORKSPACE=$(cd "$DEPLOY_DIR/.." && pwd)
UNITS=(amr.service)

for path in \
  "$DEPLOY_DIR/amr-supervisor.sh" \
  "$DEPLOY_DIR/install.sh" \
  "$WORKSPACE/install/setup.bash" \
  "$WORKSPACE/env/vehicle.sh"; do
  [[ -f "$path" ]] || { echo "missing required path: $path" >&2; exit 1; }
done

bash -n "$DEPLOY_DIR/amr-supervisor.sh" "$DEPLOY_DIR/install.sh" "$DEPLOY_DIR/trim-services.sh"
for unit in "${UNITS[@]}"; do
  systemd-analyze verify "$DEPLOY_DIR/$unit"
done

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

echo "deployment validation passed"
