"""Tape localization inside the LINE layer, P1: teach and shadow (tracked plan 3, section 4).

Pure and clock-fed, like amr_line.job: the node hands it wheel travel, the MLS track
count, the U-turn phase, AMCL poses and readiness, and publishes what it says. NOTHING
here reaches the follower or the command: in P1 the locator only logs where it would
have stopped and branched (Shadow), and teaching only records.

Times are ROS time in seconds (AMCL stamps are ROS time; the odometry buffer must use
the same clock). Wheel travel is SIGNED forward travel, so a pivot adds about nothing.

    at_home()        the AGV is parked at HOME-N: /initialpose gets HOME-N's taught pose;
                     the locator starts on the shadow circuit once readiness is READY
    teach(action)    map <id> <rev> | pass_start <circuit> | pass_stop | pass_discard |
                     passes | pass_delete <name> | station <id> | mark [label] | marks |
                     mark_delete <M> | mark_role <M> <station or point | -> | roles |
                     mark_offset | mark_along <M> <metres> [<new M>] |
                     build | publish | activate <g> | status
    begin_trip(r)    tracked plan 4: the locator moves onto a trip's route (trip_route) at
                     the AGV's place relative to HOME; loc_state() is what the job acts on
"""

import collections
import math

from amr_line import tape_graph as tg
from amr_line import tape_graph_store as store
from amr_line import tape_locator as tl
from amr_line import tape_teach as tt
from amr_line import trip_route

READY, LOST_STATES = 2, (0, 3)       # LocalizationState: UNLOCALIZED 0, CHECKING 1, READY 2, LOST 3
READINESS_STALE_S = 2.0
STATION_CAPTURE_S = 3.0              # standstill AMCL poses averaged for a station
MARK_POSE_MAX_AGE_S = 3.0            # a mark needs an AMCL pose this fresh (it updates on motion)
STATION_MIN_POSES = 5
START_SIGMA_M = 0.03                 # locator sigma at HOME-N after At home
INFO, WARN = "info", "warn"


class TapeRuntime:
    def __init__(self, mission, params, *, maps_dir, state_dir, selection=None, resolve_sha=None,
                 status="", shadow_circuit="C-MRU"):
        """selection: the active pointer ({"map_id", "map_revision", "graph_revision"}) the
        layer was started with, or None. resolve_sha(map_id, rev) -> the bundle's sha256
        (raises on a bundle that does not verify). status: why localization is not running."""
        self.m = mission
        self.p = params
        self.maps_dir, self.state_dir = maps_dir, state_dir
        self.sel = selection
        self.resolve_sha = resolve_sha
        self.shadow_circuit = shadow_circuit
        self.events = []
        self.detail = status
        self.map_sha = ""
        self.graph = self.staged = None
        self.graph_name = ""
        self.route = self.loc = self.shadow = None
        self.recorder = None
        self.pending_home = False
        self.ready, self.ready_t, self.ready_why = False, None, "no readiness yet"
        self.travel = None
        self._poses = collections.deque(maxlen=200)    # (t, x, y, yaw) for station capture
        self._odom = tl.OdomBuffer(span_s=5.0)         # wheel travel by time, for marks
        self._still_since = None
        self._forks = tg.ForkDetector()
        self._uturn_phase = ""
        self._was_lost = ""
        self.t = None
        if selection is not None and not status:
            self._load_active()

    # -- setup ---------------------------------------------------------------------
    @property
    def running(self):
        """Is AMCL expected on this layer at all?"""
        return self.sel is not None and not self.detail.startswith("off")

    def _load_active(self):
        sel = self.sel
        try:
            self.map_sha = self.resolve_sha(sel["map_id"], sel["map_revision"]) if self.resolve_sha else ""
        except Exception as e:  # noqa: BLE001 - any bundle problem is a reason, not a crash
            self.detail = f"map {sel['map_id']} rev{sel['map_revision']} refused: {e}"
            return
        g = sel.get("graph_revision")
        if g is None:
            self.detail = f"teaching on {sel['map_id']} rev{sel['map_revision']}: no graph active"
            return
        try:
            graph, _sha = store.load(self.maps_dir, sel["map_id"], g)
        except (store.StoreError, tg.GraphError) as e:
            self.detail = f"graph g{g} refused: {e}"
            return
        why = graph.check_binding(sel["map_id"], sel["map_revision"], self.map_sha)
        if why:
            self.detail = why
            return
        self.graph = graph
        self.graph_name = f"{sel['map_id']} rev{sel['map_revision']} g{g}"
        try:
            self.route = tg.compile_route(self.shadow_circuit, self.m["CIRCUITS"][self.shadow_circuit], graph)
        except (tg.RouteError, KeyError) as e:
            self.detail = f"{self.graph_name}: {e}"
            return
        self.detail = f"{self.graph_name}: press At home at {self.m['HOME']}"

    # -- inputs --------------------------------------------------------------------
    def tick(self, t, travel, nlcp, still, uturn_phase="", pivot=False):
        """Every control tick. travel: cumulative signed wheel travel (None: unknown).
        pivot: a kink pivot or the U-turn spin turns the sensor across the tape (the node
        already feeds #LCP 0 then; the recorder notes where, to drop the corner's fork)."""
        if self.ready_t is not None and t - self.ready_t > READINESS_STALE_S and self.ready:
            self._readiness(False, "localization state stale")
        self.t = t
        if travel is None:
            return
        self.travel = travel
        self._odom.add(t, travel)
        self._still_since = (self._still_since or t) if still else None
        if self.recorder is not None:
            self.recorder.tick(t, travel, nlcp, pivot)
        loc = self.loc
        if loc is not None:
            loc.predict(t, travel)
        ep = self._forks.update(travel, nlcp)
        if ep is not None and loc is not None:
            verdict, node = loc.fork(ep[1], ep[2])
            if verdict == "unexpected":
                self.events.append((WARN, f"shadow: fork with no taught junction near S {loc.S:.2f} m "
                                          f"(sigma {loc.sigma:.2f}): would HOLD position"))
            elif verdict == "resync":
                self.events.append((INFO, f"shadow: resync at {node['id']}, S {loc.S:.2f} m"))
        self._uturn(travel, uturn_phase)
        if self.pending_home and self.ready and self.route is not None:
            self._start_locator(t, travel)
        if loc is not None and self.shadow is not None:
            self._shadow_tick(still)
        if loc is not None and loc.lost != self._was_lost and self.shadow is None:
            self.events.append((WARN, f"trip locator LOST - {loc.lost}") if loc.lost
                               else (INFO, f"trip locator re-acquired at S {loc.S:.2f} m"))
            self._was_lost = loc.lost

    def _uturn(self, travel, phase):
        prev, self._uturn_phase = self._uturn_phase, phase or ""
        # Into "stopping" from the approach, or straight from following (a strip read in the
        # last 0.3 m, the guide page's forced U-turn, a Start at the tape end): one U-turn.
        if phase == "stopping" and prev in ("", "approach") and self.recorder is not None:
            self.recorder.uturn(travel)
        if prev in ("spin", "center", "settle") and not phase and self.loc is not None:
            near = [n for n in self.loc.route.nodes if n["kind"] == "uturn"]
            node = min(near, key=lambda n: abs(n["S"] - self.loc.S)) if near else None
            if node is not None and abs(node["S"] - self.loc.S) <= max(3 * self.loc.sigma, 1.0):
                self.loc.uturn_done(node["id"])
                self.events.append((INFO, f"shadow: U-turn {node['id']} done, S {self.loc.S:.2f} m"))
            else:
                self.events.append((WARN, "shadow: U-turn where the route has none: would HOLD position"))

    def amcl(self, t, stamp, x, y, yaw, cov_xx, cov_xy, cov_yy):
        self._poses.append((stamp, x, y, yaw))
        if self.recorder is not None:
            self.recorder.pose(stamp, x, y)
        if self.loc is None:
            return
        _, _, h = self.route.point(self.loc.S)
        c, s = math.cos(h), math.sin(h)
        var = cov_xx * c * c + 2 * cov_xy * c * s + cov_yy * s * s
        self.loc.correct(t, stamp, x, y, var)

    def readiness(self, t, state, reason=""):
        self.ready_t = t
        if state == READY:
            self._readiness(True, "")
        elif state in LOST_STATES:
            self._readiness(False, reason or ("LOST" if state == 3 else "UNLOCALIZED"))
        else:
            self._readiness(False, "")      # CHECKING: no corrections, not LOST

    def _readiness(self, ready, why):
        self.ready, self.ready_why = ready, why
        if self.loc is not None:
            self.loc.readiness(ready, why)

    # -- the locator -----------------------------------------------------------------
    def at_home(self):
        """(ok, message, pose or None to publish on /initialpose)."""
        if self.route is None:
            return False, f"At home: no route ({self.detail})", None
        st = self.graph.stations.get(self.m["HOME"])
        self.pending_home = True
        self.loc = self.shadow = None
        return (True, f"At home: initial pose {self.m['HOME']} sent; confirm the scans align",
                st.pose)

    # -- trips (tracked plan 4) --------------------------------------------------------
    def compile_trip(self, trip):
        """trip.Trip -> trip_route.TripRoute on the active graph (RouteError when it cannot)."""
        if self.graph is None:
            raise tg.RouteError(f"no active tape graph ({self.detail})")
        return trip_route.compile_trip(trip, self.m, self.graph, junction_lead_m=self.p.junction_lead_m,
                                       areas=self._areas())

    def _areas(self):
        """The high-speed areas of the active map revision, read fresh: an area drawn on the map
        counts from the next trip on, with no rebuild."""
        return store.load_areas(self.state_dir, self.sel["map_id"], self.sel["map_revision"]) \
            if self.sel is not None else {}

    def begin_trip(self, route):
        """Move the locator onto the trip's route, where it is now relative to HOME. (ok, msg)."""
        loc = self.loc
        if loc is None or loc.lost or self.travel is None:
            return False, "trip: the tape locator is not running"
        off = self._home_offset()
        if off is None:
            return False, "trip: the locator is not near HOME"
        new = tl.TapeLocator(route, self.p, self.graph)
        new.readiness(self.ready)
        new.start(route.S_start + off, loc.sigma, self.t or 0.0, self.travel)
        self.loc, self.shadow, self._was_lost = new, None, ""
        self.events.append((INFO, f"trip locator on {route.label} at S {new.S:.2f} m (HOME {off:+.2f} m), "
                                  f"sigma {new.sigma:.3f} m"))
        return True, ""

    def _home_offset(self):
        """S minus HOME's S on the locator's route (HOME is its start and its end)."""
        loc = self.loc
        if loc is None:
            return None
        r = loc.route
        return min((loc.S - r.S_start, loc.S - r.S_end), key=abs)

    def loc_state(self):
        """What a trip acts on (job.Inputs.loc), or None without a locator."""
        loc = self.loc
        if loc is None:
            return None
        r = loc.route
        return {"route": getattr(r, "ident", f"circuit:{r.circuit}"), "started": loc.started, "S": loc.S,
                "sigma": loc.sigma, "health": loc.health, "lost": loc.lost,
                "wrong_branch": loc.wrong_branch, "home_offset": self._home_offset()}

    def _start_locator(self, t, travel):
        self.pending_home = False
        self.loc = tl.TapeLocator(self.route, self.p, self.graph)
        self.loc.readiness(True)
        self.loc.start(self.route.S_start, START_SIGMA_M, t, travel)
        self.shadow = self._new_shadow()
        self._was_lost = ""
        self.events.append((INFO, f"shadow: locator started at {self.m['HOME']} on {self.route.circuit}"))

    def _new_shadow(self):
        """The lap's would-be decisions, the plan-4 positions on the circuit included: a taught
        mid-line U-turn point where it would stop and pivot, where the circuit enters and leaves
        each high-speed area (E2: the log is checked against the floor before the engine drives)."""
        points = []
        for pid in self.m.get("POINTS", {}):
            st = self.graph.stations.get(pid) if self.graph else None
            hit = next((s0 + st.s - lo for s0, leg, lo, _hi in self.route.segments
                        if st and leg.id == st.leg), None)
            if hit is not None:
                what = f"U-turn point of {self.m['UTURN_POINTS'][pid]['machine']}"
                points.append((hit - self.m["STOP_DISTANCE_M"], pid, what))
        for a, b, aid in trip_route.area_ranges(self.route.segments, self._areas()):
            points += [(a, aid, "high-speed area: HIGH from"), (b, aid, "high-speed area: NORMAL by")]
        return tl.Shadow(self.route, self.p, self.m["STOP_DISTANCE_M"], self.m["UTURNS"], points,
                         self.m["CIRCUITS"][self.route.circuit].get("steers"))

    def _shadow_tick(self, still):
        loc = self.loc
        self.events += self.shadow.tick(loc)
        if loc.lost != self._was_lost:
            self.events.append((WARN, f"shadow: LOST - {loc.lost}") if loc.lost
                               else (INFO, f"shadow: re-acquired at S {loc.S:.2f} m"))
            self._was_lost = loc.lost
        if loc.S >= self.route.S_end or (still and self.shadow.done):
            # Back at HOME (past the end, or every decision logged and standing there):
            # the next lap starts where this one ended.
            loc.S -= self.route.S_end - self.route.S_start
            self.shadow = self._new_shadow()
            self.events.append((INFO, f"shadow: lap complete at {self.m['HOME']}, sigma {loc.sigma:.3f} m"))

    # -- teaching --------------------------------------------------------------------
    def _need_map(self):
        if self.sel is None:
            return "no map selected: teach map <map_id> <revision>, then restart LINE"
        if not self.map_sha:
            return self.detail or "the selected map did not verify"
        return ""

    def teach(self, t, action, arg=""):
        """(ok, message). Engineer actions; the web gates them by PIN."""
        fn = getattr(self, f"_t_{action}", None)
        if fn is None:
            return False, (f"unknown teach action {action!r}: map, pass_start, pass_stop, pass_discard, "
                           f"passes, pass_delete, station, mark, marks, mark_delete, mark_role, mark_offset, "
                           f"mark_along, roles, build, publish, activate, status")
        try:
            return fn(t, (arg or "").strip())
        except (store.StoreError, tg.GraphError, tt.TeachError, ValueError) as e:
            return False, f"{action}: {e}"

    def _t_status(self, _t, _arg):
        rec = f"; recording {self.recorder.summary()}" if self.recorder else ""
        staged = f"; built: {len(self.staged.legs)} legs, {len(self.staged.stations)} stations" \
            if self.staged else ""
        return True, f"{self.detail}{rec}{staged}"

    def _t_map(self, _t, arg):
        parts = arg.split()
        if len(parts) != 2:
            return False, "map <map_id> <revision>"
        map_id, rev = parts[0], int(parts[1])
        sha = self.resolve_sha(map_id, rev) if self.resolve_sha else ""
        store.write_active(self.state_dir, map_id, rev, None, "")
        return True, (f"teaching map {map_id} rev{rev} ({sha[:12]}) selected: it is loaded when LINE "
                      f"starts next (Home -> More -> Restart tape layer, or a service restart)")

    def _t_pass_start(self, t, arg):
        why = self._need_map()
        if why:
            return False, why
        if arg not in self.m["CIRCUITS"]:
            return False, f"circuit {arg!r}: expected one of {sorted(self.m['CIRCUITS'])}"
        if not self.ready:
            return False, f"localization is not READY ({self.ready_why or 'confirm the scans align'})"
        if self.recorder is not None:
            return False, f"already recording {self.recorder.circuit}: pass_stop or pass_discard first"
        self.recorder = tt.PassRecorder(arg, started=tt.now_iso())
        return True, f"recording a {arg} pass: start at {self.m['HOME']}, drive the circuit, stop there"

    def _t_pass_stop(self, _t, _arg):
        if self.recorder is None:
            return False, "not recording"
        rec, self.recorder = self.recorder, None
        # Saved in every case (2026-10-24): a lap costs minutes on the floor, and Build re-tries
        # every saved pass with the current matcher. One that still does not match is skipped
        # (REFUSED in the Build report); delete it once it is known to be a wrong route.
        name = store.save_pass(self.state_dir, self.sel["map_id"], self.sel["map_revision"], rec.to_dict())
        notes = []
        try:
            tt.split_pass(rec.to_dict(), self.m, notes, self._anchors())
        except tt.TeachError as e:
            return False, (f"pass {name} saved but it does NOT match yet: {e} ({rec.summary()}); "
                           f"Build skips it")
        extra = f"; {'; '.join(notes)}" if notes else ""
        return True, f"pass {name} saved: {rec.summary()}{extra}"

    def _anchors(self):
        return store.load_anchors(self.state_dir, self.sel["map_id"], self.sel["map_revision"])

    def _t_pass_discard(self, _t, _arg):
        was, self.recorder = self.recorder, None
        return (True, "pass discarded") if was else (False, "not recording")

    def _t_passes(self, _t, _arg):
        why = self._need_map()
        if why:
            return False, why
        names = store.list_passes(self.state_dir, self.sel["map_id"], self.sel["map_revision"])
        return True, ", ".join(names) if names else "no passes recorded"

    def _t_pass_delete(self, _t, arg):
        why = self._need_map()
        if why:
            return False, why
        ok = store.delete_pass(self.state_dir, self.sel["map_id"], self.sel["map_revision"], arg)
        return ok, f"pass {arg} deleted" if ok else f"no pass {arg}"

    def _binding(self):
        return {"map_id": self.sel["map_id"], "map_revision": int(self.sel["map_revision"]),
                "map_sha256": self.map_sha}

    def _t_build(self, _t, _arg):
        why = self._need_map()
        if why:
            return False, why
        sel = self.sel
        passes = store.load_passes(self.state_dir, sel["map_id"], sel["map_revision"])
        stations = store.load_stations(self.state_dir, sel["map_id"], sel["map_revision"]).values()
        self.staged, report = tt.build(passes, self.m, self._binding(), stations=stations,
                                       anchors=self._anchors())
        missing = []
        for cid, c in self.m["CIRCUITS"].items():
            try:
                tg.compile_route(cid, c, self.staged)
            except tg.RouteError as e:
                missing.append(str(e))
        report += self._reproject_marks(self.staged)
        return True, "; ".join(report + (missing or ["every circuit compiles"]))

    # -- marks (2026-10-24): positions marked from the moving vehicle, roles given later ----
    def _t_mark(self, t, arg):
        why = self._need_map()
        if why:
            return False, why
        graph = self.staged or self.graph
        if graph is None:
            return False, "no legs: build (or activate a graph) first"
        # Not READY does not refuse a mark (2026-10-24 15:14: one 0.15 m AMCL correction on the
        # trunk latched LOST and refused every mark after it): what a mark needs is a fresh
        # AMCL pose. It is flagged, so it can be checked on the map.
        doubt = "" if self.ready else (self.ready_why or "localization not READY")
        if not self._poses or t - self._poses[-1][0] > MARK_POSE_MAX_AGE_S:
            return False, (f"no AMCL pose in the last {MARK_POSE_MAX_AGE_S:g} s (AMCL updates on motion): "
                           f"mark while driving, or nudge the vehicle")
        stamp, x, y, yaw = self._poses[-1]
        then = self._odom.at(stamp)
        ahead = (self.travel - then) if (then is not None and self.travel is not None) else 0.0
        try:
            leg, s, d, (px, py, ph), over = tt.place_mark(graph, x, y, yaw, ahead)
        except tt.TeachError:
            # Off every built leg (2026-10-25: the first lap of a new circuit, C-BTU): kept at the
            # AMCL pose moved on by the travel since it; Build puts it on its leg once there is one.
            leg, s, over = "", 0.0, 0.0
            px, py, ph = x + ahead * math.cos(yaw), y + ahead * math.sin(yaw), yaw
        sel = self.sel
        marks = store.load_marks(self.state_dir, sel["map_id"], sel["map_revision"])
        n = 1 + max((int(k[1:]) for k in marks if k[1:].isdigit()), default=0)
        mid = f"M{n}"
        marks[mid] = {"label": arg, "leg": leg, "s": round(s, 3),
                      "pose": [round(px, 3), round(py, 3), round(ph, 4)],
                      "marked": tt.now_iso(), "lag_m": round(ahead, 3), "loc": doubt}
        store.save_marks(self.state_dir, sel["map_id"], sel["map_revision"], marks)
        extra = f"; {over:.2f} m past the leg's end, put at its end" if over > 0.01 else ""
        extra += f"; marked while {doubt}: check it on the map" if doubt else ""
        name = f" ({arg})" if arg else ""
        if not leg:
            return True, (f"{mid}{name} at ({px:.2f}, {py:.2f}), not on a built leg yet: Build puts it "
                          f"on its leg{extra}")
        return True, f"{mid}{name} on {leg} at {s:.2f} m, ({px:.2f}, {py:.2f}){extra}"

    def _t_mark_offset(self, _t, arg):
        """mark_offset <ref mark> <metres> [<new id>]: a mark on the tape the other way past the
        reference mark (the inbound stop beside an outbound release: site D17), the given distance
        along that tape (+ = the way the AGV drives there), measured on the floor (2026-10-25)."""
        return self._offset(arg, "mark_offset", same=False)

    def _t_mark_along(self, _t, arg):
        """mark_along <ref mark> <metres> [<new id>]: a mark on the reference mark's own tape, the
        given distance along it (+ = onward, the way the AGV drives there): a U-turn point past
        its machine's release stop (2026-10-25)."""
        return self._offset(arg, "mark_along", same=True)

    def _offset(self, arg, action, same):
        why = self._need_map()
        if why:
            return False, why
        parts = arg.split()
        if len(parts) not in (2, 3):
            return False, f"{action} <mark> <metres> [<new mark id>]"
        ref, d = parts[0], float(parts[1])
        graph = self.staged or self.graph
        if graph is None:
            return False, "no legs: build (or activate a graph) first"
        sel = self.sel
        marks = store.load_marks(self.state_dir, sel["map_id"], sel["map_revision"])
        mk = marks.get(ref)
        if mk is None:
            return False, f"no mark {ref!r}"
        if len(parts) == 3:
            mid = parts[2]
            if not (mid[:1] == "M" and mid[1:].isdigit()):
                return False, f"a mark id is M<number>, got {mid!r}"
            if mid in marks:
                return False, f"{mid} exists already"
        else:
            mid = f"M{1 + max((int(k[1:]) for k in marks if k[1:].isdigit()), default=0)}"
        leg, s, (px, py, ph) = tt.offset_mark(graph, mk["leg"], mk["pose"][0], mk["pose"][1], d, same=same)
        marks[mid] = {"label": f"{ref} {d:+.2f} m", "leg": leg, "s": round(s, 3),
                      "pose": [round(px, 3), round(py, 3), round(ph, 4)], "marked": tt.now_iso(),
                      "lag_m": 0.0, "loc": "", "from": ref, "offset_m": d}
        store.save_marks(self.state_dir, sel["map_id"], sel["map_revision"], marks)
        return True, f"{mid} on {leg} at {s:.2f} m ({d:+.2f} m from {ref}), ({px:.2f}, {py:.2f})"

    def _t_marks(self, _t, _arg):
        why = self._need_map()
        if why:
            return False, why
        marks = store.load_marks(self.state_dir, self.sel["map_id"], self.sel["map_revision"])
        if not marks:
            return True, "no marks"
        order = sorted(marks.items(), key=lambda kv: int(kv[0][1:]) if kv[0][1:].isdigit() else 0)
        return True, "; ".join(f"{k}{' (' + v.get('label') + ')' if v.get('label') else ''}"
                               f"{' = ' + v['role'] if v.get('role') else ''} {v['leg']} "
                               f"{v['s']:.2f} m" for k, v in order)

    def _t_mark_delete(self, _t, arg):
        why = self._need_map()
        if why:
            return False, why
        marks = store.load_marks(self.state_dir, self.sel["map_id"], self.sel["map_revision"])
        if marks.pop(arg, None) is None:
            return False, f"no mark {arg!r}"
        store.save_marks(self.state_dir, self.sel["map_id"], self.sel["map_revision"], marks)
        return True, f"{arg} deleted"

    def _t_mark_role(self, t, arg):
        """mark_role <M> <id>: the mark's pose becomes station or point <id> (tracked plan 4,
        section 2.1); "-" takes the role off again. Checked on the built legs when there are."""
        why = self._need_map()
        if why:
            return False, why
        parts = arg.split()
        if len(parts) != 2:
            return False, "mark_role <mark> <station or point>, or mark_role <mark> -"
        mid, role = parts
        sel = self.sel
        marks = store.load_marks(self.state_dir, sel["map_id"], sel["map_revision"])
        mk = marks.get(mid)
        if mk is None:
            return False, f"no mark {mid!r}"
        stations = store.load_stations(self.state_dir, sel["map_id"], sel["map_revision"])
        if role == "-":
            old = mk.pop("role", "")
            if old and stations.get(old, {}).get("mark") == mid:
                stations.pop(old)
                store.save_stations(self.state_dir, sel["map_id"], sel["map_revision"], stations)
            store.save_marks(self.state_dir, sel["map_id"], sel["map_revision"], marks)
            return True, f"{mid}: role {old or 'none'} removed"
        known = set(self.m["STATIONS"]) | set(self.m.get("POINTS", {})) | {self.m["HOME"]}
        if role not in known:
            return False, (f"{role!r} is not a station or point of {self.m['MISSION_NAME']}: "
                           f"{', '.join(sorted(known))}")
        pose = list(mk["pose"])
        graph = self.staged or self.graph
        where = ""
        if graph is not None:
            st = tt.project_station(graph, self.m, role, pose, tt.now_iso(), 0)
            graph.put_station(st)        # refuses a point off its leg
            where = f" on {st.leg} at s {st.s:.2f} m"
        notes = []
        for k, v in marks.items():
            if k != mid and v.get("role") == role:
                v.pop("role")
                notes.append(f"{k} no longer {role}")
        prev = mk.get("role")
        if prev and prev != role and stations.get(prev, {}).get("mark") == mid:
            stations.pop(prev)
            notes.append(f"{prev} untaught")
        mk["role"] = role
        stations[role] = {"id": role, "pose": pose, "taught": tt.now_iso(), "samples": 0, "mark": mid}
        store.save_stations(self.state_dir, sel["map_id"], sel["map_revision"], stations)
        store.save_marks(self.state_dir, sel["map_id"], sel["map_revision"], marks)
        extra = f"; {'; '.join(notes)}" if notes else ""
        return True, f"{mid} is {role}{where}{extra}: Build to put it in a graph"

    def _t_roles(self, _t, _arg):
        """Which stations and points are taught (and from which mark), and which are not."""
        why = self._need_map()
        if why:
            return False, why
        stations = store.load_stations(self.state_dir, self.sel["map_id"], self.sel["map_revision"])
        want = list(dict.fromkeys([self.m["HOME"], *self.m["STATIONS"], *self.m.get("POINTS", {})]))
        have = [f"{k}={stations[k].get('mark') or 'standstill'}" for k in want if k in stations]
        todo = [k for k in want if k not in stations]
        return True, f"taught: {', '.join(have) or 'none'}; not taught: {', '.join(todo) or 'none'}"

    def _reproject_marks(self, graph):
        """Marks follow re-averaged legs: each is projected again from its pose."""
        sel = self.sel
        marks = store.load_marks(self.state_dir, sel["map_id"], sel["map_revision"])
        lost = []
        for k, v in marks.items():
            x, y, h = v["pose"]
            try:
                v["leg"], s, _d, _p, _o = tt.place_mark(graph, x, y, h)
                v["s"] = round(s, 3)
            except tt.TeachError:
                lost.append(k)
        if marks:
            store.save_marks(self.state_dir, sel["map_id"], sel["map_revision"], marks)
        return [f"marks not on a built leg: {', '.join(lost)}"] if lost else []

    def _t_station(self, t, arg):
        why = self._need_map()
        if why:
            return False, why
        if not self.ready:
            return False, "localization is not READY"
        if self._still_since is None or t - self._still_since < STATION_CAPTURE_S:
            return False, f"hold the vehicle still for {STATION_CAPTURE_S:g} s first"
        poses = [p[1:] for p in self._poses if p[0] >= t - STATION_CAPTURE_S]
        if len(poses) < STATION_MIN_POSES:
            return False, (f"only {len(poses)} AMCL poses in the last {STATION_CAPTURE_S:g} s: AMCL updates "
                           f"only on motion; nudge the vehicle and hold again")
        graph = self.staged or self.graph
        if graph is None:
            return False, "no legs yet: record passes and build first"
        pose = tt.mean_pose(poses)
        st = tt.project_station(graph, self.m, arg, pose, tt.now_iso(), len(poses))
        graph.put_station(st)       # refuses a station off its leg
        store.save_station(self.state_dir, self.sel["map_id"], self.sel["map_revision"],
                           {"id": arg, "pose": list(pose), "taught": st.taught, "samples": st.samples})
        return True, f"{arg} taught on {st.leg} at s {st.s:.3f} m, {st.d * 100:+.1f} cm from the tape"

    def _t_publish(self, _t, _arg):
        if self.staged is None:
            return False, "build first"
        n = store.publish(self.maps_dir, self.staged, summary=f"mission {self.m['MISSION_NAME']}")
        return True, f"published {self.sel['map_id']} g{n}: activate {n} to use it"

    def _t_activate(self, _t, arg):
        why = self._need_map()
        if why:
            return False, why
        g, sha = store.load(self.maps_dir, self.sel["map_id"], int(arg))
        bad = g.check_binding(self.sel["map_id"], self.sel["map_revision"], self.map_sha)
        if bad:
            return False, bad
        store.write_active(self.state_dir, self.sel["map_id"], self.sel["map_revision"], int(arg), sha)
        return True, f"g{arg} active: it is loaded when LINE starts next (Home -> More -> Restart tape layer)"

    # -- outputs ---------------------------------------------------------------------
    def drain_events(self):
        out, self.events = self.events, []
        return out

    def snapshot(self):
        """LineState's loc_* fields."""
        loc = self.loc
        snap = loc.snapshot() if loc is not None else {}
        idle = "IDLE" if self.running else ""
        health = snap.get("health") or ("WAITING" if self.pending_home else idle)
        detail = (snap.get("lost") or snap.get("last_reject") or "") if loc is not None else self.detail
        return {"loc_health": health, "loc_circuit": self.route.circuit if self.route else "",
                "loc_leg": snap.get("leg", ""), "loc_s_m": float(snap.get("S", 0.0)),
                "loc_sigma_m": float(snap.get("sigma", 0.0)), "loc_rejects": int(snap.get("rejected", 0)),
                "loc_detail": detail, "loc_graph": self.graph_name,
                "teach": self.recorder.summary() if self.recorder else "",
                **self.map_identity()}

    def map_identity(self):
        """The map AMCL runs on in this layer (LineState loc_map_*), empty when it does not."""
        if not self.running:
            return {"loc_map_id": "", "loc_map_revision": 0, "loc_map_sha256": ""}
        return {"loc_map_id": str(self.sel["map_id"]), "loc_map_revision": int(self.sel["map_revision"]),
                "loc_map_sha256": self.map_sha or ""}
