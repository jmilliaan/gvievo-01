"""A U-turn set on /blind and run from the panel in MANUAL.

Pure computation owned by the CAN thread, like uturn.py and blindrun.py: no
clocks, no I/O. The web page only SETS one of these; PB Start runs it.

It stands in for a U-turn tag read, with the vehicle already at rest on the
tape - the caller refuses to start one without a track under the MLS. How it
ends depends on the angle, because the tape only comes back at 180:

  180  exactly the AUTO pivot (uturn.UTurn): the MLS must lose the tape and
       find it again inside u_turn_min_deg..u_turn_max_deg, then centre.
  90   on a straight tape the sensor bar ends parallel to it, 97 mm to one
       side, so there is nothing to find. The pivot ends on the ENCODER angle
       (blindrun's trapezoid, overrun and time checks), then centres only if a
       track - a crossing tape - is under the sensor once the drives are at rest.
"""
import math

import blindrun
import config
import uturn

KIND = "u_turn"
ANGLES = (90, 180)
DIRECTIONS = ("cw", "ccw")


def plan(angle_deg, direction, counts_per_wheel_rev):
    """Validate a turn and return it as a /blind plan. Moves nothing."""
    if not counts_per_wheel_rev or counts_per_wheel_rev <= 0:
        raise ValueError("encoder scale unknown")
    try:
        angle = float(angle_deg)
    except (TypeError, ValueError):
        angle = None
    if angle not in ANGLES:
        raise ValueError(f"U-turn angle_deg must be one of {ANGLES}")
    if direction not in DIRECTIONS:
        raise ValueError("U-turn direction must be cw or ccw")
    angle = int(angle)
    pivot = None
    if angle != 180:
        # Blind-run convention: + is counter-clockwise.
        sign = -1 if direction == "cw" else 1
        pivot = blindrun.plan([{"kind": "pivot", "angle_deg": sign * angle}],
                              {"motor_rpm": config.AUTO_U_TURN_RPM},
                              counts_per_wheel_rev)
    return {"kind": KIND, "angle_deg": angle, "direction": direction,
            "end": "tape" if pivot is None else "encoder",
            "rpm": config.AUTO_U_TURN_RPM,
            "counts_per_wheel_rev": counts_per_wheel_rev, "pivot": pivot}


class ManualTurn:
    def __init__(self, planned, start_counts, start_level):
        self.plan = planned
        self.angle = planned["angle_deg"]
        self.direction = planned["direction"]
        self._cpr = planned["counts_per_wheel_rev"]
        self.phase = uturn.SPIN
        self.reason = None
        self.centred = None          # unknown until the turn ends
        self._pivot = None
        self._turn = None
        if planned["pivot"] is None:
            self._turn = uturn.UTurn(self.direction, self._cpr, start_counts, start_level)
        else:
            self._pivot = blindrun.BlindRun(planned["pivot"], start_counts)

    @property
    def active(self):
        return self.phase not in (uturn.DONE, uturn.FAILED)

    @property
    def turned_deg(self):
        """Turned so far in the commanded direction, by encoder."""
        deg = 0.0
        if self._pivot is not None:
            sign = -1.0 if self.direction == "cw" else 1.0
            deg += math.degrees(self._pivot.pose[2]) * sign
        if self._turn is not None:
            deg += self._turn.angle_deg
        return deg

    def _fail(self, reason):
        self.phase, self.reason = uturn.FAILED, reason
        return 0.0, 0.0

    def abort(self, reason):
        if self.active:
            self._fail(reason)
        return 0.0, 0.0

    def update(self, counts, e_mm, level, dt, stopped):
        """One tick. `stopped` is the drives' speed-zero verdict (None: unknown).

        Returns (left_rpm, right_rpm) in driver terms.
        """
        if not self.active:
            return 0.0, 0.0
        if self._turn is None:
            left, right = self._pivot.update(counts, dt, stopped)
            if self._pivot.phase == blindrun.ABORTED:
                return self._fail(f"{self.angle} deg pivot: {self._pivot.reason}")
            if self._pivot.phase != blindrun.DONE:
                return left, right
            # At rest on the encoder angle. BlindRun only finishes once both
            # drives report standstill, so this is the settled MLS reading.
            if e_mm is None or level is None:
                self.phase, self.centred = uturn.DONE, False
                return 0.0, 0.0
            self._turn = uturn.UTurn(self.direction, self._cpr, counts, level,
                                     phase=uturn.CENTER)
        left, right = self._turn.update(counts, e_mm, level, dt)
        self.phase = self._turn.phase
        if self.phase == uturn.FAILED:
            self.reason = self._turn.reason
        elif self.phase == uturn.DONE:
            self.centred = True
        return left, right

    def snapshot(self):
        return {"kind": KIND, "phase": self.phase, "reason": self.reason,
                "angle_deg": self.angle, "direction": self.direction,
                "end": self.plan["end"], "turned_deg": self.turned_deg,
                "tape_lost": bool(self._turn is not None and self._turn.lost),
                "centred": self.centred}
