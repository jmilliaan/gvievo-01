"""The AGV's side of a VDA5050 3.0 RELEASE zone (contract v1.6 section 13). Pure: no ROS, no clock.

One ZoneClient lives in the job for the life of the line layer, NOT in a trip (a SiteRun): a grant
outlives the trip that asked for it (home-bound: until the trolleys are off at HOME) and the line layer
itself (a file in the state directory, 13.6).

    request(order_id, zone_id, home_bound)   -> requestId "<orderId>:<zoneId>:<n>", REQUESTED
    on_response(requestId, grantType, where) -> what the job must do (see RESPONSE_ACTIONS)
    link_seen(now) / link_up(now)            -> the bridge's heartbeat: entering needs a live link
    may_enter(requestId, now)                -> GRANTED and the link up (13.6)
    release(requestId, why)                  -> only for the four reasons in RELEASES (13.5, 13.6)

An entry is never dropped for any other reason: an abort, a Reset, a FAULT or the end of a trip keep a
GRANTED entry. A REQUESTED entry with no trip behind it is withdrawn (drop_unused): it holds nothing.
"""

import json
import os
import re

# The statuses the AGV reports (13.2). QUEUED is kept as a display flag only: the state schema has no
# such requestStatus value.
REQUESTED, GRANTED, REVOKED = "REQUESTED", "GRANTED", "REVOKED"
GRANT_TYPES = ("GRANTED", "QUEUED", "REJECTED", "REVOKED")

# The only ways a GRANTED entry is removed (advisor review 2026-11-24, contract 13.5-13.7).
RELEASES = ("tail_clear", "trolleys_off", "operator", "revoked_idle")

# Entering needs a heartbeat from the bridge this recent (13.6: "its MQTT link is up").
LINK_FRESH_S = 3.0

# Error types the bridge reports (6.3).
REJECTED_ERROR = "ZONE_REQUEST_REJECTED"
RELEASE_LOST_ERROR = "ZONE_RELEASE_LOST"

# What on_response asks the job to do.
NOTHING, HOLD_REJECTED, REREQUEST, STOP_LOST = "nothing", "hold_rejected", "rerequest", "stop_lost"
RESPONSE_ACTIONS = (NOTHING, HOLD_REJECTED, REREQUEST, STOP_LOST)

_ID = re.compile(r"^(?P<order>.+):(?P<zone>[A-Za-z0-9_-]+):(?P<n>[1-9][0-9]*)$")
FILE_NAME = "zone_grants.json"
SEQ_FILE_NAME = "zone_seq.json"    # orderId -> highest n used, kept across restarts (13.2)
SEQ_KEEP = 8                       # orders remembered: only the current one can ask again


class ZoneError(ValueError):
    pass


def parse_request_id(rid):
    """(orderId, zoneId, n), or None when it is not ours to answer."""
    m = _ID.match(rid or "")
    return (m["order"], m["zone"], int(m["n"])) if m else None


class ZoneClient:
    def __init__(self, state_dir=None, zone_set_id="SITE103-TRAFFIC-1"):
        self.zone_set_id = zone_set_id
        self.path = os.path.join(state_dir, FILE_NAME) if state_dir else None
        self.seq_path = os.path.join(state_dir, SEQ_FILE_NAME) if state_dir else None
        self.entries = {}           # requestId -> {"zone", "status", "home_bound", "restored", "queued"}
        self._link_t = None
        self.error = ("", "")       # (errorType, requestId), latest; cleared by clear_error()
        self.log = []               # (level, text) for the job's events
        self._max_n = {}            # orderId -> highest n used, so a dropped id is never reused
        self._load()
        self._load_seq()

    # -- persistence (13.6) ---------------------------------------------------------------
    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path) as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as e:
            # Fail loud and closed: a grant file we cannot read may hide a held zone.
            self.entries["?unreadable"] = {"zone": "?", "status": GRANTED, "home_bound": False,
                                           "restored": True, "queued": False}
            self.log.append(("warn", f"zone grant file unreadable ({e}): held until an operator releases it"))
            return
        for rid, row in (doc.get("grants") or {}).items():
            if row.get("status") in (GRANTED, REVOKED):
                self.entries[rid] = {"zone": row.get("zone", "?"), "status": row["status"],
                                     "home_bound": bool(row.get("home_bound")), "restored": True,
                                     "queued": False}
                self.log.append(("warn", f"zone {row.get('zone')} still held from before the restart "
                                         f"({rid}): release it on Run once the AGV is clear"))
        if doc.get("zone_set_id"):
            self.zone_set_id = doc["zone_set_id"]

    def _load_seq(self):
        """The highest n per order from before a restart. A missing or unreadable file only risks a
        repeated requestId, which the station takes as a new request once the old one is gone."""
        if not self.seq_path or not os.path.exists(self.seq_path):
            return
        try:
            with open(self.seq_path) as fh:
                doc = json.load(fh)
            self._max_n = {str(k): int(v) for k, v in doc.items()}
        except (OSError, ValueError, TypeError, AttributeError) as e:
            self.log.append(("warn", f"zone request counter unreadable ({e}): counting again from the "
                                     f"grants held"))
        for rid in self.entries:                # a held grant's n counts too
            p = parse_request_id(rid)
            if p:
                self._max_n[p[0]] = max(self._max_n.get(p[0], 0), p[2])

    def _save_seq(self):
        if not self.seq_path:
            return
        keep = dict(list(self._max_n.items())[-SEQ_KEEP:])
        self._max_n = keep
        tmp = self.seq_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(keep, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.seq_path)

    def _save(self):
        if not self.path:
            return
        held = {rid: {"zone": e["zone"], "status": e["status"], "home_bound": e["home_bound"]}
                for rid, e in self.entries.items() if e["status"] in (GRANTED, REVOKED)
                and rid != "?unreadable"}
        if not held:
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"zone_set_id": self.zone_set_id, "grants": held}, fh, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    # -- link ------------------------------------------------------------------------------
    def link_seen(self, now):
        self._link_t = now

    def link_up(self, now):
        return self._link_t is not None and now - self._link_t <= LINK_FRESH_S

    # -- requests --------------------------------------------------------------------------
    def request(self, order_id, zone_id, home_bound=False):
        """A new REQUESTED entry for this order and zone; n counts this order's requests (13.2)."""
        if not order_id:
            raise ZoneError("a zone request needs an order: local trips do not ask (owner, F)")
        n = 1 + max((p[2] for p in map(parse_request_id, self.entries) if p and p[0] == order_id),
                    default=0)
        n = max(n, 1 + self._max_n.get(order_id, 0))
        rid = f"{order_id}:{zone_id}:{n}"
        self._max_n.pop(order_id, None)
        self._max_n[order_id] = n          # last = newest
        self._save_seq()                    # before the id goes out
        self.entries[rid] = {"zone": zone_id, "status": REQUESTED, "home_bound": bool(home_bound),
                             "restored": False, "queued": False}
        self.log.append(("info", f"asked for zone {zone_id} ({rid})"))
        return rid

    def status(self, rid):
        e = self.entries.get(rid)
        return e["status"] if e else ""

    def granted(self, rid):
        return self.status(rid) == GRANTED

    def queued(self, rid):
        e = self.entries.get(rid)
        return bool(e and e["queued"])

    def may_enter(self, rid, now):
        """13.6: GRANTED and the link up at this moment. An unused grant with the link down waits."""
        return self.granted(rid) and self.link_up(now)

    def held(self):
        """requestIds whose zone this AGV holds (GRANTED or REVOKED, not yet dropped)."""
        return [rid for rid, e in self.entries.items() if e["status"] in (GRANTED, REVOKED)]

    def restored(self):
        """Held from before a restart, with no trip: NOT_READY ZONE_HELD (13.6)."""
        return [rid for rid, e in self.entries.items() if e["restored"]]

    # -- responses (13.3, 13.7) --------------------------------------------------------------
    def on_response(self, rid, grant_type, where="none"):
        """A response from the station. where: "none" (no trip behind the entry), "outside" (a trip,
        not yet in the zone) or "inside". Returns one of RESPONSE_ACTIONS."""
        e = self.entries.get(rid)
        if e is None or grant_type not in GRANT_TYPES:
            return NOTHING                      # not ours, or not a value we know: ignored (13.3)
        if grant_type == "QUEUED":
            if e["status"] == REQUESTED:
                e["queued"] = True
            return NOTHING
        if grant_type == "GRANTED":
            if e["status"] == REQUESTED:
                e["status"], e["queued"] = GRANTED, False
                self._save()                    # persisted BEFORE anything acts on it
                self.log.append(("info", f"zone {e['zone']} granted ({rid})"))
            return NOTHING                      # a repeated GRANTED changes nothing
        if grant_type == "REJECTED":
            if e["status"] == REQUESTED:
                self.error = (REJECTED_ERROR, rid)
                if not e.get("rejected"):           # the station repeats REJECTED each second: log once
                    e["rejected"] = True
                    self.log.append(("warn", f"zone {e['zone']} request rejected ({rid})"))
                return HOLD_REJECTED
            return NOTHING
        # REVOKED (13.7)
        if e["status"] == REVOKED:
            return NOTHING
        if where == "inside" and e["status"] == GRANTED:
            e["status"] = REVOKED
            self._save()
            self.error = (RELEASE_LOST_ERROR, rid)
            self.log.append(("warn", f"zone {e['zone']} revoked while inside ({rid}): stopped"))
            return STOP_LOST
        if where == "outside":
            self._drop(rid, f"zone {e['zone']} revoked before entering ({rid}): asking again")
            return REREQUEST
        self._drop(rid, f"zone {e['zone']} revoked with no trip ({rid}): released")
        return NOTHING

    # -- release (13.5) ----------------------------------------------------------------------
    def release(self, rid, why):
        if why not in RELEASES:
            raise ZoneError(f"a zone is released only for {RELEASES}, not {why!r}")
        if rid not in self.entries:
            return False
        self._drop(rid, f"zone {self.entries[rid]['zone']} released ({why}, {rid})")
        return True

    def release_home_bound(self):
        """The trolleys are confirmed off at HOME: every home-bound grant goes (owner, 2026-11-24)."""
        done = [rid for rid, e in self.entries.items() if e["home_bound"] and e["status"] == GRANTED]
        for rid in done:
            self.release(rid, "trolleys_off")
        return done

    def operator_release(self):
        """Run page "release zone" (13.6, any operator): what was held from before a restart, or a
        home-bound grant with no trip. Never one a running trip uses: the caller checks that."""
        done = [rid for rid, e in self.entries.items()
                if e["status"] in (GRANTED, REVOKED, REQUESTED) and (e["restored"] or e["home_bound"])]
        for rid in done:
            self._drop(rid, f"zone {self.entries[rid]['zone']} released by the operator ({rid})")
        return done

    def operator_reset(self):
        """Reset after ZONE_RELEASE_LOST: the REVOKED entry goes (13.7)."""
        done = [rid for rid, e in self.entries.items() if e["status"] == REVOKED]
        for rid in done:
            self._drop(rid, f"zone {self.entries[rid]['zone']} dropped on Reset ({rid})")
        if self.error[0] == RELEASE_LOST_ERROR:
            self.error = ("", "")
        return done

    def drop_unused(self):
        """A trip ended: its REQUESTED entries hold nothing and are withdrawn."""
        for rid in [r for r, e in self.entries.items() if e["status"] == REQUESTED]:
            self._drop(rid, f"zone request withdrawn, the trip ended ({rid})")
        if self.error[0] == REJECTED_ERROR:
            self.error = ("", "")

    def clear_error(self):
        self.error = ("", "")

    def _drop(self, rid, text):
        self.entries.pop(rid, None)
        self._save()
        self.log.append(("info", text))

    # -- report (state.zoneRequests) ---------------------------------------------------------
    def snapshot(self):
        """The OrderState zone fields, in request order."""
        rows = [(rid, e) for rid, e in self.entries.items()]
        return {
            "zone_request_ids": [rid for rid, _e in rows],
            "zone_ids": [e["zone"] for _rid, e in rows],
            "zone_set_ids": [self.zone_set_id for _rid, _e in rows],
            "zone_statuses": [e["status"] for _rid, e in rows],
            "zone_error_type": self.error[0],
            "zone_error_request_id": self.error[1],
        }
