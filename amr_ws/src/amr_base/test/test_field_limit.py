"""Scanner fields gate AUTO (2026-10-02): protective zeroes, warning scales, unknown zeroes."""

from amr_base.gating import (
    FOLLOW,
    LINE,
    MANUAL,
    NONE,
    PENDANT,
    ROTATE,
    Field,
    FieldParams,
    apply_scale,
    ramp_scale,
    FieldView,
    Params,
    Selection,
    field_limit,
    field_view,
)

FP = FieldParams(protective_index=0, warning_indices=(1, 2), warning_active_level=False, warning_scale=0.5)
SUP = Params(require_supervisor=True)


def sel(source, v=0.4, w=0.2):
    return Selection(source, v, w, "x", 3)


def test_view_matches_the_walk_in_test():
    """agv-01, 2026-10-02: walking in read 111 -> 110 -> 100 -> 000 (paths 0,1,2)."""
    assert field_view(1.0, Field(0.9, (True, True, True)), FP) == FieldView(True, True, False)
    assert field_view(1.0, Field(0.9, (True, True, False)), FP) == FieldView(True, True, True)
    assert field_view(1.0, Field(0.9, (True, False, False)), FP) == FieldView(True, True, True)
    assert field_view(1.0, Field(0.9, (False, False, False)), FP) == FieldView(True, False, True)
    inverted = FieldParams(warning_indices=(1,), warning_active_level=True)
    assert field_view(1.0, Field(0.9, (True, True)), inverted).warning_active


def test_stale_short_or_missing_is_not_clear():
    assert field_view(2.0, Field(1.0, (True, True)), FP) == FieldView(False, False, False)
    assert field_view(1.0, Field(0.9, (True, True)), FP).fresh is False  # path 2 missing
    assert field_view(1.0, None, FP).fresh is False
    assert field_view(1.0, None, FieldParams(assume_clear=True)) == FieldView(True, True, False)


def test_protective_zeroes_every_auto_source():
    v = FieldView(True, False, False)
    for src in (FOLLOW, ROTATE, LINE):
        out, k = field_limit(sel(src), v, SUP, FP)
        assert (out.source, out.v, out.w, out.code, k) == (NONE, 0.0, 0.0, "FIELD_PROTECTIVE", 0.0)


def test_warning_asks_for_half_and_the_scale_keeps_the_curvature():
    out, k = field_limit(sel(LINE, 0.30, 0.10), FieldView(True, True, True), SUP, FP)
    assert (out.source, out.v, out.w, k) == (LINE, 0.30, 0.10, 0.5), "the target, not yet applied"
    half = apply_scale(out, 0.5)
    assert (half.v, half.w, half.generation) == (0.15, 0.05, 3)


def test_clear_to_warning_ramps_in_1_5_s_and_back_in_1_5_s():
    """Operator, 2026-10-02: a time ramp both ways, not a step and not a distance."""
    dt, k = 0.025, 1.0
    for _ in range(30):
        k = ramp_scale(k, 0.5, dt, FP)
    assert abs(k - 0.75) < 1e-9, "halfway down at half the time"
    for _ in range(31):
        k = ramp_scale(k, 0.5, dt, FP)
    assert k == 0.5, "fully down at 1.5 s, and it never undershoots"
    for _ in range(60):
        k = ramp_scale(k, 1.0, dt, FP)
    assert abs(k - 1.0) < 1e-9
    assert ramp_scale(1.0, 1.0, dt, FP) == 1.0
    step = FieldParams(warning_decel_s=0.0)
    assert ramp_scale(1.0, 0.5, dt, step) == 0.5, "a zero time is a step"


def test_unknown_fields_zero_auto_only_when_supervised():
    out, _ = field_limit(sel(FOLLOW), FieldView(False, False, False), SUP, FP)
    assert out.source == NONE and out.code == "FIELD_UNKNOWN"
    out, k = field_limit(sel(FOLLOW), FieldView(False, False, False), Params(), FP)
    assert out.source == FOLLOW and k == 1.0


def test_manual_sources_are_untouched():
    for src in (MANUAL, PENDANT, NONE):
        s = sel(src)
        assert field_limit(s, FieldView(True, False, True), SUP, FP) == (s, 1.0)
