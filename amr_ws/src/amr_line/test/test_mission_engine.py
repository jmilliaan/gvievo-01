"""The mission engine on the line layer (schema v2, 2026-10-08: the RFID tag table).

The real job, follower and TapeRun, fed dataclass inputs; no ROS. The missions
are TEST documents validated by the real agv_core.mission.parse, shaped like the
site's table (missions/line-a.json): Home, an always-stop, a track-end U-turn,
a speed toggle and destination stops.
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
COUNTS_PER_MOTOR_REV = 10000.0
PER_REV = COUNTS_PER_MOTOR_REV * vehicle.GEAR_RATIO

HOME, TROLLEY, UTURN, TOGGLE = "0010", "0020", "0030", "0040"
MRU1, MRU2 = "0110", "0120"


def stop(tag, role, label, ignore_s=4):
    return {"tag": tag, "action": "stop", "ignore_s": ignore_s, "stop_distance_m": 0.5,
            "role": role, "label": label}


SITE_ROWS = [
    stop(HOME, "home", "Home", 2),
    stop(TROLLEY, "always", "Trolley release", 2),
    {"tag": UTURN, "action": "u_turn", "ignore_s": 2, "direction": "cw",
     "approach_mps": 0.1, "max_approach_m": 2.0},
    {"tag": TOGGLE, "action": "speed_toggle", "ignore_s": 5, "ramp_s": 2.0},
    stop(MRU1, "destination", "MRU1"),
    stop(MRU2, "destination", "MRU2"),
]


def doc(rows=(), **over):
    d = copy.deepcopy(missions.EMPTY)
    d["mission_name"] = "test"
    d["tags"] = copy.deepcopy(list(rows))
    d.update(over)
    return missions.parse(d)


SITE = doc(SITE_ROWS)


class World:
    """Clock, RFID stream and wheel feedback around one job.

    Wheel counts integrate the job's own command, so the travel-since-tag that
    proves "at Home" is the travel the vehicle actually made. The U-turn test
    drives the counts by hand instead (integrate=False).
    """

    def __init__(self, mission=None, destination=None):
        self.t = 100.0
        self.seq = 0
        self.gen = 0
        self.comms = True
        self.enc = []
        self.counts = (0, 0)
        self.integrate = True
        self.still = False
        self.job = lj.FollowJob(autopilot.LineFollower(), auto_start_delay_s=0.6)
        ok, why = self.job.set_mission(mission, destination)
        assert ok, why
        self.tick()  # the layer is up before anything is read, as on the vehicle

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
        left, right = self.job.tick(self.inputs(**over))
        if self.integrate:
            step = lambda rpm: int(round(rpm / 60.0 * 0.02 * COUNTS_PER_MOTOR_REV))  # noqa: E731
            self.counts = (self.counts[0] + step(left), self.counts[1] + step(right))
        return left, right

    def move(self, metres):
        """A manual jog: wheel travel the job did not command."""
        c = metres / (3.141592653589793 * vehicle.WHEEL_DIA_M) * PER_REV
        self.counts = (self.counts[0] + int(c), self.counts[1] + int(c))
        self.tick()

    def press_start(self):
        self.t += 0.1
        self.job.tick(self.inputs(start_edge=True, start_edge_t=self.t - 0.05))

    def start(self):
        self.press_start()
        assert self.job.state == lj.RUNNING, self.job.reason

    def drive(self, seconds, **over):
        for _ in range(int(seconds / 0.02)):
            self.tick(**over)

    def until(self, cond, seconds=10.0, **over):
        for _ in range(int(seconds / 0.02)):
            self.tick(**over)
            if cond():
                return True
        return False

    def park_at_home(self):
        """Jog over the Home tag in IDLE, as an operator would."""
        self.read(HOME)
        self.tick()
        self.move(0.2)
        assert self.job.at_home()[0], self.job.at_home()


def at_rest_stopped(w):
    return w.until(lambda: w.job.state != lj.RUNNING)


# -- plain line following --------------------------------------------------------

def test_no_mission_is_plain_line_following():
    w = World(None)
    w.start()
    w.read("0010")  # a tag means nothing without a mission
    w.drive(2.0)
    assert w.job.state == lj.RUNNING and w.job.tape.stop is None
    assert w.job.mission_snapshot()["mission"] == ""


def test_plain_line_following_does_not_need_the_rfid_link():
    w = World(None)
    w.start()
    w.comms = False
    w.drive(1.0)
    assert w.job.state == lj.RUNNING


# -- the job: destination and Home --------------------------------------------------

def test_a_destination_mission_refuses_start_without_a_destination():
    w = World(SITE)
    w.park_at_home()
    w.press_start()
    assert w.job.state == lj.IDLE and "no destination selected" in w.job.reason


def test_start_is_refused_away_from_home():
    w = World(SITE, "MRU2")
    w.press_start()
    assert w.job.state == lj.IDLE and "not at Home" in w.job.reason
    w.park_at_home()
    w.move(1.0)  # pushed off Home
    w.press_start()
    assert w.job.state == lj.IDLE and "moved" in w.job.reason


def test_an_unknown_destination_is_refused():
    w = World(SITE)
    ok, why = w.job.set_mission(SITE, "MRU9")
    assert not ok and "not a stop of this mission" in why
    ok, why = w.job.set_mission(None, "MRU1")
    assert not ok


def test_the_job_changes_only_in_idle_or_done():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.start()
    ok, why = w.job.set_mission(SITE, "MRU2")
    assert not ok and "clear first" in why
    w.job.clear()
    assert w.job.set_mission(SITE, "MRU2")[0]


def _run_to(w, seconds=3.0):
    w.drive(seconds)
    assert w.job.state == lj.RUNNING, w.job.reason


def _uturn(w):
    """From the U-turn tag: creep, tape ends, stop, pivot cw, reacquire, resume."""
    w.read(UTURN)
    w.tick()
    assert w.job.tape.uturn_req["phase"] == "approach"
    w.drive(2.0)  # down to the creep
    assert abs(w.job.diag["speed_target_rpm"] - 0.1 * vehicle.RPM_PER_MPS) < 1.0
    assert w.job.state == lj.RUNNING
    assert w.until(lambda: w.job.tape.uturn_req["phase"] == "stopping", 3.0, sensor=NO_TAPE), \
        "the end of the tape is the trigger"
    w.still = True
    w.integrate = False
    assert w.until(lambda: w.job.tape.uturn is not None, 3.0, sensor=NO_TAPE), w.job.reason
    base = w.counts
    for deg, sensor in ((40, NO_TAPE), (120, NO_TAPE), (175, CENTRED)):
        c = uturn.counts_for_angle(deg, PER_REV)
        w.counts = (base[0] + int(round(c)), base[1] + int(round(-c)))
        w.tick(sensor=sensor)
    assert w.job.tape.uturn.phase in (uturn.CENTER, uturn.SETTLE), w.job.tape.uturn.phase
    w.drive(vehicle.U_TURN_RESUME_DELAY_S + 0.2)
    assert w.job.tape.uturn_req is None and w.job.state == lj.RUNNING, w.job.reason
    w.still, w.integrate = False, True


def test_a_full_job_home_to_mru2_and_back():
    w = World(SITE, "MRU2")
    w.park_at_home()
    w.start()
    w.read(HOME)  # still in the field after Start
    w.tick()
    assert w.job.tape.stop is None and w.job.tape.last_encounter["action"] == "suppressed"
    _run_to(w)

    w.read(MRU1)
    w.tick()
    assert w.job.tape.stop is None, "not the destination: passed at speed"
    assert w.job.tape.last_encounter["action"] == "passed MRU1"

    w.drive(1.0)
    w.read(MRU2)
    w.tick()
    assert w.job.tape.stop["where"] == "MRU2"
    assert at_rest_stopped(w) and w.job.state == lj.HOLD and w.job.hold_cause == "station"
    w.drive(1.0)
    assert w.job.state == lj.HOLD, "only the physical Start moves it on"
    w.tick(start_edge=True, start_edge_t=w.t)
    w.drive(0.7)
    assert w.job.state == lj.RUNNING, w.job.reason
    _run_to(w)

    _uturn(w)
    _run_to(w, 1.0)
    w.read(MRU2)  # the return leg
    w.tick()
    assert w.job.tape.stop is None and "already served" in w.job.tape.last_encounter["reason"]
    w.drive(1.0)
    w.read(HOME)
    w.tick()
    assert w.job.tape.stop["role"] == "home"
    assert at_rest_stopped(w)
    assert w.job.state == lj.DONE and "MRU2 served" in w.job.reason, w.job.reason
    assert w.job.destination is None, "a finished job is spent"
    assert w.job.at_home()[0], w.job.at_home()

    w.press_start()
    assert w.job.state == lj.DONE and "no destination" in w.job.reason, "one PB press cannot repeat a job"
    assert w.job.set_mission(SITE, "MRU1")[0], "a new job is accepted at DONE"
    w.start()


def test_a_missed_destination_is_never_served_from_the_return_leg():
    w = World(SITE, "MRU2")
    w.park_at_home()
    w.start()
    _run_to(w)
    _uturn(w)  # MRU2's tag was never read outbound
    events = [text for _, text in w.job.tape.drain_events()]
    assert any("MRU2 not reached before the U-turn" in e for e in events)
    w.read(MRU2)
    w.tick()
    assert w.job.tape.stop is None
    w.drive(1.0)
    w.read(HOME)
    assert at_rest_stopped(w)
    assert w.job.state == lj.DONE and "MISSED" in w.job.reason


def test_the_always_stop_stops_every_pass():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.start()
    _run_to(w)
    w.read(TROLLEY)
    assert at_rest_stopped(w) and w.job.hold_cause == "station"
    assert w.job.mission_snapshot()["stop_where"] == "Trolley release"


def test_the_ignore_window_swallows_a_second_read():
    w = World(SITE, "MRU2")
    w.park_at_home()
    w.start()
    _run_to(w)
    w.read(MRU1)
    w.tick()
    w.drive(1.0)
    w.read(MRU1)  # a second distinct encounter inside the 4 s window
    w.tick()
    assert w.job.tape.last_encounter["action"] == "ignored"
    w.drive(3.5)
    w.read(MRU1)
    w.tick()
    assert w.job.tape.last_encounter["action"] == "passed MRU1", "the window expired"


# -- speed toggle --------------------------------------------------------------------

def test_a_speed_toggle_is_ramped_over_ramp_s():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.start()
    w.drive(4.0)
    assert w.job.diag["v_base"] == vehicle.AUTO_RPM
    w.read(TOGGLE)
    w.tick()
    assert w.job.diag["speed_target_rpm"] == vehicle.AUTO_SLOW_RPM
    w.drive(1.0)
    drop = vehicle.AUTO_RPM - w.job.diag["v_base"]
    full = vehicle.AUTO_RPM - vehicle.AUTO_SLOW_RPM
    assert 0.3 * full < drop < 0.7 * full, f"half way through a 2 s change, dropped {drop:.0f} of {full:.0f}"
    w.drive(1.5)
    assert w.job.diag["v_base"] == vehicle.AUTO_SLOW_RPM
    assert w.job.tape.speed_changing is False
    w.read(TOGGLE)  # inside the 5 s lockout
    w.tick()
    assert w.job.tape.speed.slow is True


# -- U-turn ----------------------------------------------------------------------------

def test_the_u_turn_tag_is_ignored_once_on_the_way_back():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.start()
    _run_to(w)
    w.read(MRU1)
    assert at_rest_stopped(w)
    w.tick(start_edge=True, start_edge_t=w.t)
    w.drive(0.7)
    _run_to(w)
    _uturn(w)
    assert w.job.tape.uturn_skip == UTURN
    w.t += 3.0  # past its ignore window: only the re-pass rule holds it
    w.read(UTURN)
    w.tick()
    assert w.job.tape.uturn_req is None and w.job.tape.last_encounter["action"] == "suppressed"


def test_the_tape_that_never_ends_faults_the_u_turn():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.start()
    _run_to(w)
    w.read(UTURN)
    assert w.until(lambda: w.job.state == lj.FAULT, 40.0), "max_approach_m bounds the creep"
    assert "did not end" in w.job.reason


def test_a_silent_sensor_on_the_approach_is_a_fault_not_a_tape_end():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.start()
    _run_to(w)
    w.read(UTURN)
    w.tick()
    w.tick(sensor_age_s=1.0)
    assert w.job.state == lj.FAULT and "sensor silent" in w.job.reason


def test_a_hold_during_the_u_turn_faults_rather_than_resuming_mid_manoeuvre():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.start()
    _run_to(w)
    w.read(UTURN)
    w.tick()
    w.tick(torque_off=True)
    assert w.job.state == lj.FAULT and "U-turn" in w.job.reason


# -- RFID continuity ---------------------------------------------------------------------

def test_rfid_link_loss_holds_for_a_person():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.start()
    _run_to(w)
    w.comms = False
    w.tick()
    assert w.job.state == lj.HOLD and w.job.hold_cause == "rfid", w.job.reason
    w.drive(1.0)
    w.tick(start_edge=True, start_edge_t=w.t)
    assert w.job.state == lj.HOLD, "Start is refused while the link is down"
    w.comms = True
    w.gen += 1
    w.enc = []
    w.drive(3.0)
    assert w.job.state == lj.HOLD, "the link coming back does not resume by itself"
    w.tick(start_edge=True, start_edge_t=w.t)
    assert w.job.state == lj.RUNNING, w.job.reason
    w.drive(0.5)
    assert w.job.state == lj.RUNNING, "a reconnect seen while held is not a second hold"


def test_an_encounter_gap_holds_the_vehicle():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.start()
    w.seq += 5  # entries never arrived
    w.enc.append((w.seq, MRU1))
    w.tick()
    assert w.job.state == lj.HOLD and w.job.hold_cause == "rfid" and "overrun" in w.job.reason


def test_rfid_loss_during_the_u_turn_is_a_fault():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.start()
    _run_to(w)
    w.read(UTURN)
    w.tick()
    w.comms = False
    w.tick()
    assert w.job.state == lj.FAULT and "U-turn" in w.job.reason


def test_start_needs_the_rfid_link_for_a_tag_mission():
    w = World(SITE, "MRU1")
    w.park_at_home()
    w.comms = False
    w.press_start()
    assert w.job.state == lj.IDLE and "RFID link down" in w.job.reason
