"""Which node ended a launch group (unified plan WP-H4, H-P1-5). No ROS.

A required node that exits shuts its whole `ros2 launch` down (launch_helpers.required),
and the supervisor only sees the launch leader go: "base pgid=812 leader=0 exited".
That names no node. So required()'s exit handler records the FIRST node of the group
that exited, with its exit code, in $AMR_STATE_DIR/exits/<role>.json, and the supervisor
reads it when it reaps the group: "BASE_EXITED: drive_node exited with code -6 (SIGABRT)".

    record(state_dir, role, node, code)   first exit wins: the others are the cascade
    read(state_dir, role)                 {"node", "code", "at"} or None
    clear(state_dir, role)                before every spawn of that role
    describe(body)                        the words for the fault reason

The role comes from the supervisor (env AMR_GROUP_ROLE, set by _spawn). A launch started
by hand has none and records nothing. Every call is silent: a failed write must never
change how a launch ends.
"""

from __future__ import annotations

import json
import os
import signal
import time

EXITS = "exits"
ROLE_ENV = "AMR_GROUP_ROLE"


def path(state_dir: str, role: str) -> str:
    return os.path.join(os.path.expanduser(state_dir), EXITS, f"{role}.json")


def clear(state_dir: str, role: str) -> None:
    try:
        os.unlink(path(state_dir, role))
    except OSError:
        pass


def record(state_dir: str, role: str, node: str, code) -> bool:
    """Write exits/<role>.json unless one is there already. True if this call wrote it.
    tmp + fsync + link: the file appears whole or not at all, and link() refuses to
    replace an existing one, so of a cascade of exits only the first is kept."""
    if not role:
        return False
    final = path(state_dir, role)
    tmp = f"{final}.{os.getpid()}.tmp"
    body = {"node": str(node), "code": code if isinstance(code, int) else None, "at": time.time()}
    try:
        os.makedirs(os.path.dirname(final), exist_ok=True)
        if os.path.exists(final):
            return False
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(body, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(tmp, final)
        return True
    except OSError:
        return False
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def read(state_dir: str, role: str) -> dict | None:
    try:
        with open(path(state_dir, role), encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) and body.get("node") else None


def describe(body: dict | None) -> str:
    """'drive_node exited with code -6 (SIGABRT)', or '' without a record."""
    if not body:
        return ""
    code = body.get("code")
    if not isinstance(code, int):
        return f"{body['node']} exited"
    how = f"code {code}"
    if code < 0:
        try:
            how += f" ({signal.Signals(-code).name})"
        except ValueError:
            pass
    return f"{body['node']} exited with {how}"
