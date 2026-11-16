"""WP-C11 (cpu-load C#19, 2026-11-16): parameter services only where someone tunes live.

No RUNBOOK step, script or node calls `ros2 param set` / SetParameters on a vehicle node, so
every production node is built with start_parameter_services=False (six fewer services and
their executor wake-ups per node). Launch-time parameters still apply: they come in with
--ros-args at init, not through the services. A node that SHOULD keep them goes into KEEP with
its reason - adding one is a deliberate change, not a default.
"""

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[2]

# Node files that keep their parameter services, and why.
KEEP = {
    "commissioning_node.py": "engineering tool: live tuning on the bench is plausible",
    "route_executor_node.py": "WP-C14 deferred with NAVIGATION (no UI entry since 2026-10-28)",
    "imu_bias_node.py": "sim only since WP-C5",
    "diff_drive_odom_node.py": "sim only since WP-C10",
}
# Sim stand-ins are driven with `ros2 param set` (fake_panel_node's docstring).
SIM_PACKAGE = "amr_sim"

_INIT = re.compile(r'super\(\)\.__init__\(\s*"[^"]+"(?P<rest>[^)]*)\)')


def _node_files():
    for path in sorted(SRC.glob("*/*/*_node.py")):
        if path.parts[-3] == SIM_PACKAGE or "/test/" in path.as_posix():
            continue
        yield path


def test_every_production_node_turns_its_parameter_services_off():
    missing = []
    for path in _node_files():
        if path.name in KEEP:
            continue
        inits = list(_INIT.finditer(path.read_text(encoding="utf-8")))
        if not inits:
            continue  # no Node subclass constructed by name here
        if not all("start_parameter_services=False" in m.group("rest") for m in inits):
            missing.append(path.relative_to(SRC).as_posix())
    assert not missing, f"parameter services still on (add start_parameter_services=False or KEEP): {missing}"


def test_the_keep_list_names_real_files():
    names = {p.name for p in SRC.glob("*/*/*_node.py")}
    assert set(KEEP) <= names, set(KEEP) - names
