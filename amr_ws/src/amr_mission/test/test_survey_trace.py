"""WP-E9 / H-P1-16 (2026-11-16): IMU gaps during a survey leave a trace. Pure part; the node
wiring (mapping_session_node: message, one SURVEY_IMU_GAP event, review["trace"]) is checked
in its source here and for real in test_continue_survey on the vehicle."""

from __future__ import annotations

import pathlib

import pytest
from amr_mission.survey_trace import ImuGaps

NODE = pathlib.Path(__file__).resolve().parents[1] / "amr_mission" / "mapping_session_node.py"


def feed(g, t0, t1, dt=0.02):
    t = t0
    while t < t1 - 1e-9:
        t += dt
        g.sample(t)
    return t


def test_a_3_s_gap_while_mapping_is_counted_reported_once_and_summarised():
    g = ImuGaps(limit_s=0.20)
    g.start(100.0)
    t = feed(g, 100.0, 110.0)
    assert g.total_s(t) == 0.0 and not g.first_gap(t) and g.text(t) == ""
    # the IMU goes quiet for 3 s: counted while still open (a dead IMU never closes it)
    assert g.total_s(t + 2.0) == pytest.approx(2.0)
    assert g.first_gap(t + 2.0), "one event on the first gap"
    g.sample(t + 3.0)
    assert g.count == 1 and g.total_s(t + 3.0) == pytest.approx(3.0)
    assert not g.first_gap(t + 3.0), "only once per survey"
    t = feed(g, t + 3.0, t + 10.0)
    assert g.summary(t) == {"imu_gap_s": 3.0, "imu_gaps": 1, "imu_gap_limit_s": 0.2}
    assert g.text(t).startswith("IMU gaps 3.0 s")


def test_gaps_at_the_limit_or_outside_a_survey_do_not_count():
    g = ImuGaps(limit_s=0.20)
    g.sample(1.0)
    g.sample(5.0)
    assert g.total_s(5.0) == 0.0, "not surveying"
    g.start(10.0)
    g.sample(10.125)
    g.sample(10.25)
    assert g.total_s(10.25) == 0.0, "under the limit"
    g.sample(10.75)
    assert g.count == 1 and g.total_s(10.75) == pytest.approx(0.5)


def test_a_failed_save_resumes_the_same_survey_and_a_new_one_starts_clean():
    g = ImuGaps(limit_s=0.20)
    g.start(0.0)
    g.sample(1.0)  # a 1 s gap
    g.pause(1.5)  # SAVING: the half second since the last sample was a gap too
    assert g.total_s(9.0) == pytest.approx(1.5) and g.count == 2, "nothing counts while paused"
    g.resume(10.0)
    g.sample(10.1)
    assert g.total_s(10.1) == pytest.approx(1.5)
    g.start(20.0)
    assert g.total_s(20.0) == 0.0 and g.count == 0


def test_the_node_wires_the_trace():
    src = NODE.read_text(encoding="utf-8")
    assert "self._imu_gaps.sample(" in src and 'self.event("SURVEY_IMU_GAP"' in src
    assert 'review["trace"] = self._imu_gaps.summary(' in src
    assert 'self.event("SURVEY_SCAN_GAP", gap)' in src and "self._scan_gap.update(" in src
