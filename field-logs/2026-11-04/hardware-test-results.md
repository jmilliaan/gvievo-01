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
| Retest on `28fd613` | Pass | Service up 10:40:13. pytest 997 passed, 19 skipped, 6 xfailed (now including `amr_web`); `run_all.py` 731 checks; `test_alarms.py` 5 passed, domain 89 | |
| 4B.1 on `28fd613` | Pass | All values as in the updated document: `a_max` 0.1, `d_max` 0.125, `auto_jerk` 0.1, `taper_decel` 0.125, `taper_jerk` 0.1, `approach_velocity_scaling_dist` 3.4; also `desired_linear_vel` 0.72 | 20261104-104146 |
| First run, rev 2 by ITG button | Stopped by localization, see note 9 | 10:37:36 start, 10:37:45 `LOC_JUMP` 0.16 m / 0.0° (limit 0.15 m), run FAULT at 10 s, peak cross-track 0.02 m. Not recorded | |

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
   button now loads rev 2. 4B as written names rev 1, whose mission still exists; runs started
   with the ITG button are on rev 2, which is a deviation from the document.
9. The 10:37 stop has no recording, so its cause is unproven. Before the next run, at 10:43,
   `cov_xx` read 3.3e-08 m² after AMCL had been sitting still doing no-motion updates, against
   about 3e-04 m² just after the jump. To check in the 20261104-104146 bag: whether a collapsed
   particle cloud at rest makes corrections arrive as steps once the vehicle moves.
10. The 10:47 stop was not localization: kernel log shows `enp3s0` (GLS621) link down 10:46:14 and
    `enp2s0` (nanoScan3) link down 10:47:19, back at 10:47:38 and 10:47:32. `stale: scan` was still
    reported at 10:49:45. Cause of the link loss not found.
    The 10:58 stop (run stamp 20261104-104146) was `LOC_SCAN_MISMATCH`, 21 % at the s12 U-turn. The
    operator reports the trolleys moved since the survey. Offline, on the live scan at that spot:
    `scan_long` 0.184 without and 0.053 with the operator's dynamic areas. Map rev 4 (rev 3 plus those
    areas, same `map.pgm`), `route-itg-02` rev 3 (same geometry as rev 2) and mission
    `kyb-map-02_rev4_route-itg-02_rev3` were created 11:11. Not driven yet.
11. `bag_report.py`'s "map->odom shift" is inflated far from the odom origin: a 1.9° heading
    correction read as 4.56 m at about 136 m out, while the jump monitor, which measures at the
    vehicle, read 0. Compare its p95 with care.
12. Run page banner `WEB_BUG /run: The operation was aborted.` / `signal is aborted without reason`
    at 10:41:44, 10:41:56, 10:43:00 and 10:43:45, from `amr.js`'s 8 s request timeout. No run was
    active and no drive or run event came with them. Which request timed out is not logged. Likely
    the route preview: `GET .../routes/route-itg-02/<rev>` took 3.5 s at load average 8, re-runs the
    clearance check on every fetch, the page repeats it, and two browsers were open. `loadMissions`
    has no catch, so a timeout surfaces as a page error. Offline tests were running 10:41:46–10:42:56
    and added load, but the 10:41:44 and 10:43:45 errors fall outside the time their requests were
    open. Also: the Run page's mission list defaults to the first entry (rev 1), while the ITG
    button loads rev 2.
13. Run on `kyb-map-02_rev4_route-itg-02_rev3` (recorder stamp 20261104-111942) faulted at 11:46:45
    after 313 s: `EXEC_OFF_PATH`, cross-track +0.10 m at 4.54 m along the s8 arc. Localization stayed
    READY. A one-off route, `route-itg-02-salvage` rev 1, was built at 11:51 from the stopped pose: a
    tangent arc ccw 30.74° R 5.306 m onto the s10 line, then the rest of rev 3, ending on a straight
    instead of the home step. Validated on map rev 4. Cause of the drift not analysed yet.
14. First salvage run faulted at 11:53:30: `EXEC_OFF_PATH`, cross-track +0.20 m at 0.68 m along s1,
    about 6 s after moving. The operator reports heavy wheel slip and does not trust the encoders. A
    second salvage revision was built from that stop.
15. `route-itg-02` rev 4 (owner's drawing, 11:59): inbound s8/s9 bulge replaced by one 90° cw arc at
    R 1.8 m onto the release line. Mission `kyb-map-02_rev4_route-itg-02_rev4`; the ITG button loads it
    on map rev 4. The return leg from the release stop on is unchanged. Not driven yet.
16. Rejected Resets explained for 11:39–11:40 (recording 20261104-111942): `protective_clear` went False
    at 11:39:48.62 and the drives dropped to Switch on disabled in the same sample. All Reset presses
    failed while the field stayed occupied, whatever their length (0.20–3.80 s). The field cleared at
    11:40:35.82 and the drives left STO at 11:40:35.83, with no press in the 4 s before. For comparison,
    10:49:30 (recording 20261104-104146): field clear, a 0.20 s press worked at once. This replaces the
    press-length suspicion from earlier in the session. The 09:16 and 10:19 failures were not recorded,
    so they are unconfirmed.
17. `route-itg-02` rev 5 (owner's drawing): rev 4 with the north half moved a further 0.2 m (0.4 m from
    rev 1) and the R 1.8 m entry kept. Mission `kyb-map-02_rev4_route-itg-02_rev5`; the ITG button loads
    it on map rev 4. Not driven yet.
18. The 11:59:41 `EXEC_ENDPOINT_MISSED` (0.009 m / 9.9°) tripped the 8° `verify_heading_deg` limit. RPP's 0.8 m
    look-ahead cut the R 1 m S-bend, and the vehicle reached the stop still turning back onto the 0.4 m final
    straight. The slow stretch before it follows `approach_velocity_scaling_dist` 3.4 m applied to the 0.30 m/s
    arc limit: 0.097 m/s at 1.07 m from the stop against 0.094 predicted.
    `route-itg-02` rev 6 (owner's choice): S-bend moved 0.8 m east, attach stop fixed, final straight 1.2 m, upper
    straight 3.4 m. Mission `kyb-map-02_rev4_route-itg-02_rev6`. Not driven yet.
