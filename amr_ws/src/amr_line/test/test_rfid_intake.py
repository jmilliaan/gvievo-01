"""WP-A1: the /amr/rfid merge (rfid_intake) and the TagOdometer cursor."""

from amr_line.rfid_intake import RfidIntake
from amr_line.tag_table import TagOdometer


def _feed(rin, t, seq, gen=7, tag="", hb=False, comms=True):
    rin.on_message(t, hb, tag, seq, gen, comms, -1.0)


def test_encounters_and_status_merge_in_order():
    rin = RfidIntake(fresh_s=1.5)
    _feed(rin, 1.0, 1, tag="A")
    _feed(rin, 1.1, 1, hb=True)
    snap = rin.snapshot(1.2)
    assert snap["encounters"] == [(1, "A")] and snap["encounter_seq"] == 1 and snap["comms_ok"]
    assert not rin.snapshot(3.0)["comms_ok"], "a silent node is a link that is down"


def test_a_seq_regression_inside_one_generation_is_a_generation_change():
    rin = RfidIntake(fresh_s=1.5)
    _feed(rin, 1.0, 5, tag="A")
    g0 = rin.snapshot(1.0)["generation"]
    _feed(rin, 2.0, 1, tag="B")  # rfid_node restarted and drew the same generation
    snap = rin.snapshot(2.0)
    assert snap["generation"] != g0 and snap["encounters"] == [(1, "B")] and snap["encounter_seq"] == 1


def test_a_new_generation_drops_the_old_buffer():
    rin = RfidIntake(fresh_s=1.5)
    _feed(rin, 1.0, 3, tag="A")
    _feed(rin, 2.0, 4, gen=8, hb=True)
    assert rin.snapshot(2.0)["encounters"] == []


def test_odometer_cursor_moves_only_over_consumed_encounters():
    odo = TagOdometer()
    rfid = {"comms_ok": True, "encounter_seq": 0, "generation": 1, "encounters": []}
    odo.update(0.0, rfid, (0, 0), 100)
    odo.update(0.1, dict(rfid, encounter_seq=1, encounters=[(1, "A")]), (0, 0), 100)
    assert odo.tag == "A"
    # heartbeat-ahead: the status counts encounter 2 before it is delivered
    odo.update(0.2, dict(rfid, encounter_seq=2, encounters=[(1, "A")]), (0, 0), 100)
    assert odo.tag is None and odo.why == "RFID encounter missing"
    odo.update(0.3, dict(rfid, encounter_seq=2, encounters=[(1, "A"), (2, "B")]), (0, 0), 100)
    assert odo.tag == "B", "the late encounter is still taken"
