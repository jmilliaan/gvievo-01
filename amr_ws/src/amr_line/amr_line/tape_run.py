"""One LINE run's mission state: route stage, speed latch, branches, stops, U-turn.

Ported 2026-10-02 from gy-demo's canworker (`_scan_route`, `_branch_scan`,
`_begin_station_stop`, `_resume_from_stop`, `_depart_route`, `_u_turn_tag`),
where all of it lived on the CAN thread. Here it is pure: no ROS, no clock of
its own, no I/O. FollowJob owns one, feeds it a frozen RFID snapshot and the
follower each tick, and acts on what it asks for:

    stop          {"kind": "station", "tag", "where", "distance_m"} while a
                  measured stop is in progress or parked at a station
    uturn_req     {"tag", "direction"} from the U-turn tag until the turn ends
    fault         a route-guard failure: the run must end, somebody must look
    events        (level, text) pairs for the operator, drained by the node

The RFID snapshot is agv_core.drivers.rfid's: comms_ok, encounter_seq,
generation, encounters [(seq, tag), ...], tag_age_s. Each encounter is
consumed exactly once; a seq gap is a buffer overrun and a generation change is
a reconnect, and under route_guard either one ends the run because the route
position can no longer be trusted.

No mission (or "empty") is plain line following: nothing here ever asks for
anything, and the follower runs at AUTO_RPM with a STRAIGHT branch order.
"""

from agv_core import config as vehicle

from amr_line import branch, route, uturn

INFO, WARN = "info", "warn"


def u_turn_error(sensor):
    """Nearest track's error in the follower's sign, and the MLS track level."""
    sensor = sensor or {}
    usable = [t for t in sensor.get("tracks") or () if abs(t["pos_mm"]) <= vehicle.SENSOR_MAX_MM]
    level = sensor.get("track_level")
    if not usable:
        return None, level
    pos = min(usable, key=lambda t: abs(t["pos_mm"]))["pos_mm"]
    return (-pos if vehicle.INVERT_ERROR else pos), level


class TapeRun:
    def __init__(self, mission=None):
        from agv_core import mission as missions  # noqa: PLC0415

        m = mission or missions.parse(missions.EMPTY)
        self.mission = m
        self.name = m["MISSION_NAME"]
        self.route = route.Route(m["ROUTE"], m["ROUTE_GUARD"])
        self.branch = branch.BranchEngine(
            m["BRANCH_LATCH"], positive_is_left=vehicle.BRANCH_POSITIVE_IS_LEFT, default=m["BRANCH_DEFAULT"]
        )
        self.u_turn_tags = dict(m["U_TURN_TAGS"])
        self.stop_tags = dict(m["STOP_TAGS"])
        self.stop_tags_any = dict(m["STOP_TAGS_ANY"])
        self.events: list[tuple[str, str]] = []
        self.fault: str | None = None
        self.stop: dict | None = None
        self.uturn_req: dict | None = None
        self.uturn: uturn.UTurn | None = None
        self.uturn_last: dict | None = None
        self.uturn_skip: str | None = None
        self.uturn_skip_m = 0.0
        self.last_encounter: dict | None = None
        self._cursor = 0
        self._generation = None
        self._reconnect_pending = False
        self._departure_tag: str | None = None
        self._departure_at: float | None = None

    @property
    def active(self):
        """Does this run carry anything beyond plain line following?"""
        m = self.mission
        return bool(m["ROUTE"] or m["STOP_TAGS"] or m["BRANCH_LATCH"] or m["U_TURN_TAGS"])

    # -- RFID cursor -------------------------------------------------------
    def sync(self, rfid):
        """Not running: everything read so far is history, not route input."""
        rfid = rfid or {}
        self._cursor = rfid.get("encounter_seq", 0)
        self._generation = rfid.get("generation", 0)
        self._reconnect_pending = False

    def _fail(self, reason):
        self.route.invalidate(reason)
        self.fault = self.fault or (reason + "; return to the first station and re-arm")

    def depart(self, now, rfid, resumed_tag=None):
        """Start (or resume from a station) committed. Raises nothing: a refused
        departure sets .fault and the job ends the run."""
        if self.route.guard_error:
            self._fail(self.route.guard_error)
            return
        if self.route.guarded and not (rfid or {}).get("comms_ok", False):
            self._fail("route guard: RFID connection required")
            return
        self.sync(rfid)
        if self.route.parked:
            self._departure_tag, self._departure_at = self.route.current.tag, now
        elif resumed_tag is not None:
            # No route stage to advance: suppress re-reads of the tag just left.
            self._departure_tag, self._departure_at = resumed_tag, now
        self.route.depart()
        self.stop = None
        if self.route.enabled:
            self.events.append(
                (INFO, f"departing station {self.route.current.id}, {self.route.direction} toward {self.route.next.id}")
            )

    def advance(self, distance_m):
        try:
            notice = self.route.advance(distance_m)
        except route.RouteError as exc:
            self._fail(str(exc))
            return
        if notice:
            self.events.append((WARN, notice))
        if self.uturn_skip is not None:
            self.uturn_skip_m += max(0.0, distance_m)
            if self.uturn_skip_m > vehicle.U_TURN_STOP_DISTANCE_M + uturn.REARM_MARGIN_M:
                self.uturn_skip = None

    def scan(self, now, rfid, driving, follower):
        """Consume the frozen, ordered batch once. Returns the tags, in order,
        for the branch ladder - which sees every one, held or not."""
        rfid = rfid or {}
        seq = rfid.get("encounter_seq", 0)
        generation = rfid.get("generation", 0)
        changed = self._generation is not None and generation != self._generation
        connected = bool(rfid.get("comms_ok", False))
        if self.route.guarded and (changed or not connected):
            self._generation, self._cursor = generation, seq
            self._fail("route guard: RFID continuity lost")
            return []
        if not connected:
            self._reconnect_pending = True
        if connected and (changed or self._reconnect_pending):
            self.events.append(
                (WARN, "RFID link re-established mid-run; a station may have been missed. "
                       "Check route position before continuing.")
            )
            self._reconnect_pending = False
        if changed or not connected:
            self._generation, self._cursor = generation, seq
            return []
        self._generation = generation
        pending = [(n, t) for n, t in rfid.get("encounters", ()) if n > self._cursor]
        if pending and pending[0][0] != self._cursor + 1:
            self._cursor = seq
            self._fail("RFID encounter buffer overrun; route position must be checked")
            return []
        self._cursor = seq
        # At startup the first physical read can arrive AFTER Start. Treat that
        # as the station being departed, not the next equal-valued tag.
        age = rfid.get("tag_age_s")
        clear = vehicle.RFID_TAG_CLEAR_S
        if (self._departure_tag is not None and now - self._departure_at >= clear
                and (age is None or age >= clear)):
            self._departure_tag = None
        tags = []
        for number, tag in pending:
            tags.append(tag)
            if self._departure_tag is not None:
                if tag == self._departure_tag:
                    self._record(now, number, tag, "suppressed", "departed station repeat")
                    continue
                self._departure_tag = None
            # Reads while stopped cannot advance logical position: a dwell or a
            # recovery must not accumulate future stops.
            if not driving or self.stop is not None or self.uturn_req is not None:
                self._record(now, number, tag, "suppressed", "route held or stopped")
                continue
            if tag in self.u_turn_tags:
                self._u_turn_tag(now, number, tag, follower)
                continue
            station = self.route.encounter(tag)
            notice = self.route.notice
            if notice:
                self.events.append((WARN, notice))
            # A mission without a route still stops at its station tags, by tag.
            routeless_stop = not self.route.enabled and tag in self.stop_tags_any
            if station is not None or routeless_stop:
                self._begin_station_stop(tag, follower)
            action = ("fault" if self.route.guard_error else
                      "station accepted" if station is not None or routeless_stop else
                      "early arrival rejected" if notice else
                      "no route action")
            self._record(now, number, tag, action, notice or self.route.guard_error,
                         station.id if station else None)
        if self.route.guard_error and not self.fault:
            self._fail(self.route.guard_error)
        return tags

    def _record(self, now, sequence, tag, action, reason=None, station=None):
        self.last_encounter = dict(sequence=sequence, tag=tag, action=action, reason=reason,
                                   station=station, at=now)

    # -- stations ------------------------------------------------------------
    def _begin_station_stop(self, tag, follower):
        if self.route.enabled:
            rule = self.stop_tags.get((self.route.direction, tag))
            where = f"station {self.route.current.id} tag {tag}"
        else:
            rule = self.stop_tags_any.get(tag)
            where = f"station tag {tag}"
        if rule is None:
            self._fail(f"missing stop rule: {self.route.direction} tag {tag}")
            return
        dist = rule["stop_distance_m"]
        rate = follower.begin_measured_stop(dist)
        self.stop = {"kind": "station", "tag": tag, "where": where, "distance_m": dist}
        self.events.append((INFO, f"{where} - stopping over {dist:.2f} m"
                            + (f" ({rate:.0f} r/min/s)" if rate else "") + ", press Start to go on"))

    # -- branches ------------------------------------------------------------
    def steer(self, sensor, tags, followed_mm):
        """Scan each new tag, then the no-tag fork scan. Returns (choice, slow)."""
        nlcp = (sensor or {}).get("nlcp")
        for tag in tags:
            self._branch_scan(nlcp, tag)
        self._branch_scan(nlcp, None)
        was = self.branch.unhonoured
        _, choice = self.branch.choose(nlcp, (sensor or {}).get("tracks"), followed_mm)
        if self.branch.unhonoured and not was:
            self.events.append((WARN, f"branch {choice} ordered, but that side is not in this "
                                      f"diverter - carrying straight on"))
        return choice, self.branch.slow

    def _branch_scan(self, nlcp, tag):
        was, was_slow, was_forks = self.branch.ladder.intent(), self.branch.slow, self.branch.forks
        intent = self.branch.scan(tag, nlcp)
        if intent != was:
            if intent != branch.STRAIGHT:
                self.events.append((INFO, f"branch {intent} (tag {tag})"))
            elif self.branch.forks != was_forks:
                self.events.append((INFO, f"branch {was} taken - order consumed at the fork"))
            else:
                self.events.append((INFO, f"branch cleared (tag {tag})"))
        if self.branch.slow != was_slow:
            self.events.append((INFO, f"slow zone {'entered' if self.branch.slow else 'left'} (tag {tag})"))

    # -- U-turn ----------------------------------------------------------------
    def _u_turn_tag(self, now, number, tag, follower):
        if tag == self.uturn_skip:
            self.uturn_skip = None
            self._record(now, number, tag, "suppressed", "own U-turn tag passed after turning")
            return
        direction = self.u_turn_tags[tag]
        dist = vehicle.U_TURN_STOP_DISTANCE_M
        rate = follower.begin_measured_stop(dist)
        self.uturn_req = {"tag": tag, "direction": direction}
        self.uturn = None
        self.uturn_last = None
        self._record(now, number, tag, f"u-turn {direction}")
        self.events.append((INFO, f"U-turn tag {tag} ({direction}) - stopping over {dist:.2f} m"
                            + (f" ({rate:.0f} r/min/s)" if rate else "")))

    def begin_spin(self, sensor, counts, counts_per_rev):
        """Stopped over the tag: start the pivot. Returns why not, or None."""
        if not counts_per_rev:
            return "U-turn needs the drive encoder scale (counts_per_wheel_rev on /wheel_states)"
        e_mm, level = u_turn_error(sensor)
        if e_mm is None or level is None:
            return "no tape under the sensor at U-turn start"
        if counts is None:
            return "U-turn encoder position (/wheel_states counts) unavailable"
        self.uturn = uturn.UTurn(self.uturn_req["direction"], counts_per_rev, counts, level)
        self.events.append((INFO, f"U-turn {self.uturn_req['direction']} - pivoting at "
                                  f"{vehicle.AUTO_U_TURN_RPM:.0f} r/min, start track level {level}"))
        return None

    def finish_u_turn(self):
        req, angle = self.uturn_req, self.uturn.angle_deg
        self.uturn_last = dict(self.uturn_snapshot() or {}, active=False)
        self.uturn = self.uturn_req = None
        self.uturn_skip, self.uturn_skip_m = req["tag"], 0.0
        self.events.append((INFO, f"U-turn {req['direction']} complete at {angle:.0f} deg by encoder, "
                                  f"centred - resuming"))

    def abort_u_turn(self):
        self.uturn = self.uturn_req = None

    def uturn_snapshot(self):
        req = self.uturn_req
        if req is None:
            return self.uturn_last
        snap = {"active": True, "phase": "stopping", "direction": req["direction"],
                "angle_deg": 0.0, "tape_lost": False, "reason": None}
        if self.uturn is not None:
            snap.update(self.uturn.snapshot())
        snap["tag"] = req["tag"]
        return snap

    def drain_events(self):
        out, self.events = self.events, []
        return out
