# AGV-02 on the same branch: what changes, and where it lives

Status: analysis, 2026-11-14. No code changed yet. Scope: the second vehicle (`gvipc-evo-02`, Wi-Fi
`192.168.2.120`), identical hardware, on branch `gvievo-main`. The station session's answers of the same day are in
section 7.

## 1. Recommendation

**One branch, one codebase. Each vehicle's differences go in files named after it, and those files are
committed. Only three things stay local on each PC:**

1. which vehicle the PC is (one line: `AGV_PROFILE=agv-02`);
2. secrets (MQTT password, web PIN);
3. what that vehicle learned on its own floor (map, taught positions, MLS calibration, logs).

Why the parameters themselves should not be local, uncommitted files:

- **Tests:** the profile loader is strict (unknown or missing keys are fatal) and `tests/test_config.py`
  checks it. A local profile is never tested and drifts silently from the schema. The next `git pull` that
  adds a key then stops unit 2 at boot.
- **Recovery:** a reinstall, a failed disk or a second clone loses a local profile. A committed one comes back
  with the repo.
- **Review:** one diff shows both vehicles' values side by side. A gain changed on one vehicle is visible.
- **Already designed for it:** `AGV_PROFILE` selects `profiles/<name>.json`. `profile_name` must match the
  file name. `station.serial_number` must follow it (`agv-02` → `agv2`, `agv_core/config.py:1414`). The
  station bridge, topics and order shapes come from the profile and the site mission, not from literals
  (`manuals/station-call-plan.md` section 20).

The IP address is not a repo parameter at all. The AGV software never names its own address. It lives in
NetworkManager (`agv-net`) on each PC (`alpha-setup.md` section 2).

## 2. Where each per-vehicle value lives

| What | Unit 1 today | Unit 2 | Where | In git |
|---|---|---|---|---|
| Hostname | `gvipc-evo-01` | `gvipc-evo-02` | OS | no |
| Login user | `gvipc-evo-01` | `gvipc-evo-01` (deploy files hard-code it, decided 2026-10-12) | OS | no |
| Wi-Fi address, gateway | `.110/24`, gw `.5` | `.120/24`, gw `.5` | NM `agv-net` | no (recipe in `alpha-setup.md`) |
| Wired links (MLS, DIO `192.168.1.30`, lidar `192.168.3.x`) | private per unit | same addresses, own cables | netplan + profile | profile yes |
| CANable serial | `2087327F5548` | **TBD** | udev rule + `can.adapter_serial` | profile yes |
| Which profile | default `agv-01` (`AGV_PROFILE` unset) | `AGV_PROFILE=agv-02` | **new local file** (section 3) | no |
| Profile | `profiles/agv-01.json` | `profiles/agv-02.json` | repo | **yes** |
| MQTT identity | `agv1` | `agv2` | `station.serial_number` | yes |
| MQTT user and password | `~/.amr/station-mqtt.json` (600) | own file, user `agv2` | local | **never** |
| Web PIN and secret | `~/.amr/web.json` | created on first run | local | **never** |
| Site mission (home, attach, groups, machines, circuits, junction orders) | `missions/site-103.json` | new `missions/<agv-02 mission>.json` | repo | **yes** |
| Map | `~/amr_maps/rev-boiacca-map-01` rev4 | rev5 (the south side, surveyed 2026-11-12 for AGV-02) | local | no |
| Taught positions (stations, marks, passes, areas) | `~/.amr/teach/<map>-rev4/` | taught on unit 2 | local | no |
| Active tape graph | `~/.amr/line_graph.json` → g11 | its own g-number | local | no |
| MLS calibration | `~/.amr/mls_cal/` | its own | local | no |
| Front lidar, IMU and chassis mounts | xacro defaults (`amr_description/urdf/amr.urdf.xacro:26-50`) | same if the mounts are identical | repo, **not per vehicle** | yes |
| Scanner fields, NanoScan3 driver | `amr_bringup/config/scanner_fields.yaml`, `nanoscan3*.yaml` | same if the FX3 and scanner config are identical | repo, not per vehicle | yes |

## 3. Changes needed in the repo (code)

**Status 2026-11-14:** R1–R6 and R8–R10 are built and tested, not committed. R7 waits for AGV-02's route. On
unit 1 nothing changes: there is no `vehicle.env`, so the default `agv-01` applies, and the identity check passes
(`gvipc-evo-01` runs `agv-01`). The supervisor script runs the check, so it takes effect at the next
`amr.service` restart.

| # | Change | Status | Files |
|---|---|---|---|
| R1 | **Local selector.** `env/vehicle.sh` reads `AGV_PROFILE=<name>` from `$AMR_STATE_DIR/vehicle.env`, one plain-name line, never executed. No file means `agv-01`. An `AGV_PROFILE` already set in the environment wins. The supervisor (`amr-supervisor.sh`) and `~/.bashrc` both source it. | Built | `amr_ws/env/vehicle.sh` |
| R2 | `validate.sh` takes `AMR_STATE_DIR` from `amr.env`. It runs under sudo, where `$HOME` is root's. It reads the same file through `vehicle.sh` and checks that profile. | Built | `amr_ws/deploy/validate.sh` |
| R3 | **Identity guard.** `python3 -m agv_core.identity`: host `gvipc-evo-NN` must run profile `agv-NN`; any other host isn't checked. `amr-supervisor.sh` runs it before the supervisor starts. On a mismatch the reason goes to the journal and the script exits before can0 or the station link opens. After systemd's restart limit (3 in 60 s) the unit is `failed`. Recovery: fix `vehicle.env`, then `sudo systemctl reset-failed amr && sudo systemctl start amr`. | Built | `agv_core/identity.py`, `amr_ws/deploy/amr-supervisor.sh` |
| R4 | **Tests pin the reference profile.** `tests/run_all.py` and every `amr_ws/src/*/test/conftest.py` set `AGV_PROFILE=agv-01` before any `agv_core` import. 5 conftests are new, only for this. `test_config` now restores the variable instead of deleting it, and uses `agv-99` as its missing name, since agv-02 exists. | Built | as listed |
| R5 | **Every profile is tested** (`tests/test_vehicles.py`, +17 checks, 938 in all). Each loads. A site mission is required when `live` or `station` is on, and loaded when present. No two profiles share a station serial. Also tested: the selector parsing, the identity rule, and the pin itself. | Built | `tests/test_vehicles.py`, `tests/run_all.py` |
| R6 | `profiles/agv-02.json` differs from agv-01 only in: `profile_name`, `station.serial_number` `agv2`, `station.enabled` and `no_trolley_run` false (no broker user yet), `tape_loc.live` false (not taught), `site_mission` `site-103-agv2` and `shadow_circuit` `C-ROW3` (planned names; the mission isn't written yet), and `can.adapter_serial` `""` (any one CANable; fill it in after reading it, `alpha-setup.md` section 3). Everything else, calibration included, is AGV-01's until measured (section 5). RFID is as on AGV-01. | Built | `profiles/agv-02.json` |
| R7 | AGV-02's site mission `site-103-agv2`: HOME-N, its attach, row 3 and the STU7–10 line. Node ids come with contract v1.5. | **Waits**: route not taught, section 4 | new file |
| R8 | `tape_merge`: `--circuit` is required, with no hidden `C-BTU` default. `--mission` defaults to the profile's site mission. The runbook (3.2B) command now names `--circuit C-BTU`. | Built | `amr_line/tape_merge.py`, `manuals/tape-localization-runbook.md` |
| R9 | The "At home" tooltips say "its home position", not `HOME-N`. | Built | `teach.html`, `mapping.html` |
| R10 | Docs: `alpha-setup.md` per-unit table, section 5.3 (creating `vehicle.env` on unit 2), checklist step 11, drift list and open items. The `config.py` docstring. | Built | docs |

Left as is, noted: the bench tools' fallback adapter serial is unit 1's (`agv_core/drivers/canbus/sdo.py:18`).
It only applies when `can0` is down and a tool opens the adapter over slcan. The bench tools never read the
profile, by design. On unit 2, with `can0` down, pass the serial or bring `can0` up first.

Not needed: changes to `vda_order.py` and `vda_state.py`. Machine lookup, swap nodes and the HOME and ATT nodes
all come from the site mission (`swaps(site)`, `canonical_order` reads `site["HOME"]`). The bridge is one per
vehicle in its own base launch. DDS is bound to `lo`, so two units on `agv_field` never see each other's
topics.

## 4. AGV-02's site mission

From `manuals/site-layout-103.md`:

- **D1:** two fixed halves.
- **D2:** AGV-02 serves BTU1–8 and STU1–10, 18 machines.
- **Its territory:** the south trunk from merge R, the departure lane's R1570 exit at J-S, and row 3 by the
  left vertical going south.

| Item | Known | Open |
|---|---|---|
| Machines | **Owner, 2026-11-14:** AGV-01 serves the north side, BTU9–24 and MRU1–4. AGV-02 serves BTU1–8 and STU1–10. STU1–10 = STU1–6 on row 3, facing BTU1–6, plus STU7–10 on their own line. This closes site-layout-103 open item 1. | — |
| BTU1–6 + STU1–6 work | Swap. One stop per facing pair and one START, as v1.4's BTU9–16 facing BTU17–24. **BTU1 faces STU1, … BTU6 faces STU6**: the numbers run the same way, unlike row 2. BTU7 and BTU8 face nothing: one stop each, as v1.3 (owner, 2026-11-14). | Uses v1.4's `machines` parameter and one-stop shape: built on the AGV 2026-11-14 (generic over the site mission: the own machine is the first listed at a stop). Row 3's node ids still need contract v1.5. |
| STU7–10 work | Release the empty trolley, take the full one back: as MRU1–4. **Pairs allowed**: two STU7–10 per trip, as two MRUs. U-turn after the release point, as MRU (owner, 2026-11-14). No new kind of stop work. | The line is the projection's separate exit, "TO STU 7-10 / FROM BTU 1-8 / STU 1-6 and STU 7-10 (AGV 2 only)" (label corrected 2026-11-14; it said STU 1-4). |
| Home | **Owner, 2026-11-14:** AGV-01 stays at HOME-N2 (right bay). AGV-02 parks at HOME-N (left bay, taught on unit 1 before 2026-11-06; re-taught on unit 2's map). | — |
| Attach point | ATT is on the departure lane, before J-N and J-S. | Shared with AGV-01, or a second ATT past J-S on R1570? |
| Junction orders | J-S: AGV-01 goes straight and steers right; AGV-02 takes R1570 (left). | J-S's left branch is the STU tape against the lane (memory 2026-11-11). The fork needs its own floor check for AGV-02. |
| Map | rev5 adds ~40 m south, for AGV-02 only. | rev5 has no pillar fix and no dynamic areas. Its MRU line reads 5–15 cm off rev4. That doesn't matter to AGV-02, but it is not the same map as AGV-01's. |
| Route | — | **None of AGV-02's route is mapped or driven** (owner, 2026-11-14): not the road to and from BTU1–8 / STU1–6, not the release points for BTU1–8, STU1–6 or STU7–10. rev5 covers the south occupancy only; the tape graph has no AGV-02 leg. Everything is taught on unit 2. |

## 5. Unit 2 calibration (identical hardware ≠ identical numbers)

Measure on unit 2 and write into `agv-02.json`. Don't copy unit 1's values unless they are checked:

- `vehicle.track_m`, `wheel_dia_m`: odometry. Unit 1's xacro has 0.487 measured.
- `can.adapter_serial` (and the udev rule).
- MLS: `mls_cal`, `invert_error`, `branch_positive_is_left` (sensor mounting).
- Autopilot gains: start from unit 1's, then do a first empty lap at NORMAL. Caps stay as they are.
- `u_turn_gyro_min_deg`: unit 1's 172 came from its encoder over-read (2026-10-24).
- Lidar mount, front and rear. If unit 2's differs from the xacro defaults, move those defaults into the
  profile, the way `rear.laser_*` already is.
- Scanner fields and FX3: the safety configuration is validated per vehicle on the hardware. The repo copy is
  only what software reads to explain a stop.

## 6. How the two PCs use one branch

| Step | Rule |
|---|---|
| Clone | Both PCs: `~/agv_can` on `gvievo-main` (`alpha-setup.md` "Before you start"). |
| Develop | One place commits: the owner, from whichever PC. The other PC only pulls. Don't edit tracked files on both, or the pulls conflict. |
| Vehicle differences | Only in `profiles/agv-0N.json`, that vehicle's site mission, and the local files in section 2. **Never a per-vehicle branch, and never an `if hostname == ...` in code.** |
| Deploy | `git pull`. If `amr_interfaces`, a package or an entry point changed, `colcon build`. Then restart `amr.service`. |
| Verify | `tests/run_all.py` pins agv-01 (R4). R5 checks agv-02's profile and mission on either PC. |
| Local state | Not in git: `~/.amr/` (vehicle.env, secrets, teach, graph pointer, calibration, logs) and `~/amr_maps/`. Back it up per vehicle. Copy a map from unit 1 to unit 2 by hand (rsync), and only the map, never `~/.amr` whole. |

## 7. Station side and two-vehicle operation

The station session answered on 2026-11-14. It is analysis only, and nothing is built for AGV 2 on either
side. Today the station supports only `agv1`, by design. It has places ready for a second AGV (topics,
`AgvView`, the free check, headerId counters, `Call.agv`, the status strip), but knows nothing about
BTU1–8, STU1–10 or any AGV-02 node.

| Topic | Station today | Recommendation (station) | Decides |
|---|---|---|---|
| Contract | One text, AGV-01 nodes only | **One text for both AGVs, one sha256, as a v1.5 bump.** An AGV-02 section with its node ids, order shapes and stop work. Each AGV refuses shapes not its own with `VALIDATION_FAILURE`. Per-AGV files would mean two hashes to keep in step. | Owner |
| STU1–10 | No STU anywhere | New node ids are a contract change either way. Work other than swap or release/take is also new AGV code and new station order-building code. | Owner (work kind) |
| Dispatch | `choose_agv()` returns `agvs[0]` (`station/dispatch.py:96`). `config.py:219` refuses more than one AGV. `orders.py` names only MRU1–4 and BTU9–24. | **A static machine-to-AGV map in the station config.** The station never sends a machine to an AGV that doesn't own it, and the AGV refuses it anyway (`VALIDATION_FAILURE`, already the case through its own site mission). Pairs stay within one AGV's group. `calls.head` must filter by owner, or an unassigned BTU1 call at the head stalls agv1's queue. | Owner confirms the split |
| Shared tape | Nothing built. Plan section 18 allows only a later dispatch-time function and forbids a stub. | A dispatch-time lock only gates departure. An order is fully released once sent, and `released: false` is refused. So "A is in the zone" doesn't cover A coming back into the HOME complex while B leaves. **First runs: a floor rule plus (a) one AGV out at a time** (no order to B while A has any active order; halves throughput). **(b) A real zone lock** (entry and exit nodes named in the contract, `released: false` horizons, AGV code) only when throughput is needed. Either must fail closed: stale state or an AGV offline counts as in the zone. Wi-Fi gaps of 10 s and more have been seen. | Owner |
| Broker | passwd: `station`, `agv1`, `watch`. No `agv2` ACL lines. The firewall allows .110 and .120. | The owner adds user `agv2` and its ACL lines (plan section 11.2) in an admin shell on the station PC, then restarts the broker. | Owner |
| Buttons and DIO | MRU1–4 on `.10` and `.11`. BTU9–24: DI on `.41`, `.42`, `.51`, `.52`; LEDs on `.43`, `.53`. | The owner supplies module IPs, DI channels and LED outputs for BTU1–8 and STU1–10. | Owner |
| Home per AGV | `config.json` `agvs[].home_node` (HOME-N2) and `attach_node` (ATT), per AGV | AGV-02 can have its own home bay. It must match AGV-02's site mission. | Owner (section 4) |

**AGV-side consequences:**
- The contract-text tests (`amr_station/test/test_vda_swap.py`) read the embedded contract. With v1.5 they gain
  AGV-02's rows, and both vehicles carry the same hash.
- (a) needs nothing on the AGV.
- (b) is new AGV code: holding at a horizon end until the station extends the order.

## 8. Order of work

1. **Owner decisions:** machine split, home bays, STU work and row 3 pairs settled 2026-11-14. Open: the shared-tape
   rule (next), shared ATT or its own, station buttons and LEDs (later).
2. **Repo, offline on unit 1:** R1–R6 and R8–R10 built 2026-11-14 (uncommitted). R7 after the route is taught.
3. **Unit 2 host:** `alpha-setup.md` end to end (hostname, `.120`, udev serial, kiosk, `install.sh`), then
   `~/.amr/vehicle.env` and `station-mqtt.json` for `agv2`.
4. **Unit 2 on the floor:**
   - copy map rev5;
   - At home on its bay;
   - teach its circuits;
   - publish the graph with `tape_merge`, never Build;
   - first empty laps.
5. **Station:**
   - contract v1.5 with AGV-02's section;
   - broker user `agv2`;
   - the button and LED map for BTU1–8 and STU1–10;
   - the machine-to-AGV map and the owner-filtered queue head;
   - rule (a), one AGV out at a time.
6. **Two vehicles at once:** a floor rule plus (a) first. The zone lock (b) is a later contract change.
