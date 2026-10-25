"""D23: the mux declares its freshness and pendant defaults from gating.DEFAULT, so the
launch files need not restate them. The literal pins in test_pendant_gating and
test_editor_js stay, so a cap cannot rise unseen."""

import ast
import pathlib

from amr_base import gating

SRC = pathlib.Path(__file__).resolve().parents[1] / "amr_base" / "cmd_mux_kinematics_node.py"
FIELDS = {
    "teleop_timeout_s": "teleop_window_s", "cmd_timeout_s": "cmd_timeout_s",
    "permit_timeout_s": "permit_timeout_s", "panel_timeout_s": "panel_timeout_s",
    "lease_timeout_s": "lease_timeout_s", "drives_timeout_s": "drives_timeout_s",
    "require_supervisor": "require_supervisor", "teleop_enabled": "teleop_enabled",
    "pendant_v_m_s": "pendant_v", "pendant_w_rad_s": "pendant_w", "pendant_turn_ratio": "pendant_turn_ratio",
}


def test_declared_defaults_are_gating_default():
    declared = {}
    for node in ast.walk(ast.parse(SRC.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "declare_parameter":
            name, default = node.args[0].value, node.args[1]
            if name in FIELDS:
                declared[name] = default
    assert set(declared) == set(FIELDS)
    for name, field in FIELDS.items():
        d = declared[name]
        assert isinstance(d, ast.Attribute) and d.attr == field and d.value.id == "d", name
    assert gating.DEFAULT.lease_timeout_s == 0.3 and gating.DEFAULT.cmd_timeout_s == 0.2


def test_base_launch_restates_none_of_them():
    launch = SRC.parents[2] / "amr_bringup" / "launch" / "base.launch.py"
    text = launch.read_text(encoding="utf-8")
    for name in ("pendant_v_m_s", "pendant_w_rad_s", "pendant_turn_ratio", "manual_a_max", "manual_jerk"):
        assert f'"{name}"' not in text, name
