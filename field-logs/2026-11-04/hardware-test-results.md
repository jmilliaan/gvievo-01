# Hardware test results, 2026-11-04

Tests from `HARDWARE-TESTS.md`, run on MCQ4-4 (`gvipc-ce`), in the order 4.0, 4A, 1, 4B, 2, 3.
Updated as tests run. Anything not listed has not been run yet.

## Section 1 state

`git log -1 --oneline`: `44f7951 kyb documetation trial`

`git status --short` at 09:18 and after the build: empty (clean tree, level with `origin/kyb-trackless`).

Python 3.10.12, pytest 6.2.5.

## Results

| ID | Result | Measured | Run stamp |
|---|---|---|---|
| 4.0 pull | Not needed | Already pulled at 09:08:48; HEAD = origin | |
| 4.0 build | Pass | Full `colcon build --symlink-install`, 10 packages, 8 s, service stopped. This is wider than the four packages 4.0 lists, because section 1 asks for all of them | |
| 4A.1 pytest | Pass | 679 passed, 3 xfailed (`test_labels` x2, `test_label_record` x1), `AMR_SIM_TESTS=0`, domain 89. Same result before and after the build | |
| 4A.1 `run_all.py` | Pass | 83 functions, 731 checks, `all checks passed`. Run before the build, not repeated after it | |
| 4A.1 `test_no_foxglove.py` | Pass | 1 passed | |
| 4A.1 `test_alarms.py` | Pass, see note 1 | 5 passed, run directly with pytest | |
| 4A.1 sim tests (optional) | Not run | | |
| 4A.2 boot check | Pass, with notes 2 and 3 | Boot at 09:27:25: `spawned base`, `STARTING -> IDLE` in about 3 s. "foxglove" 0 times in the journal, `ss` and `pgrep` empty | |
| 4A.3 shutdown check | Pass | 09:25:13 stop: `stopped base: clean`, `stopped web: clean`, `teardown: done at 1.1 s`, no foxglove line, `pgrep` empty. Operator ran the stop; the start used `sudo systemctl restart amr.service` | |
| 1 `colcon test` | Pass | 701 tests, 0 errors, 0 failures, 25 skipped, domain 89 | |
| 1 `test_home_leg.py` | Pass | 31 passed | |
| 1 `test_route.py` | Pass | 94 passed, including the store tests that fail on Windows | |
| 1 `test_home_leg_progress_chain_overshoot_and_turn_cap` | Pass | First run anywhere | |
| 1 restart and web UI | Pass, with note 3 | Service active at 09:27:26, `/home` answers 200 | |
| 4B.1 mux values | Pass, with note 4 | `a_max` 0.1, `d_max` 0.125, `auto_jerk` 0.1, `field_d_max` 0.5 by `ros2 param get` | |
| 4B.1 executor and Nav2 values | Pass | `taper_decel` 0.125, `taper_jerk` 0.1, `FollowPath.approach_velocity_scaling_dist` 3.0, NAVIGATION on kyb-map-02 rev 3 (layer started 09:32:18) | |

## Notes

1. `tests/test_alarms.py` is not in the `MODULES` list of `tests/run_all.py`, so `run_all.py` does
   not run it, though 4A.1 reads as if it does. It passes when run directly.
2. 4A.2 expects `spawned web` in the journal. It does not appear on this code:
   `supervisor_node.py` logs `spawned` only from `_launch`, and web is started through
   `Group.spawn` directly. The web process is running (pid 13041 at 09:27).
3. 4A.2 expects the web to answer 200 on `/`. It answers 302 to `/home` (`server.py:238`), and
   `/home` answers 200.
4. 4B.1 greps the journal for `cmd_mux_kinematics: r=`. That line is not in the journal, because
   node output goes to `~/.amr/logs/base.log`. It is there, showing `a_max=0.100`, at 09:27:28.
5. Reset took several tries at the 09:14 boot. From `events.jsonl`:
   `09:16:05 ESTOP_RESET_FAILED Reset did not take: drives still in STO 3 s after Reset`, repeated at
   09:16:12, 09:16:16 and 09:16:22, then `09:16:28 ESTOP cleared`. The boot followed a power-off,
   so slow drive start-up may be the cause. Not investigated.
6. Code changed during testing, on the owner's request and unrelated to any test: the route
   arc angle range went from 45–180° to 10–180°, to 2 decimals (`route.py`, `editor.js`,
   `editor.html`, `RUNBOOK.md`, `test_route.py`). Uncommitted. So `git status --short` is no longer
   empty from this point. Route `route-itg-02` rev 1 still parses. `test_route.py` and `run_all.py`
   pass. Not yet exercised in a browser or driven: arcs under 45° have never run on the vehicle.
7. `~/.amr/logs/events.jsonl` holds 2 lines that do not parse as JSON. Not investigated; anything
   reading that file line by line has to tolerate them.
8. `route-itg-02` rev 2 was built from rev 1 on the owner's request: north half moved 0.2 m north,
   and the last leg is now the home step, which is also what test 2.5 asks for. Geometry was
   checked against rev 1 and with the map validator. Its mission,
   `kyb-map-02_rev3_route-itg-02_rev2`, was created at 09:58 on the owner's request, so the ITG
   button now loads rev 2. Not driven yet. 4B as written names rev 1, whose mission still exists.
