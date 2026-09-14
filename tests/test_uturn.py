"""Differential U-turn: encoder gate, tape reacquisition and centring.

Synthetic geometry only. The pivot model is the relation the line follower is
commissioned on: the tape crosses the sensor bar at p = -Ls*tan(yaw) about each
tape direction, so de/dt = Ls*omega at both 0 and 180 degrees.
"""
import copy
import json
import math
from unittest.mock import patch

from helpers import ROOT, check, mission_doc, parse, profile_doc
import canworker
import config
import events
import kinematics
import runlog
import server
import uturn

MOTOR_CPR = 36000                      # 608Fh default, per motor revolution
CPR = MOTOR_CPR * config.GEAR_RATIO    # per wheel revolution
MLS_HALF_MM = 50.0                     # synthetic visible half-width


def counts_at(angle_deg, direction):
    """Driver-term counts for a pure pivot of angle_deg in `direction`."""
    n = uturn.counts_for_angle(angle_deg, CPR)
    sign = -1 if direction == "cw" else 1
    left, right = -sign * n, sign * n
    return (round(-left if config.INVERT_LEFT else left),
            round(-right if config.INVERT_RIGHT else right))


def tape_error(yaw):
    """Follower-convention error (mm) of the nearest tape direction, or None."""
    rel = ((yaw + math.pi / 2) % math.pi) - math.pi / 2
    e = 1000.0 * config.SENSOR_LOOKAHEAD_M * math.tan(rel)
    return e if abs(e) <= MLS_HALF_MM else None


class Plant:
    """Ideal pivot: wheel r/min -> encoder counts and yaw."""

    def __init__(self):
        self.yaw, self.lc, self.rc = 0.0, 0.0, 0.0

    def step(self, left, right, dt):
        self.yaw += kinematics.wheels_to_body(left, right)[1] * dt
        self.lc += left / 60.0 * MOTOR_CPR * dt
        self.rc += right / 60.0 * MOTOR_CPR * dt

    @property
    def counts(self):
        return round(self.lc), round(self.rc)


def run_pure(direction, dt=0.02, steps=5000):
    plant, t = Plant(), uturn.UTurn(direction, CPR, (0, 0), 5)
    spin_cmds, center_cmds, settle_s, finished_settle = [], [], 0.0, None
    for _ in range(steps):
        before = t.phase
        left, right = t.update(plant.counts, tape_error(plant.yaw), 5, dt)
        if t.phase == uturn.SPIN:
            spin_cmds.append((left, right))
        elif t.phase == uturn.CENTER:
            center_cmds.append((left, right))
        if before == uturn.SETTLE:
            settle_s += dt
        if not t.active:
            finished_settle = settle_s
            break
        plant.step(left, right, dt)
    return t, plant, spin_cmds, center_cmds, finished_settle


def test_geometry_and_counts():
    print("\nU-turn geometry")
    n = uturn.counts_for_angle(180, CPR)
    want = config.TRACK_M / (2 * config.WHEEL_DIA_M) * CPR
    check("180 deg is track/(2*D) wheel turns of counts at 36,000 P/R x gear ratio",
          abs(n - want) < 1e-6 and 1.3e6 < n < 1.6e6, f"{n:.0f}")
    t = uturn.UTurn("ccw", CPR, (0, 0), 5)
    t.update(counts_at(180, "ccw"), None, 5, 0.02)
    check("encoder counts read back as a 180 deg pivot", abs(t.angle_deg - 180) < 1e-6,
          f"{t.angle_deg:.3f}")
    t = uturn.UTurn("cw", CPR, (0, 0), 5)
    t.update(counts_at(90, "cw"), None, 5, 0.02)
    check("clockwise travel is positive progress for a cw turn", abs(t.angle_deg - 90) < 1e-6)
    start = (2**31 - 100, -(2**31) + 100)
    check("INT32 wrap is the short way round",
          uturn.counts_delta(-(2**31) + 900, start[0]) == 1000
          and uturn.counts_delta(2**31 - 900, start[1]) == -1000)


def test_closed_loop_pivot():
    print("\nU-turn closed loop, both directions")
    for direction in ("ccw", "cw"):
        t, plant, spin, center, settle = run_pure(direction)
        e = tape_error(plant.yaw)
        check(f"{direction}: finishes centred on the far tape",
              t.phase == uturn.DONE and e is not None
              and abs(e) <= config.U_TURN_CENTER_TOL_MM, f"{t.phase} e={e} {t.reason}")
        check(f"{direction}: ends near 180 deg by encoder",
              170 <= t.angle_deg <= 190, f"{t.angle_deg:.1f}")
        check(f"{direction}: the tape left the sensor before reacquisition", t.lost)
        body = [kinematics.wheels_to_body(l, r) for l, r in spin]
        want = -1 if direction == "cw" else 1
        check(f"{direction}: pivots in place at auto_u_turn_rpm, correct way",
              all(abs(v) < 1e-9 and math.copysign(1, w) == want for v, w in body)
              and all(abs(abs(l) - config.AUTO_U_TURN_RPM) < 1e-6 for l, _ in spin))
        check(f"{direction}: centring never exceeds half spin speed",
              center and all(max(abs(l), abs(r)) <= config.AUTO_U_TURN_RPM / 2 + 1e-9
                             for l, r in center))
        check(f"{direction}: holds inside tolerance for the resume delay",
              settle is not None and settle >= config.U_TURN_RESUME_DELAY_S - 1e-9,
              f"{settle}")


def test_gates_and_failures():
    print("\nU-turn gates and failures")
    dt = 0.02

    def spun_to(t, deg, e, level=5):
        return t.update(counts_at(deg, t.direction), e, level, dt)

    t = uturn.UTurn("ccw", CPR, (0, 0), 5)
    spun_to(t, 10, 0.0)
    spun_to(t, 40, None)
    spun_to(t, 60, 5.0)
    check("tape seen before u_turn_min_deg is not the far side", t.phase == uturn.SPIN)
    spun_to(t, 160, 20.0, level=5 - config.U_TURN_LEVEL_TOLERANCE - 1)
    check("a much weaker track is not the tape the spin started on", t.phase == uturn.SPIN)
    spun_to(t, 165, 20.0, level=5 - config.U_TURN_LEVEL_TOLERANCE)
    check("a similar-strength track past the gate starts centring", t.phase == uturn.CENTER)

    t = uturn.UTurn("ccw", CPR, (0, 0), 5)
    spun_to(t, 40, None)
    spun_to(t, config.U_TURN_MAX_DEG + 1, None)
    check("no reacquisition by u_turn_max_deg faults",
          t.phase == uturn.FAILED and "not reacquired" in t.reason, t.reason)

    t = uturn.UTurn("ccw", CPR, (0, 0), 5)
    spun_to(t, 120, 0.0)
    spun_to(t, config.U_TURN_MAX_DEG + 1, 0.0)
    check("a tape that never left the sensor cannot end the pivot", t.phase == uturn.FAILED)

    t = uturn.UTurn("ccw", CPR, (0, 0), 5)
    t.update(counts_at(30, "cw"), 0.0, 5, dt)
    check("encoder travel against the command faults",
          t.phase == uturn.FAILED and "opposes" in t.reason, t.reason)

    t = uturn.UTurn("ccw", CPR, (0, 0), 5)
    for _ in range(int(t._budget_s / dt) + 2):
        t.update((0, 0), None, 5, dt)
    check("a frozen counter faults on the time budget",
          t.phase == uturn.FAILED and "exceeded" in t.reason, t.reason)

    t = uturn.UTurn("ccw", CPR, (0, 0), 5)
    spun_to(t, 40, None)
    left, right = spun_to(t, 170, 30.0)
    omega = kinematics.wheels_to_body(left, right)[1]
    check("centring turns against the error, like the follower's -K*e",
          t.phase == uturn.CENTER and omega < 0, f"omega={omega}")
    left, right = spun_to(t, 170, -30.0)
    check("and the other way for the opposite error",
          kinematics.wheels_to_body(left, right)[1] > 0)
    for _ in range(int(uturn.CENTER_LOST_S / dt) + 2):
        spun_to(t, 170, None)
    check("tape lost while centring faults rather than guessing",
          t.phase == uturn.FAILED and "centring" in t.reason, t.reason)

    t = uturn.UTurn("ccw", CPR, (0, 0), 5)
    spun_to(t, 40, None)
    spun_to(t, 178, 5.0)
    spun_to(t, 178, 5.0)
    spun_to(t, 178, 25.0)
    check("leaving the band during the delay re-enters centring", t.phase == uturn.CENTER)


def test_u_turn_configuration():
    print("\nU-turn configuration")
    check("the profile's U-turn tags load", config.U_TURN_TAGS == {"0030": "cw", "0031": "ccw"},
          str(config.U_TURN_TAGS))
    # U-turn tags are the mission's; the pivot's dynamics are the vehicle's.
    def refused(name, mutate, expect):
        profile, mission = profile_doc(), mission_doc()
        mutate(profile, mission)
        try:
            parse(profile, mission)
        except config.ConfigError as e:
            check(name, expect in str(e), str(e))
        else:
            check(name, False, "accepted")

    refused("the removed enabled key is refused",
            lambda p, m: m["u_turn"][0].update(enabled=True), "expected exactly")
    refused("direction must be cw or ccw",
            lambda p, m: m["u_turn"][0].update(direction="left"), "cw or ccw")
    refused("a station tag cannot also be a U-turn tag",
            lambda p, m: m["u_turn"][0].update(tag="0010"), "assigned to another rule")
    refused("a speed tag cannot also be a U-turn tag",
            lambda p, m: m["u_turn"][0].update(tag="0020"), "assigned to another rule")
    refused("a U-turn tag listed twice is refused",
            lambda p, m: m["u_turn"][1].update(tag="0030"), "listed twice")
    refused("min angle must stay short of 180",
            lambda p, m: p["autopilot"].update(u_turn_min_deg=180.0), "u_turn angles")
    refused("max angle must pass 180",
            lambda p, m: p["autopilot"].update(u_turn_max_deg=170.0), "u_turn angles")
    refused("a zero pivot speed is refused",
            lambda p, m: p["autopilot"].update(auto_u_turn_rpm=0.0), "auto_u_turn_rpm")
    refused("level tolerance is a 0-7 grade",
            lambda p, m: p["autopilot"].update(u_turn_level_tolerance=8), "0..7")
    data = server.app.test_client().get("/api/config").get_json()
    check("/api/config exposes the U-turn tags",
          data["u_turn"] == config.U_TURN_TAGS
          and data["auto_u_turn_rpm"] == config.AUTO_U_TURN_RPM)


class Bench:
    """A controller with the pivot plant behind its sensor and encoders."""

    def __init__(self, now):
        self.now = now
        c = self.c = canworker.Controller()
        c._log = runlog.RunLog(enabled=False)
        c._auto_running = True
        c._route.depart()
        c._departure_tag = None
        c._counts_per_wheel_rev = CPR
        self.plant = Plant()
        c._read_positions = lambda: self.plant.counts
        self.frame()
        self.drives()

    def frame(self):
        e = tape_error(self.plant.yaw)
        tracks = [] if e is None else [
            {"index": 2, "pos_mm": -e if config.INVERT_ERROR else e, "width": 20}]
        with self.c._lock:
            self.c._sensor = {"nlcp": len(tracks), "tracks": tracks,
                              "track_level": 5, "has_track": bool(tracks)}
            self.c._sensor_seen += 1
            self.c._sensor_last = self.now[0]

    def drives(self):
        zero = self.c._applied_zero if hasattr(self.c, "_applied_zero") else False
        for n in (config.LEFT, config.RIGHT):
            self.c._telemetry[n]["speed_zero"] = zero
            self.c._status_seen[n] = self.now[0]

    def scan(self, tag):
        # Numbered from the controller's own cursor: every tick resyncs it to
        # the (disconnected) reader, and a gap would read as a buffer overrun.
        seq = self.c._rfid_cursor + 1
        self.c._scan_route(dict(encounter_seq=seq, generation=self.c._rfid_generation,
                                comms_ok=True, tag_age_s=0, encounters=[(seq, tag)]))

    def tick(self, dt=0.02):
        self.now[0] += dt
        self.frame()
        # The drives report zero speed once the software reference has reached it.
        self.c._applied_zero = self.c._follower._v_rpm == 0 and self.c._target == (0, 0)
        self.drives()
        left, right = self.c._run_autopilot()
        self.plant.step(left, right, dt)
        return left, right

    def until(self, predicate, limit=4000):
        seen = []
        for _ in range(limit):
            seen.append(self.tick())
            if predicate():
                break
        return seen


def test_controller_u_turn():
    print("\nU-turn on the CAN thread")
    now = [500.0]
    with patch("canworker.time.monotonic", side_effect=lambda: now[0]), \
            patch("canworker.time.perf_counter", side_effect=lambda: now[0]):
        b = Bench(now)
        c = b.c
        c._follower._v_rpm = config.AUTO_RPM
        c._route.high = True
        b.scan("0031")
        check("a U-turn tag begins a measured stop, not a route event",
              c._uturn_req == {"tag": "0031", "direction": "ccw"}
              and c._follower._stop_rate is not None and c._route.current.id == "2")
        check("the U-turn tag leaves the high-speed latch alone", c._route.high)
        check("the processed encounter names the U-turn",
              c.snapshot()["route_display"]["last_encounter"]["action"] == "u-turn ccw")
        b.scan("0010")
        check("route tags are held off while a U-turn is in progress",
              c._stop_hold is None and c._route.current.id == "2"
              and c.snapshot()["route_display"]["last_encounter"]["action"] == "suppressed")
        check("the snapshot reports the stop before the pivot",
              c.snapshot()["u_turn"]["phase"] == "stopping"
              and c.snapshot()["u_turn"]["active"])

        cmds = b.until(lambda: c._uturn_req is None)
        last = c.snapshot()["u_turn"]
        e = tape_error(b.plant.yaw)
        check("the U-turn completes without a fault",
              last["phase"] == "done" and not last["active"] and not c._fault
              and c._auto_running, f"{last} fault={c._fault}")
        check("the vehicle ends 180 deg round, centred on tape",
              abs(math.degrees(b.plant.yaw) - 180) < 10 and e is not None
              and abs(e) <= config.U_TURN_CENTER_TOL_MM,
              f"yaw={math.degrees(b.plant.yaw):.1f} e={e}")
        spin = round(config.AUTO_U_TURN_RPM)
        check("the pivot was commanded at auto_u_turn_rpm, wheels opposed",
              any(abs(l) == spin and r == -l for l, r in cmds))
        check("no wheel moved before the drives reported standstill",
              c._uturn_last["angle_deg"] < 200)

        moving = b.until(lambda: False, limit=40)
        body = kinematics.wheels_to_body(*moving[-1])
        check("line following resumes forward after the delay",
              body[0] > 0 and abs(body[1]) < body[0] * 5, str(body))

        b.scan("0031")
        check("driving back over its own tag does not turn again",
              c._uturn_req is None
              and "passed after turning" in c.snapshot()["route_display"]["last_encounter"]["reason"])
        b.scan("0031")
        check("after that one pass the tag is armed again",
              c._uturn_req == {"tag": "0031", "direction": "ccw"})
    events.clear()


def test_controller_u_turn_failures():
    print("\nU-turn interruptions")
    now = [900.0]
    with patch("canworker.time.monotonic", side_effect=lambda: now[0]), \
            patch("canworker.time.perf_counter", side_effect=lambda: now[0]):
        b = Bench(now)
        c = b.c
        b.scan("0030")
        b.until(lambda: c._uturn is not None and c._uturn.angle_deg > 30)
        check("the pivot is under way", c._uturn is not None and c._uturn.phase == uturn.SPIN)
        c._auto_hold = "line lost"
        target = b.tick()
        check("a hold mid-pivot ends the run with a fault, never a resume",
              target == (0, 0) and not c._auto_running and c._uturn_req is None
              and "U-turn interrupted" in (c._fault or ""), str(c._fault))
        check("the last U-turn state is kept for the display",
              c.snapshot()["u_turn"]["reason"].startswith("U-turn interrupted"))

        b = Bench(now)
        c = b.c
        c._counts_per_wheel_rev = None
        b.scan("0030")
        b.until(lambda: not c._auto_running, limit=500)
        check("no encoder scale refuses to pivot, with the reason",
              "encoder scale" in (c._fault or "") and c._uturn is None, str(c._fault))

        b = Bench(now)
        c = b.c
        b.scan("0030")
        b.until(lambda: c._uturn is not None, limit=500)
        c._end_auto_run("stopped by Reset")
        check("Reset cancels a U-turn quietly, keeping why",
              c._uturn_req is None and not c._fault
              and c.snapshot()["u_turn"]["reason"] == "stopped by Reset")

        c = canworker.Controller()
        table = {(0x608F, 1): 36000, (0x608F, 2): 1, (0x6091, 1): 1, (0x6091, 2): 1}
        c._read = lambda nid, index, sub=0, **kw: table.get((index, sub))
        check("encoder scale is 608Fh x vehicle.gear_ratio",
              c._read_encoder_scale() == 36000 * config.GEAR_RATIO)
        table[0x6091, 1] = int(config.GEAR_RATIO)
        check("a drive that applies the same gear ratio agrees",
              c._read_encoder_scale() == 36000 * config.GEAR_RATIO)
        table[0x6091, 1] = 7
        check("a drive gear ratio that disagrees with the profile is refused",
              c._read_encoder_scale() is None)
        table[0x608F, 1] = None
        check("an unreadable resolution is refused", c._read_encoder_scale() is None)
    events.clear()


TESTS = [test_geometry_and_counts, test_closed_loop_pivot, test_gates_and_failures,
         test_u_turn_configuration, test_controller_u_turn,
         test_controller_u_turn_failures]
