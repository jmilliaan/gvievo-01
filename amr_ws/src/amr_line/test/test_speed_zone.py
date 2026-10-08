"""amr_line.speed_zone: the high-zone state machine and the curve guard. Pure.

tracked-speed-plan-1 section 3 (state table) and section 4 (guard), row by row,
plus the corner passes with shared ids (inner 0040, outer 0060).
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
for _p in (ROOT, os.path.join(ROOT, "amr_ws", "src", "amr_line")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402
from amr_line.speed_zone import ARMED, HIGH, NORMAL, CurveGuard, SpeedZone  # noqa: E402

INNER, OUTER = "0040", "0060"
CFG = {"inner": INNER, "outer": OUTER, "high_for_m": 10.0, "arm_m": 0.7, "spacing_m": 0.5, "brake_m": 1.35}
RPM_PER_MPS, DRIVE_DECEL = 3183.1, 3200.0


def zone():
    return SpeedZone(CFG, normal_rpm=1592.0, rpm_per_mps=RPM_PER_MPS, drive_decel_rpm_s=DRIVE_DECEL)


def enter(z):
    z.tag(OUTER)
    z.travel(0.5)
    level, text = z.tag(INNER)
    assert z.state == HIGH and level == "info", text
    return z


def test_no_high_zone_means_normal_always():
    z = SpeedZone(None)
    assert z.tag(OUTER) is None and z.tag(INNER) is None
    assert z.state == NORMAL and not z.high


def test_outer_then_inner_within_the_window_is_high():
    z = zone()
    z.tag(OUTER)
    assert z.state == ARMED
    enter(zone())


def test_inner_alone_stays_normal():
    z = zone()
    level, text = z.tag(INNER)
    assert z.state == NORMAL and level == "info" and "without outer" in text


def test_the_entry_window_expires():
    z = zone()
    z.tag(OUTER)
    level, text = z.travel(0.71)
    assert z.state == NORMAL and level == "warn" and "entry window closed" in text
    level, text = z.tag(INNER)
    assert z.state == NORMAL and level == "warn" and "0.71 m after outer" in text, text


def test_a_station_tag_between_outer_and_inner_does_not_touch_the_entry():
    """Machine tags are not speed events (operator, 2026-10-08)."""
    z = zone()
    z.tag(OUTER)
    assert z.tag("0110") is None and z.state == ARMED
    z.travel(0.5)
    z.tag(INNER)
    assert z.high


def test_budget_expiry_is_the_planned_exit_on_the_comfort_ramp():
    z = enter(zone())
    z.travel(9.9)
    assert z.high
    level, text = z.travel(0.2)
    assert z.state == NORMAL and "budget" in text and z.exit_rate is None


def test_inner_while_high_is_a_late_exit_at_half_a_metre_per_s2():
    z = enter(zone())
    z.travel(3.0)                           # the far end of the straight
    level, text = z.tag(INNER)
    assert level == "warn" and z.state == NORMAL
    assert z.exit_rate == pytest.approx(0.5 * RPM_PER_MPS)


def test_outer_while_high_is_an_urgent_exit_below_the_drive_limit():
    z = enter(zone())
    z.travel(3.0)
    level, text = z.tag(OUTER)
    assert level == "warn" and "inner tag missed" in text and z.state == NORMAL
    assert z.exit_rate == pytest.approx(0.95 * DRIVE_DECEL)
    assert z.exit_rate < DRIVE_DECEL


def test_an_urgent_rate_is_never_relaxed_mid_drop():
    z = enter(zone())
    z.travel(3.0)
    z.tag(OUTER)
    z.drop("hold")
    assert z.exit_rate == pytest.approx(0.95 * DRIVE_DECEL)
    z.settled(1592.0)
    assert z.exit_rate is None


def test_drop_from_the_job():
    z = enter(zone())
    assert z.drop("stop MRU1") == "stop MRU1" and z.state == NORMAL
    assert z.drop("again") is None, "dropping NORMAL reports nothing"
    z = enter(zone())
    z.drop("curve guard", urgent=True)
    assert z.exit_rate == pytest.approx(0.95 * DRIVE_DECEL)


def test_a_station_stop_keeps_the_budget_left_for_the_departure():
    z = enter(zone())
    z.travel(3.0)
    assert z.park("stop MRU1") == "stop MRU1" and z.state == NORMAL and "departs HIGH" in z.reason
    z.travel(0.5)                           # the measured stop itself
    level, text = z.resume()
    assert z.high and level == "info" and "as arrived" in text
    assert z.budget_left_m() == pytest.approx(10.0 - 3.0 - 0.5)


def test_a_station_reached_at_normal_departs_normal():
    z = zone()
    assert z.park("stop MRU1") is None
    assert z.resume() is None and z.state == NORMAL


def test_anything_between_arrival_and_departure_forgets_the_budget():
    for spoil in (lambda z: z.drop("hold (field)"), lambda z: z.tag(OUTER), lambda z: z.tag(INNER)):
        z = enter(zone())
        z.park("stop MRU1")
        spoil(z)
        assert z.resume() is None or not z.high, "departs NORMAL"
        assert not z.high


def test_a_budget_used_up_by_the_stop_departs_normal():
    z = enter(zone())
    z.travel(9.8)
    z.park("stop MRU1")
    z.travel(0.5)
    assert z.resume() is None and z.state == NORMAL and "used up" in z.reason


def test_a_full_corner_pass_with_shared_ids():
    """Leaving S1 (inner, outer), the corner, entering S2 (outer, inner)."""
    z = enter(zone())
    z.travel(10.0)                          # budget ends on S1
    assert z.state == NORMAL
    z.tag(INNER)                            # exit inner: NORMAL already, no-op
    z.travel(0.5)
    z.tag(OUTER)                            # exit outer after an inner: leaving, never arms
    assert z.state == NORMAL and "leaving" in z.reason
    z.travel(0.5 + 0.785 + 0.5)             # the corner (R 0.5)
    z.tag(OUTER)                            # entry outer of S2
    z.travel(0.5)
    z.tag(INNER)                            # entry inner of S2
    assert z.high


def interleave(z, first, second, overlap_m=0.3, step=0.02):
    """Two clusters in the field together: reads alternate while the vehicle moves."""
    z.tag(first)
    z.travel(0.5)
    z.tag(second)
    moved, which = 0.0, first
    while moved < overlap_m:
        z.travel(step)
        moved += step
        z.tag(which)
        which = second if which == first else first


def test_overlapping_read_zones_on_entry_stay_high():
    z = zone()
    interleave(z, OUTER, INNER)
    assert z.high, z.reason


def test_overlapping_read_zones_on_exit_never_grant_high():
    """40 then 60 with the fields overlapping: the 40 re-read after the 60 is not an entry."""
    z = enter(zone())
    z.travel(10.0)                          # budget spent: NORMAL before the exit pair
    interleave(z, INNER, OUTER)
    assert z.state == NORMAL, z.reason
    z = zone()                              # a run started inside the straight, NORMAL
    interleave(z, INNER, OUTER)
    assert z.state == NORMAL, z.reason


def test_a_cluster_reread_after_a_read_gap_is_the_same_pass():
    z = zone()
    z.tag(OUTER)
    z.travel(0.15)
    z.tag(OUTER)                            # tag_clear_s gap inside one cluster: no re-arm
    assert z.armed_m == pytest.approx(0.15)
    z.travel(0.35)
    z.tag(INNER)
    assert z.high


def test_missed_entry_outer_after_a_corner_stays_normal():
    z = enter(zone())
    z.travel(10.0)
    z.tag(INNER)
    z.travel(0.5)
    z.tag(OUTER)
    z.travel(0.5 + 0.785 + 0.5 + 0.5)       # S2's outer never read
    z.tag(INNER)
    assert z.state == NORMAL


def test_curve_guard_trips_on_curvature_sustained_over_the_window():
    g = CurveGuard(0.25, 40.0, window_m=0.05)
    assert g.update(True, 0.0, 0.85, 5.0, 0.02) is None, "straight"
    assert g.update(True, 0.85, 0.85, 5.0, 0.02) is None, "1 1/m, not yet the window"
    assert g.update(True, 0.85, 0.85, 5.0, 0.02) is None
    why = g.update(True, 0.85, 0.85, 5.0, 0.02)
    assert why and "curvature" in why


def test_curve_guard_trips_on_lateral_error_and_resets_on_a_clean_tick():
    g = CurveGuard(0.25, 40.0, window_m=0.05)
    g.update(True, 0.0, 0.85, 60.0, 0.04)
    assert g.update(True, 0.0, 0.85, 5.0, 0.04) is None, "clean tick resets"
    g.update(True, 0.0, 0.85, -60.0, 0.03)
    assert "lateral error" in g.update(True, 0.0, 0.85, -60.0, 0.03)


def test_curve_guard_is_quiet_when_inactive_or_slow():
    g = CurveGuard(0.25, 40.0, window_m=0.05)
    for _ in range(10):
        assert g.update(False, 1.0, 0.85, 90.0, 0.05) is None
        assert g.update(True, 1.0, 0.1, 90.0, 0.05) is None, "below v_min: a pivot or creep"
