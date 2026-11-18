#!/bin/bash
# Freeze the platform: ROS from a dated snapshot, no new kernel, no snap or unattended
# refresh under a running vehicle (unified plan WP-P1, decision 7; external-features-survey
# section 2.14). Run it on EVERY unit: unit 2 was installed from the live packages.ros.org,
# so its package set may be newer than the snapshot (apt keeps what is installed; it never
# downgrades by itself).
#
#   ./deploy/platform/freeze.sh          show the current state (no sudo needed)
#   sudo ./deploy/platform/freeze.sh --go
#
# --go, in this order, and it stops at the first step that fails:
#   1. imports the snapshot repository key (keyserver, checked against the fingerprint below)
#   2. installs ros2-snapshot.sources, apt-preferences-amr (live packages.ros.org at -1),
#      needrestart-amr.conf and 52amr-unattended
#   3. purges ros2-apt-source (it rewrites ros2.sources to the live repo on every upgrade)
#      and moves any other live ROS source file to the backup directory
#   4. apt-get update, then shows where rclpy would come from
#   5. kernel: keeps the newest GA 5.15 image as the GRUB fallback (apt-mark manual),
#      purges the GA metas, holds the HWE metas, linux-firmware and intel-microcode
#   6. snap refresh --hold (every snap, for ever; the kiosk chromium included)
#   7. disables and masks the apt and update-notifier timers
#   8. writes the record (snapshot, kernel, GRUB fallback, holds) to
#      /var/backups/amr-platform/<host>.txt: copy the fallback into alpha-setup.md's table
#
# It touches no AMR service. Moving the snapshot date is a separate, witnessed window (WP-P2).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
KEYRING=/usr/share/keyrings/ros-snapshots-archive-keyring.gpg
# The ROS snapshot repository's signing key (wiki.ros.org/SnapshotRepository; the survey
# read 4B63CF8F...CBF125EA off the 2026-09-14 InRelease). Check the full value against the
# wiki before the first --go: a wrong value fails closed (nothing is imported).
SNAPSHOT_KEY_FPR=4B63CF8FDE49746E98FA01DDAD19BAB3CBF125EA
KEYSERVER=hkp://keyserver.ubuntu.com:80
RECORD_DIR=/var/backups/amr-platform
HWE_METAS=(linux-generic-hwe-22.04 linux-image-generic-hwe-22.04 linux-headers-generic-hwe-22.04)
GA_METAS=(linux-generic linux-image-generic linux-headers-generic)
HOLD_ALSO=(linux-firmware intel-microcode)
TIMERS=(apt-daily.timer apt-daily-upgrade.timer update-notifier-download.timer)

snapshot_uri() { sed -n 's/^URIs:[[:space:]]*//p' "$HERE/ros2-snapshot.sources" | head -1; }
installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'; }
# Newest installed GA 5.15 image version, e.g. 5.15.0-187-generic: the GRUB fallback.
fallback_kernel() {
  dpkg-query -W -f='${Package} ${Status}\n' 'linux-image-5.15.*-generic' 2>/dev/null \
    | awk '/install ok installed/{sub(/^linux-image-/,"",$1); print $1}' | sort -V | tail -1
}

status() {
  echo "host            $(hostname)"
  echo "kernel          $(uname -r)"
  echo "GRUB fallback   $(fallback_kernel || true)"
  echo "snapshot source $(snapshot_uri)"
  if [[ -f /etc/apt/sources.list.d/ros2-snapshot.sources ]]; then echo "                installed"; else echo "                NOT installed"; fi
  echo "live ROS pin    $([[ -f /etc/apt/preferences.d/60-amr ]] && echo installed || echo 'NOT installed')"
  echo "ros2-apt-source $(installed ros2-apt-source && echo 'installed (rewrites ros2.sources to live)' || echo absent)"
  echo "--- apt-mark showhold"
  apt-mark showhold 2>/dev/null || true
  echo "--- apt-cache policy ros-humble-rclpy"
  apt-cache policy ros-humble-rclpy 2>/dev/null | sed -n '1,4p' || true
  if command -v snap >/dev/null; then
    echo "--- snap refresh --time"
    snap refresh --time 2>/dev/null || true
  fi
  echo "--- timers"
  for t in "${TIMERS[@]}"; do
    printf '%-34s %s\n' "$t" "$(systemctl is-enabled "$t" 2>/dev/null || true)"
  done
}

import_key() {
  if [[ -s "$KEYRING" ]]; then
    echo "snapshot key already in $KEYRING"
    return 0
  fi
  local tmp; tmp=$(mktemp -d)
  GNUPGHOME="$tmp" gpg --batch --quiet --keyserver "$KEYSERVER" --recv-keys "$SNAPSHOT_KEY_FPR"
  local got
  got=$(GNUPGHOME="$tmp" gpg --batch --with-colons --fingerprint 2>/dev/null | awk -F: '/^fpr:/{print $10; exit}')
  if [[ "$got" != "$SNAPSHOT_KEY_FPR" ]]; then
    echo "refusing: the key fetched has fingerprint '$got', expected $SNAPSHOT_KEY_FPR" >&2
    return 1
  fi
  GNUPGHOME="$tmp" gpg --batch --export "$SNAPSHOT_KEY_FPR" >"$tmp/k.gpg"
  install -m 0644 -o root -g root "$tmp/k.gpg" "$KEYRING"
  rm -rf "$tmp"
  echo "snapshot key $SNAPSHOT_KEY_FPR -> $KEYRING"
}

apply() {
  local backup="$RECORD_DIR/$(date +%Y%m%d-%H%M%S)"
  install -d -m 0755 "$backup"
  import_key

  install -m 0644 -D "$HERE/ros2-snapshot.sources" /etc/apt/sources.list.d/ros2-snapshot.sources
  install -m 0644 -D "$HERE/apt-preferences-amr" /etc/apt/preferences.d/60-amr
  install -m 0644 -D "$HERE/needrestart-amr.conf" /etc/needrestart/conf.d/amr.conf
  install -m 0644 -D "$HERE/52amr-unattended" /etc/apt/apt.conf.d/52amr-unattended
  if command -v perl >/dev/null; then perl -c /etc/needrestart/conf.d/amr.conf; fi

  if installed ros2-apt-source; then
    cp -a /etc/apt/sources.list.d/ros2.sources "$backup/" 2>/dev/null || true
    apt-get purge -y ros2-apt-source
  fi
  # Any other file that still names the live repo (alpha-setup's old ros2.list form).
  for f in /etc/apt/sources.list.d/*; do
    [[ -f "$f" && "$f" != */ros2-snapshot.sources ]] || continue
    if grep -qE '^[^#]*packages\.ros\.org' "$f"; then
      mv "$f" "$backup/"
      echo "moved live ROS source $f to $backup/"
    fi
  done

  apt-get update
  echo "--- rclpy now comes from:"
  apt-cache policy ros-humble-rclpy | sed -n '1,6p'

  local fb; fb=$(fallback_kernel || true)
  if [[ -n "$fb" ]]; then
    local pkgs=()
    for p in "linux-image-$fb" "linux-modules-$fb" "linux-modules-extra-$fb"; do
      installed "$p" && pkgs+=("$p")
    done
    apt-mark manual "${pkgs[@]}"
    local metas=()
    for p in "${GA_METAS[@]}"; do installed "$p" && metas+=("$p"); done
    if (( ${#metas[@]} )); then apt-get purge -y "${metas[@]}"; fi
  else
    echo "warning: no GA 5.15 kernel installed: no GRUB fallback kept, GA metas left alone" >&2
  fi
  local holds=()
  for p in "${HWE_METAS[@]}" "${HOLD_ALSO[@]}"; do installed "$p" && holds+=("$p"); done
  if (( ${#holds[@]} )); then apt-mark hold "${holds[@]}"; fi

  if command -v snap >/dev/null; then
    snap refresh --hold
  fi

  for t in "${TIMERS[@]}"; do
    if systemctl cat "$t" >/dev/null 2>&1; then
      systemctl disable --now "$t" 2>/dev/null || true
      systemctl mask "$t"
    fi
  done

  install -d -m 0755 "$RECORD_DIR"
  status >"$RECORD_DIR/$(hostname).txt" 2>&1
  echo "record: $RECORD_DIR/$(hostname).txt (backups: $backup)"
  echo "GRUB fallback kernel on $(hostname): ${fb:-none}  <- put it in alpha-setup.md's per-unit table"
}

case "${1:-}" in
  "") echo "read-only; sudo $0 --go applies"; status ;;
  --go)
    [[ ${EUID} -eq 0 ]] || { echo "run with sudo: sudo $0 --go" >&2; exit 2; }
    apply ;;
  *) echo "usage: sudo $0 [--go]" >&2; exit 2 ;;
esac
