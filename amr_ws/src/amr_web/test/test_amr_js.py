"""Shared page helpers in static/amr.js under a stub DOM (lean plan group H)."""

import json
import pathlib
import shutil
import subprocess

import pytest

NODE = shutil.which("node")


def run(*cases):
    harness = pathlib.Path(__file__).with_name("amr_harness.js")
    r = subprocess.run([NODE, str(harness), *cases], capture_output=True, text=True,
                       encoding="utf-8", timeout=30)
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


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_the_temperature_chip_counts_throttling_without_colouring_it():
    """WP-P11 (2026-11-16): "65 °C · 23/min" while the package throttles; nothing extra otherwise."""
    c = run("ipcChip")["ipcChip"]
    assert c["none"]["text"] == "65 °C" and "Throttled" not in c["none"]["title"], c
    assert c["first"]["text"] == "65 °C" and "4200 times since boot, 13.4 s in all" in c["first"]["title"], c
    assert c["quiet"]["text"] == "65 °C", c
    assert c["busy"]["text"] == "65 °C · 23/min" and "idle injection 25 %" in c["busy"]["title"], c
    assert c["busy"]["cls"] == "chip", "report only: the throttle rate never colours the chip"
    assert c["noTemp"]["text"] == "– °C · 12/min", c


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_the_supply_chip_warns_and_marks_a_refused_start():
    """WP-P7 (2026-11-16): bad at or below trip_low (new runs refused), warn at warn_low or
    warn_high; no limits in the report = no class (as before); a stale report stays stale."""
    c = run("supplyChip")["supplyChip"]
    assert c["ok"]["cls"] == "chip" and c["ok"]["text"] == "52.1 V", c
    assert c["low"]["cls"] == "chip warn", c
    assert c["tooLow"]["cls"] == "chip bad" and "refused at 46.0 V" in c["tooLow"]["title"], c
    assert c["high"]["cls"] == "chip warn", c
    assert c["noLimits"]["cls"] == "chip", c
    assert c["stale"]["cls"] == "chip stale" and c["stale"]["text"] == "\u2013 V", c
