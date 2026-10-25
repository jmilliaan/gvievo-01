"""MLS sensor readings the amr_line tests share (lean plan D65): one track centred on LCP2, and
no tape at all. The dict shape is what job.Inputs.sensor carries."""

CENTRED = {"tracks": [{"index": 2, "pos_mm": 0, "width": 10}], "has_track": True, "nlcp": 2, "track_level": 5}
NO_TAPE = {"tracks": [], "has_track": False, "nlcp": 0, "track_level": 0}

# The test plants' encoders (D31): 10000 counts per motor turn, through the profile's gearhead.
import math  # noqa: E402

from agv_core import config  # noqa: E402

COUNTS_PER_MOTOR_REV = 10000.0
PER_REV = COUNTS_PER_MOTOR_REV * config.GEAR_RATIO      # counts per wheel turn


def counts_for_angle(deg, counts_per_wheel_rev=PER_REV):
    """Per-wheel counts for a pivot of `deg`: arc (track/2)*angle over pi*D (D140: test-only,
    so it lives here and not in amr_line.uturn)."""
    arc = config.TRACK_M / 2.0 * math.radians(deg)
    return arc / (math.pi * config.WHEEL_DIA_M) * counts_per_wheel_rev
