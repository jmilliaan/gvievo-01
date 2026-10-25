"""Durable writes for the revision stores (map bundles, routes/missions, tape graphs).

One writer lock, one fsync, one hash and one publish-by-rename, so the three stores
cannot drift apart in how they make a revision durable. Each store keeps its own error
class, naming rule, layout and manifest checks; this module knows none of them.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os

LOCK_NAME = ".lock"


@contextlib.contextmanager
def writer_lock(d: str, sweep_prefix: str | None = None, lock_name: str = LOCK_NAME):
    """Exclusive writer lock on directory `d` (created if missing). flock binds to the open
    file description, so two threads of one process exclude each other as two processes do.
    `sweep_prefix`: temp files only ever created under this lock; any left were abandoned."""
    os.makedirs(d, exist_ok=True)
    fd = os.open(os.path.join(d, lock_name), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if sweep_prefix:
            for name in os.listdir(d):
                if name.startswith(sweep_prefix):
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(os.path.join(d, name))
        yield
    finally:
        os.close(fd)  # releases the lock


def fsync_path(path: str, directory: bool = False) -> None:
    fd = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if directory else 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def positive_revision(revision, error: type[Exception] = ValueError) -> int:
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise error(f"revision must be a positive integer: {revision!r}")
    return revision


def publish_dir(stage: str, dest: str, wrap=None) -> None:
    """Make a staged directory durable and rename it to `dest`, which must not exist (call
    under the writer lock; callers check first with their own message). Every file and the
    stage are fsynced before the rename and the parent after it: a rename alone can be lost
    on power loss. `wrap(OSError) -> Exception` re-raises a failed rename as the store's own."""
    if os.path.lexists(dest):
        raise FileExistsError(f"already exists: {dest}")
    for name in os.listdir(stage):
        fsync_path(os.path.join(stage, name))
    fsync_path(stage, directory=True)
    try:
        os.rename(stage, dest)
    except OSError as e:
        if wrap is None:
            raise
        raise wrap(e) from e
    fsync_path(os.path.dirname(dest), directory=True)
