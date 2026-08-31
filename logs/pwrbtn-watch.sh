#!/bin/bash
# Samples ACPI interrupt counters to identify the source of spurious
# power-button shutdowns. Readable without root.
OUT=/home/gvipc-evo-01/agv_can/logs/pwrbtn-watch.log

snap() {
  printf "%s up=%s ff_pwr_btn=%s sci=%s sci_not=%s gpe_all=%s err=%s acpi_irq9=%s %s\n" \
    "$(date -Is)" \
    "$(awk '{printf "%.0f", $1}' /proc/uptime)" \
    "$(awk '{print $1}' /sys/firmware/acpi/interrupts/ff_pwr_btn 2>/dev/null)" \
    "$(awk '{print $1}' /sys/firmware/acpi/interrupts/sci 2>/dev/null)" \
    "$(awk '{print $1}' /sys/firmware/acpi/interrupts/sci_not 2>/dev/null)" \
    "$(awk '{print $1}' /sys/firmware/acpi/interrupts/gpe_all 2>/dev/null)" \
    "$(awk '{print $1}' /sys/firmware/acpi/interrupts/error 2>/dev/null)" \
    "$(awk '/ 9:/{s=0; for(i=2;i<=NF;i++) if($i ~ /^[0-9]+$/) s+=$i; print s; exit}' /proc/interrupts)" \
    "$1"
}

trap 'snap "<<< SIGTERM - system going down >>>" >> "$OUT"; sync; exit 0' TERM INT

echo "=== watcher started $(date -Is) boot=$(cat /proc/sys/kernel/random/boot_id) ===" >> "$OUT"
while :; do
  snap >> "$OUT"
  sleep 2
done
