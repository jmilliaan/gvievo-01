"""Station call plan 11.3: trolley detection and the rear case gate. Synthetic scans, no ROS."""

import ast
import math
import pathlib

import pytest

from amr_base import trolley_detect as td

P = td.Params(
    roi_x_min_m=0.1,
    roi_x_max_m=1.2,
    roi_half_width_m=0.4,
    present_points=20,
    absent_points=5,
    present_s=0.5,
    absent_s=1.0,
    stale_s=0.3,
    max_invalid_ratio=0.5,
)
N, A0, DA = 721, -math.pi / 2, math.pi / 720
RMIN, RMAX = 0.05, 40.0


def scan(boxes=(), invalid=False):
    """Ranges to the first of a list of rectangles (x0, x1, half width), else nothing there."""
    out = []
    for k in range(N):
        a = A0 + k * DA
        c, s = math.cos(a), math.sin(a)
        r = math.inf
        for x0, x1, hw in boxes:
            if c > 1e-6 and abs(x0 / c * s) <= hw and x0 <= x1:
                r = min(r, x0 / c)
        out.append(float("nan") if invalid else r)
    return out


TROLLEY = [(0.5, 1.0, 0.3)]
OUTSIDE = [(2.0, 3.0, 2.0)]


def feed(d, t0, seconds, ranges, step=0.05):
    t = t0
    while t < t0 + seconds:
        d.scan(t, ranges, A0, DA, RMIN, RMAX)
        t += step
    return t


def test_starts_unknown():
    d = td.TrolleyDetect(P)
    assert d.tick(0.0) == td.UNKNOWN


def test_present_needs_the_debounce():
    d = td.TrolleyDetect(P)
    t = feed(d, 0.0, 0.4, scan(TROLLEY))
    assert d.tick(t) == td.UNKNOWN
    t = feed(d, t, 0.2, scan(TROLLEY))
    assert d.tick(t) == td.PRESENT


def test_absent_needs_the_debounce():
    d = td.TrolleyDetect(P)
    t = feed(d, 0.0, 0.9, scan())
    assert d.tick(t) == td.UNKNOWN
    t = feed(d, t, 0.2, scan())
    assert d.tick(t) == td.ABSENT


def test_one_bad_scan_does_not_flip_it():
    d = td.TrolleyDetect(P)
    t = feed(d, 0.0, 1.1, scan())
    d.scan(t, scan(TROLLEY), A0, DA, RMIN, RMAX)
    t = feed(d, t + 0.05, 0.2, scan())
    assert d.tick(t) == td.ABSENT


def test_between_keeps_the_state_and_resets_the_timer():
    d = td.TrolleyDetect(P)
    t = feed(d, 0.0, 0.6, scan(TROLLEY))
    assert d.state == td.PRESENT
    few = scan(TROLLEY)
    keep = [k for k, r in enumerate(few) if math.isfinite(r)][:10]
    between = [few[k] if k in keep else math.inf for k in range(N)]
    t = feed(d, t, 0.9, scan())  # going absent, not yet
    t = feed(d, t, 0.1, between)  # between: timer resets, state stays
    assert d.state == td.PRESENT
    t = feed(d, t, 0.9, scan())
    assert d.state == td.PRESENT, "the 1 s starts over"
    t = feed(d, t, 0.2, scan())
    assert d.tick(t) == td.ABSENT


def test_a_stale_scan_is_unknown():
    d = td.TrolleyDetect(P)
    t = feed(d, 0.0, 1.1, scan())
    assert d.tick(t) == td.ABSENT
    assert d.tick(t + 0.4) == td.UNKNOWN


@pytest.mark.parametrize("ranges, inc", [([], DA), (None, DA), ([1.0], 0.0)])
def test_a_malformed_scan_is_unknown(ranges, inc):
    d = td.TrolleyDetect(P)
    t = feed(d, 0.0, 1.1, scan())
    d.scan(t, ranges, A0, inc, RMIN, RMAX)
    assert d.state == td.UNKNOWN


def test_too_many_invalid_beams_is_unknown():
    d = td.TrolleyDetect(P)
    t = feed(d, 0.0, 1.1, scan())
    d.scan(t, scan(invalid=True), A0, DA, RMIN, RMAX)
    assert d.state == td.UNKNOWN and "invalid" in d.detail


def test_a_frozen_scan_is_unknown():
    d = td.TrolleyDetect(P)
    r = scan()
    for n in range(30):
        d.scan(n * 0.05, r, A0, DA, RMIN, RMAX, counter=n)
    assert d.state == td.ABSENT
    for n in range(30, 40):
        d.scan(n * 0.05, r, A0, DA, RMIN, RMAX, counter=30)
    assert d.state == td.UNKNOWN and "frozen" in d.detail


def test_leaving_unknown_needs_a_full_debounce():
    d = td.TrolleyDetect(P)
    t = feed(d, 0.0, 1.1, scan())
    assert d.tick(t + 1.0) == td.UNKNOWN
    t += 1.0
    t = feed(d, t, 0.9, scan())
    assert d.state == td.UNKNOWN
    t = feed(d, t, 0.2, scan())
    assert d.tick(t) == td.ABSENT


def test_points_outside_the_zone_do_not_count():
    d = td.TrolleyDetect(P)
    t = feed(d, 0.0, 1.1, scan(OUTSIDE))
    assert d.tick(t) == td.ABSENT and d.points == 0


@pytest.mark.parametrize(
    "case, proven, status, want",
    [
        ("no_trolley", False, [True], td.FIELD_CLEAR),
        ("other", False, [True], td.FIELD_UNKNOWN),
        ("unknown", False, [True], td.FIELD_UNKNOWN),
        ("proven", True, [True], td.FIELD_CLEAR),
        ("other_with_proven", True, [True], td.FIELD_UNKNOWN),
        ("no_trolley", False, [False], td.FIELD_VIOLATED),
        ("other", False, [False], td.FIELD_VIOLATED),
    ],
)
def test_rear_clear_needs_the_case_gate(case, proven, status, want):
    active = {"no_trolley": 3, "other": 4, "other_with_proven": 4, "unknown": 0, "proven": 0}[case]
    f = td.RearField(0.5, 0, 3 if case != "proven" else -1, proven)
    f.update(0.0, status, active)
    assert f.read(0.1)[0] == want


def test_the_drivers_no_data_case_is_never_the_no_trolley_case():
    assert td.case_of(0, 3) == td.CASE_UNKNOWN and td.case_of(None, 3) == td.CASE_UNKNOWN
    assert td.case_of(3, -1) == td.CASE_UNKNOWN


def test_the_trolley_state_never_selects_a_case():
    """Static: nothing here sets a case, calls a scanner service or publishes an input."""
    here = pathlib.Path(td.__file__).parent
    for name in ("trolley_detect.py", "trolley_node.py"):
        tree = ast.parse((here / name).read_text())
        names = [
            c.func.attr
            for c in ast.walk(tree)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
        ]
        assert "create_client" not in names, name
        publishers = [
            c.args[1].value
            for c in ast.walk(tree)
            if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and c.func.attr == "create_publisher"
        ]
        assert set(publishers) <= {"/amr/rear/trolley", "/amr/events"}, name


def test_rear_field_is_unknown_when_stale():
    f = td.RearField(0.5, 0, 3, False)
    assert f.read(0.0) == (td.FIELD_UNKNOWN, td.CASE_UNKNOWN)
    f.update(0.0, [True], 3)
    assert f.read(0.4)[0] == td.FIELD_CLEAR
    assert f.read(0.6) == (td.FIELD_UNKNOWN, td.CASE_UNKNOWN)


def test_rear_field_malformed_is_no_evidence():
    f = td.RearField(0.5, 1, 3, False)
    f.update(0.0, [True, True], 3)
    f.update(0.4, [True], 3)
    assert f.read(0.45)[0] == td.FIELD_CLEAR, "the old reading ages out"
    assert f.read(0.6)[0] == td.FIELD_UNKNOWN
