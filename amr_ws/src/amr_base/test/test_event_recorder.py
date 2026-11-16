"""The base's event recorder (unified plan WP-H3, hardening plan H-P1-15): every /amr/events
publisher is heard, a write failure is a counter and one EVENTLOG_WRITE_FAILED edge, never an
exception, and DeviceHealth repeats are not news. No ROS: the pure Recorder and the source."""

from __future__ import annotations

import ast
import json
import pathlib

from agv_core import alarms
from agv_core.eventlog import EventLog

from amr_base import event_recorder as er

SRC = pathlib.Path(__file__).resolve().parents[2]
NODE = SRC / "amr_base" / "amr_base" / "event_recorder_node.py"


def _rec(tmp_path):
    return er.Recorder(EventLog(er.path_in(str(tmp_path))))


def _lines(rec):
    with open(rec.log.path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh]


def test_every_event_is_appended_in_the_web_s_row_shape(tmp_path):
    rec = _rec(tmp_path)
    row = er.event_row(1.0, "trolley_node", 1, "REAR_SCANNER_SILENT", "no scan", 7)
    assert rec.record(row) is None
    assert _lines(rec) == [{"t": 1.0, "source": "trolley_node", "level": "warn",
                            "code": "REAR_SCANNER_SILENT", "text": "no scan", "seq": 7}]
    assert rec.recorded == 1 and rec.log.errors == 0
    assert er.event_row(0, "x", 9, "C", "", 0)["level"] == "error"  # an out-of-range level is clamped


def test_its_own_file_not_the_web_s(tmp_path):
    """Two appenders rotating one file would interleave and lose lines."""
    assert er.FILENAME != "events.jsonl"
    assert er.path_in(str(tmp_path)).endswith(str(pathlib.Path("logs") / er.FILENAME))


def test_a_write_failure_is_counted_and_reported_once_then_cleared_once(tmp_path):
    rec = _rec(tmp_path)
    good = rec.log.path
    rec.log.path = str(tmp_path)  # a directory: every append fails with an OSError
    row = er.event_row(1.0, "drive_node", 2, "DRIVE_FAULT", "x", 1)
    edge = rec.record(row)
    assert edge is not None and edge[1] == "EVENTLOG_WRITE_FAILED" and edge[0] == alarms.level(edge[1])
    assert rec.failing and rec.log.errors == 1
    # its own report comes back on /amr/events: recorded (and failing) again, no second edge
    assert rec.record(er.event_row(1.1, er.SOURCE, edge[0], edge[1], edge[2], 1)) is None
    assert rec.log.errors == 2
    rec.log.path = good
    cleared = rec.record(row)
    assert cleared == (0, "EVENTLOG_WRITE_FAILED", f"cleared: writing {good} again")
    assert not rec.failing and rec.record(row) is None


def test_device_health_repeats_are_not_recorded(tmp_path):
    rec = _rec(tmp_path)
    rec.health(1.0, "dio", "OK", "", "")
    rec.health(1.5, "dio", "OK", "", "")  # the 2 Hz repeat
    rec.health(2.0, "dio", "LOST", "IO_ISLAND_LOST", "no scan for 1.0 s")
    rec.health(2.5, "dio", "LOST", "IO_ISLAND_LOST", "no scan for 1.5 s")  # detail only
    rec.health(3.0, "dio", "OK", "", "")
    got = [(x["source"], x["level"], x["code"], x["text"]) for x in _lines(rec)]
    assert got == [
        ("panel_node", "info", "DEVICE_HEALTH", "dio OK"),
        ("panel_node", "error", "IO_ISLAND_LOST", "dio LOST: no scan for 1.0 s"),
        ("panel_node", "info", "IO_ISLAND_LOST", "cleared: dio OK"),
    ]
    assert "DEVICE_HEALTH" in alarms.CATALOGUE and "EVENTLOG_WRITE_FAILED" in alarms.CATALOGUE


def _event_publishers():
    """(file, qos argument source) for every create_publisher(Event, "/amr/events", qos)."""
    out = []
    for path in sorted(SRC.rglob("*.py")):
        if "test" in path.parts or path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for c in ast.walk(tree):
            if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)):
                continue
            if (c.func.attr == "create_publisher" and len(c.args) >= 3
                    and isinstance(c.args[1], ast.Constant) and c.args[1].value == "/amr/events"):
                out.append((path.name, ast.unparse(c.args[2])))
    return out


def test_the_recorder_hears_every_event_publisher():
    """RELIABLE + VOLATILE, depth >= 200: compatible with every publisher, which must offer
    RELIABLE (a best-effort publisher would never reach a reliable subscription)."""
    pubs = _event_publishers()
    names = {f for f, _ in pubs}
    assert {"trolley_node.py", "station_bridge_node.py", "drive_node.py", "panel_node.py",
            "supervisor_node.py", "line_follow_node.py"} <= names
    for f, qos in pubs:
        assert qos.isdigit() or qos in ("EVENT_STREAM", "RELIABLE_1", "LATCHED"), (f, qos)
    src = NODE.read_text(encoding="utf-8")
    assert 'create_subscription(Event, "/amr/events", self._on_event, RECORD_QOS)' in src
    assert "depth=200" in src and "RELIABLE" in src and "QoSDurabilityPolicy.VOLATILE" in src
    assert "QoSDurabilityPolicy.TRANSIENT_LOCAL" not in src
