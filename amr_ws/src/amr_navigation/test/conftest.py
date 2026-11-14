"""amr_navigation tests: the vehicle profile they run against."""

import os

# The reference profile on either PC (manuals/agv-02-plan.md R4): before any agv_core import, as
# vehicle.sh exports AGV_PROFILE=agv-02 on unit 2 and these tests pin agv-01's values.
os.environ["AGV_PROFILE"] = "agv-01"
