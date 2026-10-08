"""One LINE run's mission state: the RFID tag table, branches, speed, stops, U-turn.

Schema v2 (2026-10-08): the mission is the site's tag reference table
(agv_core.mission). Pure: no ROS, no clock of its own, no I/O. FollowJob owns
one, feeds it a frozen RFID snapshot and the follower each tick, and acts on
what it asks for:

    stop          {"kind": "station", "tag", "where", "role", "distance_m"} while
                  a measured stop is in progress or parked at a stop
    uturn_req     {"tag", "direction", "approach_mps", "max_approach_m", "phase",
                  "travel_m", "level"} from the U-turn tag until the turn ends.
                  phase: approach (creep until the tape ends) -> stopping -> the
                  pivot (self.uturn, amr_line.uturn)
    link_lost     why the RFID stream can no longer be trusted while driving
                  (link down, reconnect, buffer overrun): the job holds the
                  vehicle for a person. A missed tag here means a station or the
                  U-turn driven past.
    fault         a mission error the run cannot continue from
    events        (level, text) pairs for the operator, drained by the node

Which reads count:
    departed tag  the stop just left (or, at the first Start, the stop the
                  vehicle is parked past) is suppressed until it has left the
                  antenna field - however slowly the vehicle pulls away
    U-turn re-pass  the U-turn's own tag, driven back over after the pivot, is
                  suppressed once within the approach distance plus a margin
    ignore_s      the table row's window (amr_line.tag_table.TagTable)
    held          reads while stopped or held cannot start a stop or a U-turn

Speed toggles and branch tags are honoured held or driving: a toggle or a
branch exit passed during a hold must still take effect.

No mission (or "empty") is plain line following: nothing here ever asks for
anything, and the follower runs at AUTO_RPM with the default branch order.
"""

from agv_core import config as vehicle

from amr_line import branch, speed_toggle, tag_table, uturn

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
    def __init__(self, mission=None, destination=None):
        from agv_core import mission as missions  # noqa: PLC0415

        m = mission or missions.parse(missions.EMPTY)
        self.mission = m
        self.name = m["MISSION_NAME"]
        self.table = tag_table.TagTable(m, destination)
        self.branch = branch.BranchEngine(
            m["BRANCH_LATCH"], positive_is_left=vehicle.BRANCH_POSITIVE_IS_LEFT, default=m["BRANCH_DEFAULT"]
        )
        toggles = [r for r in m["TAGS"].values() if r["action"] == "speed_toggle"]
        self.speed = speed_toggle.SpeedToggle(m["TOGGLE_TAGS"], toggles[0]["ignore_s"] if toggles else 0.0)
        self.ramp_s = toggles[0]["ramp_s"] if toggles else None
        self.speed_changing = False
        self.events: list[tuple[str, str]] = []
        self.fault: str | None = None
        self.link_lost: str | None = None
        self.stop: dict | None = None
        self.uturn_req: dict | None = None
        self.uturn: uturn.UTurn | None = None
        self.uturn_last: dict | None = None
        self.uturn_skip: str | None = None
        self.uturn_skip_m = 0.0
        self.uturn_rearm_m = 0.0
        self.last_encounter: dict | None = None
        self._cursor = 0
        self._generation = None
        self._departure_tag: str | None = None
        self._departure_at: float | None = None

    @property
    def active(self):
        """Does this run carry anything beyond plain line following?"""
        return bool(self.mission["TAGS"] or self.mission["BRANCH_LATCH"])

    # -- RFID cursor -------------------------------------------------------
    def sync(self, rfid):
        """Not running: everything read so far is history, not route input."""
        rfid = rfid or {}
        self._cursor = rfid.get("encounter_seq", 0)
        self._generation = rfid.get("generation", 0)
        self.link_lost = None

    def depart(self, now, rfid, resumed_tag=None):
        """Start (or resume from a stop) committed.

        resumed_tag is the stop being left. At the first Start there is none, so
        the last tag encountered stands in when it is a stop: a vehicle parked
        past Home must not stop at Home again on its first read of the tag.
        """
        rfid = rfid or {}
        if resumed_tag is None:
            enc = rfid.get("encounters") or ()
            last = enc[-1][1] if enc else None
            row = self.table.row(last) if last else None
            if row is not None and row["action"] == "stop":
                resumed_tag = last
        self.sync(rfid)
        if resumed_tag is not None:
            self._departure_tag, self._departure_at = resumed_tag, now
            self.table.departed(now, resumed_tag)
        self.stop = None
        if self.table.destination:
            self.events.append((INFO, f"departing for {self.table.destination}"))

    def advance(self, distance_m):
        if self.uturn_skip is not None:
            self.uturn_skip_m += max(0.0, distance_m)
            if self.uturn_skip_m > self.uturn_rearm_m:
                self.uturn_skip = None

    def _lose_link(self, why):
        if self.active and self.link_lost is None:
            self.link_lost = why

    def scan(self, now, rfid, driving, follower):
        """Consume the frozen, ordered batch once. Returns the tags, in order,
        for the branch ladder - which sees every one, held or not."""
        rfid = rfid or {}
        seq = rfid.get("encounter_seq", 0)
        generation = rfid.get("generation", 0)
        changed = self._generation is not None and generation != self._generation
        connected = bool(rfid.get("comms_ok", False))
        if changed or not connected:
            self._generation, self._cursor = generation, seq
            self._lose_link("RFID link lost" if not connected
                            else "RFID link re-established mid-run: a tag may have been missed")
            return []
        self._generation = generation
        pending = [(n, t) for n, t in rfid.get("encounters", ()) if n > self._cursor]
        if pending and pending[0][0] != self._cursor + 1:
            self._cursor = seq
            self._lose_link("RFID encounter buffer overrun: tags were missed")
            return []
        self._cursor = seq
        # The departed tag stays suppressed until it has left the field.
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
                    self._record(now, number, tag, "suppressed", "departed stop, still in the field")
                    continue
                self._departure_tag = None
            row = self.table.row(tag)
            if row is None:
                self._record(now, number, tag, "no tag rule")
                continue
            if row["action"] == "speed_toggle":
                self._speed_tag(now, number, tag, driving and self.stop is None)
                continue
            left = self.table.window_left(now, tag)
            if left > 0:
                self._record(now, number, tag, "ignored", f"ignore window, {left:.1f} s left")
                continue
            # Reads while stopped cannot start anything: a dwell or a recovery
            # must not queue up stops.
            if not driving or self.stop is not None or self.uturn_req is not None:
                self._record(now, number, tag, "suppressed", "held or stopped")
                continue
            if row["action"] == "u_turn":
                self._u_turn_tag(now, number, row)
                continue
            applies, why = self.table.stop_applies(row)
            self.table.acted(now, tag)
            if not applies:
                self._record(now, number, tag, f"passed {row['label']}", why)
                self.events.append((INFO, f"passed {row['label']} (tag {tag}): {why}"))
                continue
            self._begin_stop(row, follower)
            self._record(now, number, tag, f"stop {row['label']}")
        return tags

    def _record(self, now, sequence, tag, action, reason=None):
        self.last_encounter = dict(sequence=sequence, tag=tag, action=action, reason=reason, at=now)

    # -- stops ---------------------------------------------------------------
    def _begin_stop(self, row, follower):
        dist = row["stop_distance_m"]
        rate = follower.begin_measured_stop(dist)
        if row["role"] == "destination":
            self.table.reached = True
        self.speed_changing = False
        self.stop = {"kind": "station", "tag": row["tag"], "where": row["label"], "role": row["role"],
                     "distance_m": dist}
        then = "run complete" if row["role"] == "home" else "press Start to go on"
        self.events.append((INFO, f"{row['label']} (tag {row['tag']}) - stopping over {dist:.2f} m"
                            + (f" ({rate:.0f} r/min/s)" if rate else "") + f", {then}"))

    # -- speed toggle ----------------------------------------------------------
    def _speed_tag(self, now, number, tag, moving):
        result = self.speed.scan(now, tag)
        if result == "lockout":
            left = self.speed.lockout_s - (now - self.speed.changed_at)
            self._record(now, number, tag, "speed toggle ignored", f"lockout, {left:.1f} s left")
            return
        # Only a change made while cruising is spread over ramp_s; from rest the
        # vehicle accelerates on the profile ramp like any other start.
        self.speed_changing = moving
        self._record(now, number, tag, f"speed {result}")
        self.events.append((INFO, f"speed {'SLOW' if self.speed.slow else 'CRUISE'} (toggle tag {tag})"))

    def change_rate(self):
        """r/min/s for a speed change in progress, None when the profile ramp applies."""
        if not self.speed_changing or not self.ramp_s:
            return None
        return abs(vehicle.AUTO_RPM - vehicle.AUTO_SLOW_RPM) / self.ramp_s

    def speed_settled(self, v_base, target):
        if self.speed_changing and abs(v_base - target) < 1.0:
            self.speed_changing = False

    @property
    def slow(self):
        """Either reason to run at auto_slow_rpm: a junction slow zone or the toggle."""
        return self.branch.slow or self.speed.slow

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
        return choice, self.slow

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
    def _u_turn_tag(self, now, number, row):
        tag = row["tag"]
        if tag == self.uturn_skip:
            self.uturn_skip = None
            self._record(now, number, tag, "suppressed", "own U-turn tag passed after turning")
            return
        self.table.acted(now, tag)
        missed = self.table.note_u_turn()
        if missed:
            self.events.append((WARN, f"destination {missed} not reached before the U-turn: its tag "
                                      f"was missed. It will not be served from the return leg."))
        self.speed_changing = False
        self.uturn_req = {"tag": tag, "direction": row["direction"], "approach_mps": row["approach_mps"],
                          "max_approach_m": row["max_approach_m"], "phase": "approach",
                          "travel_m": 0.0, "level": None}
        self.uturn = None
        self.uturn_last = None
        self._record(now, number, tag, f"u-turn {row['direction']}")
        self.events.append((INFO, f"U-turn tag {tag} - creeping at {row['approach_mps']:.2f} m/s "
                                  f"to the end of the tape"))

    def approach(self, sensor, has_track, line_lost, distance_m):
        """One tick of the creep to the tape end. Returns a fault reason or None."""
        req = self.uturn_req
        if req["phase"] != "approach":
            return None
        if has_track:
            level = (sensor or {}).get("track_level")
            if level is not None:
                req["level"] = level
        req["travel_m"] += max(0.0, distance_m)
        if line_lost:
            req["phase"] = "stopping"
            self.events.append((INFO, f"tape ended {req['travel_m']:.2f} m after the U-turn tag - "
                                      f"stopping to pivot {req['direction']}"))
            return None
        if req["travel_m"] > req["max_approach_m"]:
            return (f"U-turn: the tape did not end within {req['max_approach_m']:.1f} m of tag "
                    f"{req['tag']}")
        return None

    def begin_spin(self, counts, counts_per_rev):
        """Stopped past the tape end: start the pivot. Returns why not, or None.

        No tape is under the sensor here - that is the trigger - so the start
        level is the last one seen on the approach, and the spin begins 'lost':
        the sensor ahead of the axle meets the tape again only near 180 deg.
        """
        req = self.uturn_req
        if not counts_per_rev:
            return "U-turn needs the drive encoder scale (counts_per_wheel_rev on /wheel_states)"
        if req["level"] is None:
            return "no tape level recorded on the approach to the U-turn"
        if counts is None:
            return "U-turn encoder position (/wheel_states counts) unavailable"
        self.uturn = uturn.UTurn(req["direction"], counts_per_rev, counts, req["level"])
        req["phase"] = "spin"
        self.events.append((INFO, f"U-turn {req['direction']} - pivoting at "
                                  f"{vehicle.AUTO_U_TURN_RPM:.0f} r/min, track level {req['level']}"))
        return None

    def finish_u_turn(self):
        req, angle = self.uturn_req, self.uturn.angle_deg
        self.uturn_last = dict(self.uturn_snapshot() or {}, active=False)
        self.uturn = self.uturn_req = None
        # Its own tag lies about the approach distance back along the tape.
        self.uturn_skip, self.uturn_skip_m = req["tag"], 0.0
        self.uturn_rearm_m = req["travel_m"] + uturn.REARM_MARGIN_M
        self.events.append((INFO, f"U-turn {req['direction']} complete at {angle:.0f} deg by encoder, "
                                  f"centred - resuming"))

    def abort_u_turn(self):
        self.uturn = self.uturn_req = None

    def uturn_snapshot(self):
        req = self.uturn_req
        if req is None:
            return self.uturn_last
        snap = {"active": True, "phase": req["phase"], "direction": req["direction"],
                "angle_deg": 0.0, "tape_lost": False, "reason": None}
        if self.uturn is not None:
            snap.update(self.uturn.snapshot())
        snap["tag"] = req["tag"]
        return snap

    def drain_events(self):
        out, self.events = self.events, []
        return out
