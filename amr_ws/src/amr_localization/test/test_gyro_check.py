"""WP-E7 / H-P1-7: the gyro against the wheels' yaw rate."""

from __future__ import annotations

import math

from amr_localization.gyro_check import GyroCheck, curve_yaw_rate


def feed(chk, t0, seconds, gyro, wheel, dt=0.02):
    t = t0
    for _ in range(int(round(seconds / dt))):
        t += dt
        chk.update(t, gyro, wheel)
    return t


def test_a_gyro_reading_zero_through_a_turn_is_suspect():
    chk = GyroCheck()
    t = feed(chk, 0.0, 0.9, 0.0, 0.3)
    assert not chk.suspect, "under turn_s: no verdict yet"
    feed(chk, t, 0.2, 0.0, 0.3)
    assert chk.suspect and "disagrees" in chk.reason


def test_the_opposite_sign_is_suspect():
    chk = GyroCheck()
    feed(chk, 0.0, 1.1, -0.3, 0.3)
    assert chk.suspect and "against" in chk.reason


def test_still_with_a_constant_reading_is_never_flagged():
    chk = GyroCheck()
    q = math.radians(0.061)  # one quantisation step, held
    feed(chk, 0.0, 30.0, q, 0.0)
    feed(chk, 30.0, 30.0, q, 0.05)  # creeping: below turn_rad_s
    feed(chk, 60.0, 5.0, q, None)  # no wheel feedback
    assert not chk.suspect and chk.windows == 0


def test_an_agreeing_turn_is_fine_and_clears_a_suspect():
    chk = GyroCheck()
    t = feed(chk, 0.0, 1.1, 0.0, 0.3)
    assert chk.suspect
    t = feed(chk, t, 0.5, 0.0, 0.0)  # stopped: the verdict stands
    assert chk.suspect
    feed(chk, t, 1.1, 0.27, 0.3)  # 10 % apart: slip and track-width error are allowed
    assert not chk.suspect and chk.windows == 2
    feed(chk, 10.0, 1.1, -0.5, -0.45)
    assert not chk.suspect, "a clockwise turn agrees the same way"


def test_a_short_turn_or_a_reversal_starts_a_new_window():
    chk = GyroCheck()
    t = feed(chk, 0.0, 0.6, 0.0, 0.3)
    t = feed(chk, t, 0.6, 0.0, -0.3)  # reversed before a window completed
    assert chk.windows == 0 and not chk.suspect
    feed(chk, t, 0.5, 0.0, -0.3)
    assert chk.windows == 1 and chk.suspect


def test_a_non_finite_gyro_sample_is_skipped_not_a_verdict():
    chk = GyroCheck()
    t = 0.0
    for i in range(60):
        t += 0.02
        chk.update(t, math.nan if i % 7 == 0 else 0.3, 0.3)
    assert chk.windows == 1 and not chk.suspect, "the finite samples still agree"
    chk.update(t + 0.02, math.inf, None)
    assert not chk.suspect


def test_the_curve_guard_rate_is_the_larger_of_the_two():
    assert curve_yaw_rate(0.0, 0.3) == 0.3, "a frozen gyro cannot keep HIGH"
    assert curve_yaw_rate(-0.4, 0.3) == -0.4
    assert curve_yaw_rate(None, 0.2) == 0.2 and curve_yaw_rate(0.1, None) == 0.1
    assert curve_yaw_rate(math.nan, 0.2) == 0.2 and curve_yaw_rate(None, None) is None
