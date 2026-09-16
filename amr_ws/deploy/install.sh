#!/bin/bash
# Install (or refresh) the AMR units. Enables nothing: which mode boots is a
# decision made with `systemctl enable`, see RUNBOOK.md. Run with sudo.
set -euo pipefail
cd "$(dirname "$0")"
for u in amr_nav.service amr_mapping.service; do
  install -m 644 "$u" /etc/systemd/system/"$u"
done
systemctl daemon-reload
echo "installed amr_nav.service and amr_mapping.service (not enabled)."
echo "boot into runtime:   sudo systemctl disable agv_controller && sudo systemctl enable amr_nav"
echo "survey now:          sudo systemctl start amr_mapping     (stops amr_nav / agv_controller)"
echo "back to runtime:     sudo systemctl start amr_nav"
echo "legacy jog pad:      sudo systemctl start agv_controller  (stops both AMR units)"
