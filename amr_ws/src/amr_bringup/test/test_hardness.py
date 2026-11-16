"""Phase 3 hardness: what happens when a piece of the stack dies.

The mechanisms are tested here without ROS or processes - a fake Group and a fake
clock - because the interesting behaviour is the POLICY (respawn how often, give
up when, say what), not the spawning. The end-to-end version lives in
test_fault_injection_sim.py and is opt-in.
"""

import os
import tempfile
import types

from amr_bringup import sdnotify
from amr_bringup.supervisor_node import RESPAWN_BACKOFF_S, RESPAWN_TRIES, Supervisor


class Log:
    def __init__(self):
        self.lines = []

    def warn(self, s):
        self.lines.append(("warn", s))

    def error(self, s):
        self.lines.append(("error", s))

    info = warn


class Dead:
    requested_stop = False
    started = float("inf")  # always "just started": a quick death unless a test says otherwise

    def poll(self):
        return 1

    def describe(self):
        return "web pgid=123"


class Alive:
    requested_stop = False
    pgid = 456

    def poll(self):
        return None

    def describe(self):
        return "web pgid=456"


def sv_with_web(monkeypatch, spawn_result=None, spawn_raises=None):
    sv = types.SimpleNamespace()
    sv.groups = {"web": Dead()}
    sv._respawnable = {"web": ["python3", "-m", "amr_web.web_node"]}
    sv._respawn_at, sv._respawn_tries = {}, {}
    sv._logs = "/tmp"
    sv.state_dir = tempfile.mkdtemp()
    sv._status_note, sv.statuses = "", []
    sv._send_status = lambda: sv.statuses.append(sv._status_note)
    sv._env = lambda: {}
    sv.events = []
    sv._event = lambda level, code, text: sv.events.append((code, text))
    sv.log = Log()
    sv.get_logger = lambda: sv.log
    sv.spawned = []

    def spawn(role, argv, env=None, log_path=None):
        sv.spawned.append(role)
        if spawn_raises:
            raise spawn_raises
        return spawn_result or Alive()

    import amr_bringup.supervisor_node as node  # noqa: PLC0415

    # scoped to the test: Group.spawn is the real thing again afterwards
    monkeypatch.setattr(node.Group, "spawn", staticmethod(spawn))
    for name in ("_reap", "_respawn_due", "_spawn"):
        setattr(sv, name, types.MethodType(getattr(Supervisor, name), sv))
    return sv


def test_a_dead_web_comes_back_after_the_backoff_not_immediately(monkeypatch):
    """The web is the operator's only window; it was also the least protected process."""
    sv = sv_with_web(monkeypatch)
    sv._reap(100.0)
    assert sv.spawned == [] and "web" not in sv.groups  # not instantly: a crash loop must not spin
    sv._respawn_due(100.0 + RESPAWN_BACKOFF_S - 0.1)
    assert sv.spawned == []
    sv._respawn_due(100.0 + RESPAWN_BACKOFF_S)
    assert sv.spawned == ["web"] and "web" in sv.groups


def test_a_web_that_keeps_dying_gives_up_and_says_so(monkeypatch):
    sv = sv_with_web(monkeypatch)
    now = 100.0
    for _ in range(RESPAWN_TRIES):
        sv.groups["web"] = Dead()
        sv._reap(now)
        now += RESPAWN_BACKOFF_S
        sv._respawn_due(now)
    assert len(sv.spawned) == RESPAWN_TRIES
    sv.groups["web"] = Dead()
    sv._reap(now)
    sv._respawn_due(now + RESPAWN_BACKOFF_S)
    assert len(sv.spawned) == RESPAWN_TRIES  # no fourth attempt
    assert sv.events and sv.events[-1][0] == "WEB_DOWN"


def test_a_failed_respawn_is_retried_rather_than_lost(monkeypatch):
    sv = sv_with_web(monkeypatch, spawn_raises=OSError("no such executable"))
    sv._reap(100.0)
    sv._respawn_due(100.0 + RESPAWN_BACKOFF_S)
    assert "web" in sv._respawn_at  # scheduled again, not dropped on the floor


def test_a_dead_base_is_still_a_fault_and_is_never_respawned(monkeypatch):
    """Respawning the base would re-arm the drives behind the operator's back."""
    sv = sv_with_web(monkeypatch)
    sv.groups = {"base": Dead()}
    sv.failed = []
    sv._fail_active = lambda code, why: sv.failed.append(code)
    sv._reap(100.0)
    assert sv.failed == ["BASE_EXITED"] and sv.spawned == []


def test_the_watchdog_notifier_is_a_no_op_without_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    n = sdnotify.Notifier()
    assert not n.enabled
    n.ready(), n.watchdog(), n.stopping()  # must not raise off the vehicle


def test_the_watchdog_notifier_pings_the_socket(tmp_path, monkeypatch):
    import socket  # noqa: PLC0415

    path = str(tmp_path / "notify.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(path)
    srv.settimeout(2.0)
    monkeypatch.setenv("NOTIFY_SOCKET", path)
    monkeypatch.setenv("WATCHDOG_USEC", "30000000")
    n = sdnotify.Notifier()
    assert n.enabled and abs(n.interval_s - 15.0) < 1e-6  # ping at HALF WatchdogSec
    n.ready()
    assert srv.recv(64) == b"READY=1"
    n.watchdog()
    assert srv.recv(64) == b"WATCHDOG=1"
    srv.close()
    os.unlink(path)


# ---- WP-H4 (H-P1-5): respawn reset, the exits file, the executor heartbeat ----------------


def test_a_long_lived_web_respawns_for_ever(monkeypatch):
    """Only quick deaths in a row give up: a web that ran 120 s starts its tries again."""
    sv = sv_with_web(monkeypatch)
    now = 1000.0
    for _ in range(3 * RESPAWN_TRIES):
        dead = Dead()
        dead.started = now - 200.0
        sv.groups["web"] = dead
        sv._reap(now)
        now += RESPAWN_BACKOFF_S
        sv._respawn_due(now)
    assert len(sv.spawned) == 3 * RESPAWN_TRIES and not sv.events


def test_three_quick_deaths_give_up_through_systemctl_status_too(monkeypatch):
    sv = sv_with_web(monkeypatch)
    now = 100.0
    for _ in range(RESPAWN_TRIES + 1):
        dead = Dead()
        dead.started = now - 1.0
        sv.groups["web"] = dead
        sv._reap(now)
        now += RESPAWN_BACKOFF_S
        sv._respawn_due(now)
    assert len(sv.spawned) == RESPAWN_TRIES and sv.events[-1][0] == "WEB_DOWN"
    assert sv.statuses and "web gave up" in sv.statuses[-1]


def test_a_planted_exits_file_names_the_node_in_base_exited(monkeypatch):
    from amr_bringup import exits  # noqa: PLC0415

    sv = sv_with_web(monkeypatch)
    sv.groups = {"base": Dead()}
    sv.failed = []
    sv._fail_active = lambda code, why: sv.failed.append((code, why))
    exits.record(sv.state_dir, "base", "drive_node", -6)
    sv._reap(100.0)
    code, why = sv.failed[0]
    assert code == "BASE_EXITED" and why.startswith("drive_node exited with code -6")


def test_a_spawn_clears_the_old_exit_and_notes_the_group(monkeypatch):
    import json  # noqa: PLC0415

    from amr_bringup import exits, uptime  # noqa: PLC0415

    sv = sv_with_web(monkeypatch)
    seen = {}

    def spawn(role, argv, env=None, log_path=None):
        seen["env"] = env
        return Alive()

    import amr_bringup.supervisor_node as node  # noqa: PLC0415

    monkeypatch.setattr(node.Group, "spawn", staticmethod(spawn))
    exits.record(sv.state_dir, "base", "drive_node", 1)
    sv._spawn("base", ["ros2", "launch", "amr_bringup", "base.launch.py"])
    assert exits.read(sv.state_dir, "base") is None
    assert seen["env"][exits.ROLE_ENV] == "base"
    with open(os.path.join(sv.state_dir, uptime.GROUPS)) as fh:
        assert json.load(fh)["groups"] == {"base": 456}


def _lease_sv(stale):
    from amr_bringup import mode_fsm as fsm  # noqa: PLC0415

    return types.SimpleNamespace(txn=None, mode=fsm.LINE, inhibit_manual=False, _exec_stale=stale,
                                 _emergency=lambda now: 0, _now=lambda: 100.0)


def test_a_stale_executor_withholds_the_watchdog_and_the_lease(monkeypatch):
    sv = types.SimpleNamespace(_t_exec=100.0, _t_feed=200.0, _exec_stale=False, pings=[])
    sv._notify = types.SimpleNamespace(watchdog=lambda: sv.pings.append(1))
    sv.log = Log()
    sv.get_logger = lambda: sv.log
    watch = types.MethodType(Supervisor._watch_executor, sv)
    watch(101.0)
    assert sv.pings == [1] and not sv._exec_stale
    watch(102.5)
    assert sv.pings == [1] and sv._exec_stale  # no WATCHDOG=1: systemd restarts a wedged executor
    assert any(kind == "error" and "executor stalled" in text for kind, text in sv.log.lines)
    assert Supervisor._allowed(_lease_sv(True)) == 0  # authority goes; nothing else does
    assert Supervisor._allowed(_lease_sv(False)) != 0
    sv._t_exec = 102.4
    watch(102.6)
    assert sv.pings == [1, 1] and not sv._exec_stale


# ---- WP-C4 (C#9): the high-rate inputs on a feed node with its own executor ---------------------


def test_a_stalled_feed_executor_withholds_the_watchdog_and_the_lease_too():
    """The main executor still beats, the feed's does not: the inputs no longer arrive, so the
    loop treats it like a wedged executor (no WATCHDOG=1, lease withheld) and names the feed."""
    sv = types.SimpleNamespace(_t_exec=100.0, _t_feed=100.0, _exec_stale=False, pings=[])
    sv._notify = types.SimpleNamespace(watchdog=lambda: sv.pings.append(1))
    sv.log = Log()
    sv.get_logger = lambda: sv.log
    watch = types.MethodType(Supervisor._watch_executor, sv)
    sv._t_exec = 102.4  # the main executor keeps beating
    watch(102.5)
    assert sv.pings == [] and sv._exec_stale
    assert any(kind == "error" and "feed executor stalled" in text for kind, text in sv.log.lines)
    sv._t_feed = 102.6
    watch(102.7)
    assert sv.pings == [1] and not sv._exec_stale


def _supervisor_tree():
    import ast  # noqa: PLC0415

    import amr_bringup.supervisor_node as node  # noqa: PLC0415

    with open(node.__file__, encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _subscriptions(fn):
    """(topic, qos source, callback attribute) of every create_subscription call in fn."""
    import ast  # noqa: PLC0415

    out = []
    for c in ast.walk(fn):
        if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "create_subscription":
            out.append((c.args[1].value, ast.unparse(c.args[3]), ast.unparse(c.args[2]).split(".")[-1]))
    return out


def test_the_four_high_rate_inputs_moved_to_the_feed_node_unchanged():
    """Same topics, QoS and Snapshots callbacks (so the same receipt stamps) as before WP-C4;
    none of them left on the main node; the feed node beats; main() spins it on its own
    SingleThreadedExecutor."""
    import ast  # noqa: PLC0415

    tree = _supervisor_tree()
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    feed = next(f for f in classes["SupervisorFeed"].body if getattr(f, "name", "") == "__init__")
    main = next(f for f in classes["Supervisor"].body if getattr(f, "name", "") == "__init__")
    assert sorted(_subscriptions(feed)) == sorted([
        ("/amr/mux_state", "RELIABLE_1", "on_mux"),
        ("/drives/status", "RELIABLE_1", "on_drives"),
        ("/wheel_states", "SENSOR", "on_wheels"),
        ("/amr/panel_state", "10", "on_panel"),
    ])
    moved = {"/amr/mux_state", "/drives/status", "/wheel_states", "/amr/panel_state"}
    assert not moved & {t for t, _, _ in _subscriptions(main)}
    assert "create_steady_timer" in ast.unparse(feed)
    run = next(f for f in tree.body if getattr(f, "name", "") == "main")
    src = ast.unparse(run)
    assert "SingleThreadedExecutor()" in src and "feed_executor.add_node(node.feed)" in src

