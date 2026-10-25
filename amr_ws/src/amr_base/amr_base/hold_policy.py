"""Hold / auto-resume / pre-move primitives shared by the two run FSMs. Pure, clock-fed.

The SLAM route executor (amr_mission) and the LINE job (amr_line) keep their own state
machines, hold paths and per-product causes; what they share is here, so the operator sees
the same words and the same debounce on either product.
"""

from __future__ import annotations

# The operator-facing text of a safety hold. Other causes show `why` as it is.
HOLD_TEXT = {
    "field": "safety stop (protective field): {why}",
    "estop": "safety stop (E-stop / safety chain): {why}",
}


def hold_text(cause: str, why: str, extra: dict[str, str] | None = None) -> str:
    """The reason shown for a hold. `extra` adds product causes ({why} is substituted)."""
    fmt = (extra or {}).get(cause) or HOLD_TEXT.get(cause)
    return fmt.format(why=why) if fmt else why


def auto_causes(base: tuple[str, ...], estop: bool) -> tuple[str, ...]:
    """Hold causes that resume by themselves; an E-stop only when the profile allows it."""
    return tuple(base) + (("estop",) if estop else ())


class Debounce:
    """True once a condition has failed CONTINUOUSLY for the grace (operator decision
    2026-09-20). Any passing tick clears the timer, so one dropped frame never latches.
    What is debounced is "something is wrong", not one message: the reason may change while
    the timer runs. The grace is passed per call because it is a live parameter."""

    __slots__ = ("since",)

    def __init__(self) -> None:
        self.since: float | None = None

    def reset(self) -> None:
        self.since = None

    def held(self, now: float, failing, grace_s: float) -> bool:
        if not failing:
            self.since = None
            return False
        if self.since is None:
            self.since = now
        return now - self.since >= grace_s


def premove_ready(waited_s: float, premove_s: float, drives_fresh: bool, torque_off: bool) -> bool:
    """The pre-move warning has run and the drives report torque: the run may move."""
    return waited_s >= premove_s and drives_fresh and not torque_off


def premove_timeout_text(timeout_s: float, tail: str) -> str:
    return f"drives did not power up within {timeout_s:.0f} s ({tail})"
