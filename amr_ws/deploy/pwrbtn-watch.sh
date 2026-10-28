#!/bin/bash
# Samples ACPI interrupt counters to identify the source of spurious
# power-button shutdowns. Readable without root. Started by the user's crontab
# (@reboot .../logs/pwrbtn-watch.sh); this file is the versioned copy.
#
# One awk per sample and no other fork (the timestamp is bash's printf): the old
# date + 7 awk forks every 2 s cost ~1.5 % of a core (cpu-load-plan Tier 1 #3).
# The log is rotated by logrotate-amr (installed by install.sh).
OUT=/home/gvipc-evo-01/agv_can/logs/pwrbtn-watch.log
ACPI=/sys/firmware/acpi/interrupts

snap() {
  local ts files=(/proc/uptime) f
  printf -v ts '%(%Y-%m-%dT%H:%M:%S%z)T' -1
  ts="${ts:0:-2}:${ts: -2}"   # +0700 -> +07:00, as date -Is wrote it
  # Only readable files: mawk stops at the first file it cannot open.
  for f in ff_pwr_btn sci sci_not gpe_all error; do
    [[ -r "$ACPI/$f" ]] && files+=("$ACPI/$f")
  done
  files+=(/proc/interrupts)
  awk -v ts="$ts" -v tag="$1" '
    FILENAME == "/proc/uptime" { up = sprintf("%.0f", $1); next }
    FILENAME == "/proc/interrupts" {
      if (!irq_done && / 9:/) {
        s = 0; for (i = 2; i <= NF; i++) if ($i ~ /^[0-9]+$/) s += $i
        irq = s; irq_done = 1
      }
      next
    }
    FNR == 1 { n = split(FILENAME, p, "/"); v[p[n]] = $1 }
    END {
      printf "%s up=%s ff_pwr_btn=%s sci=%s sci_not=%s gpe_all=%s err=%s acpi_irq9=%s %s\n",
        ts, up, v["ff_pwr_btn"], v["sci"], v["sci_not"], v["gpe_all"], v["error"], irq, tag
    }' "${files[@]}"
}

trap 'snap "<<< SIGTERM - system going down >>>" >> "$OUT"; sync; exit 0' TERM INT

echo "=== watcher started $(date -Is) boot=$(cat /proc/sys/kernel/random/boot_id) ===" >> "$OUT"
while :; do
  snap >> "$OUT"
  sleep 2
done
