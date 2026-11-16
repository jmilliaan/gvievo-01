"""How much room is left to write in (power-loss plan W3).

A full disk is a lost-write problem like a power cut: a map save that runs out of
space mid-bundle is the ugliest failure in the stack. The supervisor refuses new
surveys and saves below the stop threshold, and the operator surface raises the
alarm a gigabyte earlier - but a vehicle that is ALREADY running is never gated
on it, because stopping a moving machine over free space would be the worse
failure.

Lives in agv_core because the supervisor and the web both need the same answer
and neither should import the other's internals.

2026-11-16 (unified plan WP-P4, H-P2-7): `/` is watched too (logs, ROS logs and the
system itself live there), and a filesystem mounted read-only - ext4 remounts itself
read-only after an I/O error - is reported by path in `readonly`. A read-only disk
refuses new work like a full one: nothing could be saved.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

WARN_MB = 1000
STOP_MB = 200
OK, WARN, STOP = "ok", "warn", "stop"
UNKNOWN = "unknown"  # no watched filesystem could be read (audit R19): not healthy, not a refusal


@dataclass(frozen=True)
class DiskStatus:
    free_mb: int
    level: str  # ok | warn | stop | unknown
    path: str  # the fullest of the watched filesystems
    readonly: str = ""  # watched paths on a read-only mount, ", "-joined; "" when all writable

    @property
    def blocks_new_work(self) -> bool:
        return self.level == STOP or bool(self.readonly)


ROOT = "/"


def watched(state_dir: str, maps_dir: str) -> list[str]:
    """The filesystems the supervisor watches: state, maps and the root."""
    return [state_dir, maps_dir, ROOT]


def is_readonly(path: str, statvfs=None) -> bool:
    """True when `path` is on a read-only mount (statvfs f_flag ST_RDONLY). False when it
    cannot be told (no statvfs on this OS, an unreadable path): never a false alarm."""
    statvfs = statvfs or getattr(os, "statvfs", None)
    if statvfs is None:
        return False
    try:
        flags = statvfs(os.path.expanduser(path)).f_flag
    except OSError:
        return False
    return bool(flags & getattr(os, "ST_RDONLY", 1))


def status(paths, warn_mb: int = WARN_MB, stop_mb: int = STOP_MB, statvfs=None) -> DiskStatus:
    """The worst of the given filesystems. Unreadable paths are skipped; if none can be
    read the answer is UNKNOWN - reported, never a refusal, because refusing to work over
    a failed statvfs would be a worse failure than the one it guards against."""
    worst: DiskStatus | None = None
    readonly = []
    for path in paths:
        if not path:
            continue
        try:
            free_mb = int(shutil.disk_usage(os.path.expanduser(path)).free / (1024 * 1024))
        except OSError:
            continue
        if is_readonly(path, statvfs) and path not in readonly:
            readonly.append(path)
        level = STOP if free_mb <= stop_mb else WARN if free_mb <= warn_mb else OK
        if worst is None or free_mb < worst.free_mb:
            worst = DiskStatus(free_mb, level, path)
    if worst is None:
        return DiskStatus(-1, UNKNOWN, "")
    return DiskStatus(worst.free_mb, worst.level, worst.path, ", ".join(readonly))
