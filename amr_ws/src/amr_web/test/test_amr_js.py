"""Shared page helpers in static/amr.js under a stub DOM (lean plan group H)."""

import json
import pathlib
import shutil
import subprocess

import pytest

NODE = shutil.which("node")


def run(*cases):
    harness = pathlib.Path(__file__).with_name("amr_harness.js")
    r = subprocess.run([NODE, str(harness), *cases], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert "error" not in out, out["error"]
    return out


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_every_keeps_polling_after_a_failed_run():
    """D60: monitor, io, alarm events and params stopped for good after one dropped request."""
    e = run("every")["every"]
    assert e["runs"] == 2 and e["errors"] == 2 and e["rescheduled"], e
    assert e["hiddenRuns"] == 0 and e["hiddenRescheduled"], e  # visibleOnly skips, keeps the loop


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_the_shared_alarm_row_renders_what_home_rendered():
    """D63: Home and Alarms render through amr.js alarmRow; the markup did not change."""
    r = run("alarmRow")["alarmRow"]
    assert r["same"] and r["escaped"], r


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_act_reports_the_servers_verdict_and_a_missing_answer():
    """D64: one POST-and-report rule: data.ok when the server says, else HTTP 200."""
    a = run("act")["act"]
    assert a["okFalse"]["text"] == "not at a station" and a["okFalse"]["bad"], a
    assert a["ok200"]["text"] == "done" and not a["ok200"]["bad"], a
    assert a["ok200"]["log"].endswith("teach x: done"), a
    assert a["refused"]["status"] == 409 and a["refused"]["log"].endswith("refused: moving"), a
    assert a["none"] is None and a["noneText"] == "no response: the order may not be set" and a["noneBad"], a


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_panel_verdict_uses_the_freshness_the_server_renders():
    """D62: one selector verdict for the rail and Home; FRESH_S falls back to 0.5 s."""
    v = run("panelVerdict")["panelVerdict"]
    assert v == {"fresh": "AUTO", "stale": "STALE", "invalid": "INVALID", "manual": "MANUAL",
                 "missing": "\u2013", "fresh_s": 0.5}, v
