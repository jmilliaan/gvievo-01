"""Rolling corner (2026-11-06): a sharp corner taken without stopping, the kink pivot underneath.

Closed loop on the kink pivot's polyline plant (MLS window hard at +/-100 mm, tougher than the
vehicle's). Mechanism checks: the yaw, speed and exit band are settled on the vehicle."""
import pytest
from agv_core import config as vehicle
from agv_core import kinematics
from agv_core import mission as missions
from line_fixtures import NO_TAPE
from test_kink_pivot import DT, Plant, Split, ends_on_the_new_tape, kink
from test_mission_engine import World

from amr_line import autopilot, corner
from amr_line import job as lj


@pytest.fixture(autouse=True)
def rolling(monkeypatch):
    monkeypatch.setattr(vehicle, "CORNER_YAW_DEG_S", 30.0)
    monkeypatch.setattr(vehicle, "CORNER_RPM", 200.0)
    monkeypatch.setattr(vehicle, "CORNER_EXIT_MM", 25.0)
    monkeypatch.setattr(vehicle, "CORNER_LEAD_S", 0.3)


def start(plant):
    w = World(missions.load("c-mru-guided"))
    w.comms = False
    w.integrate = False
    w.start()
    return w, plant


def step(w, p, sensor=None, **over):
    left, right = w.tick(sensor=p.sensor() if sensor is None else sensor, **over)
    p.step(left, right)
    w.counts = (int(round(p.counts[0])), int(round(p.counts[1])))
    w.still = p.still
    return left, right


def drive(path, seconds=25.0):
    """Returns (world, plant, slowest body speed past the corner's start, wheel commands in the turn)."""
    w, p = start(Plant(path))
    slowest, turning = 9.0, []
    for _ in range(int(seconds / DT)):
        cmd = step(w, p)
        if w.job.corner.active:
            turning.append(cmd)
        if p.x > -0.3:
            slowest = min(slowest, kinematics.wheels_to_body(p.l, p.r)[0])
        arrived = p.x > path[-1][0] - 0.3 and abs(p.y - path[-1][1]) < 0.3
        if w.job.state not in (lj.RUNNING, lj.HOLD) or arrived:
            break
    return w, p, slowest, turning


@pytest.mark.parametrize("deg", [40.0, -45.0, 50.4, -50.4, 60.0])
def test_a_sharp_corner_never_stops_and_never_pivots(deg):
    w, p, slowest, _turning = drive(kink(deg))
    ends_on_the_new_tape(w, p)
    assert w.job.kinks == 0 and w.job.corners == 1
    assert slowest > 0.02, slowest
    assert not w.job.corner.active and not w.job.pivoting


def test_a_mild_corner_stays_with_the_follower():
    w, p, _slowest, _turning = drive(kink(-30.0))
    ends_on_the_new_tape(w, p)
    assert w.job.corners == 0 and w.job.kinks == 0


def test_the_turn_never_raises_a_wheel_above_the_cruise():
    w, _p, _slowest, turning = drive(kink(50.4))
    cruise = max(w.job.tape.cruise_rpm or vehicle.AUTO_RPM, 0.0)
    assert turning and max(max(abs(a), abs(b)) for a, b in turning) <= cruise + 1.0


def test_off_in_the_profile_is_the_kink_pivot(monkeypatch):
    monkeypatch.setattr(vehicle, "CORNER_YAW_DEG_S", 0.0)
    w, p, slowest, _turning = drive(kink(50.4))
    ends_on_the_new_tape(w, p)
    assert w.job.corners == 0 and w.job.kinks == 1 and slowest < 0.02


def test_the_tape_end_near_the_centre_is_still_the_end():
    w = World(missions.load("c-mru-guided"))
    w.comms = False
    w.start()
    w.drive(2.0)
    w.drive(2.0, sensor=NO_TAPE)
    assert w.job.corners == 0 and w.job.state == lj.DONE and "track lost" in w.job.reason


def turning_with_tape_gone():
    """Trip a turn on a tape running off fast, then take the tape away for good."""
    w, p = start(Plant(kink(50.4)))
    while not w.job.corner.active:
        step(w, p)
        assert p.x < 0.5, "no turn"
    return w, p


def test_a_tape_that_never_comes_back_stops_and_faults_for_a_person():
    w, p = turning_with_tape_gone()
    w.still = False
    for _ in range(int(60.0 / DT)):
        step(w, p, sensor=NO_TAPE)
        if w.job.state != lj.RUNNING:
            break
    assert w.job.state == lj.FAULT and "kink" in w.job.reason, w.job.reason
    assert f"within {vehicle.KINK_MAX_DEG:.0f} deg" in w.job.reason
    assert w.job.corner.deg == pytest.approx(vehicle.KINK_MAX_DEG, abs=2.0)
    assert not w.job.corner.active and w.job.kink is None
    assert step(w, p, sensor=NO_TAPE) == (0.0, 0.0)


def test_a_protective_stop_mid_turn_drops_it_and_the_run_recovers():
    w, p = turning_with_tape_gone()
    assert step(w, p, field_clear=False) == (0.0, 0.0)
    assert w.job.state == lj.HOLD and not w.job.corner.active
    for _ in range(int(40.0 / DT)):
        step(w, p)
        if w.job.state != lj.HOLD and (p.x > kink(50.4)[-1][0] - 0.3):
            break
    ends_on_the_new_tape(w, p)


def test_a_silent_sensor_mid_turn_is_no_blind_turn():
    w, p = turning_with_tape_gone()
    assert w.tick(sensor=p.sensor(), sensor_age_s=1.0) == (0.0, 0.0)
    assert w.job.state == lj.HOLD and not w.job.corner.active


def test_a_forced_u_turn_still_takes_a_corner_as_a_corner():
    w, p = start(Plant(kink(50.4)))
    w.job.force_u_turn(True)
    for _ in range(int(25.0 / DT)):
        step(w, p)
        if w.job.corners and not w.job.corner.active:
            break
    assert w.job.corners == 1 and w.job.kinks == 0 and w.job.state == lj.RUNNING, w.job.reason
    assert w.job.tape.uturn_req is None and w.job.tape.uturn_forced


def test_the_split_still_takes_the_ordered_leg_and_spends_the_order():
    from amr_line import branch  # noqa: PLC0415

    for side, sign in (("left", 1.0), ("right", -1.0)):
        w, p = start(Split())
        assert w.job.order_branch(side)[0]
        for _ in range(int(25.0 / DT)):
            step(w, p)
            if w.job.state != lj.RUNNING or p.x > 1.0:
                break
        assert w.job.state == lj.RUNNING, w.job.reason
        assert sign * p.y > 1.0, (side, p.y)
        assert w.job.tape.branch.ladder.intent() == branch.STRAIGHT and w.job.tape.branch.forks == 1


# -- the pure trigger ------------------------------------------------------------------


def feed(c, values, guard="", nlcp=2, v=1273.0, dt=0.02):
    return [c.watch(e, guard, nlcp, v, dt) for e in values]


def ramp_mm(a, b, n):
    return [a + (b - a) * k / (n - 1) for k in range(n)]


def test_a_fast_exit_trips_and_a_slow_drift_at_the_same_error_does_not():
    fast = corner.CornerTurn()
    assert any(feed(fast, ramp_mm(0.0, 70.0, 12)))           # 300 mm/s
    assert fast.direction == "cw"
    slow = corner.CornerTurn()
    assert not any(feed(slow, ramp_mm(0.0, 80.0, 150)))      # 27 mm/s: an ordinary curve
    back = corner.CornerTurn()
    assert not any(feed(back, ramp_mm(90.0, 30.0, 20)))      # coming back in


def test_a_reading_jump_is_not_a_rate():
    c = corner.CornerTurn()
    feed(c, [0.0] * 5)
    assert not any(feed(c, [40.0, 80.0, 90.0], guard="slew"))


def test_a_fork_reading_defers_the_turn_past_the_episode():
    c = corner.CornerTurn()
    assert not any(feed(c, ramp_mm(0.0, 70.0, 12), nlcp=6))
    assert c.watch(75.0, "", 2, 1273.0, 0.02) is False       # one single tick: not yet
    assert c.watch(80.0, "", 2, 1273.0, 0.02) is True


def test_no_trip_at_or_below_the_turn_speed():
    c = corner.CornerTurn()
    assert not any(feed(c, ramp_mm(0.0, 70.0, 12), v=vehicle.CORNER_RPM))


def test_off_never_trips(monkeypatch):
    monkeypatch.setattr(vehicle, "CORNER_YAW_DEG_S", 0.0)
    assert not any(feed(corner.CornerTurn(), ramp_mm(0.0, 90.0, 12)))


def test_the_turn_ends_on_the_exit_band_or_the_angle_limit():
    c = corner.CornerTurn()
    assert any(feed(c, ramp_mm(0.0, 70.0, 12)))
    assert c.turn(None, 0.02) and c.turn(60.0, 0.02)
    assert c.turn(20.0, 0.02) is False and c.result == "tape back" and not c.active
    c = corner.CornerTurn()
    assert any(feed(c, ramp_mm(0.0, 70.0, 12)))
    while c.turn(None, 0.02):
        pass
    assert c.result == "angle limit" and c.deg >= vehicle.KINK_MAX_DEG


def test_a_warning_field_scales_the_yaw_it_counts():
    c = corner.CornerTurn()
    assert any(feed(c, ramp_mm(0.0, 70.0, 12)))
    c.turn(None, 1.0, scale=0.0)
    assert c.deg == 0.0


def test_the_speed_never_goes_negative_and_keeps_the_outer_wheel_on_the_ramp():
    c = corner.CornerTurn()
    assert any(feed(c, ramp_mm(0.0, 70.0, 12)))
    assert c.speed_rpm(-50.0) == 0.0
    half = abs(c.yaw_rad_s()) / (2.0 * vehicle.RAD_S_PER_RPM_DIFF)
    assert c.speed_rpm(1273.0) == pytest.approx(1273.0 - half)
    assert c.speed_rpm(100.0) == 100.0


def test_the_turn_lands_on_its_speed_without_running_past_it():
    f = autopilot.LineFollower()
    f._v_rpm = 264.0
    sensor = {"tracks": [{"index": 2, "pos_mm": 0, "width": 10}], "has_track": True, "nlcp": 2}
    speeds = [f.update(sensor, 0.005, 0.02, True, cruise_rpm=200.0, urgent_rate=1600.0,
                       rolling=True)[2]["v_base"]
              for _ in range(30)]
    assert min(speeds) == pytest.approx(200.0) and speeds[-1] == pytest.approx(200.0)


def test_a_gap_in_the_turn_is_coast_and_outside_it_the_budget_stands():
    gone = {"tracks": [], "has_track": False, "nlcp": 0}
    for rolling, state in ((True, "coast"), (False, "line_lost")):
        f = autopilot.LineFollower()
        f._v_rpm = 400.0
        for _ in range(100):
            diag = f.update(gone, 0.005, 0.02, True, rolling=rolling)[2]
        assert diag["state"] == state
