"""After an E-stop Reset, take a standby drive out of Switch on disabled (emergency-suite plan
Part B E5, 2026-11-16). Pure, clock-fed; drive_node acts on it.

CiA 402: STO drops a drive to "Switch on disabled", and only a Shutdown controlword (6040h =
0x06, transition 2) takes it to "Ready to switch on" once STO is released. drive_node sends
Shutdown when it links (canopen.prepare) and when it powers down (release, engage's rollback).
With the drives already in standby when the E-stop is pressed (Manual Arm off, AUTO idle)
nothing sends one after the Reset: emergency.sto_held() stays True, RESETTING ends RESET_FAILED,
and arm_policy refuses power until a service restart (prepare's Shutdown). kyb-trackless has
the same gap (its drive_node does nothing here).

So while the panel's emergency is RESETTING (the Reset was seen with the E-stop signal clear), the link is
STANDBY and a drive still reads Switch on disabled, Shutdown is asked for that drive, at most
every period_s (STO may release a little after the Reset edge). Shutdown powers nothing: the
power stage stays off, and arming still needs arm_policy's yes after NORMAL. Outside RESETTING
nothing is sent, so a drive held by a pressed E-stop is never written to.
"""

from __future__ import annotations

from amr_base import emergency

PERIOD_S = 0.5


class StoRearm:
    def __init__(self, period_s: float = PERIOD_S) -> None:
        self.period = float(period_s)
        self._t: float | None = None  # last Shutdown asked for in this RESETTING episode

    def due(self, now: float, emergency_state: int, link_state: str, states: dict) -> list:
        """The nodes to send Shutdown to now. states: {node: reported CiA-402 state text}."""
        if emergency_state != emergency.RESETTING or link_state != "standby":
            self._t = None
            return []
        nodes = [n for n, s in sorted(states.items()) if s == emergency.STO_STATE]
        if not nodes or (self._t is not None and now - self._t < self.period):
            return []
        self._t = now
        return nodes
