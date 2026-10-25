"""Cooperative device-owner locks (unified plan §9.2).

Nothing in the OS stops two processes owning can0 (socketcan admits any
number of openers), the DIO island (Modbus TCP accepts a second client) or the
RFID reader (it serves a second TCP client and pushes tags to both).
The owners agree instead: whoever will talk to a device takes its lock FIRST,
before opening a socket or arming anything, and holds it for its whole life.

    with_lock = ownerlock.acquire("can")     # raises OwnerBusy if held
    ...                                       # lock lives as long as the object

Advisory `flock` on a file under /run/lock/amr (world-writable, sticky - no
provisioning needed on Ubuntu 22.04). The descriptor is close-on-exec, so a
child spawned by an owner does not inherit and silently keep the lock. Locks
release with the descriptor - on any exit, including SIGKILL - so nothing
ever needs to "clean up" a stale lock file, and nobody may unlink one.

Free of config, ROS and threads: the ROS owners (drive_node, panel_node,
rfid_node) and the bench tools import it alike.
"""

from __future__ import annotations

import fcntl
import os

DEFAULT_DIR = "/run/lock/amr"
RESOURCES = ("can", "dio", "rfid")


class OwnerBusy(RuntimeError):
    pass


class OwnerLock:
    def __init__(self, resource: str, fd: int, path: str) -> None:
        self.resource, self._fd, self.path = resource, fd, path

    def release(self) -> None:
        if self._fd >= 0:
            try:
                os.close(self._fd)  # closing drops the flock
            finally:
                self._fd = -1

    def __enter__(self) -> OwnerLock:
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    def __del__(self) -> None:
        self.release()


def lock_dir() -> str:
    d = os.environ.get("AMR_LOCK_DIR") or DEFAULT_DIR
    os.makedirs(d, mode=0o755, exist_ok=True)
    return d


def acquire(resource: str, who: str = "") -> OwnerLock:
    """Take `resource` or raise OwnerBusy naming the holder. Never blocks."""
    if resource not in RESOURCES:
        raise ValueError(f"unknown resource {resource!r}; one of {RESOURCES}")
    path = os.path.join(lock_dir(), f"{resource}.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = ""
        try:
            holder = os.read(fd, 256).decode(errors="replace").strip()
        except OSError:
            pass
        os.close(fd)
        raise OwnerBusy(f"{resource} is owned by {holder or 'another process'}") from None
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{who or 'pid'} {os.getpid()}".encode())
    except OSError:
        pass
    return OwnerLock(resource, fd, path)
