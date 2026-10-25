"""Line-follow authority and state machine. No ROS, no clock, no I/O.

The same split `amr_base/commissioning.py` uses, and for the same reason: the
decisions here are the ones worth testing, and a test that needs a ROS graph
does not get run. The node marshals messages, stamps freshness and owns the
clock; this file decides whether the vehicle may move and hands back a wheel
command. Everything it knows arrives in a frozen `Inputs`.

STATE VALUES ARE ON THE WIRE. They are LineState.msg's constants, and
readiness.py holds `_line_active_locked` as `line_state in (1, 2, 3)` - ARMED,
RUNNING, HOLD. mode_fsm refuses to leave LINE while that is true. Renumbering
these silently breaks the guard that stops a layer swap under a moving
vehicle, so the constants are asserted against the message in the node.

ARMED IS THE PRE-MOVE WARNING (2026-10-08). The drives are no longer powered
while idle. Every move that follows an operator's Start - a run from IDLE/DONE,
a station departure, a resume from a hold that waited for Start - first enters
ARMED: wants_power() asks drive_node for power, the panel sounds the alarm horn,
and the job goes RUNNING only once premove_s has passed AND the drives report
torque. A prerequisite lapsing (debounced like the rest; a violated field at
once) cancels back to where the Start came from, as does premove_timeout_s
without torque ("drives did not power up"). Holds that resume by themselves
keep their power and do not repeat the warning: nobody pressed anything.

WHAT HOLDS THE VEHICLE, and how each resumes:

  field       protective field violated (/output_paths): resumes by itself
  estop       drive torque gone with the field clear: needs a physical Start,
              unless auto_resume_estop
  drives      wheel feedback or drive report went stale while running: stops
              at once, resumes by itself once feedback is back
  track       no usable tape reading: the ENGINE owns the grace distance, so
              this hold is only for a reading that never arrives at all
  rate        samples are fresh but too slow, or the MLS fell back to SDO.
              sensor_timeout_s cannot see this - see track.TrackReader
  rfid        the RFID stream broke while driving (link down, reconnect,
              buffer overrun) on a mission with tags: a station or the U-turn
              may have been driven past. Needs a physical Start once the link
              is back; during a U-turn it is a FAULT like any other hold
  markers     a marker run (mission marker_run) lost its MLS marker stream, or marker
              events, while driving: the home stop may have been driven past. Needs a
              physical Start once the stream is back (2026-10-18)
  station     parked at a stop: a physical Start, then the pre-move warning
  position    a trip (the position engine, amr_line.site_run): the tape locator was not sure
              enough where the AGV is before a stop, an order or the U-turn. Held BEFORE the
              point; a physical Start re-checks (tracked plan 4, 2026-10-24)
  payload     a trip at its U-turn with a release not recorded: no pivot with a trolley
              attached. The Calls page's "released" confirmation, then a physical Start
  authority   lease, generation or panel selector changed under the run.
              Never auto-resumes: something above this layer took control.
              An explicit act - the selector leaving AUTO on a valid panel,
              LEASE_LINE withdrawn from a fresh lease, the lease replaced -
              ends the run at once (FAULT, Reset to clear), as the executor's
              manual takeover does. A MISSING signal (stale panel, stale
              lease) is a comms question and goes through the debounce

The asymmetry between debounced and immediate is deliberate and copied from
the executor: a prerequisite must fail CONTINUOUSLY for prereq_grace_s before
it faults, so one dropped frame never latches, but anything that means the
vehicle is moving without proper feedback stops on the first tick. Delaying a
stop is the wrong direction.
"""
import dataclasses

from amr_base import hold_policy, wire
from amr_line import marker_reader, tag_table

# LineState.msg, and not free to change - see the module docstring.
IDLE, ARMED, RUNNING, HOLD, DONE, FAULT = 0, 1, 2, 3, 4, 5

STATE_NAMES = wire.LINE_NAMES

# Holds that clear themselves once the cause does. "estop" joins this set only
# when auto_resume_estop is set, matching the executor's operator decision of
# 2026-09-19 that an E-stop recovery is a deliberate human act.
_AUTO_CAUSES = ("field", "drives", "rate", "track")
# Holds that keep HIGH for the resume (2026-10-09): the protective field (a
# person stepped in) and the RFID link (no RFID event may change the speed).
_PARK_CAUSES = ("field", "rfid")
# An "estop" hold parks HIGH too, and decides at the resume (2026-10-23, operator:
# a protective stop must not reset HIGH). A protective trip removes torque through the
# FX3, and the drive report can arrive before /output_paths shows the field: the tick then
# sees torque off with the field still clear and calls it an E-stop. A field violation
# reported within FIELD_RACE_S of such a hold proves it was the protective field, and the
# resume restores HIGH; otherwise it was a real E-stop and the resume departs NORMAL.
# Only the speed is decided here: the hold keeps its E-stop terms (a physical Start).
_PARKS_HIGH = _PARK_CAUSES + ("estop",)
FIELD_RACE_S = 0.5
# Kink pivot (see _kink_begin): ticks without tape before a corner is called (a one-tick
# flicker at the sensor's edge is not one), and the least angle worth searching after a
# hold took the rest of kink_max_deg.
KINK_GONE_TICKS = 2
KINK_MIN_LEFT_DEG = 10.0
# The kink pivot stops inside kink_stop_mm, not centred: settle only long enough for the
# wheels to come to rest, then the follower steers the rest.
KINK_SETTLE_S = 0.3
# Right after a U-turn the tape may drop out near the centre (2026-10-24 14:08: gone 0.94 s
# after "U-turn complete" at the MRU end, track level 3, then seen again at rest at -56 mm).
# Within this much travel after the pivot, ANY loss is handled like a kink: stop, re-read,
# pivot toward the side it was last seen if it is not in view, FAULT if it is not found -
# never the silent end of the run.
POST_UTURN_M = 1.0


@dataclasses.dataclass(frozen=True)
class Inputs:
    """One tick's worth of the world. Booleans are already ANDed with
    freshness by the node, so nothing here has to know what time it is."""

    now: float
    dt: float

    # sensor
    sensor: dict                     # the engine's track dict
    sensor_age_s: float              # decode-to-now, not publish-to-now
    track_ok: bool                   # usable: fresh, fast enough, tpdo
    track_cause: str                 # "" when track_ok

    # authority
    panel_valid: bool
    panel_auto: bool                 # LINE lives on the AUTO side of gating
    start_edge: bool
    start_edge_t: float | None
    reset_edge: bool
    lease_allowed: int               # ControlLease.allowed bitmask
    lease_line: int                  # ControlLease.LINE bit
    authority: tuple[str, int] | None  # (instance, generation)

    # safety chain
    torque_off: bool
    field_clear: bool | None       # None = no fresh /output_paths: UNKNOWN, not clear
    drives_fresh: bool

    # mission engine (2026-10-02). Defaults keep plain line following, and every
    # caller that predates the engine, unchanged.
    rfid: dict | None = None         # agv_core.drivers.rfid snapshot(encounters=True)
    counts: tuple | None = None      # (left, right) 6064h from /wheel_states, driver terms
    counts_per_rev: float = 0.0      # /wheel_states counts_per_wheel_rev; 0 = unknown
    wheels_still: bool = False       # both wheels below the stillness threshold, fresh
    # tracked-speed-plan-1 (2026-10-08). None = not fresh. HIGH needs both: the curve
    # guard's inputs. yaw from the gyro (odometry when the gyro is stale), v from odometry.
    yaw_rate: float | None = None    # rad/s, vehicle frame
    v_meas: float | None = None      # m/s, wheel odometry
    warning_scale: float = 1.0       # the mux's applied warning-field factor (/amr/mux_state)
    # MLS markers (mls-marker-plan, 2026-10-09): the /amr/line_marker snapshot, or None.
    # Logged in every state; the mission's high-zone codes set the speed while RUNNING
    # (TapeRun.markers). No marker changes the job's state.
    markers: dict | None = None
    # The tape locator (tracked plan 4): TapeRuntime.loc_state(), or None. Only a trip acts on
    # it; a Start of a trip needs it at HOME and healthy.
    loc: dict | None = None


class FollowJob:
    """Arm, run, hold, stop. Owns the engine; the node owns the messages."""

    def __init__(self, follower, *, prereq_grace_s=0.5, auto_resume_clear_s=2.0,
                 auto_resume_estop=False, premove_s=0.0, premove_timeout_s=8.0):
        self.f = follower
        self.prereq_grace_s = float(prereq_grace_s)
        self.auto_resume_clear_s = float(auto_resume_clear_s)
        self.auto_resume_estop = bool(auto_resume_estop)
        # The pre-move warning (timing.auto_start_delay_s) and how long it waits for torque.
        self.premove_s = max(0.0, float(premove_s))
        self.premove_timeout_s = max(self.premove_s, float(premove_timeout_s))
        # The mission the next run uses (agv_core.mission.load output), or None for
        # plain line following. Set only while IDLE - see set_mission().
        self.mission = None
        # The job's destination (a mission DESTINATIONS label), or None. Cleared
        # when a run ends at Home, so one PB press cannot repeat a finished job.
        self.destination = None
        self.result = ""            # how the last run ended at Home, for the operator
        # The guided page's speed toggle (2026-10-24): kept across runs, NORMAL again at every
        # mission load and node start. Each fresh TapeRun takes it over (_new_tape).
        self.high_select = False
        self.tape = None
        # Last tag and the travel since it: survives runs and mission changes.
        self.odometer = tag_table.TagOdometer()
        # Marker codes read by the MLS: counted and logged in every state; this tick's new
        # ones go to the speed zone while RUNNING, and are dropped in any other state.
        self.markers = marker_reader.MarkerReader()
        self._marker_new: list = []
        self.markers_ok = False
        self._marker_log = []
        # The position engine (tracked plan 4). Off (None) unless the node configures it
        # (tape_loc.live): then a site mission is a job, its trips form from machine calls.
        self._site_cfg = None       # {"params", "compile"}: locator limits, trip -> TripRoute
        self.site = None            # the parsed site mission while it is the job
        self.calls = None           # trip.CallQueue
        self.payload = None         # trip.Payload: "trolleys off at HOME", survives trips
        self.trip = None            # the trip being driven
        self.trip_route = None
        self.trip_new = None        # a route the node must seed the locator on, once
        self.trip_note = ""         # how the last trip ended
        self.reset()

    # -- lifecycle ---------------------------------------------------------
    def reset(self):
        self.state = IDLE
        self.hold_cause = ""
        self._hold_since = None     # first tick of the current hold
        self._estop_was_field = False  # this "estop" hold saw the field within FIELD_RACE_S
        self.reason = ""
        self.accepted_t = None      # when the Start that began this run was accepted
        self.refused = None         # why the last Start was refused, until the node reports it
        self._binding = None        # (instance, generation) the run belongs to
        self._loc = None            # the latest tape-locator snapshot (Inputs.loc), for at_home()
        self._prereq = hold_policy.Debounce()
        self._auto_since = None
        self._resume_pending = False
        # The engine has no run odometer - _track_gap_m is distance since the
        # tape was last seen, which is a different question. Integrated here.
        self.followed_m = 0.0
        self._resume_at = None
        self._premove = None        # {"kind", "since", "back"} while ARMED
        self.diag = {}
        self._counts_ref = None     # encoder counts at the last tick, for wheel travel
        self.step_m = None          # wheel travel this tick, None when counts are unavailable
        self.kink = None            # the kink pivot in progress, see _kink_begin()
        self.kinks = 0              # kink pivots this run
        self._edge_gone = 0         # ticks the tape has been gone after leaving at the edge
        self.ended_at_end = False   # DONE "track lost": the guide page may force the U-turn there
        self._post_uturn_m = None   # travel since the last U-turn, while under POST_UTURN_M
        self.continue_armed = False  # guide page: the next Start continues this run (same phase)
        self._end_gone = 0          # ticks the tape has been gone with a U-turn read pending
        if self.trip is not None:
            self._trip_abort("reset")
        self.tape = self._new_tape()
        self.f.reset()

    def _new_tape(self):
        """A fresh mission state for one run: stage, latches and cursor start over."""
        from amr_line.tape_run import TapeRun  # noqa: PLC0415  (profile-dependent)

        if self.site is not None:
            if self.trip is None:
                return TapeRun(None)            # between trips: nothing to act on
            from amr_line.site_run import SiteRun  # noqa: PLC0415
            return SiteRun(self.site, self.trip, self.trip_route, self._site_cfg["params"])
        t = TapeRun(self.mission, self.destination)
        if t.high_select is not None:
            t.high_select = self.high_select
        return t

    def order_branch(self, side):
        """The engineer's branch order (guided mission). Returns (ok, message). Chooses a tape
        at the next fork only; it never starts, resumes or speeds anything."""
        if self.tape is None:
            return False, "no mission loaded"
        return self.tape.order(side)

    def force_u_turn(self, on):
        """The guide page's fallback: the next tape end is the U-turn. Returns (ok, message).
        Running: it changes what the tape end means. DONE at the tape end on the way out: the
        NEXT physical Start pivots there instead of starting a new run. It never starts,
        resumes or speeds anything by itself."""
        if self.tape is None:
            return False, "no mission loaded"
        if not (self.tape.guided and self.tape.mrun):
            return self.tape.force_u_turn(on)       # refused there, with the reason
        if self.state == DONE:
            if not self.ended_at_end:
                return False, "the run is over: a forced U-turn only while running or at the tape end"
            ok, msg = self.tape.force_u_turn(on)
            if ok and on:
                msg = (f"U-turn armed at the tape end: press the physical Start (AUTO) to pivot "
                       f"{self.tape.mrun['direction']} here and drive back")
            return ok, msg
        if self.state not in (RUNNING, HOLD):
            return False, "no run: a forced U-turn only while running or at the tape end"
        return self.tape.force_u_turn(on)

    def continue_on_start(self, on):
        """Guide page: a guided run that ended "track lost" (a U-turn that left the AGV off
        the tape, a lost tape) continues on the NEXT physical Start from where the engineer
        put it back on the tape - same phase and distances - instead of a new run from
        "out" (2026-10-24 13:43: a new run from the MRU end took the home strip for the
        U-turn). Returns (ok, message). It never starts anything by itself."""
        if self.tape is None or not (self.tape.guided and self.tape.mrun):
            return False, "continue only in a guided marker mission"
        if self.state != DONE or not self.ended_at_end:
            return False, "nothing to continue: only after the run ended \"track lost\""
        self.continue_armed = bool(on)
        if not on:
            return True, "continue cancelled: the next Start begins a new run"
        return True, (f"continue armed ({self.tape.mrun_phase} phase): put the AGV on the tape facing "
                      f"the way to go, then press the physical Start (AUTO)")

    def select_speed(self, high):
        """The guided page's speed toggle. Returns (ok, message). HIGH only lets the marker
        pair grant HIGH; it never starts, resumes or speeds anything by itself."""
        if self.tape is None:
            return False, "no mission loaded"
        ok, msg = self.tape.select_speed(high)
        if ok:
            self.high_select = bool(high)
        return ok, msg

    # -- trips (tracked plan 4): calls, the payload, the position engine ---------------------
    def configure_site(self, params, compile_trip):
        """Let a site mission be the job (tape_loc.live). compile_trip(trip) -> TripRoute or a
        RouteError; params: the locator limits (tape_locator.Params)."""
        self._site_cfg = {"params": params, "compile": compile_trip}
        from amr_line import trip as tripmod  # noqa: PLC0415
        if self.payload is None:
            self.payload = tripmod.Payload()

    def trip_call(self, machine, now):
        if self.calls is None:
            return False, "no site mission is the job: calls are taken only while it is"
        return self.calls.call(machine, now)

    def trip_cancel(self, machine):
        if self.calls is None:
            return False, "no site mission is the job"
        if self.calls.cancel(machine):
            return True, f"{machine}'s call cancelled"
        return False, f"{machine} is not waiting" + (" (it is on the trip being driven: Clear stops it)"
                                                     if self.trip and machine in self.trip.machines else "")

    def confirm_released(self):
        """The Calls page: every trolley of this trip is off (the HOLD payload before the U-turn).
        It records; the vehicle moves only on the physical Start."""
        if self.trip is None:
            return False, "no trip is being driven"
        self.trip.confirm_released()
        return True, "releases confirmed: press the physical Start to pivot"

    def confirm_off(self):
        """The Calls page: the trolleys are off at HOME; the next trip may leave the bay."""
        if self.payload is None:
            return False, "no site mission is the job"
        if self.trip is not None:
            return False, "a trip is being driven: confirm at HOME once it has ended"
        self.payload.confirm_off()
        return True, "trolleys off at HOME confirmed: the next trip may leave"

    def trip_status(self):
        """For the Calls page and LineState: (trip, next, queue, payload)."""
        if self.calls is None:
            return {"trip": "", "trip_next": "", "trip_queue": "", "trip_payload": ""}
        q = " ".join(m for m, _t in self.calls.pending)
        g = self.calls.ready_group()
        nxt = self.tape.next_event() if hasattr(self.tape, "next_event") else ""
        if g is not None and self.trip is None:
            nxt = f"{g} trip formed: press Start at {self.site['HOME']}"
        ok, why = self.payload.may_leave()
        return {"trip": self.trip.describe() if self.trip else self.trip_note,
                "trip_next": nxt, "trip_queue": q, "trip_payload": "" if ok else why}

    def _site_at_home(self, loc):
        """(at HOME, why not) from the locator, for a trip's Start."""
        from amr_line import site_run  # noqa: PLC0415
        p = self._site_cfg["params"]
        if not loc or not loc.get("started"):
            return False, f"the tape locator is not running: press At home at {self.site['HOME']}"
        if loc.get("lost"):
            return False, f"localization LOST ({loc['lost']}): At home at {self.site['HOME']}"
        off = loc.get("home_offset")
        if off is None or abs(off) > site_run.HOME_START_M:
            far = f" ({off:+.2f} m from it)" if off is not None else ""
            return False, f"not at {self.site['HOME']}{far}: a trip starts there"
        if loc["sigma"] > p.sigma_junction_m:
            return False, f"position uncertain at {self.site['HOME']} (sigma {loc['sigma']:.3f} m)"
        return True, ""

    def _trip_check(self, i: Inputs):
        """What a trip's Start needs: the trolleys confirmed off, a formed trip, the AGV at HOME."""
        if self.trip is None:
            ok, why = self.payload.may_leave()
            if not ok:
                return why
            if self.calls.ready_group() is None:
                need = self.site["TRIP_CALLS"]
                return f"no trip formed: {need} call{'s' if need > 1 else ''} of one group needed"
        ok, why = self._site_at_home(i.loc)
        return "" if ok else why

    def _trip_take(self):
        """Form the trip and compile its route. "" or why not (the calls are put back)."""
        trip = self.calls.take()
        try:
            route = self._site_cfg["compile"](trip)
        except ValueError as e:         # tape_graph.RouteError / GraphError
            self.calls.restore(trip)
            return f"trip {trip.describe()} cannot be driven: {e}"
        self.trip, self.trip_route, self.trip_new = trip, route, route
        self.trip_note = ""
        return ""

    def _trip_abort(self, why):
        trip, self.trip = self.trip, None
        done = ", ".join(sorted(trip.served)) or "nothing"
        self.trip_note = f"trip {trip.describe()} ABORTED ({why}); served: {done}"
        if self.tape is not None:
            self.tape.events.append(("warn", self.trip_note + f" - bring the AGV to {self.site['HOME']}"))

    def set_mission(self, mission, destination=None):
        """Choose the job for the next run: mission and, when the mission has
        destination stops, the destination. Refused unless IDLE or DONE: a run's
        latches and destination belong to the job it started with."""
        if self.state not in (IDLE, DONE):
            return False, f"cannot change the job while {STATE_NAMES[self.state]}: clear first"
        if mission is not None and str(mission.get("SCHEMA", "")).startswith("site"):
            return self._set_site(mission)
        self.site = self.calls = None
        destination = (destination or "").strip() or None
        dests = mission["DESTINATIONS"] if mission else []
        if destination is not None and destination not in dests:
            have = ", ".join(dests) if dests else "none in this mission"
            return False, f"destination {destination!r} is not a stop of this mission ({have})"
        self.mission = mission
        self.destination = destination
        self.result = ""
        self.high_select = False
        self.tape = self._new_tape()
        name = mission["MISSION_NAME"] if mission else "none"
        if not mission or name == "empty":
            rows = (mission or {}).get("TAGS", {}).values()
            turns = sorted(r["tag"] for r in rows if r["action"] == "u_turn")
            return True, "plain line following" + (f" (U-turn tags {', '.join(turns)})" if turns else "")
        return True, f"mission {name}" + (f", destination {destination}" if destination else "")

    def _set_site(self, site):
        if self._site_cfg is None:
            return False, (f"{site['MISSION_NAME']} drives trips only with tape_loc.live: true "
                           f"(the position engine is off - it shadows)")
        from amr_line import trip as tripmod  # noqa: PLC0415
        self.mission, self.destination, self.result = None, None, ""
        self.site = site
        self.calls = tripmod.CallQueue(site)
        self.high_select = False
        self.tape = self._new_tape()
        return True, (f"site mission {site['MISSION_NAME']}: trips form from machine calls "
                      f"({site['TRIP_CALLS']} a trip), Start at {site['HOME']}")

    def at_home(self):
        """(at_home, why_not). (False, "") for a mission without a Home stop. A site mission
        answers with the trip's own predicate (_site_at_home, what a Start checks)."""
        if self.site is not None:
            return self._site_at_home(self._loc)
        home = self.mission["HOME"] if self.mission else None
        if home is None:
            return False, ""
        return self.odometer.at(home["tag"], tag_table.home_window_m(home))

    def _rfid_check(self, i: Inputs):
        """The mission's position sources: the RFID link, and a marker run's MLS markers."""
        if self.tape is not None and self.tape.needs_link and not (i.rfid or {}).get("comms_ok", False):
            return "RFID link down (the mission needs its tags)"
        if self.tape is not None and self.tape.needs_markers and not (i.markers or {}).get("ok", False):
            return "MLS markers down (the run's U-turn and home stop are markers)"
        return ""

    def _job_check(self, i: Inputs):
        """What a Start from IDLE/DONE needs beyond the vehicle prerequisites.

        A run may start anywhere on the line (operator, 2026-10-09: demo runs of the speed
        zones, stopped by a person). Away from Home the leg is unknown, so the U-turn
        rule still applies as written: a destination not reached before the U-turn is
        reported missed and not served from the return leg, and the run ends at Home.
        """
        rfid = self._rfid_check(i)
        if rfid:
            return rfid
        if self.site is not None:
            return self._trip_check(i)
        m = self.mission
        if m is None or m["HOME"] is None:
            return ""
        if m["DESTINATIONS"] and self.destination is None:
            return "no destination selected"
        return ""

    def _start(self, i: Inputs):
        """The physical Start from IDLE or DONE: check, then the pre-move warning.

        The press itself is the operator's intent; there is no software arm in
        front of it. A refused press is dropped, not remembered: the node hands
        each edge to exactly one tick, so a Start pressed while the field was
        blocked cannot run the vehicle later when the field clears. Torque is not
        a prerequisite: the drives are powered BY this Start (ARMED).
        """
        pre = self._prerequisite(i, torque=False) or self._job_check(i)
        if pre:
            self.reason = f"Start refused: {pre}"
            self.refused = pre      # the node turns this into one operator event
            return 0.0, 0.0
        if self.site is not None:
            why = self._trip_take()
            if why:
                self.reason = f"Start refused: {why}"
                self.refused = why
                return 0.0, 0.0
        self._binding = i.authority
        at_end = self.state == DONE and self.ended_at_end and self.tape is not None
        kind = ("uturn" if at_end and self.tape.uturn_forced
                else "continue" if at_end and self.continue_armed else "start")
        return self._begin_premove(i, kind)

    def _depart(self, i: Inputs):
        """A run from IDLE/DONE begins: fresh engine, fresh mission state."""
        self.result = ""
        self.ended_at_end = self.continue_armed = False
        self.f.reset()
        self.tape = self._new_tape()
        self.followed_m = 0.0
        self.accepted_t = i.now
        self.hold_cause = ""
        self._prereq.reset()
        self._auto_since = None
        self._resume_pending = False
        self._resume_at = None
        self.state = RUNNING
        self.reason = "running"
        self.tape.depart(i.now, i.rfid)
        if self.tape.fault:
            return self._tape_fault()
        return 0.0, 0.0

    # -- the pre-move warning (ARMED) --------------------------------------
    def wants_power(self):
        """What LineState.drive_power asks of drive_node's power policy (amr_base.arm_policy):
        the pre-move warning, a run, and holds that resume by themselves. Idle, DONE, FAULT
        and holds that wait for a physical Start leave the drives in standby."""
        return self.state in (ARMED, RUNNING) or self.auto_resume()

    def _begin_premove(self, i: Inputs, kind):
        """kind: start (IDLE/DONE), resume (a hold that waited for Start), station."""
        self._premove = {"kind": kind, "since": i.now, "back": (self.state, self.hold_cause, self.reason)}
        self.state = ARMED
        self._prereq.reset()
        return self._premove_tick(i)

    def _premove_cancel(self, why):
        back_state, back_cause, _ = self._premove["back"]
        kind = self._premove["kind"]
        self._premove = None
        self._prereq.reset()
        self.state, self.hold_cause = back_state, back_cause
        if kind in ("start", "uturn", "continue"):
            self._binding = None
        if kind == "start" and self.trip is not None:
            self.calls.restore(self.trip)       # not driven: the calls wait again
            self.trip = self.trip_route = None
        self.reason = f"Start cancelled: {why}"
        self.refused = why
        return 0.0, 0.0

    def _premove_tick(self, i: Inputs):
        """ARMED: alarm horn on (panel), power asked for; go once the warning has run AND the
        drives have torque. Nothing moves here: the node publishes no command while ARMED."""
        pm = self._premove
        kind = pm["kind"]
        if kind != "start":
            # Held state carries on as in HOLD: tags still delivered once, never acted on.
            tags = self.tape.scan(i.now, i.rfid, False, self.f)
            self.tape.link_lost = self.tape.marker_lost = None
            if self.tape.fault:
                self._premove = None
                return self._tape_fault()
            self.tape.steer(i.sensor, tags, self.f.followed_mm)
            if self.hold_cause == "station" or self.hold_cause in _PARKS_HIGH:
                self.tape.parked(self.step_m)
        pre = self._prerequisite(i, torque=False) or (
            self._job_check(i) if kind == "start" else self._rfid_check(i))
        if i.field_clear is False:
            return self._premove_cancel(pre)
        if self._prereq_held(i.now, pre):
            return self._premove_cancel(pre)
        waited = i.now - pm["since"]
        powered = not i.torque_off and i.drives_fresh
        if not pre and hold_policy.premove_ready(waited, self.premove_s, i.drives_fresh, i.torque_off):
            return self._premove_go(i)
        if waited >= self.premove_timeout_s:
            return self._premove_cancel(hold_policy.premove_timeout_text(
                self.premove_timeout_s, "safety chain open? release the E-stop and press Reset"))
        left = max(0.0, self.premove_s - waited)
        self.reason = (f"Start: warning, moving in {left:.1f} s" if powered or left > 0
                       else "Start: waiting for the drives to power up")
        return 0.0, 0.0

    def _premove_go(self, i: Inputs):
        kind = self._premove["kind"]
        back_cause = self._premove["back"][1]
        self._premove = None
        self._prereq.reset()
        if kind == "start":
            return self._depart(i)
        if kind == "continue":
            # The run that ended "track lost" goes on where the engineer put the AGV back on
            # the tape: same phase (out/back), same distances, so home is still home.
            self.ended_at_end = self.continue_armed = False
            self.state, self.hold_cause = RUNNING, ""
            self.f.reset()
            self.tape.continue_run()
            self.reason = f"continued on Start ({self.tape.mrun_phase or 'run'})"
            return 0.0, 0.0
        if kind == "uturn":
            # The run that ended at the tape end goes on: same mission state, the forced
            # U-turn from standstill (spin, reacquire, back), then the way home.
            self.ended_at_end = False
            self.state, self.hold_cause = RUNNING, ""
            self.f.reset()
            if not self.tape.turn_here():
                return self._uturn_fault("the forced U-turn was no longer armed")
            self.f.hard_stop()
            self.reason = "U-turn on Start at the tape end"
            return 0.0, 0.0
        self.state = RUNNING
        if kind == "station":
            where = (self.tape.stop or {}).get("where", "station")
            tag = (self.tape.stop or {}).get("tag")
            self.hold_cause = ""
            self.tape.depart(i.now, i.rfid, resumed_tag=tag)
            if self.tape.fault:
                return self._tape_fault()
            self.reason = f"departed {where}"
            return 0.0, 0.0
        self._resume_speed(back_cause)
        self.hold_cause = ""
        self.reason = "resumed on Start"
        return 0.0, 0.0

    def clear(self):
        """Disarm. The node zeroes the command immediately on this."""
        moving = self.state in (RUNNING, HOLD)
        self.state = IDLE
        self._premove = None
        self.hold_cause = ""
        self.accepted_t = None
        self._binding = None
        self._prereq.reset()
        self._auto_since = None
        self._resume_pending = False
        self._resume_at = None
        self.followed_m = 0.0
        self.f.hard_stop()
        if self.trip is not None:
            self._trip_abort("cleared")
        self.tape = self._new_tape()
        self.reason = "cleared"
        return moving

    # -- the checks --------------------------------------------------------
    def _prerequisite(self, i: Inputs, torque=True):
        """Why the vehicle may not move right now, or "" if it may. torque=False for a
        Start: the drives are in standby until the Start itself asks for power."""
        if not i.panel_valid:
            return "panel state is stale"
        if not i.panel_auto:
            return "selector is not in AUTO"
        if i.authority is None:
            return "no fresh control lease"
        if not (i.lease_allowed & i.lease_line):
            return "LEASE_LINE not granted by the supervisor"
        if not i.drives_fresh:
            return "no fresh drive report"
        if torque and i.torque_off:
            return "drive torque is off"
        if i.field_clear is None:
            return "protective field state unknown (no fresh /output_paths)"
        if not i.field_clear:
            return "protective field is violated"
        if not i.track_ok:
            return {"rate": "tape samples too slow for control (see line_min_track_hz)",
                    "track": "no usable tape reading"}.get(i.track_cause, "tape reading unusable")
        return ""

    def _resume_speed(self, cause):
        """The speed a hold resumes at: HIGH as arrived after a parking hold (field, RFID
        link, an "estop" that was the field reported late), NORMAL after a real E-stop."""
        if cause in _PARK_CAUSES or (cause == "estop" and self._estop_was_field):
            self.tape.resume_high()
        elif cause == "estop":
            self.tape.drop_high("resumed after an E-stop / safety-chain stop")

    def _safety_cause(self, i: Inputs):
        """Which safety story a torque loss belongs to. Unknown field evidence
        cannot prove a stop was only the field, so it is an E-stop: the hold
        that waits for a human."""
        return "field" if i.field_clear is False else "estop"

    def _taken_over(self, i: Inputs):
        """An explicit withdrawal of authority, or "". Not debounced: a
        selector flick to MANUAL and back inside the grace window must not
        leave the run entitled to resume the moment the mux re-opens."""
        if i.panel_valid and not i.panel_auto:
            return "manual takeover: selector left AUTO"
        if i.authority is not None and not (i.lease_allowed & i.lease_line):
            return "LEASE_LINE withdrawn by the supervisor"
        return ""

    def _auto_causes(self):
        return hold_policy.auto_causes(_AUTO_CAUSES, self.auto_resume_estop)

    def _prereq_held(self, now, pre):
        """True once a prerequisite has failed CONTINUOUSLY for the grace.

        Any passing tick clears the timer, so one dropped frame never latches.
        What is debounced is "something is wrong", not one message: the reason
        may change while the timer runs.
        """
        return self._prereq.held(now, pre, self.prereq_grace_s)

    def _hold(self, cause, why):
        self.state = HOLD
        self.hold_cause = cause
        self._premove = None
        self.reason = hold_policy.hold_text(cause, why, {"authority": "authority lost: {why}"})
        self._auto_since = None
        self._resume_at = None
        self.f.hard_stop()
        if self.diag:
            self.diag = dict(self.diag, v_base=0.0)     # hard_stop zeroed it: say so
        self._hold_since = None
        self._estop_was_field = False
        # A station stop parked HIGH (TapeRun._begin_stop); a protective-field or
        # RFID-link hold parks it (operator, 2026-10-09: back to HIGH after it, and no RFID
        # event changes the speed), and so does an "estop" hold until the resume knows
        # whether it was the field (see _PARKS_HIGH); any other hold forgets it. Warning
        # fields never reach here: the mux scales the command and HIGH carries on
        # through them.
        if self.tape is not None and cause in _PARKS_HIGH:
            self.tape.park_high(f"hold ({cause})")
        elif self.tape is not None and cause != "station":
            self.tape.drop_high(f"hold ({cause})")
        if self.kink is not None and self.kink["turn"] is not None:
            # A kink pivot is a search, not a measured turn: after the hold it starts again
            # from rest, toward the same side, with what is left of kink_max_deg.
            self.kink["done_deg"] += max(0.0, self.kink["turn"].angle_deg)
            self.kink["turn"] = None
        # A pivot cannot be resumed part-way (gy-demo rule): its start counts and
        # tape history describe a vehicle that has since been stopped by hand.
        if cause != "station" and self.tape is not None and self.tape.uturn_req is not None:
            self.tape.abort_u_turn()
            self.state = FAULT
            self.reason = f"U-turn interrupted ({why}); align the AGV on the tape, Reset, then Start"

    # -- the tick ----------------------------------------------------------
    def tick(self, i: Inputs):
        """Returns (left_rpm, right_rpm). Zero unless actually following."""
        # Every state, MANUAL jogs included: this is how "at Home" is proven.
        self.odometer.update(i.now, i.rfid, i.counts, i.counts_per_rev)
        self._loc = i.loc
        self._markers_tick(i.markers)
        self.step_m = self._wheel_travel(i)
        # Reset ends a run too: on the jacked-up vehicle (2026-09-21) Reset
        # did nothing while RUNNING and the wheels kept turning until the
        # follower was cleared by service. The node zeroes the command on
        # the falling edge out of RUNNING.
        # Reset wins over a Start seen in the same tick.
        if i.reset_edge and self.state != IDLE:
            self.reset()
            self.reason = "reset"
            return 0.0, 0.0

        # FAULT needs Reset first; IDLE and DONE start on the physical Start.
        if self.state in (IDLE, DONE):
            if i.start_edge:
                return self._start(i)
            if self.state == IDLE:
                # Live, not latched: what a Start pressed now would meet.
                pre = self._prerequisite(i, torque=False) or self._job_check(i)
                self.reason = f"not ready: {pre}" if pre else "ready: press the physical Start under AUTO"
            return 0.0, 0.0
        if self.state == FAULT:
            if self.trip is not None:
                self._trip_abort(self.reason)
            return 0.0, 0.0

        # Authority is re-checked every tick and never debounced: if the lease
        # or the generation moved, something above this layer took control and
        # this run is not entitled to the wheels any more.
        if self._binding is not None and i.authority != self._binding:
            self._hold("authority", "the control lease was replaced")
            self.state = FAULT
            return 0.0, 0.0
        taken = self._taken_over(i)
        if taken:
            self._hold("authority", taken)
            self.state = FAULT
            return 0.0, 0.0

        if self.state == ARMED:
            return self._premove_tick(i)

        pre = self._prerequisite(i)

        # An immediate stop for anything meaning the vehicle may be moving
        # without the feedback or the torque to do it safely.
        if self.state == RUNNING:
            if i.torque_off or i.field_clear is False:
                self._hold(self._safety_cause(i), "drive torque removed")
                return 0.0, 0.0
            if not i.drives_fresh:
                self._hold("drives", "wheel feedback stopped while running")
                return 0.0, 0.0

        if self.state == HOLD:
            # Tags read while held are still delivered exactly once - a branch or
            # slow-zone exit passed during a hold must still clear its latch - but
            # they cannot start a stop or a U-turn (TapeRun.scan, driving=False).
            tags = self.tape.scan(i.now, i.rfid, False, self.f)
            # Held, the vehicle is still: a link that dropped and came back cost
            # no tags. A link still down is caught again on the first tick driving.
            self.tape.link_lost = self.tape.marker_lost = None
            if self.tape.fault:
                return self._tape_fault()
            self.tape.steer(i.sensor, tags, self.f.followed_mm)
            if self.hold_cause == "station" or self.hold_cause in _PARKS_HIGH:
                self.tape.parked(self.step_m)
            return self._hold_tick(i, pre)

        if self.state == RUNNING:
            if self._prereq_held(i.now, pre):
                self._hold(i.track_cause or "pending", pre)
                return 0.0, 0.0
            return self._run(i)

        return 0.0, 0.0

    def _hold_tick(self, i: Inputs, pre):
        """Wait for the cause to clear, then resume - or wait for a human."""
        if self._hold_since is None:
            self._hold_since = i.now
        if (self.hold_cause == "estop" and i.field_clear is False
                and i.now - self._hold_since <= FIELD_RACE_S):
            self._estop_was_field = True  # the protective field, reported late: HIGH comes back
        # A torque loss arriving DURING a hold for some other reason takes the
        # safety cause (executor rule): a hold for stale feedback must not
        # auto-resume through an E-stop that happened while it waited. A hold
        # already on the field's or the E-stop's terms keeps them. Only holds that
        # keep their power can lose torque: the others are in standby on purpose.
        powered_hold = self.hold_cause in self._auto_causes()
        if self.hold_cause not in ("field", "estop") and powered_hold and (
                i.torque_off or i.field_clear is False):
            self._hold(self._safety_cause(i), "drive torque removed while held")
            return 0.0, 0.0

        if self.hold_cause == "station":
            # Parked in standby a field trip stops nothing. It does not cost the parked
            # HIGH either (operator, 2026-10-23: a protective stop never resets HIGH, as
            # after a protective-field hold while running): the departure is as arrived.
            return self._station_tick(i, pre)

        if self.hold_cause not in self._auto_causes():
            # estop (by default), rfid and authority: a physical Start, not a timer.
            # The drives are in standby here, so torque comes with the Start.
            pre = self._prerequisite(i, torque=False) or self._rfid_check(i)
            if i.start_edge and not pre:
                return self._begin_premove(i, "resume")
            self.reason = f"held ({self.hold_cause}): press Start when clear"
            return 0.0, 0.0

        if pre:
            self._auto_since = None
            self.reason = f"held ({self.hold_cause}): {pre}"
            return 0.0, 0.0
        if self._auto_since is None:
            self._auto_since = i.now
        if i.now - self._auto_since >= self.auto_resume_clear_s:
            self._resume_speed(self.hold_cause)
            self.state = RUNNING
            self.hold_cause = ""
            self._auto_since = None
            self.reason = "resumed: the cause cleared and stayed clear"
        else:
            self.reason = f"held ({self.hold_cause}): clear, resuming shortly"
        return 0.0, 0.0

    def _station_tick(self, i: Inputs, pre):
        """Parked at a station: Start, then the pre-move warning, then go on.

        The warning is the same one every start takes, because a station is exactly
        where somebody is likely to be standing. The drives are in standby while
        parked, so torque is not asked for until the Start.
        """
        where = (self.tape.stop or {}).get("where", "station")
        pre = self._prerequisite(i, torque=False) or self._rfid_check(i)
        if i.start_edge and not pre:
            return self._begin_premove(i, "station")
        self.reason = f"at {where}: press Start to go on" + (f" ({pre})" if pre else "")
        return 0.0, 0.0

    def _arrive_home(self):
        """The run is over. The destination is spent: the next run is a new job."""
        self.result = self.tape.result()
        if self.trip is not None:
            # The trolleys come off at HOME by hand: the next trip waits for that confirmation.
            self.payload.trip_ended()
            self.trip_note = self.result
            self.trip = None
        where = self.tape.stop["where"]
        self.state = DONE
        self.hold_cause = ""
        self.reason = f"at {where}: {self.result}"
        self.destination = None
        self.f.hard_stop()
        self.tape.events.append(("warn" if "MISSED" in self.result or "NOT" in self.result else "info",
                                 f"run ended at {where}: {self.result}"))
        return 0.0, 0.0

    def _wheel_travel(self, i: Inputs):
        """Metres the wheels moved since the last tick (mean |left|, |right|), or None.

        Every distance the speed engine and the U-turn count is this, not commanded
        speed: a warning-field hold slows the vehicle in the mux, where the follower
        cannot see it, and a commanded-speed distance would run out undriven.
        """

        from amr_line import uturn  # noqa: PLC0415

        counts, ref = i.counts, self._counts_ref
        self._counts_ref = tuple(counts) if counts is not None else None
        if counts is None or ref is None or not i.counts_per_rev:
            return None
        return uturn.unsigned_travel_m(counts, ref, i.counts_per_rev)

    def _speed_inputs(self, i: Inputs):
        """Take HIGH away when its supports are gone; run the curve guard."""
        from agv_core import config as vehicle  # noqa: PLC0415

        t = self.tape
        if (t.speed.state != "normal" or t.high) and self.step_m is None:
            t.drop_high("wheel travel unavailable (no encoder counts)")
        if self.step_m is None:
            t.parked(None)
        if t.high and (i.yaw_rate is None or i.v_meas is None):
            t.drop_high("curve guard inputs stale (gyro and odometry)")
        above = (self.diag or {}).get("v_base", 0.0) > vehicle.AUTO_RPM + 1.0
        trip = t.guard.update(t.speed.high or above, i.yaw_rate, i.v_meas,
                              (self.diag or {}).get("e_mm"), self.step_m or 0.0)
        if trip:
            t.drop_high(trip, urgent=True)

    def _tape_fault(self):
        self.state = FAULT
        self.hold_cause = ""
        self.reason = self.tape.fault
        self.f.hard_stop()
        return 0.0, 0.0

    def _uturn_fault(self, why):
        self.tape.abort_u_turn()
        self.state = FAULT
        self.hold_cause = ""
        self.reason = f"U-turn: {why}; align the AGV on the tape, Reset, then Start"
        self.f.hard_stop()
        return 0.0, 0.0

    def _uturn_tick(self, i: Inputs, tags):
        """Slow to the creep, stop the moment the tape is gone, pivot until the tape
        is back and centred (encoders gate the angle), settle, resume."""
        from agv_core import config as vehicle  # noqa: PLC0415
        from agv_core import kinematics  # noqa: PLC0415

        from amr_line import uturn  # noqa: PLC0415
        from amr_line.tape_run import approach_rate, u_turn_error  # noqa: PLC0415

        t = self.tape
        req = t.uturn_req
        if i.sensor_age_s is None or i.sensor_age_s > vehicle.SENSOR_TIMEOUT_S:
            # A silent sensor is a comms fault, never the end of the tape.
            return self._uturn_fault("sensor silent during the U-turn")
        if t.uturn is None:
            choice, _high = t.steer(i.sensor, tags, self.f.followed_mm)
            approach = req["phase"] == "approach"
            creep = req["approach_mps"] * vehicle.RPM_PER_MPS
            if approach and req["decel_rpm_s"] is None:
                # Solved once from the speed at the tag (begin_measured_stop's rule):
                # a constant rate that reaches the creep at decel_m.
                v = (self.diag or {}).get("v_base", 0.0)
                req["decel_rpm_s"] = approach_rate(v, creep, req["decel_m"]) or 0.0
            left, right, diag = self.f.update(i.sensor, i.sensor_age_s, i.dt, approach, choice, False,
                                              cruise_rpm=creep, urgent_rate=req["decel_rpm_s"] or None)
            self.diag = diag
            v_now, _ = kinematics.wheels_to_body(left, right)
            self.followed_m += abs(v_now) * i.dt
            if approach and self._kink_begin(diag):
                req["gone"] = 0     # the tape left at the edge: a corner, not the tape end
                return 0.0, 0.0
            if approach:
                # Wheel travel: a warning-field hold at the tape end must not use up
                # max_approach_m. Commanded travel only when the counts are missing.
                travel = self.step_m if self.step_m is not None else abs(v_now) * i.dt
                why = t.approach(i.sensor, diag["has_track"], travel)
                if why:
                    return self._uturn_fault(why)
                if req["phase"] == "stopping":
                    # The tape is gone: zero now. The mux brings the wheels down at
                    # the drive's deceleration (~5 mm from 0.1 m/s).
                    self.f.hard_stop()
                    self.diag = dict(diag, v_base=0.0)
                    return 0.0, 0.0
            elif diag["v_base"] == 0 and i.wheels_still:
                why = t.begin_spin(i.counts, i.counts_per_rev)
                if why:
                    return self._uturn_fault(why)
            return left, right
        if i.counts is None:
            return self._uturn_fault("encoder counts unavailable")
        e_mm, level = u_turn_error(i.sensor)
        # The spin's time budget stands still while a warning field holds it.
        left, right = t.uturn.update(i.counts, e_mm, level, i.dt, paused=i.warning_scale < 1.0,
                                     yaw_rate=i.yaw_rate)
        if t.uturn.phase == uturn.FAILED:
            return self._uturn_fault(t.uturn.reason)
        if t.uturn.phase == uturn.DONE:
            t.finish_u_turn()
            # The PID history describes the tape as it was before the pivot.
            self.f.reset()
            self._post_uturn_m = 0.0
            return 0.0, 0.0
        return left, right

    # -- the kink pivot ------------------------------------------------------
    # 2026-10-23: the HOME complex tape is grooved into the floor with corners and no
    # radius (deflections up to ~50 deg). The follower holds ~40 deg at 0.3 m/s; past
    # that the tape slides off the sensor's edge (run 2026-10-23 16:02: -2 -> -114 mm
    # in 0.2 m, 24 deg of yaw, "track lost"). A tape END leaves the sensor near the
    # centre; a CORNER leaves it at the edge. So: tape gone for KINK_GONE_TICKS with
    # the last reading >= kink_edge_mm off centre -> stop, pivot toward that side
    # until the tape is within +/-kink_stop_mm (the U-turn spin, encoder-gated to
    # kink_max_deg), resume. The sensor is only 0.1 m ahead of the axle: centring
    # over-rotates into the corner, so the pivot stops short and the follower finishes.
    # Not a U-turn to tape localization: signed wheel travel does not grow in a
    # pivot, and the node feeds the fork detectors #LCP 0 meanwhile (pivoting).

    @property
    def pivoting(self):
        """A kink pivot is turning the vehicle (tape localization ignores #LCP)."""
        return self.kink is not None

    def _kink_begin(self, diag):
        """The tape just left at the sensor's edge: stop and arm the pivot. True if so."""
        from agv_core import config as vehicle  # noqa: PLC0415

        if vehicle.KINK_MAX_DEG <= 0 or diag.get("state") == "sensor_lost":
            self._edge_gone = 0
            return False
        last = diag.get("e_used")
        after_turn = self._post_uturn_m is not None
        if diag.get("has_track") or last is None or (abs(last) < vehicle.KINK_EDGE_MM and not after_turn):
            self._edge_gone = 0
            return False
        self._edge_gone += 1
        if self._edge_gone < KINK_GONE_TICKS:
            return False
        self._edge_gone = 0
        e = -last if vehicle.INVERT_ERROR else last     # the follower's sign, as u_turn_error
        direction = "cw" if e > 0 else "ccw"
        self.kink = {"direction": direction, "at_mm": last, "turn": None, "done_deg": 0.0}
        self.kinks += 1
        self.f.hard_stop()
        self.diag = dict(diag, v_base=0.0)
        side = "right" if direction == "cw" else "left"
        if abs(last) < vehicle.KINK_EDGE_MM:
            self.tape.events.append(("warn", f"the tape vanished at {last:+.0f} mm "
                                             f"{self._post_uturn_m:.2f} m after the U-turn - stopping "
                                             f"to find it (pivot {side} if it is not in view)"))
        else:
            self.tape.events.append(("info", f"kink: the tape left the sensor at {last:+.0f} mm - "
                                             f"stopping to pivot {side} onto it"))
        return True

    def _tape_end_tick(self, t, diag, stopping):
        """A U-turn strip read still inside the junction guard, and the tape ends (gone near
        the centre for TAPE_GONE_TICKS, as the approach counts it): pivot here."""
        from amr_line.tape_run import TAPE_GONE_TICKS  # noqa: PLC0415
        if stopping or diag.get("has_track") or diag.get("state") == "sensor_lost":
            self._end_gone = 0
            return False
        self._end_gone += 1
        if self._end_gone < TAPE_GONE_TICKS or not t.tape_ended():
            return False
        self._end_gone = 0
        self.f.hard_stop()
        self.diag = dict(diag, v_base=0.0)
        return True

    def _kink_fault(self, why):
        self.kink = None
        self.state = FAULT
        self.hold_cause = ""
        self.reason = f"kink: {why}; align the AGV on the tape, Reset, then Start"
        self.f.hard_stop()
        return 0.0, 0.0

    def _kink_tick(self, i: Inputs):
        """Stopped at a corner: pivot toward the side the tape left by, centre, resume."""
        from agv_core import config as vehicle  # noqa: PLC0415

        from amr_line import uturn  # noqa: PLC0415
        from amr_line.tape_run import u_turn_error  # noqa: PLC0415

        k = self.kink
        if i.sensor_age_s is None or i.sensor_age_s > vehicle.SENSOR_TIMEOUT_S:
            return self._kink_fault("sensor silent during the pivot")
        if k["turn"] is None:
            if not i.wheels_still:
                self.f.hard_stop()
                return 0.0, 0.0
            if i.counts is None or not i.counts_per_rev:
                return self._kink_fault("encoder counts unavailable for the pivot")
            left_deg = vehicle.KINK_MAX_DEG - k["done_deg"]
            if left_deg < KINK_MIN_LEFT_DEG:
                return self._kink_fault(f"tape not found within {vehicle.KINK_MAX_DEG:.0f} deg")
            k["turn"] = uturn.UTurn(k["direction"], i.counts_per_rev, i.counts, None,
                                    min_deg=0.0, max_deg=left_deg, lost=True, what="kink pivot",
                                    band_mm=vehicle.KINK_STOP_MM, settle_s=KINK_SETTLE_S)
        e_mm, level = u_turn_error(i.sensor)
        left, right = k["turn"].update(i.counts, e_mm, level, i.dt, paused=i.warning_scale < 1.0)
        if k["turn"].phase == uturn.FAILED:
            return self._kink_fault(k["turn"].reason)
        if k["turn"].phase == uturn.DONE:
            angle = k["done_deg"] + k["turn"].angle_deg
            self.kink = None
            self.f.reset()      # the PID history describes the tape before the corner
            e_now, _level = u_turn_error(i.sensor)
            at = "" if e_now is None else f", tape at {e_now:+.0f} mm"
            self.tape.events.append(("info", f"kink: pivoted {k['direction']} {angle:.0f} deg{at} - "
                                             f"resuming"))
            return 0.0, 0.0
        return left, right

    def _run(self, i: Inputs):
        """One engine tick: mission tags, branch order, speed zone, stops, U-turn."""
        t = self.tape
        driving = self.kink is None     # a kink pivot starts no stop and no U-turn
        t.locate(i.loc, (self.diag or {}).get("v_base", 0.0))
        tags = t.scan(i.now, i.rfid, driving, self.f)
        if t.fault:
            return self._tape_fault()
        if t.hold_req is not None:
            # The position engine is not sure enough where it is: held BEFORE the point.
            cause, why = t.hold_req
            t.hold_req = None
            self._hold(cause, f"{why}; press Start to re-check")
            return 0.0, 0.0
        if t.link_lost:
            # Immediate, not debounced: the node already allows the heartbeat
            # rfid_fresh_s, and every metre driven blind is a tag not read.
            self._hold("rfid", t.link_lost + "; press Start once the link is back")
            return 0.0, 0.0
        t.markers(self._marker_new, self.markers_ok, driving, self.f)
        if t.fault:
            return self._tape_fault()
        if t.marker_lost:
            # Like the RFID link: every metre driven blind is a marker not read.
            self._hold("markers", t.marker_lost + "; press Start once the markers are back")
            return 0.0, 0.0
        if self.kink is not None:
            return self._kink_tick(i)
        if t.uturn_req is not None:
            return self._uturn_tick(i, tags)
        self._speed_inputs(i)
        choice, high = t.steer(i.sensor, tags, self.f.followed_mm)
        stopping = t.stop is not None
        left, right, diag = self.f.update(i.sensor, i.sensor_age_s, i.dt, not stopping, choice, high,
                                          cruise_rpm=t.cruise_rpm, change_rate=t.change_rate(),
                                          urgent_rate=t.urgent_rate)
        self.diag = diag
        t.speed.settled(diag["v_base"])
        if not stopping and self._kink_begin(diag):
            return 0.0, 0.0
        if self._tape_end_tick(t, diag, stopping):
            return 0.0, 0.0

        from agv_core import kinematics  # noqa: PLC0415  (profile-dependent)
        v_now, _ = kinematics.wheels_to_body(left, right)
        self.followed_m += abs(v_now) * i.dt
        if self._post_uturn_m is not None:
            self._post_uturn_m += abs(v_now) * i.dt
            if self._post_uturn_m > POST_UTURN_M:
                self._post_uturn_m = None
        t.advance(self.step_m if self.step_m is not None else abs(v_now) * i.dt)
        if t.fault:
            return self._tape_fault()

        # A measured stop that has come to rest. Home ends the run; any other
        # stop parks and waits for Start.
        if stopping and diag["v_base"] == 0:
            act = t.at_rest()
            if act == "home":
                return self._arrive_home()
            if act == "pivot":
                return 0.0, 0.0             # the U-turn takes over next tick
            if isinstance(act, tuple):
                self._hold(*act)
                return 0.0, 0.0
            self._hold("station", f"at {t.stop['where']}: press Start to go on")
            return 0.0, 0.0

        # The engine stops itself when the tape has been gone for
        # LINE_LOSS_GRACE_M of travel. That is a completed run, not a fault:
        # the vehicle reached the end of the tape, or the tape ended.
        if diag["state"] in ("line_lost", "sensor_lost"):
            if self.trip is not None:
                # A trip that lost its tape is not over where it stopped: FAULT, not DONE.
                self._trip_abort(f"tape lost at {self.tape.where()}")
                self.state, self.hold_cause = FAULT, ""
                self.reason = "track lost during a trip: bring the AGV to HOME (MANUAL), At home, Reset"
                self.f.hard_stop()
                return 0.0, 0.0
            self.state = DONE
            self.ended_at_end = diag["state"] == "line_lost"
            self.hold_cause = ""
            self.reason = ("track lost: the tape has been out of view for the "
                           "whole line-loss distance budget")
            self.f.hard_stop()
            return 0.0, 0.0

        return left, right

    # -- reporting ---------------------------------------------------------
    def _markers_tick(self, snap):
        """Drain new markers into the operator log and keep this tick's for _run."""
        ok = bool(snap and snap.get("ok"))
        if snap is not None and ok != self.markers_ok:
            self._marker_log.append(("info" if ok else "warn",
                                     f"markers {'up' if ok else 'down'}: {snap.get('status', '')}"))
        self.markers_ok = ok
        self._marker_new = self.markers.scan(snap)
        for code, _direction, lcp2, gap, _good in self._marker_new:
            note = f" ({gap} missed before it)" if gap else ""
            self._marker_log.append(("warn" if gap else "info", f"marker {code} at {lcp2:+d} mm{note}"))

    def drain_marker_events(self):
        out, self._marker_log = self._marker_log, []
        return out

    def marker_snapshot(self):
        """LineState's marker fields."""
        last = self.markers.last or {}
        return {"markers_ok": self.markers_ok, "last_marker": int(last.get("code", 0)),
                "marker_count": self.markers.count, "marker_missed": self.markers.missed}

    def mission_snapshot(self):
        """What the mission engine is doing, for LineState and the web."""
        t = self.tape
        u = t.uturn_snapshot() or {}
        at_home, why = self.at_home()
        return {
            **self.trip_status(),
            "mission": t.name if (self.mission or self.site) and t.name != "empty" else
            (self.site["MISSION_NAME"] if self.site else ""),
            "station": (t.stop or {}).get("where", ""),
            "next_station": self.destination or "",
            "branch_intent": t.branch.ladder.intent(),
            "slow_zone": False,   # junction slow zones retired 2026-10-09 (slow_speed); the field stays
            "high_speed": bool(t.high),
            "speed_select": t.speed_select,
            "speed_reason": t.speed.reason,
            "uturn_phase": (u.get("phase") or "") if u.get("active") else "",
            "last_tag": (t.last_encounter or {}).get("tag") or "",
            "last_tag_action": (t.last_encounter or {}).get("action") or "",
            "stop_where": (t.stop or {}).get("where", ""),
            "destination": self.destination or "",
            "at_home": at_home,
            "home_detail": why,
            "job_result": self.result,
        }

    def auto_resume(self):
        return self.state == HOLD and self.hold_cause in self._auto_causes()
