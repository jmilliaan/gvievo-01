"""WP-H4 / WP-P4 / WP-H2 pure parts: no ROS, no processes (unified plan, 2026-11-16).

Supervisor-level behaviour that needs rclpy lives in test_hardness.py; the policy pieces
it calls are pinned here so they run anywhere.
"""

import configparser
import os
import socket
import sys
import types
from pathlib import Path

import pytest
from agv_core import disk

from amr_bringup import exits, sdnotify
from amr_bringup import process_supervisor as ps
from amr_bringup import readiness as rd

UNIT = Path(__file__).resolve().parents[3] / "deploy" / "amr.service"


# ---- the exits file: BASE_EXITED names the node -------------------------------------------

def test_the_first_exit_of_a_group_is_kept_and_named(tmp_path):
    sd = str(tmp_path)
    assert exits.read(sd, "base") is None and exits.describe(None) == ""
    assert exits.record(sd, "base", "drive_node", -15)
    assert not exits.record(sd, "base", "panel_node", 0)  # the shutdown cascade, not the cause
    body = exits.read(sd, "base")
    assert body["node"] == "drive_node" and body["code"] == -15
    assert exits.describe(body) == "drive_node exited with code -15 (SIGTERM)"  # a negative code is a signal
    assert exits.describe({"node": "ekf_local", "code": 1}) == "ekf_local exited with code 1"
    assert exits.describe({"node": "x", "code": None}) == "x exited"
    exits.clear(sd, "base")
    assert exits.read(sd, "base") is None
    assert not os.listdir(tmp_path / exits.EXITS)  # no tmp file left behind


def test_a_launch_without_a_role_records_nothing(tmp_path):
    assert not exits.record(str(tmp_path), "", "drive_node", 1)
    assert not (tmp_path / exits.EXITS).exists()


def test_an_unwritable_state_dir_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert not exits.record(str(blocker), "base", "drive_node", 1)  # exits/ cannot be made under a file
    exits.clear(str(blocker), "base")


def test_a_garbled_exits_file_is_no_evidence(tmp_path):
    p = Path(exits.path(str(tmp_path), "layer"))
    p.parent.mkdir(parents=True)
    p.write_text("{not json")
    assert exits.read(str(tmp_path), "layer") is None


# ---- respawn tries: a long-lived web respawns for ever, quick deaths give up ---------------

def test_a_long_life_resets_the_respawn_tries_and_a_quick_death_does_not():
    assert ps.respawn_tries(3, ps.RESPAWN_RESET_S) == 0
    assert ps.respawn_tries(3, ps.RESPAWN_RESET_S + 500) == 0
    assert ps.respawn_tries(2, ps.RESPAWN_RESET_S - 0.1) == 2
    assert ps.RESPAWN_RESET_S == 120.0  # H-P1-5


# ---- the OOM preference ---------------------------------------------------------------------

def test_web_and_layer_go_first_on_oom_and_the_base_stays_protected(tmp_path):
    assert ps.OOM_SCORE_ADJ == {"web": 300, "layer": 300}
    assert ps.oom_preexec("base") is None  # inherits amr.service's -500
    assert ps.oom_preexec("supervisor") is None
    target = tmp_path / "oom_score_adj"
    target.write_text("-500")
    fn = ps.oom_preexec("web", path=str(target))
    fn()
    assert target.read_text() == "300"


def test_the_oom_preexec_is_silent_when_proc_is_missing(tmp_path):
    ps.oom_preexec("layer", path=str(tmp_path / "missing" / "oom_score_adj"))()  # must not raise


def test_amr_service_protects_the_supervisor_below_the_children():
    text = UNIT.read_text()
    assert "OOMScoreAdjust=-500" in text and "OOMPolicy=continue" in text


# ---- the stop budget fits amr.service ------------------------------------------------------

def _timeout_stop_s() -> float:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read_string(UNIT.read_text())
    raw = cp["Service"]["TimeoutStopSec"].strip()
    return float(raw.rstrip("s"))


def test_the_whole_teardown_fits_timeout_stop_sec_with_ten_seconds_spare():
    """H-P2-7: the summed stop budget stays under TimeoutStopSec - 10, or systemd's SIGKILL lands
    on a drive_node still disarming (8130h)."""
    assert ps.stop_budget_s() <= _timeout_stop_s() - 10.0, (ps.stop_budget_s(), _timeout_stop_s())


def test_the_web_stops_on_the_short_budget_after_the_base():
    assert ps.OPTIONAL_STOP_BUDGET_S == (2.0, 1.0, 1.0)
    assert set(ps.STOP_BUDGET_S) == {"layer", "base"}  # the web is not in the serial part
    assert ps.STOP_BUDGET_S["base"][0] >= 6.0  # drive_node's own teardown disarms inside the SIGINT wait


def test_the_supervisor_stops_layer_then_base_then_the_rest_together():
    src = (Path(__file__).resolve().parents[1] / "amr_bringup" / "supervisor_node.py").read_text()
    body = src.split("def _stop_groups(self)", 1)[1].split("\n    def ", 1)[0]
    assert 'for role in ("layer", "base")' in body
    assert "threading.Thread" in body and "OPTIONAL_STOP_BUDGET_S" in body
    shut = src.split("def shutdown(self)", 1)[1].split("\ndef ", 1)[0]
    assert "faulthandler.dump_traceback(all_threads=True)" in shut
    assert "extend_timeout" in shut


# ---- sd_notify: STATUS= and EXTEND_TIMEOUT_USEC= -------------------------------------------

def test_the_status_line_names_mode_generation_and_the_last_fault():
    assert sdnotify.status_line("LINE", 7) == "LINE gen 7"
    assert sdnotify.status_line("FAULT", 3, "fault", "BASE_EXITED") == "FAULT gen 3; fault; fault BASE_EXITED"
    line = sdnotify.status_line("IDLE", 4, last_fault="LAYER_EXITED at 14:02", note="web gave up")
    assert line == "IDLE gen 4; last fault LAYER_EXITED at 14:02; web gave up"


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX") or sys.platform == "win32", reason="AF_UNIX datagram")
def test_status_and_extend_timeout_reach_the_socket(tmp_path, monkeypatch):
    path = str(tmp_path / "notify.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(path)
    srv.settimeout(2.0)
    monkeypatch.setenv("NOTIFY_SOCKET", path)
    n = sdnotify.Notifier()
    n.status("LINE gen 7")
    assert srv.recv(256) == b"STATUS=LINE gen 7"
    n.extend_timeout(12.5)
    assert srv.recv(256) == b"EXTEND_TIMEOUT_USEC=12500000"
    srv.close()


def test_extend_timeout_is_a_no_op_without_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    n = sdnotify.Notifier()
    n.extend_timeout(5.0), n.status("x")  # must not raise off the vehicle


# ---- the executor heartbeat ----------------------------------------------------------------

def test_a_beat_older_than_two_seconds_is_a_stalled_executor():
    assert not rd.executor_stale(10.0, 9.0)
    assert not rd.executor_stale(10.0, 8.0)
    assert rd.executor_stale(10.01, 8.0)
    assert rd.EXECUTOR_STALE_S == 2.0


# ---- base_missing: health, not topic age only (WP-H2, H-P1-2 A1) ---------------------------

def _snap(now, panel_valid=True, drives_ok=True):
    s = rd.Snapshots()
    s.mux_t = s.drives_t = s.wheels_t = s.panel_t = now
    s.panel_valid, s.drives_ok = panel_valid, drives_ok
    return s


def test_a_dead_dio_island_at_boot_is_not_ready():
    s = _snap(100.0, panel_valid=False)
    assert rd.base_missing(s, 100.0) == "panel"
    assert not rd.base_ready(s, 100.0)
    assert rd.base_ready(s, 100.0, health=False)  # topic receipt only: what ModeState.base_ready keeps
    assert "I/O island" in rd.base_actions(s)["panel"]


def test_drives_without_torque_are_missing_and_name_the_safety_reset():
    s = _snap(100.0, drives_ok=False)
    assert rd.base_missing(s, 100.0) == "drives"
    assert "safety reset" in rd.base_actions(s)["drives"]
    s.drive_fault = True
    assert "off and on" in rd.base_actions(s)["drives"]


def test_a_healthy_base_is_ready_and_a_silent_one_lists_every_item():
    assert rd.base_missing(_snap(100.0), 100.0) == ""
    assert rd.base_missing(rd.Snapshots(), 100.0) == "mux, drives, wheel feedback, panel"


def test_the_snapshot_fills_health_from_the_messages():
    s = rd.Snapshots()
    s.on_panel(types.SimpleNamespace(valid=False, mode_auto=True))
    s.on_drives(types.SimpleNamespace(operational=False, link_state="standby",
                                      left_state="Switch on disabled", right_state="Switch on disabled"))
    assert not s.panel_valid and not s.drives_ok


def test_mode_state_carries_base_missing():
    msg = (Path(__file__).resolve().parents[2] / "amr_interfaces" / "msg" / "ModeState.msg").read_text()
    fields = [ln.split("#")[0].split() for ln in msg.splitlines() if ln.split("#")[0].strip()]
    assert fields[-1] == ["string", "base_missing"]  # appended: never inserted
    src = (Path(__file__).resolve().parents[1] / "amr_bringup" / "supervisor_node.py").read_text()
    assert "m.base_missing = rd.base_missing(self.snap, now)" in src
    assert "m.base_ready = rd.base_ready(self.snap, now, health=False)" in src


# ---- the disk: / watched, read-only detected (WP-P4, H-P2-7) --------------------------------

def _usage(free_mb):
    return lambda _p: types.SimpleNamespace(free=free_mb * 1024 * 1024, total=0, used=0)


def test_root_is_watched_with_state_and_maps():
    assert disk.watched("/s", "/m") == ["/s", "/m", "/"]


def test_a_read_only_mount_is_named_and_refuses_new_work(monkeypatch):
    monkeypatch.setattr(disk.shutil, "disk_usage", _usage(5000))
    monkeypatch.setattr(disk.os, "ST_RDONLY", 1, raising=False)
    flags = {"/": 1, "/s": 0}
    st = disk.status(["/s", "/"], statvfs=lambda p: types.SimpleNamespace(f_flag=flags[p]))
    assert st.level == disk.OK and st.readonly == "/" and st.blocks_new_work
    flags["/"] = 0
    st = disk.status(["/s", "/"], statvfs=lambda p: types.SimpleNamespace(f_flag=flags[p]))
    assert st.readonly == "" and not st.blocks_new_work


def test_an_unreadable_flag_is_never_a_false_alarm(monkeypatch):
    monkeypatch.setattr(disk.shutil, "disk_usage", _usage(5000))

    def boom(_p):
        raise OSError("gone")

    assert not disk.is_readonly("/s", statvfs=boom)
    assert disk.status(["/s"], statvfs=boom).readonly == ""
    monkeypatch.delattr(disk.os, "statvfs", raising=False)
    assert not disk.is_readonly("/s")  # an OS without statvfs: unknown, not read-only


def test_disk_readonly_has_a_catalogue_row():
    from agv_core import alarms  # noqa: PLC0415

    row = alarms.get("DISK_READONLY")
    assert row.code == "DISK_READONLY" and row.severity == alarms.ERROR and row.clears_by == "engineer"


def test_group_spawn_hands_the_oom_preference_to_web_and_layer_only(monkeypatch):
    seen = {}

    class FakeProc:
        pid = 4321

    def fake_popen(argv, **kw):
        seen[argv[-1]] = kw.get("preexec_fn")
        return FakeProc()

    monkeypatch.setattr(ps.subprocess, "Popen", fake_popen)
    for role in ("web", "layer", "base"):
        ps.Group.spawn(role, ["ros2", "launch", role])
    assert callable(seen["web"]) and callable(seen["layer"]) and seen["base"] is None
