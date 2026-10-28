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


# THE hold-cause policy, for both products (owner decision 2026-10-25, unified plan WP-A2):
# only a protective-field stop resumes by itself, and an E-stop only behind the profile's
# auto_resume_estop. Every other hold - a device dropout, a slow or missing tape reading, a
# controller abort, a panel link loss - waits for a fresh physical Start, because the
# operator must look before the vehicle moves again.
AUTO_CAUSES = ("field",)
# Holds on the safety chain's terms: the drives lost torque (STO) for a reason outside this
# software. Wheel feedback may be missing while one stands, and a later torque loss does not
# re-classify it. "panel": the I/O island reported its image invalid just before the torque
# went - the safety chain's state is then unknown, so it is never read as the field.
SAFETY_CAUSES = ("field", "estop", "panel")
# The device each cause blames (LineState/RunState.hold_device). "" = no single device.
CAUSE_DEVICE = {
    "field": "scanner",
    "estop": "safety_chain",
    "panel": "dio",
    "drives": "drives",
    "drive_fault": "drives",
    "track": "mls",
    "rate": "mls",
    "sensor": "mls",
    "markers": "mls",
    "rfid": "rfid",
    "rfid_overdue": "rfid",
    "controller": "nav2",
}


def auto_causes(estop: bool) -> tuple[str, ...]:
    """Hold causes that resume by themselves; an E-stop only when the profile allows it."""
    return AUTO_CAUSES + (("estop",) if estop else ())


def hold_device(cause: str) -> str:
    return CAUSE_DEVICE.get(cause, "")


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
