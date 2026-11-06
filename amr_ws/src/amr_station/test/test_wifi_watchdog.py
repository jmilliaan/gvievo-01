"""deploy/agv-wifi-reconnect.sh with fake nmcli and modprobe on PATH: what it does, and above all what it
leaves alone. Runs in a temp directory; touches no network or driver."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "agv-wifi-reconnect.sh"

NMCLI = """#!/bin/bash
echo "nmcli $*" >>"$FAKE/calls"
case "$*" in
  *GENERAL.STATE*) cat "$FAKE/state" ;;
  "-t radio wifi") cat "$FAKE/radio" ;;
  *"dev wifi list"*) cat "$FAKE/scan" ;;
  *"con up"*) exit "$(cat "$FAKE/conup_rc")" ;;
esac
"""
MODPROBE = """#!/bin/bash
echo "modprobe $*" >>"$FAKE/calls"
"""


class Rig:
    def __init__(self, tmp):
        self.tmp = tmp
        bindir = tmp / "bin"
        bindir.mkdir()
        for name, body in (("nmcli", NMCLI), ("modprobe", MODPROBE)):
            p = bindir / name
            p.write_text(body)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        (tmp / "calls").touch()
        self.set(oper="down\n", state="30 (disconnected)", radio="enabled", scan="", conup_rc="0", probe="ok")
        self.env = {
            **os.environ,
            "FAKE": str(tmp),
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "WIFI_OPER": str(tmp / "oper"),
            "WIFI_PROBE_CMD": f"cat {tmp / 'probe'}",
            "WIFI_TICK": "0.05",
            "WIFI_SCAN_EVERY": "0.05",
            "WIFI_SETTLE": "0",
            "WIFI_PROBE_EVERY": "0",
            "WIFI_CONUP_AFTER": "1",
            "WIFI_RELOAD_AFTER": "1",
            "WIFI_RELOAD_GAP": "1000",
            "WIFI_CONNECT_WAIT": "1",
        }

    def set(self, **files):
        for name, value in files.items():
            (self.tmp / name).write_text(value)

    def run(self, seconds=3.0):
        """Runs for about `seconds`: enough to pass every 1 s limit, then stops on its loop count."""
        env = dict(self.env, WIFI_MAX_LOOPS=str(int(seconds / 0.05)))
        r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        self.log = r.stdout
        return (self.tmp / "calls").read_text().splitlines()


@pytest.fixture()
def rig(tmp_path):
    return Rig(tmp_path)


def conups(calls):
    return [c for c in calls if "con up" in c]


def reloads(calls):
    return [c for c in calls if c.startswith("modprobe -r")]


def test_healthy_does_nothing(rig):
    rig.set(oper="up\n", state="100 (connected)")
    calls = rig.run()
    assert not conups(calls) and not reloads(calls)


def test_a_dead_path_brings_the_connection_up_and_never_reloads(rig):
    rig.set(oper="up\n", state="100 (connected)", probe="dead")
    calls = rig.run(4.0)
    assert conups(calls), rig.log
    assert not reloads(calls), "a powered-off station PC looks exactly like this"
    assert "nmcli con up" in rig.log


def test_the_con_up_backs_off(rig):
    rig.set(oper="up\n", state="100 (connected)", probe="dead")
    calls = rig.run(4.0)
    assert len(conups(calls)) <= 2, "1 s, then 2 s, then 4 s apart"


def test_refused_is_not_a_wifi_problem(rig):
    rig.set(oper="up\n", state="100 (connected)", probe="refused")
    calls = rig.run()
    assert not conups(calls) and not reloads(calls)


def test_out_of_range_only_scans(rig):
    rig.set(scan="other_net:60\nanother:40\n")
    calls = rig.run()
    assert not conups(calls) and not reloads(calls)
    assert "out of range" in rig.log


def test_hearing_nothing_at_all_reloads(rig):
    calls = rig.run()
    assert len(reloads(calls)) == 1, rig.log
    assert "modprobe iwlwifi" in calls
    assert "no network heard" in rig.log


def test_a_heard_ap_brings_the_connection_up(rig):
    rig.set(scan="agv_field:55\n")
    calls = rig.run(1.0)
    assert conups(calls) and not reloads(calls)


def test_a_weak_ap_is_left_alone(rig):
    rig.set(scan="agv_field:10\n")
    calls = rig.run()
    assert not conups(calls) and not reloads(calls)


def test_a_heard_ap_that_will_not_associate_reloads(rig):
    rig.set(scan="agv_field:55\n", conup_rc="4")
    calls = rig.run()
    assert reloads(calls), rig.log
    assert "cannot associate" in rig.log


def test_an_unavailable_device_reloads_once_then_holds(rig):
    rig.set(state="20 (unavailable)")
    calls = rig.run(4.0)
    assert len(reloads(calls)) == 1, rig.log
    assert "holding the reload" in rig.log


def test_a_radio_switched_off_is_left_alone(rig):
    rig.set(state="20 (unavailable)", radio="disabled")
    calls = rig.run()
    assert not conups(calls) and not reloads(calls)


def test_activation_without_end_reloads(rig):
    rig.set(state="50 (connecting)")
    calls = rig.run()
    assert reloads(calls), rig.log
    assert "activating" in rig.log
