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
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import helpers  # noqa: E402

MODULES = [
    "test_config",
    "test_invariants",
    "test_canmon",
    "test_lss",
    "test_verify_bus",
    "test_imu",
    "test_rpdo",
    "test_rfid",
    "test_dio",
    "test_lidar",
    "test_panel",
    "test_blindrun",
    "test_layout",
    "test_mls",
    "test_mission",
    "test_se2",
    "test_paths",
    "test_fsio",
    "test_fsutil",
]

# 869 + 24 (2026-09-19): test_mls added with the restored read_mls.py decoders
# (line-follow plan §1.1). Nothing removed or moved.
# 893 + 5 (2026-09-20): the agv_core package. test_layout stopped pinning the
# flat sys.path namespace (4 checks) and started pinning the package boundary
# instead (9), split across one extra test function: the library is a package,
# it imports neither ROS nor Flask, and no module in it imports a sibling bare.
# 898 - 367 (2026-09-21, U11): the legacy controller is gone. Removed, legacy
# only: test_canworker (70), test_web (129), test_health (32) as modules, and
# the Controller/app/runlog cases inside test_panel (37), test_blindrun (33),
# test_layout (33), test_invariants (21), test_lidar (6, the lidar_scan bench
# tool), test_dio (4, the legacy health monitor), test_rpdo (2). Moved, shared
# library: the guard-bypass checks in test_canmon (3) and the RPDO wiring
# checks in test_rpdo (4) now read amr_base/canopen.py, the bus owner that
# replaced canworker. Nothing added. Per-module counts before/after are in
# manuals/vehicle-reports/2026-09-21-restructure-and-line-layer.md.
# + 8 (2026-10-02): test_mls calibration summary (read_mls calibrate).
# - 3 + 1 (2026-10-02): dead speed params removed (manual.*, motion.py, MANUAL_HALF_RPM);
# one check that the retired manual section is refused.
# + 17 (2026-10-02): test_mission, the tape-mission validator ported from gy-demo.
# + 9 (2026-10-08): mission schema v2, the RFID tag table. test_mission 20 -> 32 (v1 route,
# stop and profile-toggle checks replaced by the tag-table rules and the site file);
# test_config 7 -> 4 (the profile toggle-tag rules became refusals of the retired keys,
# plus the U-turn window).
# + 18 (2026-10-08): tracked-speed-plan-1. test_config + 8 (the slow-zone keys refused,
# HIGH ratio / motor limit / curve guard / high ramp bounds); test_mission + 10 (the
# high_zone block: budget, entry window, refusals; the toggle check became its refusal).
# + 31 (2026-10-09): MLS markers (manuals/mls-marker-plan.md). test_canmon + 4 (guard's
# line-sensor list, read_mls writes only through it); test_mls + 15 (raw marker field,
# set-markers, marker watch, Hall profile, no-track gate, element count, baseline); test_config + 12 (the mls
# block and its refusals).
# Counted on top of the uncommitted RFID work in this tree (671).
# + 3 (2026-10-09): speed zones on MLS markers, RFID stops only. test_mission high zone
#   10 -> 13 (RFID zone row refused, v2.1 block refused, code not laid / text / same code
#   refused, zone with no RFID row; the zone-tag ignore window refusal is gone).
# + 19 (2026-10-17): tracked plan 3, tape-graph localization. test_config + 6 (the tape_loc block:
#   off, station limit within +-10 cm, refusals); test_mission + 13 (site-3 schema: the site-103
#   file, its legs and listing, 8 refusals).
# + 1 (2026-10-18): the straight-section test mission (plan 3 section 7).
# + 14 (2026-10-18): MLS diagnostics (manuals/mls-diagnostics-plan.md M0). test_mls + 11 (event
#   source/cause and temperature decoding, the reset on the guard list and the thresholds off it);
#   test_canmon + 1 (DriveLink.write_sensor goes through check_sensor; the list check now names
#   2080h:01); test_config + 2 (mls.event_clear off, and its refusal).
# + 7 (2026-10-18): the marker run (plan 3 section 7.5): test_mission, the straight's mission and
#   6 refusals.
# + 5 (2026-10-23): the four basic jobs (empty, basic-right, basic-high-left, basic-high-right)
#   and the mission picker's note (test_mission).
# + 2 (2026-10-23): the kink pivot's profile refusals (kink_edge_mm, kink_max_deg; test_config).
# + 1 (2026-10-24): kink_stop_mm's refusal (test_config).
# + 1 (2026-10-24): HIGH budget removed - the retired autopilot.high_margin_m is refused (test_config);
#   test_mission's budget checks became no-budget and retired-key checks one for one.
# + 1 (2026-10-24): guided speed toggle - a marker run with a zone on other codes loads; the guided
#   high-zone refusal became a load check (test_mission).
# + 1 (2026-10-24): the U-turn gyro gate's refusal (u_turn_gyro_min_deg; test_config).
# + 1 (2026-10-24): tape_loc.monitor_jump_m's refusal (test_config).
# + 10 (2026-10-24): tracked plan 4, the position engine. test_config + 1 (tape_loc.live without
#   tape_loc.enabled refused); test_mission + 9 (site-4: cruise, U-turn points and zones load, the
#   retired site-3 and 7 refusals).
# - 2 (2026-10-25): high-speed zones are map areas, not mission data: test_mission's 3 zone
#   refusals became 1 ("zones" refused by name).
# + 1 (2026-10-25): a merge's "steer" (MRU inbound, always left to HOME): refused off a merge.
# Lean plan (manuals/lean-plan.md), 2026-10-25:
# + 3 D44: test_canmon - the IMU TPDO COB-IDs on the line-sensor list (its exact-set check names
#   them), their mappings refused, FREE refused on both lists, the bench guard refuses before a
#   frame; "read_mls writes only through its wrapper" became "no raw sdo_write( in canbus/".
# - 3 D57: the unused statusword-flag decoder and its 3 checks (test_canmon).
# + 9 D41/D43: test_canmon - the shared CiA 301/402 words, one enable sequence, the preflight
#   verdict (healthy, silent, collision, fault, Remote clear, unreadable).
# + 1 D115: test_imu - gyro_dps.
# + 4 D28: test_verify_bus (new module) - verify_bus.run exit codes and hints.
# + 3 D55: test_canmon - decode_int, MonitorPoller.step (moved from amr_base test_canopen,
#   which loses its MonitorCursor case).
# + 1 D45: test_mls - the bench marker watch follows the runtime detector's abort grace
#   (the abort check became inside-grace / after-grace).
# + 2 D80/D150: test_rfid - the pass line parses back, channel_mhz. D82 retargeted the dropped
#   snapshot fields to the link's own state (count unchanged).
# + 4 D02: test_config - 7 retired keys refused (autopilot.dry_run, can.use_rpdo,
#   monitor.poll_period_s, imu.poll_period_s/retry_period_s, timing.telemetry_period_s/
#   manual_watchdog_s); the 2 IMU pacing refusals went with their keys; test_rpdo's
#   use_rpdo legacy-flag check went with it. R16 now uses timing.driver_timeout_s.
# + 1 D145: test_config - config.product().
# + 4 D20: test_se2 (new module) - wrap, compose, yaw_of planar and rolled, correction_at.
# + 1 D33: test_blindrun - kinematics.counts_delta / to_int32 across the wrap.
# + 1 D34: test_config - the derived WHEEL_RAD_S_PER_MOTOR_RPM.
# + 3 D75/D76/D58: test_mission - slowdowns too steep for 6084h are refused in the site stop, the
#   site U-turn and the marker-run U-turn (one decel helper behind every mission shape).
# + 8 D77: test_mission - load and load_site refuse a bad name, a missing file and invalid JSON
#   through one reader (6); a missing tag-table mission lists the alternatives; a site mission's name
#   must match its file.
# + 4 D24: test_paths (new module) - unset defaults, empty counts as unset, env wins with ~
#   expanded, env_for.
# + 6 D17: test_fsio (new module) - thread lock exclusion, temp sweep, chunked sha,
#   positive_revision, publish refuses an existing dest, wrapped rename error.
# + 8 D29: test_fsutil (new module) - rotation shift and absent file, atomic json mode/dir/failure,
#   mkstemp leaves no temp, tolerant jsonl, keep_newest and its keep-0 edge.
# + 1 D171: test_rpdo - every pp.expect object is in guard's read-only pp set.
# + 6 WP-0B (unified plan, 2026-10-28): test_canmon - sdo_probe reads both presets uploads-only,
#   prints value/abort, refuses write-shaped args, names no write/NMT helper (4); test_lss - it
#   takes the owner lock before the bus (2).
# + 5 WP-A1 (unified plan, 2026-10-28): test_rfid - a reconnect re-baselines only the tag in the
#   field at the drop (A/drop/B, A inside and outside the window, failed connect), random generation.
# + 5 WP-A7 (unified plan, 2026-10-28): test_mission - max_tag_gap_m off when absent, loads, and is
#   refused at 0, below 0 and on a mission without tag rows.
# + 9 WP-A10 (unified plan, 2026-10-28): test_config - the freshness block: cmd/lease/permit ceilings,
#   line and executor consumers below the gate, pc_loss_ms 0, heartbeat >= half the loss window,
#   driver timeout under three TPDO periods, a missing key.
# + 1 WP-B3 (2026-10-28): test_canmon - every sdo_write( in amr_base canopen.py follows a guard check.
# + 7 WP-B5 (2026-10-28): test_lss - read_mls snapshot, poll and stream --nmt take the owner lock
#   (refused while owned, release after) (6); stream without --nmt stays lock-free (1).
EXPECTED_CHECKS = 869


# An exception on a helper thread only prints a traceback by default - the
# check that started the thread can still pass. Record every one so the run
# fails instead.
THREAD_ERRORS = []


def _thread_excepthook(args):
    THREAD_ERRORS.append(f"{args.thread.name if args.thread else '?'}: "
                         f"{args.exc_type.__name__}: {args.exc_value}")
    _default_excepthook(args)


_default_excepthook = threading.excepthook


# pytest-style modules (plain asserts, no check()): run here too, outside the check count, so
# the one command covers them (lean plan D26). Paths are relative to the repo root.
PYTEST_PATHS = ["tests/test_alarms.py", "tools"]


def _run_pytest_modules():
    """'' when they pass or pytest is not installed (said so), else what failed."""
    import subprocess

    try:
        import pytest  # noqa: F401
    except ImportError:
        print("pytest not installed: skipped " + ", ".join(PYTEST_PATHS))
        return ""
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *PYTEST_PATHS],
                       cwd=str(helpers.ROOT), capture_output=True, text=True)
    print(f"pytest {' '.join(PYTEST_PATHS)}: {(r.stdout.strip().splitlines() or ['?'])[-1]}")
    return "" if r.returncode == 0 else f"pytest {' '.join(PYTEST_PATHS)} failed"


def main():
    threading.excepthook = _thread_excepthook
    print(f"profile {helpers.config.PROFILE_NAME}: "
          f"can {helpers.config.CAN_BITRATE // 1000} kbps "
          f"6083h={helpers.config.ACCEL_RPM_S}")

    ran = 0
    for name in MODULES:
        mod = importlib.import_module(name)
        for fn in mod.TESTS:
            fn()
            ran += 1

    pytest_problem = _run_pytest_modules()
    total = helpers.CHECKS[0]
    print()
    print(f"{ran} test function(s), {total} check(s)")

    problems = list(helpers.FAIL)
    problems += [f"uncaught exception in thread {e}" for e in THREAD_ERRORS]
    if pytest_problem:
        problems.append(pytest_problem)
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
