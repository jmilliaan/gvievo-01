"""STATION_LINK_HOME: at HOME with no working broker link for over 60 s. Tells people, decides nothing."""

import ast
from pathlib import Path

from agv_core import alarms

from amr_station import bridge_core as bc

LIMIT = bc.HOME_LINK_ALARM_S


def test_it_is_a_warning_and_clears_itself():
    row = alarms.get("STATION_LINK_HOME")
    assert row.severity == "warn" and row.clears_by == "auto"
    assert alarms.get("STATION_LINK_DOWN").severity == "info", "a far trip loses the link anyway"


def test_not_before_60_s():
    a = bc.HomeLinkAlarm()
    assert a.update(0.0, True, False) == ""
    assert a.update(LIMIT, True, False) == ""
    assert a.update(LIMIT + 0.1, True, False) == "raise" and a.standing


def test_not_away_from_home_however_long():
    a = bc.HomeLinkAlarm()
    for t in range(0, 1000, 10):
        assert a.update(float(t), False, False) == ""


def test_the_time_away_does_not_count():
    a = bc.HomeLinkAlarm()
    a.update(0.0, False, False)
    assert a.update(500.0, True, False) == "", "arrived just now"
    assert a.update(500.0 + LIMIT + 0.1, True, False) == "raise"


def test_a_link_at_home_never_raises():
    a = bc.HomeLinkAlarm()
    assert a.update(0.0, True, True) == "" and a.update(1000.0, True, True) == ""


def test_it_repeats_while_it_stands_and_clears_once():
    a = bc.HomeLinkAlarm()
    a.update(0.0, True, False)
    assert a.update(LIMIT + 1, True, False) == "raise"
    assert a.update(LIMIT + 2, True, False) == ""
    assert a.update(LIMIT + 1 + bc.HOME_LINK_REPEAT_S, True, False) == "raise"
    assert a.update(LIMIT + 200, True, True) == "clear" and not a.standing
    assert a.update(LIMIT + 201, True, True) == ""


def test_leaving_home_clears_it():
    a = bc.HomeLinkAlarm()
    a.update(0.0, True, False)
    a.update(LIMIT + 1, True, False)
    assert a.update(LIMIT + 2, False, False) == "clear"


def test_motion_never_reads_the_link():
    """Nothing the motion code imports knows the bridge or its alarm."""
    root = Path(__file__).resolve().parents[2]
    for path in [root / "amr_line/amr_line/job.py", root / "amr_line/amr_line/site_run.py",
                 root / "amr_base/amr_base/gating.py", root / "amr_base/amr_base/drive_node.py",
                 root / "amr_base/amr_base/cmd_mux_kinematics_node.py"]:
        src = path.read_text()
        assert "STATION_LINK" not in src, path
        tree = ast.walk(ast.parse(src))
        names = [n.module or "" for n in tree if isinstance(n, ast.ImportFrom)]
        assert not [n for n in names if n.startswith("amr_station")], path
