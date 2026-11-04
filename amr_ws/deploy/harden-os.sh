#!/bin/bash
# OS hardening against sudden power loss and hangs, on top of what install.sh sets.
#
#   ./deploy/harden-os.sh                show the current state, change nothing (no sudo)
#   sudo ./deploy/harden-os.sh --apply   make the changes
#   sudo ./deploy/harden-os.sh --revert  undo them
#
# It sets:
#   updates   no automatic apt upgrades or snap refreshes: a cut during an upgrade can leave
#             packages half installed, and an upgrade can change Nav2 unseen. Update by hand,
#             parked: sudo apt upgrade; sudo snap refresh <name>
#   boot      fsck.repair=yes: answer yes to fsck instead of stopping at a prompt.
#             GRUB_RECORDFAIL_TIMEOUT=0: no 30 s menu after a crash. To reach the menu,
#             hold Esc during boot.
#   hangs     kernel.panic=10: reboot 10 s after a kernel panic. RuntimeWatchdogSec=30s: the
#             hardware watchdog resets the PC if systemd freezes, only if the board has one.
#   writes    git core.fsyncObjectFiles for this repo; journal flushed every 30 s.
#
# Like install.sh it does not start, stop or restart the AMR service. Apart from the update
# timers, which stop at once, everything takes effect at the next reboot; it never reboots.
# --apply and --revert are safe to run twice.
set -euo pipefail

DEPLOY_DIR=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$DEPLOY_DIR" rev-parse --show-toplevel)
OWNER=$(stat -c %U "$REPO")
BACKUP_DIR="/var/backups/amr-harden/$(date +%Y%m%d-%H%M%S)"

APT_CONF=/etc/apt/apt.conf.d/99amr-no-auto-updates
GRUB_CONF=/etc/default/grub.d/90-amr-harden.cfg
SYSCTL_CONF=/etc/sysctl.d/61-amr-harden.conf
JOURNAL_CONF=/etc/systemd/journald.conf.d/90-amr-sync.conf
WATCHDOG_CONF=/etc/systemd/system.conf.d/90-amr-watchdog.conf
INITRAMFS_MODULES=/etc/initramfs-tools/modules
WATCHDOG_MODULE=iTCO_wdt
UPDATE_UNITS=(unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer)

need_root() {
  if [[ ${EUID} -ne 0 ]]; then
    echo "run with sudo: sudo $0 $1" >&2
    exit 2
  fi
}

write_file() {  # <destination>, content on stdin; never leaves a half-written file behind
  install -d -m 0755 "$(dirname "$1")"
  cat >"$1.tmp"
  chmod 0644 "$1.tmp"
  sync "$1.tmp"
  mv "$1.tmp" "$1"
  echo "wrote $1"
}

show() {  # <label> <value>
  printf '  %-30s %s\n' "$1" "$2"
}

check() {
  echo "Updates"
  for unit in "${UPDATE_UNITS[@]}"; do
    show "$unit" "$(systemctl is-enabled "$unit" 2>/dev/null || true)"
  done
  show "$(basename "$APT_CONF")" "$([[ -f $APT_CONF ]] && echo present || echo absent)"
  show "snap refresh" "$(snap refresh --time 2>/dev/null | grep -E '^hold:' || echo 'not held')"
  echo "Boot"
  show "$(basename "$GRUB_CONF")" "$([[ -f $GRUB_CONF ]] && echo present || echo absent)"
  show "fsck.repair in this boot" "$(grep -qw 'fsck.repair=yes' /proc/cmdline && echo yes || echo no)"
  echo "Hangs"
  show "kernel.panic now" "$(sysctl -n kernel.panic)"
  show "$(basename "$SYSCTL_CONF")" "$([[ -f $SYSCTL_CONF ]] && echo present || echo absent)"
  show "/dev/watchdog" "$([[ -e /dev/watchdog ]] && echo present || echo absent)"
  show "$(basename "$WATCHDOG_CONF")" "$([[ -f $WATCHDOG_CONF ]] && echo present || echo absent)"
  show "systemd watchdog now" "$(systemctl show -p RuntimeWatchdogUSec --value)"
  echo "Writes"
  show "git core.fsyncObjectFiles" "$(git -C "$REPO" config --get core.fsyncObjectFiles || echo unset)"
  show "$(basename "$JOURNAL_CONF")" "$([[ -f $JOURNAL_CONF ]] && echo present || echo absent)"
}

apply_updates() {
  if pgrep -x 'dpkg|apt|apt-get|unattended-upgr' >/dev/null; then
    echo "a package operation is running: wait for it to finish, then run this again" >&2
    exit 1
  fi
  write_file "$APT_CONF" <<'EOF'
// Automatic updates off (deploy/harden-os.sh). Update by hand, parked.
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
EOF
  systemctl disable --now "${UPDATE_UNITS[@]}"
  snap refresh --hold
}

apply_boot() {
  write_file "$GRUB_CONF" <<'EOF'
# deploy/harden-os.sh
GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT fsck.repair=yes"
GRUB_RECORDFAIL_TIMEOUT=0
EOF
  cp -a /boot/grub/grub.cfg "$BACKUP_DIR/grub.cfg"
  update-grub
}

apply_hangs() {
  write_file "$SYSCTL_CONF" <<'EOF'
# deploy/harden-os.sh
kernel.panic = 10
EOF
  # Ubuntu blacklists the watchdog drivers, so they do not load by themselves. A driver with
  # nothing holding it open does nothing, so loading it to test is harmless.
  [[ -e /dev/watchdog ]] || modprobe "$WATCHDOG_MODULE" 2>/dev/null || true
  if [[ ! -e /dev/watchdog ]]; then
    echo "no hardware watchdog found: skipped RuntimeWatchdogSec (check the BIOS, then run again)"
    return 0
  fi
  # in the initramfs, so that /dev/watchdog exists before systemd starts
  if ! grep -qx "$WATCHDOG_MODULE" "$INITRAMFS_MODULES"; then
    cp -a "$INITRAMFS_MODULES" "$BACKUP_DIR/modules"
    echo "$WATCHDOG_MODULE" >>"$INITRAMFS_MODULES"
    update-initramfs -u
  fi
  write_file "$WATCHDOG_CONF" <<'EOF'
# deploy/harden-os.sh
[Manager]
RuntimeWatchdogSec=30s
EOF
}

apply_writes() {
  sudo -u "$OWNER" git -C "$REPO" config core.fsyncObjectFiles true
  write_file "$JOURNAL_CONF" <<'EOF'
# deploy/harden-os.sh
[Journal]
SyncIntervalSec=30s
EOF
}

apply() {
  need_root --apply
  install -d -m 0755 "$BACKUP_DIR"
  apply_updates
  apply_boot
  apply_hangs
  apply_writes
  sync
  echo
  echo "Done. Reboot, parked, for the rest to take effect."
  echo "Then check with: $0"
  echo "Backup: $BACKUP_DIR"
}

revert() {
  need_root --revert
  install -d -m 0755 "$BACKUP_DIR"
  rm -f "$APT_CONF" "$SYSCTL_CONF" "$JOURNAL_CONF" "$WATCHDOG_CONF"
  if [[ -f $GRUB_CONF ]]; then
    rm -f "$GRUB_CONF"
    cp -a /boot/grub/grub.cfg "$BACKUP_DIR/grub.cfg"
    update-grub
  fi
  if grep -qx "$WATCHDOG_MODULE" "$INITRAMFS_MODULES"; then
    cp -a "$INITRAMFS_MODULES" "$BACKUP_DIR/modules"
    sed -i "/^$WATCHDOG_MODULE\$/d" "$INITRAMFS_MODULES"
    update-initramfs -u
  fi
  sudo -u "$OWNER" git -C "$REPO" config --unset core.fsyncObjectFiles || true
  systemctl enable --now "${UPDATE_UNITS[@]}"
  snap refresh --unhold
  sync
  echo
  echo "Reverted. Reboot for it to take full effect. Backup: $BACKUP_DIR"
}

case "${1:---check}" in
  --check) check ;;
  --apply) apply ;;
  --revert) revert ;;
  *)
    echo "usage: $0 [--check | --apply | --revert]" >&2
    exit 2
    ;;
esac
