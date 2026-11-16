"""W1: the marker that tells a power cut from a crash from a clean stop.

The marker is the ONLY evidence a power cut leaves behind, so these tests are about
what the operator is told, and about the one ordering rule that makes the evidence
true: the marker is cleared last, after the children are down.
"""

import json
import os
import pathlib
import re
import time

from amr_bringup import uptime


def test_a_clean_stop_leaves_no_verdict(tmp_path):
    uptime.write(str(tmp_path), "inst", "IDLE")
    assert os.path.exists(uptime.path(str(tmp_path)))
    uptime.clear(str(tmp_path))
    assert uptime.verdict(str(tmp_path)) is None
    uptime.clear(str(tmp_path))  # clearing twice is not an error


def test_a_marker_from_before_this_boot_is_a_power_loss(tmp_path):
    uptime.write(str(tmp_path), "inst", "NAVIGATION", "op-7", "line-a-to-b")
    now = time.time()
    v = uptime.verdict(str(tmp_path), now_wall=now, boot_wall=now + 10)  # boot AFTER the write
    assert v.kind == uptime.POWER_LOSS
    assert v.mode == "NAVIGATION" and v.run_id == "line-a-to-b"
    s = v.sentence()
    assert "Power was lost" in s and "mission line-a-to-b" in s
    assert "switched off and on" in s  # the drives latched 8130h: say the action


def test_a_marker_from_this_boot_is_a_crash_and_needs_no_drive_action(tmp_path):
    uptime.write(str(tmp_path), "inst", "IDLE")
    now = time.time()
    v = uptime.verdict(str(tmp_path), now_wall=now, boot_wall=now - 3600)  # boot BEFORE the write
    assert v.kind == uptime.SERVICE_CRASH
    assert "restarted itself" in v.sentence() and "power" not in v.sentence().lower()


def test_an_operation_is_named_when_no_mission_was_running(tmp_path):
    uptime.write(str(tmp_path), "i", "MAPPING", "op-save-3")
    v = uptime.verdict(str(tmp_path), boot_wall=time.time() + 1)
    assert "operation op-save-3" in v.sentence()


def test_a_corrupt_or_missing_marker_invents_nothing(tmp_path):
    assert uptime.verdict(str(tmp_path)) is None  # missing
    pathlib.Path(uptime.path(str(tmp_path))).write_text('{"written_at": ')  # cut mid-write
    assert uptime.verdict(str(tmp_path)) is None
    pathlib.Path(uptime.path(str(tmp_path))).write_text("{}")  # valid json, no timestamp
    assert uptime.verdict(str(tmp_path)) is None


def test_writing_never_raises_on_a_bad_state_dir(tmp_path):
    bad = tmp_path / "file"
    bad.write_text("not a directory")
    uptime.write(str(bad / "under-a-file"), "i", "IDLE")  # must not raise
    assert uptime.verdict(str(bad / "under-a-file")) is None


def test_the_marker_is_atomic_and_leaves_no_tmp_behind(tmp_path):
    uptime.write(str(tmp_path), "i", "IDLE")
    uptime.write(str(tmp_path), "i", "NAVIGATION")
    assert sorted(p.name for p in tmp_path.iterdir()) == [uptime.MARKER]
    body = json.loads(pathlib.Path(uptime.path(str(tmp_path))).read_text())
    assert body["mode"] == "NAVIGATION" and body["pid"] == os.getpid()


def test_boot_time_is_readable_on_this_machine():
    bt = uptime.boot_time()
    assert bt is not None and 0 < bt < time.time()


def test_the_marker_is_cleared_last_in_shutdown():
    """If anything ran after the clear and hung, a kill would look like a clean stop."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "amr_bringup" / "supervisor_node.py").read_text()
    body = src.split("def shutdown(self)", 1)[1].split("\ndef ", 1)[0]
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert lines[-1] == "uptime.clear(self.state_dir)", lines[-3:]


def test_the_supervisor_reports_ready_to_systemd_whatever_the_boot_outcome():
    """W5's caveat: READY=1 must not sit inside a success branch, or systemd kills the
    service at TimeoutStartSec and the late-base recovery path never runs."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "amr_bringup" / "supervisor_node.py").read_text()
    loop = src.split("def _loop(self)", 1)[1].split("\n    def ", 1)[0]
    ready = re.search(r"^(\s*)self\._notify\.ready\(\)", loop, re.M)
    assert ready, "the supervisor never tells systemd it is ready"
    assert len(ready.group(1)) == 8, "ready() is nested in a branch; it must run on every path"


def test_a_boot_event_waits_for_a_listener():
    """/amr/events is volatile and the web is spawned BY the supervisor: publishing the
    power-loss verdict at boot put it in an empty room (caught in sim, 2026-09-22)."""
    import types  # noqa: PLC0415

    from amr_bringup.supervisor_node import Supervisor  # noqa: PLC0415

    sv = types.SimpleNamespace()
    sv.published, sv.logged, sv._deferred, sv.now = [], [], [], 100.0
    sv.subs = 0
    sv._now = lambda: sv.now
    sv._event = lambda lvl, code, text: sv.published.append(code)
    sv._pub_event = types.SimpleNamespace(get_subscription_count=lambda: sv.subs)
    sv.get_logger = lambda: types.SimpleNamespace(warn=lambda s: sv.logged.append(s), info=print, error=print)
    for name in ("_event_when_heard", "_flush_deferred"):
        setattr(sv, name, types.MethodType(getattr(Supervisor, name), sv))

    sv._event_when_heard(2, "UNCLEAN_SHUTDOWN", "power was lost")
    assert sv.published == [] and len(sv._deferred) == 1  # nobody listening yet: held
    sv.now += 5.0
    sv._flush_deferred()
    assert sv.published == []
    sv.subs = 1  # the web finished starting and subscribed
    sv._flush_deferred()
    assert sv.published == ["UNCLEAN_SHUTDOWN"] and sv._deferred == []
    sv._flush_deferred()
    assert sv.published == ["UNCLEAN_SHUTDOWN"]  # exactly once


def test_a_boot_event_is_given_up_on_rather_than_held_for_ever():
    import types  # noqa: PLC0415

    from amr_bringup.supervisor_node import DEFER_EVENT_S, Supervisor  # noqa: PLC0415

    sv = types.SimpleNamespace()
    sv.published, sv.logged, sv._deferred, sv.now = [], [], [], 0.0
    sv._now = lambda: sv.now
    sv._event = lambda lvl, code, text: sv.published.append(code)
    sv._pub_event = types.SimpleNamespace(get_subscription_count=lambda: 0)
    sv.get_logger = lambda: types.SimpleNamespace(warn=lambda s: sv.logged.append(s))
    for name in ("_event_when_heard", "_flush_deferred"):
        setattr(sv, name, types.MethodType(getattr(Supervisor, name), sv))

    sv._event_when_heard(1, "BOOT_READY", "ready")
    sv.now = DEFER_EVENT_S + 1
    sv._flush_deferred()
    assert sv.published == [] and sv._deferred == []
    assert "BOOT_READY not delivered" in sv.logged[0]  # it still reaches the log


# ---- boot id and $SERVICE_RESULT (S-uptime-boot-id-and-service-result, WP-H5, 2026-11-16)

def _marker(at=1000.0, boot="boot-A", **kw):
    return {"written_at": at, "boot_id": boot, "mode": "LINE", **kw}


def test_classify_a_different_boot_id_is_a_power_loss_whatever_the_clock_says():
    # boot_wall says "this boot" (an RTC error or NTP step): the boot id wins
    assert uptime.classify(_marker(), "boot-B", boot_wall=0.0) == (uptime.POWER_LOSS, "")


def test_classify_the_same_boot_id_is_a_crash_whatever_the_clock_says():
    kind, cause = uptime.classify(_marker(), "boot-A", boot_wall=5000.0)  # clock says older
    assert kind == uptime.SERVICE_CRASH and cause == ""


def test_classify_without_boot_ids_falls_back_to_the_boot_time():
    old = {"written_at": 1000.0}  # a marker written before boot_id existed
    assert uptime.classify(old, "boot-A", boot_wall=2000.0)[0] == uptime.POWER_LOSS
    assert uptime.classify(old, "boot-A", boot_wall=500.0)[0] == uptime.SERVICE_CRASH
    assert uptime.classify(_marker(), None, boot_wall=500.0)[0] == uptime.SERVICE_CRASH
    # no boot id and no boot time: the heavier action
    assert uptime.classify(old, None, boot_wall=None)[0] == uptime.POWER_LOSS


def test_classify_names_the_service_result_of_this_runs_stop():
    stop = {"at": 1001.0, "boot_id": "boot-A", "service_result": "watchdog"}
    want = (uptime.SERVICE_CRASH, uptime.RESULT_TEXT["watchdog"])
    assert uptime.classify(_marker(), "boot-A", None, stop) == want
    sig = {"at": 1001.0, "boot_id": "boot-A", "service_result": "signal", "exit_status": "KILL"}
    assert uptime.classify(_marker(), "boot-A", None, sig)[1].endswith("(KILL)")
    oom = {"at": 1001.0, "boot_id": "boot-A", "service_result": "oom-kill"}
    assert "memory" in uptime.classify(_marker(), "boot-A", None, oom)[1]


def test_classify_ignores_a_stop_record_that_is_not_this_runs():
    older = {"at": 999.0, "boot_id": "boot-A", "service_result": "watchdog"}  # before the marker
    other_boot = {"at": 1001.0, "boot_id": "boot-Z", "service_result": "watchdog"}
    unknown = {"at": 1001.0, "boot_id": "boot-A", "service_result": "success"}
    for stop in (older, other_boot, unknown, {"at": "x"}, None):
        assert uptime.classify(_marker(), "boot-A", None, stop) == (uptime.SERVICE_CRASH, ""), stop
    # a power cut runs no ExecStopPost: whatever record is there names nothing
    stale = {"at": 1001.0, "boot_id": "boot-A", "service_result": "watchdog"}
    assert uptime.classify(_marker(), "boot-B", None, stale) == (uptime.POWER_LOSS, "")


def test_the_marker_carries_the_boot_id_and_the_verdict_uses_it(tmp_path, monkeypatch):
    monkeypatch.setattr(uptime, "boot_id", lambda source=uptime.BOOT_ID_PATH: "boot-A")
    uptime.write(str(tmp_path), "i", "LINE")
    body = json.loads(pathlib.Path(uptime.path(str(tmp_path))).read_text())
    assert body["boot_id"] == "boot-A"
    v = uptime.verdict(str(tmp_path), this_boot_id="boot-B")
    assert v.kind == uptime.POWER_LOSS
    v = uptime.verdict(str(tmp_path), this_boot_id="boot-A")
    assert v.kind == uptime.SERVICE_CRASH and v.cause == ""


def test_stop_post_records_the_result_and_the_crash_sentence_says_it(tmp_path, monkeypatch):
    monkeypatch.setattr(uptime, "boot_id", lambda source=uptime.BOOT_ID_PATH: "boot-A")
    uptime.write(str(tmp_path), "i", "LINE")
    time.sleep(0.01)
    env = {"SERVICE_RESULT": "watchdog", "EXIT_CODE": "killed", "EXIT_STATUS": "INT"}
    uptime.stop_post(str(tmp_path), env)
    stop = json.loads((tmp_path / uptime.LAST_STOP).read_text())
    assert stop["service_result"] == "watchdog" and stop["boot_id"] == "boot-A"
    v = uptime.verdict(str(tmp_path), this_boot_id="boot-A")
    s = v.sentence()
    assert v.kind == uptime.SERVICE_CRASH and "watchdog" in s and "restarted itself" in s
    assert "switch them off and on" in s  # 8130h is possible after a crash (WP-H5)


def test_stop_post_never_raises_and_the_cli_always_exits_0(tmp_path, monkeypatch):
    bad = tmp_path / "file"
    bad.write_text("x")
    uptime.stop_post(str(bad / "under"), {})  # must not raise
    monkeypatch.setenv("AMR_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SERVICE_RESULT", "exit-code")
    assert uptime.main(["stop-post"]) == 0
    assert json.loads((tmp_path / uptime.LAST_STOP).read_text())["service_result"] == "exit-code"
    assert uptime.main([]) == 0


def test_boot_id_is_none_when_unreadable(tmp_path):
    assert uptime.boot_id(str(tmp_path / "missing")) is None
    (tmp_path / "id").write_text("  0f1e\n")
    assert uptime.boot_id(str(tmp_path / "id")) == "0f1e"


def test_groups_file_is_role_to_pgid_and_a_clean_stop_removes_it(tmp_path):
    uptime.note_group(str(tmp_path), "web", 111)
    uptime.note_group(str(tmp_path), "base", 222)
    uptime.note_group(str(tmp_path), "web", 333)  # respawned
    body = json.loads((tmp_path / uptime.GROUPS).read_text())
    assert body["groups"] == {"web": 333, "base": 222}
    (tmp_path / uptime.GROUPS).write_text("{corrupt")
    uptime.note_group(str(tmp_path), "layer", 444)  # a corrupt file is replaced, not fatal
    assert json.loads((tmp_path / uptime.GROUPS).read_text())["groups"] == {"layer": 444}
    uptime.write(str(tmp_path), "i", "IDLE")
    uptime.clear(str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_amr_service_runs_stop_post_and_the_wrapper_calls_this_module():
    deploy = pathlib.Path(__file__).resolve().parents[3] / "deploy"
    unit = (deploy / "amr.service").read_text()
    assert "ExecStopPost=-/home/gvipc-evo-01/agv_can/amr_ws/deploy/amr-stop-post.sh" in unit
    wrapper = (deploy / "amr-stop-post.sh").read_text()
    assert "amr_bringup.uptime stop-post" in wrapper
