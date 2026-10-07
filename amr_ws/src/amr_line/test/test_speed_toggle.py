"""RFID speed toggle (2026-10-07): any toggle tag flips cruise <-> slow, 2 s lockout.

The pure SpeedToggle, then the real FollowJob/TapeRun with the profile's toggle
tags patched in - plain line following, no mission, which is how the vehicle runs.
"""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
for _p in (ROOT, os.path.join(ROOT, "amr_ws", "src", "amr_line"), os.path.dirname(__file__)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agv_core import config as vehicle  # noqa: E402
from amr_line.speed_toggle import SpeedToggle  # noqa: E402
from test_mission_engine import World  # noqa: E402

from amr_line import job as lj  # noqa: E402

A, B = "00A1", "00B2"


def test_any_toggle_tag_flips_and_others_are_ignored():
    s = SpeedToggle((A, B), lockout_s=2.0)
    assert s.slow is False, "a run starts at cruise"
    assert s.scan(10.0, A) == "slow"
    assert s.scan(13.0, A) == "fast", "the same tag flips back: direction does not matter"
    assert s.scan(16.0, B) == "slow"
    assert s.scan(19.0, A) == "fast"
    assert s.scan(20.0, "0010") is None and s.slow is False, "not a toggle tag"


def test_lockout_holds_off_toggle_tags_for_two_seconds():
    s = SpeedToggle((A, B), lockout_s=2.0)
    s.scan(10.0, A)
    assert s.scan(10.5, B) == "lockout" and s.slow is True
    assert s.scan(11.99, A) == "lockout" and s.slow is True
    assert s.ignored == 2
    assert s.scan(12.0, B) == "fast", "at exactly lockout_s it counts again"


@pytest.fixture
def toggle_tags():
    saved = vehicle.SPEED_TOGGLE_TAGS, vehicle.SPEED_TOGGLE_LOCKOUT_S
    vehicle.SPEED_TOGGLE_TAGS, vehicle.SPEED_TOGGLE_LOCKOUT_S = (A, B), 2.0
    yield
    vehicle.SPEED_TOGGLE_TAGS, vehicle.SPEED_TOGGLE_LOCKOUT_S = saved


def test_corner_from_either_end_in_plain_line_following(toggle_tags):
    w = World(None)
    w.start()
    w.drive(1.0)
    assert w.job.diag["speed_target_rpm"] == vehicle.AUTO_RPM

    w.read(A)           # corner entry
    w.tick()
    snap = w.job.mission_snapshot()
    assert snap["slow_zone"] is True and snap["last_tag_action"] == "speed slow"
    assert w.job.diag["speed_target_rpm"] == vehicle.AUTO_SLOW_RPM

    w.read(B)           # read again inside the lockout: swallowed, still slow
    w.tick()
    assert w.job.mission_snapshot()["slow_zone"] is True
    assert w.job.mission_snapshot()["last_tag_action"] == "speed toggle ignored"

    w.drive(2.5)
    w.read(B)           # corner exit
    w.tick()
    assert w.job.mission_snapshot()["slow_zone"] is False
    assert w.job.diag["speed_target_rpm"] == vehicle.AUTO_RPM

    w.drive(2.5)
    w.read(B)           # the other way round: B is now the entry
    w.tick()
    assert w.job.mission_snapshot()["slow_zone"] is True
    events = [text for _, text in w.job.tape.drain_events()]
    assert any("speed SLOW (toggle tag 00B2)" in e for e in events)


def test_a_new_run_starts_at_cruise(toggle_tags):
    w = World(None)
    w.start()
    w.read(A)
    w.tick()
    assert w.job.tape.speed.slow is True
    w.job.reset()
    assert w.job.state == lj.IDLE and w.job.tape.speed.slow is False
