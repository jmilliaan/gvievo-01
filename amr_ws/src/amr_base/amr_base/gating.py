"""Command source selection for the mux (spec §2.1, §3.5). Pure, clock-fed.

Authority comes from two places, never from the command streams themselves:
  * the physical panel: selector MANUAL is teleop authority, AUTO is the
    executor's; a stale or invalid panel image is no authority at all;
  * the executor's MotionPermit lease: FOLLOW or ROTATE, expiring 0.3 s after
    local receipt, and only honoured under AUTO.
Within an authority a command must still be fresh (0.2 s). Teleop owns the mux
for 0.5 s after its last message (so a stray nav command cannot slip in) but a
non-zero teleop command older than 0.2 s is still replaced by zero.
"""

from __future__ import annotations

from dataclasses import dataclass

NONE, TELEOP, FOLLOW, ROTATE = 0, 1, 2, 3
NAMES = {NONE: "none", TELEOP: "teleop", FOLLOW: "follow", ROTATE: "rotate"}


@dataclass(frozen=True)
class Params:
    cmd_timeout_s: float = 0.2
    teleop_window_s: float = 0.5
    permit_timeout_s: float = 0.3
    panel_timeout_s: float = 0.2


DEFAULT = Params()


@dataclass
class Stamped:
    t: float
    v: float
    w: float


@dataclass
class Permit:
    t_recv: float
    source: int
    enabled: bool


@dataclass
class Panel:
    t_recv: float
    valid: bool
    auto: bool


@dataclass
class Selection:
    source: int
    v: float
    w: float
    reason: str


def select(
    now: float,
    teleop: Stamped | None,
    follow: Stamped | None,
    rotate: Stamped | None,
    permit: Permit | None,
    panel: Panel | None,
    p: Params = DEFAULT,
) -> Selection:
    panel_ok = panel is not None and panel.valid and now - panel.t_recv <= p.panel_timeout_s
    if not panel_ok:
        return Selection(NONE, 0.0, 0.0, "no panel authority")

    if not panel.auto:
        if teleop is not None and now - teleop.t <= p.teleop_window_s:
            if now - teleop.t <= p.cmd_timeout_s:
                return Selection(TELEOP, teleop.v, teleop.w, "teleop")
            return Selection(TELEOP, 0.0, 0.0, "teleop command timed out")
        return Selection(NONE, 0.0, 0.0, "MANUAL, no teleop command")

    permit_ok = permit is not None and permit.enabled and now - permit.t_recv <= p.permit_timeout_s
    if not permit_ok:
        return Selection(NONE, 0.0, 0.0, "AUTO, no motion permit")
    if permit.source == FOLLOW:
        if follow is not None and now - follow.t <= p.cmd_timeout_s:
            return Selection(FOLLOW, follow.v, follow.w, "follow")
        return Selection(NONE, 0.0, 0.0, "permit FOLLOW, no fresh /cmd_vel")
    if permit.source == ROTATE:
        if rotate is not None and now - rotate.t <= p.cmd_timeout_s:
            return Selection(ROTATE, rotate.v, rotate.w, "rotate")
        return Selection(NONE, 0.0, 0.0, "permit ROTATE, no fresh /cmd_vel_rotate")
    return Selection(NONE, 0.0, 0.0, "permit NONE")
