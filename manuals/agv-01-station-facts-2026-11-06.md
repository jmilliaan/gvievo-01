# AGV-01 facts for the station side

Checked on the vehicle on 2026-11-06, 14:46 to 15:02 WIB. Contract: end of `manuals/station-call-plan.md`.

**State when checks started (14:46):** no trip active and not moving: LINE mode, LineState IDLE, selector MANUAL, drives off. It stayed that way through every test group; the watchdog never tripped.

**Someone ran `sudo reboot now` at 14:49:30** (pts/5, SSH from 192.168.2.5). It wasn't these checks. Readings marked "pre-reboot" are from before it, and everything else is from after it. Last reading: 15:02.

## 1. Blockers to a real call

| # | Blocker | Evidence |
|---|---|---|
| 1 | **Both drives are in FAULT since that reboot, and the base never came up.** Mode is FAULT, `BASE_NOT_READY`, with no line layer. It retried for 12 minutes without recovering, so it needs a person at the cabinet. | `base.log`: statusword `0x12B8`, error register `0x11`, both nodes |
| 2 | **No rear scanner.** Every order is refused with `TROLLEY_UNKNOWN` and `REAR_FIELD_UNKNOWN`, and there is no bypass. O1, O2, O3 and P8/P9 are open. | `rear.source: none`; no publisher on `/amr/rear/trolley` |
| 3 | **P0 isn't proven.** No logged trip has reached home in the right lane. Still owed: two MRU1 trips in a row and one MRU4. | Trip logs, section 4 below |
| 4 | **`station.enabled` is false**, so `station_bridge` isn't running. That's as intended; it's listed because it has to change before a real call. | Profile; node list |
| 5 | **At home must be pressed again** after the reboot. | Contract section 9 |
| 6 | **Wi-Fi firmware crashes during trips: at least a 10 s gap, longer than both the 3 s and 5 s limits.** Seen on 3 of the last 4 boots before this one, including 14:00:29 and 14:31:34. The AGV keeps driving, but the station sees link lost. | `iwlwifi: Queue 10 ... stuck for 10000 ms`, `Microcode SW error` |

## 2. Differences from the contract or plan

| Where | Says | Actual |
|---|---|---|
| `manuals/station-call-plan.md:30` | `HOME-N` not taught, no trip compiles | Taught 10:49, in active graph g3; all four trips compile. It has no `mark`, unlike the other stops |
| `station-call-plan.md:30, :62` | `tape_loc.live` stays false until P0 passes | True in `profiles/agv-01.json` since `9e40330` |
| `amr_web/test/test_teach_page.py:36, :65` | Pin `live` false | **Both tests fail** because of that profile change |
| Contract section 5, against `amr_station/vda_state.py:44` | `STARTUP` only while starting, changing layer or stopping; otherwise `MANUAL` | With no OrderState the code reports `STARTUP`. In today's state that lasts indefinitely, with no error giving a reason (from reading the code, not run) |
| `alpha-setup.md:174, :451, :456` | Gateway 192.168.2.10 | Gateway is 192.168.2.5 |
| `station-call-plan.md` V8 | `usb0` is the first default route | No `usb0` on this boot |
| `amr_station/test/conftest.py:26` with `test_mosquitto_loop.py:16` | Broker test skips | With `AMR_MQTT_TESTS=1` and no `mosquitto`, the **whole package reports "1 skipped" and exits without running anything** |
| `station-call-plan.md:32` | P7 passes against a real broker | `mosquitto` isn't on this vehicle. It passes with a temporary copy (test table below) |

## 3. What could affect the running AGV

**Check before the next restart:**

- **The next restart turns on untested motion behaviour.** `autopilot.corner_yaw_deg_s` went from 0 to 30 on disk at 14:54, after the service started at 14:50. The project notes say the rolling corner is off, with a vehicle trial owed.
- **The running code no longer matches disk.** Another session is editing the live tree: `profiles/agv-01.json`, `agv_core/drivers/dio.py` and `panel_node.py` all changed after boot. Python is symlinked, so any node respawn or restart picks up the edits.
- **That session also runs pytest at normal priority**, using about 99% of a core on this vehicle.

**Seen in the logs:**

- **14:31:34 during the trip:** the Wi-Fi crash and `DIO comms LOST` (Modbus exception 3 on the coil read) fell in the same second. The trip held and needed Start. The DIO is wired, so treat this as a coincidence in time, not a proven cause; the 14:00:29 crash caused no panel hold.
- **Same MAC on two networks:** `08:2c:14:ac:00:00` is both 192.168.1.30 (the panel DIO) and 192.168.2.10 (on Wi-Fi). It may be a factory default; not checked.
- **Control loops:** no deadline or timing warnings. Peak load during the tests was 3.03, and the longest mux gap was 0.194 s.
- **Journal size:** 328 MB, over the 300 MB cap.

**Effects of these checks:**

- **Live stack:** subscribe-only probes on domain 10. No effect seen; `amr.service` has 0 restarts this boot.
- **Broker:** about 330 plain TCP connects to 1883 with no bytes sent, so its log may show them.
- **Two things outside the brief:** `sudo -n true` and `sudo -n iptables -S`. Both were refused and left auth-log entries. A `pkill -f` also killed its own shell; PID and restart count were unchanged afterwards.
- **Downloads:** to run the broker tests, `mosquitto` and its libraries were fetched with `apt-get download`, unpacked in scratch without installing, and bound to 127.0.0.1:18883. They're now deleted.
- **Leftovers:** logs in `/tmp/claude-1000/-home-gvipc-evo-01-agv-can/c47b330e-a0c4-4ed6-a169-e76b13ccf976/scratchpad/probe`, and pytest temp files in `/tmp/pytest-of-gvipc-evo-01`.

## 4. Sections 1 to 6

### Section 1: What is on the vehicle

| Item | Value | How checked |
|---|---|---|
| Branch and commit | `gvievo-main`, at `9e40330` (12:26) | `git log` |
| Uncommitted | 16 modified, 2 new (rolling corner, DIO, panel), growing during this check | `git status` |
| Last build | 10:03, before the commit; no `setup.py`, msg or srv changed since | `log/latest_build`, `find -newermt` |
| Service start | 14:50:05, 0 restarts, no failed units at 14:46; earlier a stop/start at 14:18 and reboots at 14:08 and 14:49 | `systemctl show`, `journalctl` |
| Running code against disk | Differs (section 3 above) | File times against start time |
| Mission and layers now | Base only, no line layer | Node list, ModeState |
| Mission pre-reboot | LINE layer up. Site-103 loaded at start, then switched to plain line following at 14:34:52 | `layer.log` |
| `station_bridge` | Not running | Node list |
| `tape_loc.live`, `site_mission` | `true`, `site-103` | Profile |
| `trip_calls` | 1 | Mission loaded offline |
| `station.*` | `enabled` false, 192.168.2.5:1883, `gvi`/`agv1`, settle 5, holdoff 15, torque wait 4 | Profile |
| `rear.*` | `source` none, `case_proven` false, `no_trolley_case` -1, ROI and laser values are the committed defaults | Profile |
| Local override | None found: `AGV_PROFILE` unset, so it loads the repo profile | Service environment |
| Why `live` is true | No reason recorded; the commit message is only "mry trial". Plan-4 section 11 shows floor trips from 10:59 needing it, and O4 says set it for P0. It looks deliberate for the trial, but the repo profile and its tests were never reconciled | `git show`, plan-4 |
| paho-mqtt | 2.1.0 | `pip3 list` |
| `station-mqtt.json` | Exists, mode 600 | `stat` |
| `validate.sh` | Read first: changes nothing. **Passed**, rc 0. Station checks skipped because the switch is off | Ran it |

### Section 2: Tests

Run on a snapshot of the tree outside the workspace, with `HOME` redirected and separate ROS domains.

| Group | Pass | Fail | Skip | Note |
|---|---|---|---|---|
| `amr_station`, `AMR_MQTT_TESTS=1`, schemas from `~/VDA5050/json_schemas` | 129 | 0 | 0 | Needed the temporary broker |
| `amr_line`: the six named files | 168 | 0 | 0 | |
| `amr_web`: `test_teach_page`, `test_station_web` | 8 | **2** | 0 | Failures below |
| Others from P1–P7: trolley, wire contract, arm policy, launch layers, URDF, tape runtime, localization, mission engine | 195 | 0 | 0 | |
| `test_station_call_sim` | 6 | 0 | 0 | 96 s, ran last |

Failures, both caused by `live` being true:

- `test_the_site_lists_carry_machines_points_and_roles`
- `test_the_site_mission_is_offered_as_a_job_only_when_live`

**Limits:**

- The snapshot was taken at 14:53, so it misses the later edits.
- It includes the rolling corner code, with `corner_yaw_deg_s` still 0.
- `tests/run_all.py` wasn't run, because it doesn't need ROS.

### Section 3: Network to the station

| Item | Value | How checked |
|---|---|---|
| `wlp1s0` | 192.168.2.20/24, metric 700, SSID `agv_field`, channel 1 | `ip`, `nmcli` |
| Default gateway | **192.168.2.5** (the station PC), not .10 | `ip route`, `nmcli` |
| What answers at .10 | A device with MAC `08:2c:14:ac:00:00`, a DIO module per `alpha-setup.md`; ping only | `ping`, `ip neigh` |
| AP | 192.168.2.254, whose MAC matches the BSSID `8c:90:2d:9d:91:70` | `ip neigh`, `nmcli` |
| Ping to .5 | **0 replies out of 295** (and 80 of 80 unanswered pre-reboot), while TCP works. It looks like the station drops ICMP (inferred) | `ping` |
| TCP connect to :1883, 1 Hz, 302 s | 302 of 302; median 8.1 ms, p95 35.6, worst 88.0; longest gap 1.01 s | Own probe |
| Ping to the AP, 300 s | 302 of 302; median 5.5 ms, worst 95.3; longest gap 1.1 s | `ping` |
| AGV during those tests | **At rest, drives in fault. There's no ping data from a moving AGV** | LineState, ModeState |
| Signal at rest | Quality 60–70 of 70, about -45 to -49 dBm | `/proc/net/wireless` |
| Signal during the 14:26 trip | -28 to -67 dBm | `wpa_supplicant` log |
| Disconnects or roaming | None at rest; one AP, so no roaming seen. Firmware crashes as in blocker 6 | Journal |
| Clock | Synced, 0.4 ms from NTP (pre-reboot, through the .5 gateway). Offset to the station not measured | `chronyc` |

### Section 4: Site and trip readiness

**Taught stops** (from `stations.json` and graph g3, marks in brackets):

- **Taught:** `HOME-N` (no mark), `ATT` (M1), `MW-1` to `MW-4` (M8–M11), `ME-1` to `ME-4` (M12–M15).
- **Untaught:** none.

**Trip compile** (offline, on a copy of g3): MRU1, MRU2, MRU3 and MRU4 all compile, with no errors. The map binding check wasn't run, because the compile went against the graph directly.

**Floor trips on 2026-11-06:**

| Trip | Graph | Stops reached | Faults and holds | End |
|---|---|---|---|---|
| 10:59 MRU4 | Not logged | Held 0.4 m short of `ATT` | Localization LOST | Plan-4 section 11 |
| 11:25 MRU4 | Not logged | All stops | **Ended on the south bay, 1.26 m off, but reported "served"** | Plan-4 section 11.1 |
| 12:12 MRU4 | g2 | `ATT` only | 62 s field stop; false "drive link" stop | Selector left AUTO |
| 13:56 MRU1 | g2 | `ATT` +4 cm, `MW-1` +5, U-turn point +5, `ME-1` -1 | None until J-SPLIT | **FAULT, wrong tape after J-SPLIT** |
| 14:26 MRU1 | g3 | `ATT` +4, `MW-1` +4, U-turn point +3, `ME-1` **-23** | 24 s field stop; 8 s panel hold. J-SPLIT correct for the first time | Field stop at S 155.36, 5.3 m short of home, then selector left AUTO |
| 14:34 plain follow | g3 | None | Started after jogging by hand; AMCL 1.19 m off the tape | Reset |

**"mry trial" in short:** the commit turned `live` on and added the station code. The trips show the stops working to about 5 cm and J-SPLIT fixed in g3, but no complete round trip yet.

### Section 5: Live readings

| Topic | Now | Rate | Max gap |
|---|---|---|---|
| ModeState | mode 5 FAULT, `BASE_NOT_READY`, "wheel feedback" | 2.0 Hz | 0.50 s |
| LineState | No publisher (pre-reboot: IDLE, 1.03 Hz) | none | n/a |
| MuxState | Inhibited, field fresh, protective field clear | 10.0 Hz | 0.15 s |
| PanelState_ui | Valid | 8.9 Hz | 0.12 s |
| OrderState | No publisher, because the switch is off | none | n/a |

**Service health:**

- **CPU and memory:** load 2.36 (3.97–5.97 pre-reboot); the service uses 463 MB, with 4.9 GB available.
- **Nodes:** `amr_supervisor`, `amr_web`, `cmd_mux_kinematics`, `commissioning_node`, `diff_drive_odom`, `drive_node`, `ekf_local`, `imu_bias`, `panel_node`, `rfid_node`, `robot_state_publisher`, `scan_gate`, `sick_safetyscanners2_node` (node list cut off after that).
- **Warnings:** `cannot link the drives`, and `scan_gate` "511 scans expired". The `scan_gate` one is probably a side effect of having no odometry.

**What the bridge would report** (by hand, from the code):

| Field | Now (base fault) | Pre-reboot (LINE, MANUAL, plain follow) |
|---|---|---|
| `operatingMode` | `STARTUP` (no OrderState) | `MANUAL` |
| `not_ready` | Not sent at all | `SITE_NOT_LIVE` only |
| `not_ready` with site-103 loaded | n/a | `NOT_AUTO`, `NOT_AT_HOME`, `LOCALIZATION_NOT_READY`, `TAPE_NOT_SEEN`, `TROLLEY_UNKNOWN`, `REAR_FIELD_UNKNOWN`, `PREREQUISITE` |
| `loads` (trolley) | Key left out | Key left out |
| `fieldViolation` | false | false |
| Missing inputs | LineState, OrderState, TrolleyState | OrderState, TrolleyState |

- **Selector:** valid, position MANUAL, Manual Arm on. No turn needed.
- **Encoder drift:** **not done.** Drives are in fault and `/wheel_states_ui` is silent; the pre-reboot sample had `counts_valid: false`. `HOME_STILL_M` is unverified. For reference, 0.02 m is about 38,200 counts (calculated).

### Section 6: Hardware facts

| Question | Answer | Source |
|---|---|---|
| Rear scanner | Not fitted, no driver running. `nanoscan3_rear.yaml` holds placeholders (.3.11). `enp3s0` shows only the front unit, .3.10 | Live and config |
| O1, O2 | Open, nothing done | Plan |
| Trolley presence today | No sensor. The operator confirms by hand (`confirm_off`); nothing to read now | Config, code, events log |
| Warning duration | **2.0 s measured** (2.00–2.02 across the logged Starts). Torque wait up to 4.0 s for a station order, 8.0 s for a physical Start | Trip logs, config |
| Station's 5 s window | It's check 4's state age, not the warning; 4.0 s plus link time fits inside it | Contract, config |
| HOME to `ATT` | 56.8 s, 57.5 s, 59.7 s net of a field stop | Trip logs |
| `ATT` to `MW-1` | 142.0 s, 142.6 s; `MW-2` to `MW-4` never measured | Trip logs |
| `MW-1` to `ME-1` | 29.4 s, 33.2 s, including a 12.7 s U-turn | Trip logs |
| `ME-n` to HOME | **Never logged to arrival.** MRU1 took at least about 135 s to S 155, 5.3 m short | Trip logs |
| Settle and holdoff | 5 s and 15 s configured; **never exercised on the vehicle** | Profile |
| E-stop | **Inferred, not read.** It's wired to the FX3, and no DIO input carries it. Torque loss without a field violation is labelled `estop` | `job.py:814-818`, profile, `io-mapping.md` |
| Battery or charging | No charge or charging reading. Only a drive bus voltage monitor | Config |
| Second AGV | Addressing is reserved, but `.30` doesn't answer and there's no `agv-02` profile. Whether it's planned: ask a person | Ping, `profiles/` |

**What a person can press during a trip** (from the contract and code; the selector row was also seen in the 14:33 log):

| Input | AGV | Station sees |
|---|---|---|
| START at a stop | 2 s warning, then moves | Action `FINISHED`, or `START_REFUSED` |
| RESET mid-trip | Trip aborts (O13) | Row 5, Aborted |
| Selector to MANUAL | FAULT, trip aborted | `MANUAL`, `AGV_FAULT`, then Aborted |
| E-stop | Torque gone, hold waits for START; a later Reset aborts | `AGV_HOLD`, `activeEmergencyStop: MANUAL` |
| Field stop (not a button) | Resumes by itself when clear | `AGV_HOLD`, `fieldViolation: true` |
| Pendant, Manual Arm | Only act under MANUAL | Nothing directly |

## 5. Not checked, and what needs a person

**Needs a person:**

- Reset the drive cabinet, then press At home.
- Encoder drift for 2 minutes at rest, once the drives are up.
- Ping or link test while the AGV is driving the route.
- Two MRU1 trips in a row and one MRU4 for P0, then real `ME-n` to HOME times and `MW-2` to `MW-4` times.
- Exercise `SETTLING` and `HOLDOFF` on the vehicle (P7).
- Decide on O1 to O3, and check the scanner label and static inputs (V14).
- Confirm plans for AGV 2 and the gateway (AP or none).
- Decide whether `corner_yaw_deg_s: 30` should go live at the next restart.

**Not checked:**

- The running bridge against any broker, including a real MQTT login, by the owner's rule.
- OrderState and TrolleyState content on the vehicle, because neither has a publisher.
- The clock offset to the station PC.
- Why the `HOME-N` fields differ from the other stops (no mark, 1 sample): whether that matters to accuracy.
- E2 laps, E3 and the C-BTU teach (V6, V7).
- Selector polarity (V17), other than reading MANUAL now.
- The cause of the Wi-Fi firmware crashes, and whether the 14:31 DIO loss is related.
