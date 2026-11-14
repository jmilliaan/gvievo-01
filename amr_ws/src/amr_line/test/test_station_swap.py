"""A station order for a BTU lap (contract v1.3, owner 2026-11-13). Pure, Inputs only.

The swap fixture's S2 (R-1) is the closer machine, S1 (R-2) the farther, S9 shares R-1 (as BTU16 shares
R2-1 with BTU24) and faces it: S2+S9 is a face-to-face pair at one stop (contract v1.4). A lap runs HOME, ATT,
the swap stops in circuit order, HOME: no U-turn. The swaps reuse OrderState's mw_status (first stop) and
mw2_status (second); me and me2 stay ""."""

import pytest
from calling_world import SETTLE, CallingWorld, go_on, parked_at
from site_fixture import swap_graph, swap_site
from test_no_trolley_run import NoTrolleyWorld

from amr_line import job as lj

KEYS = ("att_status", "mw_status", "mw2_status", "me2_status", "me_status")


def world(cls=NoTrolleyWorld):
    """As the vehicle runs today (no_trolley_run), or with the rear lidar deciding (CallingWorld)."""
    m = swap_site(trip_calls=1)
    w = cls(m, swap_graph(m))
    w.drive(SETTLE + 0.1)
    assert w.not_ready() == [], w.not_ready()
    return w


def snap(w):
    return w.job.order_snapshot()


def statuses(w):
    s = snap(w)
    return tuple(s[k] for k in KEYS)


def walk(w, stops, on_stop=None, trolley=None):
    """From an accepted order through each stop to HOME. `trolley`: what the rear lidar reads at each stop."""
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    for sid in stops:
        parked_at(w, sid)
        if on_stop:
            on_stop(sid)
        if trolley:
            w.trolley = trolley[sid]
            w.drive(0.1)
        go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason


def test_one_btu_is_a_lap_with_no_uturn():
    w = world()
    w.order("B1", "S2")
    assert w.job.state == lj.ARMED and w.job._order_active(), w.job.reason
    assert w.job.trip.group == "S" and w.job.trip.stops() == ["ATT", "R-1", "HOME"]
    assert w.job.trip.uturn() is None
    assert snap(w)["machine"] == "S2"
    assert statuses(w) == ("WAITING", "WAITING", "", "", "")


def test_one_btu_statuses_and_sequence_ids():
    w = world()
    w.order("B1", "S2")
    seen = []

    def at(sid):
        s = snap(w)
        seen.append((sid, s["last_node_id"], s["last_node_seq"], statuses(w)))

    walk(w, ["ATT", "R-1"], on_stop=at)
    assert seen == [("ATT", "ATT", 2, ("RUNNING", "WAITING", "", "", "")),
                    ("R-1", "R-1", 4, ("FINISHED", "RUNNING", "", "", ""))]
    s = snap(w)
    assert (s["last_node_id"], s["last_node_seq"], s["active"]) == ("HOME", 6, False)
    assert statuses(w) == ("FINISHED", "FINISHED", "", "", "")
    assert "served" in w.job.result


def test_two_btus_closer_first_statuses_and_sequence_ids():
    w = world()
    w.order("B2", "S2+S1")
    assert w.job.trip.stops() == ["ATT", "R-1", "R-2", "HOME"] and w.job.trip.uturn() is None
    seen = []

    def at(sid):
        s = snap(w)
        seen.append((sid, s["last_node_seq"], statuses(w)[:3]))

    walk(w, ["ATT", "R-1", "R-2"], on_stop=at)
    assert seen == [("ATT", 2, ("RUNNING", "WAITING", "WAITING")),
                    ("R-1", 4, ("FINISHED", "RUNNING", "WAITING")),
                    ("R-2", 6, ("FINISHED", "FINISHED", "RUNNING"))]
    s = snap(w)
    assert (s["last_node_seq"], s["active"]) == (8, False)
    assert statuses(w) == ("FINISHED", "FINISHED", "FINISHED", "", "")
    assert "served" in w.job.result


def test_a_swap_wait_finishes_when_the_agv_moves_off_not_at_the_press():
    w = world()
    w.order("B1", "S2")
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0)
    parked_at(w, "ATT")
    go_on(w)
    parked_at(w, "R-1")
    w.press_start()
    assert w.job.state == lj.ARMED and snap(w)["mw_status"] == "RUNNING", "the warning runs"
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0)
    assert snap(w)["mw_status"] == "FINISHED"


@pytest.mark.parametrize("machine", ["S1+S2", "S9+S2", "S2+S2", "S2+M1", "M1+S2", "S2+S1+S9", "S7"])
def test_a_wrong_btu_order_is_refused_by_the_job_too(machine):
    """Check 5, MACHINE: farther first, a stop's facing machine before its own, the same twice, mixed kinds,
    three."""
    w = world()
    w.order("B1", machine)
    assert w.refusal() == ("VALIDATION_FAILURE", "MACHINE") and w.job.state == lj.IDLE
    assert w.job.order is None


@pytest.mark.parametrize("value", ["absent", "present", "unknown"])
def test_with_the_rear_lidar_a_swap_stop_has_no_interlock(value):
    """Plan O10: whatever the rear lidar reads at a swap stop, START goes on. ATT still wants present."""
    w = world(CallingWorld)
    w.order("B1", "S2")
    walk(w, ["ATT", "R-1"], trolley={"ATT": "present", "R-1": value})
    assert snap(w)["start_refused_reason"] == ""


def test_with_the_rear_lidar_a_btu_lap_leaves_home_only_with_no_trolley():
    """The same departure check as MRU."""
    w = world(CallingWorld)
    w.trolley = "present"
    w.tick()
    w.order("B1", "S2")
    assert w.refusal() == ("DEPARTURE_REFUSED", "TROLLEY_PRESENT") and w.job.order is None


def test_a_btu_lap_never_pivots():
    """No U-turn on a swap circuit: no pivot is ever requested, on any tick of the lap."""
    w = world(CallingWorld)
    w.order("B2", "S2+S1")
    asked = set()
    real = w.tick

    def tick(**over):
        out = real(**over)
        asked.add(w.job.tape.uturn_req if w.job.tape is not None else None)
        return out

    w.tick = tick
    walk(w, ["ATT", "R-1", "R-2"], trolley={"ATT": "present", "R-1": "present", "R-2": "present"})
    assert asked == {None}
    assert "served" in w.job.result


def test_one_mru_order_is_unchanged_on_the_swap_site():
    w = world()
    w.order("O1", "M1")
    assert w.job.trip.stops() == ["ATT", "MW-1", "ME-1", "HOME"]
    assert statuses(w) == ("WAITING", "WAITING", "", "", "WAITING")


# -- facing machines at one stop (contract v1.4, owner 2026-11-14) ---------------------------------
def test_a_facing_machine_alone_is_one_stop():
    w = world()
    w.order("B1", "S9")
    assert w.job.state == lj.ARMED, w.job.reason
    assert w.job.trip.stops() == ["ATT", "R-1", "HOME"] and w.job.trip.work("R-1") == [("S9", "swap")]


def test_a_face_to_face_pair_is_one_wait_and_one_start():
    """Both machines are swapped at one stop, released by one START (contract section 11, item 17)."""
    w = world()
    w.order("B2", "S2+S9")
    assert w.job.state == lj.ARMED, w.job.reason
    assert w.job.trip.stops() == ["ATT", "R-1", "HOME"] and w.job.trip.uturn() is None
    assert w.job.trip.work("R-1") == [("S2", "swap"), ("S9", "swap")]
    assert statuses(w) == ("WAITING", "WAITING", "", "", "")
    seen = []

    def at(sid):
        s = snap(w)
        seen.append((sid, s["last_node_seq"], statuses(w)[:3]))

    walk(w, ["ATT", "R-1"], on_stop=at)
    assert seen == [("ATT", 2, ("RUNNING", "WAITING", "")), ("R-1", 4, ("FINISHED", "RUNNING", ""))]
    s = snap(w)
    assert (s["last_node_seq"], s["active"], s["machine"]) == (6, False, "S2+S9")
    assert statuses(w) == ("FINISHED", "FINISHED", "", "", "")
    assert "served" in w.job.result and "MISSED" not in w.job.result


def test_with_the_rear_lidar_a_face_to_face_stop_has_no_interlock():
    w = world(CallingWorld)
    w.order("B2", "S2+S9")
    walk(w, ["ATT", "R-1"], trolley={"ATT": "present", "R-1": "unknown"})
    assert snap(w)["start_refused_reason"] == "" and "served" in w.job.result
