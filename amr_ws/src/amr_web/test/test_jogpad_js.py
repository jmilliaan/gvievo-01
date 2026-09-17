"""Review R01 + web-style W4: the real jogpad.js under a fake DOM with deferred press responses."""

import json
import pathlib
import shutil
import subprocess

import pytest

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_jogpad_release_before_press_response_never_refreshes_and_cells_light():
    harness = pathlib.Path(__file__).with_name("jogpad_harness.js")
    r = subprocess.run([NODE, str(harness)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    for ev in ("pointerup", "pointercancel"):
        assert out[f"active_while_pending_{ev}"] and out[f"cleared_{ev}"]
        assert out[f"refreshes_after_{ev}"] == 0, out
        assert out[f"late_session_released_{ev}"], out  # the late session is handed straight back
    assert out["refreshes_after_blur"] == 0 and out["refreshes_after_hidden"] == 0, out
    assert out["hold_refreshes"] >= 1 and out["hold_active"], out
    assert out["refreshes_after_release"] == 0 and out["release_cleared"], out
    assert out["stop_sent"] and out["stop_flash"] and out["stop_flash_cleared"], out
