"""The mission engine on the line layer (2026-10-02): stop-and-go, the two tracked
speeds (cruise, slow zone), U-turn, RFID continuity. No ROS: the real job, follower and TapeRun, fed
dataclass inputs.

The missions here are TEST documents, built inline and validated by the real
agv_core.mission.parse - the repo ships no site mission.
"""
import copy
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
for _p in (ROOT, os.path.join(ROOT, "amr_ws", "src", "amr_line")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agv_core import config as vehicle  # noqa: E402
from agv_core import mission as missions  # noqa: E402

from amr_line import autopilot, runtime, uturn  # noqa: E402
from amr_line import job as lj  # noqa: E402

runtime.load_from_profile()

LEASE_LINE = 8
CENTRED = {"tracks": [{"index": 2, "pos_mm": 0, "width": 10}], "has_track": True, "nlcp": 2, "track_level": 5}
NO_TAPE = {"tracks": [], "has_track": False, "nlcp": 0, "track_level": 0}
PER_REV = 10000.0 * vehicle.GEAR_RATIO


def doc(**over):
    d = copy.deepcopy(missions.EMPTY)
    d["mission_name"] = "test"
    d.update(over)
    return missions.parse(d)


STATION = doc(stop_until_start_button=[{"tag": "0010", "stop_distance_m": 0.3, "direction": "outbound"}])
ZONES = doc(branch_latch=[{"entry_tag": "0020", "exit_tag": "0021", "branch": "left", "slow_speed": True}])
UTURN = doc(u_turn=[{"tag": "0030", "direction": "cw"}])


class World:
    """Clock, RFID stream and wheel feedback around one job."""

    def __init__(self, mission=None):
        self.t = 100.0
        self.seq = 0
        self.gen = 0
        self.comms = True
        self.enc = []
        self.counts = (0, 0)
        self.still = False
        self.job = lj.FollowJob(autopilot.LineFollower(), auto_start_delay_s=0.6)
        ok, _ = self.job.set_mission(mission)
        assert ok

    def rfid(self):
        return {"comms_ok": self.comms, "encounter_seq": self.seq, "generation": self.gen,
                "tag_age_s": None, "encounters": list(self.enc)}

    def read(self, tag):
        self.seq += 1
        self.enc.append((self.seq, tag))

    def inputs(self, **over):
        base = dict(
            now=self.t, dt=0.02, sensor=CENTRED, sensor_age_s=0.005, track_ok=True, track_cause="",
            panel_valid=True, panel_auto=True, start_edge=False, start_edge_t=None, reset_edge=False,
            lease_allowed=LEASE_LINE, lease_line=LEASE_LINE, authority=("sup", 1), torque_off=False,
            field_clear=True, drives_fresh=True, rfid=self.rfid(), counts=self.counts,
            counts_per_rev=PER_REV, wheels_still=self.still,
        )
        base.update(over)
        return lj.Inputs(**base)

    def tick(self, **over):
        self.t += 0.02
        return self.job.tick(self.inputs(**over))

    def start(self):
        self.t += 0.1
        self.job.tick(self.inputs(start_edge=True, start_edge_t=self.t - 0.05))
        assert self.job.state == lj.RUNNING, self.job.reason

    def drive(self, seconds, **over):
        for _ in range(int(seconds / 0.02)):
            self.tick(**over)


def test_no_mission_is_plain_line_following():
    w = World(None)
    w.start()
    w.read("0010")  # a tag means nothing without a mission
    w.drive(2.0)
    assert w.job.state == lj.RUNNING and w.job.tape.stop is None
    assert w.job.mission_snapshot()["mission"] == ""


def test_station_stop_then_go_on_start_after_the_delay():
    w = World(STATION)
    w.start()
    w.drive(3.0)  # up to cruise
    w.read("0010")
    w.tick()
    assert w.job.tape.stop is not None, "the station tag starts a measured stop"
    for _ in range(500):
        w.tick()
        if w.job.state == lj.HOLD:
            break
    assert w.job.state == lj.HOLD and w.job.hold_cause == "station", w.job.reason
    assert not w.job.auto_resume(), "a station waits for a person"
    w.drive(2.0)
    assert w.job.state == lj.HOLD, "nothing but Start moves it on"

    w.tick(start_edge=True, start_edge_t=w.t)
    assert w.job.state == lj.HOLD, "Start begins the delay, it does not move at once"
    w.drive(0.7)
    assert w.job.state == lj.RUNNING and w.job.tape.stop is None, w.job.reason

    w.read("0010")  # the tag just left, read again on the way out
    w.tick()
    assert w.job.tape.stop is None, "the departed tag does not stop it twice"
    assert w.job.tape.last_encounter["action"] == "suppressed"


def test_a_prerequisite_during_the_start_delay_cancels_it():
    w = World(STATION)
    w.start()
    w.drive(3.0)
    w.read("0010")
    for _ in range(500):
        w.tick()
        if w.job.state == lj.HOLD:
            break
    w.tick(start_edge=True, start_edge_t=w.t)
    w.tick(panel_auto=True, track_ok=False, track_cause="track")
    w.drive(1.0)
    assert w.job.state == lj.HOLD and "press Start" in w.job.reason


def test_two_tracked_speeds_cruise_then_slow_zone_then_cruise():
    w = World(ZONES)
    assert abs(vehicle.AUTO_RPM * vehicle.MPS_PER_RPM - 0.75) < 0.005, "tracked cruise is 0.75 m/s"
    assert vehicle.AUTO_SLOW_RPM == vehicle.AUTO_RPM * vehicle.AUTO_SLOW_RATIO, "slow is derived from cruise"
    assert vehicle.AUTO_SLOW_RATIO == 0.5, "tracked slow is 50% of cruise"
    w.start()
    w.drive(1.0)
    assert w.job.diag["speed_mode"] == "normal"
    assert w.job.diag["speed_target_rpm"] == vehicle.AUTO_RPM
    w.read("0020")
    w.tick()
    assert w.job.mission_snapshot()["slow_zone"] is True
    assert w.job.diag["speed_target_rpm"] == vehicle.AUTO_SLOW_RPM
    w.drive(1.0)
    w.read("0021")
    w.tick()
    assert w.job.mission_snapshot()["slow_zone"] is False
    assert w.job.diag["speed_target_rpm"] == vehicle.AUTO_RPM
    assert "high_speed" not in w.job.mission_snapshot()


def test_an_encounter_gap_is_an_overrun_and_ends_the_run():
    w = World(STATION)
    w.start()
    w.seq = 5  # entries 1..4 never arrived
    w.enc = [(5, "0010")]
    w.tick()
    assert w.job.state == lj.FAULT and "overrun" in w.job.reason


def test_a_reconnect_mid_run_warns_but_an_unguarded_run_goes_on():
    w = World(STATION)
    w.start()
    w.drive(0.5)
    w.gen, w.enc = 1, []
    w.tick()
    events = w.job.tape.drain_events()
    assert any("re-established" in text for _, text in events)
    assert w.job.state == lj.RUNNING


def _counts(deg):
    """Per-wheel counts for a cw pivot of `deg`: left forward, right back."""
    c = uturn.counts_for_angle(deg, PER_REV)
    return (int(round(c)), int(round(-c)))


def test_u_turn_stops_pivots_reacquires_centres_and_resumes():
    w = World(UTURN)
    w.start()
    w.drive(3.0)
    w.read("0030")
    w.tick()
    assert w.job.tape.uturn_req is not None
    for _ in range(500):
        w.tick()
        if w.job.diag.get("v_base") == 0:
            break
    w.still = True
    w.tick()
    assert w.job.tape.uturn is not None, w.job.reason
    left, right = w.tick()
    assert left > 0 > right or left < 0 < right, "a pivot: wheels opposed"

    for deg, sensor in ((40, NO_TAPE), (120, NO_TAPE), (175, CENTRED)):
        w.counts = _counts(deg)
        w.tick(sensor=sensor)
    assert w.job.tape.uturn.phase in (uturn.CENTER, uturn.SETTLE), w.job.tape.uturn.phase
    w.drive(vehicle.U_TURN_RESUME_DELAY_S + 0.2)
    assert w.job.tape.uturn_req is None and w.job.state == lj.RUNNING, w.job.reason
    assert w.job.tape.uturn_skip == "0030", "its own tag, re-read on the way out, is ignored once"


def test_a_hold_during_a_u_turn_faults_rather_than_resuming_mid_pivot():
    w = World(UTURN)
    w.start()
    w.drive(3.0)
    w.read("0030")
    w.tick()
    w.tick(torque_off=True)
    assert w.job.state == lj.FAULT and "U-turn" in w.job.reason


def test_the_mission_changes_only_while_idle():
    w = World(None)
    w.start()
    ok, why = w.job.set_mission(STATION)
    assert not ok and "clear first" in why
    w.job.clear()
    assert w.job.set_mission(STATION)[0]
