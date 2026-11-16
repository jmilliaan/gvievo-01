"""Black box (unified plan WP-P6, S-rosbag2-snapshot-mcap): what to record, when to dump, what to keep.

An always-armed `ros2 bag record --snapshot-mode` keeps the last CACHE_MB (blackbox_cache_mb:=) of the
low-rate control topics in RAM (serialized, never deserialized) and writes nothing until
its `~/snapshot` service is called. blackbox_node calls it on a FAULT or stop edge, a few
seconds after the edge so the aftermath is in the file too. The web report zip carries the
newest files (amr_web/reports.py).

Pure: no rclpy. The recorder argv, the trigger policy and the prune plan are tested here
(test_blackbox.py); the node and the launch entry are thin.

Never a required() role: a dead recorder or trigger respawns and never faults the vehicle.
Default OFF (AMR_BLACKBOX, base.launch.py blackbox:=) until the owner's pidstat check on the
N97 (plan §6 OP-1). Read-only: no CAN, scanner or motion interaction.
"""

from __future__ import annotations

import os

NODE_NAME = "amr_blackbox"  # --node-name: run_log.sh's recorder keeps /rosbag2_recorder
SNAPSHOT_SERVICE = f"/{NODE_NAME}/snapshot"  # rosbag2_interfaces/srv/Snapshot
DIRNAME = "blackbox"  # under the state dir
ENV = "AMR_BLACKBOX"  # "true" turns it on (base.launch.py blackbox:= default)
CACHE_MB = 16  # per cache; RAM is about twice this (double buffer)

# amr_base.health_pub.TOPIC (WP-H1), EVENT_STREAM QoS. Spelt out here so this module stays
# rclpy-free; test_blackbox holds the two equal.
DEVICE_HEALTH_TOPIC = "/amr/device_health"

# Low-rate topics only. No /scan, /map, /amr/line_track (100 Hz) or /cmd_wheel_vel: the _ui
# copies stand in for the fast streams.
TOPICS = (
    "/amr/events",
    DEVICE_HEALTH_TOPIC,
    "/amr/mode_state",
    "/amr/line_state",
    "/amr/run_state",
    "/amr/mux_state",
    "/amr/control_lease",
    "/amr/motion_permit",
    "/drives/status",
    "/wheel_states_ui",
    "/amr/line_track_ui",
    "/amr/panel_state_ui",
    "/amr/line/order_state",  # the station call's order (WP-P6 delta 2026-11-16)
    "/amr/rear/trolley",
    "/output_paths",  # ~17 Hz, a few bytes: the field stop evidence
    "/diagnostics",
)

# ModeState / LineState / Event values (amr_interfaces), as plain ints.
MODE_FAULT = 5
LINE_HOLD, LINE_FAULT = 3, 5
EVENT_ERROR = 2


def enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def root(state_dir: str) -> str:
    return os.path.join(os.path.expanduser(state_dir), DIRNAME)


def record_argv(out_dir: str, cache_mb: int = CACHE_MB, topics: tuple = TOPICS) -> list[str]:
    if not 1 <= int(cache_mb) <= 256:
        raise ValueError(f"blackbox cache {cache_mb} MB: expected 1..256")
    return [
        "ros2", "bag", "record",
        "--snapshot-mode",
        "--max-cache-size", str(int(cache_mb) * 1024 * 1024),
        "-s", "mcap",
        "--node-name", NODE_NAME,
        "-o", out_dir,
        *topics,
    ]


def recorder_cmd(state_dir: str, cache_mb: int = CACHE_MB) -> list[str]:
    """The launch command: a new bb-<YYYYmmdd-HHMMSS> directory on every (re)spawn, because
    `ros2 bag record -o` refuses one that exists and a respawn reuses the same argv."""
    argv = record_argv("OUT", cache_mb)
    i = argv.index("OUT")
    script = " ".join(argv[:i]) + ' "$1/bb-$(date +%Y%m%d-%H%M%S)" ' + " ".join(argv[i + 1:])
    return ["sh", "-c", f"mkdir -p \"$1\" && exec {script}", "sh", root(state_dir)]


def newest_bag_dir(names: list[str]) -> str:
    """The running recorder's directory: the newest bb-<stamp> name ("" if none)."""
    bags = sorted(n for n in names if n.startswith("bb-"))
    return bags[-1] if bags else ""


class TriggerPolicy:
    """Which edges dump, and when.

    observe_mode / observe_line / observe_event feed the latest values; due(now) returns the
    reasons to dump now (and forgets them) or []. A trigger waits `post_s` so the seconds after
    the edge are in the snapshot, and dumps are at least `min_gap_s` apart: triggers in between
    are kept and dumped together at the end of the gap (the cache still holds them). The first
    sample of each stream is a baseline, not an edge: a respawned trigger node in FAULT does not
    dump again."""

    def __init__(self, post_s: float = 3.0, min_gap_s: float = 60.0) -> None:
        self.post_s, self.min_gap_s = float(post_s), float(min_gap_s)
        self._mode: int | None = None
        self._line: int | None = None
        self._pending: list[str] = []
        self._first_t: float | None = None
        self._last_dump: float | None = None

    def _trigger(self, now: float, reason: str) -> None:
        if self._first_t is None:
            self._first_t = now
        if reason not in self._pending:
            self._pending.append(reason)

    def observe_mode(self, now: float, mode: int, fault_code: str = "") -> None:
        prev, self._mode = self._mode, int(mode)
        if prev is not None and prev != MODE_FAULT and self._mode == MODE_FAULT:
            self._trigger(now, f"mode FAULT {fault_code}".strip())

    def observe_line(self, now: float, state: int, hold_cause: str = "") -> None:
        prev, self._line = self._line, int(state)
        if prev is None or prev == self._line:
            return
        if self._line == LINE_FAULT:
            self._trigger(now, "line FAULT")
        elif self._line == LINE_HOLD:
            self._trigger(now, f"line HOLD {hold_cause}".strip())

    def observe_event(self, now: float, level: int, code: str) -> None:
        if int(level) >= EVENT_ERROR:
            self._trigger(now, f"event {code}")

    def due(self, now: float) -> list[str]:
        if not self._pending:
            return []
        at = self._first_t + self.post_s
        if self._last_dump is not None:
            at = max(at, self._last_dump + self.min_gap_s)
        if now < at:
            return []
        out, self._pending, self._first_t, self._last_dump = self._pending, [], None, now
        return out


def prune_plan(files: list[tuple[str, float, int]], keep: int = 20, max_bytes: int = 400 * 1024 * 1024,
               protect: str = "") -> list[str]:
    """(path, mtime, size) of every snapshot file -> the paths to delete: the oldest first, until at
    most `keep` files and `max_bytes` remain. Nothing under `protect` (the running recorder's
    directory) is ever on the list."""
    prefix = os.path.join(protect, "") if protect else None

    def live(path: str) -> bool:
        return bool(prefix) and path.startswith(prefix)

    ordered = sorted(files, key=lambda f: f[1], reverse=True)  # newest first
    kept = sum(1 for f in files if live(f[0]))
    total = sum(f[2] for f in files if live(f[0]))
    out = []
    for path, _t, size in ordered:
        if live(path):
            continue
        if kept < keep and total + size <= max_bytes:
            kept, total = kept + 1, total + size
        else:
            out.append(path)
    return out


def snapshot_files(state_dir: str) -> list[tuple[str, float, int]]:
    """Every .mcap under <state_dir>/blackbox, as (path, mtime, size)."""
    out = []
    for d, _dirs, names in os.walk(root(state_dir)):
        for n in names:
            if n.endswith(".mcap"):
                p = os.path.join(d, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out.append((p, st.st_mtime, st.st_size))
    return out
