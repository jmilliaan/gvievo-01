"""WP-T2 (S-fake-output-paths-from-field-geometry): /output_paths from the scan, SIM ONLY."""

import math
import os

import pytest
import yaml

from amr_sim import field_occupancy as fo

PKG = os.path.join(os.path.dirname(__file__), "..", "amr_sim")
FIELDS = os.path.join(os.path.dirname(__file__), "..", "..", "amr_bringup", "config", "scanner_fields.yaml")


def _doc():
    with open(FIELDS, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _scan_at(x, y, beams=3):
    """A few returns at one point (an obstacle), seen from the scanner origin."""
    r, a = math.hypot(x, y), math.atan2(y, x)
    return fo.points([r] * beams, a, 0.0, 0.05, 40.0)


def test_points_drop_invalid_returns():
    pts = fo.points([1.0, float("inf"), 0.01, float("nan"), 2.0], 0.0, math.pi / 2, 0.05, 40.0)
    assert len(pts) == 2
    assert pts[0] == pytest.approx((1.0, 0.0))
    assert pts[1] == pytest.approx((2.0, 0.0), abs=1e-9)  # index 4: a full turn


def test_an_obstacle_occupies_the_fields_it_is_in_and_they_nest():
    doc = _doc()

    def occ(x):
        o = fo.occupied_now(_scan_at(x, 0.0), doc)
        return o["protective"], o["warning_2"], o["warning_1"]

    assert occ(0.3) == (True, True, True)
    assert occ(0.8) == (False, True, True)
    assert occ(1.5) == (False, False, True)
    assert not any(fo.occupied_now(_scan_at(3.0, 0.0), doc).values())
    assert not any(fo.occupied_now(_scan_at(0.3, 0.0, beams=1), doc).values())  # one stray beam is noise


def test_the_paths_follow_the_yaml_index_and_polarity():
    doc = _doc()
    f = doc["fields"]
    occ = {"protective": True, "warning_1": False, "warning_2": False}
    status, valid = fo.output_paths(occ, doc)
    active = f["protective"]["active"]
    assert len(status) == fo.N_PATHS and all(valid)
    assert status[f["protective"]["path"]] is active
    assert status[f["warning_1"]["path"]] is (not active)
    flipped = yaml.safe_load(yaml.safe_dump(doc))
    for r in fo.ROLES:
        flipped["fields"][r]["active"] = not active
    assert fo.output_paths(occ, flipped)[0][f["protective"]["path"]] is (not active)
    assert not any(fo.output_paths(occ, doc, valid=False)[1])


def test_debounce_needs_consecutive_agreement():
    d = fo.Debounce(2)
    on = {"protective": True, "warning_1": True, "warning_2": True}
    off = dict.fromkeys(fo.ROLES, False)
    assert not d.update(on)["protective"]
    assert d.update(on)["protective"]
    assert d.update(off)["protective"]  # one clear scan is not a clear field
    assert not d.update(off)["protective"]


def test_scripted_overrides():
    assert fo.override_occupancy(fo.AUTO) is None
    assert not any(fo.override_occupancy(fo.CLEAR).values())
    assert fo.override_occupancy("violate:warning_2") == {
        "protective": False, "warning_1": True, "warning_2": True,
    }
    assert all(fo.override_occupancy("violate:protective").values())
    for good in ("auto", "clear", "drop", "invalid", "violate:warning_1"):
        assert fo.check_override(good) == good
    for bad in ("violate:rear", "nonsense", ""):
        with pytest.raises(ValueError):
            fo.check_override(bad)


def test_the_node_refuses_the_vehicle_domain_before_it_starts():
    """It must never run beside a real scanner (the docstring forbids reuse as a field monitor)."""
    src = open(os.path.join(PKG, "fake_output_paths_node.py"), encoding="utf-8").read()
    main = src[src.index("def main()"):]
    assert main.index("_refuse_vehicle_domain()") < main.index("run(FakeOutputPaths)")
    assert '== "10"' in src and "never" in src.lower()
