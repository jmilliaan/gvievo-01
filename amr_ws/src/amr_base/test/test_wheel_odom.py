"""H-P2-2 / WP-P8 + WP-C10 + WP-T4: the staleness bridge, the 6064h-vs-606Ch check and the
/odom_raw integrator drive_node now runs itself (amr_base.wheel_odom). Pure: runs on the dev box."""

import math
import pathlib
import time

import pytest
from test_canopen import FakeBus, _arm, _link

from amr_base import wheel_odom
from amr_base.canopen import ARMED, STANDBY, WheelPosition, WheelScale, wheel_feedback
from amr_base.diff_drive import Geometry

CPR = 1_080_000.0  # counts per wheel rev, gear 30: 36 000 per motor rev
S = WheelScale(30.0, False, False, CPR)
MAX_RPM = 4000.0
ONE = 2 * math.pi / CPR
GEOM = Geometry(0.1, 0.5)


def _wp():
    return WheelPosition(max_rpm=MAX_RPM)


def test_a_short_staleness_gap_is_bridged_with_its_whole_delta():
    w = _wp()
    w.update(0, True, S, True, 1, t=0.00)
    w.update(100, True, S, True, 1, t=0.02)
    assert w.joined and w.step == pytest.approx(100 * ONE) and w.step_dt == pytest.approx(0.02)
    w.update(150, False, S, True, 1, t=0.04, stale_only=True)  # late: baseline kept
    assert not w.joined and w.rad == pytest.approx(100 * ONE)
    w.update(400, True, S, True, 1, t=0.10)
    assert w.joined and w.gaps == 1 and w.rebaselines == 0
    assert w.rad == pytest.approx(400 * ONE)  # the gap's motion counted, not lost
    assert w.step_dt == pytest.approx(0.08)


def test_a_long_or_implausible_gap_is_a_rebaseline_and_never_moves_the_output():
    w = _wp()
    w.update(0, True, S, True, 1, t=0.0)
    w.update(None, False, S, True, 1, t=0.1, stale_only=True)
    w.update(1000, True, S, True, 1, t=0.6)  # gap 0.6 s >= 0.5 s
    assert not w.joined and w.rebaselines == 1 and w.rad == 0.0
    # 0.2 s since the last valid sample at 4000 r/min: 13.3 motor revs = 480 000 counts, x1.2 = 576 000
    w.update(1000, False, S, True, 1, t=0.7, stale_only=True)
    w.update(1000 + 600_000, True, S, True, 1, t=0.8)  # faster than the motor turns
    assert not w.joined and w.rebaselines == 2 and w.rad == 0.0
    w.update(1000 + 600_010, True, S, True, 1, t=0.82)
    assert w.joined and w.rad == pytest.approx(10 * ONE)


def test_a_fault_or_scale_gap_is_not_bridged_and_the_old_constructor_never_bridges():
    w = _wp()
    w.update(0, True, S, True, 1, t=0.0)
    w.update(None, False, S, True, 1, t=0.02, stale_only=False)  # not just late: dropped
    w.update(10, True, S, True, 1, t=0.04)
    assert not w.joined and w.rebaselines == 1 and w.gaps == 0
    old = WheelPosition()  # no max_rpm: R06 behaviour exactly
    old.update(0, True, S, True, 1, t=0.0)
    old.update(5, False, S, True, 1, t=0.02, stale_only=True)
    old.update(10, True, S, True, 1, t=0.04)
    assert not old.joined and old.rad == 0.0


def test_wheel_feedback_marks_a_late_sample_stale_only():
    bus = FakeBus()
    link = _link(bus)
    _arm(link, 20, None, 0, 30.0, False, False)
    now = 1000.0
    pos = {n: WheelPosition(max_rpm=MAX_RPM) for n in (1, 2)}
    for n in (1, 2):
        t = link.telemetry[n]
        t.statusword, t.rpm, t.position, t.error_register = 0x1637, 0, 500, 0
        t.t_status = t.t_position = now
    wheels = ((1, True), (2, False))
    wheel_feedback(link, now, 0.05, wheels, {1: True, 2: True}, pos)
    for n in (1, 2):
        link.telemetry[n].position = 600
    fb = wheel_feedback(link, now + 0.02, 0.05, wheels, {1: False, 2: False}, pos)  # pair incomplete
    assert not fb[1][2] and pos[1]._held  # late, not wrong
    for n in (1, 2):
        link.telemetry[n].t_status = link.telemetry[n].t_position = now + 0.04
    fb = wheel_feedback(link, now + 0.04, 0.05, wheels, {1: True, 2: True}, pos)
    assert fb[1][2] and pos[1].gaps == 1 and pos[1].joined


# ---------------------------------------------------------------- FeedbackCheck

def _run(chk, counts_rad_s, vel_rad_s, seconds, armed=True, dt=0.02):
    n = int(round(seconds / dt))
    for k in range(n):
        chk.update(k * dt, counts_rad_s * dt, dt, vel_rad_s, armed)
    return chk.implausible


def test_frozen_counts_under_a_turning_606c_make_the_wheel_implausible_then_clear():
    chk = wheel_odom.FeedbackCheck(max_wheel_rad_s=14.0)
    assert not _run(chk, 3.0, 3.0, 2.0)  # agreeing: never
    assert not _run(chk, 0.0, 3.0, 0.5)  # one bad window is not a verdict
    assert _run(chk, 0.0, 3.0, 0.5) and chk.trips == 1 and "606Ch" in chk.reason
    assert _run(chk, 3.0, 3.0, 0.5)  # one good window does not clear it
    assert not _run(chk, 3.0, 3.0, 0.5)


def test_counts_moving_while_606c_reads_zero_trip_too_and_standby_judges_nothing():
    chk = wheel_odom.FeedbackCheck(max_wheel_rad_s=14.0)
    assert _run(chk, 2.0, 0.0, 1.0)
    assert not _run(chk, 2.0, 0.0, 0.1, armed=False)  # not armed: verdict dropped
    assert not _run(chk, 2.0, 0.0, 3.0, armed=False)  # a pushed vehicle in STANDBY is not judged


def test_a_lagging_606c_on_a_ramp_stays_inside_the_tolerance():
    """606Ch 60 ms behind the counts on a 0.5 m/s^2 ramp (5 rad/s^2 at r=0.1) up to 7 rad/s."""
    chk = wheel_odom.FeedbackCheck(max_wheel_rad_s=14.0)
    dt, lag = 0.02, 0.06
    for k in range(int(1.4 / dt) + 50):
        t = k * dt
        w = min(7.0, 5.0 * t)
        chk.update(t, w * dt, dt, min(7.0, max(0.0, 5.0 * (t - lag))), True)
        assert not chk.implausible, t


def test_a_gap_in_the_steps_restarts_the_window():
    chk = wheel_odom.FeedbackCheck(max_wheel_rad_s=14.0)
    _run(chk, 0.0, 3.0, 0.4)
    chk.update(1.0, None, None, 3.0, True)  # not a measured continuation
    assert chk._dt == 0.0 and chk.windows == 0


def test_an_implausible_wheel_is_reported_invalid_but_keeps_counting():
    bus = FakeBus()
    link = _link(bus)
    _arm(link, 20, None, 0, 30.0, False, False)
    assert link.state == ARMED
    pos = {n: WheelPosition(max_rpm=MAX_RPM) for n in (1, 2)}
    checks = {n: wheel_odom.FeedbackCheck(max_wheel_rad_s=14.0) for n in (1, 2)}
    wheels = ((1, True), (2, False))
    now = 1000.0
    for _ in range(80):  # node 1: counts frozen while it reports 1000 r/min
        now += 0.02
        for n in (1, 2):
            t = link.telemetry[n]
            t.statusword, t.rpm, t.error_register = 0x1637, 1000 if n == 1 else 0, 0
            t.position = 500
            t.t_status = t.t_position = now
        fb = wheel_feedback(link, now, 0.05, wheels, {1: True, 2: True}, pos, checks)
    assert checks[1].implausible and not fb[1][2] and fb[2][2]
    assert pos[1].joined  # the position chain underneath is intact
    link.state = STANDBY
    fb = wheel_feedback(link, now + 0.02, 0.05, wheels, {1: True, 2: True}, pos, checks)
    assert not checks[1].implausible


# ---------------------------------------------------------------- WheelOdom

def test_odom_integrates_steps_and_skips_a_chain_start():
    o = wheel_odom.WheelOdom(GEOM)
    assert o.update(False, 1.0, 1.0, 0.02, 0.0, 0.0) is None
    assert o.update(True, 1.0, 1.0, None, 0.0, 0.0) is None and o.skipped == 1  # no dt: chain start
    v, wz = o.update(True, 0.2, 0.2, 0.02, 0.0, 0.0)
    assert v == pytest.approx(0.1 * 0.2 / 0.02) and wz == pytest.approx(0.0)
    assert o.state.x == pytest.approx(0.02)
    assert o.update(True, math.nan, 0.2, 0.02, 0.0, 0.0) is None  # never integrated


def test_twist_from_606c_is_behind_a_switch_and_the_pose_still_comes_from_counts():
    o = wheel_odom.WheelOdom(GEOM, twist_source="606c")
    v, wz = o.update(True, 0.2, 0.2, 0.02, 9.0, 11.0)
    assert v == pytest.approx(0.1 * 10.0) and wz == pytest.approx(0.1 * 2.0 / 0.5)
    assert o.state.x == pytest.approx(0.02)
    with pytest.raises(ValueError):
        wheel_odom.WheelOdom(GEOM, twist_source="both")


def test_drive_node_defaults_keep_counts_twist_and_gyro_withholding_off():
    """Contract (the node needs rclpy, so read its source): the T4 switch and the gyro_check
    withholding default OFF, and /odom_raw keeps its topic and frames for ekf.yaml."""
    src = (pathlib.Path(wheel_odom.__file__).parent / "drive_node.py").read_text(encoding="utf-8")
    assert 'dp("odom_twist_source", "counts")' in src
    assert 'dp("gyro_check", False)' in src
    assert '"/odom_raw"' in src and 'dp("odom_frame", "odom")' in src
    assert 'dp("base_frame", "base_footprint")' in src
    assert "TransformBroadcaster" not in src  # the EKF owns odom -> base_footprint


def test_time_base_is_monotonic_not_the_ros_clock():
    """dt comes from the bus thread's clock passed through WheelPosition, never a header stamp."""
    w = _wp()
    t0 = time.monotonic()
    w.update(0, True, S, True, 1, t=t0)
    w.update(36, True, S, True, 1, t=t0 + 0.02)
    assert w.step_dt == pytest.approx(0.02)
