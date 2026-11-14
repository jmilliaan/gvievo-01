"""Import paths for the amr_station tests: the repo root (agv_core), amr_station and what it is tested
against from source (amr_base, amr_line, amr_sim, and amr_line's test helpers)."""

import os
import sys

# The reference profile on either PC (manuals/agv-02-plan.md R4): before any agv_core import, as
# vehicle.sh exports AGV_PROFILE=agv-02 on unit 2 and these tests pin agv-01's values.
os.environ["AGV_PROFILE"] = "agv-01"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
SRC = os.path.join(ROOT, "amr_ws", "src")
for _p in (
    ROOT,
    os.path.join(SRC, "amr_station"),
    os.path.join(SRC, "amr_line"),
    os.path.join(SRC, "amr_sim"),
    os.path.join(SRC, "amr_base"),
    os.path.join(SRC, "amr_line", "test"),
    HERE,
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Left out of collection, not only skipped: with plugin autoload the launch_testing plugin imports test
# modules while collecting, and a module-level Skipped then ends the WHOLE session as "1 skipped"
# (amr_bringup/test/conftest.py, review R34).
collect_ignore = []
if os.environ.get("AMR_MQTT_TESTS") != "1":
    collect_ignore.append("test_mosquitto_loop.py")
if not os.environ.get("VDA5050_SCHEMAS"):
    collect_ignore.append("test_vda_schema.py")
