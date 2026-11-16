"""Sim fault hooks (hardening plan H-P3-2, unified plan WP-T2). Sim only, never on a vehicle.

Every fake gets the same two switches, as std_srvs/SetBool services on the node:
    ~/mute     true: publish nothing (a silent device: consumers see it go stale)
    ~/freeze   true: publish the last message again with a fresh stamp (a frozen device:
               stamps and seq move on, the content does not)
and some take a script in parameters (seconds since the node started):
    start_delay_s   silent until then
    drop_after_s    silent from then on            (dropout_at_s + dropout_s: silent for a window)
    freeze_after_s  frozen from then on
    tape_synth also: rate_after_s + rate_hz_after (a slow MLS from then on)
A negative or zero value is off. The services win over the script while they are set.

Pure: no rclpy (test_fault_hooks.py). The nodes keep one Hooks per published stream.
"""

from __future__ import annotations

import copy

OK, MUTE, FREEZE = "ok", "mute", "freeze"


class Script:
    """A fault timeline in seconds since start. mode(t) -> OK | MUTE | FREEZE."""

    def __init__(self, start_delay_s: float = 0.0, drop_after_s: float = 0.0, freeze_after_s: float = 0.0,
                 dropout_at_s: float = 0.0, dropout_s: float = 0.0) -> None:
        self.start_delay_s = float(start_delay_s)
        self.drop_after_s = float(drop_after_s)
        self.freeze_after_s = float(freeze_after_s)
        self.dropout_at_s = float(dropout_at_s)
        self.dropout_s = float(dropout_s)

    def mode(self, t: float) -> str:
        if self.start_delay_s > 0 and t < self.start_delay_s:
            return MUTE
        if self.drop_after_s > 0 and t >= self.drop_after_s:
            return MUTE
        if self.dropout_s > 0 and 0 < self.dropout_at_s <= t < self.dropout_at_s + self.dropout_s:
            return MUTE
        if self.freeze_after_s > 0 and t >= self.freeze_after_s:
            return FREEZE
        return OK


class Hooks:
    """One published stream. out(t, msg) -> the message to publish (msg, or the frozen copy) or
    None to publish nothing. The caller stamps what it gets back."""

    def __init__(self, script: Script | None = None) -> None:
        self.script = script or Script()
        self.muted = False
        self.frozen = False
        self._held = None

    def mode(self, t: float) -> str:
        if self.muted:
            return MUTE
        if self.frozen:
            return FREEZE
        return self.script.mode(t)

    def out(self, t: float, msg):
        m = self.mode(t)
        if m == MUTE:
            return None
        if m == FREEZE:
            if self._held is None:
                self._held = copy.deepcopy(msg)
            return self._held
        self._held = None
        return msg

    def set(self, name: str, on: bool) -> str:
        """The ~/mute and ~/freeze services. Returns the reply text."""
        if name == MUTE:
            self.muted = bool(on)
        elif name == FREEZE:
            self.frozen = bool(on)
        else:
            raise ValueError(f"unknown hook {name!r}")
        return f"{name} {'on' if on else 'off'}"


# Script's arguments, in order: the parameter names every hooked fake declares.
SCRIPT_PARAMS = ("start_delay_s", "drop_after_s", "freeze_after_s", "dropout_at_s", "dropout_s")


def script_from(get) -> Script:
    """The script parameters through a get(name) -> value reader (0.0 = off)."""
    return Script(*(float(get(n)) for n in SCRIPT_PARAMS))


def decimation(rate_hz: float, rate_hz_after: float) -> int:
    """tape_synth rate_hz_after: publish every Nth tick, N = the nearest whole divisor (>= 1).
    0 or above rate_hz = unchanged."""
    if rate_hz_after <= 0 or rate_hz_after >= rate_hz:
        return 1
    return max(1, round(rate_hz / rate_hz_after))
