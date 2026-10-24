#!/bin/bash
# Turn off OS services a vehicle PC has no use for: printing (cups snap), the
# cellular modem manager, SAN multipath, and unattended package upgrades (they can
# replace ROS or system packages under a running vehicle).
#
#   ./deploy/trim-services.sh                 show the current state (no sudo needed)
#   sudo ./deploy/trim-services.sh --go       apply
#   sudo ./deploy/trim-services.sh --revert   restore the state before the first --go
#
# Everything is disable/mask, nothing is uninstalled. amr.service, NetworkManager,
# snapd (the kiosk Chromium is a snap) and the display stack are not touched.
set -euo pipefail

# The pre-trim state, written once by the first --go and never overwritten, so a
# repeated --go cannot replace it with an already-trimmed state.
BACKUP=/var/backups/amr-trim/original
APT_PERIODIC=/etc/apt/apt.conf.d/20auto-upgrades
# Units masked so neither D-Bus activation (ModemManager via NetworkManager) nor a
# socket (multipathd) brings them back.
MASK_UNITS=(ModemManager.service multipathd.service multipathd.socket unattended-upgrades.service)
# Timers only disabled: masking a timer breaks a later `apt` reconfigure.
TIMERS=(apt-daily.timer apt-daily-upgrade.timer)
SNAP=cups

mode=${1:-}
case "$mode" in
  ""|--go|--revert) ;;
  *) echo "usage: sudo $0 [--go|--revert]" >&2; exit 2 ;;
esac
if [[ -n "$mode" && ${EUID} -ne 0 ]]; then
  echo "run with sudo: sudo $0 $mode" >&2
  exit 2
fi

status() {
  printf '%-30s %-10s %s\n' UNIT ENABLED ACTIVE
  for u in "${MASK_UNITS[@]}" "${TIMERS[@]}"; do
    printf '%-30s %-10s %s\n' "$u" "$(systemctl is-enabled "$u" 2>/dev/null || true)" \
      "$(systemctl is-active "$u" 2>/dev/null || true)"
  done
  if snap list "$SNAP" >/dev/null 2>&1; then
    snap services "$SNAP" | sed 1d | awk '{printf "%-30s %-10s %s\n", "snap " $1, $2, $3}'
  fi
  if [[ -f "$APT_PERIODIC" ]]; then
    echo "--- $APT_PERIODIC"
    grep -v '^\s*//' "$APT_PERIODIC"
  fi
}

# Refuse when a block device really is multipathed: disabling multipathd would
# then drop a path to a disk in use. A single local NVMe/SATA has none.
multipath_in_use() {
  dmsetup ls --target multipath 2>/dev/null | grep -qv '^No devices found'
}

apply() {
  if multipath_in_use; then
    echo "refusing: a multipath device is active (dmsetup ls --target multipath)" >&2
    exit 1
  fi
  if [[ ! -d "$BACKUP" ]]; then
    install -d -m 0755 "$BACKUP"
    for u in "${MASK_UNITS[@]}" "${TIMERS[@]}"; do
      echo "$u $(systemctl is-enabled "$u" 2>/dev/null || echo unknown)"
    done >"$BACKUP/units.state"
    if snap list "$SNAP" >/dev/null 2>&1; then
      snap services "$SNAP" | sed 1d | awk '{print $1, $2}' >"$BACKUP/snap.state"
    fi
    if [[ -f "$APT_PERIODIC" ]]; then cp -a "$APT_PERIODIC" "$BACKUP/"; fi
  fi
  if snap list "$SNAP" >/dev/null 2>&1; then
    snap stop --disable "$SNAP"
  fi

  systemctl disable --now "${MASK_UNITS[@]}" "${TIMERS[@]}" 2>/dev/null || true
  systemctl mask "${MASK_UNITS[@]}"
  cat >"$APT_PERIODIC" <<'EOF'
// amr trim-services.sh: no unattended package lists or upgrades on the vehicle.
// Update deliberately with `sudo apt update && sudo apt upgrade` at a service window.
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
EOF
  systemctl daemon-reload
  echo "original state kept in $BACKUP"
}

revert() {
  [[ -f "$BACKUP/units.state" ]] || { echo "no backup in $BACKUP; nothing to revert" >&2; exit 1; }
  echo "restoring from $BACKUP"
  systemctl unmask "${MASK_UNITS[@]}"
  while read -r unit state; do
    case "$state" in
      enabled) systemctl enable --now "$unit" ;;
      masked) systemctl mask "$unit" ;;
      *) ;;  # disabled/static/unknown before: leave disabled
    esac
  done <"$BACKUP/units.state"
  if [[ -f "$BACKUP/snap.state" ]]; then
    while read -r svc startup; do
      if [[ "$startup" == enabled ]]; then snap start --enable "$svc"; fi
    done <"$BACKUP/snap.state"
  fi
  if [[ -f "$BACKUP/$(basename "$APT_PERIODIC")" ]]; then
    cp -a "$BACKUP/$(basename "$APT_PERIODIC")" "$APT_PERIODIC"
  fi
  systemctl daemon-reload
}

case "$mode" in
  "") echo "read-only; sudo $0 --go applies"; status ;;
  --go) apply; status ;;
  --revert) revert; status ;;
esac
