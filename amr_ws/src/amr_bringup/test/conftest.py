"""Simulation launch tests are opt-in (AMR_SIM_TESTS=1).

They are left out of collection here instead of relying only on their module-level
pytest.skip: with plugin autoload the launch_testing plugin imports them while
collecting, and that Skipped escapes its hook and ends the WHOLE session as
"1 skipped" - every unit test next to them silently not run (review R34).
"""

import os

# The reference profile on either PC (manuals/agv-02-plan.md R4): before any agv_core import, as
# vehicle.sh exports AGV_PROFILE=agv-02 on unit 2 and these tests pin agv-01's values.
os.environ["AGV_PROFILE"] = "agv-01"

SIM_TESTS = [
    "test_unified_sim.py",
    "test_sim_tf.py",
    "test_fault_injection_sim.py",
]

collect_ignore = [] if os.environ.get("AMR_SIM_TESTS") == "1" else list(SIM_TESTS)
# The station chain also needs a real broker (station call plan P7). The same escape, so the same rule.
if os.environ.get("AMR_SIM_TESTS") == "1" and os.environ.get("AMR_MQTT_TESTS") == "1":
    SIM_TESTS.append("test_station_call_sim.py")
else:
    collect_ignore.append("test_station_call_sim.py")


def pytest_report_header(config):
    if collect_ignore:
        return f"amr_bringup: sim tests skipped (AMR_SIM_TESTS=1 runs them): {', '.join(SIM_TESTS)}"
    return None
