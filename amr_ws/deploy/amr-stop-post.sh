#!/bin/bash
# ExecStopPost of amr.service (unified plan WP-H5, S-uptime-boot-id-and-service-result).
# Runs after EVERY stop, clean or not, as the service user, and keeps systemd's verdict
# ($SERVICE_RESULT, $EXIT_CODE, $EXIT_STATUS) in $AMR_STATE_DIR/last_stop.json. The next
# start's crash sentence names it ("the supervisor stopped answering the watchdog").
# A power cut runs nothing, which is exactly what tells the two apart.
#
# No ROS environment: uptime.py needs only agv_core.fsutil. The unit prefixes this
# with "-", so a failure here never changes the unit's result.
AMR_WORKSPACE="${AMR_WS:-$HOME/agv_can/amr_ws}"
REPO_ROOT=$(cd "$AMR_WORKSPACE/.." && pwd)
export PYTHONPATH="$AMR_WORKSPACE/src/amr_bringup:$REPO_ROOT"
export AMR_STATE_DIR="${AMR_STATE_DIR:-$HOME/.amr}"
exec /usr/bin/python3 -m amr_bringup.uptime stop-post
