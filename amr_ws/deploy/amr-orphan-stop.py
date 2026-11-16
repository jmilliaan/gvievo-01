#!/usr/bin/env python3
"""Stop what the supervisor left behind when it died (unified plan WP-H5, H-P1-4).

Run by amr-orphan-stop.sh from amr.service's ExecStop, as the service user, only
when the main process (the supervisor) is already gone. Its children are separate
process groups (process_supervisor.Group: one session each), so a supervisor that
crashed, was OOM-killed or SIGKILLed leaves them running. systemd would SIGKILL
them all at once after this, and a SIGKILLed drive_node never disarms: both drives
time out their PC heartbeat (1016h) and latch 8130h.

So, before that: SIGINT each group in turn, base first (drive_node's own teardown
disarms the drives), then the rest, and wait at most BUDGET_S in total. Whatever is
still alive afterwards is systemd's (KillMode=mixed sends the final SIGKILL to the
whole cgroup).

Which group is which comes from $AMR_STATE_DIR/groups.json (uptime.note_group, the
supervisor writes it). Without it, the group leaders' command lines decide
(base.launch.py is base). Only process groups that are in THIS unit's cgroup are
ever signalled, so a stale groups.json or a reused pid cannot reach anything else.
Standard library only; no ROS.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time

GROUPS = "groups.json"  # == amr_bringup.uptime.GROUPS (test_unclean_death pins it)
ORDER = ("base", "layer", "web")  # base first: it owns the drives
BUDGET_S = 12.0
BASE_SHARE_S = 8.0  # of the budget, for the base alone


def own_cgroup_procs(proc_self_cgroup: str = "/proc/self/cgroup", root: str = "/sys/fs/cgroup") -> str | None:
    """cgroup.procs of the cgroup this process runs in (cgroup v2: the '0::' line)."""
    try:
        with open(proc_self_cgroup, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("0::"):
                    return os.path.join(root, line[3:].strip().lstrip("/"), "cgroup.procs")
    except OSError:
        return None
    return None


def read_pids(procs_path: str | None) -> list[int]:
    if not procs_path:
        return []
    try:
        with open(procs_path, encoding="utf-8") as fh:
            return [int(x) for x in fh.read().split() if x.isdigit()]
    except OSError:
        return []


def pgid_of(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def cmdline_of(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def read_groups(path: str) -> dict[str, int]:
    """role -> pgid from groups.json; {} when missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            body = json.load(fh)
        return {str(k): int(v) for k, v in dict(body.get("groups", {})).items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def role_from_cmdline(cmd: str) -> str:
    if "base.launch.py" in cmd:
        return "base"
    if "amr_web.web_node" in cmd:
        return "web"
    return "layer" if "launch" in cmd else "other"


def plan(pids: list[int], pgid_of, groups: dict[str, int], cmdline_of,
         own_pgid: int) -> list[tuple[str, int]]:
    """[(role, pgid)] to stop, in order. Pure: everything is passed in.

    Only process groups with a member in `pids` (this unit's cgroup) count; our own
    group is never one of them."""
    live = []
    for pid in pids:
        g = pgid_of(pid)
        if g is not None and g != own_pgid and g not in live:
            live.append(g)
    roles = {}
    for role, g in groups.items():
        if g in live:
            roles[g] = role
    for g in live:
        roles.setdefault(g, role_from_cmdline(cmdline_of(g)))
    rank = {r: i for i, r in enumerate(ORDER)}
    return sorted(((roles[g], g) for g in live),
                  key=lambda rg: (rank.get(rg[0], len(ORDER)), live.index(rg[1])))


def interrupt(pgid: int, pids: list[int], kill=None, killpg=None) -> None:
    """SIGINT the launch leader when it is alive (ros2 launch shuts its nodes down in
    order), else every member of the group."""
    kill = kill or os.kill
    killpg = killpg or os.killpg
    try:
        if pgid in pids:
            kill(pgid, signal.SIGINT)
        else:
            killpg(pgid, signal.SIGINT)
    except OSError:
        pass


def run(state_dir: str, procs_path: str | None, *, pgid_of=pgid_of, cmdline_of=cmdline_of,
        kill=None, killpg=None, now=time.monotonic, sleep=time.sleep,
        own_pgid: int | None = None, log=print) -> list[tuple[str, int, bool]]:
    """Stop the orphaned groups. Returns [(role, pgid, empty_afterwards)]."""
    own = os.getpgid(0) if own_pgid is None else own_pgid
    pids = read_pids(procs_path)
    todo = plan(pids, pgid_of, read_groups(os.path.join(state_dir, GROUPS)), cmdline_of, own)
    if not todo:
        log("amr-orphan-stop: nothing left in the cgroup")
        return []
    deadline = now() + BUDGET_S

    def members(g):
        return [p for p in read_pids(procs_path) if pgid_of(p) == g]

    def wait_empty(gs, until):
        while now() < until:
            if not any(members(g) for g in gs):
                return
            sleep(0.1)

    out = []
    base = [g for r, g in todo if r == "base"]
    rest = [g for r, g in todo if r != "base"]
    for g in base:
        log(f"amr-orphan-stop: SIGINT base (pgid {g})")
        interrupt(g, pids, kill, killpg)
    if base:
        wait_empty(base, min(deadline, now() + BASE_SHARE_S))
    for r, g in todo:
        if r != "base":
            log(f"amr-orphan-stop: SIGINT {r} (pgid {g})")
            interrupt(g, pids, kill, killpg)
    if rest:
        wait_empty(rest, deadline)
    for r, g in todo:
        empty = not members(g)
        out.append((r, g, empty))
        log(f"amr-orphan-stop: {r} pgid {g} {'stopped' if empty else 'STILL RUNNING (systemd kills it)'}")
    return out


def main() -> int:
    state_dir = os.path.expanduser(os.environ.get("AMR_STATE_DIR") or "~/.amr")
    run(state_dir, own_cgroup_procs())
    return 0  # never fail the stop: systemd's SIGKILL is the backstop


if __name__ == "__main__":
    sys.exit(main())
