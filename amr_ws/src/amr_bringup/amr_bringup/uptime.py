"""Did the vehicle stop, or was it cut off? (power-loss plan W1)

A clean stop removes a marker file; a power cut cannot. So on every start the
supervisor reads the marker left by the previous run and can say, in one
sentence, what happened - "Power was lost at 14:32 while NAVIGATION, mission m3"
rather than leaving the operator to guess why the drives will not arm.

Telling a POWER CUT from a SERVICE CRASH is the whole point, because the actions
differ: after a cut the drives have latched 8130h and need a power cycle, while a
crash that systemd restarted usually needs nothing but a look at the log. The
test is the kernel's boot id (2026-11-16, S-`uptime-boot-id-and-service-result`):
a marker written under another boot id belongs to a previous boot, so the machine
went down; the same boot id means only the process died. A marker without a boot
id (written before this change) falls back to the boot time: a marker written
BEFORE this boot began belongs to a previous boot. The boot id cannot be fooled
by an RTC error or an NTP step; the boot time can.

amr.service's ExecStopPost (deploy/amr-stop-post.sh) runs `python3 -m
amr_bringup.uptime stop-post` after every stop, clean or not, and keeps systemd's
$SERVICE_RESULT in last_stop.json. A crash verdict then says how it died
(watchdog, signal, core dump, out of memory). A power cut runs no ExecStopPost,
so its last_stop.json is an older one and is ignored.

The marker is rewritten on every mode change, so it also carries WHAT was
interrupted. Writes are atomic (tmp + fsync + replace) and never raise: a
read-only or full state dir must not stop the vehicle starting.

groups.json (unified plan WP-H5) lists the supervisor's child process groups by
role, so amr-orphan-stop.sh can stop them base first when the supervisor itself
died. Written by note_group(), removed by a clean stop.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass

from agv_core import fsutil

MARKER = "running.json"
LAST_STOP = "last_stop.json"
GROUPS = "groups.json"
BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"
POWER_LOSS, SERVICE_CRASH = "power_loss", "service_crash"

# systemd's $SERVICE_RESULT (man systemd.exec) in the operator's words. "success" and
# anything unknown add nothing: the sentence then says only that it stopped.
RESULT_TEXT = {
    "watchdog": "the supervisor stopped answering the watchdog",
    "signal": "a process was killed by a signal",
    "core-dump": "a process crashed",
    "exit-code": "the supervisor exited with an error",
    "oom-kill": "the PC ran out of memory",
    "timeout": "it did not start or stop in time",
    "protocol": "it broke the systemd start protocol",
    "resources": "systemd could not set it up",
}


@dataclass(frozen=True)
class Verdict:
    kind: str  # POWER_LOSS | SERVICE_CRASH
    at: float  # wall clock of the last marker write
    mode: str
    operation_id: str
    run_id: str
    instance: str
    cause: str = ""  # RESULT_TEXT of the stop that ended the run; crash only

    @property
    def clock(self) -> str:
        return time.strftime("%H:%M", time.localtime(self.at))

    def sentence(self) -> str:
        """What the operator is told. Names the interrupted work, then the consequence."""
        doing = f" while {self.mode}" if self.mode else ""
        if self.run_id:
            doing += f", mission {self.run_id}"
        elif self.operation_id:
            doing += f", operation {self.operation_id}"
        if self.kind == POWER_LOSS:
            # A kernel panic or the hardware watchdog (WP-P5) also reboots the PC, and
            # looks the same from here: the drives lost the heartbeat either way.
            return (
                f"Power was lost, or the PC restarted, at {self.clock}{doing}. The drives lost the PC "
                "heartbeat and latched; they need to be switched off and on."
            )
        why = f" ({self.cause})" if self.cause else ""
        # A drive_node that died without its teardown leaves the drives' heartbeat
        # consumer (1016h) to time out, which latches 8130h: possible, not certain.
        return (
            f"The service stopped unexpectedly at {self.clock}{doing}{why} and restarted itself. "
            "If the drives do not arm, switch them off and on."
        )


def path(state_dir: str) -> str:
    return os.path.join(os.path.expanduser(state_dir), MARKER)


def _in(state_dir: str, name: str) -> str:
    return os.path.join(os.path.expanduser(state_dir), name)


def boot_time() -> float | None:
    """Wall clock when this boot began, from /proc/stat btime. None if unreadable."""
    try:
        with open("/proc/stat", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("btime "):
                    return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def boot_id(source: str = BOOT_ID_PATH) -> str | None:
    """The kernel's id for this boot (a new random UUID at every boot). None if unreadable."""
    try:
        with open(source, encoding="utf-8") as fh:
            value = fh.read().strip()
    except OSError:
        return None
    return value or None


def classify(marker: dict, this_boot_id: str | None, boot_wall: float | None,
             stop: dict | None = None) -> tuple[str, str]:
    """(kind, cause) for a marker that survived. Pure: every input is passed in.

    kind: the boot id decides when both are known (different -> POWER_LOSS, same ->
    SERVICE_CRASH); otherwise the boot time, and without a boot time the heavier
    action (POWER_LOSS). cause: for a crash only, from the ExecStopPost record `stop`
    when it belongs to this run - same boot as the marker, written after it."""
    written = float(marker["written_at"])
    marker_boot = marker.get("boot_id") or None
    if marker_boot and this_boot_id:
        kind = SERVICE_CRASH if marker_boot == this_boot_id else POWER_LOSS
    else:
        kind = POWER_LOSS if boot_wall is None or written < boot_wall else SERVICE_CRASH
    cause = ""
    if kind == SERVICE_CRASH and isinstance(stop, dict):
        stop_boot = stop.get("boot_id") or None
        same_boot = stop_boot is not None and stop_boot == (marker_boot or this_boot_id)
        try:
            after = float(stop.get("at", 0)) >= written
        except (TypeError, ValueError):
            after = False
        if same_boot and after:
            cause = RESULT_TEXT.get(str(stop.get("service_result", "")), "")
            status = str(stop.get("exit_status", ""))
            if cause and stop.get("service_result") == "signal" and status:
                cause += f" ({status})"
    return kind, cause


def write(state_dir: str, instance: str, mode_name: str, operation_id: str = "", run_id: str = "") -> None:
    """Record what is running now. Atomic and silent: never raises into the loop."""
    body = {
        "written_at": time.time(),
        "boot_id": boot_id(),
        "instance": instance,
        "mode": mode_name,
        "operation_id": operation_id,
        "run_id": run_id,
        "pid": os.getpid(),
    }
    try:
        fsutil.atomic_write_json(path(state_dir), body)
    except OSError:
        pass


def note_group(state_dir: str, role: str, pgid: int) -> None:
    """Record a child group's process-group id under its role, for amr-orphan-stop.sh.
    Read-modify-write of one small file, atomic, silent. A stale entry is harmless:
    the stop script only signals process groups that are still in the service's cgroup."""
    p = _in(state_dir, GROUPS)
    try:
        with open(p, encoding="utf-8") as fh:
            groups = dict(json.load(fh).get("groups", {}))
    except (OSError, ValueError, AttributeError, TypeError):
        groups = {}
    groups[str(role)] = int(pgid)
    try:
        fsutil.atomic_write_json(p, {"written_at": time.time(), "pid": os.getpid(), "groups": groups})
    except OSError:
        pass


def clear(state_dir: str) -> None:
    """A clean stop. Anything else leaves the marker, which is what makes it evidence."""
    for name in (GROUPS, MARKER):  # the marker last
        try:
            os.unlink(_in(state_dir, name))
        except OSError:
            pass


def stop_post(state_dir: str, env: dict) -> dict:
    """ExecStopPost: keep systemd's verdict on the stop that just happened. Silent."""
    body = {
        "at": time.time(),
        "boot_id": boot_id(),
        "service_result": env.get("SERVICE_RESULT", ""),
        "exit_code": env.get("EXIT_CODE", ""),
        "exit_status": env.get("EXIT_STATUS", ""),
    }
    try:
        fsutil.atomic_write_json(_in(state_dir, LAST_STOP), body)
    except OSError:
        pass
    return body


def _read_json(p: str) -> dict | None:
    try:
        with open(p, encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def verdict(state_dir: str, now_wall: float | None = None, boot_wall: float | None = None,
            this_boot_id: str | None = None) -> Verdict | None:
    """Read (and keep) the previous run's marker. None when the last stop was clean,
    the marker is missing, or it is unreadable - an unparseable marker is no evidence,
    and inventing a power cut from it would be worse than silence.

    With neither boot_wall nor this_boot_id given, both are this machine's. A caller
    that injects either one gets exactly what it injected (a test passing only
    boot_wall tests the boot-time fallback)."""
    body = _read_json(path(state_dir))
    if body is None:
        return None
    try:
        written = float(body["written_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if boot_wall is None and this_boot_id is None:
        bid, boot_wall = boot_id(), boot_time()
    else:
        bid = this_boot_id or None
    now = time.time() if now_wall is None else now_wall
    kind, cause = classify(body, bid, boot_wall, _read_json(_in(state_dir, LAST_STOP)))
    return Verdict(
        kind=kind,
        at=min(written, now),
        mode=str(body.get("mode", "")),
        operation_id=str(body.get("operation_id", "")),
        run_id=str(body.get("run_id", "")),
        instance=str(body.get("instance", "")),
        cause=cause,
    )


def main(argv: list[str]) -> int:
    """`python3 -m amr_bringup.uptime stop-post` from amr.service's ExecStopPost. Always 0."""
    if argv[:1] == ["stop-post"]:
        state_dir = os.environ.get("AMR_STATE_DIR") or "~/.amr"
        body = stop_post(state_dir, dict(os.environ))
        print(f"amr stop: result={body['service_result'] or '?'} code={body['exit_code'] or '-'} "
              f"status={body['exit_status'] or '-'}", flush=True)
        return 0
    print("usage: python3 -m amr_bringup.uptime stop-post", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
