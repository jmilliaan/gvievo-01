"""Import paths for the amr_line tests, once (lean plan D27): the repo root (agv_core), the
packages they test against from source (amr_line, amr_sim, amr_base) and this directory
(harness, site_fixture, shared test modules). Same insert order the files used to repeat."""

import os
import sys

# The reference profile on either PC (manuals/agv-02-plan.md R4): before any agv_core import, as
# vehicle.sh exports AGV_PROFILE=agv-02 on unit 2 and these tests pin agv-01's values.
os.environ["AGV_PROFILE"] = "agv-01"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
SRC = os.path.join(ROOT, "amr_ws", "src")
for _p in (ROOT, os.path.join(SRC, "amr_line"), os.path.join(SRC, "amr_sim"),
           os.path.join(SRC, "amr_base"), HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
