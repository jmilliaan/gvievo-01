"""Kink pivot (2026-10-23): grooved tape with corners and no radius (HOME complex,
deflections up to ~50 deg). The tape leaving the sensor at the EDGE is a corner: stop,
pivot toward it until centred, resume. Leaving near the CENTRE is still the tape end.

Closed loop: the real FollowJob and LineFollower drive a polyline tape plant (pose from
the wheels through the drive ramp, MLS window +/-100 mm, sensor 0.1 m ahead of the axle);
the encoder counts the job reads are the plant's own wheels."""
import math

from agv_core import config as vehicle  # noqa: E402
from agv_core import kinematics  # noqa: E402
from agv_core import mission as missions  # noqa: E402
from test_mission_engine import CENTRED, COUNTS_PER_MOTOR_REV, World  # noqa: E402

from amr_line import job as lj  # noqa: E402

DT = 0.02
HALF_M = 0.100
from line_fixtures import NO_TAPE  # noqa: E402


def kink(deg, lead=1.5, tail=2.5):
    """Tape along +x, turning by `deg` (positive left) at the origin."""
    a = math.radians(deg)
    return [(-lead, 0.0), (0.0, 0.0), (tail * math.cos(a), tail * math.sin(a))]


def jog(lateral=-0.380, along=0.550, lead=1.5, tail=2.5):
    """The HOME stem jog: two corners, 380 mm across over 550 mm (~35 deg each)."""
    return [(-lead, 0.0), (0.0, 0.0), (along, lateral), (along + tail, lateral)]


class Plant:
    """Differential base on polyline tape. Wheel speeds follow the command at the drive
    ramp; the MLS reports every tape crossing of its +/-100 mm window, positive left."""

    def __init__(self, path, x=-1.2):
        self.path, self.x, self.y, self.th = path, x, 0.0, 0.0
        self.l = self.r = 0.0
        self.counts = [0.0, 0.0]

    def step(self, lc, rc):
        acc, dec = (float(vehicle.RAMP["auto"][k]) * DT for k in ("accel", "decel"))

        def ramp(act, cmd):
            lim = dec if abs(cmd) < abs(act) else acc
            return act + max(-lim, min(lim, cmd - act))
        self.l, self.r = ramp(self.l, lc), ramp(self.r, rc)
        v, w = kinematics.wheels_to_body(self.l, self.r)
        self.x += v * math.cos(self.th) * DT
        self.y += v * math.sin(self.th) * DT
        self.th += w * DT
        self.counts[0] += self.l / 60.0 * DT * COUNTS_PER_MOTOR_REV
        self.counts[1] += self.r / 60.0 * DT * COUNTS_PER_MOTOR_REV

    @property
    def still(self):
        return abs(self.l) < 1.0 and abs(self.r) < 1.0

    def sensor(self):
        ls = vehicle.SENSOR_LOOKAHEAD_M
        sx, sy = self.x + ls * math.cos(self.th), self.y + ls * math.sin(self.th)
        nx, ny = -math.sin(self.th), math.cos(self.th)
        hits = []
        for (ax, ay), (bx, by) in zip(self.path[:-1], self.path[1:], strict=True):
            dx, dy = bx - ax, by - ay
            den = nx * dy - ny * dx
            if abs(den) < 1e-12:
                continue
            t = ((ax - sx) * dy - (ay - sy) * dx) / den
            u = ((sx - ax) * ny - (sy - ay) * nx) / (dx * ny - dy * nx)
            if 0.0 <= u <= 1.0 and abs(t) <= HALF_M:
                mm = round(t * 1000.0)
                if not any(abs(mm - h) < 30 for h in hits):    # one tape width: one track
                    hits.append(mm)
        if not hits:
            return NO_TAPE
        hits.sort(reverse=True)
        return {"tracks": [{"index": i + 2, "pos_mm": m, "width": 10} for i, m in enumerate(hits)],
                "has_track": True, "nlcp": 2 if len(hits) == 1 else 6, "track_level": 5}

    def off_tape_mm(self):
        """Axle distance to the tape's last leg, and heading error to it (deg)."""
        (ax, ay), (bx, by) = self.path[-2], self.path[-1]
        hd = math.atan2(by - ay, bx - ax)
        lat = (self.x - ax) * -math.sin(hd) + (self.y - ay) * math.cos(hd)
        err = (self.th - hd + math.pi) % (2 * math.pi) - math.pi
        return abs(lat) * 1000.0, abs(math.degrees(err))


def run(path, seconds=25.0, mission="c-mru-guided", hold_at=None):
    """Start on the tape before the corner and drive. Returns (world, plant)."""
    w = World(missions.load(mission) if mission else None)
    w.comms = False
    w.integrate = False
    p = Plant(path)
    w.start()
    held = False
    for _ in range(int(seconds / DT)):
        over = {}
        if hold_at is not None and not held and hold_at(w):
            held = True
            over = {"field_clear": False}
        left, right = w.tick(sensor=p.sensor(), **over)
        p.step(left, right)
        w.counts = (int(round(p.counts[0])), int(round(p.counts[1])))
        w.still = p.still
        if w.job.state not in (lj.RUNNING, lj.HOLD):
            break
        if p.x > path[-1][0] - 0.3 and abs(p.y - path[-1][1]) < 0.3:
            break
    return w, p


def ends_on_the_new_tape(w, p):
    lat_mm, err_deg = p.off_tape_mm()
    assert w.job.state == lj.RUNNING, w.job.reason
    assert lat_mm < 15.0 and err_deg < 5.0, (lat_mm, err_deg)


def test_a_mild_corner_is_followed_without_a_pivot():
    w, p = run(kink(-30.0))
    ends_on_the_new_tape(w, p)
    assert w.job.kinks == 0


def test_the_corners_the_follower_loses_are_pivoted_onto():
    # the pivot stops with the tape at +/-kink_stop_mm (75), not centred: a 60 deg corner
    # may lose the tape once more on the way out and take a second short pivot
    for deg, most in ((45.0, 1), (-45.0, 1), (50.4, 1), (-50.4, 1), (60.0, 2)):
        w, p = run(kink(deg))
        ends_on_the_new_tape(w, p)
        assert 1 <= w.job.kinks <= most, (deg, w.job.kinks)
        assert w.job.kink is None


def test_the_stem_jog_both_corners():
    w, p = run(jog())
    ends_on_the_new_tape(w, p)


def test_plain_following_at_normal_speed_too():
    w, p = run(kink(-45.0), mission=None)
    ends_on_the_new_tape(w, p)
    assert w.job.kinks == 1


def test_pivoting_is_reported_while_it_turns():
    w = World(missions.load("c-mru-guided"))
    w.comms = False
    w.start()
    w.drive(2.0)
    edge = {"tracks": [{"index": 2, "pos_mm": -95, "width": 10}], "has_track": True, "nlcp": 2,
            "track_level": 5}
    w.drive(0.1, sensor=edge)
    assert w.job.kink is None
    w.drive(0.1, sensor=NO_TAPE)
    assert w.job.pivoting and w.job.kink["direction"] == "cw"     # -95 mm: the tape is right
    assert w.job.diag["v_base"] == 0.0


def test_the_tape_end_near_the_centre_is_still_the_end():
    w = World(missions.load("c-mru-guided"))
    w.comms = False
    w.start()
    w.drive(2.0)
    w.drive(2.0, sensor=NO_TAPE)
    assert w.job.kinks == 0 and w.job.state == lj.DONE and "track lost" in w.job.reason


def test_a_one_tick_flicker_at_the_edge_is_not_a_corner():
    w = World(missions.load("c-mru-guided"))
    w.comms = False
    w.start()
    w.drive(2.0)
    edge = {"tracks": [{"index": 2, "pos_mm": 70, "width": 10}], "has_track": True, "nlcp": 2,
            "track_level": 5}
    w.drive(0.2, sensor=edge)
    w.tick(sensor=NO_TAPE)
    w.drive(0.5, sensor=edge)
    assert w.job.kinks == 0 and w.job.state == lj.RUNNING


def test_no_tape_within_kink_max_deg_faults_for_a_person():
    w = World(missions.load("c-mru-guided"))
    w.comms = False
    w.start()
    w.drive(2.0)
    edge = {"tracks": [{"index": 2, "pos_mm": 90, "width": 10}], "has_track": True, "nlcp": 2,
            "track_level": 5}
    w.drive(0.2, sensor=edge)
    w.drive(0.1, sensor=NO_TAPE)
    assert w.job.pivoting
    w.still = True                          # stopped; the counts now follow the spin command
    assert w.until(lambda: w.job.state != lj.RUNNING, 30.0, sensor=NO_TAPE)
    assert w.job.state == lj.FAULT and "kink" in w.job.reason, w.job.reason
    assert f"within {vehicle.KINK_MAX_DEG:.0f} deg" in w.job.reason and w.job.kink is None


def test_off_in_the_profile_is_the_old_behaviour():
    keep = vehicle.KINK_MAX_DEG
    try:
        vehicle.KINK_MAX_DEG = 0.0
        w, p = run(kink(50.4))
        assert w.job.kinks == 0 and w.job.state == lj.DONE and "track lost" in w.job.reason
    finally:
        vehicle.KINK_MAX_DEG = keep


def test_a_protective_stop_mid_pivot_resumes_the_search():
    def mid_pivot(w):
        k = w.job.kink
        return k is not None and k["turn"] is not None and k["turn"].angle_deg > 10.0
    w, p = run(kink(50.4), hold_at=mid_pivot, seconds=40.0)
    ends_on_the_new_tape(w, p)
    assert w.job.kinks == 1


def test_a_corner_on_the_u_turn_creep_is_not_the_tape_end():
    w = World(missions.load("c-mru-guided"))
    w.comms = False
    w.integrate = False
    p = Plant(kink(-50.4))                  # the corner 1.2 m ahead, inside max_approach_m
    w.start()
    w.job.tape._mrun_out_m = 50.0           # far from HOME-N: the code is the U-turn
    w.mark(3)
    after = None
    for n in range(int(40.0 / DT)):
        left, right = w.tick(sensor=p.sensor())
        p.step(left, right)
        w.counts = (int(round(p.counts[0])), int(round(p.counts[1])))
        w.still = p.still
        if after is None and w.job.kinks == 1 and w.job.kink is None:
            after = n
        if w.job.state != lj.RUNNING or (after is not None and n - after > 25):
            break
    assert w.job.kinks == 1 and w.job.state == lj.RUNNING, w.job.reason
    req = w.job.tape.uturn_req
    assert req is not None and req["phase"] == "approach", req
    assert p.sensor()["has_track"] and CENTRED["has_track"]


def test_a_pivot_sweep_is_no_junction_to_tape_localization():
    """The node feeds #LCP 0 while job.pivoting: the fork detectors (teach pass and shadow
    locator) hold their state, so a sensor sweeping two tape legs at a corner is no fork."""
    from amr_line import tape_graph as tg  # noqa: PLC0415

    sweep = [2, 6, 6, 2, 2]                 # what the MLS reports while the pivot crosses the corner
    raw, held = tg.ForkDetector(), tg.ForkDetector()
    eps_raw = [raw.update(0.0, n) for n in sweep] + [raw.update(0.2, 2)]
    eps_held = [held.update(0.0, 0) for _ in sweep] + [held.update(0.2, 2)]
    assert any(eps_raw), "without the hold the sweep would be a junction"
    assert not any(eps_held)


class Split(Plant):
    """J-SPLIT: the stem ends in two legs at +/-50.4 deg - a fork and a corner at once."""

    def __init__(self, deg=50.4, tail=2.0):
        a = math.radians(deg)
        self.legs = [[(-1.5, 0.0), (0.0, 0.0), (tail * math.cos(a), s * tail * math.sin(a))]
                     for s in (1.0, -1.0)]
        super().__init__(self.legs[0])

    def sensor(self):
        hits = []
        for leg in self.legs:
            self.path = leg
            for t in Plant.sensor(self)["tracks"]:
                if not any(abs(t["pos_mm"] - h) < 30 for h in hits):
                    hits.append(t["pos_mm"])
        if not hits:
            return NO_TAPE
        hits.sort(reverse=True)
        return {"tracks": [{"index": i + 2, "pos_mm": m, "width": 10} for i, m in enumerate(hits)],
                "has_track": True, "nlcp": 2 if len(hits) == 1 else 6, "track_level": 5}


def test_the_split_takes_the_ordered_leg_and_spends_the_order():
    from amr_line import branch  # noqa: PLC0415

    for side, sign in (("left", 1.0), ("right", -1.0)):
        w = World(missions.load("c-mru-guided"))
        w.comms = False
        w.integrate = False
        p = Split()
        w.start()
        assert w.job.order_branch(side)[0]
        for _ in range(int(25.0 / DT)):
            left, right = w.tick(sensor=p.sensor())
            p.step(left, right)
            w.counts = (int(round(p.counts[0])), int(round(p.counts[1])))
            w.still = p.still
            if w.job.state != lj.RUNNING or p.x > 1.0:
                break
        assert w.job.state == lj.RUNNING, w.job.reason
        assert sign * p.y > 1.0 and abs(math.degrees(p.th) - sign * 50.4) < 5.0, (side, p.y, p.th)
        assert w.job.tape.branch.ladder.intent() == branch.STRAIGHT and w.job.tape.branch.forks == 1
