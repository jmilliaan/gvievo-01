"""Speed 0.40 plan A3/A6: the real editor.js against a fake DOM - the speed control is a number
input and must show a loaded route's stored cap without rewriting it."""

import json
import pathlib
import shutil
import subprocess

import pytest

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_editor_speed_control_shows_stored_value_and_defaults_to_040():
    harness = pathlib.Path(__file__).with_name("editor_harness.js")
    r = subprocess.run([NODE, str(harness)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert "error" not in out, out
    assert float(out["new_draft_speed"]) == 0.40, out
    assert float(out["loaded_speed_shown"]) == 0.3, out
    assert out["saved_limits"] == {"linear_mps": 0.3}, out  # the stored value survives a save
    assert float(out["reset_speed"]) == 0.40, out


def test_browser_jog_presets_are_untouched():
    from amr_web import jog

    assert (jog.V_MAX, jog.W_MAX) == (0.30, 0.30)
