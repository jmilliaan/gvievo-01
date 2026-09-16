#!/usr/bin/env python3
"""Run the whole offline suite. No CAN, no hardware, no motion.

    python3 tests/run_all.py

Splitting one 1,465-line file into eight had a failure mode worth guarding: a
module that quietly stops being imported costs coverage without producing a
symptom - the run still ends in "all checks passed", just with fewer checks in
it. So this runner pins BOTH the module list and the total number of checks. A
dropped module, or a test that silently stopped asserting, fails the run.

Raise EXPECTED_CHECKS deliberately when checks are added; never lower it to make
a run go green.
"""
import importlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import helpers  # noqa: E402

MODULES = [
    "test_config",
    "test_canworker",
    "test_invariants",
    "test_health",
    "test_canmon",
    "test_lss",
    "test_imu",
    "test_rpdo",
    "test_rfid",
    "test_dio",
    "test_lidar",
    "test_panel",
    "test_blindrun",
    "test_web",
    "test_layout",
]

EXPECTED_CHECKS = 784


def main():
    print(f"profile {helpers.config.PROFILE_NAME}: "
          f"can {helpers.config.CAN_BITRATE // 1000} kbps "
          f"use_rpdo={helpers.config.CAN_USE_RPDO} "
          f"jog {helpers.config.MANUAL_FULL_RPM} r/min "
          f"6083h={helpers.config.ACCEL_RPM_S}")

    ran = 0
    for name in MODULES:
        mod = importlib.import_module(name)
        for fn in mod.TESTS:
            fn()
            ran += 1

    total = helpers.CHECKS[0]
    print()
    print(f"{ran} test function(s), {total} check(s)")

    problems = list(helpers.FAIL)
    if total != EXPECTED_CHECKS:
        problems.append(
            f"expected {EXPECTED_CHECKS} checks, ran {total} - a module or a "
            f"check went missing (or update EXPECTED_CHECKS deliberately)")

    if problems:
        print(f"{len(problems)} FAILED: " + ", ".join(problems))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
