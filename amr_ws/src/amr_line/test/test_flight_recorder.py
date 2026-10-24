"""amr_line.flight_recorder: the last seconds of ticks, written on demand, pruned."""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from amr_line import flight_recorder as fr  # noqa: E402


def test_keeps_the_last_span_and_writes_a_csv(tmp_path):
    r = fr.FlightRecorder(str(tmp_path), span_s=1.0, rate_hz=10.0, keep=2)
    assert r.dump("nothing yet") is None
    for i in range(25):
        r.add(t=i, job="RUNNING", engine="run", e_used_mm=i, extra="ignored")
    path = r.dump("DONE track lost: the tape", now=0)
    rows = list(csv.DictReader(open(path)))
    assert [int(x["t"]) for x in rows] == list(range(15, 25))
    assert os.path.basename(path).endswith("done-track-lost--the-tape.csv")
    for k in range(3):
        r.dump(f"kink {k}", now=k + 1)
    assert len(os.listdir(r.dir)) == 2
