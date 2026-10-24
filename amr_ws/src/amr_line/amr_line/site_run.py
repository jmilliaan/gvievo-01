"""The position engine: one trip driven from the tape locator (tracked plan 4, section 3). Pure.

SiteRun is a TapeRun (same surface for FollowJob: scan, steer, advance, stop, uturn_req and the
U-turn calls, speed, events, fault), so the job's measured stop, U-turn pivot, kink pivot,
post-U-turn search, holds and pre-move warning are the ones every run uses. What changes is
WHO decides: not RFID tags or marker strips, but the distance S along the trip's route
(amr_line.trip_route) from the locator, handed in each tick (locate()).

    stop       at S_stop - stop_distance_m: the measured stop over what is left (F1, F2). The
               locator must be within sigma_station_m there, else HOLD "position" before the
               station. At rest: HOLD "station"; the panel Start serves it (trip.serve) and
               departs. HOME ends the run (DONE, the trip's result)
    order      left/right for the next diverge, armed at S_fork - junction_lead_m and never
               before the previous node is passed (F3, site D15): sigma_junction_m or HOLD
               "position" before the fork. Still standing past the node: FAULT (the fork was
               not seen where it is taught)
    U-turn     mid-line: a measured stop at the point, then trip.may_pivot() (else HOLD
               "payload"), then the pivot from the tape (UTurn: leave it, reacquire it past the
               gyro gate). Tape end: may_pivot() and sigma_junction_m at S_end - lead_m, then
               the usual approach to where the tape ends (F5)
    speed      NORMAL = the site's cruise_mps. HIGH inside a zone [S_a, S_b) only while the
               locator is healthy (F4, no latching), under an envelope that is back at the
               cruise by every stop, U-turn, junction fork and zone end ahead (F6)
    wrong      the locator's wrong-branch latch: FAULT

Every doubt is a hold BEFORE the point, never motion. Nothing here starts, resumes or
speeds the vehicle on its own: the run is moving on AUTO + the physical Start, and every
decision is a slowdown, a stop or a refusal. Not in the safety path (plan section 6).
"""

import math

from agv_core import config as vehicle

from amr_line import branch
from amr_line.tape_run import INFO, WARN, TapeRun

# The envelope is back at the cruise this far before each point it protects.
ENVELOPE_MARGIN_M = 0.3
# A stop or U-turn reached below CREEP_FRACTION of the cruise - from rest after a hold or a
# resume - creeps at CREEP_MPS to within CREEP_STOP_M and stops measured over that: a measured
# stop solved at (near) 0 m/s, with the ramp still accelerating, runs on past the point
# (0.23 m in the closed-loop test). Within STOP_SNAP_M of the point it stops where it is.
CREEP_MPS = 0.1
CREEP_FRACTION = 0.8
CREEP_STOP_M = 0.05
STOP_SNAP_M = 0.03
# An armed order still standing this far past its node: the fork was not seen there.
ORDER_UNUSED_M = 1.0
# How close to the taught U-turn a tape end may come and still be it.
TAPE_END_MARGIN_M = 0.5
# A trip starts at HOME: the locator within this of HOME's taught S (job._site_at_home).
HOME_START_M = 0.5


class SiteRun(TapeRun):
    def __init__(self, site, trip, route, params, stop_distance_m=None):
        super().__init__(None)                      # no tags, no marker zone, no marker run
        self.site, self.trip, self.route, self.p = site, trip, route, params
        self.name = site["MISSION_NAME"]
        self.stop_distance_m = site["STOP_DISTANCE_M"] if stop_distance_m is None else stop_distance_m
        self.cruise = site["CRUISE_MPS"] * vehicle.RPM_PER_MPS
        self.creep = min(CREEP_MPS, site["CRUISE_MPS"]) * vehicle.RPM_PER_MPS
        # The envelope's deceleration: the HIGH<->NORMAL comfort rate (high_ramp_s).
        self.a_rpm_s = abs(vehicle.AUTO_HIGH_RPM - vehicle.AUTO_RPM) / vehicle.HIGH_RAMP_S
        self.loc = None
        self.v_rpm = 0.0
        self.hold_req = None                        # (cause, why) for the job, once
        self.phase = "out"
        self._next = 0                              # route.events cursor
        self._ceiling = self.cruise
        self._high = False
        self._blocked = None                        # zone id HIGH was taken away in
        self._creeping = None                       # the event a creep-up is for
        self._armed = None                          # the order event standing in the ladder
        self._step_ok = False
        self._multi_now = False
        self.decisions = []                         # (S, sigma, text): the trip's log
        self._slow = sorted(
            [e["S"] - self.stop_distance_m for e in route.events if e["kind"] == "stop"]
            + [self._trigger(e) for e in route.events if e["kind"] == "uturn"]
            + [n["S_fork"] for n in route.nodes if n["kind"] == "junction"]
            + [b for _a, b, _z in route.zones])
        self.events.append((INFO, f"trip {trip.describe()}: {len(route.stops) - 1} stops, "
                                  f"{sum(1 for e in route.events if e['kind'] == 'order')} orders"
                                  + (f"; {'; '.join(route.notes)}" if route.notes else "")))

    # -- inputs ------------------------------------------------------------------------
    def locate(self, loc, v_rpm=0.0):
        """This tick's locator state (the node's TapeRuntime.loc_state()) and last base speed."""
        self.loc = loc
        self.v_rpm = float(v_rpm or 0.0)

    @property
    def S(self):
        loc = self.loc
        return loc["S"] if loc and loc.get("started") and loc.get("route") == self.route.ident else None

    def _loc_why(self, limit):
        loc = self.loc
        if not loc or not loc.get("started"):
            return f"the tape locator is not running (At home at {self.site['HOME']})"
        if loc.get("route") != self.route.ident:
            return "the tape locator is not on this trip's route"
        if loc.get("lost"):
            return f"localization LOST ({loc['lost']})"
        if loc["sigma"] > limit:
            return f"position uncertain: sigma {loc['sigma']:.3f} m > {limit:g} m"
        return ""

    def _decide(self, text, level=INFO):
        loc = self.loc or {}
        S, sigma = loc.get("S", 0.0), loc.get("sigma", 0.0)
        self.decisions.append((S, sigma, text))
        self.events.append((level, f"{text} (S {S:.2f} m, sigma {sigma:.3f} m)"))

    def _hold(self, cause, why):
        if self.hold_req is None:
            self.hold_req = (cause, why)
            self._decide(f"HOLD {cause}: {why}", WARN)

    # -- surface FollowJob reads -----------------------------------------------------------
    @property
    def needs_link(self):
        return False

    @property
    def active(self):
        return True

    @property
    def cruise_rpm(self):
        return self._ceiling

    @property
    def high(self):
        return self._high

    @property
    def urgent_rate(self):
        return self.a_rpm_s if self.route.zones else None

    def change_rate(self):
        return self.a_rpm_s if self.route.zones else None

    def drop_high(self, reason, urgent=False):
        """A hold, the curve guard, stale inputs: no HIGH for the rest of this zone."""
        z = self._zone_at(self.S)
        if z is not None and self._blocked != z:
            self._blocked = z
            self.events.append((WARN if urgent else INFO, f"speed NORMAL for the rest of zone {z}: {reason}"))
        self._high = False

    def park_high(self, reason):
        pass                    # HIGH is where the AGV is, not a state to keep across a hold

    def resume_high(self):
        pass

    def parked(self, distance_m):
        pass

    def markers(self, reads, ok, driving, follower=None):
        pass                    # positions, not strips: no marker acts in a trip

    def order(self, side):
        return False, "a trip takes its branch orders from its route, not by hand"

    def force_u_turn(self, on):
        return False, "a trip turns where its route says (the U-turn point or the tape end)"

    def select_speed(self, high):
        return False, "a trip's speed comes from its zones"

    def result(self):
        return self.trip.result()

    # -- the tick ------------------------------------------------------------------------------
    def depart(self, now, rfid, resumed_tag=None):
        self.sync(rfid)
        st = self.stop
        if st is not None and st.get("role") in ("station", "attach"):
            self.trip.serve(st["tag"])
            work = ", ".join(f"{kind} {mc}" for mc, kind in self.trip.work(st["tag"]))
            work = work or st.get("plan_role", "stop")
            self._decide(f"left {st['tag']}: {work} done")
        self.stop = None
        nxt = next((e for e in self.route.events[self._next:] if e["kind"] in ("stop", "uturn")), None)
        if nxt is not None:
            self.events.append((INFO, f"next: {nxt['kind']} {nxt['id']} at S {nxt['S']:.2f} m"))

    def scan(self, now, rfid, driving, follower):
        self.sync(rfid)
        loc = self.loc or {}
        if loc.get("wrong_branch") and self.fault is None:
            self.fault = f"{loc['wrong_branch']}; MANUAL, jog back to the junction, Reset, Start"
            return []
        self._speed()
        if driving and self.stop is None and self.uturn_req is None and self.hold_req is None:
            self._order_check()
            if self.fault is None:
                self._events(follower)
        return []

    def steer(self, sensor, tags, followed_mm):
        from amr_line.tape_run import MULTI_NLCP  # noqa: PLC0415
        self._multi_now = (sensor or {}).get("nlcp") in MULTI_NLCP
        return super().steer(sensor, tags, followed_mm)

    def advance(self, distance_m):
        self._step_ok = distance_m is not None
        super().advance(distance_m)

    def _events(self, follower):
        S = self.S
        if S is None:
            self._hold("position", self._loc_why(self.p.sigma_junction_m))
            return
        while self._next < len(self.route.events):
            e = self.route.events[self._next]
            if S < self._trigger(e):
                return
            if e["kind"] == "order":
                if not self._arm(e):
                    return
            elif e["kind"] == "stop":
                if not self._begin_stop_at(e, follower, "home" if e["role"] == "home" else "station"):
                    return
            elif e["mode"] == "midline":
                if not self._begin_stop_at(e, follower, "uturn"):
                    return
            elif not self._tape_end_approach(e, follower):
                return
            self._next += 1

    def _trigger(self, e):
        if e["kind"] == "order":
            return e["S"]
        if e["kind"] == "uturn" and e["mode"] == "tapeend":
            return e["S"] - e["lead_m"]
        return e["S"] - self.stop_distance_m

    # -- orders ----------------------------------------------------------------------------
    def _arm(self, e):
        S = self.S
        if S >= e["S_fork"]:
            self.fault = (f"order {e['order']} for {e['id']} came due past its fork (S {S:.2f} m, fork at "
                          f"{e['S_fork']:.2f} m): the position jumped; check the AGV's branch, Reset")
            return False
        why = self._loc_why(self.p.sigma_junction_m)
        if why:
            self._hold("position", f"before {e['id']}: {why}")
            return False
        if self._multi_now:
            return False        # still on the previous node's tapes: arm once on one track
        self.branch.order(e["order"])
        self._armed = e
        self._decide(f"order {e['order'].upper()} armed for {e['id']}, fork in {e['S_fork'] - S:.2f} m")
        return True

    def _order_check(self):
        e = self._armed
        if e is None:
            return
        if self.branch.ladder.intent() == branch.STRAIGHT:
            self._armed = None
            self._decide(f"order {e['order']} taken at {e['id']}")
            return
        S = self.S
        if S is not None and S > e["S_node"] + ORDER_UNUSED_M:
            self.fault = (f"order {e['order']} for {e['id']} not used: no fork seen within "
                          f"{ORDER_UNUSED_M:g} m of where {e['id']} is taught; check the AGV's branch, Reset")

    # -- stops -----------------------------------------------------------------------------
    def _begin_stop_at(self, e, follower, role):
        S = self.S
        why = self._loc_why(self.p.sigma_station_m)
        if why:
            self._hold("position", f"before {e['id']}: {why}")
            return False
        left = e["S"] - S
        if self._creeping is not e and left > CREEP_STOP_M and self.v_rpm < CREEP_FRACTION * self.cruise:
            self._creeping = e      # from rest: creep up first
        if self._creeping is e and left > CREEP_STOP_M:
            return False
        rate = follower.begin_measured_stop(max(left, 0.01))
        if rate is None and left > STOP_SNAP_M:
            self._creeping = e      # the follower is at rest after all (a hold zeroed it)
            return False
        self._creeping = None
        self.stop = {"kind": "station", "tag": e["id"], "where": e["id"], "role": role,
                     "distance_m": left, "S_stop": e["S"], "plan_role": e.get("role", role)}
        what = {"home": "end of the trip", "uturn": "U-turn point"}.get(role, e.get("role", "stop"))
        self._decide(f"stopping at {e['id']} ({what}) over {left:.2f} m"
                     + (f" ({rate:.0f} r/min/s)" if rate else ""))
        return True

    def at_rest(self):
        """The measured stop has come to rest: "home", "station", "pivot" (the job carries on
        into the U-turn) or ("payload", why) - a hold."""
        st = self.stop
        S = self.S
        if S is not None and "S_stop" in st:
            self._decide(f"at rest at {st['tag']}, {100 * (S - st['S_stop']):+.0f} cm from it")
        role = st["role"]
        if role in ("home", "station"):
            return role
        ok, why = self.trip.may_pivot()
        if not ok:
            return ("payload", f"{why}: no U-turn; confirm the release on the Calls page or go back "
                               f"to the release stop")
        e = self.route.uturn
        self.stop = None
        if role == "uturn":
            self._turn(e, stopping=True)
        else:
            self._turn(e, stopping=False)
        return "pivot"

    # -- U-turns -----------------------------------------------------------------------------
    def _tape_end_approach(self, e, follower):
        why = self._loc_why(self.p.sigma_junction_m)
        if why:
            self._hold("position", f"before the U-turn {e['id']}: {why}")
            return False
        ok, _why = self.trip.may_pivot()
        if not ok:
            # Stop here and hold: at rest at_rest() asks again and approaches once it may.
            follower.begin_measured_stop(0.3)
            self.stop = {"kind": "station", "tag": e["id"], "where": e["id"], "role": "payload",
                         "distance_m": 0.3}
            return True
        self._turn(e, stopping=False)
        return True

    def _turn(self, e, stopping):
        sigma = (self.loc or {}).get("sigma", 0.0)
        row = {"tag": e["id"], "direction": e["direction"],
               "approach_mps": e.get("approach_mps", CREEP_MPS), "decel_m": e.get("decel_m", 0.3),
               "max_approach_m": e.get("lead_m", 0.0) + max(TAPE_END_MARGIN_M, 3.0 * sigma)}
        how = "here, from the tape" if stopping else "at the tape end"
        self._start_u_turn(row, f"U-turn {e['id']} ({how})")
        if stopping:
            self.uturn_req["phase"] = "stopping"
            self.uturn_req["level"] = self._level
        self._decide(f"U-turn {e['id']} {e['direction']}: "
                     + ("pivoting here" if stopping else "approaching the tape end"))

    def tape_ended(self):
        """The tape ended under a following AGV: the U-turn when it is the taught tape end."""
        if self.stop is not None or self.uturn_req is not None or self.phase != "out":
            return False
        e, S = self.route.uturn, self.S
        if e is None or e["mode"] != "tapeend" or S is None:
            return False
        sigma = (self.loc or {}).get("sigma", 0.0)
        if abs(e["S"] - S) > e["lead_m"] + max(TAPE_END_MARGIN_M, 3.0 * sigma):
            return False
        ok, why = self.trip.may_pivot()
        if not ok:
            self.fault = f"the tape ended before the U-turn approach and {why}; align, Reset"
            return False
        k = next(k for k, ev in enumerate(self.route.events) if ev["kind"] == "uturn")
        self._next = max(self._next, k + 1)
        self._turn(e, stopping=True)
        return True

    def turn_here(self):
        return False

    def continue_run(self):
        pass

    def finish_u_turn(self):
        super().finish_u_turn()
        self.phase = "back"
        self._decide("U-turn complete: inbound")

    # -- speed -------------------------------------------------------------------------------
    def _zone_at(self, S):
        if S is None:
            return None
        return next((z for a, b, z in self.route.zones if a <= S < b), None)

    def _speed(self):
        S = self.S
        cruise, ceiling = self.cruise, self.cruise
        if self._blocked is not None and self._zone_at(S) != self._blocked:
            self._blocked = None
        z = self._zone_at(S)
        healthy = not self._loc_why(self.p.sigma_junction_m)
        if z is not None and z != self._blocked and healthy and self._step_ok and self.stop is None \
                and self.uturn_req is None:
            ceiling = vehicle.AUTO_HIGH_RPM
            a = self.a_rpm_s * vehicle.MPS_PER_RPM
            v_c = cruise * vehicle.MPS_PER_RPM
            for p in self._slow:
                if p < S:
                    continue
                v = math.sqrt(v_c * v_c + 2.0 * a * max(0.0, p - S - ENVELOPE_MARGIN_M))
                ceiling = min(ceiling, v * vehicle.RPM_PER_MPS)
                if v * vehicle.RPM_PER_MPS >= vehicle.AUTO_HIGH_RPM:
                    break
        if self._creeping is not None:
            ceiling = min(ceiling, self.creep)
        self._ceiling = ceiling
        self._high = ceiling > cruise + 1.0

    # -- display ---------------------------------------------------------------------------
    def where(self):
        S = self.S
        return f"S {S:.2f} m ({self.route.where(S)})" if S is not None else "an unknown position"

    def next_event(self):
        """What comes next, for LineState: 'stop MW-1 in 3.2 m'."""
        S = self.S
        for e in self.route.events[self._next:]:
            what = f"{e['order']} at {e['id']}" if e["kind"] == "order" else f"{e['kind']} {e['id']}"
            return what.replace("uturn ", "U-turn ") + (f" in {e['S'] - S:.1f} m" if S is not None else "")
        return ""
