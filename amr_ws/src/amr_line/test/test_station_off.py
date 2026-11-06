"""Station call plan P1: with station.enabled false the trip engine is the P0 baseline.

The golden CSVs were recorded from job code before any station change (plan section 7) and are
regenerated only on purpose: AMR_RECORD_GOLDEN=1 python3 -m pytest -q test_station_off.py
They are sparse: a row is written only when the tick's values differ from the row before.
"""

import csv
import math
import os
import pathlib

import pytest
import test_site_run
from site_fixture import graph, site
from test_site_run import TripWorld, go_on, one_call, parked_at, spin

from amr_line import job as lj
from amr_line import site_run

GOLDEN = pathlib.Path(__file__).parent / "golden"
FIELDS = ("tick", "state", "hold_cause", "left_rpm", "right_rpm", "reason")
TOL_RPM = 1e-9


@pytest.fixture(autouse=True)
def recorded_plant(monkeypatch):
    """The baseline was recorded with a left fork that jumps the follower to a tape at +45 mm and
    then reads centred. ForkWatch (2026-11-06) rightly calls that the other tape: kept off here, so
    this stays the same job, on the same plant, against the same untouched recording."""
    monkeypatch.setattr(site_run.ForkWatch, "MIN_SEP_MM", math.inf)
    monkeypatch.setattr(test_site_run, "FORK_NEG", test_site_run.FORK)


def _traced(w):
    """Record every job tick of this world: (state, hold_cause, left, right, reason)."""
    rows, real = [], w.job.tick

    def tick(i):
        out = real(i)
        rows.append((w.job.state, w.job.hold_cause, out[0], out[1], w.job.reason))
        return out

    w.job.tick = tick
    return rows


def _one_call_trip():
    w = one_call()
    rows = _traced(w)
    w.job.trip_call("M1", w.t)
    w.start()
    for sid in ("ATT", "MW-1"):
        parked_at(w, sid)
        go_on(w)
    assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0), (w.job.reason, w.S)
    spin(w)
    parked_at(w, "ME-1")
    go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), (w.job.reason, w.S)
    return rows


def _two_call_trip():
    m = site(
        uturn_points={},
        groups={
            "M": {
                "circuit": "C-M",
                "machines": {
                    "M1": {"release": "MW-1", "take": "ME-1"},
                    "M2": {"release": "MW-2", "take": "ME-2"},
                },
            }
        },
    )
    w = TripWorld(m, graph(m, skip=("UT-M1", "UT-M2")))
    rows = _traced(w)
    w.job.trip_call("M2", w.t)
    w.job.trip_call("M1", w.t + 1)
    w.start()
    for sid in ("ATT", "MW-1", "MW-2"):
        parked_at(w, sid)
        go_on(w)
    assert w.until(lambda: (w.job.tape.uturn_req or {}).get("phase") == "approach", 60.0), w.job.reason
    assert w.until(lambda: w.job.tape.uturn_req["phase"] == "stopping", 30.0), (w.job.reason, w.S)
    w.still, w.integrate = True, False
    spin(w)
    for sid in ("ME-2", "ME-1"):
        parked_at(w, sid)
        go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
    return rows


def _write(path, rows):
    GOLDEN.mkdir(exist_ok=True)
    with open(path, "w", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(FIELDS)
        last = None
        for n, row in enumerate(rows):
            if row != last:
                out.writerow((n, row[0], row[1], repr(row[2]), repr(row[3]), row[4]))
            last = row
        out.writerow((len(rows), "end", "", "", "", ""))


def _read(path):
    rows, last, at = [], None, 0
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            n = int(r["tick"])
            rows += [last] * (n - at)
            at = n
            if r["state"] == "end":
                break
            last = (
                int(r["state"]),
                r["hold_cause"],
                float(r["left_rpm"]),
                float(r["right_rpm"]),
                r["reason"],
            )
    return rows


def _compare(name, rows):
    path = GOLDEN / f"{name}.csv"
    if os.environ.get("AMR_RECORD_GOLDEN") == "1":
        _write(path, rows)
    want = _read(path)
    assert len(rows) == len(want), f"{name}: {len(rows)} ticks, the baseline has {len(want)}"
    for n, (got, base) in enumerate(zip(rows, want, strict=True)):
        assert got[0] == base[0] and got[1] == base[1] and got[4] == base[4], (n, got, base)
        assert math.isclose(got[2], base[2], abs_tol=TOL_RPM), (n, got, base)
        assert math.isclose(got[3], base[3], abs_tol=TOL_RPM), (n, got, base)


def test_the_one_call_trip_matches_the_baseline():
    _compare("one_call_trip", _one_call_trip())


def test_the_two_call_trip_matches_the_baseline():
    _compare("two_call_trip", _two_call_trip())


def _waiting():
    w = one_call()
    assert w.job.trip_call("M1", w.t)[0]
    return w


def _assert_idle_for(w, seconds):
    for _ in range(int(seconds / 0.02)):
        assert w.tick() == (0.0, 0.0)
        assert w.job.state == lj.IDLE and w.job.trip is None, w.job.reason
    assert [m for m, _t in w.job.calls.pending] == ["M1"]


def test_a_waiting_call_with_no_start_stays_idle():
    w = _waiting()
    _assert_idle_for(w, 60.0)


@pytest.mark.parametrize("landing", ["reset", "clear", "selector"])
def test_a_waiting_call_stays_idle_after_reset_clear_and_a_selector_return(landing):
    """The three landing points a level trigger would fire on."""
    w = _waiting()
    if landing == "reset":
        w.tick(reset_edge=True)
    elif landing == "clear":
        w.job.clear()
    else:
        w.drive(0.2, panel_auto=False)
    _assert_idle_for(w, 5.0)
