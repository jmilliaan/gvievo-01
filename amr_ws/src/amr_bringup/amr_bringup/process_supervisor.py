"""Child process groups for the supervisor (unified plan §3.3). No ROS.

    g = Group.spawn("mapping", ["ros2", "launch", "amr_bringup", "mapping_layer.launch.py", ...])
    g.poll()          -> exit code or None; a launch that ended is a group that ended
    g.alive_pids()    -> every process still in the group's session (leader or not)
    g.stop(...)       -> SIGINT the leader, wait; SIGTERM the group, wait; SIGKILL the
                         group; True only when the group is verifiably EMPTY

Rules:
  * Only an allow-listed executable is spawned, argv as a list, shell=False.
  * Each group is its own session (setsid), so it has a unique process-group
    id and we can signal every member without knowing their PIDs.
  * "Stopped" means no process with our pgid exists any more, checked through
    /proc - a leader that exited while a grandchild lives is NOT stopped.
  * Nothing is killed by name.
  * The web and the mode layer go first when the PC runs out of memory (oom_score_adj
    +300, WP-H5); the base and the supervisor keep amr.service's OOMScoreAdjust=-500.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field

from amr_bringup import logs

ALLOWED_EXECUTABLES = ("ros2",)
# Direct module entry points: `ros2 run` does not forward SIGINT to its child,
# so nodes we must stop cleanly are started as `python3 -m <module>` instead.
ALLOWED_MODULES = ("amr_web.web_node",)

# OOM killer preference per role (unified plan WP-H5). A role not listed inherits the
# supervisor's -500 (amr.service OOMScoreAdjust): the base owns the drives and must outlive
# both of these. Raising it needs no privilege; lowering it would.
OOM_SCORE_ADJ = {"web": 300, "layer": 300}
OOM_ADJ_PATH = "/proc/self/oom_score_adj"

# The bounded teardown (unified plan WP-P4, H-P2-7). Group.stop() budgets per role, as
# (SIGINT wait, SIGTERM wait, SIGKILL wait) seconds. Layer, then base: in turn, because the
# base must outlive the layer that commands it. Every other group (the web) in parallel
# after the base, on the short budget: it holds nothing the vehicle needs.
STOP_BUDGET_S = {"layer": (6.0, 4.0, 2.0), "base": (6.0, 4.0, 2.0)}
OPTIONAL_STOP_BUDGET_S = (2.0, 1.0, 1.0)
LOCK_WAIT_S = 2.0  # shutdown() waits this long for the state lock
EXECUTOR_STOP_S = 2.0  # main(): executor.shutdown, then the loop join, each
LOOP_JOIN_S = 2.0
# A web that ran this long before it died is not a crash loop: its tries start again.
RESPAWN_RESET_S = 120.0


def stop_budget_s() -> float:
    """The worst case of the whole supervisor teardown, in seconds. amr.service's
    TimeoutStopSec must exceed it by 10 s (test_liveness pins it)."""
    serial = sum(sum(b) for b in STOP_BUDGET_S.values())
    return LOCK_WAIT_S + serial + sum(OPTIONAL_STOP_BUDGET_S) + EXECUTOR_STOP_S + LOOP_JOIN_S


def respawn_tries(previous: int, ran_s: float, reset_after_s: float = RESPAWN_RESET_S) -> int:
    """The give-up counter after a respawnable group died having run `ran_s` seconds:
    a long life clears it, so only quick deaths in a row add up to giving up."""
    return 0 if ran_s >= reset_after_s else previous


def oom_preexec(role: str, path: str = OOM_ADJ_PATH):
    """A preexec_fn that sets the child's oom_score_adj for `role`, or None for a protected
    role. Runs between fork and exec: os-level calls only, and silent on any error."""
    value = OOM_SCORE_ADJ.get(role)
    if value is None:
        return None
    data = str(int(value)).encode()

    def set_adj() -> None:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_TRUNC)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
        except OSError:
            pass

    return set_adj


def _pgid_of(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            stat = f.read().decode(errors="replace")
        # field 5 after the last ')' is pgrp
        fields = stat[stat.rindex(")") + 2 :].split()
        return int(fields[2])
    except (OSError, ValueError, IndexError):
        return None


def pids_in_group(pgid: int) -> list[int]:
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        if _pgid_of(int(entry)) == pgid:
            out.append(int(entry))
    return out


@dataclass
class Group:
    role: str
    argv: list[str]
    proc: subprocess.Popen
    pgid: int
    started: float = field(default_factory=time.monotonic)
    requested_stop: bool = False
    exit_code: int | None = None

    @classmethod
    def spawn(cls, role: str, argv: list[str], env: dict | None = None, log_path: str | None = None) -> Group:
        exe = os.path.basename(argv[0]) if argv else ""
        module_entry = len(argv) >= 3 and argv[1] == "-m" and argv[2] in ALLOWED_MODULES
        python = exe.startswith("python3") or argv[:1] == [sys.executable]
        if not argv or not (exe in ALLOWED_EXECUTABLES or (python and module_entry)):
            raise ValueError(f"refusing to spawn {argv[:3]!r}: not an allow-listed executable")
        for a in argv:
            if not isinstance(a, str) or "\0" in a:
                raise ValueError("argv must be plain strings")
        if log_path:
            # Every spawn begins a fresh file (power-loss plan W2): a report then carries
            # the previous run's log, and no single file grows for the life of the install.
            logs.rotate(log_path)
        out = open(log_path, "ab", buffering=0) if log_path else subprocess.DEVNULL
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,  # own session -> own pgid, signal the whole tree
            close_fds=True,
            preexec_fn=oom_preexec(role),  # inherited by the whole group
        )
        if log_path:
            out.close()
        return cls(role=role, argv=list(argv), proc=proc, pgid=proc.pid)

    # -- observation --

    def poll(self) -> int | None:
        if self.exit_code is None:
            code = self.proc.poll()
            if code is not None:
                self.exit_code = code
        return self.exit_code

    def alive_pids(self) -> list[int]:
        return pids_in_group(self.pgid)

    @property
    def leader_alive(self) -> bool:
        return self.poll() is None

    @property
    def empty(self) -> bool:
        self.poll()
        return not self.alive_pids()

    # -- control --

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(self.pgid, sig)
        except ProcessLookupError:
            pass

    def _wait_empty(self, deadline: float) -> bool:
        while time.monotonic() < deadline:
            if self.empty:
                return True
            time.sleep(0.05)
        return self.empty

    def stop(self, int_wait_s: float = 6.0, term_wait_s: float = 4.0, kill_wait_s: float = 2.0) -> bool:
        """Bounded escalation. Returns True iff the group is empty afterwards."""
        self.requested_stop = True
        if self.empty:
            return True
        # 1. SIGINT to the launch leader: `ros2 launch` forwards orderly shutdown
        if self.leader_alive:
            try:
                self.proc.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
        if self._wait_empty(time.monotonic() + int_wait_s):
            return True
        # 2. the leader is gone or ignoring us: TERM every member
        self._signal_group(signal.SIGTERM)
        if self._wait_empty(time.monotonic() + term_wait_s):
            return True
        # 3. last resort
        self._signal_group(signal.SIGKILL)
        return self._wait_empty(time.monotonic() + kill_wait_s)

    def describe(self) -> str:
        code = self.poll()
        leader = "alive" if code is None else str(code)
        return f"{self.role} pgid={self.pgid} leader={leader} members={len(self.alive_pids())}"
