# Unified coding plan: hardening, CPU load, external features (2026-10-25, re-checked 2026-10-28)

**Re-check 2026-10-28.** Every WP was compared with the tree at 64e9654. None is built. L has
landed (§0 rule 1), so every milestone gate that waited on it is open. The partial
progress L made on some WPs is in §2 and noted in the WPs.

**Re-check 2026-11-16 (a5c9431).** The open WPs were compared with the tree after 27 commits
of station-call, AGV-02 and web work. No open WP was built in that time. The done WPs are
intact. What changed under the plan is in §1a. The WPs it touches carry a
"**Delta 2026-11-16**" note, and those notes win over the WP text they follow. WP-Y1 is replaced
by `manuals/emergency-suite-plan.md` Part B (decision 22).

**Implemented 2026-11-16 (uncommitted).** The open WPs were built on the dev box the same day;
§7 "Implementation 2026-11-16" has the state of each and what is still owed on the vehicle.

For a coding agent. It merges three plans into one ordered list of work packages, with the
owner's answers to their open questions applied:

| Short name | Source |
|---|---|
| **H** | `manuals/sensor-dropout-hardening-plan.md` (items H-P0-1 … H-P3-3) |
| **C** | `manuals/cpu-load-plan.md` (items C-§4a-a … C-#28) |
| **S** | `manuals/external-features-survey.md` (items by slug, e.g. S-`rfid-0072-heartbeat`) |
| **L** | `manuals/lean-plan.md` (D-numbers). P0 + P1 committed (75f2bea, 64e9654); 122 of 161 marked; the rest are in §0 rule 1 |

The source items hold the full rationale, evidence and line anchors. This plan states **what
to build, in what order, and what changed versus the source**. When a work package says
"as source", build the source item exactly. When it lists deltas, the deltas win.

---

## 0. Rules for the agent

1. **L has landed** (75f2bea, 64e9654), and so has plan 4 (ef319d9). Check `git status`
   before starting a WP anyway. The source line numbers are stale, so **re-anchor every item
   by symbol** (function or class name), never by line. These L items are still open, and
   each overlaps a WP here. Do each one together with its WP, not separately:

   | L item | State | Do it with |
   |---|---|---|
   | D16: two horn engines | todo | WP-C7 (panel_node horn subscriptions) |
   | D08: `agv_core/events.py` ring written, never read | todo | WP-H3 (event forensics) |
   | D51: Foxglove plumbing | todo | Superseded by WP-0A |
   | D01: `lidar.*` keys have no consumer | partial, owner decision | WP-P10 launches the scanner from them, which settles D01: the keys stay |
   | D53: localization group built twice | todo | WP-C15 (Nav2 lifecycle/container) |

   The remaining L items (D13 rest, D36, D39, D95 and the P3 tail) touch no WP file.
2. **Use L's homes:**
   - CANopen constants: `canbus/cia301.py` and `cia402.py`.
   - SDO: `canbus/sdo.py`, including `bench_bus` and `guarded_sdo_write`.
   - QoS: `amr_base/qos.py`.
   - Wire enums: `amr_base/wire.py`. The new DeviceHealth device and state enums go here.
   - Node boilerplate: `amr_base/lean_node.py` (`LeanNode`, `run`).
   - TF to pose: `amr_base/tfpose.py`.
   - Hold primitives shared by the two run FSMs: `amr_base/hold_policy.py` (`auto_causes`,
     `Debounce`, `hold_text`, `premove_ready`).
   - Event ring: `eventlog.EventRing`.
   - State and maps paths: `agv_core/paths.py`.
   - Atomic file writes: `agv_core/fsio.py`.
3. **Check before you build.** Several items may already be done by L or plan-4 work. Grep
   for the symbol the item adds. If it exists and its test exists, mark the item done in §7
   and move on.
4. CLAUDE.md applies in full. In particular:
   - No service start/stop, no CAN frames, no bench tools.
   - Focused tests only: `python3 tests/run_all.py` for agv_core, and
     `python3 -m pytest -q <files>` for amr_ws.
   - Lint: `cd amr_ws && ruff check src/` and `ruff check .` from the repo root.
   - Change `EXPECTED_CHECKS` deliberately, with a dated comment.
   - Profile keys need a schema entry, validation and a refusal test in `tests/test_config.py`.
   - **Two profiles (2026-11-16):** every new key goes into `profiles/agv-01.json` **and**
     `profiles/agv-02.json`. The loader refuses a missing or unknown key. Refusal tests stay
     in `tests/test_config.py` against agv-01, and `tests/test_vehicles.py` must still load
     every profile. No per-host code (`manuals/agv-02-plan.md` §6).
   - No commits.
5. **Safety-listed files:** `gating.py`, `cmd_mux_kinematics_node.py`, `scanner_fields.*`,
   `guard.py`. Every change to them adds or adjusts a test, and the WP summary states the
   **failure mode and recovery path**.
6. **The unified sim** runs once per milestone (end of M1, M3, M5), sequentially, on its own
   `ROS_DOMAIN_ID`. It checks mechanisms, not tolerances. Known failures to tell apart
   from new ones (triage 2026-10-28, none caused by L):
   - **Stale tests, to fix in WP-T3:**
     - `test_square_drive`: no panel, so the vehicle never leaves `PANEL_STALE`.
     - `test_run_control_sim`: still expects the obstruction check, removed 2026-09-21.
     - `test_fault_injection_sim::test_killing_the_base…`: expects a `BASE_EXITED` event, but only `MODE_CHANGE` is emitted.
   - **Flaky:** `test_route_sim` passes when run alone.
   - **Not diagnosed:** `test_amcl_sim` and `test_survey_sim`. They clash with the live service on port 5001; diagnose with `amr.service` stopped.
   - **Already failing in plain pytest** (not sim):
     - `test_launch_layers::test_line_layer_is_only_the_follower`
     - `test_node_attributes::test_no_node_reads_an_attribute_it_never_assigns` (`site_run.py`).
       Re-triage it (2026-11-16): `site_run.py` grew by 316 lines and `amr_station` is new
       scan input, so the failure may have changed.
7. **Build marks:**
   - R: service restart is enough
   - C: needs `colcon build` (msg/srv or a new entry point)
   - D: deploy file, applied by the owner with `install.sh` off-shift
8. When a WP is done, tick it in §7 with the date and the tests that ran.

---

## 1. Decisions applied (owner, 2026-10-25)

| # | Question | Answer | Effect on the plan |
|---|---|---|---|
| 1 | Which holds resume by themselves | Only `field` (+ `estop` behind its existing flag) | `_AUTO_CAUSES = ("field",)`. Every device-dropout hold needs a fresh physical Start in both products (WP-A2) |
| 2 | Pendant must be released before it drives | Yes | WP-A6 (H-P0-10). Overrides the `panel.py` "held at power-on is meant to drive" rule |
| 3 | How a drive fault is cleared | Supervisor Recover, engineer role. No ALM-RST wiring | WP-B4. 8130h stays a power-cycle clear |
| 4 | One drive silent: still force the healthy drive into 8130h | Keep | No change to heartbeat withholding. Document it in RUNBOOK |
| 5 | nanoScan3 `skip: 3` | Stays rejected | — |
| 6 | No dev sessions in production | **No.** VS Code Remote and agent CLIs stay | C Tier 1 #2 dropped. CPU projections carry 5–23 % of a core for dev tooling |
| 7 | Platform freeze + snapshot move + monthly patch window | Yes | WP-P1, WP-P2 |
| 8 | Foxglove | **Retire entirely** | WP-F1. S-`foxglove-bridge-readonly-lockdown` and L D51 are superseded |
| 9 | CAN re-plug recovery | systemd only (`canable@can0.service`) | WP-P3. No in-process bus reconnect |
| 10 | PEAK PCAN-USB | Not yet | S-`can-adapter-real-error-counters` parked |
| 11 | RFID band | Ignore | S-`cf821-indonesia-band` dropped |
| 12 | nanoScan3 24 V | Always on; off only on its circuit protector or vehicle power-off | SCN-1 stays "partial". H-P1-12 scanner watch moves to P2 (WP-Z) |
| 13 | Data output saved in Safety Designer | Unknown | Human task HT-1. S-`sick-driver-no-write-fork` stays blocked on it |
| 14 | FX3 status to the PC | Q3 will carry E-stop status to a DI, wired later. FX3 CPU is **FX3-CPU000000**. Q4 not used | WP-Y1 deferred until wired. S-`fx3-spare-q4-status-bit` and S-`fx3-gateway-readonly` dropped |
| 15 | DIO | `num_do` stays 16. Module is **CK-TP5162**. DO8 not answered → unchanged | Electrical doc rename = HT-2 (SKILL workflow). O-1 (DI08) resolved 2026-10-28 |
| 16 | BMS | Ignore | S §2.12 dropped, except the error/RTR-frame filter, which is a latent EMCY collision bug (WP-B6) |
| 17 | RFID heartbeat opcode | 0x0072 | WP-E1 |
| 18 | Bench session | Yes | §5. Needs the read-only probe WP-0B first for the SDO reads |
| 19 | `/wheel_states` under STO; CCW gyro spin | Later | H-P1-14 and the `gyro_sign` VERIFY stay gated |
| 20 | turbostat run | No | PL1 backstop and S-`pmqos-cpu-latency-holder` parked. CPU §3 acceptance `pidstat` still owed (§6) |
| 21 | Order of work | Not answered → recommended order | M0 → M6 below |
| 23 | RFID (2026-11-16) | **Not used any more** (owner) | WP-E1, WP-C8 and §5 bench item 5 are withdrawn. WP-H1 has no RFID device and `IO_ISLAND_LOST` is DIO only. WP-A1 (done) stays as it is. `rfid.enabled` set to false in both profiles (owner, 2026-11-16) |
| 24 | E-stop signal polarity and source (2026-11-16, after the implementation) | **Q3 HIGH = E-stop triggered, LOW / no signal = normal. Informational, not safety. Only the safety controller's signal makes an emergency: a DIO gap / invalid image never does** | `emergency.py` starts NORMAL and holds its state while blind; `panel_io` filters on valid images only. Profile keys renamed: `panel.di_estop` (was `di_estop_ok`), `panel.estop_confirm_scans` (was `estop_low_scans`), new `panel.estop_active_high: true`; `di_names[9]` "ESTOP ACTIVE". A broken DI09 wire reads normal. The drawings still say "ON = not pressed" (HT-2). `EXPECTED_CHECKS` 984 → 986 |
| 22 | E-stop status DI (2026-11-16) | `manuals/emergency-suite-plan.md` Part B replaces WP-Y1 | Q3 → DI09 is wired (`io-mapping.md`, owner 2026-11-15). Part B (E1–E8) is built from its own plan. WP-Y1 is withdrawn; its checks move into Part B E1 (see Z) |

### Open items (record them; don't block on them)
- **O-1, DI08: resolved 2026-10-28.** DI08 is the **Manual Arm** switch (owner), not FX3 Q3.
  `io-mapping.md` and sheets 08/09 are corrected; the Manual Arm switch details and Q3's
  destination are still `«placeholder»` there. The future Q3 E-stop status needs a free DI in
  **DI09–DI0F** (COM1 group; DI07 is COM0 and won't read a sourcing output). Until it is
  wired, no code reads Q3 as E-stop. **2026-11-16:** wired to DI09 (owner 2026-11-15). The
  software is emergency-suite-plan Part B (decision 22), not yet built.
- **O-2, DO8** in `dio.motion_on` (`[0, 8]`): sheet 09 marks DO8–DOB as "NOT USED".
  Leave it unchanged and make it visible (WP-Y2).
- **O-3, does an E-stop end a run? Answered (owner, 2026-11-16): no.** `emergency-suite-plan.md`
  §4 stands: the run goes into the `estop` hold and resumes on a physical Start after NORMAL.
  This overrides `station-call-plan.md` O13 for an E-stop: the Reset the operator presses after
  releasing the E-stop (manual 10.7: release, RESET, START) does not abort the trip while the
  hold cause is `estop`. A Reset outside IDLE in any other state still aborts (O13 otherwise
  unchanged). Built in Part B E5, with `test_reset_mid_trip_aborts_it` kept for the non-estop
  case and a new test for the estop case.
- **O-4, turbo. Answered (owner, 2026-11-16): the installed unit stays.** `cpu-freq-cap.service`
  (turbo on, capped at 2.2 GHz, `Conflicts=cpu-no-turbo.service`) is the thermal strategy;
  `cpu-load-plan.md` §2 is corrected to follow it. Whether a PL1 cap would bind under it stays
  unknown until turbostat runs (decision 20).

### Conflict with L, settled
- **L D02** (landed) removes the profile IMU, monitor and telemetry periods because nothing
  reads them. The ROS params in drive_node rule. H-P2-1 wanted to wire `imu.poll_period_s` and
  `retry_period_s` into the profile. **L wins for those:** they stay ROS params.
- H-P2-1 keeps only the new `freshness` block: gate limits with hard ceilings, and consumer
  limits pinned ≥ gate (WP-A9).

## 1a. Code that arrived after the plan (re-check 2026-11-16)

| Change | Where | Effect on the plan |
|---|---|---|
| Two vehicles | `profiles/agv-02.json`, `agv_core/identity.py`, `amr_ws/env/vehicle.sh`; `amr-supervisor.sh` runs `python3 -m agv_core.identity` first | §0 rule 4 (both profiles). §5 bench reads per unit. WP-P1, P2, P3 per PC. WP-H5 names the identity-mismatch failure |
| Station calling over MQTT / VDA 5050 | `amr_ws/src/amr_station` (`station_bridge_node`, `mqtt_link`, `vda_order`, `vda_state`); `station.enabled` true on agv-01, false on agv-02 | §2 "VDA 5050 dropped" is withdrawn. New device for WP-H1/H3/H4/P6. New WP-C17. Departure from HOME on an accepted order needs no Start (station-call §3.1): the one exception to decision 1's "fresh physical Start" |
| Rear scanner + trolley detection | `rear_scanner.launch.py`, `nanoscan3_rear.yaml` (placeholders), `trolley_node`, `trolley_detect.RearField`; hold causes `trolley` (CALL), `CAUSE_DEVICE["trolley"] = "rear_scanner"` | Not fitted: `rear.source` is `none` on both units. WP-E2, E3, E4, P10 cover both scanners. WP-H1 gets a `rear_scanner` device |
| Stop-call alarm | `hold_policy.CALL_CAUSES`, `panel_io.call_wanted` / `call_phase`, profile `dio.call_alarm_on_s` / `_off_s` | WP-C7 keeps it |
| At-home combination | `PanelState.start_held` / `reset_held`, `amr_line/home_combo.py` | WP-C3, C6 latency tests |
| No NAVIGATION from the web | `amr_web/server.py` `api_mode`: "No NAVIGATION (2026-10-28)"; Routes and trackless missions removed | WP-C14, most of C15 deferred. WP-C16 is the Mapping page only |
| Web cut down | demo, editor, maps, review, run_tracked, survey_continue pages deleted; `home_tile()` added | WP-H2 LINE headline done; WP-C12 counts change |
| CPU caps in the repo | `deploy/cpu-power-limit.service` (PL2 15 W, PL1 untouched), `cpu-freq-cap.service`; install.sh installs, engineer enables | Z PL1 backstop still parked; O-4 |
| Wi-Fi reconnect watchdog | `deploy/agv-wifi-reconnect.{sh,service}` (journal only) | WP-H3 report zip, WP-H5 failure handling |
| Q3 → DI09 wired | `io-mapping.md` (owner 2026-11-15) | Decision 22 |
| Drive power-down from a future-stamped panel sample | `drive_node._update_power` now takes `now` after the read (2026-11-06) | A side effect of WP-A5's "future-stamped is stale" rule. See the WP-A5 note |

---

## 2. Already done or dropped (don't redo)

| Item | State |
|---|---|
| S "Two guard.py bypasses" / L D44 | **Done by L**: `canbus/sdo.guarded_sdo_write`, used by `drive_forward` and `read_imu.enable_tpdo`. Test verified 2026-10-28: `tests/test_canmon.py` "no raw sdo_write( outside sdo.guarded_sdo_write". It scans `canbus/` only. A remaining gap in `amr_base/canopen.py` is assigned to WP-B3 |
| H-P0-2 shared module | **Done by L**: `amr_base/hold_policy.py`. Both FSMs call `auto_causes()` and `Debounce`. WP-A2 changes the cause sets, not the plumbing |
| H-P1-2 parts | **Done**: `LineState.auto_resume` and `RunState.auto_resume` are filled. `IoImage.comms_ok` comes from `PanelAdapter.source_fresh` |
| C#22 LeanNode part | **Done by L**: `RouteExecutor(LeanNode)` with `MultiThreadedExecutor(4)`. The rest of WP-C14 is open |
| H-P0-8 LINE half | `line_follow_node` already has `field_source` / `field_fresh_s`. The executor half is still open (WP-A8) |
| C §3 (LeanNode, commissioning idle period, scan_gate poll, web live subs, `AMR_FOXGLOVE=false`) | Committed (8f7944a). Deployed: built `LineState` matches the source, amr.service was restarted 2026-10-25 10:14. **Acceptance pidstat not taken** (§6) |
| C Tier 1 #1 (`tape_loc.enabled=false`) | Withdrawn in the source |
| C Tier 1 #2 (no dev session) | Dropped (decision 6) |
| C §4a f, g / Tier 3 #25, #26 (AMCL lean, EKF 30 Hz) | Wait for tracked-plan-3 P0 M1–M6 on the floor. Not in this plan |
| Foxglove lockdown, Q4 status bit, FX0-GMOD, CF821 band, PCAN, BMS census/decoder/refusal/inventory/physical/poll-guard, i18n, Lichtblick | Dropped or parked (decisions 8, 10, 11, 14, 16; S §5) |
| VDA 5050 | **Built** in `amr_station` under `station-call-plan.md` (2026-11-06 onward). S `vda5050-*` items are superseded by it. Was listed here as dropped until 2026-11-16 |
| WP-H2 LINE headline | **Done** by `amr_web/alarms.home_tile()` (7295543), test `test_the_status_tile`. `headline()` still has no LINE branch: align or retire it in WP-H2 |
| WP-E3 index half | **Done before the plan**: the protective index reaches mux, follower and executor from `scanner_fields.load()` (test_launch_layers D165). Only polarity is left |
| WP-E6 reconnect | **Done**: `dio._scan_with_retry` (tests/test_dio.py) |
| WP-P3 `After=` | **Done**: `amr.service` `After=… canable@can0.service`, test_shutdown_order |

---

## 3. Milestones

| Milestone | Theme | Gate to start |
|---|---|---|
| **M0** | Small, isolated wins + bench probe + deploy files | Open |
| **M1** | Motion authority and missed stops (H-P0) | Open (L committed 75f2bea) |
| **M2** | Bus thread and drive recovery | Open (L committed 75f2bea) |
| **M3** | Device health and an honest HMI | M1 + M2 |
| **M4** | CPU: transport and wakeups | Any time after M0. Prefer after M2: drive_node items overlap |
| **M5** | Peripherals: RFID, scanner, DIO, IMU, MLS, web transport | M3 for the health-model consumers |
| **M6** | Durability, evidence, test infrastructure | M3 |
| **Z** | Parked / conditional | Named trigger |

---

## M0: small, isolated wins

### WP-0A Retire Foxglove · R (C for package.xml) · decision 8
- **Files:**
  - `supervisor_node.py`: docstring "four process groups", the `dp("foxglove", True)` param,
    the spawn block in the group start, `"foxglove"` in the stop-order tuple, and the respawn
    comment
  - `launch_helpers.foxglove()`
  - The `foxglove` arg and include in `mapping`, `nav`, `sim`, `lidar` and `drivers` `.launch.py`
  - `amr_bringup/package.xml` `<exec_depend>foxglove_bridge</exec_depend>`
  - `deploy/amr-supervisor.sh` `-p foxglove:=…`
  - `deploy/amr.env` `AMR_FOXGLOVE`
  - `test_fault_injection_sim.py` and `test_unified_sim.py`: the `foxglove:=false` args
  - `agv_core/alarms.py` SUPERVISOR text "base/web/foxglove groups" → "base/web groups"
  - Comments in `cyclonedds-local.xml`, `domains.py`, `base.launch.py` and
    `navigation_layer.launch.py`
  - Docs: README, amr_ws/README, RUNBOOK, alpha-setup. L's doc pass (2026-10-25) wrote
    "Foxglove only with `AMR_FOXGLOVE=true`" into alpha-setup §6/§6.1. Remove that too.
  - State on 2026-10-28: the env-default conflict that L D51 names is still present.
    `amr-supervisor.sh` uses `${AMR_FOXGLOVE:-true}`, `amr.env` sets `false`, and the
    supervisor's `dp("foxglove", True)` defaults to true. All three go.
- **validate.sh:** warn if `AMR_FOXGLOVE` is still present in the installed env file.
- **Don't** `apt remove ros-humble-foxglove-bridge` here. That is the owner's call in WP-P1.
- **Tests:**
  - `test_launch_layers.py`: no launch file declares `foxglove`.
  - Supervisor param test: the param is gone.
  - Grep test: no `foxglove` outside `manuals/`.
- **Done when:** `grep -ri foxglove amr_ws/src amr_ws/deploy agv_core` is empty.

### WP-0B Read-only SDO probe for the bench session · no build · gates §5
- **New** `agv_core/drivers/canbus/sdo_probe.py`. Run as
  `python3 -m agv_core.drivers.canbus.sdo_probe NODE:INDEX:SUB [...]`, plus named presets:
  - `--preset mls-tpdo`: node 10, 1800h:01/02/03/05, 1806h:01/02/05, 1A06h:00..08, 1A00h:00..08
  - `--preset drive-health`: nodes 1, 2 — 1802h/1803h:01/02/03/05, 1A02h/1A03h:00..08,
    407Bh:00, 60FDh:00, 603Fh:00, 1003h:00..08, 1016h:01, 1017h:00, 1001h, 6041h
- **Behaviour:**
  - `sdo_read` only, through `sdo.bench_bus(…, lock=True)`. It refuses while the service holds
    can0 and sends no NMT.
  - Prints hex, decimal and the abort code.
  - Refuses (argparse error) any write-shaped argument. It has no `--go` flag.
- **Tests (`tests/`):**
  - A fake bus answers the presets.
  - OwnerBusy → exit 2, `open_bus` never called.
  - The module imports no write helper: AST check that `sdo_write`/`guarded_sdo_write` are
    not referenced.
- **Bump `EXPECTED_CHECKS`.**

### WP-0C Doc and comment fixes · no build
- RUNBOOK reverse speed (§ route editor, "Reverse (2026-09-18)", which still says "half the
  speed cap"): say **0.30 m/s** (0.5 × 0.60). Add a test pinning reverse ≤ 0.30 m/s in the
  route compiler test (S "RUNBOOK reverse speed wording").
- `amcl.yaml`: mark `save_pose_rate` dead in Humble nav2_amcl 1.1.20.
- `nanoscan3.yaml`: the `intrusion_data: true` comment says it is the field status.
  `/output_paths` comes from application data, not `intrusion_data`. Fix the comment.
- `bus_health.py`: the module docstring already says slcan has no error-state visibility.
  Still owed: the soak summary prints "zero errors". Say "0 errors (slcan: 0 means unknown,
  not clean)" there and in the RUNBOOK.
- `cpu-load-plan.md` §3: the heading still says "NOT deployed". Change it to "deployed
  2026-10-25, acceptance pidstat owed". Tier 1 #2: dropped
  (decision 6). Add a §6 note that the projection keeps dev tooling.
- `sensor-dropout-hardening-plan.md` §7 and `external-features-survey.md` §0: one line each
  pointing to this plan's §1 for the answers.
- **Don't** touch `documentation/electrical/` (HT-2).

### WP-0D `lifecycle-event-bringup` remnant · R · S
- Set `attempt_respawn_reconnection: false` on the Nav2 lifecycle managers. Assert it in
  `test_launch_layers.py`.

### WP-0E Tier 1 operations scripts · D · C #3, #4, #5, #7 (as source)
- **`logs/pwrbtn-watch.sh`:** one `awk` (or a sysfs read) per 2 s instead of a `date` fork plus
  7 `awk` forks. Rotate its log with a logrotate drop-in copied into `amr_ws/deploy/`.
- **Kiosk watchdog:** slow it to 20 s and drop the duplicate `xrandr` probe.
- **Kiosk Chromium flags:** merge the duplicate `--disable-features` and add
  `--disable-background-networking --disable-component-update`.
- Both kiosk files live in `/usr/local/bin`. Version copies in `amr_ws/deploy/kiosk/`, and
  have `validate.sh` compare them with the installed files. The owner installs them.
- **CycloneDDS:** raise `net.core.rmem_max` in `deploy/sysctl-amr.conf` (265 RcvbufErrors
  measured). Leave the participant index and FragmentSize alone in this pass.
- **Apply `trim-services.sh`:** owner action, listed in §6.

---

## M1: motion authority and missed stops (H-P0)

All these WPs have verification **U**, plus **V** in §6 where noted.

### WP-A1 RFID encounter integrity · R · H-P0-1 as source
- The pure `amr_line/rfid_intake.py` takes the `_on_rfid` merge.
- Re-baseline window `RFID_TAG_CLEAR_S`.
- Heartbeat publishes `encounter_seq=self._sent` after `_poll()`.
- The cursor advances only to the highest seq it consumed.
- Random generation seed.
- Note: L changed `rfid.py` (`read_frames`, `RX_BUFFER_MAX`). Merge onto it.

### WP-A2 Single hold-cause policy · C (`hold_device`) · H-P0-2, with decision 1
- **Today (2026-10-28):**
  - `job._AUTO_CAUSES = ("field", "drives", "rate", "track")`.
  - The executor passes `("field", "controller")` to `hold_policy.auto_causes()`.
  - Decision 1 removes `drives`, `rate`, `track` **and the executor's `controller`**.
- `CAUSE_POLICY` goes in `amr_base/hold_policy.py`, beside `auto_causes()`, which L created
  and both FSMs already call. `auto_causes()` reads it instead of a per-product tuple, and
  `job._AUTO_CAUSES` goes. `agv_core/alarms.py` keeps its `clears_by` per code.
- **Delta:** the source's sub-points stay as written:
  - Split `panel_fresh` / `panel_image_valid`.
  - A fresh `valid=False` holds at once with cause `panel` and code `PANEL_LINK_LOST`.
  - Line `pending` → `LINE_PREREQ_LOST`.
  - In `_hold_tick`, reclassify an auto hold to `pending` when `field_clear is None`.
  - Executor: torque loss after a panel invalid → `panel`.
  - Append `hold_device` to LineState and RunState. `auto_resume` is already there.
- Regenerate the `job.py` module docstring and RUNBOOK §4.
- **Tests:**
  - A new `amr_base/test/test_hold_policy.py`. The library suite in `tests/` reads amr_ws
    files only as text and imports none of them:
    `clears_by=='auto'` ⇔ the cause is in `CAUSE_POLICY` auto, for both products.
  - `test_line_authority`: `rate`/`track`/`drives` holds stay held 10 s with `wants_power()`
    False, and resume only on start_edge + premove.
  - The source's panel and field cases.
  - `test_route_executor_logic`: panel blip + torque_off → `panel`.

### WP-A3 MLS silent → HOLD `sensor`, blind-travel accounting · R · H-P0-3 as source
- Depends on WP-A2 (the cause is non-auto).
- `autopilot.py` untouched.
- `HOLD_CODES sensor → MLS_SILENT`.

### WP-A4 LINE reacts to a drive-link FAULT · R · H-P0-4 as source
- `drives_operational` and `drive_link` in Inputs.
- Hold `drive_fault`, non-auto.
- No tape-distance advance unless the counts are valid and the drives operational.
- drive_node publishes state `stale` for a node with stale TPDO1.

### WP-A5 Monotonic freshness in the mux · R (D for chrony) · H-P0-7 = S-`steady-clock-freshness` · SAFETY-LISTED
- Mux `_now()` returns `time.monotonic()`. Today it uses `get_clock().now()`.
- `_fresh` requires `0 ≤ age ≤ limit`.
- STEADY_TIME timers in panel_node, line_follow, route_executor and supervisor.
- `deploy/chrony-amr.conf` drop-in: step only at start. `validate.sh` checks it.
- **Failure mode:** a backward wall-clock step lets a sample stamped before the step read
  fresh for up to its limit after the step, extending a stale command.
- **Recovery:** after the fix, a future-stamped sample is stale, so output goes to zero. The
  next fresh sample restores selection. Nothing is latched.
- **Tests:**
  - `test_gating`: future-stamped lease/panel/permit/line/teleop → not fresh, source NONE.
  - Contract test: the mux `_now` uses `time.monotonic`, and the listed nodes pass a STEADY
    clock to `create_timer`.
- **Note 2026-11-16:** after this WP, a consumer that takes `now` before reading a message can
  see a receive time from the future and read it as stale. That powered the drives down
  under a running vehicle three times on 2026-11-06. `drive_node._update_power` now takes
  `now` after the read. Any new freshness consumer must do the same.

### WP-A6 Pendant release before use · R · H-P0-10, decision 2
- In `PanelAdapter` only. `gating.py` and `DebouncedLevels` are unchanged.
- Update the `panel.py` contract docstring (the "held at power-on is meant to drive" text).
- Replace the old test at `test_panel_io.py` (≈:142).

### WP-A7 Missed-tag backstops · C · H-P0-9 as source
- Mission key `max_tag_gap_m`: schema, validation and refusal in `tests/test_mission.py`.
- Hold `rfid_overdue` → `RFID_TAG_OVERDUE`.
- Append `StationDetection.work_mode_mismatch`.
- Add the key with a default, so existing missions stay valid until it is set. Plan 4's
  `mission.py` work is committed (ef319d9).

### WP-A8 Executor field state ages · R · H-P0-8, executor half
- `_field_clear` becomes `(status, t_recv)`, plus `field_fresh_s` and `field_source`
  params. Mirror `line_follow_node`'s existing implementation (the same names and the same
  `assume_clear` handling).
- `navigation_layer.launch.py` passes `field_source`.
- `test_launch_layers` asserts the executor gets `scanner` when real.

### WP-A9 Stop tag read while braking in an auto hold · R · H-P0-11 as source
- After WP-A2, the only auto cause is `field`.

### WP-A10 Freshness limits into the profile · R · H-P2-1, reduced (see §1 conflict) · SAFETY-LISTED
- **Placement:** pulled forward because it pins the gate limits before M4 touches rates.
- New profile block `freshness`:
  - `cmd_s` ≤ 0.2 (hard ceiling)
  - `lease_s` / `permit_s` ≤ 0.3
  - `panel_s`
  - `field_s`
  - consumer limits for line, executor and readiness
- Refuse:
  - `pc_heartbeat ≥ pc_loss/2`
  - `pc_loss == 0`
  - `driver_timeout > 3 TPDO periods`
- **No value changes:** today's defaults move into agv-01.json verbatim.
- Contract test: every consumer limit is ≥ the gate limit.
- **Failure mode:** a future edit widens a gate limit, or tightens a consumer below the gate,
  unnoticed.
- **Recovery:** the profile is refused at load and the service won't start. The error names
  the key.

**End of M1:** run the unified sim once. Add RUNBOOK §4 entries for every new code:
MLS_SILENT, PANEL_LINK_LOST, LINE_PREREQ_LOST, RFID_TAG_OVERDUE, drive_fault.

---

## M2: bus thread and drive recovery

### WP-B1 Bound all sensor work on the bus thread · R · H-P0-6 as source
- `DriveLink.read_sensor(timeout ≤ 0.05)`.
- One-read-per-poll `_Job` chains for MLS and IMU rediscovery. The blocking `start()` runs
  pre-loop only.
- `nmt_nowait` for MLS.
- One sensor-SDO token per loop iteration.
- IMU backoff on the miss rate (≥ 3 of the last 10).
- **(e)** The loop-period max and overrun counter go into diagnostics. This is also the
  in-service measurement that replaces the bench "slcan TX backlog" question. Add the TX
  queue depth from `/sys/class/net/can0/statistics/tx_dropped` and the ENOBUFS count (WP-B2)
  to the same diagnostic.

### WP-B2 CAN TX errors and MLS exceptions don't kill the base · R · H-P1-3 as source

### WP-B3 Drive cleanup timing · R · H-P1-6 as source, plus one delta
- **Delta (found 2026-10-28):** `DriveLink._raw_write` in `amr_base/canopen.py` calls
  `sdo_write` without `guard.check`. It is the teardown path for 60FFh=0 and the 6040h
  shutdown/disable controlwords, used by `_zero_target_raw` and `_controlwords_raw`. That
  breaks "every SDO write goes through guard.py". L D44's test scans `canbus/` only, so it
  misses this.
- **Fix:** call `guard.check(index, value, sub)` first. A `ForbiddenWrite` returns
  `(False, …)`, so the teardown never raises. Today's three values pass the guard (checked).
- **Test:** extend the D44 scan to `amr_base/canopen.py`. Every `sdo_write(` sits in a method
  that calls `guard.check`/`check_sensor` first.
- **Failure mode:** a future teardown edit writes a deny-listed object unguarded.
- **Recovery:** the write is refused and reported as a teardown failure. The drives stay as
  they were, and STO is unaffected.

### WP-B4 Drive fault: a working clear and an honest standing row · C · H-P0-5, decision 3
- Recover is the existing supervisor Recover action, **gated to the engineer role** in amr_web
  (PIN, as the other engineer actions). The supervisor admission refuses while LineState is
  ARMED, RUNNING or in a powered HOLD, or while RunState is active. It then calls
  `/drives/ack_fault`. This wires the orphan endpoint L D169 flags.
- No ALM-RST text anywhere.
- Action text: "power-cycle the drives, wait for boot, then Recover".
- Absorb these survey items into the preflight:
  - S-`blvr-alarm-history-8130h-facts`: read 603Fh and 1003h in `prepare()` preflight, into
    the fault detail and the report zip.
  - S-`blvr-bootup-reboot-detect`: a boot-up frame 0x700+n with data 0x00 feeds `decide()`
    a `rebooted` flag.
- RUNBOOK: one-drive loss deliberately trips both drives (decision 4).
- **Delta 2026-11-16 (open parts):** `DriveLink.preflight()` now caches
  `preflight_statusword`, and `reported_state()` reports it before the first feedback. Put
  the 603Fh/1003h reads in the same read wrapper and carry them through `reported_state()`
  into DriveStatus. Build `fault_code` from `canopen.decide()` and retire the substring map in
  drive_node `_fault_code()`. The report zip is `amr_web/reports.py`.

### WP-B5 Bench tool ownership · no build · H-P1-9, narrowed
- `read_mls` modes that **send** SDO or NMT (snapshot, poll, calibrate, set-*, clear-event,
  `--nmt`) take the `can` owner lock.
- `stream` without `--nmt` is listen-only and stays lock-free, which keeps the documented
  "run beside the service" use.
- **Narrowed** relative to the source, which locked every mode except `calibrate --step report`.
- Test: OwnerBusy → the SDO-sending modes return 2 and `open_bus` is never called.

### WP-B6 Router ignores error and RTR frames · R · from S-`bms-router-ext-key`, BMS part dropped
- Key routes by `(arbitration_id, is_extended_id)`.
- Drop `is_error_frame` and `is_remote_frame` before routing. Otherwise a python-can error
  frame with id 0x081/0x082 reaches the EMCY routes of nodes 1 and 2.
- FakeBus tests in `test_canopen.py`.

---

## M3: device health and an honest HMI

### WP-H1 `agv_core/health.py` + `DeviceHealth.msg` · C · H-P1-1 as source
- Device and state enums in `amr_base/wire.py` (L D04).
- Owners, in order: drive_node → panel_node. The scanner wrapper is parked (WP-Z). No RFID
  device (decision 23).
- **The correlator has no BMS** (decision 16).
- `IO_ISLAND_LOST` = DIO only (decision 23 removed RFID from the shared cable group).
- **Delta 2026-11-16:**
  - Append `rear_scanner` (owner `trolley_node`) and `station_link` (owner
    `station_bridge_node`) to the device enum in `wire.py`. Both already publish ad-hoc
    edges (`REAR_SCANNER_SILENT`, `STATION_LINK_DOWN/UP`) that this replaces.
  - Whether a device exists comes from the profile (`rear.source`, `station.enabled`). An
    unconfigured device is ABSENT, never LOST.
  - The DIO `retried` counter (`dio._scan_with_retry`) feeds DEGRADED.
  - `station_link` stays out of `IO_ISLAND_LOST`: it runs over Wi-Fi, not the shared cable.

### WP-H2 HMI truthfulness · C · H-P1-2 as source
- **Already done:** `LineState.auto_resume`, `IoImage.comms_ok` from `source_fresh`.
- **Open:**
  - LINE `headline()`.
  - `ModeState.base_missing`: `readiness.base_missing()` exists, but no msg field carries it.
  - Structured `DIO_LINK_LOST/OK`: no such codes in `agv_core/alarms.py`.
- PANEL_STALE takes its IP from config. The text still hard-codes 192.168.1.30.
- All web text fits at UI scale `l`. Reuse `amr.css` classes.
- **Delta 2026-11-16:**
  - The LINE headline is done by `home_tile()` (§2). The Home page uses the tile's big text
    and title and takes only `detail` from `headline()`. Give `headline()` a LINE branch that
    matches the tile, or retire it.
  - `readiness.base_missing()` still checks topic age only. Carry it in ModeState as planned.
  - panel_node still sends DIO link text under event code `PANEL` by substring, and the new
    "DIO scan retried" event goes out the same way. Both move to the `DIO_LINK_*` codes.
  - PANEL_STALE: take the IP from `config.DIO_IP`. Both profiles have 192.168.1.30 today, so
    the text is right but not sourced.
  - Add a standing row from `/amr/rear/trolley` (rear silent / trolley UNKNOWN) when
    `rear.source == "scanner"`. Today they are events only.

### WP-H3 Event forensics independent of the web · R · H-P1-15 as source
- Do L D08 here: the DIO/RFID drivers write `agv_core/events.py`, and nothing reads it.
  Either this WP's forensic log reads it, or the ring goes. Use `eventlog.EventRing`
  (L) for any new ring.
- **Delta 2026-11-16:** the recorder covers every `/amr/events` publisher, now including
  `trolley_node` and `station_bridge_node`. `agv-wifi-reconnect.sh` logs to the journal
  only: add `journalctl -u agv-wifi-reconnect` to the report zip.

### WP-H4 Supervisor and launch liveness · R · H-P1-5 as source
- Add S-`sdnotify-extend-timeout-status-executor-watchdog`: `STATUS=` with the mode and the
  last fault, plus `EXTEND_TIMEOUT_USEC` during the bounded stop. `sdnotify.Notifier`
  already has a `STATUS=` sender that the supervisor never calls (it calls `ready`,
  `watchdog`, `stopping`). Wire that, and add `EXTEND_TIMEOUT_USEC`.
- **Delta 2026-11-16:** `station_bridge`, the rear sick driver and `trolley_node` launch with
  `respawn=True` and are not `required()`, so they never raise BASE_EXITED, and ROS respawn has
  no give-up limit. A bridge with wrong MQTT credentials exits and respawns every 5 s. Add
  them to the launch-walk allow-list as respawning-optional, and surface a respawn loop as a
  health row (WP-H1), not a base fault.

### WP-H5 Unclean-death handling · D · H-P1-4, minus the re-plug part (WP-P3)
- `WatchdogSignal=SIGINT`, `faulthandler` dump, `ExecStop=amr-orphan-stop.sh` with an atomic
  `groups.json`, `OOMPolicy=continue` + `OOMScoreAdjust`, `OnFailure=amr-failed.service`.
- **Delta:** the static "call engineer" page is written to `/run/amr/failed.html` (changed
  from `$AMR_STATE_DIR` on 2026-11-16, see below) and served by the kiosk as a `file://`
  fallback. **No nginx** (S §5).
- S-`uptime-boot-id-and-service-result`: classify unclean shutdowns by `boot_id` and
  `$SERVICE_RESULT` in `ExecStopPost`. Pure `classify()` with tests. Extend
  `amr_bringup/uptime.py`, which already tells a power cut from a crash by the kernel boot
  time. Add the two inputs there; don't add a second classifier.
- Reword SERVICE_CRASHED (8130h is possible).
- **Delta 2026-11-16:**
  - **Kiosk conflict: fixed 2026-11-16.** `deploy/kiosk/amr-kiosk-browser` killed Chromium
    when its one tab was not on `http://127.0.0.1`, so a `file://` fallback would have died
    every 20 s. The kiosk now opens `file:///run/amr/failed.html` while `amr.service` is
    failed and the page exists, accepts exactly that URL there, and restarts onto the UI when
    the service recovers. **The page lives in `/run/amr/`, not `$AMR_STATE_DIR`:** the kiosk
    runs as `amrkiosk`, which can't read the service user's home. `/run` is tmpfs, so a stale
    page never survives a boot. `amr-failed.service` (root) writes it with mode 0644 in a 0755
    directory, and `ExecStartPre` of amr.service removes it.
  - The failed page also names the identity mismatch: `amr-supervisor.sh` exits before the
    supervisor when `agv_core.identity` refuses, and the restart limit leaves the unit
    failed. Text: check `vehicle.env`, then `systemctl reset-failed amr`.
  - Add the new deploy units (`agv-wifi-reconnect`, `cpu-power-limit`, `cpu-freq-cap`) to
    validate.sh's is-failed check. `OnFailure` for them is not in scope.

**End of M3:** run the unified sim once.

---

## M4: CPU, transport and wakeups

Each item is behaviour-preserving unless marked. Re-profile after the milestone (§6), not per
item. Source totals: §4a a–e ≈ 13–15 % of a core, Tier 2 ≈ 0.4–0.5 core.

| WP | Items | Build | Notes |
|---|---|---|---|
| WP-C1 | C §4a **a + C#10** (the same item): localization_monitor drains the age-only streams at its 10 Hz tick using `take_message` and `source_timestamp` | R | Contract test: the ages come from `source_timestamp`, and the limits are unchanged |
| WP-C2 | C §4a **b, c, d, e**: raw `/scan_gated` with one decode per `match_period`; raycast early-exit + cos/sin cache (bit-identical, oracle test); scan_gate raw pass-through; TF listener on its own lean node, no param services | R | c: brute-force oracle equality test. d: bytes-in == bytes-out test |
| WP-C3 | C#8 panel_node publishes once per DIO acquisition + a 50 ms fallback | R | Authority stream. Test: every Start/Reset edge is published exactly once, and the worst-case gap is ≤ 60 ms with a fake clock. **Delta 2026-11-16:** PanelState now carries the `start_held`/`reset_held` levels that feed `home_combo`. The test also covers a held Start+Reset: the At home combination fires within `HOLD_S` + 50 ms |
| WP-C4 | C#9 supervisor feed node with its own executor (mux, drives, wheels, panel) | R | Receipt stamps and freshness windows unchanged; test_hardness |
| WP-C5 | C#11 gyro bias folded into drive_node `_publish_imu`; retire imu_bias_node; `/imu/data_raw` only with subscribers | C | `gyro_bias.py` moves to agv_core. "Nothing until calibrated" kept. **After WP-B1** (same file) |
| WP-C6 | C#12, #13, #14 line_follow: idle tick 10 Hz with `timer.reset()` on any edge; `/imu/data` subscribed only outside IDLE; (v, wz) from `/wheel_states`, drop `/odom_raw` | R | Test: Start-edge reaction ≤ 20 ms. Wrapper only, autopilot untouched. **Delta 2026-11-16:** with `station.enabled`, an accepted `/amr/line/order` departs HOME with no Start (`_srv_order`). The idle tick also resets on order accept and order cancel. Test: order-accept-to-motion ≤ 20 ms. Each tick now also does trip-log rows, the order-state publish and `_position_tick`: check that they don't run at the idle rate in a way that hides an edge. Confirm which job state the vehicle sits in at HOME while it waits for orders before choosing the idle condition |
| WP-C7 | C#15 panel_node: no `/cmd_wheel_vel` or `/drives/status` subscriptions when `horn.enabled` is false; motion lamp from a DriveStatus `turning` flag | C | L did not do it: panel_node still subscribes both topics unconditionally (2026-10-28). Do L D16 (two horn engines) in the same change. **Delta 2026-11-16:** the premise holds (`_on_drives` only feeds horn `armed`). Remove the horn block from both profiles (both have `enabled: false`). **Keep the stop-call pulse** (`panel_io.call_wanted` / `call_phase`, driven from LineState `hold_cause`): it drives the alarm output, not the legacy horn. `horn.enabled: false` does not mean there is no alarm output. Check that `dio.motion_on` doesn't need `/drives/status` before you cut it |
| ~~WP-C8~~ | C#16 rfid_node wakes on a new tag via a GuardCondition | R | **Withdrawn 2026-11-16** (decision 23: RFID not used) |
| WP-C9 | C#17 cmd_mux: a repeated zero at 10 Hz when source NONE and output exactly zero · **SAFETY-LISTED** | R | **Failure mode:** a lost idle zero. drive_node treats > 0.2 s as zero anyway (2× margin). **Recovery:** revert. Test: any nonzero, first zero or generation change is published on that tick |
| WP-C10 | C#18 `/odom_raw` computed in drive_node; retire diff_drive_odom_node | C | After WP-C5 |
| WP-C11 | C#19 `start_parameter_services=False` where nobody runs `ros2 param set` | R | Grep RUNBOOK and the scripts for `param set` first. Keep the services on nodes the RUNBOOK tunes live. **Delta 2026-11-16:** the only `param set` is in `amr_sim/fake_panel_node.py` (sim). Add `station_bridge_node` and `trolley_node` to the candidates |
| WP-C12 | C#20 amr_web: service clients on a second node; stop the idle `_live_pose` / reconcile timers; `/drives/pp_status` on demand; `live.py` ceil division | R | Combine with WP-E5 (same process). **Delta 2026-11-16:** 23 service clients now (run/pause/abort/resume and the route preview gone). amr_web no longer subscribes `/drives/pp_status` (gone since ef319d9; the only subscriber is `commissioning_node`): the on-demand part moves to drive_node, with WP-C13. `_live_reconcile` (1 Hz) and `_live_pose` (5 Hz) are still there |
| WP-C13 | C#21 small items | R | Absorbs the `/drives/pp_status` on-demand item from WP-C12 |
| WP-C14 | C#22 route_executor: no param services, TF on its own thread, **keep MultiThreadedExecutor**; plus S-`rclpy-nonblocking-action-checks` (`server_is_ready()`, stamp-age-checked TF) | R | LeanNode already done by L. Read TF through `tfpose`. **Deferred 2026-11-16:** route_executor runs only in NAVIGATION, which the web can no longer enter (`server.py` `api_mode`, since 2026-10-28). Build it when NAVIGATION gets a UI again |
| WP-C15 | C#23, #24 Nav2 controller/behavior inactive while the executor is IDLE; one `component_container_isolated`; `bond_timeout: 0` | R | Opt-in sim once. Plus S-`nav2-lifecycle-health-after-commit` (pure `layer_health`, LAYER_INACTIVE). Do L D53 (localization group built twice) in the same launch change. **Delta 2026-11-16:** the controller/behavior and container parts are deferred with WP-C14 (NAVIGATION only). The `bond_timeout: 0` part still applies: it also hits LINE's tape_loc group (`amcl.yaml`). D53 is still open; both callers must pass line_layer's new `dynamic_yaml` argument |
| WP-C16 | C#28 web live view in NAV/MAPPING from a 5 Hz display topic | C | **Delta 2026-11-16:** scope is the Mapping page only (`templates/mapping.html` + `liveview.js`, including LINE tape-localization positioning there). No NAV page. `/api/live/*` only |
| WP-C17 | **New 2026-11-16.** station_bridge_node (agv-01 only, `station.enabled`): wake `_drain` from the paho network thread with a GuardCondition (same pattern as WP-C8) instead of its 20 Hz timer; keep `_state_tick` at 10 Hz; no param services | R | Test: a queued MQTT message is handled on the next spin, and none is lost when several arrive at once |

**Re-profile scope (2026-11-16):** OP-1 and OP-2 must include a running LINE trip, not only
idle. `trip_log` builds a row every 50 Hz tick while ARMED/RUNNING/HOLD and has a writer
thread. `trolley_node` and the rear driver add nothing today (`rear.source: none`); profile
again after the rear scanner is fitted.

**Not in M4:**
- C#27 slam_toolbox parameters: map-quality risk, one parameter at a time, on the vehicle. It
  stays with the survey re-run work.
- §4a f, g (see §2).

---

## M5: peripherals and web transport

### ~~WP-E1 RFID heartbeat on 0x0072 + detection/reporting~~ · **Withdrawn 2026-11-16 (decision 23: RFID not used)**
- Heartbeat sends `CMD_GET_PARAMS` (0x0072) instead of `CMD_ONLINE` (0x0050). Each reply also
  refreshes `param_mismatches()`, with edge-triggered logging.
- Fix the module docstring, which says 0x0050 is the heartbeat.
- Profile `rfid.heartbeat_s` and `heartbeat_timeout_s` stay **0.0 (off)** in agv-01.json.
  The owner turns them on after the §5 bench check (0x0072 at 1 Hz doesn't cut reads/s).
- The rest as H-P1-11:
  - The ETIMEDOUT split.
  - `comms_ok` requires the thread to be alive.
  - Appended `detail`, `heartbeat_state`, `bad_frames` and `silent` fields.
  - U-turn-only note.
  - No Start refusal unless `rfid.heartbeat_required` (schema + refusal test).
- S-`rfid-site-epc-prefix` (reject foreign UHF tags) goes here if `tag_table` doesn't already
  filter. Check first.
- **Delta 2026-11-16:** `rfid.py` is unchanged since the plan. `heartbeat_s` and
  `heartbeat_timeout_s` stay as they are in **both** profiles. `rfid.heartbeat_required` goes
  into both profiles. The H-P1-11 RFID Start check is now `job._rfid_check`; put the
  U-turn-only note there.

### WP-E2 Scanner: honour `is_valid`, show the active case · R · S-`scn-outputpaths-valid-safe` · SAFETY-LISTED (mux)
- `gating.Field(now, status, valid)`: an invalid path is UNKNOWN, so there is no AUTO resume
  and the most restrictive scale applies.
- The executor and line_follow apply the same rule.
- **Failure mode:** an untrustworthy path bit was read as clear.
- **Recovery:** the next valid sample restores selection. A physical Start is needed only if
  a hold was taken.
- **Delta 2026-11-16:** line_follow and the executor read the field through
  `drive_state.field_clear`, so change it there. New consumer: `trolley_detect.RearField`
  reads `status[index]` only. It gets the same rule (an invalid rear path reads
  FIELD_UNKNOWN) and its own test. The rear already publishes its active case
  (`TrolleyState.rear_case`), so showing the active case is front only.

### WP-E3 Scanner index/polarity from one source · R · H-P1-13 as source · SAFETY-LISTED (`scanner_fields.*`)
- **Delta 2026-11-16:**
  - The index half is done (§2). Left: polarity. `field_clear` hard-codes True as clear;
    pass the protective polarity from `scanner_fields` into line_follow and the executor.
  - The rear index and polarity come from the profile (`rear.field_output_index`) by design,
    while the rear has no Safety Designer copy. Record that as a named exception in the test,
    or move it into `scanner_fields` at the rear fit.
  - `scanner_fields.yaml` is marked STALE (documentation D1, 2026-11-15). Don't touch the
    rects or `stop_m` until D1 is decided.

### WP-E4 Scanner diagnosis rows · R · S-`scn-diag-status-overview` + H-P1-12 web half
- Pure `scanner_health.py` maps the driver's `/diagnostics` State and `status_overview` to
  SCANNER_CONTAMINATED / SCANNER_ERROR / SCANNER_CONFIG_UNVERIFIED rows, ranked above
  FIELD_PROTECTIVE.
- Mapping gap function: SURVEY_SCAN_GAP.
- Test with a recorded DiagnosticArray fixture.
- **Delta 2026-11-16:** key the rows per scanner (by hardware_id or node name). Add rear rows
  only when `rear.source == "scanner"`. SURVEY_SCAN_GAP is front only. Whether the rear
  driver's `/diagnostics` is namespaced is unknown until the rear is fitted.

### WP-E5 Serve the HMI with waitress · R · S-`waitress-wsgi` + H-P2-9 socket-timeout half
- `python3-waitress` comes from apt. Add `<exec_depend>` and `validate.sh` checks it.
- Cut the `adapter._call` timeouts.
- Jog stays held by re-POSTs.
- `wifi.powersave = 2` NetworkManager drop-in in `deploy/` (D).
- **Delta 2026-11-16:**
  - Power save is already off per connection, by hand (alpha-setup `agv-net`,
    `802-11-wireless.powersave 2`). Drop the drop-in. Instead, validate.sh checks
    `nmcli -g 802-11-wireless.powersave con show agv-net` reads disable.
  - flask is pinned with `pip --user` (alpha-setup), not apt. Install waitress the same way
    (pinned pip plus the alpha-setup import check), or move both to apt. Don't mix the two.
  - Today: werkzeug `app.run(threaded=True)` in `web_node.py`; `adapter._call` defaults to
    30 s, and `line_mission`, `line_teach` and `_trigger` pass no timeout of their own.

### WP-E6 DIO transport · R · H-P1-10 + S-`dio-pymodbus-retries-zero` + S-`dio-fc03-combined-image`
- One timeout counts as one failed scan (retries 0).
- One immediate reconnect after a good scan.
- DI and DO in one FC03 read.
- A drops-in-10-min counter.
- Re-baseline unchanged.
- **Delta 2026-11-16:** the immediate reconnect is done (`dio._scan_with_retry`, §2). Left:
  `retries=0` on `ModbusTcpClient` (matters more now: each library retry multiplies inside the
  new retry; check the installed pymodbus default), DI+DO in one FC03 read (still
  `read_discrete_inputs` + `read_coils`), and the drops-in-10-min counter.

### WP-E7 IMU coupling and plausibility · R · H-P1-7, minus the `gyro_sign` closure (decision 19)
- The pure `gyro_check` lives in `amr_localization`.
- The `gyro_sign` VERIFY stays open.
- **Note 2026-11-16:** `line_follow_node.py` grew by about 390 lines. Re-locate H-P1-7's curve
  guard by symbol, not by the source's line number.

### WP-E8 MLS marker gaps + frozen diagnostics · C · H-P1-8 + S-`mls-tpdo-period-gap-detector`
- **Gate:** the bench answer on 1800h:05 (§5). If it reads **0** (on change), disable the
  gap detector while stationary.

### WP-E9 IMU gaps during a survey leave a trace · R · H-P1-16 as source

---

## M6: durability, evidence, test infrastructure

| WP | Items | Build | Notes |
|---|---|---|---|
| WP-P1 | **Platform freeze** (decision 7): ROS apt source on `snapshots.ros.org/humble/2026-09-14` with a `Package: *` pin, `packages.ros.org` at -1, purge/hold `ros2-apt-source`, kernel meta holds (`apt-mark manual` 5.15.0-187), snap refresh hold, needrestart drop-in (never auto-restart amr.service), unattended-upgrades policy with the timers masked and a monthly window documented in RUNBOOK. S §2.14 items | D | Files in `amr_ws/deploy/platform/`; `install.sh` installs them; `validate.sh` checks `apt-cache policy` and `apt-mark showhold`. **Delta 2026-11-16:** freeze **both** PCs. Unit 2 was installed from live `packages.ros.org` (alpha-setup), so its package set may differ from the snapshot: switch alpha-setup to the snapshot source. Record the GRUB-fallback kernel per unit. The chromium snap hold is a manual alpha-setup step today; move it into the platform files |
| WP-P2 | **Snapshot move to 2026-10-12** for tf2 0.25.24 (S-`tf2-0-25-24-abba-fix`) + S-`platform-manifest-lock` (pure manifest module + committed baseline, `platform.txt` in the report zip) | D | Owner runs it in a maintenance window: `~/.amr` copied off, clean `colcon build`, run_all, focused pytest, one unified sim, then a witnessed vehicle run. **Delta 2026-11-16:** the manifest also covers the pip packages (`paho-mqtt==2.1.0`, flask). Compare the agv-01 and agv-02 manifests |
| WP-P3 | **CAN re-plug** (decision 9): `amr.service` `After=`/`WantedBy=canable@can0.service`; `canable@` `Restart=on-failure`, `RestartSec=2`; `reset-failed` verb in `amr-web.sudoers`; versioned `canable@.service` + `70-canable.rules` (+ USB `power/control=on`) | D | Contract test parses the units. Takes effect at the next witnessed enable. **Delta 2026-11-16:** `After=` is done (§2). Left: `WantedBy=`, `Restart=on-failure` (alpha-setup's text has `Restart=no`), the sudoers verb, and the versioned units. `70-canable.rules` is a per-unit template that takes its serial from profile `can.adapter_serial` (agv-02's is still empty). The web `reset-failed` must **not** clear an identity-mismatch failure: that needs the engineer at the PC |
| WP-P4 | Logs/disk/storage (H-P2-7) + S-`ros-log-bounding` (`ROS_LOG_DIR` under the state dir, tmpfiles, `--disable-external-lib-logs`) | R/D | — |
| WP-P5 | Hardware watchdog (H-P2-5, watchdog part): `/etc/modules-load.d/iTCO_wdt.conf` (the HWE package blacklists it), `RuntimeWatchdogSec=30`, `kernel.panic=10` | D | Owner checks `wdctl` first (§5, no CAN needed). Skip the txqueuelen and scheduling parts until WP-B1's overrun counter has a shift of data |
| WP-P6 | Black box: S-`rosbag2-snapshot-mcap` (always-armed snapshot recorder, low-rate `_ui` topics + DeviceHealth + events, `--node-name amr_blackbox`, dumped on FAULT/stop edges into the report zip) | R | Pure trigger-policy test. Owner runs a pidstat check before default-on. **Delta 2026-11-16:** add OrderState / the station bridge status and `/amr/rear/trolley` to the snapshot topics |
| WP-P7 | Supply/brownout (H-P2-6) | R | — |
| WP-P8 | Drive odometry bridge + plausibility (H-P2-2) | R | Update the R06 contract test deliberately |
| WP-P9 | MLS reboot/variant (H-P2-3) | R | Read-only 0x70A |
| WP-P10 | Scanner config hygiene (H-P2-4): launch from `LIDAR_*` keys, fixed texts, `validate.sh` checks enp3s0 · SAFETY-LISTED for any QoS change on `/output_paths` | R | Measuring the p99 inter-arrival is a §6 item. This gives the `lidar.*` profile keys a consumer, which settles L D01: keep them. **Delta 2026-11-16:** two scanners. Generate both driver configs from the profile. `nanoscan3_rear.yaml` has placeholder IPs and port 6061 and no profile keys: add `rear.sensor_ip`, `rear.host_ip` and `rear.port` (≠ `lidar.port`) to both profiles, with schema and refusal tests. validate.sh checks the rear link once the rear is fitted |
| WP-P11 | S-`ipc-throttle-telemetry` (thermal_throttle counters next to the IPC temperature on the HMI) | R | sysfs fake-tree test. The N97 throttles while showing ~65 °C. **Delta 2026-11-16:** `cpu-power-limit.service` (PL2 15 W) and `cpu-freq-cap.service` (2.2 GHz) are now versioned and installed, but enabled by hand. The telemetry also shows the caps work; validate.sh warns if either unit is not enabled (it checks only syntax today) |
| WP-T1 | H-P3-1 pure tests; S-`hypothesis-stateful-gating` (derandomized, outside EXPECTED_CHECKS) | — | — |
| WP-T2 | H-P3-2 sim fault hooks + S-`fake-output-paths-from-field-geometry` (sim only, refuses domain 10, asserted in `test_launch_layers`) | C | **2026-11-16:** copy the pattern of `amr_sim/fake_trolley_node.py` and its "never launched on a vehicle" assertion in `test_launch_layers` |
| WP-T3 | H-P3-3 opt-in sim cases | — | Once, sequentially |
| WP-T4 | S-`amcl-persisted-initial-pose`, S-`odom-twist-from-606c` (measure the 606Ch lag on a logged run before switching) | R | **2026-11-16:** `home-auto-confirm-plan.md` Part B re-seeds AMCL at HOME in LINE and never runs after a service restart. The persisted pose covers the restart case, so they complement each other. Keep home-auto-confirm's "monitor code unchanged" promise, or say that it changes |

---

## Z: parked or conditional (trigger named)

| Item | Trigger |
|---|---|
| ~~WP-Y1 E-stop status DI~~ **Withdrawn 2026-11-16 (decision 22).** Replaced by `manuals/emergency-suite-plan.md` Part B (E1–E8), which uses `panel.di_estop_ok` (DI09). Carry two of Y1's checks into Part B E1: the key must be in the COM1 range DI09–DI0F (DI07 is COM0 and won't read a sourcing output; DI08 is Manual Arm), and it must be distinct from the panel/pendant channels. The key goes into both profiles (§0 rule 4). Part B E5 replaces the torque-loss guess (`job._safety_cause` and the executor's), so no other WP touches it. When E5 is built: a rear OSSD stop also reads as torque loss (station-call O8) and must not become `estop` once the DI exists; and O-3 must be settled first. Part B adds no-motion layers to `gating.py` and the mux, so the safety-listed rule (§0 rule 5) applies | Trigger met: Q3 → DI09 wired (owner 2026-11-15). Build from emergency-suite-plan Part B |
| WP-Y2 S-`profile-do-names-from-sheet` + S-`io-mapping-parsed-profile-test` (with KNOWN_OPEN for DO8, decision 15, and for the `«placeholder»` rows: Q3's destination, the Manual Arm switch details) | HT-2 mostly done (2026-11-16): CK-TP5162 is in io-mapping §4 and Q3 has its destination (DI09). Left: the Manual Arm terminal-block numbers («TB?»). Q3 leaves KNOWN_OPEN. Both profiles still name `di_names[9]` "[SPARE]" (now ESTOP OK, set it with Part B E1) and every `do_names` entry "[SPARE]", although DO0 and DO1 are the horn/alarm outputs. Apply to both profiles |
| H-P1-12 scanner watch wrapper (exit + respawn on `/scan` silence) | A scanner-only power loss is observed, or HT-1 shows the data output is not saved |
| S-`sick-driver-no-write-fork` | HT-1 proves the Safety Designer data output persists |
| H-P1-14 odometry under STO | Operator observes `/wheel_states` during a field trip (decision 19) |
| `gyro_sign` VERIFY closure | Operator CCW spin (decision 19) |
| S-`blvr-tpdo3-hwto-speeddev` + `blvr-tpdo3-tpdo4-monitor` + `blvr-407B-information-bits` (one TPDO3/4 change, guard steps tested) | §5 bench reads confirm 1A02h/1A03h are free and the 407Bh layout matches MEXE02 |
| S-`mls-tpdo7-gyro-stream` + `mls-imu-init-and-axes` | WP-B1 done and §5 reads 1A06h |
| H-P2-8 DIO hardware side (loopback, module comm-loss reset) | HT-2 + module manual for CK-TP5162 |
| H-P2-10 connector-health trend | WP-H1 deployed for a week |
| H-P2-11 IMU TPDO path | Gyro TPDO commissioned |
| C Tier 4 (C++ ports: scan_gate, cmd_mux transport) | Re-profile after M4 shows a node still > ~10 % |
| PL1 backstop, S-`pm-latency-baseline`, `pmqos-cpu-latency-holder`, EPP change | A turbostat run is approved (decision 20). If approved, the PL1 backstop edits `amr_ws/deploy/cpu-power-limit.service` (`constraint_0`); today it writes PL2 only. See O-4 |
| S P2 navigation (`along-track-goal-checker`, `nav2-fault-reporting-plugins`, `vector-pursuit-controller`, `nav2-keepout-filter`), `dt-raymarch-field`, `odom-calibration-umbmark-scanref`, `rosbag2-replay-regression`, `survey-flight-recorder-slam-replay`, `can-flight-recorder`, `cgroup-scope-sim-tests` | Owner picks them after M6 |
| S-`can-adapter-real-error-counters` | Owner buys the adapter (decision 10) |

---

## 5. Bench session (owner, `amr.service` stopped) — what to read

None of these reads writes anything.

**Per unit (2026-11-16):** agv-01 and agv-02 have their own drives, MLS and RFID reader. Run the
session on each unit before acting on its answers there. Turn a profile key on (for example
`rfid.heartbeat_s`) only in the profile of the unit that was benched.

**No CAN needed (can run any time):**
1. `wdctl`; `lsmod | grep -i iTCO`; `ls /lib/modprobe.d/ | grep -i blacklist` → WP-P5.
2. `ip -details -statistics link show can0` → baseline TX dropped/errors → WP-B1(e).

**Needs WP-0B (`sdo_probe`), with the service stopped:**
3. `sdo_probe --preset mls-tpdo`:
   - 1800h:05 = 10 → timer; 0 → on change → WP-E8.
   - 1806h / 1A06h → WP-Z gyro TPDO.
   - A 1A06h abort means the mapping is fixed: fall back to Table 16.
4. `sdo_probe --preset drive-health`:
   - 1802h/1803h:01 has bit 31 set (TPDO3/4 disabled, i.e. free).
   - 1A02h/1A03h:00 = 0.
   - 60FDh bit 3.
   - 407Bh.
   - 603Fh and 1003h history.
   - → WP-B4 preflight and the WP-Z TPDO3/4 decision.

**RFID:** ~~5. Reads/s with and without 0x0072 at 1 Hz~~ — withdrawn 2026-11-16 (decision 23).

**Dropped from the bench list:**
- "slcan TX backlog during arm/disarm": measured in service by WP-B1(e) and WP-B2 instead.
- "Does 0x0050 interleave": moot, the heartbeat uses 0x0072.

---

## 6. Owner and operator steps (not for the agent)

| # | Step | Unblocks |
|---|---|---|
| HT-1 | Open the nanoScan3 project in Safety Designer **read-only**: is a continuous UDP data output to 192.168.3.2:6060 saved, and at what publishing frequency? Don't transfer anything | WP-Z scanner items |
| HT-2 | Electrical docs through `documentation/electrical/agent/SKILL.md` (interpret → confirm → build). **Done 2026-10-28:** DI08 = Manual Arm in `io-mapping.md` and sheets 08/09. **Open:** module **CK-TP5162** on sheets 03 and 09 and in `io-mapping.md` (no mention yet; also check the "12 relay" text against `num_do` 16); fill the `«placeholder»`/`?` items: the Manual Arm switch type, terminal and wire, Q3's destination and its test-pulse setting; remove Q3 from sheet 08's orange cable if it is not wired; plan the Q3 → DI09–DI0F E-stop status row. **2026-11-16:** CK-TP5162 is in io-mapping §4; Q3 → DI09 is wired and documented. Still open: the Manual Arm «TB?» numbers | Part B E1 (was WP-Y1), WP-Y2 |
| OP-1 | CPU §3 acceptance, no dev session attached for 60 s: `pidstat -u 10 6` per process, idle LINE. Repeat after M4, **idle and during a running LINE trip** (2026-11-16), on each unit | §6 projection |
| OP-2 | After each milestone: a witnessed LINE run; watch `LineState.track_hz` holds, panel/lease stale events and FIELD_UNKNOWN chatter | M1, M4 rate changes |
| OP-3 | Fault-injection table (hardening §5), rows matching the built WPs only | M1–M5 |
| OP-4 | Apply the deploy files (WP-0E, WP-P1, WP-P3, WP-P5, WP-H5) off-shift with `install.sh` + `daemon-reload`; run `validate.sh` | M0, M3, M6 |
| OP-5 | `/output_paths` p99 inter-arrival from one bag (`bag_report`) against the 0.07 m `stop_m` budget | WP-P10 |

---

## 7. Status

Checked against the tree on 2026-10-28 (64e9654), by grepping each WP's anchor symbol.
"Partial" means L landed part of the WP. §2 and the WP text say which part.

| WP | State | Date | Evidence |
|---|---|---|---|
| WP-0A | done (C: package.xml) | 2026-10-28 | test_launch_layers `test_foxglove_is_retired`; validate.sh warns on a leftover AMR_FOXGLOVE |
| WP-0B | done | 2026-10-28 | run_all (test_canmon sdo_probe ×4, test_lss owner lock ×2) |
| WP-0C | done | 2026-10-28 | test_route reverse ceiling; RUNBOOK/plan text |
| WP-0D | done | 2026-10-28 | test_launch_layers `test_nav2_lifecycle_managers_do_not_rebond_a_dead_node` |
| WP-0E | done (D: owner installs) | 2026-10-28 | deploy/pwrbtn-watch.sh (same line format, checked), logrotate-amr, kiosk/ copies, rmem_max; validate.sh notes kiosk drift. `trim-services.sh` still owner |
| WP-A1 | done | 2026-10-28 | run_all test_rfid ×5; test_rfid_intake, test_mission_engine (seq ahead), TagOdometer |
| WP-A2 | done (C: hold_device) | 2026-10-28 | test_hold_policy (policy = catalogue), test_line_authority, test_auto_resume (controller, panel) |
| WP-A3 | done, minus the FAULT bound | 2026-10-28 | test_line_authority sensor holds, test_marker_run blind travel. **No bound value exists for "blind_m above a bound → FAULT": owner to set one** |
| WP-A4 | done | 2026-10-28 | test_line_authority drive_fault ×3, test_mission_engine tape distance, test_r07 `stale` state |
| WP-A5 | done (D: chrony drop-in) | 2026-10-28 | test_authority future stamps ×3 + steady-timer contract |
| WP-A6 | done | 2026-10-28 | test_panel_io release-first ×4 |
| WP-A7 | done (C: work_mode_mismatch) | 2026-10-28 | run_all test_mission ×5; test_mission_engine gap ×2, work mode |
| WP-A8 | done | 2026-10-28 | test_auto_resume field ages ×4; test_launch_layers executor field_source |
| WP-A9 | done | 2026-10-28 | test_mission_engine `..._while_braking_in_a_field_hold...` |
| WP-A10 | done | 2026-10-28 | run_all test_config ×9; test_authority profile contract; test_cmd_mux_defaults |
| End of M1 | **unified sim not run** | 2026-10-28 | Needs `colcon build` (LineState/RunState.hold_device, StationDetection.work_mode_mismatch) and the service stopped: owner, off-shift |
| WP-B1 | partial | 2026-10-28 | (e) only: can/bus diagnostics `loop_max_ms`, `loop_overruns` (> cmd_timeout_s), `tx_dropped`. **Open:** (a)–(d) read_sensor ≤ 0.05 s, one-read-per-poll rediscovery chains, nmt_nowait, one sensor SDO per loop, IMU miss-rate backoff. Left until M1/M2 have had a witnessed run: it reshapes the bus thread's timing |
| WP-B2 | done | 2026-10-28 | test_canopen TxHealth, loop contract, decode/idle counters; CAN_TX_FAILED row; can/bus diagnostics tx_errors, error_frames, decode_errors, idle_errors, mls_errors |
| WP-B3 | done | 2026-10-28 | test_canopen standstill ×2, 1017h in prepare, teardown guard; test_arm_policy backoff; run_all test_canmon canopen guard scan |
| WP-B4 | partial | 2026-10-28 | Done: engineer-only Recover (test_operator_ux), supervisor acks `/drives/ack_fault` with the run refusal (test_readiness), clean preflight clears the latched alarm, release() failure takes fault() semantics (test_canopen), web DRIVE_FAULT/DRIVE_SILENT row hides DRIVES_NOT_READY, action texts, RUNBOOK. **Open:** 603Fh/1003h read into the fault detail and report zip, boot-up frame `rebooted` flag, DriveStatus `fault_code`/`fault_detail` (C) |
| WP-B5 | done | 2026-10-28 | run_all test_lss read_mls lock ×7 |
| WP-B6 | done | 2026-10-28 | test_canopen router error/RTR drop, (id, extended) key; fixtures now build 11-bit frames |
### Implementation 2026-11-16 (uncommitted, dev box only)

Built on the Windows dev box: pure tests ran there, against a baseline failure set taken before
any change. Everything that needs rclpy, ROS launch, CAN, systemd or the vehicle is **unverified**
until the owner's on-vehicle checks. Marks: R restart, C `colcon build`, D deploy file (owner,
`install.sh`). `EXPECTED_CHECKS` 938 → 984.

| WP | State | Evidence / what is still open |
|---|---|---|
| WP-B1 | done (R) | (a)–(d): `read_sensor` ≤ 0.05 s, `_Job` rediscovery chains, `nmt_nowait`, `SensorToken` one MLS SDO per slot, IMU miss rate 3/10. test_sensor_slots, test_mls_imu, test_mls_track |
| WP-B4 | done (C) | 603Fh/1003h in preflight, diagnostics and `drives.txt` in the report zip; boot-up frame → `decide(rebooted)` → DRIVE_REBOOTED; DriveStatus `fault_code`/`fault_detail`. test_drive_fault_history, test_reports_drives |
| WP-H1 | done (C) | `agv_core/health.py`, `DeviceHealth.msg` on `/amr/device_health`; owners drive_node, panel_node, station_bridge, trolley_node; no RFID (decision 23). test_health |
| WP-H2 | done (C) | `ModeState.base_missing`; `health_view.py`: DIO_LINK_*, PANEL_STALE IP from config, LINE headline, DeviceHealth/scanner/disk/eventlog rows. test_hmi_truth, test_liveness |
| WP-H3 | done | `event_recorder_node` (launched, respawning), `agv_core/eventlog.py`, `journal-wifi.txt`; D08: `agv_core/events.py` removed. test_event_recorder |
| WP-H4 | done (R) | STATUS=, EXTEND_TIMEOUT_USEC, respawn reset, exits file names the node, executor heartbeat, rsp/imu_bias respawn, launch-walk allow-list; FAULT events logged under the fault code. test_liveness, test_fault_event (rclpy) |
| WP-H5 | done (D) | amr.service WatchdogSignal/OOMPolicy/OnFailure/ExecStop/ExecStopPost; amr-failed page in `/run/amr/`; kiosk fallback fixed; uptime `classify()`. test_unclean_death, test_uptime |
| WP-C1, C2 | done (R) | `take_message` drain, raw `/scan_gated`, raycast oracle, scan_gate pass-through, TF thread. test_stream_age, test_raycast, test_scan_gate_raw |
| WP-C3 | done (R) | `PublishGate`. test_panel_publish |
| WP-C4 | done (R) | `SupervisorFeed` node. test_hardness (rclpy) |
| WP-C5, C10 + P8 | done (C) | drive_node publishes `/imu/data` and `/odom_raw`; diff_drive_odom/imu_bias sim only; feedback plausibility. test_gyro_filter, test_wheel_odom, test_r06 |
| WP-C6 | done (R) | idle 10 Hz with edge wake, `/imu/data` only ARMED–HOLD, `/odom_raw` dropped. test_tick_rate |
| WP-C7 + D16 | done (C) | no horn engine, motion lamp from DriveStatus `turning`; horn section retired in both profiles. test_panel_publish |
| WP-C9 | done (R) | idle zero at 10 Hz. test_idle_zero |
| WP-C11 | done (R) | `start_parameter_services=False` on production nodes; KEEP list commissioning, route_executor, sim. test_param_services |
| WP-C12, C13 | done (R) | calls node, live timers on demand, pp_status on demand. test_adapter_contract, test_live_demand |
| WP-C14 | deferred | NAVIGATION has no UI |
| WP-C15 | partial | `bond_timeout: 0.0` + D53 done; controller/behavior/container deferred with C14 |
| WP-C16 | done (C) | web consumer + 5 Hz publishers. test_live_display |
| WP-C17 | done (R) | station_bridge GuardCondition wake. test_bridge_wake |
| WP-E1, C8 | withdrawn | decision 23 (RFID not used; `rfid.enabled` false, rfid_node not launched) |
| WP-E2 | done (R) | invalid path = UNKNOWN (gating, drive_state, RearField). test_field_limit, test_trolley_detect |
| WP-E3 | done (R) | protective polarity from scanner_fields to mux/follower/executor; rear is the named exception |
| WP-E4 | done | `scanner_health.py` + web rows + status_overview + SURVEY_SCAN_GAP. Fixture rebuilt, not recorded: confirm key names on the vehicle |
| WP-E5 | done | waitress via `serve.py` (werkzeug fallback), call timeouts; pip pin in alpha-setup |
| WP-E6 | done (FC03 off) | retries=0, drops/retries_10min; FC03 behind `dio.COMBINED_IMAGE=False` until benched |
| WP-E7 | done, withholding off | `agv_core.gyro` check (logs only: `gyro_check` default false until the gyro_sign VERIFY), StampTracker frozen, curve guard |
| WP-E8, P9 | done | TPDO hole detection (`GAPS_WHILE_STATIONARY=False` until the 1800h:05 read), marker continuity, MLS reboot; line consumers. test_mls_track, test_tpdo_holes |
| WP-E9 | done | `survey_trace.ImuGaps`. test_survey_trace |
| WP-P1, P3, P5 | done (D) | `deploy/platform/`, canable units + rule template, watchdog files. test_unclean_death |
| WP-P2 | owner | snapshot move in a maintenance window |
| WP-P4 | done (R/D) | ROS_LOG_DIR, tmpfiles, `/` watched + DISK_READONLY, 2/1/1 stop, quiet logs |
| WP-P6 | done, default off | black box (`AMR_BLACKBOX`). test_blackbox |
| WP-P7 | done | `bus_v_trip_low` (46.0 V placeholder), SUPPLY_* events, chip, Start refused at or below trip_low |
| WP-P10 | done (C) | rear.* keys (placeholders), `scanner_config`, both launches from the profile |
| WP-P11 | done | throttle counters on the HMI chip |
| WP-T1 | partial | test_gating_properties (needs hypothesis), drive-state strings; test_line_authority fixture left (see note) |
| WP-T2, T3 | done, sim unrun | fault hooks, fake_output_paths, 4 sim cases, stale tests fixed |
| WP-T4 | partial | 606Ch twist switch (default counts); persisted initial pose open |
| WP-Y1 | withdrawn | → emergency-suite Part B E1–E7 done (E8 vehicle acceptance open) |
| WP-Y2 | done | ESTOP OK / horn DO names; test_vehicles test_wiring |

Notes:
- test_line_authority builds four "fresh age + track" inputs the node never produces; the
  vehicle holds `sensor` at once there (stricter). Left as is, open.
- **Superseded 2026-11-16 (owner: "do A + B"):** a hold no longer ends a U-turn. The approach
  and the stop at the tape end start again; a pivot under way continues as a fresh turn with its
  gates lowered by the angle already turned (`uturn.resume`, `tape_run.hold_u_turn`). FAULT only
  when the counts are missing, the AGV turned more than 30 deg while held, or no angle is left.
  A field stop mid-pivot now resumes by itself like any field stop. Vehicle check: do 6064h
  counts keep counting under STO? Old note follows.
- An E-stop during a U-turn still FAULTs the run (a pivot is never resumed part-way), so the
  trip ends there. Owner to confirm under O-3.
