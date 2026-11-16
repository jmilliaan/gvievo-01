"""The base's event recorder, framework-free (unified plan WP-H3, hardening plan H-P1-15).

Every /amr/events message, and every DeviceHealth edge, appended to its own file
(`<state_dir>/logs/recorded_events.jsonl`, agv_core.eventlog: rotated, ERROR synced). It
runs in the base, so the record survives the web being down or respawning; the web's own
ring and file are the Alarms page's and stay as they are.

A write that fails is counted, never raised (a full disk must not stop the base). The
failing edge is reported once as EVENTLOG_WRITE_FAILED, and its clearing once. The
recorder hears its own report on /amr/events and records it like any other; while the log
stays failing that adds no further edge.

The legacy in-process ring agv_core/events.py cannot be read from here (it lives in the
memory of the process that wrote it). Lean plan D08 removes it; the DIO link edges it held
reach /amr/events through panel_node already.
"""

from __future__ import annotations

import os

from agv_core import alarms, health
from agv_core.eventlog import EventLog

FILENAME = "recorded_events.jsonl"
LEVELS = ("info", "warn", "error")  # Event.level 0..2
SOURCE = "event_recorder"


def path_in(state_dir: str) -> str:
    return os.path.join(os.path.expanduser(state_dir), "logs", FILENAME)


def event_row(t_wall: float, source: str, level: int, code: str, text: str, seq: int) -> dict:
    """An Event msg as one log line: the web's own row shape (amr_web adapter._on_event)."""
    return {"t": t_wall, "source": source, "level": LEVELS[max(0, min(int(level), 2))],
            "code": code, "text": text, "seq": int(seq)}


class Recorder:
    def __init__(self, log: EventLog) -> None:
        self.log = log
        self.recorded = 0
        self.failing = False
        self._health: dict[str, tuple[str, str]] = {}  # device -> (state, code) last recorded

    def record(self, row: dict) -> tuple[int, str, str] | None:
        """Append one row. -> (level, code, text) to publish when the write state changed."""
        before = self.log.errors
        self.log.append(row, sync=row.get("level") == "error")
        self.recorded += 1
        failing = self.log.errors > before
        if failing == self.failing:
            return None
        self.failing = failing
        if failing:
            return (alarms.level("EVENTLOG_WRITE_FAILED"), "EVENTLOG_WRITE_FAILED",
                    f"cannot write {self.log.path} ({self.log.errors} failed writes)")
        return (0, "EVENTLOG_WRITE_FAILED", f"cleared: writing {self.log.path} again")

    def health(self, t_wall: float, device: str, state: str, code: str, detail: str):
        """One DeviceHealth row: recorded only when the device's (state, code) changed (the 2 Hz
        repeats are not news). -> what record() returns, or None."""
        key = (state, code)
        prev = self._health.get(device)
        if prev == key:
            return None
        self._health[device] = key
        owner = health.OWNER.get(device, "?")
        text = f"{device} {state}" + (f": {detail}" if detail else "")
        if code:
            level, shown = alarms.level(code), code
        elif prev is not None and prev[1]:
            level, shown, text = 0, prev[1], f"cleared: {text}"  # back to OK / ABSENT
        else:
            level, shown = 0, "DEVICE_HEALTH"
        return self.record(event_row(t_wall, owner, level, shown, text, 0))
