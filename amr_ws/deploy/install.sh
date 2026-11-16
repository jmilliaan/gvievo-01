#!/bin/bash
# Install or refresh deployment files only. This script deliberately does not
# enable, start, stop or restart any service; cutover is a separate witnessed
# step in RUNBOOK.md after vehicle acceptance.
#
#   sudo ./deploy/install.sh              everything below except the hardware watchdog
#   sudo ./deploy/install.sh --watchdog   also the hardware watchdog (WP-P5): only after
#                                         `wdctl` was checked (RUNBOOK section 5)
set -euo pipefail

DEPLOY_DIR=$(cd "$(dirname "$0")" && pwd)
WORKSPACE=$(cd "$DEPLOY_DIR/.." && pwd)
REPO_ROOT=$(cd "$WORKSPACE/.." && pwd)
BACKUP_DIR="/var/backups/amr-units/$(date +%Y%m%d-%H%M%S)"
# canable@.service is a template: installed as is, never enabled (udev starts canable@can0).
UNITS=(amr.service amr-failed.service canable@.service)

WATCHDOG=no
case "${1:-}" in
  "") ;;
  --watchdog) WATCHDOG=yes ;;
  *) echo "usage: sudo $0 [--watchdog]" >&2; exit 2 ;;
esac

if [[ ${EUID} -ne 0 ]]; then
  echo "run with sudo: sudo $0" >&2
  exit 2
fi

"$DEPLOY_DIR/validate.sh"

# The CANable rule is per unit (WP-P3): its serial comes from this unit's profile. Rendered
# before anything is installed, so a missing serial installs nothing.
state_dir=$(sed -n 's/^AMR_STATE_DIR=//p' "$DEPLOY_DIR/amr.env" | tail -n 1)
profile=$(unset AGV_PROFILE; AMR_STATE_DIR="$state_dir"; source "$WORKSPACE/env/vehicle.sh" >/dev/null
          echo "${AGV_PROFILE:-agv-01}")
serial=$(python3 - "$REPO_ROOT/profiles/$profile.json" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    print(json.load(fh)["can"]["adapter_serial"])
PY
)
if [[ ! "$serial" =~ ^[A-Za-z0-9]{4,32}$ ]]; then
  echo "refusing: profiles/$profile.json can.adapter_serial is '${serial}', not a USB serial." >&2
  echo "  Read this unit's CANable serial (alpha-setup.md section 3):" >&2
  echo "    udevadm info -a /dev/ttyACM0 | grep -m1 'ATTRS{serial}'" >&2
  live_serial=$(grep -o 'ATTRS{serial}=="[^"]*"' /etc/udev/rules.d/70-canable.rules 2>/dev/null \
                | head -1 | cut -d'"' -f2 || true)
  if [[ -n "$live_serial" ]]; then
    echo "  The installed /etc/udev/rules.d/70-canable.rules matches serial $live_serial." >&2
  fi
  echo "  Put it in can.adapter_serial, commit, and run install.sh again. Nothing was installed." >&2
  exit 1
fi
rendered=$(mktemp)
sed "s/@ADAPTER_SERIAL@/$serial/g" "$DEPLOY_DIR/70-canable.rules.in" >"$rendered"
if grep -q '@ADAPTER_SERIAL@' "$rendered"; then
  echo "refusing: 70-canable.rules.in did not render" >&2; rm -f "$rendered"; exit 1
fi

install -d -m 0755 "$BACKUP_DIR"
for unit in "${UNITS[@]}"; do
  if [[ -f "/etc/systemd/system/$unit" ]]; then
    cp -a "/etc/systemd/system/$unit" "$BACKUP_DIR/$unit"
  fi
  install -m 0644 "$DEPLOY_DIR/$unit" "/etc/systemd/system/$unit"
done

# Power-loss hardening (plan W6/W7): a shorter dirty-page window and a bounded
# journal. Both are drop-ins that only take effect where they are installed, and
# neither changes service state. The old copies are backed up like the units.
install_dropin() {  # <source> <destination>
  local src="$DEPLOY_DIR/$1" dst="$2"
  [[ -f "$src" ]] || return 0
  if [[ -f "$dst" ]]; then
    # Units keep their name (RUNBOOK section 7 copies *.service back); other files get the
    # full path in the name, because several drop-ins are all called amr.conf.
    local name flat="${dst#/}"
    if [[ "$(dirname "$dst")" == /etc/systemd/system ]]; then name=$(basename "$dst"); else name="${flat//\//_}"; fi
    cp -a "$dst" "$BACKUP_DIR/$name"
  fi
  install -m 0644 -D "$src" "$dst"
  echo "installed $dst"
}
install_dropin sysctl-amr.conf /etc/sysctl.d/60-amr.conf
install_dropin journald-amr.conf /etc/systemd/journald.conf.d/amr.conf
install_dropin logrotate-amr /etc/logrotate.d/amr
install_dropin chrony-amr.conf /etc/chrony/conf.d/amr.conf
# ROS logs and run recordings age out (WP-P4); systemd-tmpfiles-clean.timer applies it.
install_dropin tmpfiles-amr.conf /etc/tmpfiles.d/amr.conf
# Wi-Fi rejoin (alpha-setup 2.3). It runs as root, so it runs from a root-owned copy.
install -m 0755 "$DEPLOY_DIR/agv-wifi-reconnect.sh" /usr/local/sbin/agv-wifi-reconnect
install_dropin agv-wifi-reconnect.service /etc/systemd/system/agv-wifi-reconnect.service
# The "call the engineer" page writer (WP-H5): root runs a root-owned copy, as above.
install -m 0755 -o root -g root "$DEPLOY_DIR/amr-failed.py" /usr/local/sbin/amr-failed
# Thermal caps for the fanless N97 (2026-10-02: 100 C, 86 throttles in 2 h at stock
# 3.6 GHz / PL2 25 W). Installed here, enabled by hand like every other unit.
install_dropin cpu-freq-cap.service /etc/systemd/system/cpu-freq-cap.service
install_dropin cpu-power-limit.service /etc/systemd/system/cpu-power-limit.service

# CANable (WP-P3): the rule rendered above. Reloading the rules changes nothing that runs;
# they apply at the next plug-in or boot.
if [[ -f /etc/udev/rules.d/70-canable.rules ]]; then
  cp -a /etc/udev/rules.d/70-canable.rules "$BACKUP_DIR/70-canable.rules"
fi
install -m 0644 "$rendered" /etc/udev/rules.d/70-canable.rules
rm -f "$rendered"
echo "installed /etc/udev/rules.d/70-canable.rules (serial $serial, profile $profile)"
udevadm control --reload-rules || echo "warning: udevadm reload failed; the rule applies at reboot" >&2

# Platform freeze (WP-P1). needrestart and unattended-upgrades policies always; the ROS
# snapshot source and the live-repo pin only once freeze.sh --go has imported the snapshot
# key (a source without its key only breaks apt update).
install_dropin platform/needrestart-amr.conf /etc/needrestart/conf.d/amr.conf
install_dropin platform/52amr-unattended /etc/apt/apt.conf.d/52amr-unattended
if [[ -s /usr/share/keyrings/ros-snapshots-archive-keyring.gpg ]]; then
  install_dropin platform/ros2-snapshot.sources /etc/apt/sources.list.d/ros2-snapshot.sources
  install_dropin platform/apt-preferences-amr /etc/apt/preferences.d/60-amr
else
  echo "note: platform not frozen yet: sudo $DEPLOY_DIR/platform/freeze.sh --go (RUNBOOK section 5)"
fi

# Hardware watchdog (WP-P5), only when asked for: it arms at the next boot.
if [[ "$WATCHDOG" == yes ]]; then
  install_dropin iTCO_wdt.conf /etc/modules-load.d/iTCO_wdt.conf
  install_dropin systemd-watchdog-amr.conf /etc/systemd/system.conf.d/60-amr-watchdog.conf
fi
sysctl --quiet --system || echo "warning: sysctl --system failed; reboot applies it anyway" >&2

systemctl list-unit-files 'amr*.service' --no-legend \
  >"$BACKUP_DIR/enabled-state.txt" || true
systemctl daemon-reload

echo "Installed unit files without changing enabled or running services."
echo "The journal cap needs: systemctl restart systemd-journald"
echo "The chrony drop-in needs: systemctl restart chrony (off-shift)"
echo "Wi-Fi rejoin, once per unit: systemctl enable --now agv-wifi-reconnect (safe while running)"
echo "CPU caps, once per unit: systemctl enable --now cpu-power-limit cpu-freq-cap (safe while running)"
echo "CAN re-plug (WantedBy=canable@can0), once per unit, witnessed: systemctl reenable amr.service"
if [[ "$WATCHDOG" == yes ]]; then
  echo "Hardware watchdog: arms at the next reboot; afterwards wdctl shows it (RUNBOOK section 5)"
fi
echo "Backup: $BACKUP_DIR"
echo "Follow the witnessed cutover or rollback procedure in $DEPLOY_DIR/../RUNBOOK.md."
