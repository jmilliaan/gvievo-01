"""Scanner fields gate AUTO (2026-10-02): protective zeroes, warning 1 (outer) x0.5,
warning 2 (inner) x0.1 with the lower winning, unknown zeroes, every change ramped in 1 s."""

import os

import pytest
from amr_base.gating import (
    FOLLOW,
    LINE,
    MANUAL,
    NONE,
    PENDANT,
    ROTATE,
    Field,
    FieldParams,
    FieldView,
    Params,
    Selection,
    SpeedRamp,
    apply_scale,
    field_limit,
    field_view,
)

# agv-01 (config/scanner_fields.yaml): path 0 protective, path 2 outer warning, path 1 inner.
FP = FieldParams(protective_index=0, warning_indices=(2, 1), warning_scales=(0.5, 0.1), warning_active_level=False)
SUP = Params(require_supervisor=True)


def sel(source, v=0.4, w=0.2):
    return Selection(source, v, w, "x", 3)


def test_view_on_a_walk_in():
    """Walking in reads (paths 0,1,2) 111 -> 110 -> 100 -> 000: outer, then inner, then protective."""
    assert field_view(1.0, Field(0.9, (True, True, True)), FP) == FieldView(True, True, False, 0, 1.0)
    assert field_view(1.0, Field(0.9, (True, True, False)), FP) == FieldView(True, True, True, 1, 0.5)
    assert field_view(1.0, Field(0.9, (True, False, False)), FP) == FieldView(True, True, True, 2, 0.1)
    assert field_view(1.0, Field(0.9, (False, False, False)), FP) == FieldView(True, False, True, 2, 0.1)
    # the inner field alone (something entering from the side) still asks for its own 10 %
    assert field_view(1.0, Field(0.9, (True, False, True)), FP).warning_scale == 0.1
    inverted = FieldParams(warning_indices=(1,), warning_scales=(0.5,), warning_active_level=True)
    assert field_view(1.0, Field(0.9, (True, True)), inverted).warning_active


def test_stale_short_or_missing_is_not_clear():
    assert field_view(2.0, Field(1.0, (True, True, True)), FP) == FieldView(False, False, False)
    assert field_view(1.0, Field(0.9, (True, True)), FP).fresh is False  # path 2 missing
    assert field_view(1.0, None, FP).fresh is False
    assert field_view(1.0, None, FieldParams(assume_clear=True)) == FieldView(True, True, False)


def test_protective_zeroes_every_auto_source():
    v = FieldView(True, False, True, 2, 0.1)
    for src in (FOLLOW, ROTATE, LINE):
        out, k = field_limit(sel(src), v, SUP, FP)
        assert (out.source, out.v, out.w, out.code, k) == (NONE, 0.0, 0.0, "FIELD_PROTECTIVE", 0.0)


def test_warning_targets_and_the_scale_keeps_the_curvature():
    out, k = field_limit(sel(LINE, 0.30, 0.10), FieldView(True, True, True, 1, 0.5), SUP, FP)
    assert (out.source, out.v, out.w, k) == (LINE, 0.30, 0.10, 0.5), "the target, not yet applied"
    _, k = field_limit(sel(LINE), FieldView(True, True, True, 2, 0.1), SUP, FP)
    assert k == 0.1
    half = apply_scale(out, 0.5)
    assert (half.v, half.w, half.generation) == (0.15, 0.05, 3)


def test_every_change_ramps_in_1_s():
    """Operator, 2026-10-02: time ramps, 1.0 s per change in either direction."""
    dt = 0.025  # 40 ticks = 1 s
    r = SpeedRamp()
    for _ in range(20):
        r.tick(0.5, dt, FP)
    assert r.value == pytest.approx(0.75), "halfway to warning 1 at half the time"
    for _ in range(20):
        r.tick(0.5, dt, FP)
    assert r.value == pytest.approx(0.5)
    r.tick(0.5, dt, FP)
    assert r.value == 0.5, "it never undershoots"
    for _ in range(39):
        r.tick(0.1, dt, FP)
    assert r.value > 0.1, "warning 1 -> warning 2 also takes the full second"
    r.tick(0.1, dt, FP)
    r.tick(0.1, dt, FP)
    assert r.value == pytest.approx(0.1)
    for _ in range(39):
        r.tick(1.0, dt, FP)
    assert r.value < 1.0, "not yet back before 1.0 s"
    r.tick(1.0, dt, FP)
    r.tick(1.0, dt, FP)
    assert r.value == pytest.approx(1.0)
    straight = SpeedRamp()
    for _ in range(40):
        straight.tick(0.1, dt, FP)
    assert straight.value == pytest.approx(0.1), "clear -> warning 2 directly: 1 s too"
    step = SpeedRamp()
    assert step.tick(0.5, dt, FieldParams(warning_decel_s=0.0)) == 0.5, "a zero time is a step"


def test_unknown_fields_zero_auto_only_when_supervised():
    out, _ = field_limit(sel(FOLLOW), FieldView(False, False, False), SUP, FP)
    assert out.source == NONE and out.code == "FIELD_UNKNOWN"
    out, k = field_limit(sel(FOLLOW), FieldView(False, False, False), Params(), FP)
    assert out.source == FOLLOW and k == 1.0


def test_manual_sources_are_untouched():
    for src in (MANUAL, PENDANT, NONE):
        s = sel(src)
        assert field_limit(s, FieldView(True, False, True, 2, 0.1), SUP, FP) == (s, 1.0)


def test_the_saved_field_set_matches_the_scanner_and_feeds_these_params():
    """config/scanner_fields.yaml: the corners give the ranges the nanoScan3 reports on
    /field_data (0.64 / 1.14 / 1.92 m, 2026-10-02), and its params are FP above."""
    import importlib.util

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "amr_bringup"))
    spec = importlib.util.spec_from_file_location("scanner_fields", os.path.join(root, "amr_bringup", "scanner_fields.py"))
    sf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sf)
    doc = sf.load(os.path.join(root, "config", "scanner_fields.yaml"))
    reach = {r: round(sf.reach_m(doc["fields"][r]["rect"]), 2) for r in sf.ROLES}
    assert reach == {"protective": 0.64, "warning_1": 1.92, "warning_2": 1.14}
    p = sf.mux_params(doc)
    got = (p["protective_index"], tuple(p["warning_indices"]), tuple(p["warning_scales"]), p["warning_active_level"])
    assert got == (FP.protective_index, FP.warning_indices, FP.warning_scales, FP.warning_active_level)
    bad = {**doc, "fields": {**doc["fields"], "warning_2": {**doc["fields"]["warning_2"], "scale": 0.7}}}
    with pytest.raises(ValueError, match="inner is the slower"):
        sf.validate(bad)
