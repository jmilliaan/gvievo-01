"""Logs and journals on disk: numbered rotation, atomic JSON, tolerant JSONL, pruning.

Each primitive raises OSError to its caller; the callers decide whether a failure is
silent (uptime, logs.rotate, the PIN file) or reported (the event log's error count).
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterator


def rotate_numbered(path: str, keep: int) -> None:
    """path -> path.1 -> ... -> path.<keep>; the oldest falls off. Nothing when path is absent."""
    if not os.path.exists(path):
        return
    for n in range(keep - 1, 0, -1):
        src, dst = f"{path}.{n}", f"{path}.{n + 1}"
        if os.path.exists(src):
            os.replace(src, dst)
    os.replace(path, f"{path}.1")


def atomic_write_json(path: str, doc, mode: int = 0o644, indent: int | None = None,
                      mkstemp: bool = False) -> None:
    """tmp + fsync + replace: a power cut leaves the old file or the new one, never half of
    one. `mkstemp`: a unique temp name (concurrent writers) instead of `<path>.tmp`."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    if mkstemp:
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    else:
        tmp = f"{path}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=indent)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def iter_jsonl(path: str) -> Iterator:
    """Every JSON value in a JSON-lines file, in order. Blank lines and lines that do not
    parse (a power cut mid-append) are skipped, never raised. OSError reaches the caller."""
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except ValueError:
                continue


def keep_newest(directory: str, keep: int, match: Callable[[str], bool]) -> list[str]:
    """Delete all but the `keep` last (by sorted name) matching files; returns those removed.
    A file that cannot be removed is left; listing the directory raises OSError."""
    names = sorted(n for n in os.listdir(directory) if match(n))
    removed = []
    for name in names[:-keep] if keep > 0 else []:
        try:
            os.remove(os.path.join(directory, name))
            removed.append(name)
        except OSError:
            pass
    return removed
