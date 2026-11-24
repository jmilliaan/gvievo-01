"""zones.ZoneClient: the AGV's side of the CLUSTER RELEASE zone (contract v1.6 section 13)."""
import json
import os

import pytest

from amr_line import zones as z

O = "STU8-20261125T081500"


def client(tmp_path=None):
    return z.ZoneClient(str(tmp_path) if tmp_path else None)


def test_request_ids_count_per_order_and_are_never_reused():
    c = client()
    a = c.request(O, "CLUSTER")
    assert a == f"{O}:CLUSTER:1" and c.status(a) == z.REQUESTED
    c.on_response(a, "GRANTED")
    c.release(a, "tail_clear")
    b = c.request(O, "CLUSTER", home_bound=True)
    assert b == f"{O}:CLUSTER:2"
    assert c.request("BTU5-20261125T090000", "CLUSTER").endswith(":CLUSTER:1")


def test_local_trips_never_ask():
    with pytest.raises(z.ZoneError):
        client().request("", "CLUSTER")


def test_granted_only_from_requested_and_repeats_change_nothing():
    c = client()
    rid = c.request(O, "CLUSTER")
    assert c.on_response(rid, "QUEUED") == z.NOTHING and c.queued(rid) and not c.granted(rid)
    c.on_response(rid, "GRANTED")
    assert c.granted(rid) and not c.queued(rid)
    assert c.on_response(rid, "GRANTED") == z.NOTHING and c.granted(rid)
    assert c.on_response("someone-else:CLUSTER:1", "GRANTED") == z.NOTHING   # not ours: ignored
    assert c.on_response(rid, "BANANA") == z.NOTHING and c.granted(rid)


def test_entering_needs_the_grant_and_a_live_link():
    c = client()
    rid = c.request(O, "CLUSTER")
    c.link_seen(100.0)
    assert not c.may_enter(rid, 100.5)                  # not granted
    c.on_response(rid, "GRANTED")
    assert c.may_enter(rid, 100.5)
    assert c.may_enter(rid, 100.0 + z.LINK_FRESH_S)
    assert not c.may_enter(rid, 100.1 + z.LINK_FRESH_S)  # link quiet: an unused grant waits (13.6)
    assert not client().link_up(0.0)                     # never heard: down


def test_a_grant_survives_a_restart_and_reads_as_held_with_no_trip(tmp_path):
    c = client(tmp_path)
    rid = c.request(O, "CLUSTER", home_bound=True)
    assert not os.path.exists(os.path.join(tmp_path, z.FILE_NAME))  # REQUESTED holds nothing
    c.on_response(rid, "GRANTED")
    doc = json.load(open(os.path.join(tmp_path, z.FILE_NAME)))
    assert doc["grants"][rid]["status"] == z.GRANTED and doc["zone_set_id"] == "SITE103-TRAFFIC-1"
    again = client(tmp_path)                             # the line layer restarted
    assert again.held() == [rid] and again.restored() == [rid]
    snap = again.snapshot()
    assert snap["zone_request_ids"] == [rid] and snap["zone_statuses"] == [z.GRANTED]
    assert again.request(O, "CLUSTER").endswith(":CLUSTER:2")   # n goes on past the held one


def test_release_only_for_the_four_reasons(tmp_path):
    c = client(tmp_path)
    rid = c.request(O, "CLUSTER")
    c.on_response(rid, "GRANTED")
    for why in ("abort", "reset", "fault", "trip_end", ""):
        with pytest.raises(z.ZoneError):
            c.release(rid, why)
    assert c.granted(rid)
    assert c.release(rid, "tail_clear") and c.status(rid) == ""
    assert not os.path.exists(os.path.join(tmp_path, z.FILE_NAME))


def test_drop_unused_withdraws_requests_but_keeps_grants():
    c = client()
    held = c.request(O, "CLUSTER", home_bound=True)
    c.on_response(held, "GRANTED")
    asked = c.request("BTU5-20261125T090000", "CLUSTER")
    c.drop_unused()
    assert c.granted(held) and c.status(asked) == ""


def test_trolleys_off_releases_only_home_bound_grants():
    c = client()
    out = c.request(O, "CLUSTER")
    c.on_response(out, "GRANTED")
    home = c.request(O, "CLUSTER", home_bound=True)
    c.on_response(home, "GRANTED")
    assert c.release_home_bound() == [home]
    assert c.granted(out)


def test_rejected_holds_and_keeps_the_entry_requested():
    c = client()
    rid = c.request(O, "CLUSTER")
    assert c.on_response(rid, "REJECTED") == z.HOLD_REJECTED
    assert c.status(rid) == z.REQUESTED and c.error == (z.REJECTED_ERROR, rid)
    assert c.on_response(rid, "REJECTED") == z.HOLD_REJECTED
    assert sum("rejected" in t for _lvl, t in c.log) == 1     # the station repeats it: logged once


def test_request_ids_are_never_reused_across_a_restart(tmp_path):
    # joint test T3, 2026-11-24: a probe restarted with nothing held asked :1 again
    c = client(tmp_path)
    for _ in range(3):
        rid = c.request(O, "CLUSTER")
        c.on_response(rid, "GRANTED")
        c.release(rid, "tail_clear")
    assert not os.path.exists(os.path.join(tmp_path, z.FILE_NAME))   # nothing held, no grant file
    assert client(tmp_path).request(O, "CLUSTER") == f"{O}:CLUSTER:4"


def test_the_request_counter_keeps_only_recent_orders_and_survives_a_bad_file(tmp_path):
    c = client(tmp_path)
    for i in range(z.SEQ_KEEP + 3):
        c.request(f"ORD{i}", "CLUSTER")
    doc = json.load(open(os.path.join(tmp_path, z.SEQ_FILE_NAME)))
    assert len(doc) == z.SEQ_KEEP and f"ORD{z.SEQ_KEEP + 2}" in doc and "ORD0" not in doc
    open(os.path.join(tmp_path, z.SEQ_FILE_NAME), "w").write("{not json")
    d = client(tmp_path)
    assert any("counter unreadable" in t for _lvl, t in d.log)
    assert d.request(O, "CLUSTER") == f"{O}:CLUSTER:1"


def test_a_held_grant_counts_for_the_next_id_even_without_the_counter(tmp_path):
    c = client(tmp_path)
    c.request(O, "CLUSTER")
    rid = c.request(O, "CLUSTER", home_bound=True)
    c.on_response(rid, "GRANTED")
    os.remove(os.path.join(tmp_path, z.SEQ_FILE_NAME))
    assert client(tmp_path).request(O, "CLUSTER") == f"{O}:CLUSTER:3"


@pytest.mark.parametrize("where, action, left", [
    ("none", z.NOTHING, ""),             # no trip: that is the release
    ("outside", z.REREQUEST, ""),        # not in yet: drop it, ask again with the next n
    ("inside", z.STOP_LOST, z.REVOKED),  # inside: stop, keep it REVOKED until Reset
])
def test_revoked_by_where_the_agv_is(where, action, left, tmp_path):
    c = client(tmp_path)
    rid = c.request(O, "CLUSTER")
    c.on_response(rid, "GRANTED")
    assert c.on_response(rid, "REVOKED", where) == action
    assert c.status(rid) == left
    if where == "inside":
        assert c.error == (z.RELEASE_LOST_ERROR, rid)
        assert client(tmp_path).status(rid) == z.REVOKED     # persisted too
        assert c.operator_reset() == [rid] and c.status(rid) == "" and c.error == ("", "")


def test_operator_release_takes_restored_and_home_bound_never_an_outbound_grant(tmp_path):
    c = client(tmp_path)
    home = c.request(O, "CLUSTER", home_bound=True)
    c.on_response(home, "GRANTED")
    out = c.request("BTU5-20261125T090000", "CLUSTER")
    c.on_response(out, "GRANTED")
    assert c.operator_release() == [home]
    assert c.granted(out)
    again = client(tmp_path)
    assert again.operator_release() == [out]          # after a restart everything held is the operator's


def test_an_unreadable_grant_file_reads_as_held(tmp_path):
    open(os.path.join(tmp_path, z.FILE_NAME), "w").write("{not json")
    c = client(tmp_path)
    assert c.held() and c.restored()                  # fail closed: ZONE_HELD until released
    assert c.operator_release()
    assert not c.held()


def test_snapshot_lists_every_entry_with_the_zone_set():
    c = client()
    a = c.request(O, "CLUSTER")
    c.on_response(a, "GRANTED")
    b = c.request("BTU5-20261125T090000", "CLUSTER")
    snap = c.snapshot()
    assert snap["zone_request_ids"] == [a, b]
    assert snap["zone_ids"] == ["CLUSTER", "CLUSTER"]
    assert snap["zone_set_ids"] == ["SITE103-TRAFFIC-1"] * 2
    assert snap["zone_statuses"] == [z.GRANTED, z.REQUESTED]
    assert snap["zone_error_type"] == ""


def test_parse_request_id():
    assert z.parse_request_id(f"{O}:CLUSTER:2") == (O, "CLUSTER", 2)
    assert z.parse_request_id("nonsense") is None
    assert z.parse_request_id(f"{O}:CLUSTER:0") is None
