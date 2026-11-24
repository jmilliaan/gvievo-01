"""RELEASE zones on a whole station trip (contract v1.6 section 13), closed loop: the real FollowJob and
SiteRun on the site_fixture circuit, a no-trolley-run AGV (no rear scanner, START at HOME says the trolleys
are off), and the station's answers played by hand.

Trip M1: HOME S 5, ATT S 13, MW-1 S 28, U-turn point S 31, ME-1 S 34, HOME S 67.
Zone OUT just past ATT (asked at ATT's START, released when the last trolley is clear). Zone IN on the way
down to HOME (asked on the move, home-bound: released when the trolleys are off at HOME)."""

import pytest
from calling_world import SETTLE, CallingWorld, go_on, parked_at, spin
from site_fixture import AREAS, graph, site

from amr_line import job as lj
from amr_line import order as om
from amr_line import trip_route as trr
from amr_line import zones as zmod

BOX = lambda x0, x1, y0, y1: [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]  # noqa: E731
OUT, IN = BOX(9, 11, 4, 8), BOX(-1, 1, 2, 6)


class ZoneWorld(CallingWorld):
    JOB_ARGS = {**CallingWorld.JOB_ARGS, "no_trolley_run": True}

    def __init__(self, tmp_path, zones):
        self.link = True
        self.auto = set()               # zone ids the "station" grants at once
        m = site(trip_calls=1)
        super().__init__(m, graph(m))
        self.zone_polys = zones
        self.job.configure_site(self.job._site_cfg["params"],
                                lambda trip: trr.compile_trip(trip, m, self.g, areas=AREAS, release=self.zone_polys),
                                zones_fn=lambda: self.zone_polys)
        self.job.zones = zmod.ZoneClient(str(tmp_path))
        for attr, value in {"trolley": "unknown", "rear_clear": None}.items():
            setattr(self, attr, value)
        self.tick(start_edge=True)      # trolleys off at HOME (no-trolley run)
        self.drive(SETTLE + 0.1)

    def tick(self, **over):
        if self.link:
            self.job.zone_link(self.t)
        zc = self.job.zones
        if zc is not None:
            for rid, e in list(zc.entries.items()):
                if e["status"] == zmod.REQUESTED and e["zone"] in self.auto:
                    self.job.zone_response(rid, "GRANTED")
        return super().tick(**over)

    def zone(self, zone_id):
        """(requestId, status) of the newest entry for this zone, or (None, "")."""
        rows = [(rid, e["status"]) for rid, e in self.job.zones.entries.items() if e["zone"] == zone_id]
        return rows[-1] if rows else (None, "")

    def snap(self):
        return self.job.order_snapshot()


def world(tmp_path, **zones):
    return ZoneWorld(tmp_path, zones or {"OUT": OUT, "IN": IN})


def test_no_zone_drawn_refuses_station_orders(tmp_path):
    w = world(tmp_path, NONE=BOX(100, 101, 100, 101))      # something drawn, so the world is zone-aware
    assert w.not_ready() == []
    w.zone_polys = {}
    w.job._zones_seen = (None, False)
    w.drive(0.1)
    assert om.ZONES_MISSING in w.not_ready()
    assert w.snap()["zone_capable"] is False                # the bridge reports it as v1.5 (13.10)


def test_att_start_asks_and_holds_traffic_with_att_still_running(tmp_path):
    w = world(tmp_path)
    w.order(machine="M1")
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    parked_at(w, "ATT")
    assert w.zone("OUT") == (None, "")                      # never asked between HOME and ATT
    w.press_start()
    w.drive(0.3)
    rid, st = w.zone("OUT")
    assert st == zmod.REQUESTED and rid.endswith(":OUT:1")
    assert w.job.state == lj.HOLD and w.job.hold_cause == "traffic", w.job.reason
    assert w.snap()["att_status"] == "RUNNING"              # Z1 stays held while it waits (section 12)
    assert w.snap()["zone_statuses"] == [zmod.REQUESTED]
    w.job.zone_response(rid, "QUEUED")
    w.drive(1.0)
    assert w.job.hold_cause == "traffic" and "queued" in w.job.reason
    w.job.zone_response(rid, "GRANTED")
    w.tick()
    assert w.job.state == lj.ARMED, w.job.reason           # the warning, no second Start
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    assert w.snap()["att_status"] == "FINISHED"
    # released once the last trolley (4.8 m behind the centre) is out of the zone
    s_out = next(z for z in w.job.trip_route.release_zones if z["zone"] == "OUT")["S_out"]
    assert w.until(lambda: w.zone("OUT")[1] == "", 60.0), (w.S, w.job.reason)
    assert w.S >= s_out - 0.05


def test_a_grant_with_the_link_down_waits_at_att(tmp_path):
    w = world(tmp_path)
    w.order(machine="M1")
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0)
    parked_at(w, "ATT")
    w.link = False
    w.drive(zmod.LINK_FRESH_S + 0.5)
    w.press_start()
    w.drive(0.2)
    rid, _st = w.zone("OUT")
    w.job.zone_response(rid, "GRANTED")
    w.drive(1.0)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "traffic"
    assert "link is down" in w.job.reason
    w.link = True
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason


def test_home_bound_stops_before_the_zone_then_goes_and_holds_it_until_trolleys_off(tmp_path):
    w = world(tmp_path)
    w.auto = {"OUT"}
    w.order(machine="M1")
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0)
    for stop in ("ATT", "MW-1", "ME-1"):
        if stop == "ME-1":
            assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0), (w.job.reason, w.S)
            spin(w)
        parked_at(w, stop)
        go_on(w)
    z_in = next(z for z in w.job.trip_route.release_zones if z["zone"] == "IN")
    assert z_in["home"]
    assert w.until(lambda: w.job.state == lj.HOLD, 120.0), (w.S, w.job.reason)
    assert w.job.hold_cause == "traffic", w.job.reason
    rid, st = w.zone("IN")
    assert st == zmod.REQUESTED
    assert w.S < z_in["S_in"]                               # the front is not in the zone
    assert w.S == pytest.approx(z_in["S_in"] - trr.GATE_MARGIN_M, abs=0.15)
    w.job.zone_response(rid, "GRANTED")
    assert w.until(lambda: w.job.state == lj.ARMED, 1.0), w.job.reason      # horn first
    assert w.until(lambda: w.job.state == lj.DONE, 120.0), (w.S, w.job.reason)
    assert w.zone("IN") == (rid, zmod.GRANTED)              # parked, trolleys on: still held
    assert w.snap()["zone_request_ids"] == [rid]
    w.still = True                                          # at rest in the bay
    w.drive(1.0)
    w.tick(start_edge=True)                                 # trolleys off (no-trolley run: START at HOME)
    assert w.job.payload.may_leave()[0], w.job.reason
    assert w.zone("IN") == (None, "")
    assert w.snap()["zone_request_ids"] == []


def test_granted_while_braking_for_the_edge_goes_on_after_the_warning(tmp_path):
    w = world(tmp_path, IN=IN)
    w.order(machine="M1")
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0)
    for stop in ("ATT", "MW-1", "ME-1"):
        if stop == "ME-1":
            assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0)
            spin(w)
        parked_at(w, stop)
        go_on(w)
    z_in = w.job.trip_route.release_zones[0]
    assert w.until(lambda: (w.job.tape.stop or {}).get("role") == "traffic", 120.0), (w.S, w.job.reason)
    rid, _st = w.zone("IN")
    w.job.zone_response(rid, "GRANTED")
    assert w.until(lambda: w.job.state == lj.ARMED, 5.0), w.job.reason
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    assert w.until(lambda: w.S > z_in["S_in"] + 1.0, 30.0)


def test_revoked_inside_stops_and_reset_drops_it(tmp_path):
    w = world(tmp_path)
    w.auto = {"OUT"}
    w.order(machine="M1")
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0)
    parked_at(w, "ATT")
    go_on(w)
    z = next(z for z in w.job.trip_route.release_zones if z["zone"] == "OUT")
    assert w.until(lambda: w.S > z["S_in"] + 0.5, 30.0)
    rid, st = w.zone("OUT")
    assert st == zmod.GRANTED
    w.job.zone_response(rid, "REVOKED")
    w.tick()
    assert w.job.state == lj.HOLD and w.job.hold_cause == "traffic", w.job.reason
    assert w.snap()["zone_error_type"] == zmod.RELEASE_LOST_ERROR
    assert w.zone("OUT") == (rid, zmod.REVOKED)
    w.drive(2.0)
    assert w.job.state == lj.HOLD                            # no grant brings it back: only Reset
    w.tick(reset_edge=True)
    assert w.zone("OUT") == (None, "") and w.snap()["zone_error_type"] == ""


def test_a_grant_survives_a_line_layer_restart_as_zone_held(tmp_path):
    w = world(tmp_path)
    w.order(machine="M1")
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0)
    parked_at(w, "ATT")
    w.press_start()
    w.drive(0.2)
    rid, _st = w.zone("OUT")
    w.job.zone_response(rid, "GRANTED")
    # the layer restarts: a new job, a new client on the same state directory
    w2 = world(tmp_path)
    assert w2.zone("OUT") == (rid, zmod.GRANTED)
    assert om.ZONE_HELD in w2.not_ready()
    assert w2.snap()["zone_statuses"] == [zmod.GRANTED]
    ok, msg = w2.job.release_zone()
    assert ok, msg
    assert w2.zone("OUT") == (None, "")
    w2.drive(SETTLE + 0.1)
    assert om.ZONE_HELD not in w2.not_ready()


def test_local_trips_never_ask(tmp_path):
    w = world(tmp_path)
    t = w.job._new_tape()
    assert getattr(t, "zc", None) is None or not t.rz       # no order: no zone client in the run
