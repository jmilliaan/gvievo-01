"""The one-dimensional tape locator (tracked plan 3, section 2.3). Pure and clock-fed.

State: the distance S along one compiled route (amr_line.tape_graph.Route), its
uncertainty sigma, and a health. The tape fixes lateral position and heading, so AMCL's
lateral output is only a health check (distance from the taught path).

    predict   signed forward wheel travel; sigma grows by k_odo x |travel|
    correct   an AMCL pose, taken AT ITS STAMP: the travel at the stamp comes from a
              2 s odometry buffer, the innovation is formed there and applied now
              (0.1 s of latency at 0.5 m/s is 5 cm, half the budget). Accepted only
              READY, fresh, near the taught path, and inside the innovation gate
    resync    an MLS fork episode at a known node, a completed U-turn
    health    HEALTHY  a correction accepted within healthy_window_m, sigma under the
                       station limit
              DEGRADED running on wheel travel and forks; sigma says how far to trust S
              LOST     a wrong branch only (latched until restart)

AMCL corrects S; it has no veto (2026-11-06: a trip stopped 0.4 m short of ATT, on the tape, with
AMCL 12 cm off the taught path among moved trolleys). lost_rejects rejected in a row, readiness
leaving READY or sigma over sigma_lost_m set amcl_out: S carries on from the wheels and the tape,
sigma growing, and poses count again by themselves once two in a row agree and pass the gates.

Not in the safety path (plan D6): it says where the vehicle is along the tape. It starts and
speeds up nothing.
"""

import collections
import dataclasses
import math

from amr_line import trip_route

HEALTHY, DEGRADED, LOST = "HEALTHY", "DEGRADED", "LOST"
# With amcl_out, poses count again once two in a row agree this well.
REACQUIRE_AGREE_M = 0.05
# The pose handed to AMCL from a tape position (HOME, or the survey start): 5 cm, ~1.7 deg.
INITIAL_POSE_SIGMA_XY_M = 0.05
INITIAL_POSE_SIGMA_YAW_RAD = 0.03


def initial_pose_cov():
    """The 6x6 row-major covariance for an initial pose set from the tape (x, y, yaw only)."""
    cov = [0.0] * 36
    cov[0] = cov[7] = INITIAL_POSE_SIGMA_XY_M ** 2
    cov[35] = INITIAL_POSE_SIGMA_YAW_RAD ** 2
    return cov


@dataclasses.dataclass(frozen=True)
class Params:
    """The profile's tape_loc block. Provisional values until P0 (plan section 5)."""

    k_odo: float = 0.01               # sigma growth per metre of wheel travel (P0 M6)
    amcl_sigma_floor_m: float = 0.03  # AMCL along-track sigma floor (P0 M1)
    max_lateral_m: float = 0.10       # pose farther from the taught path is rejected (P0 M2)
    innov_min_m: float = 0.10         # innovation gate floor
    pose_max_age_s: float = 0.5
    sigma_station_m: float = 0.025    # station stop limit (2 sigma <= 5 cm)
    sigma_junction_m: float = 0.20
    junction_lead_m: float = 1.0      # junction order latched by S_fork - lead
    lost_rejects: int = 5
    sigma_lost_m: float = 0.5
    healthy_window_m: float = 2.0
    wrong_branch_sep_m: float = 0.15
    wrong_branch_margin_m: float = 0.05
    wrong_branch_run_m: float = 0.5
    wrong_branch_window_m: float = 3.0
    wrong_lane_m: float = 0.5         # AMCL this far off, after an ordered fork: another tape
    wrong_lane_run_m: float = 1.5     # for this much travel, on one side
    wrong_lane_window_m: float = 12.0 # looked for this far past the fork
    wrong_lane_max_m: float = 8.0     # farther than any tape can be by then: AMCL is just wrong

    @classmethod
    def from_profile(cls, v):
        return cls(k_odo=v.TAPE_LOC_K_ODO, amcl_sigma_floor_m=v.TAPE_LOC_AMCL_SIGMA_FLOOR_M,
                   max_lateral_m=v.TAPE_LOC_MAX_LATERAL_M, innov_min_m=v.TAPE_LOC_INNOV_MIN_M,
                   pose_max_age_s=v.TAPE_LOC_POSE_MAX_AGE_S, sigma_station_m=v.TAPE_LOC_SIGMA_STATION_M,
                   sigma_junction_m=v.TAPE_LOC_SIGMA_JUNCTION_M, junction_lead_m=v.TAPE_LOC_JUNCTION_LEAD_M,
                   lost_rejects=v.TAPE_LOC_LOST_REJECTS, sigma_lost_m=v.TAPE_LOC_SIGMA_LOST_M,
                   healthy_window_m=v.TAPE_LOC_HEALTHY_WINDOW_M)


def interp_sorted(series, t):
    """Linear interpolation in a time-sorted [(t, value)] sequence, for t inside
    [first t, last t] (the caller decides what lies outside). Bisection, O(log n)."""
    lo, hi = 0, len(series) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if series[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    (t0, v0), (t1, v1) = series[lo], series[hi]
    return v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)


class OdomBuffer:
    """(t, travel) samples for span_s; interpolated travel at a past stamp."""

    def __init__(self, span_s=2.0):
        self.span_s = float(span_s)
        self._q = collections.deque()

    def add(self, t, travel):
        q = self._q
        if q and t <= q[-1][0]:
            return
        q.append((float(t), float(travel)))
        while len(q) > 2 and q[1][0] < t - self.span_s:
            q.popleft()

    def at(self, t):
        """Travel at time t, or None outside the buffer (too old, or newer than the last)."""
        q = self._q
        if not q or t < q[0][0] or t > q[-1][0] + 0.05:
            return None
        if t >= q[-1][0]:
            return q[-1][1]
        return interp_sorted(q, t)

    def clear(self):
        self._q.clear()


class TapeLocator:
    def __init__(self, route, params=None, graph=None):
        self.route = route
        self.p = params or Params()
        self.odom = OdomBuffer()
        # Wrong-branch candidates: at each ordered diverge, the other taught legs from that node.
        self._alts = {}
        if graph is not None:
            for n in route.nodes:
                if n["kind"] == "junction" and n["order"] in ("left", "right", "straight"):
                    alts = [leg for leg in graph.legs_from(n["id"]) if leg.id != n["leg_out"]]
                    if alts:
                        self._alts[n["S"]] = (n, alts)
        self._ordered = [n for n in route.nodes
                         if n["kind"] == "junction" and n["order"] in ("left", "right", "straight")]
        self._wl_run, self._wl_travel, self._wl_side = 0.0, None, 0
        self.started = False
        self.S = self.sigma = 0.0
        self.travel = None
        self.lost = ""                 # why LOST (a wrong branch), "" when not
        self.amcl_out = ""             # why AMCL is not correcting S just now, "" when it is
        self.wrong_branch = ""         # latched: the junction and the leg it fits better
        self.rejects = 0               # in a row
        self.rejected = self.accepted = 0
        self.last_reject = ""
        self.last_innov = None
        self.last_lateral = None
        self._accept_travel = None
        self._reacq = None             # last innovation seen while AMCL is not trusted
        self._wb_run = 0.0
        self._wb_travel = None
        self._ready = False

    # -- lifecycle -----------------------------------------------------------------
    def start(self, S, sigma, t, travel):
        self.started = True
        self.S, self.sigma = float(S), float(sigma)
        self.travel = float(travel)
        self.odom.clear()
        self.odom.add(t, travel)
        self.lost = self.wrong_branch = self.amcl_out = ""
        self.rejects = 0
        self._accept_travel = self.travel
        self._reacq = None
        self._wb_run, self._wb_travel = 0.0, None
        self._wl_run, self._wl_travel, self._wl_side = 0.0, None, 0

    # -- inputs ----------------------------------------------------------------------
    def predict(self, t, travel):
        """Cumulative signed forward wheel travel at time t (the node integrates the
        wheel positions; a pivot adds ~0)."""
        if self.travel is None:
            self.travel = float(travel)
        d = float(travel) - self.travel
        self.travel = float(travel)
        self.odom.add(t, travel)
        if not self.started:
            return
        self.S += d
        self.sigma += self.p.k_odo * abs(d)
        if self.sigma > self.p.sigma_lost_m and not self.amcl_out:
            self.amcl_out = f"sigma {self.sigma:.2f} m > {self.p.sigma_lost_m:g} m without a correction"

    def readiness(self, ready, why=""):
        """Readiness READY (fresh) or not. Leaving READY takes AMCL's word away, not the position."""
        if self.started and self._ready and not ready and why and not self.amcl_out:
            self.amcl_out = f"localization {why}"
        self._ready = bool(ready)

    def correct(self, now, stamp, x, y, var_along=0.0):
        """One AMCL pose. Returns "" when accepted, else why it was rejected."""
        if not self.started:
            return "not started"
        if self.wrong_branch:
            return self._reject("wrong branch latched", count=False)
        if now - stamp > self.p.pose_max_age_s:
            return self._reject(f"pose {now - stamp:.2f} s old", count=False)
        tp = self.odom.at(stamp)
        if tp is None:
            return self._reject("no odometry at the pose stamp", count=False)
        back = self.travel - tp
        S_p = self.S - back
        r = max(math.sqrt(max(var_along, 0.0)), self.p.amcl_sigma_floor_m)
        w = max(4.0 * self.sigma, 0.5)
        hit = self.route.project(x, y, S_p - w, S_p + w, hint=S_p)
        if hit is not None:
            # Any pose counts, READY or not: small errors have no say, this is not a small error.
            self._wrong_lane_check(S_p, hit[1], tp)
            if self.wrong_branch:
                return self._reject(self.wrong_branch, count=False)
        trusted = self._ready and not self.amcl_out
        if hit is not None and self._ready:
            # Before anything else: the rejections a wrong branch causes must not hide it, and they
            # are what sets amcl_out. Localization not READY has no say on the branch.
            self._wrong_branch_check(S_p, x, y, abs(hit[1]), tp)
            if self.wrong_branch:
                return self._reject(self.wrong_branch, count=False)
        if hit is None:
            return self._reject("pose projects off the route window")
        S_m, d = hit
        self.last_lateral = d
        if abs(S_m - S_p) >= w - 1e-6:
            return self._reject(f"innovation beyond the {w:.2f} m window")
        if abs(d) > self.p.max_lateral_m:
            return self._reject(f"{d:+.2f} m from the taught path")
        innov = S_m - S_p
        gate = max(3.0 * math.hypot(self.sigma, r), self.p.innov_min_m)
        if abs(innov) > gate:
            return self._reject(f"innovation {innov:+.2f} m > {gate:.2f} m")
        if not trusted:
            # The offset from the wheels, not the position: a moving AGV's positions differ by what
            # it drove between two poses (2026-11-06: 177 of 320 poses refused like that at 0.4 m/s).
            prev, self._reacq = self._reacq, innov
            if prev is None or abs(prev - innov) > REACQUIRE_AGREE_M:
                return self._reject("AMCL out: waiting for a second pose that agrees", count=False)
        k = self.sigma ** 2 / (self.sigma ** 2 + r ** 2)
        self.S += k * innov
        self.sigma = math.sqrt((1.0 - k) * self.sigma ** 2)
        self.last_innov = innov
        self.rejects = 0
        self.amcl_out = ""
        self.accepted += 1
        self._accept_travel = self.travel
        return ""

    def _reject(self, why, count=True):
        self.last_reject = why
        self.rejected += 1
        if count:
            self.rejects += 1
            self._reacq = None
            if self.rejects >= self.p.lost_rejects and not self.amcl_out:
                self.amcl_out = f"{self.rejects} corrections rejected in a row ({why})"
        return why

    def _wrong_lane_check(self, S_p, d, travel_p):
        """Far off the taught path just after an ordered fork, and staying there: the AGV is on
        another tape, taught or not (2026-11-06: J-SPLIT's right bay is not in the graph, so
        _wrong_branch_check had nothing to compare with, and a trip ended 1.26 m off, "served")."""
        p = self.p
        node = next((n for n in self._ordered if n["S"] <= S_p <= n["S"] + p.wrong_lane_window_m), None)
        side = 1 if d > 0 else -1
        if node is None or not p.wrong_lane_m <= abs(d) <= p.wrong_lane_max_m \
                or (self._wl_side and side != self._wl_side):
            self._wl_run, self._wl_travel, self._wl_side = 0.0, None, 0
            return
        if self._wl_travel is not None:
            self._wl_run += max(0.0, travel_p - self._wl_travel)
        self._wl_travel, self._wl_side = travel_p, side
        if self._wl_run >= p.wrong_lane_run_m:
            self.wrong_branch = (f"wrong tape after {node['id']}: ordered {node['order']}, AMCL is "
                                 f"{abs(d):.2f} m to the {'left' if d > 0 else 'right'} of that tape")
            self.lost = self.wrong_branch

    def _wrong_branch_check(self, S_p, x, y, d_route, travel_p):
        p = self.p
        hit = None
        for S_node, (node, alts) in self._alts.items():
            if S_node <= S_p <= S_node + p.wrong_branch_window_m:
                hit = (node, alts, S_p - S_node)
                break
        if hit is None:
            self._wb_run, self._wb_travel = 0.0, None
            return
        node, alts, into = hit
        px, py, _ = self.route.point(S_p)
        lim = into + p.wrong_branch_window_m
        for alt in alts:
            on_alt = alt.line.project(px, py, 0.0, lim)
            here = alt.line.project(x, y, 0.0, lim)
            if on_alt is None or here is None:
                continue
            sep, d_alt = abs(on_alt[1]), abs(here[1])
            if sep >= p.wrong_branch_sep_m and d_alt + p.wrong_branch_margin_m < d_route:
                if self._wb_travel is not None:
                    self._wb_run += max(0.0, travel_p - self._wb_travel)
                self._wb_travel = travel_p
                if self._wb_run >= p.wrong_branch_run_m:
                    self.wrong_branch = (f"wrong branch at {node['id']}: ordered {node['order']} "
                                         f"({node['leg_out']}), the pose fits {alt.id}")
                    self.lost = self.wrong_branch
                return
        self._wb_run, self._wb_travel = 0.0, None

    def fork(self, end_travel, crossing=False):
        """An MLS fork episode ended at wheel travel end_travel. Returns (verdict, node):
        "resync" at a known node, "unexpected" with no node within 3 sigma, "" not started."""
        if not self.started:
            return "", None
        S_e = self.S - (self.travel - end_travel)
        tol = max(3.0 * self.sigma, 0.10)
        near = [n for n in self.route.nodes if n["fork"] and abs(n["S"] - S_e) <= tol]
        best = min(near, key=lambda n: abs(n["S"] - S_e)) if near else None
        if best is None:
            return "unexpected", None
        if self.lost:
            return "resync-skipped", best
        self._measure(best["S"] - S_e, best["sigma"])
        return "resync", best

    def uturn_done(self, node_id):
        """The pivot ended at a taught tape end: S is that node's S. A mid-line U-turn node
        (amr_line.trip_route, "mirror") is no measurement: the AGV pivots on the floor point it
        stopped on, which lies as far past the node on the return leg as it stopped short of
        it on the way out - S mirrors about the node, sigma carries over."""
        n = next((n for n in self.route.nodes if n["id"] == node_id and n["kind"] == "uturn"), None)
        if n is None or not self.started or self.lost:
            return False
        if n.get("mirror"):
            self.S = 2.0 * n["S"] - self.S
            return True
        self.S, self.sigma = n["S"], max(n["sigma"], min(self.sigma, n["sigma"] * 3))
        return True

    def _measure(self, innov, r):
        """A resync as a measurement of S with its taught spread r."""
        k = self.sigma ** 2 / (self.sigma ** 2 + r ** 2)
        self.S += k * innov
        self.sigma = math.sqrt((1.0 - k) * self.sigma ** 2)
        self._accept_travel = self.travel

    # -- outputs --------------------------------------------------------------------
    @property
    def health(self):
        if not self.started:
            return ""
        if self.lost:
            return LOST
        since = self.travel - self._accept_travel
        if abs(since) <= self.p.healthy_window_m and self.sigma <= self.p.sigma_station_m \
                and not self.amcl_out:
            return HEALTHY
        return DEGRADED

    def ok_for(self, limit):
        """May a decision with this sigma limit be taken now?"""
        return self.started and not self.lost and self.sigma <= limit

    def where(self):
        """(leg id, s on it) for display."""
        _, leg, s = self.route.at(self.S)
        return leg.id, s

    def snapshot(self):
        leg, s = self.where() if self.started else ("", 0.0)
        return {"health": self.health, "S": self.S, "sigma": self.sigma, "leg": leg, "s": s,
                "lost": self.lost, "amcl_out": self.amcl_out, "rejects": self.rejects,
                "accepted": self.accepted,
                "rejected": self.rejected, "last_reject": self.last_reject,
                "lateral": self.last_lateral, "innov": self.last_innov}


class Shadow:
    """P1 shadow mode: where the locator WOULD have stopped and ordered, logged, with the
    check each decision would have met. Motion is not touched."""

    def __init__(self, route, params, stop_distance_m, uturns=None, points=(), steers=None):
        """points: [(S, id, what)] taught positions of tracked plan 4 on this route (mid-line
        U-turn points, zone ends): logged where the position engine would act on them."""
        self.p = params
        self.events = []   # (S_trigger, kind, id, detail)
        for S, ident, what in points:
            self.events.append((S, "point", ident, what))
        # The engine's own schedule (trip_route.decision_points / trigger_S) over the whole
        # circuit, so a shadow line says where the live engine would act (lean plan D13).
        turns = [{"id": n["id"], "mode": "tapeend", "S": n["S"], "lead_m": 1.5,
                  **(uturns or {}).get(n["id"], {})}
                 for n in route.nodes if n["kind"] == "uturn" and not trip_route.side_at(n, steers or {})]
        for e in trip_route.decision_points(route.stops, route.nodes, params.junction_lead_m, steers,
                                            turns, check=False):
            detail = e["order"] if e["kind"] == "order" else e["S"]
            self.events.append((trip_route.trigger_S(e, stop_distance_m), e["kind"], e["id"], detail))
        self.events.sort(key=lambda e: e[0])
        self._next = 0

    @property
    def done(self):
        """Every decision of the lap has been passed (the last is the HOME stop)."""
        return self._next >= len(self.events)

    def tick(self, loc):
        """Events whose trigger S the locator has just passed -> [(level, text)]."""
        out = []
        while self._next < len(self.events) and loc.S >= self.events[self._next][0]:
            S_t, kind, ident, detail = self.events[self._next]
            self._next += 1
            pivot = kind == "point" and detail.startswith("U-turn")
            # As site_run: only a mid-line pivot and HIGH ask for a sigma; stops, orders and the
            # tape end go on at any sigma.
            ok = (loc.ok_for(self.p.sigma_junction_m) if kind == "point"
                  else loc.started and not loc.lost)
            verdict = "ok" if ok else f"would HOLD ({loc.health}, sigma {loc.sigma:.3f})" \
                if not loc.lost else f"would HOLD (LOST: {loc.lost})"
            if kind == "point" and not pivot:
                verdict = "ok" if ok else "NORMAL (not sure enough for HIGH)"
            what = {"stop": f"stop {ident}", "order": f"order {detail} at {ident}",
                    "uturn": f"U-turn approach {ident}", "point": f"{detail} {ident}"}[kind]
            out.append(("info" if ok else "warn",
                        f"shadow: {what} at S {S_t:.2f} m, sigma {loc.sigma:.3f} m: {verdict}"))
        return out
