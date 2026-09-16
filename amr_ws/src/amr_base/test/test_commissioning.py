"""U8 / P1-P2 attachment (unified plan §12.2): a plan upload cannot start motion;
a fresh physical Start can authorise exactly one job; authority loss aborts it."""

import json

import pytest

from amr_base import commissioning as cj

CPR = 1_080_000.0
PLAN = json.dumps(
    {"id": "t", "segments": [{"kind": "straight", "distance_m": 0.5}], "speed": {"speed_mps": 0.1}}
)
COMM = cj.LEASE_COMMISSIONING


def inputs(t, counts=(0, 0), start=False, manual=True, lease=COMM, stopped=True):
    return cj.Inputs(
        now=t,
        dt=0.02,
        counts=counts,
        counts_per_rev=CPR,
        stopped=stopped,
        panel_valid=True,
        panel_manual=manual,
        start_edge=start,
        lease_allowed=lease,
    )


def test_plan_upload_moves_nothing_and_needs_a_scale():
    job = cj.Job()
    with pytest.raises(ValueError, match="scale"):
        job.plan(PLAN, 0.0)
    assert job.phase == cj.IDLE
    planned = json.loads(job.plan(PLAN, CPR))
    assert job.phase == cj.PREPARED and planned["segments"][0]["counts"][0] > 0
    for _ in range(50):  # no edge, no motion, whatever else is true
        assert job.tick(inputs(1.0)) == (0.0, 0.0)
    assert job.phase == cj.PREPARED
    with pytest.raises(ValueError, match="number"):
        job.plan(
            json.dumps(
                {"segments": [{"kind": "straight", "distance_m": "far"}], "speed": {"speed_mps": 0.1}}
            ),
            CPR,
        )


def test_fresh_start_under_authority_runs_exactly_one_job():
    job = cj.Job()
    job.plan(PLAN, CPR)
    # Start under AUTO, or without the COMMISSIONING class, or while rolling: ignored
    job.tick(inputs(1.0, start=True, manual=False))
    assert job.phase == cj.PREPARED and "panel" in job.reason
    job.tick(inputs(1.0, start=True, lease=1))
    assert job.phase == cj.PREPARED and "supervisor" in job.reason
    job.tick(inputs(1.0, start=True, stopped=False))
    assert job.phase == cj.PREPARED and "rest" in job.reason
    # the real thing
    assert job.tick(inputs(1.0, start=True)) == (0.0, 0.0)  # baseline tick
    assert job.phase == cj.RUNNING
    wl, wr = job.tick(inputs(1.02))
    assert wl > 0 and wr > 0  # forward, vehicle terms
    # a held Start (edge again) changes nothing; a second edge cannot start a second job
    job.tick(inputs(1.04, start=True))
    assert job.phase == cj.RUNNING and job.run is not None
    run = job.run
    job.tick(inputs(1.06, start=True))
    assert job.run is run
    job.clear()
    assert job.phase == cj.ABORTED and job.tick(inputs(1.08, start=True)) == (0.0, 0.0)
    assert job.phase == cj.ABORTED  # DONE/ABORTED need a new plan before any Start does anything


def test_selector_or_lease_loss_aborts_a_running_job():
    for kind, kw in (("selector", {"manual": False}), ("lease", {"lease": 1}), ("counts", {"counts": None})):
        job = cj.Job()
        job.plan(PLAN, CPR)
        job.tick(inputs(1.0, start=True))
        assert job.tick(inputs(1.02))[0] > 0
        assert job.tick(inputs(1.04, **kw)) == (0.0, 0.0), kind
        assert job.phase == cj.ABORTED, kind
        assert job.snapshot()["phase"] == "ABORTED"
        ev = job.evidence()
        assert ev["started_counts"] == [0, 0] and ev["plan"] is not None
