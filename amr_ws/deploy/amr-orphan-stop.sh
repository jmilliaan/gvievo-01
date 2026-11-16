#!/bin/bash
# ExecStop of amr.service (unified plan WP-H5). systemd runs ExecStop on every stop,
# also when the main process already died on its own.
#
#   supervisor alive ($MAINPID)  -> do nothing: systemd then sends SIGINT to it and the
#                                   supervisor's own ordered teardown runs (unchanged)
#   supervisor gone              -> SIGINT its orphaned child groups, base first, and
#                                   wait at most 12 s (amr-orphan-stop.py), so drive_node
#                                   disarms before the final SIGKILL instead of the drives
#                                   latching 8130h
#
# The unit prefixes this with "-": nothing here can fail the stop.
if [ -n "${MAINPID:-}" ] && kill -0 "$MAINPID" 2>/dev/null; then
  exit 0
fi
exec /usr/bin/python3 -I "$(dirname "$0")/amr-orphan-stop.py"
