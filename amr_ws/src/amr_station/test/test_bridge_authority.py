"""The bridge's authority limit (plan 12.10), read from the source: it may publish only MQTT,
/amr/events and its DeviceHealth row on /amr/device_health (through health_pub.Outbox, WP-H1;
reporting only), and call only /amr/line/order."""

import ast
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "amr_station"
NODE = (PKG / "station_bridge_node.py").read_text()
FORBIDDEN = (
    "/amr/line_cmd",
    "/amr/manual_command",
    "/amr/line/clear",
    "/amr/line/trip",
    "/amr/line/at_home",
    '/amr/panel_state"',
    "/amr/control_lease",
    "/amr/line/mission",
    "request_mode",
    "/cmd_vel",
)
SUBSCRIBED = {
    "/amr/line/order_state",
    "/amr/line_state",
    "/amr/mode_state",
    "/amr/panel_state_ui",
    "/amr/mux_state",
}


def _calls(tree, attr):
    return [
        c
        for c in ast.walk(tree)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == attr
    ]


def test_the_node_uses_only_its_allowed_names():
    tree = ast.parse(NODE)
    assert {c.args[1].value for c in _calls(tree, "create_publisher")} == {"/amr/events"}
    # the one other topic: DeviceHealth `station_link`, published by the shared Outbox (2026-11-16)
    outboxes = [c for c in _calls(tree, "Outbox") if isinstance(c.func.value, ast.Name)
                and c.func.value.id == "health_pub"]
    assert len(outboxes) == 1
    from amr_base import health_pub

    assert health_pub.TOPIC == "/amr/device_health"
    assert {c.args[1].value for c in _calls(tree, "create_client")} == {"/amr/line/order"}
    assert {c.args[1].value for c in _calls(tree, "create_subscription")} == SUBSCRIBED
    assert _calls(tree, "create_service") == []
    for name in FORBIDDEN:
        assert name not in NODE, name
    topics = set(re.findall(r'"(/[a-z_/]+)"', NODE))
    assert topics == SUBSCRIBED | {"/amr/events", "/amr/line/order"}


def test_the_only_service_verbs_are_depart_cancel_and_zone():
    core = (PKG / "bridge_core.py").read_text()
    assert set(re.findall(r'\("(\w+)", (?:r\.order_id|order_id)', core)) == {"depart", "cancel"}
    # contract v1.6 section 13: the station's zone answers and the link heartbeat. "zone" moves nothing:
    # the job only marks a request GRANTED or the link alive; entering still needs the AGV's own gate.
    assert set(re.findall(r'\("(\w+)", rid, gt\)', core)) == {"zone"}
    node = NODE
    assert set(re.findall(r'_ask\(\("(\w+)"', node)) == {"zone"}
    assert re.findall(r'_ask\(\("zone", "(\w+)", "(\w+)"\)', node) == [("link", "up")]


def test_no_literal_agv1_in_code():
    for path in PKG.glob("*.py"):
        assert "agv1" not in path.read_text(), path.name


def test_paho_is_imported_lazily():
    for path in PKG.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.Import | ast.ImportFrom):
                mod = getattr(node, "module", None) or node.names[0].name
                assert not mod.startswith("paho"), path.name
