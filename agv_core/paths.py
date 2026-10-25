"""Where the vehicle keeps its state and its maps. One answer for every process.

amr.service sets AMR_STATE_DIR / AMR_MAPS_DIR (amr_ws/deploy/amr.env); a shell, a bench
tool or a test without them gets the defaults below. Every node, launch file, web view,
report and tool asks here, so they cannot disagree about the volume they write to (if one
did, LINE would refuse to start, navigation would see no map and the disk alarm would
watch the wrong volume). An empty variable counts as unset.
"""

from __future__ import annotations

import os

STATE_ENV = "AMR_STATE_DIR"
MAPS_ENV = "AMR_MAPS_DIR"
STATE_DEFAULT = "~/.amr"
MAPS_DEFAULT = "~/amr_maps"


def _resolve(env: str, default: str) -> str:
    return os.path.expanduser(os.environ.get(env) or default)


def state_dir() -> str:
    return _resolve(STATE_ENV, STATE_DEFAULT)


def maps_dir() -> str:
    return _resolve(MAPS_ENV, MAPS_DEFAULT)


def state_path(*parts: str) -> str:
    return os.path.join(state_dir(), *parts)


def logs_dir() -> str:
    return state_path("logs")


def mls_cal_dir() -> str:
    return state_path("mls_cal")


def env_for(state: str, maps: str) -> dict[str, str]:
    """The variables a child process needs to resolve the same directories as its parent."""
    return {STATE_ENV: os.path.expanduser(state), MAPS_ENV: os.path.expanduser(maps)}
