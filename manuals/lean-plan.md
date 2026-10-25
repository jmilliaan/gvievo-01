# Lean plan — redundancy consolidation (2026-10-25)

Source: multi-agent sweep of the working tree (10 subsystem readers, 4 cross-cutting hunters, dedupe, per-item refute + plan). 

## 1. Summary

**Counts**

| Metric | Value |
|---|---|
| Candidates | 173 |
| Planned | 161 |
| Rejected | 12 |
| Unverified | 0 |
| Estimated lines removed (planned) | **3,602** |

**Per phase**

| Phase | Items | Est. lines removed |
|---|---|---|
| P0 | 19 | 472 |
| P1 | 79 | 1,315 |
| P2 | 16 | 520 |
| P3 | 47 | 1,295 |
| **Total** | **161** | **3,602** |

- Line counts are per-item estimates. The large ones (D03, D21, D47, D02) carry most of the total.
- Nine items remove 0 lines (D26, D88, D92, D127, D137, D164, D165, D166, D171). They are drift fixes, relocations or cross-checks, not deletions.

**Top 8 by payoff** (lines removed, weighted by the silent drift each one ends)

| # | Id | Phase | Lines | Why it pays |
|---|---|---|---|---|
| 1 | D07 | P1 | 100 | One QoS module replaces 49 definitions in 26 files. Drift between copies is silent today because LeanNode suppresses incompatible-QoS logs. |
| 2 | D04 | P1 | 70 | One wire-enum table set in amr_base. Today there are 4 MODE copies, demo is missing STOPPING/LINE, and panel_io/readiness hold bare ints. No contract test exists. |
| 3 | D02 | P1 | 150 | Removes profile keys that are validated but never read (dry_run, use_rpdo, the IMU/monitor/telemetry periods, manual_watchdog_s). Today they contradict the ROS params that actually rule. |
| 4 | D06 | P1 | 60 | demo_server fakes adapter state and mode rules. It has already drifted: wrong line_mission arity, no emit, and DI names that disagree with the profile. |
| 5 | D03 | P3 | 250 | One sim launch-test harness instead of four near-identical conftests and copied _yaw/_call. It also fixes fault_injection's ROS_DOMAIN_ID 69, which is outside TEST_RANGE. |
| 6 | D47 | P0 | 227 | Deletes the fully superseded 0910-fix-plan-001.md. Nothing links to it. |
| 7 | D21 | P3 | 220 | Retires the T-log in amr_ws/README.md, which names removed code. Keeps the TF tree, geometry and wire/rate table. |
| 8 | D05 | P3 | 130 | One amr_web adapter stub and a corrected Protocol replace 5 hand-rolled stubs, a stale Protocol and 11 hasattr guards. |

**Main redundancy patterns**

- **Wire vocabulary has no single home.** Each node or page re-declares enum names, lease bits, QoS, topic names, the source strings 'tpdo'/'sdo' and the hold causes, kept in sync only by comments.
  - Items: D04, D07, D46, D61, D137, D167, D142, D157, D158, D159.
- **Config is declared twice.** Profile keys sit beside ROS param defaults that nothing overrides, and launch literals restate the gating defaults. Whichever copy wins at runtime goes unnoticed.
  - Items: D02, D23, D35, D110, D111, D165, D166, D24.
- **Node boilerplate is rewritten for every new node.** This covers main() spin/shutdown, Event builders, the lease replay filter, TF lookup to pose, the _ui throttle and the DriveStatus predicates.
  - Items: D10, D14, D22, D71, D100, D30, D101.
- **Small pure algorithms are rebuilt from scratch in each session.** Examples: angle wrap and quaternion-to-yaw, the int32 counter delta, rad/s per motor rpm, decel feasibility, dilation, interpolation, arc pose and s16.
  - Items: D20, D33, D34, D58, D75, D76, D106, D113, D115, D147.
- **Storage primitives are re-implemented per store.** This covers lock, fsync, sha, publish, atomic JSON, rotation, mask and manifest loaders, and store layout.
  - Items: D17, D29, D38, D39, D68, D87, D123.
- **Bench scripts quietly became the CAN library.** Production imports from verify_drivers and drive_forward, there are two SDO clients, two preflight/enable sequences, and guard.py is bypassed in places.
  - Items: D18, D28, D41, D42, D43, D44, D80.
- **Migrations were left half-done, so two engines run side by side.** Examples: TripRoute vs Route, Shadow vs SiteRun, the legacy horn, the events ring, three alarm pollers, the dead survey clients and the at_home predicate.
  - Items: D08, D12, D13, D16, D45, D59, D63, D67, D144.
- **Fakes drift from the real code.** demo_server, fake_panel, tape_synth and fake_base reproduce real logic and have diverged.
  - Items: D06, D95, D114, D33, D34.
- **Every test file builds its own harness.** This covers conftests, sys.path bootstraps, Log/Clock fakes, gating fixtures, FakeLink and JS DOM harnesses.
  - Items: D03, D05, D09, D19, D27, D65, D66, D84.
- **Page JS is copy-pasted.** This covers `$`, poll loops, POST-and-report handlers, freshness and status text, and Python constants mirrored into JS.
  - Items: D60, D62, D64, D109, D130, D141, D148, D155, D156.
- **Docs are used as logs.** Decision logs, superseded plans, links into manuals/obsolete and stale facts (check count, auto_rpm, the "boots to IDLE" claim).
  - Items: D21, D47, D48, D49, D50, D88, D89, D90, D91.

## 2. Ground rules
- Behavior-preserving: no feature removed; wire values, msg fields and profile keys change only with a migration.
- Both products stay first-class (LINE tape AGV, SLAM AMR).
- Bench tools in `agv_core/drivers/canbus` stay, but share decoders/helpers with the ROS nodes instead of owning copies.
- Web demo stays, but reuses `server.py` routes instead of a parallel fake server.
- Protected: `autopilot.py`/`branch.py` (verbatim port), `agv_core` stays ROS/Flask-free, `drive_node.py` sole can0 owner, `guard.py` deny-list, `gating.py` pure/clock-fed, `mode_fsm` constants are wire values.
- Changes to `gating.py`, `cmd_mux_kinematics_node.py`, `scanner_fields.*`, `guard.py` carry a test and a stated failure mode + recovery.
- Verification per item: focused pytest on affected files; `ruff` (root for agv_core, `amr_ws/` for src); `colcon build` only where marked; `tests/run_all.py` EXPECTED_CHECKS updated deliberately.

## 3. Phases

### P0 — Dead code & orphans

19 items, about 472 lines. None of them depends on another item, so they are ordered by payoff and grouped so each test run or `colcon build` happens once. No item touches `gating.py`, `cmd_mux_kinematics_node.py`, `scanner_fields.*` or `guard.py`. D139 and D103 deliberately leave `guard.py` and `scanner_fields.reach_m` alone. D121 and D161 are the only items that need `colcon build`; do them last, in one build.

**Docs & deploy**

**D47 — 0910-fix-plan-001.md is fully superseded** (low / S / ~227 lines / build no)
- Keep: `manuals/obsolete/0910-fix-plan-001.md` (historical) · Remove: `0910-fix-plan-001.md` (repo root)
- Steps: 1. `git mv` it into `manuals/obsolete/` (you commit). 2. Optional status line: "B4 moot: markers_enabled retired 2026-10-23".
- Tests: none
- Depends: none

**D52 — amr-launch.sh is an unused legacy-unit wrapper; PYTHONPATH is injected three times** (low / S / ~35 lines / build no)
- Keep: `amr_ws/env/vehicle.sh:11` as the only PYTHONPATH injection, changed to honour `${AGV_CAN_ROOT:-$HOME/agv_can}`; `amr-supervisor.sh` unchanged · Remove: `amr_ws/deploy/amr-launch.sh`; the references to it at `validate.sh:11,18`
- Steps: 1. You confirm the legacy-unit rollback window is closed. 2. Make `vehicle.sh` use `${AGV_CAN_ROOT:-$HOME/agv_can}`. 3. Delete `amr-launch.sh`, drop it from the `validate.sh` lists and reword `validate.sh:45-54` to cite `vehicle.sh`. 4. Update `README.md:143`, `amr_ws/README.md:101,391-393`, `alpha-setup.md:664,711`, `vehicle.sh:10` and `amr_line/package.xml:22`.
- Tests: `bash -n validate.sh`; no Python test impact
- Failure / recovery: if someone still runs `ros2 launch` through `amr-launch.sh` by hand, they source `env/vehicle.sh` first or restore the file from git.
- Depends: your sign-off on the rollback window (step 1)

**agv_core library and offline suite** (`tests/run_all.py` once at the end; only D57 changes `EXPECTED_CHECKS`)

**D56 — tests/helpers.py `_FakeRaw` SDO fake bus has no users** (low / S / ~55 lines / build no)
- Keep: `tests/helpers.py` `check()`/`FAIL`/`ROOT`; `test_canopen.py` `FakeBus` · Remove: `tests/helpers.py:53-105` `_FakeRaw`, `:20` `import struct`
- Steps: 1. Delete the class and the import. 2. Run `ruff check .` and `python3 tests/run_all.py`.
- Tests: no checks removed; `EXPECTED_CHECKS` unchanged
- Depends: none

**D57 — `alarms.decode_statusword_flags` / `SW_FLAGS` have had no caller since U11** (low / S / ~36 lines / build no)
- Keep: `alarms.decode_nmt`, `EMCY_CODES`; `bus_health.decode_state` for the CiA 402 state · Remove: `agv_core/drivers/canbus/alarms.py:124-151` (comment block, `SW_FLAGS`, `decode_statusword_flags`); `tests/test_canmon.py:47-53` (3 checks)
- Steps: 1. Delete the function, the table and the comment. Keep the bit-5 QS note only if `decode_state` lacks it. 2. Delete the 3 checks in `test_canmon`. 3. `EXPECTED_CHECKS` −3, with a dated comment. Restore from git if ILA (bit 5, quick stop active) is ever wanted for stop explanation.
- Tests: `python3 tests/run_all.py` with `EXPECTED_CHECKS` −3
- Depends: none

**D99 — `ownerlock.holder()` and unused resources `'app'`/`'scanner'`** (low / S / ~18 lines / build no)
- Keep: `ownerlock.acquire(resource, who)`, `OwnerLock` with `RESOURCES=('can','dio','rfid')`; `OwnerBusy` still names the holder · Remove: `agv_core/ownerlock.py:28` `'app'`/`'scanner'`, `:86-101` `holder()`, and the `:18` docstring mention of the legacy controller
- Steps: 1. Set `RESOURCES` to `('can','dio','rfid')`. 2. Delete `holder()`. 3. In `test_ownerlock.py`, replace the `holder()` asserts with acquire-expects-`OwnerBusy` (already at `:20`) and acquire-succeeds-after-release (already at `:26`). 4. Run the focused tests.
- Tests: `pytest -q amr_ws/src/amr_base/test/test_ownerlock.py tests/test_lss.py tests/test_rfid.py`; re-run `run_all.py` to confirm `EXPECTED_CHECKS` (no change expected)
- Behaviour: `acquire('app')` and `acquire('scanner')` now raise `ValueError`; nothing calls them
- Depends: none

**D82 — `RfidLink.snapshot` fields with no consumer** (low / S / ~12 lines / build no)
- Keep: the `snapshot()` fields `rfid_node` reads (generation, comms_ok, rx_age_s, tag_age_s, rssi_dbm, channel, freq_mhz, reader, config_mismatch, encounters, passes, encounter_seq); `identity` stays, through `reader` or a separate accessor if a test needs it; `rfid.tag_hold_s`/`silent_warn_s` stay in the schema and profile · Remove: `agv_core/drivers/rfid.py:469-490` unread fields (tag/live hold computation, silent, last_tag, tags_seen, epc, antenna, heartbeat, bad_frames, detail, carrier)
- Steps: 1. Retarget the `test_rfid` asserts on dropped fields to internal state or accessors (tags_seen counter, identity). 2. Remove the fields from `snapshot()`. 3. Leave `RFID_TAG_HOLD_S`/`RFID_SILENT_WARN_S` loaded but annotated "no reader"; retiring them, with refusal tests, is a follow-up. 4. Change `EXPECTED_CHECKS` only if a check is dropped rather than retargeted.
- Tests: `python3 tests/run_all.py` (`test_rfid` retargeted; aim for an unchanged count)
- Behaviour: none; the `StationDetection` msg is unchanged
- Depends: none

**D125 — unreachable bool-return branch in `rpdo.configure`; stale canworker/tune_mls/motion.py references** (low / S / ~5 lines / build no)
- Keep: `rpdo.configure(bus, node, sdo_write)` with the documented contract `sdo_write -> (ok: bool, detail: str)` · Remove: `agv_core/drivers/canbus/rpdo.py:208-213` isinstance/else branch, which becomes `ok, detail = sdo_write(...)`
- Steps: 1. Unpack the tuple directly and state the contract in the docstring. 2. Repoint the bench-facing docstrings only (`rpdo.py:34,196`, `verify_drivers.py:36,144`, `read_imu.py:5`, `drive_forward.py:233`): canworker → `amr_base.canopen.DriveLink`; `core/health.py` → drive_node feedback freshness/heartbeat; `tune_mls.py` → `read_mls.py --go`; `motion.py` → kinematics/config invert flags. Leave the "port of canworker" provenance notes elsewhere. 3. Run the tests.
- Tests: `python3 -m pytest -q tests/test_rpdo.py amr_ws/src/amr_base/test/test_canopen.py`; `run_all.py` count unchanged
- Behaviour: none today; a future bare-bool `sdo_write` raises `TypeError` instead of being accepted. `guard.py` is not touched, and RPDO writes still go through it.
- Depends: none

**D138 — catalogue code `EXEC_ROUTE_INVALID` is never emitted** (low / S / ~4 lines / build no)
- Keep: the rest of the catalogue; the RunMission reply stays the refusal channel · Remove: `agv_core/alarms.py:260-262` row; `amr_ws/RUNBOOK.md:717` row (by regeneration)
- Steps: 1. Delete the catalogue row. 2. Run `python3 -m agv_core.alarms --md` and paste the output into RUNBOOK §4 between the BEGIN/END GENERATED markers. 3. Re-grep web/JS for the code (it had none).
- Tests: `python3 -m pytest -q tests/test_alarms.py` (pins RUNBOOK agreement); check `EXPECTED_CHECKS` if `test_alarms` counts per-code checks
- Depends: none

**D154 — `blindrun.RESULTS_KEPT` unused** (low / S / ~2 lines / build no)
- Keep: `BlindRun.results` behaviour unchanged · Remove: `agv_core/blindrun.py:29-30` (constant plus a comment describing a cap that is not enforced)
- Steps: 1. Delete both lines. 2. `ruff check .` from the repo root.
- Tests: `python3 tests/run_all.py` (no count change)
- Depends: none

**amr_ws Python, no build needed** (symlinked; `cd amr_ws && ruff check src/` once at the end)

**D67 — web adapter's direct coordinator survey clients are dead behind the supervisor** (low / S / ~23 lines / build no)
- Keep: `adapter.survey_request` (RequestSurvey via the supervisor), `survey_move`, `survey_move_stop`; `mapping_session_node` services and the `mapping_layer` `internal:=` arg (standalone diagnostics); the supervisor's internal clients; `mode_fsm` `REQ_SURVEY_*` wire strings · Remove: `amr_web/adapter.py:60` `SaveMap` and `:62` `StartSurvey` imports, `:366-369` the four `_srv` clients, `:993-1005` `survey_start`/`survey_returned`/`survey_save`/`survey_abort`; `amr_web/server.py:53-56` Protocol stubs
- Steps: 1. Delete the four methods and their `_srv` entries. 2. Drop the `StartSurvey`/`SaveMap` imports if nothing else uses them; keep `Trigger`. 3. Delete the four Protocol lines. 4. Run ruff and the web tests.
- Tests: `pytest amr_web/test/test_server.py` plus any adapter import smoke test; no `EXPECTED_CHECKS` impact
- Behaviour: the web node creates four fewer service clients; no code called them
- Depends: none

**D83 — `DriveLink.arm()` is test-only** (low / S / ~12 lines / build no)
- Keep: a new `_arm(link, *args)` helper in `test_canopen.py`, next to `_link` (`:198`): `prepare`, then `engage`, and `disarm(force=True)` plus re-raise on failure. r04/r05/r07 import it the same way they import `FakeBus`/`_link`. · Remove: `amr_ws/src/amr_base/amr_base/canopen.py:607-623` `DriveLink.arm`
- Steps: 1. Add `_arm()`. 2. Replace `link.arm(...)` with `_arm(link, ...)` in `test_canopen`, `test_r04`, `test_r05`, `test_r07`. 3. Delete `DriveLink.arm`. 4. Run the four test files.
- Tests: `pytest -q amr_ws/src/amr_base/test/test_canopen.py test_r04_fault_stop.py test_r05_arm_rollback.py test_r07_feedback_freshness.py`; check count unchanged (not in `run_all.py`)
- Note: the R05 rollback tests keep exercising a composite that production never runs. `drive_node` uses `prepare()`/`engage()`, and an engage failure is retried, not force-disarmed.
- Depends: none

**D126 — square_drive `closing_error_m`/`deg` declared but never applied** (partial: the params are inert, but `test_survey_sim` sets them, so remove both sides) (low / S / ~9 lines / build no)
- Keep: square_drive plan from side_a/side_b/speed/turn/settle; `test_survey_sim` gets its return error from wheel slip · Remove: `amr_sim/square_drive.py:32-36` comment and two `declare_parameter`; `amr_mission/test/test_survey_sim.py:57,85-86` `CLOSING_ERROR_*` constants and launch params
- Steps: 1. Delete the declares and their comment. 2. Remove the constants and params from `test_survey_sim`, and correct its docstring (`:3-4`) to say the error comes from the 2 % slip. 3. A unit import check is enough now.
- Tests: `test_survey_sim` is opt-in; run it once at the next milestone sim pass (`truth_err > 0.05` at `:200` is already met by slip alone). No `EXPECTED_CHECKS` impact.
- Depends: none

**D112 — unused functions in the tape-localization core** (partial: `Route.stop` survives, because plan-4 tests use it) (low / S / ~7 lines / build no)
- Keep: `tape_graph.compile_route(circuit_id, circuit, graph)`, `Route.stop(ident)` · Remove: `amr_line/tape_locator.py:390-392` `route_for`; `amr_line/tape_graph.py:386-389` `lateral_to`
- Steps: 1. Delete both functions. 2. Let ruff flag any `math`/`tg` imports that are now unused. 3. Run the tests.
- Tests: `pytest -q amr_ws/src/amr_line/test/test_tape_localization.py test_trip_route.py test_site_run.py test_tape_runtime.py`; `cd amr_ws && ruff check src/amr_line`. These files have uncommitted edits, so land this after the current tape work settles.
- Depends: none

**D103 — unused members in supervisor / operations / process_supervisor** (partial: `Book.recent()` and `scanner_fields.reach_m` survive) (low / S / ~5 lines / build no)
- Keep: `operations.Book.recent()` (test seam for the bound, `test_mode_fsm.py:80`); `scanner_fields.reach_m` (documented API, cross-checked against `/field_data`); `ALLOWED_MODULES=('amr_web.web_node',)` · Remove: `supervisor_node.py:232-234` `lm_loc_active` client; `operations.py:26` `STATUS_NAMES`; `process_supervisor.py:32` `'amr_bringup.supervisor_node'` entry
- Steps: 1. Delete the `lm_loc_active` client entry. 2. Delete `STATUS_NAMES`, or fold it into the D04 wire table if D04 lands first. 3. Drop `supervisor_node` from `ALLOWED_MODULES`. 4. Run the tests.
- Tests: `pytest -q amr_ws/src/amr_bringup/test/test_process_supervisor.py test_mode_fsm.py test_logs.py`; no `EXPECTED_CHECKS` impact
- Behaviour: one fewer idle service client on the supervisor. `scanner_fields` is not touched.
- Depends: none hard; soft ordering with D04 for `STATUS_NAMES`

**D133 — dead Home CSS/JS** (low / S / ~5 lines / build no)
- Keep: one 3-column `.home-live` grid (`repeat(3,minmax(0,1fr))`, gap `.8rem`), with class `three` kept in the markup so `test_operator_ux.py:695` still passes; `@media` rule at `:645` simplified to `.home-live` · Remove: `amr.css:572-573` `.home-big.warn/.error` (never match, since the LV map emits `lv-*`); `amr.css:577-579` base 2-column rule and comment; `home.html:145` `live-marker` guard (always true; dedent the body)
- Steps: 1. Delete `.home-big.warn/.error`. 2. Make `.home-live` the 3-column grid and drop the `.three` override. 3. Simplify the `@media` selector. 4. Remove the guard.
- Tests: `python3 -m pytest -q amr_ws/src/amr_web/test/test_operator_ux.py`; visual check of Home at UI scale `l` (1280×720)
- Depends: none

**D122 — junction slow-zone path unreachable since `slow_speed` was retired** (low / S / ~4 lines / build no)
- Keep: `LineState.msg:50` `slow_zone` wire field; `job.py:1262` publishes literal `False` with a "retired 2026-10-09" comment; `branch.py` untouched (protected verbatim port) · Remove: `amr_line/tape_run.py:656` `was_slow` capture; `:665-666` slow-zone event branch
- Steps: 1. Drop `was_slow` and the event branch in `TapeRun._branch_scan`. 2. Replace `bool(t.branch.slow)` with `False` in `job.py`, with the comment. 3. Update the `tape_run.py:595` docstring if needed. 4. Run the tests.
- Tests: `pytest -q amr_ws/src/amr_line/test/test_tape_runtime.py test_site_run.py` plus any test asserting LineState fields; the `tests/test_mission.py:148` refusal stays; no `EXPECTED_CHECKS` change
- Behaviour: none; both values were already constant `False`
- Depends: none

**D139 — `runtime.snapshot()` has no production caller** (partial: only `runtime.snapshot()` is removed; `is_loaded`, `cell_to_world`, the protocol constants and the guard query API stay) (low / S / ~4 lines / build no)
- Keep: `runtime.is_loaded` (harness), `grid.cell_to_world`, rfid/imu protocol constants, `guard.is_allowed`/`is_sensor_allowed` (`guard.py` not touched) · Remove: `amr_line/runtime.py:146-148` `snapshot()`
- Steps: 1. Delete it. 2. Re-grep `config.snapshot` / `runtime.snapshot` to confirm there are no callers.
- Tests: `python3 -m pytest -q amr_ws/src/amr_line/test/test_control.py amr_ws/src/amr_line/test/test_track_reader.py`
- Depends: none

**Needs colcon build** (do last, in one build, then re-source)

**D121 — `SafetyFieldStatus.msg` is generated but never used** (low / S / ~8 lines / build yes)
- Keep: `/output_paths` (sick_safetyscanners2) as the only field-status source · Remove: `amr_interfaces/msg/SafetyFieldStatus.msg`; `amr_interfaces/CMakeLists.txt:14`
- Steps: 1. Delete the `.msg` and its CMake entry. 2. `colcon build --symlink-install` for `amr_interfaces` and dependants. 3. Re-source and run the import smoke tests.
- Tests: after the build, `pytest -q` on any `amr_interfaces`/adapter import test; no `EXPECTED_CHECKS` impact
- Behaviour: none; the type was never on the wire, and the software read path from `/output_paths` is unchanged
- Depends: none (batch with D161)

**D161 — entry point `amr_bringup` `amr_supervisor` has no caller** (low / S / ~1 line / build yes)
- Keep: `python3 -m amr_bringup.supervisor_node` (the systemd path via `amr-supervisor.sh`, also used by `test_fault_injection_sim.py:49`) · Remove: `amr_bringup/setup.py:26` console_scripts entry
- Steps: 1. Remove the entry. 2. `colcon build amr_bringup`. A clean build drops the stale `install/lib/amr_bringup/amr_supervisor` wrapper.
- Tests: `python3 -m pytest -q amr_ws/src/amr_bringup/test/test_launch_layers.py`
- Behaviour: `ros2 run amr_bringup amr_supervisor` no longer exists; no deploy or doc path uses it
- Depends: none (batch with D121)
### P1 — Single sources of truth

Items are in dependency order, then by payoff. None of them needs `colcon build`. Some depend on IDs outside this list (D01, D11, D16, D51, D61); those are marked *(outside P1 list)*. D07 and D10 depend on each other, so land them as one change.

---

**Group A: Profile and config as the only source**

**D02 — Retire profile keys that are validated but never read** (low / M / ~150 lines / build no)
- Keep: the ROS params in `drive_node` (`cmd_timeout_s`, `imu_poll_hz`, `monitor_period_*`). `tape_loc.lost_fault_s` stays in `_SCHEMA`/profile, and the docstring at `config.py:354` is marked "reserved, not read yet". `driver_timeout_s` keeps its own validation.
- Remove: `config.py:442 dry_run`, `:604 use_rpdo`, `:608 monitor.poll_period_s`, `:650-651` imu periods, `:672-673 telemetry_period_s/manual_watchdog_s`. Also the cross-checks at `:1039-1048,1066-1067,1179-1186` (keep `driver_timeout_s>0` vs heartbeat), the TUNING NOTES at `:78-120,164-187`, the matching lines in `profiles/agv-01.json` (`:5,180,250,251` plus monitor/imu periods), the banner field at `tests/run_all.py:122` and the legacy check at `tests/test_rpdo.py:238-240`.
- Steps:
  1. Drop the 7 keys from `_SCHEMA` and their cross-checks. The strict schema then refuses any leftover as "unknown key".
  2. Migrate `agv-01.json` in the same change.
  3. Point the R16 non-finite tests (`test_config.py:146-169`) at `timing.driver_timeout_s`. Drop the describe checks at `:178-179,447-448,477,485-486`.
  4. Add one "leftover `<key>` is refused" check per key, following the pattern at `test_config.py:316-329`.
  5. Trim the TUNING NOTES and mark `lost_fault_s` reserved.
- Tests: `python3 tests/run_all.py`. `EXPECTED_CHECKS` net change is +7 refusals, -1 rpdo legacy check, -2 to -4 describe rows; put the exact delta and the date in a comment. Sanity run: `pytest -q amr_ws/src/amr_line/test/test_runtime*`.
- Note: the Params page loses 7 rows that showed values nothing obeyed (`manual_watchdog_s` showed 0.6 while 0.2 s is what applies). An out-of-tree profile that still has a retired key will fail to start `amr.service`. The error names the key: delete it and restart.
- Depends: —

**D70 — Remove the leftover speed-section code in `describe()`** (low / S / ~20 lines / build no)
- Keep: the `speed` section with its two rows and labels (Params page layout unchanged). · Remove: `config.py:1485-1488 _MOVED` and its uses, the dead drivers-ramp loop at `:1566-1573`, and the manual wording at `:1546-1551` and `:1616-1618`.
- Steps:
  1. Drop `_MOVED`; the section loop filters nothing.
  2. Delete the drivers-ramp append loop.
  3. Rewrite the note: 6083h/6084h ramp for AUTO, also the yaw-accel ceiling.
- Tests: `run_all` count unchanged; check that `test_config.py:406,488` still find `drivers.ramp.auto.accel`.
- Depends: D01 *(outside P1 list)*, D02

**D110 — `drive_node` reads profile values directly, not through never-overridden ROS params** (low / S / ~5 lines / build no)
- Keep: `config.LOOP_PERIOD_S`, `DRIVER_TIMEOUT_S`, `IMU_ENABLED`, `MLS_VARIANT`, `MONITOR_ENABLED`, plus the ROS-only params (`feedback_hz`, `pc_loss_ms`, `gyro_sign`, `monitor_period_*`, `imu_poll_hz`). · Remove: the `declare_parameter` lines at `drive_node.py:133,136,145,155,160`.
- Steps:
  1. Replace `p('rate_hz')` and the other four reads with the config constants.
  2. Delete the five declare lines.
  3. Update the notes at `mls-marker-plan.md:146/367`.
- Tests: focused `drive_node` tests (`test_marker_events`, `test_canopen`).
- Note: a manual `--ros-args` override of these five no longer works; the profile is the only source.
- Depends: —

**D111 — Auto-resume default comes from the profile** (low / S / ~1 line / build no)
- Keep: `autopilot.auto_resume_hold_s` → `config.AUTO_RESUME_HOLD_S`. `line_follow` keeps its -1 sentinel and `FollowJob` keeps its kwarg default. · Remove: the literal 2.0 at `route_executor_node.py:208`.
- Steps:
  1. Set the default to `float(vehicle_config.AUTO_RESUME_HOLD_S)`.
  2. Fix the note at `RUNBOOK.md:519`.
  3. Optional: add a source assert in `test_auto_resume.py`, mirroring `test_track_reader.py:92`.
- Tests: `pytest -q src/amr_mission/test/test_auto_resume.py src/amr_line/test/test_track_reader.py`.
- Depends: —

**D94 — One int-list reader in `config.py`** (low / S / ~12 lines / build no)
- Keep: `_int_list(raw, where, *, what, distinct_msg, lo, hi, length=None, nonempty=False, sort=True)`. The three readers become thin wrappers that keep their error texts. · Remove: the repeated isinstance/duplicate/range blocks in `_read_do_list`, `_read_zone_bytes` and `_read_marker_codes`, and the unreachable `.get` fallback at `:913`.
- Steps:
  1. Add `_int_list` with per-caller message strings.
  2. Rebuild the three readers on it (`zone_bytes`: `length=3`, unsorted).
  3. Read `doc['dio']['movement_horn']` directly.
- Tests: `run_all` count unchanged (`'listed twice'` is pinned at `test_config.py:257-258`). Optional `marker_codes` refusals would raise `EXPECTED_CHECKS`.
- Depends: —

**D145 — `config.product()`** (low / S / ~2 lines / build no)
- Keep: `config.product(tracked=TRACKED) -> 'tape'|'slam'|'both'` (not a profile key, so no schema change). · Remove: the dict literals at `supervisor_node.py:381` and `server.py:215`.
- Steps:
  1. Add the helper.
  2. Use it at both sites; `server._product` keeps its try/except.
- Tests: `test_config.py` +1 check for True/False/None (bump `EXPECTED_CHECKS`); amr_web product tests.
- Depends: —

**D160 — `drive_node` uses `config.NODES`** (low / S / ~1 line / build no)
- Keep: `config.NODES`. · Remove: the literal at `drive_node.py:187`, replaced by `dict(config.NODES)`.
- Tests: `amr_base` drive_node/canopen tests.
- Depends: —

---

**Group B: Wire vocabulary and protocol constants**

**D04 — Pure wire-enum table module** (low / M / ~70 lines / build no)
- Keep: new `amr_base/wire.py` (no rclpy, no msg import) with the MODE, RUN, SURVEY/MAPPING, LOC, LINE, OP and COMMISSIONING name maps, plus `LINE_HELD=(1,2,3)`, `LINE_ACTIVE`, `RUN_ACTIVE`, `LOC_READY/LOC_LOST`. It re-exports `gating.NAMES` (mux) and `run_fsm.NAMES`. `mode_fsm.py` stays the authority for mode ints and is not edited.
- Remove: the name maps at `adapter.py:73-97`, `MODE_NAMES` at `commissioning_node.py:51-60`, the tables at `demo_server.py:70-73`, `LINE_STATES/MUX_SOURCES` at `bag_report.py:32,41-42`, `NAMES` at `test_unified_sim.py:49`, `S` at `test_run_control_sim.py:55-63`, `operations.STATUS_NAMES:26`, and the `MODE_*` literals at `server.py:44`.
- Steps:
  1. Create `wire.py` with each value copied once.
  2. Repoint adapter, server, demo_server, commissioning_node, bag_report, bringup readiness (`in (1,2,3)` → `LINE_HELD`), tape_runtime and the sim tests.
  3. `panel_io` keeps its ints or imports `wire`.
  4. Add a contract test.
  5. The `RunState.msg:6` comment fix waits for the next interface change (it would force an `amr_interfaces` rebuild).
- Tests:
  - New `amr_base/test/test_wire_contract.py`: every table equals the msg constants (ModeState, RunState, LineState, MuxState, LocalizationState, MappingState, OperationState, RequestSurvey), and `job.STATE_NAMES`, `run_fsm.NAMES`, `readiness.NAMES` and `mode_fsm.MODE_NAMES` equal `wire`.
  - `test_alarm_horn.py` pins `LINE_ACTIVE/RUN_ACTIVE/LINE_PREMOVE` against LineState/RunState.
  - Focused web, mode_fsm and gating tests. `EXPECTED_CHECKS` unchanged.
- Safety: `panel_io.py` (only a test, plus an optional import). Failure mode: a wrong value silences the alarm horn or mislabels UI/bag text. Recovery: the contract and horn pin tests fail at once; revert.
- Depends: —

**D46 — Lease bits from `gating.LEASE_*` only** (low / S / ~6 lines / build no)
- Keep: `gating.py:46 LEASE_*` (gating.py itself is not edited). `supervisor_node` imports from it, so `test_tracked_product` keeps working. · Remove: `commissioning.py:67`, `pp.py:394`, `survey_move_node.py:52`, `test_mission_engine.py:30`, `test_line_authority.py:24`, and the `&1/&4/&8` literals in `adapter.manual_allowed`.
- Steps:
  1. Turn the supervisor definition into an import.
  2. Repoint commissioning, pp, survey_move and the two line tests.
  3. Switch the adapter to the named bits.
- Tests: `test_gating.py` gets an equality test against `ControlLease.MANUAL/AUTONOMOUS/COMMISSIONING/LINE` (skipped if `amr_interfaces` is not importable). Also run test_line_mux, test_tracked_product, test_mission_engine, test_line_authority and the commissioning/adapter tests.
- Safety: `gating.py` only gains a test. Failure mode: a wrong bit denies motion (fail-closed). Recovery: the equality test catches it; revert the import.
- Depends: —

**D167 — `LineTrack.source` constants** (low / S / ~0 lines / build no)
- Keep: `SOURCE_TPDO='tpdo'` and `SOURCE_SDO='sdo'` in `mls_track.py`. No msg change. · Remove: the literals at `track.py:79`, `tape_health.py:50`, `marker_events.py:75`, `tape_synth_node.py:81`, and `mls_track.py:275,303`.
- Steps:
  1. Define the constants and use them in `MODES` and at `:275/303`.
  2. Repoint the four consumers.
- Tests: an `amr_base` test that asserts the wire values; focused track, tape_health, marker_events and mls_track tests.
- Note: this prevents a producer rename from silently turning off LINE acceptance (consumers gate on `!= 'tpdo'`).
- Depends: —

**D142 — NLCP constants from `branch.py`** (low / S / ~3 lines / build no)
- Keep: `branch.MULTI_NLCP/SINGLE_NLCP/CROSSING_NLCP` (protected port, imported read-only). · Remove: `tape_graph.py:394-395`, `tape_run.py:99` (becomes `MULTI_NLCP = branch.MULTI_NLCP`), the lazy import at `site_run.py:207`, and the literal `nlcp == 7` at `tape_graph.py:421`.
- Tests: `pytest -q test_tape_runtime.py test_site_run.py test_tape_localization.py`. Optional: assert `tape_graph.MULTI_NLCP is branch.MULTI_NLCP`.
- Depends: —

**D152 — `leg_id()` in `agv_core.mission`** (low / S / ~2 lines / build no)
- Keep: `mission.leg_id(frm, order, to)`; `tape_graph` imports and re-exports it. The persisted format is unchanged. · Remove: `tape_graph.py:45-46 def leg_id` and the inline f-strings at `mission.py:663,669`.
- Tests: test_trip_route, test_tape_runtime, test_site_run, and `run_all` (unchanged, or +1 if the optional check is added).
- Depends: —

**D151 — U-turn re-arm margin** (low / S / ~1 line / build no)
- Keep: public `mission.REARM_MARGIN_M = 1.0`; `uturn.REARM_MARGIN_M` aliases it. · Remove: the literal at `uturn.py:56`; rename `_REARM_MARGIN_M` and update its test references.
- Tests: `pytest -q tests/test_mission.py src/amr_line/test/test_tape_runtime.py`.
- Depends: —

**D158 — Repeat bound** (low / S / ~1 line / build no)
- Keep: `route.MAX_REPEAT`. `run_fsm` imports it as `MAX_PASSES`. · Remove: the literal at `run_fsm.py:25` and the sync comments at `route.py:45` and `test_route.py:442`.
- Tests: assert `MAX_PASSES == route.MAX_REPEAT`; run test_run_fsm and test_route.
- Depends: —

**D159 — `RUN_ACTIVE` set** (low / S / ~1 line / build no)
- Keep: `alarms.RUN_ACTIVE`. The 3-state set at `alarms.py:151` stays separate. · Remove: the tuple literals at `alarms.py:165` and `server.py:1195`.
- Tests: existing headline and restart tests.
- Depends: —

**D157 — MUST/SHOULD tiers** (low / S / ~1 line / build no)
- Keep: `drivers/canbus/alarms.py:23`. · Remove: `canmon.py:36`, replaced by an import.
- Tests: `ruff check .`, `run_all` unchanged.
- Depends: —

**D153 — Tape initial-pose covariance** (low / S / ~2 lines / build no)
- Keep: `tape_locator.INITIAL_POSE_SIGMA_XY_M=0.05`, `_YAW_RAD=0.03` (or `initial_pose_cov()`). · Remove: the literals at `line_follow_node.py:463-464` and `tape_loc.py:49-50` (`tape_loc` imports the new names lazily).
- Tests: assert `cov[0]==cov[7]==0.0025` and `cov[35]==0.0009`.
- Depends: —

**D74 — `marker_expectation` derived from `MARKER_SETTINGS`** (low / S / ~6 lines / build no)
- Keep: `read_mls.marker_expectation(polarity_lock, teach_lock)`, re-exported for `drive_node`. · Remove: the body at `drive_node.py:103-111`.
- Tests: `test_marker_events.py:84-91` becomes a direct unit test with the same assertions.
- Depends: —

**D116 — Track-over-SDO object list** (low / S / ~6 lines / build no)
- Keep: `read_mls.TRACK_SDO_ITEMS` and `decode_sdo_values(vals, combi)`; `mls_track.SDO_ITEMS` aliases the tuple. · Remove: the body at `mls_track.py:63-69` and the slicing at `:273,381`.
- Tests: mls_track and read_mls tests, plus an order check (bump `EXPECTED_CHECKS` if it goes in `tests/`).
- Depends: —

---

**Group C: Pure math helpers**

**D20 — `agv_core/se2.py`** (low / M / ~45 lines / build no)
- Keep: `wrap`, `compose`, `yaw_of` (full formula), `quat_zw` and `correction_at`. `survey_move.slam_correction` and `live.yaw_of` remain as aliases. `compiler`, `relocalize` and `tape_graph` keep their local `_wrap` (no new dependency edge; plan-4 freeze).
- Remove:
  - the wrap copies in diff_drive, mapping_session_node, survey_move and readiness (re-export where tests import them)
  - `readiness._apply` and the `on_map_odom` math
  - the yaw helpers in route_executor, localization_monitor, mapping_session, survey_move_node, scan_synth, `live.py`, `grid.py` (only if it already imports agv_core) and the sim tests
  - the inline wrap in demo_server
- Steps:
  1. Add `se2.py` and `tests/test_se2.py`.
  2. Point survey_move and readiness at it.
  3. Replace the yaw helpers (planar, so values are identical).
- Tests: `test_se2.py` in `run_all` covering wrap edges, compose vs old `_apply`, and yaw for z-only and full quaternions (bump `EXPECTED_CHECKS`). Also survey_move, readiness and live tests.
- Depends: —

**D71 — `amr_base/tfpose.py`** (low / S / ~22 lines / build no)
- Keep: `yaw_of`, `lookup_pose(buf, target, source, time=None)`, `lookup_stamp`. The method names that tests stub (`_map_odom_stamp`, `_pose_in_map`, `_laser_pose`) stay. Keep the bare `except Exception`.
- Remove: the `_yaw` and lookup bodies in survey_move_node, route_executor and mapping_session (`_slam_lag_s` becomes `_last_scan_stamp - _map_odom_stamp()`), and the inline yaw at `localization_monitor:208,249,259`.
- Steps:
  1. Add the module (new file in an existing package; symlink install picks it up).
  2. Port the four nodes.
- Tests: new `test_tfpose.py` with a fake buffer (exception → None; planar and rolled yaw). `test_continue_survey.py` runs unchanged.
- Depends: D20

**D33 — INT32 counter delta** (low / S / ~18 lines / build no)
- Keep: `kinematics.to_int32` and `counts_delta(new, old)`. `blindrun`/`uturn.counts_delta` become re-exports and `canopen.unwrap_i32` delegates. `fake_base` uses `to_int32` and `diff_drive.forward`; cpr stays 1080000.0. · Remove: the duplicate bodies and the wrap/twist code at `fake_base:150-163,179-182`.
- Tests: a wrap check in test_kinematics or test_blindrun (bump `EXPECTED_CHECKS`). `test_canopen:73-75` and `test_r06` stay as pins. Also uturn, tag_table and fake_base tests.
- Depends: —

**D32 — Wheel travel formula, step 1 only** (low / S / ~12 lines / build no)
- Keep: `uturn.m_per_count(cpr)` and `unsigned_travel_m(counts, ref, cpr)`. TagOdometer keeps its ref and grace. The `pos_rad` migration is dropped. · Remove: the inline math at `job.py:926-929`, `tag_table.py:155-158` and `uturn.py:100`.
- Tests: a wrap-equivalence case in `test_uturn.py` (`math.pi` vs the literal); test_mission_engine and test_tag_table.
- Depends: D11 *(outside P1 list)*

**D34 — `WheelScale` in a can-free module** (low / S / ~15 lines / build no)
- Keep: `RAD_S_PER_RPM` and `WheelScale` in `amr_base/diff_drive.py`, re-exported from `canopen`. Derived `WHEEL_RAD_S_PER_MOTOR_RPM` in `config._derive` (no schema key).
- Remove: the four module constants (cmd_mux, commissioning, fake_base, tape_synth), the sign math at `commissioning.py:336-340`, and the bodies at `canopen.py:183-207`.
- Steps:
  1. Move the class.
  2. Add the derived constant.
  3. Commissioning and fake_base use a `WheelScale` instance; tape_synth uses `motor_rpm`. This fixes a latent sign bug that has no effect while the invert flags are false.
- Tests: a derived-value check in `test_config.py` (+1 `EXPECTED_CHECKS`); a sim test with `invert_left=True` (tape_synth body motion equals fake_base); r03, r06 and commissioning tests.
- Safety: `cmd_mux_kinematics_node.py` (a constant is replaced by an import of the same value). Failure mode: a sign or scale error in commissioning or sim. The vehicle path already uses `WheelScale`. Recovery: the invert-flag test and r03/r06 catch it; revert.
- Depends: —

**D35 — `profile_geometry()`** (low / S / ~10 lines / build no)
- Keep: `diff_drive.profile_geometry()` (lazy config import) as the default for the mux, odom and fake_base params; no ROS interface is removed. `agv_core.kinematics` is unchanged. · Remove: the stale xacro comment at `:16`, the hand-computed v/w at `bag_report.py:107-108`, the duplicate `r=` at `p0_report.py:241`, and four test `Geometry(0.09, 0.487)` literals.
- Steps:
  1. Add the helper and use it as the param default.
  2. `base.launch` passes radius/track to the description include.
  3. bag_report uses `diff_drive.forward`, plus a shared `wheel_travel`.
  4. Tests use `PROFILE_GEOM` unless they pin geometry on purpose.
- Tests: in `test_diff_drive.py`, `kinematics.body_to_wheels` must equal `diff_drive.inverse(profile_geometry())`. Also wheel_model, r06, mux_manual_profile and test_urdf.
- Safety: `cmd_mux_kinematics_node.py` (only where a param default comes from). Failure mode: wrong geometry scales wheel commands wrongly. Recovery: the offline contract test; revert the default.
- Depends: —

**D75 — `kinematics.approach_decel_rpm_s`** (low / S / ~4 lines / build no)
- Keep: the pure, uncapped helper (takes `mps_per_rpm` as a parameter). `tape_run.approach_rate` keeps its None handling and 0.95 cap. The braking envelopes in survey_move, blindrun and site_run stay as they are. · Remove: the inline formula at `mission.py:259,347,605` and `tape_run.py:105`.
- Tests: equality with the old expression on 2-3 inputs (bump `EXPECTED_CHECKS`); test_tape_runtime and job tests.
- Depends: —

**D76 — `_decel_needed` in `mission.py`** (low / S / ~8 lines / build no)
- Keep: `_decel_needed(vehicle, v_rpm, distance_m, end_rpm=0.0) -> (rate, limit)`, built on D75. Messages stay byte-identical. · Remove: the decel lookup, rate and compare at `mission.py:282-290, 345-354, 605-607, 701-705`.
- Tests: add stop-distance refusals for the site mission and marker_run (bump `EXPECTED_CHECKS`).
- Depends: D75

**D58 — `_uturn_approach` in `mission.py`** (low / S / ~22 lines / build no)
- Keep: `_uturn_approach(row, where, vehicle, verbose=False)`. Each caller keeps its extra fields and its current wording (`verbose=True` for the tags table). · Remove: the U-turn blocks in `_read_tags`, `_read_marker_run` and `_site_uturn`.
- Tests: `test_mission.py` gets one decel-too-steep refusal per caller where missing; test_tape_localization and test_site_run.
- Depends: D75 (and reuses D76's helper if that lands first)

**D77 — `mission.load()` built on `_read_doc`** (low / S / ~14 lines / build no)
- Keep: `_read_doc(name, directory, have=None)`, `_path`, `_named`, `_as_mission_error`. Public signatures and messages unchanged. Build `have` lazily, on the error path only. · Remove: the inline block in `load()`, the duplicate name-match check, and the duplicate wrapper in `parse`/`parse_site`.
- Tests: refusals for a bad name, a missing file (`'have ['`), invalid JSON and a name mismatch, for both `load` and `load_site` (bump `EXPECTED_CHECKS`).
- Depends: —

---

**Group D: ROS node plumbing (one change for D07 and D10, after D61)**

**D07 — `amr_base/qos.py`** (low / M / ~100 lines / build no)
- Keep: `RELIABLE_1`, `LATCHED`, `SENSOR_DATA`, `EVENT_STREAM` (depth 50 RELIABLE VOLATILE). Local aliases where names differ. Any profile that does not match stays local with a comment saying why.
- Remove: the per-module QoS literals in drive_node, cmd_mux, panel_node, commissioning_node, diff_drive_odom, rfid_node, adapter, supervisor, line_follow, route_executor, mapping_session, survey_move, localization_monitor, scan_gate, imu_bias, fake_base, square_drive and the sim tests.
- Steps:
  1. Add the module, field-for-field identical.
  2. Migrate module by module, including the route, run_control and amcl sim tests.
  3. Run `ruff check src/` from `amr_ws`.
- Tests: new `test_qos.py` pinning depth, reliability and durability of each profile (cmd_mux included); focused node tests; one sequential sim run at the milestone.
- Safety: `cmd_mux_kinematics_node.py` (import only). Failure mode: LATCHED mapped to RELIABLE_1 means late joiners miss latched state and consumers time out to zero/not-ready (fail-safe). Recovery: the `test_qos` pins, plus `AMR_QOS_EVENTS=1` to show the incompatibility.
- Depends: D61 *(outside P1 list)*, D10

**D10 — `lean_node.run()`** (low / M / ~100 lines / build no)
- Keep: `run(node_factory, args=None, before_destroy=None, catch_runtime=True)` next to `LeanNode`. The `main(args=None)` symbols named in setup.py stay. · Remove: the `main()` bodies in about 17 nodes (amr_base 6, amr_sim 6, amr_mission 3, amr_localization 3, amr_line 1).
- Steps:
  1. Add `run()`.
  2. Move the sim nodes to `LeanNode` plus `run`.
  3. Production mains: drive_node `before_destroy=lambda n: n.stop()`, commissioning finalize, panel close and rfid `link.stop` with `catch_runtime=False`.
- Tests: with a fake rclpy, `run()` calls `before_destroy` before `destroy_node` and swallows RuntimeError only when rclpy is not ok. Run `pytest -q src/amr_base/test src/amr_sim/test`; unified sim at the milestone.
- Safety: `cmd_mux_kinematics_node.py` (its `main()` is converted). Failure mode: if drive_node's `before_destroy` is dropped or reordered, the drives are not disarmed on the bus thread at shutdown; the owner-side disarm and FX3 STO still hold. Recovery: restore `node.stop()` first in `finally`; the helper test pins the order.
- Depends: D07 (same change)

**D14 — Event builder and severity map** (low / M / ~55 lines / build no)
- Keep: `agv_core/alarms.LEVEL` and `level(code)`. An `amr_base` helper (`make_event` or `LeanNode.emit_event`) that uses `_event_seq`. Each node keeps its source string, text format and publish-safety mode (drive `_safe_publish`, supervisor `safe=True`). · Remove: the 9 builder bodies and the 4 inline severity dicts.
- Tests: in `tests/test_alarms`, `LEVEL` equals the constants parsed from `Event.msg` (bump `EXPECTED_CHECKS`). Also test_mux_manual_profile, route_executor, line_follow and localization tests.
- Safety: `cmd_mux_kinematics_node.py` (only how its event is built; gating untouched). Failure mode: operator events are lost, never commands. Recovery: revert; the alarms test catches a wrong map.
- Depends: —

**D22 — `gating.lease_stale`** (medium / S / ~20 lines / build no)
- Keep: `gating.lease_stale(cur_instance, cur_gen, cur_seq, instance, gen, seq, monotonic_generation=False)`, pure. The two rules are kept on purpose and documented. A-callers (drive_node, cmd_mux, fake_base) keep building `Lease` with their own clock and lock. B-callers (commissioning, line_follow) pass `True` and keep storing the raw msg. cmd_mux keeps `_apply_generation`. · Remove: the inline filters in all five `_on_lease`.
- Tests: about 4 `test_gating` cases (same-gen replay, reorder, generation regress dropped only under B, new instance accepted). Also test_authority, commissioning and line_follow tests.
- Safety: `gating.py`, `cmd_mux_kinematics_node.py`. Failure mode: an inverted comparison accepts a replayed or old-generation lease, so authority holds for up to one more 0.3 s window. Recovery: lease expiry still zeroes commands in `select`/`drive_gate`; the new cases pin seq monotonicity for each variant.
- Depends: —

**D23 — Mux defaults from `gating.DEFAULT`** (medium / M / ~20 lines / build no)
- Keep: `gating.Params/DEFAULT` for timeouts and pendant caps. `FieldParams.warning_stop_m=0.0` stays the pure default. cmd_mux gets one constant `WARNING_STOP_M_DEFAULT=0.40`, used at `:162` and `:207`. `scanner_fields.yaml` stays the authority. Moving freshness to the profile is not part of this item.
- Remove: the six identical overrides at `base.launch.py:160-165` (keep a_max/alpha_max/d_max/delta_max), the literal defaults at `cmd_mux:138-152`, and the literals at `jog.py:29`.
- Steps:
  1. cmd_mux declares its params from the `DEFAULT` fields.
  2. Drop the six launch overrides.
  3. `jog.py` imports the pendant caps.
  4. Make the Hz comments at `line_follow:133` and `gating:398` agree.
- Tests: new `test_cmd_mux_defaults.py` (declared defaults equal `gating.DEFAULT`). The literal pins in `test_pendant_gating:66` and `test_editor_js:97` stay, so a cap cannot rise. Also field_limit and gating tests.
- Safety: `cmd_mux_kinematics_node.py`, plus `gating.py` (read only). Failure mode: a default bound to the wrong field (lease vs permit) changes the watchdog or pendant cap in any launch without overrides. Recovery: the defaults test; the launch overrides are dropped only while the defaults equal them.
- Depends: —

**D100 — `UiThrottle` and `_ui` periods** (low / S / ~4 lines / build no)
- Keep: `UI_PERIOD_S` and a pure `UiThrottle(period).due(now)` in `lean_node.py` (or the D61 registry). Each node keeps its own publish call; drive_node keeps `_safe_publish`. · Remove: the literal 0.1/0.2 periods and the 6 compare/assign sites. The tape_synth `_ui` copy is optional and is called out separately.
- Tests: `test_lean_node.py` throttle test; drive_node and panel tests.
- Depends: D61 *(outside P1 list)*

**D166 — Localization monitor defaults from `readiness.Limits`** (low / S / ~0 lines / build no)
- Keep: the `rd.Limits()` defaults (`jump_angle` through `math.degrees`, ages from `age_limits`). Node-only params unchanged. · Remove: the literals at `localization_monitor_node.py:53-73`.
- Tests: declared defaults equal the `Limits` defaults; amr_localization readiness tests.
- Depends: —

**D165 — Protective field index reaches the follower and executor** (low / S / ~0 lines / build no)
- Keep: `scanner_fields.protective_index(doc)`, used by `mux_params`. line_layer and navigation_layer pass `field_output_index`. Node defaults stay 0 for standalone runs.
- Tests: `protective_index(load()) == 0` and equal to the mux value; the launch params are present; `raycast.MOUNTED_FOV` equals the nanoscan3 `angle_end - angle_start` (within 1e-3); scan_synth `fov_deg` is 190.
- Safety: `scanner_fields.py`. Failure mode: a wrong index makes the follower/executor read a warning path as protective, so they refuse to arm or explain stops wrongly. Actual stopping is unaffected (FX3/STO). Recovery: the test pins 0; revert to the node default.
- Depends: —

**D30 — `amr_base/drive_state.py`** (low / S / ~20 lines / build no)
- Keep: `OPERATION_ENABLED`, `SWITCH_ON_DISABLED`, `STANDBY_STATES`, `torque_off`, `still(..., eps, inclusive)`, `field_clear(status, index)`. `readiness.drives_ok` keeps its signature and uses `canopen.STANDBY`. The `_drive_code` in `alarms` and drive_node share the `SWITCH_ON_DISABLED` constant only. · Remove: 3 torque-off expressions, 5 stillness expressions (each keeps its eps and `<`/`<=`), 2 field reads, and the `'standby'` literal.
- Tests: new `test_drive_state.py`; the pins at `test_mode_fsm:145-158` stay; alarms, readiness, route_executor and line_follow tests.
- Depends: —

**D15 — `amr_base/hold_policy.py`, shared primitives only** (low / S / ~25 lines / build no)
- Keep: `Debounce(grace_s).held()`, `HOLD_TEXT`/`hold_text`, `auto_causes(base, estop)`, `premove_ready`, `premove_timeout_text(timeout_s, tail)`. Both FSMs, hold paths, premove outcomes and per-product causes stay; the job keeps its `'authority'` entry local. · Remove: both `_prereq_held` bodies, the field/estop hold texts, and both `_auto_causes` bodies.
- Tests: new `test_hold_policy.py`; test_mission_engine and test_auto_resume as the lock (strings byte-identical).
- Depends: D30

**D117 — `pp.authority_gate` takes objects; one panel cache** (low / S / ~4 lines / build no)
- Keep: the gate rules and reason strings exactly as they are (deliberately not `drive_gate`). `drive_node._power_panel` becomes the only panel cache. · Remove: `drive_node.py:220 _panel`, the tuple at `:297`, and the Lease→tuple conversion at `:643`.
- Tests: `test_pp.py` builds `gating.Lease`/`arm_policy.Panel` objects, same fragments.
- Depends: —

---

**Group E: CAN and bench drivers**

**D41 — `cia402.py` / `cia301.py`** (low / M / ~25 lines / build no)
- Keep: the CW/SW masks, `OPERATION_ENABLED_MASK`, `is_operation_enabled`, `MODE_PV/PP`, `COB_DISABLED`, `COB_MASK`, `TRANSMISSION_ASYNC`, NMT commands and EMCY/HB bases. Bench SENSOR_NODE/BITRATE/DEVICE_TYPE go in too. Neither module imports python-can; old names stay as aliases. `guard.py` is not touched.
- Remove: `COB_DISABLED` at `read_imu.py:115` and `read_mls.py:101`, `canopen.py:68-69,80,82`, the literal at `pp.py:39`, the `0x6F/0x27` literals at `drive_forward.py:198,200`, and the unused `CW_QUICK_STOP`, `OBJ_YAW_RESET` and `MODE_WAITING`. `canopen.prepare` writes `cia402.MODE_PV`.
- Tests: assert the values (0x000F, 0x6F/0x27, 1<<31, 255, NMT bytes); test_rpdo, test_canopen, test_canmon and the bench text checks; `EXPECTED_CHECKS` if the new test is counted.
- Depends: —

**D42 — PDO constants and `check_steps`** (low / S / ~10 lines / build no)
- Keep: the RPDO literal step list as written (labels pinned). `rpdo.check_steps`. TPDO1 constants live in the D41 module. · Remove: `canopen.py:68-69`, `COB_DISABLED` at `read_mls.py:101` and `read_imu.py:115`, `read_mls.py:95-96`, and the guard loop at `canopen.py:112-116`.
- Tests: `test_rpdo.py` and `test_canopen.py:34-51` unchanged; `EXPECTED_CHECKS` unchanged.
- Depends: D41

**D44 — Bench SDO writes go through `guard.py`** (medium / S / ~5 lines / build no)
- Keep: `drive_forward.guarded_sdo_write(..., sensor=False)`, used by `drive_forward.w`, `coast_to_stop`, `read_imu.enable_tpdo` and `read_mls`. · Remove: the `_guarded_write` body in read_mls, which becomes a call to the shared helper.
- Steps:
  1. Add the helper.
  2. Route the bench writes through it.
  3. Add `(0x1803..0x1806, 1)` "IMU TPDO COB-ID" to `SENSOR_ALLOWED`.
- Tests: `test_canmon` asserts the exact `SENSOR_ALLOWED` set, `ALLOWED`/`FORBIDDEN` unchanged and FREE still denied, and that no raw `sdo_write` exists outside the helper (+1-2 checks, bump `EXPECTED_CHECKS`).
- Safety: `guard.py`. Failure mode: a bench write is refused with `ForbiddenWrite` (missing sub-index, or a controlword value check on `coast_to_stop`); the tool aborts and the drives are not commanded. Recovery: add the explicit (index, sub) with a test.
- Depends: —

**D115 — `s16`/`s8` and `gyro_dps`** (low / S / ~5 lines / build no)
- Keep: `read_imu.s16` (None-safe), new `read_imu.gyro_dps`, `read_mls.s8`. · Remove: `s16` at `read_mls.py:136-137`, the inline sign conversion at `bus_health.py:92-93`, and the inline gyro scaling at `read_imu.py:322`. `mls_imu` calls `gyro_dps`.
- Tests: a `gyro_dps` check in `test_imu.py` (+1 `EXPECTED_CHECKS`); test_mls_imu and the existing s16/s8 checks.
- Depends: —

**D79 — `SdoProbe` for MLS rediscovery** (low / S / ~10 lines / build no)
- Keep: `mls_track.SdoProbe` (clock-fed; constants plus `BACKOFF_S=2.0`), used by MlsImu. Class-attribute aliases stay if tests patch them. MlsTrack keeps its `_cycle` reset; MlsImu keeps its `OBJ_ENABLE` probe. · Remove: the constants at `mls_imu.py:163-168` and the bookkeeping at `mls_imu.py:234-251` and `mls_track.py:325-331,368-375`.
- Tests: `SdoProbe` unit test (5 misses → 2.0 s backoff, hit resets); test_mls_track and test_mls_imu.
- Depends: —

**D80 — `rfid.read_frames` / `channel_mhz`** (low / S / ~15 lines / build no)
- Keep: both helpers in `rfid.py`. `read_frames` applies the 8 KiB bound. `_session` keeps its heartbeat and params logic; survey keeps its handshake order. · Remove: the loop at `rfid_survey.py:47-56` and the MHz formula at `rfid_survey.py:86-87` and `rfid.py:470-471`.
- Tests: RFID tests; a `channel_mhz` check (+1 `EXPECTED_CHECKS`).
- Note: the survey now also drops a junk buffer over 8 KiB, as the link already does.
- Depends: —

**D150 — RFID pass-line format and parser in one place** (low / S / ~3 lines / build no)
- Keep: `rfid.PASS_RE` and `parse_pass_summary` next to `pass_summary`. · Remove: `bag_report.py:33-35`.
- Tests: a round-trip check in `test_rfid.py` (+1 `EXPECTED_CHECKS`).
- Depends: —

---

**Group F: Files, stores, paths, maps**

**D24 — `agv_core/paths.py`** (medium / M / ~30 lines / build no)
- Keep: `state_dir()`, `maps_dir()` (env first, then the expanded default) and named sub-paths. Node params stay, with defaults from `paths.*`. · Remove: the per-site env+expanduser expressions in launch files, nodes, web, reports and tools, and the `$HOME/.amr` hard-codes in `run_log.sh`.
- Steps:
  1. Add the module and tests.
  2. Repoint launch files, node defaults, web_node/adapter, reports, tools and read_mls.
  3. `supervisor._env()` exports `AMR_STATE_DIR`/`AMR_MAPS_DIR` from its params.
  4. `run_log.sh` sources `amr.env` or asks `paths`.
- Tests: `tests/test_paths.py` (env set/unset, `~`), bump `EXPECTED_CHECKS`; a reports producer-path test; a supervisor `_env` test. Check at the milestone that the `test_fault_injection_sim:45` workaround is no longer needed.
- Note: if a node resolves another dir, LINE refuses to start, navigation reports no map (fail-safe) and the disk alarm watches the wrong volume. Covered by `test_paths` plus `validate.sh`.
- Depends: —

**D17 — `agv_core/fsio.py` for the revision stores** (low / M / ~50 lines / build no)
- Keep: `writer_lock(dir, sweep_prefix)`, `fsync_path`, `sha256_file` (chunked), `positive_revision`, `publish_dir`. Each store keeps its error class, plain-name rule, `REV_RE`, layout and manifest checks; `store._commit_new` stays. · Remove: `_lock`/`_fsync`/`_sha` and the publish body in tape_graph_store; `_fsync_path`, the `map_lock` body and `sha256_file` in map_bundle (re-exported); `_locked`, `_fsync_dir`, `sha256_file` and the `_revision` body in store.
- Tests: `tests/test_fsio.py` (thread lock exclusion, publish refuses an existing dest, sha equality), bump `EXPECTED_CHECKS`; map_bundle, store and tape_graph tests.
- Depends: D11 *(outside P1 list)*

**D29 — `agv_core/fsutil.py` for logs and journals** (low / M / ~40 lines / build no)
- Keep: `rotate_numbered`, `atomic_write_json(path, doc, mode, indent, mkstemp)`, `iter_jsonl`, `keep_newest`. `logs.rotate` stays as an OSError-swallowing wrapper. EventLog keeps its size check, and `tail` still reads only `.1` and the live file. Stamps, `now_iso` and `run_log.sh` are unchanged (the rotation gap there is a separate fix).
- Remove: the rotate loop in EventLog; the tmp/fsync blocks in uptime, role and `tape_graph_store._atomic_json`; `flight_recorder._prune`; the `reports._prune` body; the tolerant loops in `eventlog.tail`, `operations._replay` and `tape_health_report`.
- Tests: `tests/test_fsutil.py`, bump `EXPECTED_CHECKS`; test_logs and test_operator_ux as pins; tape_graph_store, reports and eventlog tests.
- Depends: —

**D38 — Map revision resolution** (low / S / ~12 lines / build no)
- Keep: `tape_loc.verified_map`, now also used by navigation_layer. New `map_bundle.manifest_sha`. `readiness.resolve_map` keeps its strict semantics and messages. · Remove: `navigation_layer.launch.py:88-96` and the `line_follow_node._bundle_sha` body.
- Tests: tape_loc, readiness and map_bundle tests (+ a `manifest_sha` case).
- Note: a navigation launch with no revisions now raises BundleError instead of RuntimeError; same message, and the launch fails either way.
- Depends: —

**D68 — Continue check for pose-graph files** (low / S / ~12 lines / build no)
- Keep: `map_bundle.POSEGRAPH_FILES` and `missing_posegraph(manifest)`. readiness gains an internal `_resolve` that returns the Manifest; `resolve_map`'s return value is unchanged. · Remove: `CONTINUE_FILES` and the yaml re-read in readiness, `POSEGRAPH_FILES` in mapping_session, and the tuple at `server.py:140`.
- Tests: test_continue_survey_supervisor, the mapping_session and server continue tests, and a `missing_posegraph` unit test.
- Depends: —

**D123 — Per-generation file names; sweep `loc_map_gen`** (low / S / ~2 lines / build no)
- Keep: `logs.GENERATION_FILES` and `gen_path()`; navigation_layer uses `gen_path`. · Remove: the literal parsing at `logs.py:87-89` and the f-strings at `navigation_layer.launch.py:39,75`.
- Tests: `test_logs.py` (`loc_map_gen3.*` kept at `keep_generation=3`, others removed); test_launch_layers.
- Note: stale `loc_map_gen` files from dead generations are now deleted; the live generation is kept.
- Depends: —

**D40 — `grid.OCCUPIED`, `occupied()`, `trinary_image()`** (low / S / ~18 lines / build no)
- Keep: those three in `amr_maps/grid.py`; `to_pgm_bytes` uses `trinary_image`. `live.grid_to_gray` stays as it is. · Remove: `OCCUPIED` in relocalize and scan_consistency, the inline images in server and demo_server, and the remaining `>= 65` literals.
- Tests: `trinary_image` matches the `to_pgm_bytes` payload pixel for pixel; footprint, validate, relocalize, scan_consistency and map-image tests.
- Depends: —

**D106 — `grid.dilate_square`** (low / S / ~10 lines / build no)
- Keep: `dilate_square(mask, k)`. `occupied_near` keeps its API; `relocalize.proximity` keeps its ring loop; `footprint.dilate` (disc) stays. · Remove: the `occupied_near` loop body; the `OCCUPIED` copies (shared with D40).
- Steps:
  1. First add a test that `occupied_near == proximity>0` on the sim factory at 0.05/0.15/0.3 m.
  2. Then rewrite `occupied_near`.
- Tests: the equality test, plus scan_consistency, relocalize and route tests.
- Depends: D40 (same `OCCUPIED`)

**D87 — `grid.read_optional`** (low / S / ~6 lines / build no)
- Keep: `read_optional(path)`. map_bundle keeps its BundleError wrap. · Remove: `validate.keepout_misalignment` (call `gridio.mask_misalignment` at `:112`) and the duplicate path/isfile logic.
- Tests: map_bundle (`:377,383`), validate/route and server tests, plus a `read_optional` case.
- Depends: —

**D119 — `grid.meta_dict`** (low / S / ~3 lines / build no)
- Keep: `meta_dict(grid)`, used by `server.api_map` and `demo_server.map_meta`; `live.py` unchanged. · Remove: the inline keys at `server.py:647-651` and `demo_server.py:203-206`.
- Tests: `meta_dict` with a non-zero origin; map API JSON unchanged.
- Depends: —

**D113 — `tape_locator.interp_sorted`** (low / S / ~10 lines / build no)
- Keep: `interp_sorted(series, t)`. Edge rules stay in the callers: OdomBuffer returns None (with +0.05 s tolerance), p0_report clamps. · Remove: the bisection bodies at `p0_report.py:51-59` and `tape_locator.py:90-98`.
- Tests: `tools/test_p0_report.py`, `test_tape_localization.py`.
- Depends: —

**D149 — `run_log.sh` uses `vehicle.sh` and the loaded profile path** (low / S / ~3 lines / build no)
- Keep: `amr_ws/env/vehicle.sh` and `config.PROFILE_PATH_LOADED`. · Remove: the export at `run_log.sh:23` (replaced by a `ROS_DOMAIN_ID_RUN` override), the `${AGV_PROFILE:-agv-01}` path at `:81`, and the hard-coded path at `reports.py:102` (lazy import with the old path as fallback).
- Tests: a reports test that `build()` includes the loaded profile basename; shellcheck `run_log.sh`.
- Note: the recorder now uses the service's loopback CycloneDDS config, so it discovers the same graph (a fix).
- Depends: —

---

**Group G: Supervisor**

**D102 — `OperationBook.by_request` and `_dedup_or_admit`** (low / S / ~8 lines / build no)
- Keep: both helpers; reply text and order unchanged (shared code starts after the per-service kind lookup). · Remove: the duplicate blocks at `supervisor_node.py:407-416` and `453-462`, and the reach into `_by_request`.
- Tests: disk_guard (fake gets `by_request`), continue_survey_supervisor and mode_fsm tests, plus a duplicate-`request_id` test.
- Depends: —

**D101 — `Supervisor._spawn`** (low / S / ~8 lines / build no)
- Keep: `_spawn(role, argv)`, used by `_launch`, the web and foxglove spawns in `_boot`, and `_respawn_due`. `launch_helpers.foxglove` is not touched. · Remove: the inline `Group.spawn` calls at `:998-1000,1016-1018,1057-1062`.
- Tests: hardness, r25_r27, process_supervisor and logs tests; bind `_spawn` onto the SimpleNamespace fakes.
- Depends: D51 *(outside P1 list)*

**D143 — `_enter_idle_if_base_ready`** (low / S / ~3 lines / build no)
- Keep: the helper; the late path keeps its log line before the transition. · Remove: the duplicated condition and transition at `:1114-1117` and `1130-1134`.
- Tests: supervisor boot tests, plus a late-base-ready test if missing.
- Depends: —

**D93 — Remove the readiness disk shim** (low / S / ~11 lines / build no)
- Keep: `agv_core/disk.py`, imported directly as `diskmod` in supervisor_node. · Remove: `readiness.py:16` and the alias block at `:37-42`, and `test_disk_guard.py:53-56`.
- Tests: test_disk_guard, test_continue_survey_supervisor.
- Depends: —

---

**Group H: Web HMI (D156 first, since D155 builds on it)**

**D156 — One `$` in `amr.js`** (low / S / ~10 lines / build no)
- Keep: one global `$` in `amr.js`. · Remove: all 11 page copies (5 static, 6 templates) in the same change; any copy left over is a SyntaxError.
- Tests: run, review, editor and teach page tests. Add `$` to the harness contexts that load page scripts without `amr.js`.
- Note: a missed copy kills that page's script. Recovery: delete the line and reload.
- Depends: —

**D155 — One `ago(s, suffix)`** (low / S / ~2 lines / build no)
- Keep: `amr.js ago(s, suffix='')` with an hour branch. · Remove: `linetrack.js:85` and `alarms.html:23`.
- Tests: JS harness tests that touch linetrack.
- Note: Home ages past 1 h now read "x.x h ago" (cosmetic).
- Depends: D156

**D60 — `every()` poll loop** (low / S / ~20 lines / build no)
- Keep: `every(ms, fn, {visibleOnly, backoff, onError})`, with every interval kept. · Remove: the try/catch+setTimeout boilerplate in `amr.js` (4 loops), `alarms.html` (2), home, monitor, io, params and tapegraph. `demo.js` stays.
- Tests: a JS harness test that `every()` reschedules after a rejected `fn`; templates render.
- Note: bug fix. Monitor, io, alarm events and params keep polling after one dropped request; `/io` shows `#io-lost`.
- Depends: —

**D63 — One `/api/alarms` poller** (low / S / ~20 lines / build no)
- Keep: `pollAlarms` and `onAlarms`, plus `LV` and `alarmRow(a, detailHtml)` in `amr.js`. · Remove: `LV`, the loops and the row markup in `home.html` (`:87,236-242,257-260`) and `alarms.html` (`:22,27-41`).
- Tests: test_server and the page template tests; check the fit at UI scale `l`.
- Note: one alarm request per second instead of two; rendered output identical.
- Depends: —

**D64 — `act()` POST-and-report** (low / S / ~30 lines / build no)
- Keep: `amr.js act(path, body, {msgEl, noResponse, prefix})`, with the level from `data.ok ?? status===200`. `operation()` stays for 202 endpoints. · Remove: the order/speed/uturn/cont bodies in guide, and the inline handlers in run.js, home, teach and run_tracked.
- Tests: a JS harness for the `act()` level and the no-response text; teach and operator_ux pages render.
- Note: refusals in run.js now get the `bad` class (cosmetic).
- Depends: —

**D62 — `FRESH_S`, `panelVerdict`, `sourceTile`** (low / S / ~8 lines / build no)
- Keep: `alarms.FRESH_S`, rendered into `base.html` as `data-fresh-s` (0.5 fallback), plus `panelVerdict()` and `sourceTile()` in `amr.js`. The Drives and Gen tiles stay page-specific. · Remove: `amr.js:55`, the `panelVal` at `home.html:201`, and the duplicate mux tile code in home and manual.
- Tests: `base.html` carries `data-fresh-s`; a JS harness for `panelVerdict` (ages 0.4/0.6, invalid, missing).
- Depends: —

**D130 — `lineFresh` / `placeLcpDots`** (low / S / ~5 lines / build no)
- Keep: both helpers in `linetrack.js`. · Remove: the inline code at `home.html:153-158` and `linetrack.js:6,8,14-18`.
- Tests: a `test_operator_ux` assert that home calls `placeLcpDots(`.
- Depends: —

**D132 — `_engineer_only(what)`** (low / S / ~5 lines / build no)
- Keep: a nested helper in `create_app`, called at the same spot (before `_body()`), with the messages verbatim. · Remove: the six inline role checks.
- Tests: `test_server -k engineer` and test_teach_page; add a 403 assert for `/api/line/areas`.
- Depends: —

**D59 — `EventRing`** (low / S / ~22 lines / build no)
- Keep: `eventlog.EventRing(maxlen=300, log)` with `add`, `since` and `restore`; the disk append stays outside the lock. `agv_core/events.py` is untouched. The DemoAdapter gains `emit()` and `event_log_files()`. · Remove: the duplicate bodies in `adapter._on_event`/`emit`, the restore loop, and the DemoAdapter ring.
- Tests: `EventRing` unit checks (trim, monotonic `n`, restored flag, sync on error, `log=None`); `/api/page-error` on the demo.
- Depends: —

**D06 — DemoAdapter reuses the real code** (low / M / ~60 lines / build no)
- Keep: `create_app` as the only server. The DemoAdapter keeps its scenario and sim logic and takes:
  - mode ints and admission from `mode_fsm` / `mode_fsm.admit`
  - op dicts from `operations.OperationBook`
  - wheels from `diff_drive.inverse` plus `config.GEAR_RATIO`
  - DI/DO names from `config` (selector looked up by name, literal fallback)
  - the horn from `panel_io.horn_wanted`

  The statebook is deferred to P3.
- Remove: `MODE` at `:70`, `DI/DO_NAMES` at `:74-84`, the kinematics literals at `:538-539,794-795`, the `_op` ints at `:597-611` and the refusal rules at `:613-640`.
- Steps:
  1. Fix `line_mission(name, destination='')`.
  2. Add `emit`, `event_log_files` and `line_*` stubs.
  3. Wire in the real modules.
- Tests: new `test_demo_contract.py` (signatures bind the args server.py passes; the `state()` keys are a subset of a pinned RosAdapter key list); test_operator_ux.
- Depends: D04, D16 *(outside P1 list)*; D59 overlaps (`emit`)

**D109 — Server sends Python constants to page JS** (low / M / ~10 lines / build no)
- Keep: server-rendered `data-*` JSON for the route bounds and jog constants, with the current literals as JS fallback. `maps.html` renders its spin buttons from `ROTATE_STEPS_DEG`. · Remove: `editor.js:9-10` (`LEGACY_SPEED_KEYS`/`routeLimits`) and the hard-coded spin buttons in `maps.html`.
- Tests: update `test_editor_js`/`editor_harness`; a server test that legacy keys are dropped on save; `maps.html` renders 12 buttons; fit at `l`.
- Depends: —

**D141 — Arc sampling and `viewIsActive`, dedup part only** (low / S / ~5 lines / build no)
- Keep: `arcCentre`, `arcPose` and `viewIsActive(view, state)` as globals in `mapview.js`. `editor.js:277` stays on its current rule; switching it changes the LINE-mode overlay and needs your sign-off. · Remove: `editor.js:35-36`, the inline formula at `run.js:153-154`, and `run.js:13-16`.
- Tests: `pytest -q src/amr_web/test`.
- Depends: —

**D134 — `recover()` / `restart(text)` in home** (low / S / ~4 lines / build no)
- Keep: both functions; both confirm strings stay verbatim. · Remove: `home.html:220` and `:221-224`.
- Tests: test_operator_ux.
- Depends: —

**D118 — One config try block in `api_line_site`** (low / S / ~4 lines / build no)
- Keep: one try block; read the name first and guard live with `getattr(config, 'TAPE_LOC_LIVE', False)` to keep the exact fallback behaviour. The machines sort stays. · Remove: the second block at `server.py:428-433`.
- Tests: test_teach_page (payload unchanged).
- Depends: —

**D148 — `rfidTags` reuses `why`** (low / S / ~2 lines / build no)
- Keep: `rfidReading().why`; texts verbatim. · Remove: the three duplicated branches at `linetrack.js:67-69`.
- Tests: test_operator_ux.
- Depends: —
### P2: Engine consolidation & finished migrations

None of these items touches a safety-invariant file (`gating.py`, `cmd_mux_kinematics_node.py`, `scanner_fields.*`, `guard.py`). None needs `colcon build`. Each item has a **Failure** line where the data gave a failure mode.

Order:
- **Tape engine, amr_line (D11 freeze):** D12 → D13, then D144 and D105.
- **canbus library:** D18 → D43, then D55, D45 and D124.
- **Legacy migrations:** D16, then D08, which waits on D84.
- **Launch / web / sim:** D39, D53, D36, then D95 → D164.

---

**Tape route engine (amr_line, under the plan-4 / D11 freeze)**

**D12: Merge trip_route.TripRoute/compile_trip into tape_graph.Route/compile_route** (medium / M / ~40 lines / build no)
- Keep: `tape_graph.Route` as the only route class, with 4-tuple segments `(S0, leg, lo, hi)`. Full circuits use lo=0 and hi=leg.length. It keeps at/point/project/stop/length and gains `where()`. `TripRoute(Route)` adds uturn/zones/events/notes/label/ident. Two new helpers, `tape_graph._circuit_order` and `_node(prev, leg, s0)`. · Remove:
  - `trip_route.py:TripRoute.length/at/point/project/stop` (duplicate bodies)
  - `trip_route.py:compile_trip` order/missing block and junction node dict
  - `tape_runtime.py:262` segment re-tupling
- Steps:
  1. Move Route to 4-tuples using TripRoute's at/project maths (lo=0 gives today's Route formula). Add `where()`.
  2. Make TripRoute subclass Route: `super().__init__()` plus the trip fields. Delete the duplicated methods.
  3. Factor `_circuit_order`/`_node` out of compile_route and use them in compile_trip. The mirror U-turn node stays local.
  4. Fix the unpacks at `tape_runtime.py:258/:262` (pass `route.segments` straight to `area_ranges`). Grep every `for s0, leg in` in amr_line and `amr_web/tapegraph_view`.
  5. Run the existing tests unchanged as the lock. Floats must stay bit-equal.
- Tests: `python3 -m pytest -q src/amr_line/test/test_tape_localization.py src/amr_line/test/test_trip_route.py src/amr_line/test/test_site_run.py src/amr_line/test/test_tape_runtime.py`. No EXPECTED_CHECKS impact.
- Failure: a missed 2-tuple unpack raises ValueError at layer start or trip compile. The layer refuses the trip and logs it. The tests catch it offline.
- Depends: D11

**D13: Put the P1 Shadow and the live engine on one decision schedule (TripRoute events + SiteRun)** (medium / M / ~30 lines / build no)
- Keep:
  - `trip_route.decision_points(route, stop_distance_m, junction_lead_m, uturns, prev_clamp=True)`
  - `trip_route.trigger_S(e, stop_distance_m)`, moved from `site_run._trigger`
  - `tape_locator.loc_ok(loc, limit)`
  - Shadow's tick/logging text and its `point` entries

  · Remove:
  - `tape_locator.py:Shadow.__init__` stop/order/uturn event loops
  - `tape_runtime.py:_new_shadow` hand-built points
  - `site_run.py:_loc_why` sigma/lost body (it now delegates)
- Steps:
  1. Extract compile_trip's events block into `decision_points`. Trip output stays identical; test_trip_route pins it.
  2. Move `_trigger` to `trip_route.trigger_S` and call it from site_run.
  3. Shadow takes `decision_points` (whole-circuit route, U-turns from the mission) and uses `trigger_S`. `_new_shadow` keeps only the plan-4 `point` and zone entries.
  4. Add `loc_ok`. `site_run._loc_why` becomes the route-ident check plus `loc_ok`. `TapeLocator.ok_for` uses `loc_ok` too.
  5. Update the test_tape_runtime shadow-log expectations on purpose: the order clamp and mid-line U-turn triggers now match the engine.
- Tests: `python3 -m pytest -q src/amr_line/test/test_tape_runtime.py src/amr_line/test/test_site_run.py src/amr_line/test/test_trip_route.py src/amr_line/test/test_tape_localization.py`
- Behavior: only the Shadow log changes. Trigger S for clamped orders and mid-line U-turns now matches the live engine. Motion is untouched. **Land this before the E2 5-lap acceptance.**
- Failure: Shadow never commands motion, so a wrong schedule only produces wrong log lines. test_site_run pins the engine.
- Depends: D12, D11

**D144: Point job.at_home() at the trip predicate in site missions** (low / S / ~2 lines / build no)
- Keep:
  - `job._site_at_home`, the single trip predicate behind `_trip_check`
  - `tape_runtime.begin_trip`'s locator guard (defensive, not a duplicate)

  · Remove: `job.py:440-441`, the unconditional `if self.site is not None: return False, ""`
- Steps:
  1. In `job.step()`, store the latest loc: `self._loc = i.loc`. There is no existing `_last_loc` to reuse.
  2. `at_home()`: when `self.site` is set, return `self._site_at_home(self._loc)`.
  3. Leave `_trip_check` and `begin_trip` as they are.
  4. Coordinate with the plan-4 author before editing job.py (D11 freeze).
- Tests: add to `amr_line/test/test_site_run.py`: in a site mission, `mission_snapshot()['at_home']` equals `_site_at_home` for an at-HOME, an off-HOME and a LOST loc, and `home_detail` is not empty when the value is false.
- Behavior: visible fix. In site missions the Home tile and headline show YES or a reason instead of NO with an empty detail. Start gating is unchanged.
- Failure: display only. Start still goes through `_trip_check`. Recovery: revert the dispatch.
- Depends: D11

**D105: Replace the four copy-paste Trigger handlers in line_follow_node with one** (low / S / ~12 lines / build no)
- Keep: `line_follow_node._trigger(label, call, res)`. It sets success/message, logs `f'{label}: {res.message}'`, calls `_publish_state()` and returns res. · Remove: `_srv_branch`, `_srv_continue`, `_srv_uturn`, `_srv_speed`
- Steps:
  1. Add `_trigger`.
  2. Rewrite the four registration loops to call it through lambdas. Keep the exact log labels: `branch order X`, `continue X`, `forced U-turn X`, `speed toggle X`.
  3. Delete the four methods.
- Tests: `pytest -q` the amr_line node-level tests that import line_follow_node, if any exist. No EXPECTED_CHECKS impact.
- Failure: service names and replies stay the same. A wrong label only changes log text.
- Depends: D11

---

**canbus library home (agv_core/drivers/canbus)**

**D18: Move the shared SDO/bus helpers into canbus/sdo.py + cia402.py (partial)** (medium / M / ~80 lines / build no)
- Planned part: the shared library home plus the dedup. Two parts are dropped:
  - rfid_survey is not routed through canbus `claim_bus`, which would pull python-can into an RFID tool.
  - The set of read_mls modes that take the lock does not change. That is the user's decision.
- Keep:
  - `canbus/sdo.py`: `sdo_read`, `sdo_write`, `sdo_int(bus, node, idx, sub, signed=False)`, `u32`, `nmt`, `open_bus`, `claim_bus(who)`, `bench_bus(who)`, `read_identity(bus, node)`, and a shared `_await_reply` matcher.
  - `canbus/cia402.py`: `CW_*`/`SW_*` and `decode_state`.
  - The old modules re-export, so the CLIs, `tests/test_invariants.py:29-30` and the docs keep working.
  - `guard.py` is unchanged. Guarding stays in `DriveLink.write` and `read_mls._guarded_write`.

  · Remove:
  - Bodies of `drive_forward.py:sdo_write/nmt` and `verify_drivers.py:sdo_read/u32/open_bus/claim_bus` (moved, re-exported)
  - `read_mls.py:nmt` (868-872) and the `rd` wrapper body
  - `read_imu.rd`, `bus_health.read`, `drive_forward.statusword` (become `sdo_int` calls)
  - The try/open_bus/"connected via" blocks in 9 CLI mains
  - The 1018h identity loops in verify_bus, verify_drivers and lss
- Steps:
  1. Create sdo.py and cia402.py and make the old modules re-export.
  2. Switch the `canopen.py` and `drive_node.py:59` imports to sdo/cia402.
  3. Replace the inline SDO int wrappers, `nmt` and the identity loops. Keep each tool's empty-payload behaviour.
  4. Put `bench_bus` in the 9 CLI mains, keeping exit code 2. read_mls uses `claim_bus('read_mls')` for its current mode list only. Fix the stale `agv_controller` text.
  5. Re-run the canbus tests and the read_mls `sdo_write(` count==1 source check.
- Tests:
  - `python3 -m pytest -q tests/test_canmon.py tests/test_invariants.py tests/test_lss.py` plus the amr_base canopen tests.
  - The `tests/test_canmon.py:135-137` check (read_mls has exactly one `sdo_write()`, through `guard.check_sensor`) must still hold. Adjust only the text location if it moves.
  - EXPECTED_CHECKS changes only if an identity or sdo_int check is added. If one is, bump it on purpose.
- Behavior: none. Only the claim_bus message text changes.
- Failure: the shared reply matcher could accept a late reply to another object, so canopen (inside the can0 owner process) reads a wrong value. Or the DriveLink write path could lose its guard. test_invariants C04 and test_canmon's guard source checks pin both. Recovery: revert the canopen import switch; the re-exports keep the old paths working.
- Depends: none

**D43: Share the drive preflight/enable sequence between DriveLink and bench drive_forward** (medium / M / ~25 lines / build no)
- Keep:
  - `preflight_report(read_sdo, read, nodes) -> (ok, lines)`, using DriveLink's text
  - `ENABLE_SEQUENCE` (Shutdown / Switch On / Enable Operation)
  - `OPERATION_ENABLED_MASK`/`OPERATION_ENABLED` and `is_operation_enabled(sw)`
  - Home: `drive_forward.py`, or `cia402.py` if D18 lands first
  - Teardown untouched (`coast_to_stop` vs `disarm`; they differ on purpose)

  · Remove:
  - `drive_forward.py:151-180` preflight body
  - The duplicated enable-triple loops in `drive_forward.arm` and `canopen._enable_sequence`
  - The literal `(sw & 0x6F) == 0x27` at `drive_forward.py:198,200`
- Steps:
  1. Move the mask constants and `is_operation_enabled`. canopen re-imports them under the same names.
  2. Add the pure `preflight_report`. The bench gains the "diagnostics unreadable" branch.
  3. `DriveLink.preflight` calls it with the router `sdo_read` and `self.read`, keeping the keepalive hooks. The bench prints the lines with indent and BAD markers.
  4. `_enable_sequence` and `arm` both iterate `ENABLE_SEQUENCE`, each with its own write/sleep/pump.
- Tests:
  - `amr_base/test/test_canopen.py` preflight/arm cases unchanged.
  - New `preflight_report` unit test in `tests/`: no response, collision, fault, remote clear, unreadable. Bump EXPECTED_CHECKS on purpose.
- Behavior: bench preflight wording now matches the ROS text and no longer crashes on an unreadable 1001h/6041h. The ROS path is unchanged.
- Depends: none declared. Land after D18 if cia402.py is the home.

**D55: Fold canopen.MonitorCursor into canmon.MonitorPoller.step()** (low / S / ~30 lines / build no)
- Keep: `MonitorPoller.step(read) -> (nid, key, value)|None` in `agv_core/canmon.py`. It does the node interleave, keeps the reads/timeouts counters and uses a public `decode_int(ctype, value)`. `next_object`/`store` keep their API for tests. · Remove:
  - `canopen.py:MonitorCursor`
  - The `drive_node.py:203` `_cursor` construction
  - The int→bytes round trip
- Steps:
  1. Add `decode_int` and `step(read)` with the same interleave (object fixed for a full node sweep).
  2. `drive_node._monitor_slot` calls `self._mon.step(...)` and reads `self._mon.reads/timeouts`.
  3. Delete MonitorCursor and its import in test_canopen.py.
  4. Move the `test_canopen.py:413-434` cases into `tests/test_canmon.py`.
- Tests: `tests/test_canmon.py` covers step ordering, the timeout counter and signed decode. Remove the MonitorCursor test from amr_base. EXPECTED_CHECKS +N on purpose.
- Behavior: none (same read order, same bus_stats keys).
- Depends: none

**D45: Make the bench read_mls.MarkerWatch use the runtime MarkerDetector** (medium / M / ~25 lines / build no)
- Keep:
  - `agv_core/drivers/canbus/mls_markers.py`: `MarkerDetector`, `MarkerEvent`, `ABORT_GRACE_FRAMES`, `lcp2(reading, default)`
  - `amr_base/marker_events.py` as a re-export shim, so the drive_node import is unchanged
  - MarkerWatch's line format, polarity set and `summary()` keys. It delegates to `MarkerDetector(codes=1..31)` fed with `source='tpdo', ok=True`.

  · Remove:
  - MarkerWatch counting/abort logic (feed keeps its print line)
  - 2 of the 3 LCP2 expressions
  - The duplicated abort tests at `tests/test_mls.py:143-155`
- Steps:
  1. Create mls_markers.py with the moved detector plus `lcp2()`.
  2. Turn marker_events.py into the shim.
  3. MarkerWatch delegates; `summary()` maps the detector counts.
  4. read_mls, marker_events and mls_track use `lcp2()`.
  5. Update the test_mls abort check: the bench now follows the 5-frame grace.
- Tests: `test_marker_events.py` unchanged through the shim. Adjust the `tests/test_mls.py` MarkerWatch checks, and update EXPECTED_CHECKS only if the count changes. Run `tests/run_all.py`.
- Behavior: bench `markers` mode abort and code counts change on purpose to match the runtime. The ROS runtime is unchanged. **Tell the user before the B-series instrumentation reruns.**
- Depends: none

**D124: Keep the PC heartbeat cadence in one place, link._t_hb (partial)** (medium / S / ~3 lines / build no)
- Planned part: one cadence via `keepalive(strict=True)`. Dropped: the plain swap to `link.keepalive()`, because it would swallow the bus send error that today ends `_loop` in the "bus error" handler.
- Keep: `DriveLink.keepalive(strict: bool=False)`. strict=True re-raises send errors. Blocking sequences keep the swallowing default. · Remove:
  - `drive_node.py:426` `t_hb`
  - `drive_node.py:538-540` heartbeat block
- Steps:
  1. Add `strict` to keepalive.
  2. Replace `drive_node.py:538-540` with `link.keepalive(strict=True)`.
  3. Drop `t_hb` from the loop's timer tuple.
- Tests: amr_base test cases:
  - strict=True propagates a `router.send` error
  - strict=False swallows it
  - nothing is sent while `heartbeat_withheld`
  - a heartbeat is due at `pc_heartbeat_s`

  No EXPECTED_CHECKS impact.
- Behavior: none, except that the extra early heartbeat after a blocking-sequence keepalive goes away. The interval stays ≤ pc_hb_s, so the drive 1016h timeout is unaffected.
- Failure: if the strict path were wrong, a dead bus would keep the loop alive. The 1016h consumer timeout on the drives still stops them. Recovery: revert to the explicit send.
- Depends: none

---

**Legacy migrations**

**D16: Retire the legacy horn.* engine (dio.motion_on/movement_horn/alarm_on stay)** (medium / M / ~85 lines / build no)
- Keep:
  - `dio.motion_on/movement_horn/alarm_on` via `panel_io.motion_outputs` and the alarm logic
  - `config.HORN_HOLD_S`. **It must stay**: it is the hold for every dio coil (`panel_node.py:192,196`).

  · Remove:
  - `panel_node.py:77` `/cmd_wheel_vel` subscription, `:93-94`, `:97`, `:123-125`, `:201-209`, and the horn text at `:8-9` and `:111`
  - `panel_io.py:horn_wanted` and the horn paragraph of the docstring (`:20-27`)
  - `test_panel_io.py:102+` (horn-follows test)
  - `config.py` horn schema `:583-585`, checks `:1144-1145` and `:1152-1157`, docs `:221-243`
  - The `profiles/agv-01.json` horn block, and the 4 horn refusals at `tests/test_config.py:261-274`
- Steps:
  1. Remove the panel_node horn path and the `/cmd_wheel_vel` subscription (cpu-load-plan item 15).
  2. Delete `horn_wanted` and its test.
  3. Retire `horn.*` with a retired-key refusal (clear message). Drop the block from agv-01.json in the same change.
  4. test_config: −4 horn refusals, +1 "horn section retired" check. EXPECTED_CHECKS −3 on purpose, with a dated comment.
- Tests: `python3 tests/run_all.py` (EXPECTED_CHECKS −3); `pytest amr_ws/src/amr_base/test/test_panel_io.py`
- Behavior: none at runtime (horn.enabled is false). A profile still carrying the horn block is refused.
- Failure: a missed profile edit makes config refuse at boot, so every node fails and BOOT_ERROR is raised. Recovery: drop the block or revert. Removing HORN_HOLD_S by mistake would make the dio coils lose their hold and drop.
- Depends: none

**D08: Replace the unread agv_core/events.py ring with an injected on_event callback** (low / M / ~80 lines / build no)
- Keep: `DioLink(..., on_event=None)` and `RfidLink(..., on_event=None)`: a `callable(level, text)`, no-op by default, called at the same edges. · Remove:
  - `agv_core/events.py`
  - The events imports at `dio.py:61` and `rfid.py:79`
  - Stale references at `canbus/alarms.py:18,22` and in the `drive_node.py:840` docstring
- Steps:
  1. Add the `on_event` kwarg and replace each `events.info/warn` call 1:1.
  2. Rewrite `test_dio_events_are_edge_only` to count callback calls, keeping the same 4 checks.
  3. Delete events.py and fix the comment references.
  4. Optional, and a visible change, so ask the user first: panel_node/rfid_node pass a `get_logger()` adapter.
- Tests: `tests/test_dio.py` keeps its 4 checks, so EXPECTED_CHECKS is unchanged. Grep `tests/test_layout.py` for an events module pin. Run `pytest` on amr_base test_panel_io.
- Behavior: none (no-op default).
- Failure: a missed call site raises NameError in the link thread, so the link stays down and panel valid=false, which fails safe. The run_all import checks catch it offline.
- Depends: D84

---

**Launch / web / sim**

**D39: Make tapegraph_view read and write through amr_line.tape_graph_store** (medium / M / ~35 lines / build no)
- Keep:
  - In tapegraph_view: `_thin`, `check_polygon`, the `AREA_*` limits, `view()` output shaping, and save_area's validation/messages
  - Reads/writes go through the store: `read_active`, `teach_dir`, `list_passes`, `load_stations/marks/areas/anchors`, `save_areas`
  - New in the store: `read_graph_doc(maps_dir, map_id, g)` (no manifest check, None on error)

  · Remove:
  - `tapegraph_view.py:_read/_selection/_teach_dir` path building
  - The `PLAIN` regex
  - save_area's own tempfile write
  - `view()`'s passes listing
- Steps:
  1. Add `read_graph_doc` built on `graph_root`.
  2. Add `<exec_depend>amr_line</exec_depend>` to `amr_web/package.xml`.
  3. Rewrite the internals on store calls. Adapt the anchor shape: `load_anchors` returns tuples, but `view()` filters `isinstance(v, list)`, so a naive swap drops every anchor.
  4. Selection: keep the view's looser check. `write_active` always writes `graph_revision`.
  5. Coordinate with the uncommitted plan-4 tape_graph_store edits. The JSON output stays byte-for-byte the same.
- Tests:
  - `amr_web/test/test_teach_page.py` plus any tapegraph view test: same JSON for a fixture state dir, including anchors and a pass-only state
  - `amr_line/test/test_tape_runtime.py` (areas round trip)
  - EXPECTED_CHECKS unaffected
- Behavior: none. The areas write gains fsync.
- Depends: none

**D53: Build the localization group once (tape_loc.group used by navigation_layer)** (medium / M / ~35 lines / build no)
- Keep: `amr_bringup/tape_loc.group` (optionally renamed `localization_group` with a `tape_loc` alias), with new kwargs `autostart=True`, `map_loc_yaml=None` and `amcl_extra_params`. `map_loc_yaml=None` adds `map_server_loc`, the remap and `node_names`. · Remove: the inline map_server/amcl/lifecycle/monitor Node blocks in `navigation_layer.launch.py:125-187`
- Steps:
  1. Extend `group()`. The defaults keep today's LINE output.
  2. `navigation_layer._compose` calls `group(map_yaml, autostart=..., map_loc_yaml=loc_yaml if blank, generation, dynamic_yaml)`. The controller/planner actions stay after it.
  3. Check that node names, the order of `required()` wrappers and the lifecycle `node_names` list all match.
- Tests: `amr_bringup/test/test_launch_layers.py` (`:276-309` localization assertions) unchanged. test_amcl_sim only once per milestone (opt-in).
- Behavior: none. AMCL params gain an empty `{}` on the nav path.
- Depends: none

**D36: Add raycast.cast_from_base and use it in place of the duplicated raycasting (partial)** (low / M / ~30 lines / build no)
- Planned part: the demo Sim raycaster, scan_synth's geometry and the test pose-compose. Kept, not dead:
  - `grid.world_to_pixel/pixel_to_world` (the reference for mapview.js, and tested)
  - scan_consistency's `cells()` (different shape)
  - `Sim.occupied` (needed for the wall-stop)
- Keep:
  - `amr_maps/raycast.py`: `cast_from_base(grid, base_pose, laser_pose, geom)` plus `mounted()`
  - scan_synth defaults to `mounted()`, with fov_deg/beams param overrides at their current defaults (190/381)
  - The demo uses `cast_from_base(world, pose, (0.964, 0, 0), mounted(191, 18.0))`, keeping the `max_points` cap

  · Remove:
  - `demo_server.py:Sim.scan` ray march, `LASER_X`, FOV, `_angles`, `_radii`
  - `scan_synth_node.py:62-68` geometry build and `144-146` pose compose
  - The local laser-pose compose in test_relocalize and test_continue_survey
- Steps:
  1. Add `cast_from_base` and a test.
  2. Switch scan_synth and the two tests to it.
  3. Switch the demo's `Sim.scan`, keeping `occupied()`/reveal.
  4. Note the demo-only visual change in the demo.
- Tests:
  - `amr_sim/test/test_raycast.py`: `cast_from_base` equals `cast` on a composed pose
  - Focused runs of test_relocalize.py and test_continue_survey.py, plus an amr_web demo smoke test if one exists
- Behavior: none on the vehicle or in sim. Demo only: no boundary points where rays leave the map, and the minimum radius goes from 0.1 m to `geom.range_min` 0.05 m.
- Depends: none

**D95: Shared fill_line_track for drive_node and tape_synth (partial)** (low / S / ~8 lines / build no)
- Planned part: the shared LineTrack fill. Deferred to the marker-sim plan: a synthetic TPDO1 encoder, which would be new code rather than redundancy removal.
- Keep: `amr_base/mls_track.py:fill_line_track(msg, reading, lcp_mm, source, age_s, seq)`, with no rclpy import. tape_synth builds its reading dict with `read_mls.NLCP_MEANING[2/0]` and marker code 0. · Remove:
  - `tape_synth_node.py:_tick` hand-filled fields (85-96)
  - `drive_node.py:_publish_track` field fill (993-1001, moved)
- Steps:
  1. Extract `fill_line_track` from drive_node.
  2. drive_node calls it; stamp and `_safe_publish` stay in the node.
  3. tape_synth builds the reading dict and calls it.
- Tests: unit-test `fill_line_track` against a `decode_tpdo1` output. Run test_tape_plant.py and the drive_node track tests. No EXPECTED_CHECKS impact.
- Behavior: sim only. Off tape, the line_tile label reads "no track" instead of "none". The vehicle is unchanged.
- Failure: a wrong field mapping mislabels line_good or validity, which the follower gates on. The drive_node tests must cover the fill. Recovery: revert.
- Depends: none

**D164: Label tape_synth_node as manual-only (partial)** (low / S / ~0 lines / build no)
- Planned part: the docstring note. Dropped: the reported INVERT sign bug (lines `:70-71` are the rad/s→rpm conversion and the node has no INVERT handling), and wiring the node into base.launch, which would be a feature.
- Keep:
  - `amr_sim.tape_plant.TapePlant` and test_tape_plant.py, unchanged
  - tape_synth_node as an ad-hoc `ros2 run amr_sim tape_synth_node` dev tool

  · Remove: nothing
- Steps:
  1. Add a one-line docstring note: manual-only, not in any launch.
  2. Decide wiring and a sign review together with D34/D95/D100.
- Tests: none now. If it is wired later, add it to the test_launch_layers.py `SIM_EXES` case.
- Behavior: none
- Depends: D34, D95, D100
### P3 — Tests, docs, structure

Order: blockers first (D26, D27, D88, D90), then payoff. "Depends" on an item outside P3 means that item lands first.

**Suite correctness: do first, so the refactors below run on a suite that really fails**

**D26 — Library suite blind spots: check() never raises under pytest, test_alarms not in run_all, tools/ tests on no path** (low / S / ~0 lines / build no)
- Keep: tests/helpers.py check()/FAIL, test_control.py:428-438 bridge (for now) · Remove: nothing
- Steps: 1. Add `tests/conftest.py`. Its autouse fixture snapshots `len(helpers.FAIL)` and asserts no growth. 2. Add `run_all.PYTEST_MODULES=['test_alarms']`, run them via `pytest.main`, fail on a non-zero exit, and keep them outside the check count. 3. Add `tools` to testpaths, or as a PYTEST_MODULES entry.
- Tests: EXPECTED_CHECKS unchanged while pytest modules stay outside the count. A previously silent failing check may surface: fix it or record it as a known failure.
- Depends: none

**D171 — PP expect indices duplicated between config and guard with no cross-check** (low / S / ~0 lines / build no)
- Keep: config.py:PP_EXPECT_OBJECTS and guard.py:PP_CONFIG_READ_ONLY (one is a mapping, the other a deny tuple) · Remove: nothing
- Steps: 1. In `tests/test_rpdo.py:test_pp_write_surface` assert `set(config.PP_EXPECT_OBJECTS.values()) <= set(guard.PP_CONFIG_READ_ONLY)`. 2. EXPECTED_CHECKS +1. 3. `python3 tests/run_all.py`.
- Tests: test_rpdo +1 check, EXPECTED_CHECKS +1
- Safety: guard.py is read, not changed. The check catches a new pp.expect object that guard leaves writable. Recovery: add the index to PP_CONFIG_READ_ONLY together with its guard test.
- Depends: none

**D137 — hold_cause literals are not checked against HOLD_CODES; run.js keeps its own HOLD_NAMES** (low / S / ~0 lines / build no)
- Keep: agv_core/alarms.py HOLD_CODES as the only vocabulary; web alarms.py:77 fallback · Remove: run.js:HOLD_NAMES
- Steps: 1. Add a source-scan test asserting that every `_hold("x")`, `return False, "x"` and hold_cause literal in job.py, track.py and route_executor_node.py is a HOLD_CODES key. 2. adapter.py adds `hold_title` from `alarms.get(fault_code).title`. 3. run.js:127 uses `r.hold_title || r.hold_cause`.
- Tests: in tests/test_alarms.py this adds +1 check, so update EXPECTED_CHECKS deliberately. Also run `pytest -q amr_web/test/test_operator_ux.py`.
- Behaviour: the run page's hold label changes to the catalogue titles (operator-visible, cosmetic). No wire change.
- Depends: none

**D136 — Alarm catalogue well-formedness asserted in two suites** (low / S / ~3 lines / build no)
- Keep: test_operator_ux BUTTON-label check (it pins the home.html handlers) · Remove: test_operator_ux.py:451 title/action/level assertion
- Steps: 1. Add the describe() key/level assertion to test_alarms.py's well-formed loop. 2. Reduce the web test to the BUTTON label set.
- Tests: `pytest -q tests/test_alarms.py amr_web/test/test_operator_ux.py`. EXPECTED_CHECKS unaffected.
- Depends: none

**amr_line tests**

**D27 — sys.path bootstrap repeated in 17 amr_line test modules** (low / S / ~45 lines / build no)
- Keep: the bootstraps in harness.py, test_control.py and the `__main__`-run files (test_control, test_line_mux, test_line_authority, test_track_reader) · Remove: the per-file sys.path blocks everywhere else
- Steps: 1. Add `amr_line/test/conftest.py` with the union of the paths: ROOT, package, test dir, amr_base, amr_sim. Use the same insert order as the files it replaces. 2. Delete the per-file blocks. 3. Run the focused pytest.
- Tests: `pytest -q amr_line/test` (collection plus pass)
- Depends: none

**D65 — Duplicate lj.Inputs builders and MLS sensor fixtures in amr_line tests** (low / S / ~30 lines / build no)
- Keep: harness.py and test_control.py untouched · Remove: test_line_authority.py:24 LEASE_LINE and the inputs() body; test_mission_engine.py:30-32 literals; test_kink_pivot.py:25 NO_TAPE
- Steps: 1. Create `line_fixtures.py` with `base_inputs(**over)`, CENTRED, NO_TAPE, `sensor_dict(mm, index=2)`, and LEASE_LINE imported from gating. 2. Point test_line_authority, test_mission_engine, test_kink_pivot and test_tape_plant at it.
- Tests: the 4 files, assertions unchanged
- Depends: D27

**D85 — test_line_mux tests amr_base.gating from amr_line and overlaps test_gating** (low / S / ~15 lines / build no)
- Keep: the LINE-branch select() tests · Remove: test_line_mux.py:142-158 (2 overlapping tests plus the stray `__main__`), :17-20 bootstrap
- Steps: 1. `git mv` to `amr_base/test/test_gating_line.py`. 2. Drop the two overlapping tests and the mid-file `__main__`. 3. Drop the bootstrap.
- Tests: `pytest -q amr_base/test/test_gating_line.py amr_base/test/test_gating.py`. If the `'line'` string matters, add `NAMES[LINE] == 'line'` to test_gating.
- Safety: gating.py is not modified. This only relocates tests.
- Depends: none

**D140 — uturn.counts_for_angle is test-only** (low / S / ~4 lines / build no)
- Keep: nothing in uturn.py · Remove: uturn.py:70-73 counts_for_angle
- Steps: 1. Move it into a shared amr_line test helper. 2. Switch the 7 call sites. 3. Delete it from uturn.py.
- Tests: `pytest -q test_guided_run.py test_marker_run.py test_site_run.py test_mission_engine.py`
- Depends: none

**D31 — Encoder-CPR spelling spread across test plants** (partial; plants stay) (low / S / ~10 lines / build no)
- Keep: amr_sim TapePlant, the test_kink_pivot Plant, harness._integrate (verbatim), test_blindrun 36000 · Remove: test_uturn.py:22 local CPR, test_mission_engine.py:33-34 COUNTS_PER_MOTOR_REV/PER_REV
- Steps: 1. Add `COUNTS_PER_MOTOR_REV=10000` and `counts_step(rpm, dt)` to a shared amr_line test helper. 2. Use it in test_uturn and test_mission_engine.
- Tests: `pytest -q test_uturn.py test_mission_engine.py test_kink_pivot.py`
- Depends: D32 (outside P3)

**D72 — site_fixture copies BINDING/TRUE from test_tape_localization** (partial; DOCs stay separate) (low / S / ~10 lines / build no)
- Keep: test_tape_localization BINDING/TRUE/STATIONS; both DOC dicts · Remove: site_fixture.py:BINDING, :TRUE
- Steps: 1. Wait until the plan-4 test work settles (both files are uncommitted). 2. site_fixture imports BINDING, STATIONS and TRUE and builds `TAUGHT = {**STATIONS, UT-M1, UT-M2}`.
- Tests: `pytest -q test_tape_localization.py test_tape_runtime.py test_trip_route.py test_site_run.py`
- Depends: D11 (outside P3)

**ROS package test fakes**

**D03 — Sim launch-test harness copied across 6 sim tests** (low / M / ~250 lines / build no)
- Keep: each test's own ROS_DOMAIN_ID pin · Remove: `_yaw`/`_call` in test_route_sim, test_run_control_sim (`_yaw`), test_survey_sim and test_amcl_sim; 4 conftest bodies (down to ~3 lines each); test_unified_sim kill_owned/BASE_PATTERN (moved)
- Steps: 1. Add the plain module `amr_sim/amr_sim/testing.py`: call(timeout), yaw_of, QoS, publish_initialpose, drive, localize_at_mark, nav_sim_launch, sim_collect_ignore, spawn_sim_supervisor, kill_owned/BASE_PATTERN. 2. Add `<test_depend>amr_sim</test_depend>` in amr_mission, amr_localization and amr_bringup. 3. Point the conftests at sim_collect_ignore. 4. Migrate one file per change. 5. Set `domains.TEST_RANGE=range(61,70)`, which covers fault_injection's 69.
- Tests: plain pytest on the 4 dirs still skips the sim tests without AMR_SIM_TESTS; test_domains asserts 69; one sequential opt-in sim run at the milestone
- Depends: none

**D19 — Null logger / Clock / service-client / supervisor fakes duplicated** (low / S / ~60 lines / build no)
- Keep: test_survey_move_node Log (it checks severity); a local subclass wherever a test relies on a quirk (test_hardness RecLog) · Remove: the duplicate Log/Logger/_Logger/Clock/Future/Client classes in the listed files
- Steps: 1. Add a `test/_fakes.py` per package (amr_bringup, amr_mission, amr_base, amr_web), not shared between packages. 2. Replace the local classes with imports. 3. Add `fake_supervisor(methods, **attrs)` in amr_bringup.
- Tests: listed tests, assertions unchanged
- Depends: none

**D37 — Manifest-from-Grid build repeated in fixtures, mapping session and tests** (partial; no publish_grid wrapper) (low / S / ~30 lines / build no)
- Keep: mapping_session stage/serialize/stage_holder flow; test_map_bundle.py:30-50 · Remove: fixtures.py:55-71 and mapping_session_node.py:577-589 Manifest literals; the two `bundle()` bodies; test_server.py:79-90
- Steps: 1. Add `mb.manifest_for(grid, map_id, revision, start, review, software=None, frame_id='map')` and use it in fixtures._write_locked and mapping_session._save_locked. 2. Add `fixtures.write_test_bundle(...) -> rev_dir`. 3. Replace the test helpers; callers that need the manifest use `mb.load_manifest`.
- Tests: test_map_bundle (add a manifest_for field check), test_continue_survey, test_continue_survey_supervisor, amr_web test_server
- Depends: none

**D66 — Gating fixtures redefined in amr_base tests** (low / S / ~20 lines / build no)
- Keep: gating.py untouched · Remove: SUP/INST/lease/panel/drives duplicates in test_authority, test_pendant_gating, test_r02_r03_manual_intake
- Steps: 1. Add `gating_fixtures.py` with SUP, SUP_TELEOP (teleop_enabled=True), INST, panel(), drives() and `lease(t=10.0, gen=3, allowed=..., seq=10, inst=INST)`. 2. Callers pass `allowed` explicitly. 3. Swap the imports.
- Tests: test_authority, test_pendant_gating, test_r02_r03_manual_intake, test_gating, test_field_limit
- Depends: none

**D84 — FakeLink/Frame duplicated in amr_base MLS tests** (low / S / ~16 lines / build no)
- Keep: test_mls_track FakeLink/Frame · Remove: test_mls_imu.py FakeLink/Frame; test_pp_drivelink.py:62 literal tuple
- Steps: 1. test_mls_imu imports FakeLink and Frame from test_mls_track. 2. test_pp_drivelink:62 asserts against `guard.PP_CONFIG_READ_ONLY`, so 0x60F2 is now covered too.
- Tests: `pytest -q test_mls_imu.py test_mls_track.py test_pp_drivelink.py`
- Depends: none

**D127 — test_raycast lives in amr_sim but tests amr_maps** (partial; box builders stay) (low / S / ~0 lines / build no)
- Keep: its own box_world; test_relocalize helpers · Remove: amr_sim/test/test_raycast.py (moved)
- Steps: 1. `git mv` it to amr_maps/test. 2. Check that the generate_sim_factory import resolves.
- Tests: `pytest -q amr_maps/test/test_raycast.py`
- Depends: none

**amr_web tests and frontend**

**D05 — Five hand-rolled adapter stubs, a stale Protocol, 11 hasattr guards** (low / M / ~130 lines / build no)
- Keep: the hasattr guards where DemoAdapter deliberately lacks `live` · Remove: server.py:53-56 survey_* from the Protocol; per-file Stub classes (overrides only stay); the other hasattr guards
- Steps: 1. Regenerate the Protocol from the `adapter.*` calls in server.py. 2. Add `test_adapter_contract.py`: RosAdapter, DemoAdapter and StubAdapter each define every member. 3. Add `amr_web/test/conftest.py` with `StubAdapter(state, live, strict)` and `make_client(tmp_path, stub)`; convert one file at a time. 4. Remove a guard only after the contract test proves both real adapters implement that method.
- Tests: new contract test; existing amr_web tests unchanged. Failure mode: a guard removed early gives AttributeError on /diagnostics or the map routes in demo mode. Recovery: restore the guard.
- Depends: none

**D09 — Node JS harnesses re-implement fake DOM/MapView/api** (low / M / ~100 lines / build no)
- Keep: run.js:193 `typeof graphOverlay` guard (unless run.html is shown to always load tapegraph.js) · Remove: fake DOM/MapView/api blocks in the 4 `*_harness.js`; 9 repeated which/run/parse blocks
- Steps: 1. Extract `harness_common.js` (makeEl, makeDoc, FakeMapView, scriptedApi, loadPage, flush). 2. Add a module-scoped `run_harness(name)` fixture. 3. Stop test_editor_js re-running its harness 5 times.
- Tests: existing JS tests, same assertions; still skip when node is absent
- Depends: none

**D131 — LINE/locator level maps, no-line tile and motion warn-box repeated** (partial) (low / S / ~6 lines / build no)
- Keep: same classes and text · Remove: teach.html:67 HEALTH map; run_tracked.html:145 inline map; tile literals run_tracked:126 / teach:118
- Steps: 1. Move LINE_LEVEL into amr.js; add LOC_HEALTH_LEVEL and `noLineTile(label, inLine)`. 2. Use them in run_tracked, teach and guide (guide:123). 3. Add `_motion_note.html` with a tail variable, included by run, run_tracked, teach, guide and calls.
- Tests: test_teach_page plus the run/guide page tests (check nothing greps the inline maps); fit at UI scale `l`
- Depends: none

**D128 — Undo/redo snapshot stacks and mm duplicated in editor.js/review.js** (low / S / ~6 lines / build no)
- Keep: editor's draftToken/lastResult/savedRef invalidation, moved into onChange · Remove: editor.js:23-25,28; review.js:30,32-34; the history/future resets
- Steps: 1. Add `History(get, set, onChange)` to mapview.js and `mm` to amr.js. 2. Port editor, then review. 3. Resets become `hist.clear()`.
- Tests: amr_web page tests; manual undo/redo on Editor and Review
- Depends: none

**D96 — Initial map selection copied in review.js and survey_continue.js** (partial; selectMap stays per page) (low / S / ~6 lines / build no)
- Keep: per-page selectMap; editor/run one-line bootstraps · Remove: review.js:130-133, survey_continue.js:87-90
- Steps: 1. Add `initialMapSelection(sel, msgEl)` to mapview.js. 2. Use it in both IIFEs. 3. In the same change, inject it into the review_harness.js:33-36 vm context.
- Tests: test_review_js (`first_load == ['m1/1']`)
- Depends: none

**D97 — Drag-to-heading pose tool on MapView** (partial; editor stays) (low / S / ~5 lines / build no)
- Keep: editor.js (multi-tool setTool); run.js viewIsActive/poseGen guard in onPose · Remove: run.js:19-22,30; survey_continue.js:39-41,45
- Steps: 1. Add `MapView.poseTool(name, {onPose, onPreview})`. 2. Port run.js, then survey_continue.js.
- Tests: no harness covers this. On the sim HMI, check initialpose by hand and check the continue-survey hint. Wrong yaw mislocalises AMCL.
- Depends: none

**D120 — MapView image loader x3, path builder x3** (low / S / ~4 lines / build no)
- Keep: polyline/polygon/fillPolygon signatures · Remove: mapview.js:80,84,97 inline Image promises; :178,179,181 loops
- Steps: 1. Add `loadImage(src, tolerant)` and `_path(pts, close)`. 2. Rewrite the callers on them. 3. Smoke Maps, Editor and Review.
- Tests: amr_web page tests
- Depends: none

**D98 — demo.css fonts, demo.js reload, reload SVG duplicated** (low / S / ~12 lines / build no)
- Keep: demo.html loading neither amr.css nor amr.js · Remove: demo.css:5-10; demo.js:145-154; amr.js:306-316 (moved); inline SVGs in demo.html:22 and base.html:53
- Steps: 1. Move amr.css:13-30 to `static/fonts.css` and link it from both templates. 2. Add a dependency-free `static/reload.js` bound to `[data-reload]`. 3. Add a `_reload_icon.html` include.
- Tests: assert both templates link fonts.css and reload.js, and that demo.html has no amr.js; `pytest -q test_*demo* test_teach_page.py`
- Depends: D25 (outside P3)

**Docs: link fixes first, then the big moves**

**D88 — Docs link to manuals moved into manuals/obsolete** (low / S / ~0 lines / build no)
- Keep: guard.py refusal strings as they are · Remove: dangling paths (rewritten to `manuals/obsolete/...`, marked historical)
- Steps: 1. Use sed to rewrite paths in agv_core comments/docstrings, README, RUNBOOK and run_all.py:55. 2. Inline the pp.expect/pp.vendor_ref fill procedure at RUNBOOK.md:584 in 3-4 lines. 3. Fix amr_ws/README.md:3-4 together with D21.
- Tests: `python3 tests/run_all.py` (no count change)
- Safety: guard.py is untouched by default. If its strings are edited, the deny-list test must still pass. Recovery: revert the string.
- Depends: none

**D21 — amr_ws/README 'Decisions recorded here' T-log** (partial; reference facts stay) (low / M / ~220 lines / build no)
- Keep: TF tree, Geometry, DDS scope, wire/rate table as "Reference" · Remove: amr_ws/README.md:82-402 T-log (moved, not deleted); :40 agv_controller; :100 app/server.py; :332 legacy_guard; :395 Conflicts= claim
- Steps: 1. Copy :82-402 verbatim to `manuals/obsolete/amr_ws-decision-log.md`. 2. Keep the Reference block. 3. Delete the stale statements. 4. Replace the survey/readiness/execution/permission/panel paragraphs with links to README "How it works" and RUNBOOK §2/§4.
- Tests: `grep -n 'legacy_guard\|agv_controller\|app/server.py' amr_ws/README.md` is empty
- Depends: D88

**D90 — RUNBOOK, alpha-setup, deploy comments describe removed behaviour** (low / S / ~4 lines / build no)
- Keep: rfid-tag-table.md "Speeds" as the only speed text · Remove: RUNBOOK.md:131-133 speed formula
- Steps: 1. RUNBOOK:100: a missing key is refused, there is no default. :104 and :174 Status→Home. 2. RUNBOOK:131-133 becomes a pointer to the tag table. 3. alpha-setup:769-775, 1215, 1256: Home page; foxglove only with AMR_FOXGLOVE=true. 4. amr.env:1-2, amr-supervisor.sh:2-3: boot IDLE, then LINE unless tracked=false. Fix line_layer.launch.py:23.
- Tests: none (comments/docs)
- Depends: none

**D49 — Install steps triplicated** (partial; deploy file headers stay) (low / S / ~30 lines / build no)
- Keep: RUNBOOK §5 as the install procedure; the 2-line headers in deploy files · Remove: alpha-setup.md:704-711 role table, :723-726 journald/swapoff, :735-740 sudoers block (keep the one-line why)
- Steps: 1. Check that RUNBOOK §5 covers sudoers, journald, sysctl, swapoff and the data volume (W8); add what is missing. 2. alpha-setup §6 becomes ordered bullets pointing at the §5 subsections.
- Tests: none
- Depends: D90

**D50 — Stale legacy-controller rationale in agv_core docstrings (shown on /params)** (low / M / ~40 lines / build no)
- Keep: every config.py note heading token (`timing.*`, `vehicle.invert_right`, `rfid.*`, `can.use_rpdo`, `drivers.ramp`/6083h, CF821) · Remove: canmon.py:7-22 canworker text (down to one line); kinematics.py:3-8; config.py:13-14 app.py; config.py:477, 486, 932, 1191 RFID-zone/toggle text; removed-module refs in panel.py, ownerlock.py, events.py, lidarframe.py
- Steps: 1. Rewrite the docstrings as one-liners naming the current owners. 2. config.py: Four→Five; tracked null boots to LINE; /blind and LOCKED wording; RFID zone→MLS marker zone. 3. `python3 tests/run_all.py` and `ruff check .`.
- Tests: test_config.py:458 `test_tuning_notes_are_parsed_not_restated` stays green; no EXPECTED_CHECKS change. A broken heading drops a /params note; recovery is to restore the token.
- Depends: none

**D48 — Speed-zone rules written out in three manuals** (partial; plan-2 and D7 stay) (low / S / ~40 lines / build no)
- Keep: rfid-tag-table.md "Speed zones"/"Speeds" as the rule source; plan-1 rationale, engine design, failure modes · Remove: plan-1 §3 restated rules; the "(replaces the speed toggle)" heading wording at plan-1:86
- Steps: 1. Add "Rules live in rfid-tag-table.md" at the top of plan-1 §3. 2. Collapse the Layout/Corner-entry/Site-table restatements to a link plus rationale.
- Tests: none
- Depends: none

**D91 — tape-localization-runbook §1A duplicates plan-3 §7, wrong "current" values** (low / S / ~12 lines / build no)
- Keep: plan-3 §7.2/7.5 as the source; runbook operator procedure · Remove: runbook :41-42 "(the current values)"; :47-52 strip layout
- Steps: 1. Change :41-42 to: stage 1 uses test-mru-straight / C-STRAIGHT; the profile holds site-103 / C-MRU, so switch it first. 2. Replace the strip list with a link to plan-3 §7.5 plus the drawing; keep the one-line FAULT/backstop action.
- Tests: none
- Depends: none

**D89 — README.md stale facts** (low / S / ~5 lines / build no)
- Keep: status-table speed caps unchanged · Remove: "531 checks" x3; motion.py in the module list; "35" gains; "RFID high zone" in the status table
- Steps: 1. Refer to EXPECTED_CHECKS instead of a count. 2. Build the module list from `ls agv_core/*.py`. 3. State the MLS rate once, linking the amr_ws wire table; cue becomes "MLS marker zone". 4. Update Known gaps.
- Tests: none
- Depends: none

**D104 — tests/helpers.py docstring says the plant rig is gone** (partial; reporters not merged) (low / S / ~8 lines / build no)
- Keep: harness.py FAIL/CHECKS/check unchanged · Remove: helpers.py:3-14 stale paragraph
- Steps: 1. Replace it with a 3-line pointer to amr_line/test/harness.py and amr_sim/tape_plant.py.
- Tests: none
- Depends: none

**D01 — lidar profile section / lidarframe stale comments** (partial; comment fix only) (low / S / ~10 lines / build no)
- Keep: lidarframe.py, test_lidar.py and the fixture (survey decision); profile `lidar` host_ip/sensor_ip/port/zones_validated (planned P2-4 single source) · Remove: nanoscan3.yaml:12-15 lidar_scan.py sentence; config.py:552-556 bench-tool claim
- Steps: 1. Reword both: the keys feed the lidarframe fixture decoder and the planned launch wiring. 2. Owner decision: if the survey decision is dropped, retire zone_block, zone_bytes, zone_active_low, reassembly_timeout_s and enabled with refusal tests, delete the decoder files, and set EXPECTED_CHECKS −36 plus the refusals.
- Tests: comment-only, so no test change
- Depends: none

**D51 — Foxglove defaults conflict between env, shell and node** (partial; retirement is an owner decision) (low / S / ~10 lines / build no)
- Keep: amr.env as the source of service switches; launch_helpers.foxglove() · Remove: the conflicting `${AMR_FOXGLOVE:-true}` and `dp('foxglove', True)` defaults; alpha-setup.md:709 "all true"
- Steps: 1. Set the supervisor default and the shell fallback to false. 2. validate.sh flags a fallback that contradicts amr.env. 3. Fix alpha-setup:709 and RUNBOOK:4 ("optional, off by default"). 4. Ask the owner whether Foxglove is retired; if yes, a later item removes the group, the package.xml dep and the launch args.
- Tests: `bash deploy/validate.sh`; test_hardness/supervisor param tests. A manual script run without env now gets foxglove off; recovery is `AMR_FOXGLOVE=true`.
- Depends: none

**Code structure**

**D28 — verify_drivers.main duplicates verify_bus** (low / S / ~45 lines / build no)
- Keep: verify_drivers library exports (sdo_read, open_bus, claim_bus, used by canopen.py and drive_node.py); EXPECTED/DEVICE_TYPE_EXPECTED · Remove: verify_drivers.py:main steps 1-4 body (183-256)
- Steps: 1. Parameterise the verify_bus helpers on expected/scan_range (defaults = current constants). 2. Add `verify_bus.run(...)` returning rc, with strict_type, identity_only_expected, per-node hints and dead_help. 3. verify_drivers.main does claim/open plus a lazy import and `run(scan_timeout=0.25, listen_s=2, strict_type=True, hints={2: ID-SEL})`.
- Tests: new `tests/test_verify_bus.py` with a fake bus (rc and hint for found={1,2}, {1}, wrong type); EXPECTED_CHECKS updated deliberately; no hardware run
- Depends: none

**D54 — mapping.launch.py / nav.launch.py duplicate base, args, web node** (partial; sim/drivers launches stay) (low / S / ~25 lines / build no)
- Keep: sim.launch.py, drivers.launch.py; file names and arg names/defaults · Remove: `_base`, duplicated DeclareLaunchArguments and the web Node in both
- Steps: 1. Add `standalone_args()`, `standalone_base(context, **extra)` and `standalone_web()` to launch_helpers.py. 2. Both files call them; nav passes panel_auto.
- Tests: test_launch_layers.py (if it parses them); sim tests at the milestone only
- Depends: none

**D69 — runtime._FROM_PROFILE is an identity map** (low / S / ~3 lines / build no)
- Keep: grouping comments; _DERIVED; autopilot.py untouched · Remove: dict values; runtime.py:30-33 "None means derived" comment
- Steps: 1. Convert to a tuple. 2. Line 117: `missing = [k for k in _FROM_PROFILE if not hasattr(config, k)]`. 3. Line 125: `ns = {k: getattr(config, k) for k in _FROM_PROFILE}`.
- Tests: `pytest -q test_control.py test_line_authority.py test_ramp_scurve.py test_tape_plant.py`
- Depends: none

**D107 — PanelScan re-implements the DebouncedLevels core** (medium / S / ~10 lines / build no)
- Keep: PanelScan API (scan, reset, mode); panel_io.py unchanged · Remove: PanelScan `_candidate`/`_count` bookkeeping (panel.py:65-67, 70-74, 104-112)
- Steps: 1. PanelScan wraps `DebouncedLevels(channels, debounce_scans)` and applies polarity. 2. Edges come only from a change in the stable tuple; the first stable tuple is the baseline with no edges. 3. Keep the reset-on-reconnect and malformed-image→IDLE branches explicit.
- Tests: `pytest -q tests/test_panel.py amr_base/test/test_panel_io*.py` unchanged; optionally add "Start held through a comms drop gives no edge after reconnect" (EXPECTED_CHECKS +1, deliberately)
- Safety: Start-edge path (agv_core/panel.py). Failure mode: a phantom Start edge after reconnect (for example a tied-down button) arms AUTO with nobody at the box. test_panel hazard tests 1-3 catch it. Recovery: revert panel.py. FX3/STO stays in the safety path. Do this late.
- Depends: none

**D86 — map_bundle lives in amr_mission but is a map-layer library** (medium / M / ~8 lines / build yes)
- Keep: the same API at `amr_maps/amr_maps/bundle.py`; a re-export shim in amr_mission/map_bundle.py until grep is clean · Remove: amr_navigation validate.py:49-52 load_mask; amr_line package.xml:18 amr_mission dep; the old map_bundle body (shim, then deleted)
- Steps: 1. `git mv` and add a shim that re-exports public plus test-used underscore names. 2. validate.load_mask re-exports bundle.load_mask. 3. package.xml: amr_line gets exec_depend amr_maps and drops amr_mission. 4. Migrate imports package by package, amr_line last. 5. Drop the shim when `grep 'amr_mission import map_bundle'` is empty; move test_map_bundle to amr_maps/test.
- Tests: `pytest -q test_map_bundle.py test_r27_save_rollback.py test_continue_survey.py amr_navigation/test/test_route.py amr_web/test/test_server.py`; colcon build and re-source. A missed lazy import fails only when invoked; the shim covers it.
- Depends: none

**D78 — Three encounter-stream cursors** (partial; node builders stay) (medium / S / ~6 lines / build no)
- Keep: each consumer's policy (link_lost strings, first-gap check, last-tag, missed count); line_follow_node builders · Remove: TapeRun.scan :284-293; TagOdometer.update :125-140 cursor bookkeeping; MarkerReader.scan :32-41
- Steps: 1. Add a pure `EncounterCursor.advance(snapshot, *, seed)` to marker_reader.py. 2. Port MarkerReader, then TagOdometer, then TapeRun (verbatim strings).
- Tests: new test_encounter_cursor.py (generation reset, gap, first sight); test_tape_run, test_tag_table and test_marker_reader unchanged. A wrong port means a missed tag might not raise link_lost; recovery is to revert the file.
- Depends: none (plan-4 live code, so land after it settles)

**D108 — blindrun midpoint step repeats diff_drive.integrate** (partial; pose_delta stays) (low / S / ~4 lines / build no)
- Keep: unwrapped heading in blindrun; the wrap in diff_drive; pose_delta · Remove: blindrun.py:207-212 inline step
- Steps: 1. Add an unwrapped `kinematics.midpoint_step(x, y, th, left_m, right_m, track_m)`. 2. Use it in both. 3. Only do this when either file is touched for another reason.
- Tests: `python3 tests/run_all.py` (+1 if a check is added, deliberately); `pytest -q amr_base/test`
- Depends: none

**D135 — job.py tape-gone debounce counters** (partial; tape_run unchanged) (low / S / ~4 lines / build no)
- Keep: tape_run req['gone']; the constants; each reset predicate verbatim · Remove: job.py:1056-1061, 1083-1088 counter arithmetic
- Steps: 1. Only when job.py is next touched: add `Debounce(n)` with `.step()` and `.clear()` and use it for _edge_gone/_end_gone.
- Tests: `pytest -q test_site_run.py test_tape_runtime.py` plus the kink/U-turn job tests
- Depends: none

**D92 — Commissioning evidence JSON has no reader** (partial; no removal) (low / S / ~0 lines / build no)
- Keep: the blindrun/commissioning chain, msgs, srv and lease-bit-4 interlock · Remove: nothing
- Steps: 1. Optional: reports.build zips the newest N `<state_dir>/commissioning/*.json` under logs/commissioning/. 2. Retiring the chain is an owner decision, outside this plan.
- Tests: if the reports change, extend the amr_web report test for the newest-N files
- Depends: none

**D61 — QoS profiles and shared topic names restated at every endpoint** (partial; no full registry) (medium / L / ~40 lines / build no)
- Keep: each endpoint's current QoS exactly; depth-10 lease subscriptions as documented overrides; run_log.sh regex, with a comment pointing at nav_topic · Remove: 9 duplicate RELIABLE_1 definitions; repeated `/amr/control_lease`, `/amr/panel_state`, `/amr/events`, `/amr/line_cmd` literals
- Steps: 1. Land D07 qos.py. 2. Add `amr_base/topics.py` with the 8 most-shared names and `layer_pattern()` derived from gating.nav_topic. 3. Migrate node by node. 4. bag_report uses topics/layer_pattern.
- Tests: contract test that topics.* and the qos profiles equal the current literals; focused node tests; unified sim once at the milestone
- Safety: touches cmd_mux_kinematics_node.py (and drive_node and panel_node). Failure mode: a QoS mismatch silently drops lease or panel messages, the lease goes stale, and mux and drive stop (fail-closed). The contract test and the sim catch it. Recovery: revert that node's import.
- Depends: D07 (outside P3)

**D114 — fake_panel and panel_node build PanelState separately** (partial; fake keeps bypassing PanelAdapter) (low / S / ~6 lines / build no)
- Keep: the fake bypassing PanelAdapter.tick (back-to-back set_mode/press_start in the sim tests) · Remove: fake_panel_node.py:78-87 and panel_node.py:162-171 field-by-field fill
- Steps: 1. Add `amr_base/panel_msg.py:to_msg(frame, stamp)`. 2. panel_node uses it. 3. The fake builds a `PanelFrame(valid=True, ...)` and calls to_msg. 4. Apply the shared `_ui` throttle after D100.
- Tests: `pytest -q amr_base/test/test_panel_io.py` plus a to_msg mapping test that includes manual_arm; unified sim at the milestone only
- Depends: D100 (outside P3)

**D146 — Executor keeps the removed obstruction check's /scan_gated plumbing** (low / S / ~3 lines / build yes)
- Keep: the /scan_gated subscription as a freshness prerequisite; RunState BLOCKED value (wire unchanged) · Remove: route_executor_node.py:288 `self._scan`; the :319-321 obstruction rationale
- Steps: 1. `_on_scan` stores only `_scan_t`, seeded as never-received (None), never as fresh. 2. :595 tests whether `_scan_t` is None or stale. 3. Reword :319-321 and the scan_gate.py:12-14 consumer list. 4. RunState.msg:6 comment: "held with a cause (hold_cause)". 5. test_route_executor_logic sets `_scan_t`.
- Tests: `pytest amr_mission/test/test_route_executor_logic.py`; colcon build for the .msg comment
- Depends: D04 (outside P3)

## 4. Item table

| id | phase | title | verdict | risk | effort | ~lines | build | safety |
|---|---|---|---|---|---|---|---|---|
| D103 | P0 | Unused members in supervisor/operations/process_supervisor/scanner_fields | partial | low | S | 5 | no | — |
| D112 | P0 | Unused functions in the tape-localization core (route_for, lateral_to, Route.stop) | partial | low | S | 7 | no | — |
| D121 | P0 | amr_interfaces SafetyFieldStatus.msg is generated but never used | keep | low | S | 8 | yes | — |
| D122 | P0 | Junction slow-zone path unreachable since slow_speed was retired | keep | low | S | 4 | no | — |
| D125 | P0 | rpdo.configure bool-return branch and stale canworker/tune_mls/motion.py references | keep | low | S | 5 | no | — |
| D126 | P0 | square_drive closing_error_m/deg parameters declared but never applied | partial | low | S | 9 | no | — |
| D133 | P0 | Dead Home CSS/JS: .home-big.warn/.error never match; 2-column .home-live and live-marker guard superseded | keep | low | S | 5 | no | — |
| D138 | P0 | Catalogue code EXEC_ROUTE_INVALID is never emitted | keep | low | S | 4 | no | — |
| D139 | P0 | Small production helpers with no production caller (runtime.snapshot, is_loaded, cell_to_world, protocol constants, guard query API) | partial | low | S | 4 | no | — |
| D154 | P0 | blindrun.RESULTS_KEPT unused | keep | low | S | 2 | no | — |
| D161 | P0 | Entry point amr_bringup 'amr_supervisor' has no caller | keep | low | S | 1 | yes | — |
| D47 | P0 | 0910-fix-plan-001.md is fully superseded | keep | low | S | 227 | no | — |
| D52 | P0 | amr-launch.sh is an unused legacy-unit wrapper; PYTHONPATH injection exists three times | keep | low | S | 35 | no | — |
| D56 | P0 | tests/helpers.py _FakeRaw SDO fake bus has no users | keep | low | S | 55 | no | — |
| D57 | P0 | alarms.decode_statusword_flags / SW_FLAGS: no caller since U11 | keep | low | S | 36 | no | — |
| D67 | P0 | Web adapter direct coordinator survey clients (survey_start/returned/save/abort) are dead behind the supervisor | keep | low | S | 23 | no | — |
| D82 | P0 | RfidLink.snapshot fields with no consumer (tag, silent, identity, heartbeat, tags_seen, bad_frames, detail, epc, antenna, carrier, last_tag) | keep | low | S | 12 | no | — |
| D83 | P0 | DriveLink.arm() is test-only | keep | low | S | 12 | no | — |
| D99 | P0 | ownerlock.holder() and unused resources 'app'/'scanner' | keep | low | S | 18 | no | — |
| D02 | P1 | Profile keys validated but never read (dry_run, use_rpdo, monitor/imu/telemetry periods, manual_watchdog_s, tape_loc.lost_fault_s), some contradicting the ROS params that rule | partial | low | M | 150 | no | — |
| D04 | P1 | Wire enum name tables (Mode/Run/Survey/Mapping/Loc/Line/Mux/Operation/Commissioning) copied across supervisor, web, demo, commissioning_node, panel_io, readiness, bag_report and tests, with no contract test | keep | low | M | 70 | no | amr_base/amr_base/panel_io.py (test only, optional import) |
| D06 | P1 | tools/demo_server.py fakes adapter state, supervisor rules, horn, DIO names and kinematics instead of reusing real code (and has drifted) | keep | low | M | 60 | no | — |
| D07 | P1 | QoS profiles (RELIABLE_1, LATCHED, SENSOR_DATA, depth-50 event stream) redefined in ~25-40 modules | keep | low | M | 100 | no | amr_ws/src/amr_base/amr_base/cmd_mux_kinematics_node.py |
| D10 | P1 | rclpy main() spin/shutdown boilerplate in ~17-20 nodes; sim nodes not on LeanNode | keep | low | M | 100 | no | — |
| D100 | P1 | '_ui' display-copy throttle hand-rolled in 4 producers; sim tape_synth has no _ui copy | partial | low | S | 4 | no | — |
| D101 | P1 | Group.spawn(role, argv, env, log_path) repeated 4 times; foxglove launch name hard-coded twice | partial | low | S | 8 | no | — |
| D102 | P1 | _srv_mode and _srv_survey repeat the same preamble and reach into OperationBook._by_request | keep | low | S | 8 | no | — |
| D106 | P1 | Obstacle dilation implemented 3x (scan_consistency.occupied_near, relocalize.proximity, footprint.dilate) | partial | low | S | 10 | no | — |
| D109 | P1 | Page JS hard-codes Python constants (editor route bounds and legacy speed keys, jogpad speeds/track, maps.html spin steps) | keep | low | M | 10 | no | — |
| D110 | P1 | drive_node re-declares profile values as never-overridden ROS params (mls_track_variant, imu_enabled, monitor_enabled, driver_timeout_s, rate_hz) | keep | low | S | 5 | no | — |
| D111 | P1 | Auto-resume delay under two names (profile auto_resume_hold_s vs ROS param auto_resume_clear_s) with separate defaults | partial | low | S | 1 | no | — |
| D113 | P1 | Time-indexed travel interpolation in tools/p0_report vs tape_locator.OdomBuffer | keep | low | S | 10 | no | — |
| D115 | P1 | Signed-int helpers s16/s8 written 4 times; gyro scaling re-implemented in mls_imu | partial | low | S | 5 | no | — |
| D116 | P1 | Track-over-SDO object list duplicated (read_mls.live_values vs mls_track.SDO_ITEMS) | keep | low | S | 6 | no | — |
| D117 | P1 | pp.authority_gate re-implements lease freshness/generation on tuples; drive_node caches PanelState twice | partial | low | S | 4 | no | — |
| D118 | P1 | api_line_site imports/guards agv_core.config twice; machine circuit-order re-derived beside trip.Trip | partial | low | S | 4 | no | — |
| D119 | P1 | Map meta dict for MapView built three times | partial | low | S | 3 | no | — |
| D123 | P1 | Per-generation file names duplicated; loc_map_gen files never swept | keep | low | S | 2 | no | — |
| D130 | P1 | MLS LCP dot placement and freshness rule duplicated between linetrack.js and Home | partial | low | S | 5 | no | — |
| D132 | P1 | Engineer-role check copy-pasted in five /api/line routes | keep | low | S | 5 | no | — |
| D134 | P1 | home.html wires Recover and Restart twice | keep | low | S | 4 | no | — |
| D14 | P1 | Operator Event builder and alarm severity->Event.level map copied into ~8 nodes | keep | low | M | 55 | no | — |
| D141 | P1 | Arc sampling written twice in page JS; editor executor-pose overlay still on the old active-map rule | partial | low | S | 5 | no | — |
| D142 | P1 | MULTI_NLCP/SINGLE_NLCP defined three times, with a 4th consumer importing a copy | keep | low | S | 3 | no | — |
| D143 | P1 | Boot-ready transition written twice in supervisor _tick | keep | low | S | 3 | no | — |
| D145 | P1 | Product name mapping {True:'tape', False:'slam'} duplicated | keep | low | S | 2 | no | — |
| D147 | P1 | footprint.arc_poses re-derives compiler.arc_pose inline | keep | low | S | 3 | no | — |
| D148 | P1 | rfidTags() re-derives the reader status text rfidReading().why computes | keep | low | S | 2 | no | — |
| D149 | P1 | tools/run_log.sh hand-copies the vehicle ROS env without CYCLONEDDS_URI and re-defaults the profile path | keep | low | S | 3 | no | — |
| D15 | P1 | Safety-hold / auto-resume / premove / prereq-debounce policy implemented twice (SLAM executor vs LINE job) | partial | low | S | 25 | no | — |
| D150 | P1 | RFID pass log line formatted in agv_core and regex-parsed back in bag_report | partial | low | S | 3 | no | — |
| D151 | P1 | U-turn re-arm margin defined in both mission loader and uturn | keep | low | S | 1 | no | — |
| D152 | P1 | Tape-graph leg id format defined twice (persisted wire format) | keep | low | S | 2 | no | — |
| D153 | P1 | Tape initial-pose covariance (5 cm / 0.03 rad) in node and launch helper | keep | low | S | 2 | no | — |
| D155 | P1 | Two different ago helpers with colliding global names | keep | low | S | 2 | no | — |
| D156 | P1 | `const $ = id => document.getElementById(id)` defined in 9 page scripts | keep | low | S | 10 | no | — |
| D157 | P1 | MUST/SHOULD tier constants defined twice | keep | low | S | 1 | no | — |
| D158 | P1 | Route repeat bound duplicated: route.MAX_REPEAT vs run_fsm.MAX_PASSES | keep | low | S | 1 | no | — |
| D159 | P1 | 'Run is live' state set duplicated between alarms.headline and service restart | partial | low | S | 1 | no | — |
| D160 | P1 | drive_node rebuilds config.NODES | keep | low | S | 1 | no | — |
| D165 | P1 | scanner_fields.yaml field path reaches only the mux; follower/executor hard-default field_output_index 0; mounted FOV in two places | keep | low | S | 0 | no | — |
| D166 | P1 | Readiness Limits defaults restated as ROS parameter defaults in localization_monitor_node | keep | low | S | 0 | no | — |
| D167 | P1 | LineTrack.source wire vocabulary ('tpdo'/'sdo') compared as literals in four consumers | keep | low | S | 0 | no | — |
| D17 | P1 | Three immutable revision stores re-implement lock/fsync/sha/plain-name/revision/publish primitives | keep | low | M | 50 | no | — |
| D20 | P1 | Angle wrap, quaternion<->yaw, SE2 compose and SLAM correction math copied ~20 times | partial | low | M | 45 | no | — |
| D22 | P1 | ControlLease replay/ordering intake filter implemented five times in two variants | keep | medium | S | 20 | no | amr_ws/src/amr_base/amr_base/gating.py, amr_ws/src/amr_base/amr_base/cmd_mux_kinematics_node.py |
| D23 | P1 | Mux/gating timeouts, pendant caps and scanner-field defaults stated 3-4 times (gating dataclasses, cmd_mux declares, base.launch, other nodes, jog.py), two already disagree | partial | medium | M | 20 | no | amr_ws/src/amr_base/amr_base/gating.py (read only), amr_ws/src/amr_base/amr_base/cmd_mux_kinematics_node.py |
| D24 | P1 | State/maps directory defaults and state-dir sub-layout spelled in ~24 places with inconsistent env handling | keep | medium | M | 30 | no | — |
| D29 | P1 | Log/journal file helpers re-implemented: numbered rotation, atomic JSON write, JSONL append/tolerant read, keep-newest prune, timestamp stems | partial | low | M | 40 | no | — |
| D30 | P1 | DriveStatus torque-off/standby/safety-reset/wheel-stillness/field-status predicates re-coded per node with diverging thresholds | partial | low | S | 20 | no | — |
| D32 | P1 | Wheel travel computed twice per tick from two sources (unwrapped pos_rad vs raw counts re-unwrapped) with three helper copies | partial | low | S | 12 | no | — |
| D33 | P1 | INT32 6064h counter-wrap delta implemented 3x plus inverse/count emulation in fake_base | keep | low | S | 18 | no | — |
| D34 | P1 | Wheel rad/s per motor r/min and inversion sign derived ad hoc in 4-5 places beside canopen.WheelScale; tape_synth latent sign bug | keep | low | S | 15 | no | amr_ws/src/amr_base/amr_base/cmd_mux_kinematics_node.py (constant import only) |
| D35 | P1 | Differential-drive geometry from two sources (profile-driven kinematics vs never-overridden ROS params, URDF/xacro, tools, tests) | partial | low | S | 10 | no | amr_ws/src/amr_base/amr_base/cmd_mux_kinematics_node.py |
| D38 | P1 | Map revision resolution / manifest verification implemented 5-6 times | partial | low | S | 12 | no | — |
| D40 | P1 | Occupancy threshold 65 and trinary grid->grey image (254/205/0) re-coded across the stack | keep | low | S | 18 | no | — |
| D41 | P1 | CiA 402/301 and bench constants scattered (COB_DISABLED x4, CW 0x000F x3, 0x6F/0x27, MODE_PV literal, transmission 255, NMT bytes, EMCY/HB bases, 0x7FF, node/bitrate/device-type/ANSI) plus unused doc constants | partial | low | M | 25 | no | — |
| D42 | P1 | PDO disable-remap-enable step builder written twice (rpdo vs canopen TPDO) | partial | low | S | 10 | no | — |
| D44 | P1 | Bench SDO writes bypass guard.py (drive_forward, read_imu) while read_mls and DriveLink are guarded | keep | medium | S | 5 | no | agv_core/drivers/canbus/guard.py |
| D46 | P1 | ControlLease.allowed bit constants defined six+ times (incl. literal 1/4/8 in web adapter) | keep | low | S | 6 | no | — |
| D58 | P1 | mission.py validates U-turn approach blocks three times | keep | low | S | 22 | no | — |
| D59 | P1 | Event ring append duplicated inside RosAdapter (_on_event/emit/restore) and again in DemoAdapter | keep | low | S | 22 | no | — |
| D60 | P1 | Hand-rolled page poll loops (11 copies); five stop for good after one network error | keep | low | S | 20 | no | — |
| D62 | P1 | Panel/drives/mux freshness verdict and status text computed in Python alarms, amr.js rail and Home (mirrored FRESH_S, 'standby' literal) | partial | low | S | 8 | no | — |
| D63 | P1 | Three /api/alarms pollers: amr.js onAlarms registry unused; Home and Alarms run their own loops and duplicate row markup | keep | low | S | 20 | no | — |
| D64 | P1 | POST-and-report handlers repeated across pages (guide.html x4, ~14 inline api().then(log) handlers with inconsistent status/ok rule) | keep | low | S | 30 | no | — |
| D68 | P1 | 'Can this revision be continued' (pose-graph files) checked 3x with 3 copies of the file list; readiness re-reads manifest | keep | low | S | 12 | no | — |
| D70 | P1 | Vestigial 'speed' section machinery in config.describe() after the manual section was retired | keep | low | S | 20 | no | — |
| D71 | P1 | TF lookup -> (x, y, yaw)/stamp boilerplate repeated in SLAM nodes | keep | low | S | 22 | no | — |
| D74 | P1 | marker_expectation hard-codes the values read_mls.MARKER_SETTINGS already holds | keep | low | S | 6 | no | — |
| D75 | P1 | Approach deceleration (v^2-c^2)/(2d) and braking envelope sqrt(v_end^2+2ad) written independently in several engines | partial | low | S | 4 | no | — |
| D76 | P1 | mission.py checks measured-stop feasibility three times | keep | low | S | 8 | no | — |
| D77 | P1 | mission.load() duplicates _read_doc(); parse()/parse_site() duplicate the error wrapper | keep | low | S | 14 | no | — |
| D79 | P1 | MLS rediscovery/backoff logic duplicated in MlsTrack and MlsImu | keep | low | S | 10 | no | — |
| D80 | P1 | rfid_survey re-implements RfidLink's connect/handshake/recv/dispatch loop | keep | low | S | 15 | no | — |
| D87 | P1 | Mask loader duplicated (validate.load_mask vs map_bundle.load_mask) plus trivial keepout_misalignment wrapper | keep | low | S | 6 | no | — |
| D93 | P1 | readiness.py alias shim re-exports agv_core.disk | keep | low | S | 11 | no | — |
| D94 | P1 | Three near-identical int-list readers in config.py plus an unreachable fallback | keep | low | S | 12 | no | — |
| D08 | P2 | agv_core/events.py ring buffer is written by DIO/RFID drivers but never read (legacy Flask reader retired at U11) | keep | low | M | 80 | no | — |
| D105 | P2 | Four copy-paste Trigger service handlers in line_follow_node | keep | low | S | 12 | no | — |
| D12 | P2 | trip_route.TripRoute/compile_trip is a second copy of tape_graph.Route/compile_route | keep | medium | M | 40 | no | — |
| D124 | P2 | PC heartbeat cadence kept twice (loop timer and DriveLink.keepalive) | partial | medium | S | 3 | no | — |
| D13 | P2 | Two decision-schedule engines over the locator: P1 Shadow (log) vs TripRoute events + SiteRun, with drifted trigger rules | keep | medium | M | 30 | no | — |
| D144 | P2 | Two 'at HOME' predicates; LineState.at_home not migrated to the trip path | partial | low | S | 2 | no | — |
| D16 | P2 | Two horn engines: legacy horn.* (setpoint-following, disabled) beside dio.motion_on/movement_horn/alarm_on | keep | medium | M | 85 | no | — |
| D164 | P2 | tape_synth_node entry point is not launched anywhere (latent INVERT sign bug) | partial | low | S | 0 | no | — |
| D18 | P2 | canbus has no library home: production imports SDO/bus helpers from bench scripts; bus-session, claim_bus, SDO int-read, NMT, 1018h identity and SDO reply matching repeated | partial | medium | M | 80 | no | — |
| D36 | P2 | Raycasting duplicated: demo_server Sim raycaster, scan_synth mounted geometry, laser-pose compose + LaserScan fill in tests; raycast.mounted/grid pixel helpers test-only | partial | low | M | 30 | no | — |
| D39 | P2 | amr_web/tapegraph_view.py re-implements tape_graph_store's on-disk layout and readers | keep | medium | M | 35 | no | — |
| D43 | P2 | Drive preflight/enable sequence implemented twice (DriveLink vs bench drive_forward) | keep | medium | M | 25 | no | — |
| D45 | P2 | Two MLS marker-edge/abort engines: bench read_mls.MarkerWatch vs runtime marker_events.MarkerDetector (disagree on aborts) | keep | medium | M | 25 | no | — |
| D53 | P2 | Localization group (map_server + AMCL + lifecycle_manager_localization + monitor) built twice | keep | medium | M | 35 | no | — |
| D55 | P2 | canmon.MonitorPoller and canopen.MonitorCursor both iterate objects x nodes | keep | low | S | 30 | no | — |
| D95 | P2 | tape_synth hand-builds LineTrack instead of the drive_node fill / read_mls decoder | partial | low | S | 8 | no | — |
| D01 | P3 | lidar.* profile section, agv_core/lidarframe.py and test_lidar have no runtime consumer | partial | low | S | 10 | no | — |
| D03 | P3 | Sim launch-test harness copied across sim tests (probe helpers, nav.launch include, bundle setup, QoS, _yaw, conftest opt-in, supervisor spawn, domain ids) | keep | low | M | 250 | no | — |
| D05 | P3 | Five hand-rolled amr_web adapter stubs, a stale Adapter Protocol and 12 hasattr guards in server.py | keep | low | M | 130 | no | — |
| D09 | P3 | Node JS page harnesses re-implement fake DOM/MapView/api; Python runners spawn the same harness per test | keep | low | M | 100 | no | — |
| D104 | P3 | check/FAIL/CHECKS reporter duplicated in harness.py; tests/helpers.py docstring says the plant rig is gone | partial | low | S | 8 | no | — |
| D107 | P3 | PanelScan re-implements the DebouncedLevels debounce core | keep | medium | S | 10 | no | — |
| D108 | P3 | Three odometry integrators for the same differential geometry | partial | low | S | 4 | no | — |
| D114 | P3 | fake_panel builds PanelState separately from panel_node and bypasses panel_io | partial | low | S | 6 | no | — |
| D120 | P3 | MapView internals: image loader x3 and polygon path builder x3 | keep | low | S | 4 | no | — |
| D127 | P3 | test_raycast lives in amr_sim but tests amr_maps.raycast; box builder duplicated | partial | low | S | 0 | no | — |
| D128 | P3 | Undo/redo JSON-snapshot stacks duplicated in editor.js and review.js; mm helper duplicated | keep | low | S | 6 | no | — |
| D131 | P3 | LINE state / locator health level maps and LINE-page warn-box / no-line-state tile repeated | partial | low | S | 6 | no | — |
| D135 | P3 | Three 'tape gone for N ticks' debounce counters | partial | low | S | 4 | no | — |
| D136 | P3 | Alarm catalogue well-formedness asserted in two suites | partial | low | S | 3 | no | — |
| D137 | P3 | hold_cause vocabulary typed as bare literals by producers, alarm map and run.js; redundant hold-code fallback in alarm view | partial | low | S | 0 | no | — |
| D140 | P3 | uturn.counts_for_angle is a test-only helper in a production module | keep | low | S | 4 | no | — |
| D146 | P3 | Executor keeps the removed obstruction check's /scan_gated plumbing and docs | keep | low | S | 3 | yes | — |
| D171 | P3 | PP expect object indices duplicated between config and guard deny-list without a cross-check | keep | low | S | 0 | no | — |
| D19 | P3 | Null logger / Clock / service-client / SimpleNamespace supervisor fakes duplicated across ROS package tests | keep | low | S | 60 | no | — |
| D21 | P3 | amr_ws/README.md 'Decisions recorded here' is a historical T-log overlapping README/RUNBOOK and naming removed code | partial | low | M | 220 | no | — |
| D26 | P3 | Library suite blind spots: check() never raises under pytest, test_alarms not in run_all, tools/ tests on no test path | keep | low | S | 0 | no | — |
| D27 | P3 | sys.path bootstrap repeated in 17 amr_line test modules (no conftest) | keep | low | S | 45 | no | — |
| D28 | P3 | verify_drivers.main duplicates verify_bus (listen, scan, identity, verdict) | keep | low | S | 45 | no | — |
| D31 | P3 | Tape plants: amr_sim TapePlant, kink-pivot polyline Plant, harness._integrate, plus encoder-count integration in 4 test plants | partial | low | S | 10 | no | — |
| D37 | P3 | 'Write a grid as the next bundle revision' sequence repeated in fixtures, mapping session and test helpers | partial | low | S | 30 | no | — |
| D48 | P3 | Speed-zone (MLS marker HIGH) rules written out in three manuals | partial | low | S | 40 | no | — |
| D49 | P3 | Install steps triplicated: deploy file headers, RUNBOOK §5, alpha-setup §6 | partial | low | S | 30 | no | — |
| D50 | P3 | Stale legacy-controller rationale in agv_core docstrings and config.py notes (rendered on /params) | keep | low | M | 40 | no | — |
| D51 | P3 | Foxglove 'removed' (139e3a8, AMR_FOXGLOVE=false) but plumbing remains; feature-switch defaults triplicated with conflicting values | partial | low | S | 10 | no | — |
| D54 | P3 | Standalone wrappers mapping.launch.py and nav.launch.py duplicate base selection, args and web node | partial | low | S | 25 | no | — |
| D61 | P3 | Topic contract (name + msg type + QoS) restated at every endpoint; generation-topic pattern copied into tools | partial | medium | L | 40 | no | — |
| D65 | P3 | Two builders of a valid lj.Inputs world and duplicated MLS sensor-dict fixtures (NO_TAPE/CENTRED/sensor()/LEASE_LINE) in amr_line tests | keep | low | S | 30 | no | — |
| D66 | P3 | Gating fixtures (SUP params, INST, MANUAL/AUTO panels, drives, lease builders) redefined in amr_base tests | keep | low | S | 20 | no | — |
| D69 | P3 | amr_line.runtime _FROM_PROFILE is an identity map | keep | low | S | 3 | no | — |
| D72 | P3 | site_fixture.py copies test_tape_localization's site mission, geometry and binding | partial | low | S | 10 | no | — |
| D78 | P3 | Three encounter-stream cursors over the same {generation, seq, encounters} snapshot shape | partial | medium | S | 6 | no | — |
| D84 | P3 | FakeLink/Frame test doubles duplicated across amr_base MLS tests | keep | low | S | 16 | no | — |
| D85 | P3 | test_line_mux tests amr_base.gating from amr_line and overlaps test_gating | keep | low | S | 15 | no | — |
| D86 | P3 | map_bundle lives in amr_mission but is a map-layer library | keep | medium | M | 8 | yes | — |
| D88 | P3 | Docs link to manuals moved into manuals/obsolete | keep | low | S | 0 | no | — |
| D89 | P3 | README.md stale facts (check count, module list, gains count, MLS rate, known gaps) | keep | low | S | 5 | no | — |
| D90 | P3 | RUNBOOK, alpha-setup and deploy comments describe removed/changed behaviour | keep | low | S | 4 | no | — |
| D91 | P3 | tape-localization-runbook §1A duplicates plan-3 §7 and states wrong 'current' profile values | keep | low | S | 12 | no | — |
| D92 | P3 | Blind-run/commissioning chain has no UI caller after /commissioning page deletion; CommissioningState mostly write-only; evidence JSON has no reader | partial | low | S | 0 | no | — |
| D96 | P3 | Map-page bootstrap and token-guarded selectMap copied across review/survey_continue/editor/run | partial | low | S | 6 | no | — |
| D97 | P3 | 'Drag from position towards heading' pose tool implemented three times on MapView | partial | low | S | 5 | no | — |
| D98 | P3 | demo.css re-declares fonts; demo.js re-implements reload button; reload SVG copied | keep | low | S | 12 | no | — |

## 5. Rejected / intentional duplication

Recorded so later sessions do not re-raise them.

| id | title | verdict | reason |
|---|---|---|---|
| D11 | Plan-4 work in progress: 'trip.py wired nowhere' is stale; freeze plan-4 amr_line files from redundancy refactors and fix docs saying 'nothing built' | not-a-candidate | A meta item. 'trip.py wired nowhere' is stale: job.py builds SiteRun and owns CallQueue/Payload, line_follow_node serves /amr/line/trip behind TAPE_LOC_LIVE, and site_run.py, trip_route.py and the plan-4 doc are now tracked in git. The plan-4 status line no longer says 'nothing built' (it now reads 'E0, E1 and the code of E2/E3 built ... tape_loc.live is false'). Stale text remains: config.py:339-341 ('only TEACHES and SHADOWS... nothing it says changes motion'), config.py:358 'site-3' (SITE_SCHEMA is site-4 at mission.py:568), mission.py:479 'schema site-3', and the tape_runtime.py:1-6 docstring ('P1 ... NOTHING here reaches the follower'). |
| D25 | Deprecated visitor Demo page still served (route, module, template, assets, tests) - user decision | intentional | This is not a redundancy. It is one deprecated feature, still deliberately served: server.py:556-569 (line numbers shifted), base.html:46 'route stays until removed', test_demo.py:196 asserts that it still serves. It is wired through setup.py:10 (static/demo/*) and test_live_demand.py:109. Removing it is a feature removal, which is outside a behaviour-preserving plan, so it needs an explicit decision from the user. |
| D73 | Panel edge/tie-down/comms-loss behaviour asserted at two layers | refuted | PanelAdapter is not a thin wrapper. panel_io.py:80-93 adds acquisition counting (the 'scans' dedup, audit R01), same-scan other-input suppression, the comms_ok->valid composition with LOST/invalid change notes, and config wiring of DI indices and auto_when_on. test_panel_io.py:39-95 uses snapshot dicts to check that this wiring keeps tie-down, debounce and re-baseline intact (e.g. :68-82 asserts the 'LOST' text and that the selector moves during the outage). These are integration checks of the wrapper's own logic on the panel's motion-entry path. Trimming them loses coverage. |
| D81 | RfidLink and DioLink share the same thread/snapshot skeleton written twice | refuted | Only start() (5 lines) and _set_detail (3 lines) are really the same. The loops are different. DioLink._run (dio.py:228-243) runs one paced scan per pass and drops/waits only when a scan raises. RfidLink._run (rfid.py:515-523) runs one long session and always drops and waits after it. stop() is also different: DIO waits for a bounded quiesce so the latched coils go low, while RFID shuts the socket down. A shared base class would save about 8 lines and blur a safety-relevant coil-quiesce path. |
| D129 | 'How this revision came to be' text built three ways | refuted | The three outputs differ. maps.js:98-104 derived() builds one escaped ' · '-joined line (dynamic area, continued_from with scan match, edits with counts and note). review.js:83-91 builds two tiles (an area tile and a 'from rev / N edit(s)' tile, unescaped, no continued_from). survey_continue.js:50-58 shows only 'continued from revN'/'surveyed' as a subtitle. A single revisionStory(meta) would change displayed text; the only shared piece is the one-line area product dynamic_cells*res². |
| D162 | pyserial listed as a lazily-imported dependency but nothing imports serial | refuted | pyserial is used. agv_core/drivers/canbus/verify_drivers.py:110 lazily imports `from serial.tools import list_ports` in find_adapter(). open_bus():156 calls it when can0 is not up (the USB CANable lookup), and the bench tools read_imu, lss, read_mls, bus_health, verify_bus and drive_forward all import open_bus. The pyproject.toml:13-15 comment and CLAUDE.md:109 are correct. |
| D163 | /run-trackless route alias has no in-repo link | intentional | server.py:312 /run-trackless is a stacked alias on page_run (zero extra code, 1 decorator); test_operator_ux.py:595 pins it. Possible operator bookmarks on the panel; removing it is a URL-surface change, not redundancy worth a migration. |
| D168 | Junction anchors are read in production but only written by a test | not-a-candidate | Not redundancy. anchors.json is a real production input: ~/.amr/teach/rev-boiacca-map-01-rev1/anchors.json exists, draw_marks.py:122 reads it, and tape-graph-g1/README.md:19 lists the anchors. It is hand-maintained (or was written by an earlier session); tape_runtime._anchors (:347-348,:340,:380) feeds tape_teach.split_pass/build, and tapegraph_view shows it. save_anchors has only the test caller (test_tape_localization.py:550), but it is the store's symmetric writer and costs about 3 lines. |
| D169 | Orphan service endpoints: /drives/arm, /drives/disarm, /drives/ack_fault, /imu/recalibrate, /sim/panel/press_reset have no client | not-a-candidate | Not a redundancy: each endpoint is a single implementation with no duplicate. No create_client for /drives/arm/disarm/ack_fault, /imu/recalibrate, /sim/panel/press_reset (grep; /amr/ack_fault is a different executor service with adapter client). They are documented CLI services in amr_ws/README.md:111,214,223 (not RUNBOOK). Wiring ack_fault is plan P0-5 feature work; removing arm/disarm is a drive_node change needing owner decision. |
| D170 | Write-only wire fields (no in-repo reader) | intentional | Confirmed write-only: line_available (supervisor_node.py:378), inhibit_reason (l.353), track_source/omega_rad_s (line_follow_node.py:834,838), StationDetection station_id/known; no reader in amr_ws/src .py/.js/.html or agv_core. Messages are append-only wire; station_id already carries an 'unused' comment (StationDetection.msg:13). Not a duplicate capability. |
| D172 | Two ruff configs repeat line-length/target/select (intentional) | intentional | pyproject.toml:21-33 and amr_ws/ruff.toml repeat 110/py310/E,F,W,I,B,UP; differences (known-first-party, extend-exclude, cwd contract) are documented in both files and CLAUDE.md. Keep as is. |
| D173 | Verified clean (coverage record): web routes, templates, static assets, CSS, JS, launch files, configs, entry points, publishers, parameters | not-a-candidate | Coverage record. Spot-checks still hold: /run-trackless is at server.py:312, onAlarms is defined at static/amr.js:111 and nothing calls it. Nothing to consolidate. |

## 6. Guardrails against regrowth

Each guardrail below is cheap: a test, a table or one rule. If one adds checks to the library suite, update `EXPECTED_CHECKS` in `tests/run_all.py` deliberately.

| # | Measure | Where | Protects |
|---|---|---|---|
| 1 | **Single-home source scan.** One test with an explicit table mapping each pattern to the module allowed to hold it. It fails when a pattern appears anywhere else. Patterns: `QoSProfile(`, the enum name dicts (e.g. `'STOPPING'` beside `'IDLE'`), `1 << 31`, `>= 65` on grids, the `atan2(math.sin(` wrap, `WHEEL_RAD_S_PER_MOTOR_RPM =`, the `'posegraph.posegraph'` literal, `ExternalShutdownException` outside the run() helper. | `amr_ws/src/amr_base/test/test_single_home.py`, plus a library twin in `tests/` for agv_core literals | D04, D07, D10, D20, D33, D34, D40, D41, D46, D61, D68, D142, D157, D158 |
| 2 | **Wire-vocabulary contract test.** Assert that every consumer table equals the source module: adapter MUX/LINE/MODE/RUN/LOC names vs gating, job, mode_fsm and run_fsm; bag_report tables; ControlLease bits vs `ControlLease.msg`. Also scan job, track and the executor for `_hold('<x>')` literals and require each one to be a `HOLD_CODES` key. Do the same for `'tpdo'`/`'sdo'` against the LineTrack producer constant. | `amr_base/test`, `tests/test_alarms.py` | D04, D46, D137, D167, D159 |
| 3 | **Profile key has a reader.** For each validated profile key, assert that at least one read exists outside `config.py` and the tests, with an explicit allowlist of reserved keys (`tape_loc.lost_fault_s`, with the reason). Add a second scan: a `declare_parameter` whose default comes from `config.*` must be set by some launch file or yaml, or be on an allowlist. | `tests/test_config.py`, `amr_base/test` | D02, D23, D35, D110, D111, D165, D166 |
| 4 | **Adapter Protocol conformance.** Derive the method set server.py calls on `adapter.` by AST scan, then assert that the Protocol, the shared test stub and `DemoAdapter` all implement it. With that in place, unguarded `adapter.emit` and arity drift fail in CI instead of in the demo. | `amr_web/test/test_adapter_contract.py` | D05, D06, D59, D67 |
| 5 | **Shared test fixtures, enforced.** One conftest per package, plus one `sim_harness` module for launch tests. A scan test fails on new `def _yaw`, `def _call`, `class Log`, `class Clock` or `sys.path.insert` in test files outside an allowlist (the __main__-runnable files, the ported harness.py). It also asserts that every sim test pins a `ROS_DOMAIN_ID` inside `domains.TEST_RANGE`. | each package's `test/conftest.py` | D03, D19, D27, D65, D66, D84, D09 |
| 6 | **The library suite must be able to fail.** `check()` raises under pytest. Add a test that compares `run_all.MODULES` with the `tests/test_*.py` glob, and a test that compares the check count in README with `EXPECTED_CHECKS`. Add `tools/` tests to testpaths. | `tests/helpers.py`, `tests/run_all.py`, root `pyproject.toml` | D26, D89, D136 |
| 7 | **CAN layering rule.** An import scan fails if `amr_base` or another drivers module imports from bench scripts (`verify_drivers`, `drive_forward`, `bus_health`) instead of the canbus library modules. A second scan fails on any `sdo_write(` call that does not go through `guard.py`. | `tests/test_invariants.py` (already covers guard) | D18, D28, D41, D42, D43, D44 |
| 8 | **"Where things live" table plus a doc rule.** One table in README.md (and a line in the CLAUDE.md Layout section) that names the home of: QoS, wire names, angle and kinematics math, revision-store primitives, the event builder, node run(), the CAN library, the JS helpers in `amr.js` (`$`, poll, POST-and-report). Rule: README and RUNBOOK state current facts only, and decisions go to git history or `manuals/obsolete/`. Back it with a link test that fails when a live doc or code file cites a path that now exists only under `manuals/obsolete/`. | `README.md`, `CLAUDE.md`, `tests/test_docs_links.py` | D14, D17, D20, D21, D47, D48, D50, D60, D64, D88, D90, D91, D156 |

## 7. Status

| id | phase | status |
|---|---|---|
| D103 | P0 | done |
| D112 | P0 | done |
| D121 | P0 | edited; colcon build pending |
| D122 | P0 | done |
| D125 | P0 | done |
| D126 | P0 | done |
| D133 | P0 | done |
| D138 | P0 | done |
| D139 | P0 | done |
| D154 | P0 | done |
| D161 | P0 | edited; colcon build pending |
| D47 | P0 | done |
| D52 | P0 | done |
| D56 | P0 | done |
| D57 | P0 | done |
| D67 | P0 | done |
| D82 | P0 | done |
| D83 | P0 | done |
| D99 | P0 | done |
| D02 | P1 | done |
| D04 | P1 | done |
| D06 | P1 | done |
| D07 | P1 | done |
| D10 | P1 | done |
| D100 | P1 | done |
| D101 | P1 | done |
| D102 | P1 | done |
| D106 | P1 | done |
| D109 | P1 | done |
| D110 | P1 | done |
| D111 | P1 | done |
| D113 | P1 | done |
| D115 | P1 | done |
| D116 | P1 | done |
| D117 | P1 | done |
| D118 | P1 | done |
| D119 | P1 | done |
| D123 | P1 | done |
| D130 | P1 | done |
| D132 | P1 | done |
| D134 | P1 | done |
| D14 | P1 | done |
| D141 | P1 | done |
| D142 | P1 | done |
| D143 | P1 | done |
| D145 | P1 | done |
| D147 | P1 | done |
| D148 | P1 | done |
| D149 | P1 | done |
| D15 | P1 | done |
| D150 | P1 | done |
| D151 | P1 | done |
| D152 | P1 | done |
| D153 | P1 | done |
| D155 | P1 | done |
| D156 | P1 | done |
| D157 | P1 | done |
| D158 | P1 | done |
| D159 | P1 | done |
| D160 | P1 | done |
| D165 | P1 | done |
| D166 | P1 | done |
| D167 | P1 | done |
| D17 | P1 | done |
| D20 | P1 | done |
| D22 | P1 | done |
| D23 | P1 | done |
| D24 | P1 | done |
| D29 | P1 | done |
| D30 | P1 | done |
| D32 | P1 | done |
| D33 | P1 | done |
| D34 | P1 | done |
| D35 | P1 | done |
| D38 | P1 | done |
| D40 | P1 | done |
| D41 | P1 | done |
| D42 | P1 | done |
| D44 | P1 | done |
| D46 | P1 | done |
| D58 | P1 | done |
| D59 | P1 | done |
| D60 | P1 | done |
| D62 | P1 | done |
| D63 | P1 | done |
| D64 | P1 | done |
| D68 | P1 | done |
| D70 | P1 | done |
| D71 | P1 | done |
| D74 | P1 | done |
| D75 | P1 | done |
| D76 | P1 | done |
| D77 | P1 | done |
| D79 | P1 | done |
| D80 | P1 | done |
| D87 | P1 | done |
| D93 | P1 | done |
| D94 | P1 | done |
| D08 | P2 | todo |
| D105 | P2 | done |
| D12 | P2 | done |
| D124 | P2 | done |
| D13 | P2 | partial (steps 1-3; loc_ok skipped) |
| D144 | P2 | done |
| D16 | P2 | todo |
| D164 | P2 | done |
| D18 | P2 | done |
| D36 | P2 | todo |
| D39 | P2 | todo |
| D43 | P2 | done |
| D45 | P2 | done |
| D53 | P2 | todo |
| D55 | P2 | done |
| D95 | P2 | todo |
| D01 | P3 | partial (comments fixed; retiring the lidar keys is an owner decision) |
| D03 | P3 | todo |
| D05 | P3 | partial (Protocol complete + RosAdapter contract test; stubs and hasattr guards left) |
| D09 | P3 | partial (editor harness runs once per module; harness_common.js not done) |
| D104 | P3 | done |
| D107 | P3 | todo |
| D108 | P3 | todo |
| D114 | P3 | todo |
| D120 | P3 | todo |
| D127 | P3 | done |
| D128 | P3 | todo |
| D131 | P3 | todo |
| D135 | P3 | todo |
| D136 | P3 | done |
| D137 | P3 | partial (vocabulary test; hold_title/run.js not done) |
| D140 | P3 | done |
| D146 | P3 | todo |
| D171 | P3 | done |
| D19 | P3 | partial (null Log in bringup+mission, Clock in web; quirky fakes stay local) |
| D21 | P3 | done |
| D26 | P3 | done |
| D27 | P3 | done |
| D28 | P3 | done |
| D31 | P3 | done |
| D37 | P3 | todo |
| D48 | P3 | partial (pointer + heading; restated rules kept as A1 rationale) |
| D49 | P3 | done |
| D50 | P3 | partial (config/panel/kinematics; canmon, ownerlock, events, lidarframe not reviewed) |
| D51 | P3 | todo |
| D54 | P3 | todo |
| D61 | P3 | todo |
| D65 | P3 | partial (CENTRED/NO_TAPE shared; Inputs builders differ in shape) |
| D66 | P3 | done |
| D69 | P3 | todo |
| D72 | P3 | todo |
| D78 | P3 | todo |
| D84 | P3 | done |
| D85 | P3 | done |
| D86 | P3 | todo |
| D88 | P3 | done |
| D89 | P3 | partial (speed-toggle/high_zone facts fixed; floor-run and RFID-region gaps not re-verified) |
| D90 | P3 | done |
| D91 | P3 | done |
| D92 | P3 | todo |
| D96 | P3 | todo |
| D97 | P3 | todo |
| D98 | P3 | todo |
