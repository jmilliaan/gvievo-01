"""A station order for two machines (contract v1.2 PROPOSAL, owner 2026-11-11). Pure, Inputs only.

The fixture's M1 (MW-1, ME-1) is the closer machine, M2 (MW-2, ME-2) the farther: a pair "M1+M2" runs
HOME, ATT, MW-1, MW-2, U-turn at UT-M2, ME-2, ME-1, HOME. Two trolleys out, two back."""

import pytest
from calling_world import SETTLE, settled, spin
from site_fixture import graph, site
from test_no_trolley_run import NoTrolleyWorld
from test_site_run import go_on, parked_at

from amr_line import job as lj
from amr_line import order
from amr_line import trip as tripmod

PAIR = "M1+M2"
ROUTE = ["ATT", "MW-1", "MW-2", "ME-2", "ME-1"]
# What the rear lidar must read for Start at each stop of a pair, and the refusal for the other value
NEED = {"ATT": "present", "MW-1": "present", "MW-2": "absent", "ME-2": "present", "ME-1": "present"}


def snap(w):
    return w.job.order_snapshot()


def refused(w):
    s = snap(w)
    return s["start_refused_node"], s["start_refused_reason"]


def statuses(w):
    s = snap(w)
    return tuple(s[k] for k in ("att_status", "mw_status", "mw2_status", "me2_status", "me_status"))


def walk(w, until=None, on_stop=None):
    """From an accepted pair, through each stop with the trolley each wants, to `until` (parked) or HOME."""
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    for sid in ROUTE:
        if sid == "ME-2":
            assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0), (w.job.reason, w.S)
            spin(w)
        parked_at(w, sid)
        if on_stop:
            on_stop(sid)
        if sid == until:
            return
        w.trolley = NEED[sid]
        w.drive(0.1)
        go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason


def test_a_pair_is_one_trip_closer_first_turning_after_the_farther():
    w = settled()
    w.order("P1", PAIR)
    assert w.job.state == lj.ARMED and w.job._order_active(), w.job.reason
    assert w.job.trip.machines == ["M1", "M2"] and w.job.trip.stops() == ROUTE + ["HOME"]
    assert w.job.trip.uturn()["id"] == "UT-M2"
    assert snap(w)["machine"] == PAIR


def test_action_states_and_sequence_ids_follow_a_pair():
    w = settled()
    w.order("P1", PAIR)
    assert statuses(w) == ("WAITING",) * 5
    seen = []

    def at(sid):
        s = snap(w)
        seen.append((sid, s["last_node_id"], s["last_node_seq"], statuses(w).count("RUNNING")))

    walk(w, on_stop=at)
    assert seen == [("ATT", "ATT", 2, 1), ("MW-1", "MW-1", 4, 1), ("MW-2", "MW-2", 6, 1),
                    ("ME-2", "ME-2", 8, 1), ("ME-1", "ME-1", 10, 1)]
    s = snap(w)
    assert (s["last_node_id"], s["last_node_seq"], s["active"]) == ("HOME", 12, False)
    assert statuses(w) == ("FINISHED",) * 5
    assert "served" in w.job.result


def test_the_running_wait_is_the_stop_where_it_stands():
    w = settled()
    w.order("P1", PAIR)
    keys = dict(zip(ROUTE, ("att_status", "mw_status", "mw2_status", "me2_status", "me_status"), strict=True))

    def at(sid):
        s = snap(w)
        assert [k for k in keys.values() if s[k] == "RUNNING"] == [keys[sid]], (sid, s)

    walk(w, on_stop=at)


def test_one_machine_keeps_its_three_waits_and_sequence_8():
    w = settled()
    w.order("O1", "M1")
    s = snap(w)
    assert (s["mw2_status"], s["me2_status"]) == ("", "")
    assert set(w.job.order.status) == {"att", "mw", "me"} and w.job.order.seq_end == order.SEQ_END


# -- the rear lidar at each stop (no_trolley_run false) ----------------------------------------------
@pytest.mark.parametrize("sid", ROUTE)
def test_start_at_each_stop_of_a_pair_wants_its_trolley(sid):
    w = settled()
    w.order("P1", PAIR)
    walk(w, until=sid)
    need = NEED[sid]
    wrong = "absent" if need == "present" else "present"
    w.trolley = wrong
    w.drive(0.1)
    w.press_start()
    want = order.NO_TROLLEY if need == "present" else order.TROLLEY_STILL_ON
    assert w.job.state == lj.HOLD and refused(w) == (sid, want), (sid, w.job.reason)
    w.trolley = "unknown"
    w.drive(0.1)
    w.press_start()
    assert w.job.state == lj.HOLD and refused(w) == (sid, order.TROLLEY_UNKNOWN)
    w.trolley = need
    w.drive(0.1)
    go_on(w)
    assert refused(w) == ("", "")


def test_the_first_release_wants_present_because_one_trolley_stays_on():
    """The lidar sees 'a trolley', not how many: at MW-1 it cannot tell one came off. Pinned."""
    w = settled()
    w.order("P1", PAIR)
    walk(w, until="MW-1")
    assert w.job._start_interlock(w.inputs(trolley="present")) == ""
    assert w.job._start_interlock(w.inputs(trolley="absent")) == order.NO_TROLLEY


def test_no_u_turn_until_both_releases_are_served():
    m = site(trip_calls=1)
    t = tripmod.Trip(m, "M", ["M1", "M2"])
    t.serve("MW-1")
    assert t.may_pivot()[0] is False and t.releases_pending() == ["M2"]
    t.serve("MW-2")
    assert t.may_pivot() == (True, "")


# -- no_trolley_run --------------------------------------------------------------------------------
def test_a_pair_runs_whole_with_no_rear_scanner():
    m = site(trip_calls=1)
    w = NoTrolleyWorld(m, graph(m))
    w.trolley, w.rear_clear = "unknown", None
    w.drive(SETTLE + 0.1)
    w.order("P1", PAIR)
    assert w.job.state == lj.ARMED, w.job.reason
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    for sid in ROUTE:
        if sid == "ME-2":
            assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0), (w.job.reason, w.S)
            spin(w)
        parked_at(w, sid)
        go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
    assert snap(w)["last_node_seq"] == 12 and statuses(w) == ("FINISHED",) * 5


# -- check 5: which pairs the job takes ----------------------------------------------------------------
@pytest.mark.parametrize("key", ["M2+M1", "M1+M1", "M1+NOPE", "M1+M2+M1", "M1+", "+M2"])
def test_a_wrong_pair_is_refused_as_machine(key):
    w = settled()
    w.order("P1", key)
    assert w.refusal() == ("VALIDATION_FAILURE", "MACHINE") and w.job.order is None
    assert w.job.state == lj.IDLE


def test_a_pair_across_two_groups_is_refused():
    w = settled()
    w.job.site = dict(w.job.site)
    w.job.site["MACHINES"] = {**w.job.site["MACHINES"], "M2": "OTHER"}
    w.job.site["GROUPS"] = {**w.job.site["GROUPS"], "OTHER": {"circuit": "C-M", "machines": {
        "M2": w.job.site["GROUPS"]["M"]["machines"]["M2"]}}}
    w.order("P1", PAIR)
    assert w.refusal() == ("VALIDATION_FAILURE", "MACHINE")


def test_cancel_in_the_warning_fails_all_five_waits():
    w = settled()
    w.order("P1", PAIR)
    assert w.job.state == lj.ARMED
    w.job.order_cancel("P1", "c1")
    w.tick()
    s = snap(w)
    assert s["cancel_status"] == "FINISHED" and not s["active"] and statuses(w) == ("FAILED",) * 5


# -- the same orderId again (the station resends until taken or refused) ------------------------------
def test_a_refused_pair_id_is_taken_later():
    w = settled()
    w.job.order_request("P1", PAIR)
    w.tick(field_clear=False)
    assert w.job.state == lj.IDLE and w.refusal()[0] == "DEPARTURE_REFUSED" and w.job.order is None
    w.drive(SETTLE + 0.2)       # the front field going clear restarts SETTLING
    w.order("P1", PAIR)
    assert w.job.state == lj.ARMED and w.job.order.order_id == "P1"


def test_a_held_pair_id_never_starts_twice():
    w = settled()
    w.order("P1", PAIR)
    seq = w.job.refusal["seq"]
    w.order("P1", PAIR)
    assert w.job.state == lj.ARMED and w.job.refusal["seq"] == seq, "dropped, not refused"
