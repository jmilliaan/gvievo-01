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
CRUISE = 0.4 * vehicle.RPM_PER_MPS


class TripWorld(World):
    def __init__(self, m, g, sigma=0.01, params=None):
        self.m, self.g = m, g
        self.sigma, self.lost, self.wrong = sigma, "", ""
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
        home = min((self.S - r.S_start, self.S - r.S_end), key=abs) if r else self.S - 5.0
        return {"route": ident, "started": True, "S": self.S, "sigma": self.sigma, "health": "HEALTHY",
                "lost": self.lost, "wrong_branch": self.wrong, "home_offset": home}

    def tape(self):
        r = self.route
        if r is None:
            return CENTRED
        for n in r.nodes:
            if n["fork"] and n["S_fork"] <= self.S < n["S"]:
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


def test_doubt_before_a_stop_holds_before_it_and_start_rechecks():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    w.sigma = 0.08                                  # over sigma_station_m (0.025)
    assert w.until(lambda: w.job.state == lj.HOLD, 60.0)
    assert w.job.hold_cause == "position" and "before ATT" in w.job.reason, w.job.reason
    assert w.S < w.at("ATT"), "held before the station"
    w.press_start()                                 # still uncertain: held again at once
    w.until(lambda: w.job.state == lj.HOLD and w.job.hold_cause == "position", 3.0)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "position"
    w.sigma = 0.01
    go_on(w)
    err = parked_at(w, "ATT", 30.0)                 # creeps up from rest, then the measured stop
    assert abs(err) < 0.05


def test_doubt_before_a_diverge_holds_before_the_fork():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    parked_at(w, "ATT")
    go_on(w)
    w.sigma = 0.3                                   # over sigma_junction_m (0.2)
    assert w.until(lambda: w.job.state == lj.HOLD, 60.0)
    assert w.job.hold_cause == "position" and "before J-B" in w.job.reason, w.job.reason
    fork = next(n for n in w.route.nodes if n["id"] == "J-B")["S_fork"]
    assert w.S < fork


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
