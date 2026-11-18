"""Deploy contracts for unclean death, CAN re-plug, logs, watchdog and platform freeze
(unified plan WP-H5, WP-P3, WP-P4, WP-P5, WP-P1; 2026-11-16).

These files are applied by the owner with install.sh, off-shift, so the only check before
the vehicle is this one: parse what the repo would install. Pattern: test_shutdown_order.
"""

import importlib.util
import json
import os
import re
import signal
from pathlib import Path

import pytest

from amr_bringup import uptime

WS = Path(__file__).resolve().parents[3]
DEPLOY = WS / "deploy"
REPO = WS.parent


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _unit(name: str) -> dict[str, list[tuple[str, str]]]:
    """systemd unit -> {section: [(key, value)]}; keys may repeat (ExecStartPre)."""
    out, section = {}, None
    for raw in _text(DEPLOY / name).splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            out.setdefault(section, [])
            continue
        k, _, v = line.partition("=")
        out[section].append((k.strip(), v.strip()))
    return out


def _values(unit, section, key):
    return [v for k, v in unit.get(section, []) if k == key]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


orphan = _load("amr_orphan_stop", DEPLOY / "amr-orphan-stop.py")
failed = _load("amr_failed", DEPLOY / "amr-failed.py")


# ---------------------------------------------------------------- WP-H5: amr.service

def test_amr_service_handles_an_unclean_death():
    u = _unit("amr.service")
    assert _values(u, "Service", "WatchdogSignal") == ["SIGINT"]  # ordered teardown, not SIGABRT
    assert _values(u, "Service", "OOMPolicy") == ["continue"]
    adj = _values(u, "Service", "OOMScoreAdjust")
    assert len(adj) == 1 and -1000 < int(adj[0]) < 0  # protected, never unkillable
    assert _values(u, "Unit", "OnFailure") == ["amr-failed.service"]
    stop = _values(u, "Service", "ExecStop")
    assert stop == ["-/home/gvipc-evo-01/agv_can/amr_ws/deploy/amr-orphan-stop.sh"], stop
    # the supervisor's own SIGINT teardown is still the normal stop path
    assert _values(u, "Service", "KillSignal") == ["SIGINT"]
    assert _values(u, "Service", "KillMode") == ["mixed"]


def test_amr_service_removes_the_failed_page_before_it_starts():
    pre = _values(_unit("amr.service"), "Service", "ExecStartPre")
    assert f"+/bin/rm -f {failed.OUT}" in pre, pre
    # before ExecStart runs, i.e. in ExecStartPre, and as root ("+"): the page is root's
    start = _values(_unit("amr.service"), "Service", "ExecStart")
    assert start and start[0].endswith("amr-supervisor.sh")


def test_the_kiosk_shows_exactly_the_page_amr_failed_writes():
    kiosk = _text(DEPLOY / "kiosk" / "amr-kiosk-browser")
    m = re.search(r"^FALLBACK=(\S+)$", kiosk, re.M)
    assert m, "the kiosk lost its FALLBACK= line"
    assert m.group(1) == failed.OUT == "/run/amr/failed.html"
    assert "systemctl is-failed --quiet amr.service" in kiosk


def test_amr_failed_service_runs_the_root_owned_copy_and_is_never_enabled():
    u = _unit("amr-failed.service")
    assert _values(u, "Service", "Type") == ["oneshot"]
    assert _values(u, "Service", "ExecStart") == ["/usr/bin/python3 -I /usr/local/sbin/amr-failed"]
    assert "Install" not in u  # started by OnFailure= only
    install = _text(DEPLOY / "install.sh")
    assert '"$DEPLOY_DIR/amr-failed.py" /usr/local/sbin/amr-failed' in install
    assert re.search(r"^UNITS=\(.*\bamr-failed\.service\b", install, re.M)


def test_the_failed_page_names_the_identity_mismatch():
    lines = ["identity: host gvipc-evo-02 must run profile agv-02, but profile agv-01 is loaded. Set "
             "AGV_PROFILE=agv-02 in $AMR_STATE_DIR/vehicle.env (manuals/agv-02-plan.md), or fix the host "
             "name. Nothing was started."]
    page = failed.render({"Result": "start-limit-hit", "NRestarts": "3"}, lines, "gvipc-evo-02", 0.0)
    assert "Call the engineer" in page and "wrong vehicle" in page
    assert "vehicle.env" in page and "systemctl reset-failed amr" in page
    assert "must run profile agv-02" in page  # the journal's own sentence, quoted


def test_the_failed_page_otherwise_says_what_systemd_saw_and_escapes_the_journal():
    state = {"Result": "watchdog", "ExecMainStatus": "2"}
    page = failed.render(state, ["<script>x</script> & more"], "h", 0.0)
    assert "wrong vehicle" not in page
    assert failed.RESULT_TEXT["watchdog"] in page
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "journalctl -u amr.service -b" in page
    plain = failed.render({}, [], "h", 0.0)
    assert "(no journal lines)" in plain and "result ?" in plain


def test_the_failed_page_is_world_readable_in_a_world_readable_dir(tmp_path):
    out = tmp_path / "amr" / "failed.html"
    failed.write("<p>x</p>", str(out))
    assert out.read_text() == "<p>x</p>"
    assert not (out.parent / "failed.html.tmp").exists()
    if os.name == "posix":
        assert (out.stat().st_mode & 0o777) == 0o644
        assert (out.parent.stat().st_mode & 0o777) == 0o755


def test_journal_tail_prefers_the_failed_invocation():
    calls = []

    def journal(argv):
        calls.append(argv)
        return "a\nb\n" if any(a.startswith("_SYSTEMD_INVOCATION_ID=") for a in argv) else ""

    assert failed.journal_tail("abc", journal) == ["a", "b"]
    calls.clear()
    assert failed.journal_tail("", journal) == []
    assert calls and "-u" in calls[0]


# ---------------------------------------------------------------- WP-H5: orphan stop

def _fake(pgids: dict[int, int]):
    return lambda pid: pgids.get(pid)


def test_orphans_are_stopped_base_first_and_only_from_this_cgroup():
    pids = [500, 501, 600, 601, 700, 900]
    pg = _fake({500: 500, 501: 500, 600: 600, 601: 600, 700: 700, 900: 900})
    groups = {"web": 700, "layer": 600, "base": 500, "gone": 4242}  # 4242: not in the cgroup
    todo = orphan.plan(pids, pg, groups, lambda pid: "", own_pgid=900)
    assert todo == [("base", 500), ("layer", 600), ("web", 700)]  # own group 900 left alone


def test_orphans_without_groups_json_are_named_by_their_leaders_command_line():
    pids = [10, 20, 30]
    pg = _fake({10: 10, 20: 20, 30: 30})
    cmd = {10: "python3 -m amr_web.web_node", 20: "ros2 launch amr_bringup line_layer.launch.py",
           30: "ros2 launch amr_bringup base.launch.py real:=true"}
    todo = orphan.plan(pids, pg, {}, lambda pid: cmd.get(pid, ""), own_pgid=1)
    assert todo == [("base", 30), ("layer", 20), ("web", 10)]


def test_orphan_stop_reads_what_uptime_writes(tmp_path):
    assert orphan.GROUPS == uptime.GROUPS
    uptime.note_group(str(tmp_path), "base", 321)
    assert orphan.read_groups(str(tmp_path / orphan.GROUPS)) == {"base": 321}
    assert orphan.read_groups(str(tmp_path / "missing.json")) == {}


def test_own_cgroup_is_the_v2_line(tmp_path):
    (tmp_path / "cgroup").write_text("0::/system.slice/amr.service\n")
    assert orphan.own_cgroup_procs(str(tmp_path / "cgroup"), "/sys/fs/cgroup") == os.path.join(
        "/sys/fs/cgroup", "system.slice/amr.service", "cgroup.procs")
    assert orphan.own_cgroup_procs(str(tmp_path / "none")) is None


class _Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_orphan_stop_signals_the_base_waits_for_it_then_the_rest_within_12_s(tmp_path):
    procs = tmp_path / "cgroup.procs"
    alive = {500: 500, 501: 500, 61: 600, 700: 700}  # 600's leader is dead, a member lives
    procs.write_text("\n".join(map(str, alive)))
    uptime.note_group(str(tmp_path), "base", 500)
    uptime.note_group(str(tmp_path), "layer", 600)
    uptime.note_group(str(tmp_path), "web", 700)
    clock, sent = _Clock(), []

    def kill(pid, sig):
        sent.append(("kill", pid, sig, clock.t))
        if pid == 500:  # the base leader stops its nodes after 2 s
            clock.t += 2.0
            for p in (500, 501):
                alive.pop(p)
            procs.write_text("\n".join(map(str, alive)))

    def killpg(pg, sig):
        sent.append(("killpg", pg, sig, clock.t))

    out = orphan.run(str(tmp_path), str(procs), pgid_of=lambda p: alive.get(p), cmdline_of=lambda p: "",
                     kill=kill, killpg=killpg, now=clock.now, sleep=clock.sleep, own_pgid=1,
                     log=lambda s: None)
    assert sent[0][:3] == ("kill", 500, signal.SIGINT)  # base first, to its launch leader
    assert ("killpg", 600, signal.SIGINT) in [s[:3] for s in sent]  # leaderless group: every member
    assert ("kill", 700, signal.SIGINT) in [s[:3] for s in sent]
    assert all(s[3] >= 2.0 for s in sent[1:])  # the rest only after the base had its turn
    want = {("base", 500): True, ("layer", 600): False, ("web", 700): False}
    assert dict(((r, g), e) for r, g, e in out) == want
    assert clock.t <= orphan.BUDGET_S + 0.2


def test_orphan_stop_with_nothing_left_does_nothing(tmp_path):
    procs = tmp_path / "cgroup.procs"
    procs.write_text("")
    sent = []
    assert orphan.run(str(tmp_path), str(procs), pgid_of=lambda p: p, kill=lambda *a: sent.append(a),
                      killpg=lambda *a: sent.append(a), own_pgid=1, log=lambda s: None) == []
    assert sent == []
    assert orphan.run(str(tmp_path), None, own_pgid=1, log=lambda s: None) == []


def test_orphan_stop_is_a_no_op_while_the_supervisor_lives():
    sh = _text(DEPLOY / "amr-orphan-stop.sh")
    assert re.search(r'kill -0 "\$MAINPID".*\n\s*exit 0', sh)
    assert "amr-orphan-stop.py" in sh and "python3 -I" in sh
    assert orphan.BUDGET_S <= 12.0 < 55  # well inside TimeoutStopSec


# ---------------------------------------------------------------- WP-P3: CAN re-plug

def test_amr_service_is_wanted_by_the_can_bridge():
    u = _unit("amr.service")
    wanted = " ".join(_values(u, "Install", "WantedBy")).split()
    assert "canable@can0.service" in wanted and "multi-user.target" in wanted
    assert _values(u, "Unit", "BindsTo") == ["sys-subsystem-net-devices-can0.device"]


def test_canable_unit_restarts_on_failure():
    u = _unit("canable@.service")
    assert _values(u, "Service", "Restart") == ["on-failure"]
    assert _values(u, "Service", "RestartSec") == ["2"]
    assert _values(u, "Unit", "BindsTo") == ["dev-canable0.device"]
    assert _values(u, "Service", "ExecStart") == ["/usr/bin/slcand -o -c -f -s4 -F /dev/canable0 %i"]
    install = _text(DEPLOY / "install.sh")
    assert re.search(r"^UNITS=\(.*\bcanable@\.service\b", install, re.M)


def test_canable_rule_is_a_per_unit_template():
    rules = _text(DEPLOY / "70-canable.rules.in")
    body = "\n".join(ln for ln in rules.splitlines() if not ln.lstrip().startswith("#"))
    assert body.count('serial}=="@ADAPTER_SERIAL@"') == 2  # tty symlink + usb power rule
    assert not re.search(r'serial}=="[0-9A-F]{8,}"', body)  # no unit's serial baked in
    assert 'ENV{SYSTEMD_WANTS}="canable@can0.service"' in body
    assert 'ATTR{power/control}="on"' in body
    assert 'ACTION!="remove"' in body


def test_install_renders_the_rule_from_the_profile_and_refuses_an_empty_serial():
    install = _text(DEPLOY / "install.sh")
    assert '["can"]["adapter_serial"]' in install
    assert "^[A-Za-z0-9]{4,32}$" in install and "refusing:" in install
    assert "s/@ADAPTER_SERIAL@/$serial/g" in install
    # refused before anything is installed: the check comes before the first `install -m`
    assert install.index("refusing: profiles/") < install.index("install -m")
    with open(REPO / "profiles" / "agv-01.json", encoding="utf-8") as fh:
        assert re.fullmatch(r"[A-Za-z0-9]{4,32}", json.load(fh)["can"]["adapter_serial"])


def test_web_sudo_rules_cannot_clear_an_identity_mismatch():
    lines = [ln for ln in _text(DEPLOY / "amr-web.sudoers").splitlines() if ln and not ln.startswith("#")]
    cmds = [ln.split("NOPASSWD:", 1)[1].strip() for ln in lines]
    assert cmds == [
        "/usr/bin/systemctl restart amr.service",
        "/usr/bin/journalctl -u amr.service --since -2h --no-pager",
        "/usr/bin/journalctl -u agv-wifi-reconnect.service --since -2h --no-pager",
        "/usr/bin/systemctl reset-failed canable@can0.service",
    ]
    assert not any("reset-failed" in c and "amr" in c.split("reset-failed", 1)[1] for c in cmds)


# ---------------------------------------------------------------- WP-P4: logs

def test_ros_logs_live_under_the_state_dir_and_age_out():
    sh = _text(DEPLOY / "amr-supervisor.sh")
    assert 'export ROS_LOG_DIR="$AMR_STATE_DIR/ros_log"' in sh
    assert sh.index("ROS_LOG_DIR=") < sh.index("exec python3 -m amr_bringup.supervisor_node")
    assert re.search(r"--ros-args \\\n\s+--disable-external-lib-logs \\\n", sh)
    tmp = [ln.split() for ln in _text(DEPLOY / "tmpfiles-amr.conf").splitlines()
           if ln.strip() and not ln.startswith("#")]
    assert ["e", "/home/gvipc-evo-01/.amr/ros_log", "-", "-", "-", "7d"] in tmp
    assert all(t[0] == "e" for t in tmp)  # clean only, never create
    assert not any("maps" in t[1] or "operations" in t[1] or "events" in t[1] for t in tmp)
    assert "tmpfiles-amr.conf /etc/tmpfiles.d/amr.conf" in _text(DEPLOY / "install.sh")


# ---------------------------------------------------------------- WP-P5: watchdog

def test_hardware_watchdog_files_and_only_on_request():
    mods = [ln for ln in _text(DEPLOY / "iTCO_wdt.conf").splitlines() if ln and not ln.startswith("#")]
    assert mods == ["iTCO_wdt"]
    u = _unit("systemd-watchdog-amr.conf")
    assert _values(u, "Manager", "RuntimeWatchdogSec") == ["30"]
    assert re.search(r"^kernel\.panic = 10$", _text(DEPLOY / "sysctl-amr.conf"), re.M)
    install = _text(DEPLOY / "install.sh")
    gated = install.split('if [[ "$WATCHDOG" == yes ]]; then', 1)[1].split("fi", 1)[0]
    assert "iTCO_wdt.conf /etc/modules-load.d/iTCO_wdt.conf" in gated
    assert "/etc/systemd/system.conf.d/60-amr-watchdog.conf" in gated
    assert "wdctl" in _text(WS / "RUNBOOK.md")


# ---------------------------------------------------------------- WP-P1: platform freeze

PLATFORM = DEPLOY / "platform"


def test_ros_comes_from_the_2026_09_14_snapshot_and_never_from_the_live_repo():
    src = _text(PLATFORM / "ros2-snapshot.sources")
    assert re.search(r"^URIs: http://snapshots\.ros\.org/humble/2026-09-14/ubuntu$", src, re.M)
    keyring = re.search(r"^Signed-By: (\S+)$", src, re.M).group(1)
    assert f"KEYRING={keyring}" in _text(PLATFORM / "freeze.sh")
    assert f"-s {keyring} ]]" in _text(DEPLOY / "install.sh")  # sources only once the key is there
    pref = [ln for ln in _text(PLATFORM / "apt-preferences-amr").splitlines()
            if ln and not ln.startswith("#")]
    assert pref == ["Package: *", "Pin: origin packages.ros.org", "Pin-Priority: -1"]


def test_needrestart_and_unattended_never_touch_the_vehicle_stack():
    nr = _text(PLATFORM / "needrestart-amr.conf")
    assert r"$nrconf{override_rc}{qr(^amr\.service$)} = 0;" in nr
    assert "$nrconf{kernelhints} = -1;" in nr
    ua = _text(PLATFORM / "52amr-unattended")
    assert 'APT::Periodic::Unattended-Upgrade "0";' in ua
    assert '"ros-humble-";' in ua and '"linux-";' in ua


def test_freeze_holds_kernel_snaps_and_records_the_fallback():
    fz = _text(PLATFORM / "freeze.sh")
    assert "snap refresh --hold" in fz  # every snap, chromium included (moved from alpha-setup 7.1)
    assert "apt-mark hold" in fz and "apt-mark manual" in fz and "linux-generic-hwe-22.04" in fz
    assert "apt-get purge -y ros2-apt-source" in fz
    assert "GRUB fallback" in fz
    alpha = _text(REPO / "alpha-setup.md")
    assert "http://packages.ros.org/ros2/ubuntu jammy main\" | sudo tee" not in alpha
    assert "snap refresh --hold chromium" not in alpha
    assert "freeze.sh --go" in alpha


def test_validate_checks_failed_units_and_the_platform():
    v = _text(DEPLOY / "validate.sh")
    block = v.split("for unit in amr.service amr-failed.service", 1)[1].split("done", 1)[0]
    for unit in ("canable@can0.service", "agv-wifi-reconnect.service", "cpu-power-limit.service",
                 "cpu-freq-cap.service"):
        assert unit in block, unit
    assert "systemctl is-failed --quiet" in block
    assert "apt-cache policy" in v and "apt-mark showhold" in v


@pytest.mark.parametrize("script", ["amr-orphan-stop.sh", "amr-stop-post.sh", "amr-supervisor.sh",
                                    "install.sh", "validate.sh", "platform/freeze.sh"])
def test_deploy_scripts_are_bash(script):
    assert _text(DEPLOY / script).startswith("#!/bin/bash\n")


def test_the_kiosk_shows_the_failed_page_through_nginx_not_file_url():
    """unit 2, 2026-11-18: the kiosk policy blocks file:// (URLBlocklist "*", allow 127.0.0.1 only) and the
    Chromium snap cannot read /run/amr. The browser opens nginx's /amr-failed.html, which aliases the file
    amr-failed writes; alpha-setup 7.3 carries that location."""
    import pathlib  # noqa: PLC0415

    repo = pathlib.Path(__file__).resolve().parents[4]
    browser = (repo / "amr_ws/deploy/kiosk/amr-kiosk-browser").read_text(encoding="utf-8")
    assert "FALLBACK_URL=http://127.0.0.1/amr-failed.html" in browser
    assert 'echo "file://' not in browser
    guide = (repo / "alpha-setup.md").read_text(encoding="utf-8")
    assert "location = /amr-failed.html {\n        alias /run/amr/failed.html;" in guide
