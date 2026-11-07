"""The position engine closed-loop (tracked plan 4, E1): the real FollowJob, follower and
SiteRun on the World plant of test_mission_engine, the site_fixture circuit, and a synthetic
locator - S is the signed wheel travel the job's own commands make, sigma what the test says.
The tape is where the route says: two tracks over the last 0.4 m into each junction, no tape
past the tape end."""
import math

import pytest
from agv_core import config as vehicle  # noqa: E402
from line_fixtures import counts_for_angle  # noqa: E402
from site_fixture import AREAS, graph, site  # noqa: E402
from test_mission_engine import CENTRED, NO_TAPE, PER_REV, World  # noqa: E402

from amr_line import job as lj  # noqa: E402
from amr_line import site_run  # noqa: E402
from amr_line import tape_locator as tl  # noqa: E402
from amr_line import trip_route as trr  # noqa: E402

FORK = {"tracks": [{"index": 2, "pos_mm": 0, "width": 10}, {"index": 3, "pos_mm": 45, "width": 10}],
        "has_track": True, "nlcp": 6, "track_level": 5}
# The AGV keeps a tape at 0 and the other appears beside it: on the far side from the order, as
# on the floor at every fork (each logged "that side is not in this diverter").
FORK_NEG = {"tracks": [{"index": 1, "pos_mm": -45, "width": 10}, {"index": 2, "pos_mm": 0, "width": 10}],
            "has_track": True, "nlcp": 3, "track_level": 5}
CRUISE = 0.4 * vehicle.RPM_PER_MPS


class TripWorld(World):
    def __init__(self, m, g, sigma=0.01, params=None):
        self.m, self.g = m, g
        self.sigma, self.lost, self.wrong = sigma, "", ""
        self.bias = 0.0                 # the locator's S minus the true S: AMCL out, wheels off
        self.amcl_out = ""
        self.extra_fork = None          # (S_a, S_b): two tracks where no junction is taught
        self.fork_left = FORK_NEG       # what a fork ordered left reads
        self.route = None
        self.S = 5.0                    # at HOME on the circuit, before any trip
        self._phase = "out"
        self._last = (0, 0)
        super().__init__(None)
        self.params = params or tl.Params()
        self.job.configure_site(self.params, lambda trip: trr.compile_trip(trip, m, g, areas=AREAS))
        ok, msg = self.job.set_mission(m)
        assert ok, msg
        self.job.confirm_off()

    def loc(self):
        r = self.route
        ident = r.ident if r else "circuit:C-M"
        S = self.S + self.bias
        home = min((S - r.S_start, S - r.S_end), key=abs) if r else S - 5.0
        return {"route": ident, "started": True, "S": S, "sigma": self.sigma, "health": "HEALTHY",
                "lost": self.lost, "amcl_out": self.amcl_out, "wrong_branch": self.wrong, "home_offset": home}

    def tape(self):
        r = self.route
        if r is None:
            return CENTRED
        for n in r.nodes:
            if n["fork"] and n["S_fork"] <= self.S < n["S"]:
                return self.fork_left if n["order"] == "left" else FORK
        if self.extra_fork and self.extra_fork[0] <= self.S < self.extra_fork[1]:
            return FORK
        u = r.uturn
        if u and u["mode"] == "tapeend" and self._phase == "out" and self.S >= u["S"]:
            return NO_TAPE
        return CENTRED

    def inputs(self, **over):
        over.setdefault("loc", self.loc())
        over.setdefault("sensor", self.tape())
        return super().inputs(**over)

    def tick(self, **over):
        before = self.counts
        out = super().tick(**over)
        dl, dr = self.counts[0] - before[0], self.counts[1] - before[1]
        dl, dr = (-dl if vehicle.INVERT_LEFT else dl), (-dr if vehicle.INVERT_RIGHT else dr)
        self.S += 0.5 * (dl + dr) * math.pi * vehicle.WHEEL_DIA_M / PER_REV
        if self.job.trip_new is not None:
            off = self.S - (self.route.S_end if self.route else 5.0)
            off = self.S - 5.0 if self.route is None else min((self.S - self.route.S_start, off), key=abs)
            self.route, self.job.trip_new = self.job.trip_new, None
            self.S, self._phase = self.route.S_start + off, "out"
        t = self.job.tape
        if getattr(t, "phase", "out") == "back" and self._phase == "out":
            u = self.route.uturn
            self.S = 2 * u["S"] - self.S if u["mode"] == "midline" else u["S"]
            self._phase = "back"
        return out

    def at(self, sid):
        return self.route.stop(sid)["S"]


def spin(w):
    """The U-turn spin from standstill, by hand: counts turned, the tape left and found again."""
    t = w.job.tape
    w.still, w.integrate = True, False
    assert w.until(lambda: t.uturn is not None, 3.0), w.job.reason
    base = w.counts
    for deg, sensor in ((40, NO_TAPE), (120, NO_TAPE), (176, CENTRED)):
        c = counts_for_angle(deg, PER_REV)
        w.counts = (base[0] + int(round(c)), base[1] + int(round(-c)))
        w.tick(sensor=sensor)
    w.drive(vehicle.U_TURN_RESUME_DELAY_S + 0.2, sensor=CENTRED)    # facing back along the tape
    assert t.uturn_req is None and w.job.state == lj.RUNNING, w.job.reason
    w.still, w.integrate = False, True


def parked_at(w, sid, seconds=200.0):
    """Drive until held at a station; returns the stop error (m)."""
    assert w.until(lambda: w.job.state == lj.HOLD, seconds), (w.job.reason, w.S)
    assert w.job.hold_cause == "station", w.job.reason
    assert w.job.tape.stop["tag"] == sid, w.job.tape.stop
    return w.S - w.at(sid)


def go_on(w):
    w.press_start()
    assert w.until(lambda: w.job.state == lj.RUNNING, 2.0), w.job.reason


def one_call():
    m = site(trip_calls=1)
    return TripWorld(m, graph(m))


def test_a_one_call_trip_stops_turns_mid_line_and_ends_at_home():
    w = one_call()
    assert w.job.trip_call("M1", w.t) == (True, "M1 called (M: 1 of 1)")
    w.start()
    assert w.job.trip.describe() == "M: M1, U-turn at UT-M1"
    w.drive(2.0)
    assert abs(w.job.diag["v_base"] - CRUISE) < 1.0, "the site's cruise, 0.4 m/s"
    for sid in ("ATT", "MW-1"):
        err = parked_at(w, sid)
        assert abs(err) < 0.05, f"{sid}: {err:+.3f} m"
        go_on(w)
    assert w.job.tape.branch.forks >= 1, "J-B taken with the armed order"
    # the U-turn point: a measured stop, then the pivot from the tape
    assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0), (w.job.reason, w.S)
    assert abs(w.S - w.route.uturn["S"]) < 0.05
    spin(w)
    assert w.job.tape.phase == "back"
    err = parked_at(w, "ME-1")
    assert abs(err) < 0.05
    go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), (w.job.reason, w.S)
    assert abs(w.S - w.route.S_end) < 0.05
    assert "served" in w.job.reason and w.job.trip is None
    log = " | ".join(text for _S, _sig, text in w.job.tape.decisions)
    assert "order RIGHT armed for J-B" in log and "order LEFT armed for J-C" in log
    ok, why = w.job.payload.may_leave()
    assert not ok and "confirm the trolleys are off" in why


def test_a_two_call_trip_turns_at_the_tape_end_when_its_machine_has_no_point():
    m = site(uturn_points={},
             groups={"M": {"circuit": "C-M", "machines": {"M1": {"release": "MW-1", "take": "ME-1"},
                                                          "M2": {"release": "MW-2", "take": "ME-2"}}}})
    w = TripWorld(m, graph(m, skip=("UT-M1", "UT-M2")))
    w.job.trip_call("M2", w.t)
    w.job.trip_call("M1", w.t + 1)
    w.start()
    assert w.job.trip.machines == ["M2", "M1"] and w.route.uturn["mode"] == "tapeend"
    for sid in ("ATT", "MW-1", "MW-2"):
        assert abs(parked_at(w, sid)) < 0.05
        go_on(w)
    assert w.until(lambda: (w.job.tape.uturn_req or {}).get("phase") == "approach", 60.0), w.job.reason
    assert w.until(lambda: w.job.tape.uturn_req["phase"] == "stopping", 30.0), (w.job.reason, w.S)
    w.still, w.integrate = True, False
    spin(w)
    for sid in ("ME-2", "ME-1"):
        assert abs(parked_at(w, sid)) < 0.05
        go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
    assert w.job.trip_note.endswith("served")


def test_high_inside_a_high_speed_area_and_back_to_the_cruise_before_it_ends():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    go = parked_at(w, "ATT")
    assert abs(go) < 0.05
    go_on(w)
    high = []
    while w.S < w.route.zones[0][1] + 0.5 and w.job.state == lj.RUNNING:
        w.tick()
        high.append((w.S, w.job.tape.high, w.job.diag.get("v_base", 0.0)))
    a, b, _z = w.route.zones[0]
    assert any(h for S, h, _v in high if a <= S < b), "HIGH granted inside the zone"
    assert not any(h for S, h, _v in high if S < a), "never before it"
    top = max(v for _S, _h, v in high)
    assert top > CRUISE + 100.0
    at_end = [v for S, _h, v in high if S >= b - 0.05]
    assert at_end and max(at_end) <= CRUISE + 15.0, "the envelope is back at the cruise by the zone end"


def log_of(w):
    return " | ".join(text for _S, _sig, text in w.job.tape.decisions)


def tape_end_world():
    m = site(uturn_points={}, trip_calls=1,
             groups={"M": {"circuit": "C-M", "machines": {"M1": {"release": "MW-1", "take": "ME-1"},
                                                          "M2": {"release": "MW-2", "take": "ME-2"}}}})
    return TripWorld(m, graph(m, skip=("UT-M1", "UT-M2")))


def drive_tape_end_trip(w, sigma, machine="M2", release="MW-2", take="ME-2"):
    """The MRU4 shape: the farthest machine, its U-turn at the tape end. Every stop, then HOME.
    A trip starts sure of HOME; sigma is what it has from the first metre on."""
    assert w.job.trip_call(machine, w.t)[0]
    w.start()
    w.sigma = sigma
    assert w.route.uturn["mode"] == "tapeend"
    for sid in ("ATT", release):
        parked_at(w, sid)
        go_on(w)
    assert w.until(lambda: (w.job.tape.uturn_req or {}).get("phase") == "approach", 60.0), w.job.reason
    assert w.until(lambda: w.job.tape.uturn_req["phase"] == "stopping", 30.0), (w.job.reason, w.S)
    w.still, w.integrate = True, False
    spin(w)
    parked_at(w, take)
    go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), (w.job.reason, w.S)


def test_a_whole_trip_runs_with_amcl_out_and_takes_every_branch():
    """2026-11-06: AMCL 12 cm off the taught path among moved trolleys stopped a trip on the tape."""
    w = tape_end_world()
    w.amcl_out = "5 corrections rejected in a row (+0.12 m from the taught path)"
    drive_tape_end_trip(w, 0.45)
    log = log_of(w)
    assert "order right taken at J-B" in log, log
    assert "order left taken at J-C" in log, log
    assert "HOLD" not in log and "best estimate" in log, log
    assert "served" in w.job.reason


def test_a_stop_goes_on_at_any_sigma_and_says_so():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    w.sigma = 0.3
    err = parked_at(w, "ATT")
    assert abs(err) < 0.05
    assert "best estimate, position uncertain by 30 cm" in log_of(w)


@pytest.mark.parametrize("bias", [-0.7, 0.0, 0.7])
def test_branches_are_right_with_s_wrong_inside_its_sigma(bias):
    """S up to 2.3 sigma off the tape, either way: the order still stands when the fork comes."""
    w = tape_end_world()
    w.job.trip_call("M2", w.t)
    w.start()
    w.sigma = 0.3
    parked_at(w, "ATT")
    w.bias = bias
    go_on(w)
    forks = w.job.tape.branch.forks
    assert w.until(lambda: w.job.tape.branch.forks == forks + 1, 60.0), (w.job.reason, w.S)
    w.drive(0.2)
    assert "order right taken at J-B" in log_of(w), log_of(w)
    assert w.job.tape.fault is None and w.job.state == lj.RUNNING, w.job.reason


def test_the_window_before_a_fork_grows_with_sigma():
    def armed_before_fork(sigma):
        w = one_call()
        w.job.trip_call("M1", w.t)
        w.start()
        parked_at(w, "ATT")
        w.sigma = sigma
        go_on(w)
        assert w.until(lambda: "armed for J-B" in log_of(w), 60.0), w.job.reason
        return next(n for n in w.route.nodes if n["id"] == "J-B")["S_fork"] - w.S

    assert 0.85 <= armed_before_fork(0.01) <= 1.0, "the lead"
    assert armed_before_fork(0.6) >= 1.7, "3 sigma"


def test_a_fork_seen_before_the_window_arms_the_order_and_counts_as_the_junction():
    """S behind the tape by more than its sigma says: the fork itself arms the order."""
    w = tape_end_world()
    w.job.trip_call("M2", w.t)
    w.start()
    parked_at(w, "ATT")
    w.bias = -1.5
    go_on(w)
    assert w.until(lambda: "armed for J-B" in log_of(w), 60.0), w.job.reason
    assert w.job.tape.branch.ladder.latched(), "armed while the fork is under the sensor"
    assert w.until(lambda: "at the fork seen before it" in log_of(w), 30.0), (log_of(w), w.job.reason)
    assert w.job.tape.fault is None and w.job.state == lj.RUNNING, w.job.reason
    assert not w.job.tape.branch.ladder.latched()


def test_a_fork_before_its_own_uses_the_order_and_it_is_armed_again():
    w = tape_end_world()
    w.job.trip_call("M2", w.t)
    w.start()
    w.sigma = 0.5
    parked_at(w, "ATT")
    S_fork = next(n for n in w.route.nodes if n["id"] == "J-B")["S_fork"]
    w.extra_fork = (S_fork - 3.5, S_fork - 3.2)
    go_on(w)
    assert w.until(lambda: "order right taken at J-B" in log_of(w), 60.0), (log_of(w), w.job.reason)
    assert "armed again" in log_of(w) and w.job.tape.branch.forks >= 2
    assert w.job.tape.fault is None


def test_an_order_with_no_fork_at_all_still_faults():
    w = tape_end_world()
    w.job.trip_call("M2", w.t)
    w.start()
    parked_at(w, "ATT")
    w.tape = lambda: CENTRED                        # no junction under the sensor
    go_on(w)
    assert w.until(lambda: w.job.state == lj.FAULT, 60.0), (w.job.reason, w.S)
    assert "not used" in w.job.reason, w.job.reason


def test_fork_watch_sees_which_tape_is_left():
    def run(order, multi, single):
        w = site_run.ForkWatch({"id": "J", "order": order}, True)
        for tracks, nlcp in multi:
            assert w.tick(nlcp, [{"pos_mm": p} for p in tracks]) is None
        out = None
        for _ in range(site_run.ForkWatch.SETTLE_TICKS):
            assert out is None
            out = w.tick(2, [{"pos_mm": single}])
        return out

    # Left ordered, the right tape leaves: the left tape is what stays.
    assert run("left", [((-20, 5), 3), ((-90, 2), 3)], 3)["verdict"] == "ordered"
    # 2026-11-06, J-SPLIT: the left tape runs off the sensor and the right one stays.
    r = run("left", [((-5, 20), 3), ((-30, 90), 3)], -32)
    assert r["verdict"] == "other" and r["kept"] == 90 and r["other"] == -30
    assert run("right", [((-90, 5), 3)], -88)["verdict"] == "ordered"
    assert run("right", [((-90, 5), 3)], 4)["verdict"] == "other"
    # A merge closes up; a tape reads double a few mm wide; a crossing has no side.
    assert run("left", [((-60, 0), 3), ((-8, 0), 3)], -4)["verdict"] == "unjudged"
    assert run("left", [((-2, 6), 3), ((-10, -4), 3)], -8)["verdict"] == "unjudged"
    assert run("left", [((-60, 0, 60), 7)], 0)["verdict"] == "unjudged"


def test_a_split_that_opens_with_three_tracks_is_still_judged():
    """The real J-SPLIT, from the trip log of 2026-11-06."""
    def run(single):
        w = site_run.ForkWatch({"id": "J-SPLIT", "order": "left"}, True)
        for nlcp, tracks in ((7, (-1, 7, 16)), (7, (-10, 9, 28)), (6, (-21, 42)), (6, (-56, 105))):
            w.tick(nlcp, [{"pos_mm": p} for p in tracks])
        out = None
        for _ in range(site_run.ForkWatch.SETTLE_TICKS):
            out = w.tick(2, [{"pos_mm": single}])
        return out["verdict"]

    assert run(100) == "ordered"
    assert run(-68) == "other"


def test_the_merge_before_the_real_split_is_not_the_split():
    """Tracks closing up (-123 to -3 mm) used the order 5 m early; a merge says nothing."""
    w = site_run.ForkWatch({"id": "J-SPLIT", "order": "left"}, True)
    for tracks in ((-123, 36), (-65, 27), (-21, 18), (-3, 11), (2, 9)):
        w.tick(3, [{"pos_mm": p} for p in tracks])
    out = None
    for _ in range(site_run.ForkWatch.SETTLE_TICKS):
        out = w.tick(2, [{"pos_mm": 7}])
    assert out["verdict"] == "unjudged"


def test_fork_watch_waits_out_a_flicker():
    w = site_run.ForkWatch({"id": "J", "order": "left"}, True)
    w.tick(3, [{"pos_mm": -40}, {"pos_mm": 40}])
    assert w.tick(2, [{"pos_mm": -40}]) is None and w.tick(2, [{"pos_mm": -40}]) is None
    w.tick(3, [{"pos_mm": -60}, {"pos_mm": 20}])    # two tracks again: not over
    for _ in range(2):
        assert w.tick(2, [{"pos_mm": 18}]) is None
    assert w.tick(2, [{"pos_mm": 18}])["verdict"] == "ordered"


def test_a_lost_ordered_tape_faults_at_the_fork_and_is_logged():
    w = tape_end_world()
    w.job.trip_call("M2", w.t)
    w.start()
    parked_at(w, "ATT")
    go_on(w)
    assert w.until(lambda: "armed for J-B" in log_of(w), 60.0), w.job.reason
    node = next(n for n in w.route.nodes if n["id"] == "J-B")
    plain = w.tape
    wrong = {"tracks": [{"index": 2, "pos_mm": 0, "width": 10}, {"index": 3, "pos_mm": 90, "width": 10}],
             "has_track": True, "nlcp": 6, "track_level": 5}
    gone = {"tracks": [{"index": 2, "pos_mm": 90, "width": 10}], "has_track": True, "nlcp": 2,
            "track_level": 5}
    # Ordered right, the kept (right-most) tape is the one at 0; only the +90 tape stays.
    w.tape = lambda: wrong if node["S_fork"] <= w.S < node["S"] else gone if w.S >= node["S"] else plain()
    assert w.until(lambda: w.job.state == lj.FAULT, 30.0), (w.job.reason, w.S)
    assert "wrong tape at J-B" in w.job.reason and w.S < node["S"] + 0.5, w.job.reason
    assert w.job.tape.fork_log[-1]["verdict"] == "other" or "wrong tape" in w.job.reason


def test_every_ordered_fork_of_a_good_trip_reports_the_ordered_tape():
    w = tape_end_world()
    drive_tape_end_trip(w, 0.01)
    log = log_of(w)
    assert "fork J-B: ordered right" in log and "fork J-C: ordered left" in log, log
    assert ": other" not in log, log


def test_two_orders_never_overwrite_each_other():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    t = w.job.tape
    t.locate(w.loc())
    S = t.S
    first = {"kind": "order", "id": "A", "order": "right", "S": S, "S_fork": S + 1.0, "S_node": S + 1.4,
             "S_prev": S - 1.0}
    second = {"kind": "order", "id": "B", "order": "left", "S": S, "S_fork": S + 2.0, "S_node": S + 2.4,
              "S_prev": S + 1.4}
    assert t._arm(first) and not t._arm(second) and t._armed is first


def test_a_mid_line_u_turn_uncertain_holds_once_and_start_is_the_word_to_pivot():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    for sid in ("ATT", "MW-1"):
        parked_at(w, sid)
        go_on(w)
    w.sigma = 0.3                                   # over sigma_junction_m (0.2)
    assert w.until(lambda: w.job.state == lj.HOLD, 60.0)
    assert w.job.hold_cause == "position" and "before UT-M1" in w.job.reason, w.job.reason
    assert w.S < w.route.uturn["S"]
    w.press_start()
    assert w.until(lambda: w.job.tape.uturn_req is not None, 40.0), w.job.reason
    assert w.job.hold_cause != "position"


def test_high_goes_by_sigma_and_amcl_being_out_is_no_veto():
    """2026-11-06: all 1427 running ticks of the first zone were held at the cruise by amcl_out."""
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    parked_at(w, "ATT")
    go_on(w)
    a = w.route.zones[0][0]
    w.amcl_out = "localization LOST"
    assert w.until(lambda: w.S >= a + 1.0, 60.0), w.job.reason
    assert w.job.tape.high, w.job.tape.high_why
    w.sigma = 0.3                                   # over sigma_junction_m
    w.drive(0.1)
    assert not w.job.tape.high and "uncertain" in w.job.tape.high_why


def test_a_release_not_recorded_holds_payload_at_the_u_turn_point():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    for sid in ("ATT", "MW-1"):
        parked_at(w, sid)
        go_on(w)
    w.job.trip.served.discard("MW-1")               # as if the release stop had not been served
    assert w.until(lambda: w.job.state == lj.HOLD, 60.0)
    assert w.job.hold_cause == "payload" and "release not recorded for M1" in w.job.reason, w.job.reason
    assert w.job.tape.uturn_req is None, "no pivot with a trolley attached"
    w.press_start()
    w.drive(1.5)                                    # past the pre-move warning
    assert w.job.state == lj.HOLD and w.job.hold_cause == "payload", "a Start alone does not pivot"
    ok, msg = w.job.confirm_released()
    assert ok and "Start" in msg
    go_on(w)
    spin(w)
    assert w.job.tape.phase == "back"


def test_a_wrong_branch_faults_and_aborts_the_trip():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    w.drive(1.0)
    w.wrong = "wrong branch at J-B: ordered right (J-B:right>U), the pose fits J-B:straight>X"
    w.tick()
    assert w.job.state == lj.FAULT and "wrong branch at J-B" in w.job.reason
    w.tick()
    assert w.job.trip is None and "ABORTED" in w.job.trip_note


@pytest.mark.parametrize("setup, needle", [
    (lambda w: None, "no trip formed: 1 call of one group needed"),
    (lambda w: (w.job.trip_call("M1", w.t), w.job.payload.trip_ended()), "confirm the trolleys are off"),
    (lambda w: (w.job.trip_call("M1", w.t), setattr(w, "S", 9.0)), "not at HOME (+4.00 m from it)"),
    (lambda w: (w.job.trip_call("M1", w.t), setattr(w, "lost", "3 corrections rejected")), "LOST"),
])
def test_a_trip_start_is_refused_until_everything_is_in_place(setup, needle):
    w = one_call()
    setup(w)
    w.press_start()
    assert w.job.state == lj.IDLE and needle in w.job.reason, w.job.reason


def test_an_untaught_trip_is_refused_and_its_calls_wait_again():
    m = site(trip_calls=1)
    w = TripWorld(m, graph(m, skip=("UT-M1",)))
    w.job.trip_call("M1", w.t)
    w.press_start()
    assert w.job.state == lj.IDLE and "not taught: U-turn point UT-M1" in w.job.reason, w.job.reason
    assert [mc for mc, _t in w.job.calls.pending] == ["M1"]


def test_reset_mid_trip_aborts_it():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    w.drive(1.0)
    w.tick(reset_edge=True)
    assert w.job.state == lj.IDLE and w.job.trip is None and "ABORTED (reset)" in w.job.trip_note


def test_a_trip_takes_no_hand_orders_and_no_forced_u_turn():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    assert not w.job.order_branch("left")[0]
    assert not w.job.force_u_turn(True)[0]
    snap = w.job.mission_snapshot()
    assert snap["mission"] == "t" and snap["trip"].startswith("M: M1")
    assert snap["trip_next"].startswith("stop ATT")


def test_the_site_mission_is_refused_as_a_job_without_the_live_engine():
    m = site()
    w = World(None)
    ok, msg = w.job.set_mission(m)
    assert not ok and "tape_loc.live" in msg


def test_home_start_window():
    assert site_run.HOME_START_M == 0.5


def test_home_shows_the_trip_predicate_in_a_site_mission():
    """Lean plan D144: the Home tile read NO with an empty detail in every site mission; it now
    says what a trip's Start checks (job._site_at_home)."""
    w = one_call()
    snap = lambda: w.job.mission_snapshot()  # noqa: E731
    w.tick()                                    # at HOME on the circuit
    assert snap()["at_home"] is True and w.job.at_home() == w.job._site_at_home(w.loc())
    w.S = 9.0                                   # off HOME
    w.tick()
    s = snap()
    assert s["at_home"] is False and s["home_detail"] == w.job._site_at_home(w.loc())[1] != ""
    w.lost = "no junction for 3 m"
    w.tick()
    s = snap()
    assert s["at_home"] is False and "LOST" in s["home_detail"]


def test_high_comes_back_on_the_return_through_the_same_zone():
    """HS-MRU, 2026-11-06: one zone covers both directions, and the U-turn took HIGH away from all of it."""
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    t = w.job.tape
    t.route.zones = [(0.0, 1e6, "Z")]
    parked_at(w, "ATT")
    go_on(w)
    parked_at(w, "MW-1")
    go_on(w)
    assert w.until(lambda: t.uturn_req is not None, 60.0), (w.job.reason, w.S)
    assert t._blocked == "Z" and not t.high, "the U-turn itself still drops it"
    spin(w)
    assert t._blocked is None
    settle_end = t.route.uturn["S"] + site_run.UTURN_SETTLE_M
    seen = []
    while w.job.state == lj.RUNNING and w.S < settle_end and len(seen) < 5000:
        w.tick()
        seen.append(t.high)
    assert not any(seen), "no HIGH while it straightens after the pivot"
    assert t._blocked is None, "and so nothing for the curve guard to trip on"
    parked_at(w, "ME-1")
    go_on(w)
    assert w.until(lambda: t.high, 30.0), (t.high_why, w.S)


def test_a_block_on_the_way_out_still_lasts_for_that_pass():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    t = w.job.tape
    t.route.zones = [(0.0, 1e6, "Z")]
    assert w.until(lambda: t.high, 30.0), (t.high_why, w.S)
    t.drop_high("a hold")
    w.drive(1.0)
    assert not t.high and "taken away" in t.high_why
