# Station call plan: machine calls from the station over MQTT (AGV side)

Status: software built 2026-11-06, uncommitted, `station.enabled` false. See "As built" below. Paths and
line numbers in the rest of this file are for `gvievo-01` branch `gvievo-main` at `c41afb3`. I opened the files cited with a line number. Where I
rely on the earlier code map instead, the text says "second-hand" or "not opened". With the switch in
P1 off, the job, node and web behave as the P0 baseline. P0's two settings (`trip_calls` 1 and
`tape_loc.live` true) and any rear hardware are not covered by that promise (section 4.2).

The owner's decisions of 2026-11-05 are final. This plan designs to them and does not re-open them.

References: the interface contract, embedded word for word at the end ("contract section N" means
that text); `manuals/site-layout-103.md`; `manuals/tracked-plan-4-position-engine.md`;
`manuals/tape-localization-runbook.md`; `amr_ws/RUNBOOK.md`; the VDA5050 spec and JSON schemas in
the station repo (`gvievo-sta/VDA5050/`, not in this repo).

Three rules for whoever implements this:

- Do not call this system VDA5050 compliant. It is a subset (contract section 10).
- Do not commit or push unless the owner asks.
- Write the tests first, in the phase that names them, and run them failing before the code exists.

## As built (2026-11-06)

The owner accepted the safety aspect and the automatic departure on 2026-11-06, and with it the
recommended defaults of section 0. That is acceptance of this design. It is not the P9 record: O1, O2 and
the named approval in 15.2 stay open until the rear scanner exists and is verified.

| Phase | State |
|---|---|
| P0 | Repo edits done (`trip_calls` 1, its two tests, documents). The floor proof is owed, and `tape_loc.live` stays false in the repo profile (O4). **`HOME-N` is not taught on this vehicle** (V2, 2026-11-06), so no trip compiles yet |
| P1 to P6 | Built, tests pass |
| P7 | Sim tests pass against a real loopback broker. Vehicle steps 1 to 11 owed |
| P8, P9 | Owner, safety engineer, witnessed. Nothing done |

Where the build differs from the text below, on purpose:

| Point | Text says | Built | Why |
|---|---|---|---|
| Arrival baseline for `_home_moved` | `_arrive_home` saves `i.counts` | Saved on the first tick with the wheels at rest after arrival; `NOT_AT_HOME` until then | Wheels can still be slowing when the commanded speed reaches 0, which would have cleared the baseline on every trip |
| Active monitoring case (V18) | Not verified | The driver has `OutputPaths.active_monitoring_case`. New key `rear.no_trolley_case` (-1 = not set, 0 refused: the driver reports 0 for no data). `EXPECTED_CHECKS` is 887, not 886 | The case gate can rest on data. The driver's topics are relative, so namespace `rear` works (source read; confirm on the vehicle) |
| Frozen scans (V18) | A repeated scan counter | The bytes of `ranges` stand in for it. The real counter is only on `raw_data`, a big message at the scan rate | Reads UNKNOWN, the safe side. Confirm at P8 that an open floor does not repeat |
| Invalid beams | Not defined | NaN or below `range_min` is invalid. `inf` or above `range_max` is a valid "nothing there" | Otherwise an open floor reads as a blind scanner. Confirm against the real unit at P8 |
| `OrderState` | The table in 4.4 | Adds `cancelled_text` | The contract's `DEPARTURE_CANCELLED` example carries a description |
| `amr_station` | Four modules | Adds `bridge_core.py` | The bridge's decisions stay testable with the node thin |
| P7 sim test | "real job" under the bridge | A real `FollowJob` on the test plant, plus one test with the real `line_follow_node` on no site mission | A supervisor sim with a taught graph does not exist. A real departure through the real node is first seen at G3 |
| D14 | Remove the citation of `CLAUDE.md` | Kept | `CLAUDE.md` is in this repo. Section 2's "stale text" note on it is wrong |

The manual's parallel copies (`operation-manual-doc.md`, `.docx`) and `operation-manual-context.md` are not
changed: the owner decides when a revision goes to TÜV SÜD. 10.10 of `operation-manual.md` is marked as not
in force until O3.

## 0. Open decisions for the owner

Each has a default, so software work can go on. O1 to O3 block the real automatic departure (P9),
and nothing else.

| # | Decision | Recommended default | Blocks |
|---|---|---|---|
| O1 | **Rear safety field while towing.** The hitched trolley sits in the rear scanner's view. How the field behaves then is a safety hardware decision, not a software one | Decide with the safety engineer before buying anything. Have them assess a second monitoring case for towing. Check first whether the fitted scanner variant has static inputs to select one (not confirmed; see P8). Case selection must never come from the non-safety trolley detection. The rear case gate in 3.3 applies whatever is chosen | P8, P9 |
| O2 | **Rear scanner in the safety chain.** All 8 FX3 safe inputs are used (`documentation/electrical/01-schematic/io-mapping.md:72-79`). The drawings say no OSSD inputs are reserved (`documentation/electrical/01-schematic-iec/iec-page-41.html:58-60`) | Add inputs by expansion, and model the chain in SISTEMA first. The brief warns of limited PFHd headroom, using placeholder values (`code_ce/sick_lidar/safety-system-brief.md:210-218`) | P8, P9 |
| O3 | **Risk assessment of automatic departure**, including the 5 s `SETTLING` and each of its restart events, the 15 s `HOLDOFF`, the residuals in 3.2 and the warning text in section 18. The existing rule "agree who presses START" no longer covers leaving home. **Prerequisite:** the rear scanner chain verification and SISTEMA update (O2, P8 step 1) | Named sign-off before the first real automatic departure. Keep 5 s and 15 s until then | P9 |
| O4 | **`tape_loc.live: true`.** It is `false` in the repo profile (`profiles/agv-01.json:214`), which means no trip can run. `amr_web/test/test_teach_page.py:36` pins it `false` | Set it on the vehicle for P0. Change the repo profile and that test together once P0 passes | P0 |
| O5 | **First machine to prove by hand** | MRU1 (first on the line, mid-line U-turn), twice in a row. Then MRU4 (tape-end U-turn) | P0 |
| O6 | **Run → Calls while the switch is on** | Keep it. Local calls and station orders exclude each other (section 4.3) | P2 |
| O7 | **Sensor check before the U-turn pivot.** Added by this plan: the release confirmation it replaces was the pivot's guard (`amr_line/trip.py:151-156`). Unknown or present means hold, no pivot | On | P2 |
| O8 | **How a rear OSSD stop is labelled.** `job._safety_cause` (`job.py:721-725`) calls a torque loss with the front field clear `estop`. A rear stop would therefore read as an E-stop and wait for START | Keep this. It never resumes by itself, and `hold_policy.AUTO_CAUSES` stays `("field",)` | P8 |
| O9 | **Trolley still standing behind the AGV after unhitching at MW-n.** A lidar cannot tell hitched from standing close. START is refused until the trolley is out of the detection zone | Accept this. It is the safe side. The operator moves the trolley clear, then presses START | P2 |
| O10 | **What the lidar does not cover.** No interlock at BTU swap stops (the decisions name none). Trolley loss while driving is reported in `loads` but stops nothing | Accept for now | P2 |
| O11 | **At home needs presence.** `/api/line/at_home` is open to anyone on the network (`server.py:495-498`) and seeds the at-home check that automatic departure relies on | With the switch on, refuse At home unless the selector is MANUAL (P3). Added by this plan | P3 |
| O12 | **paho-mqtt install.** The vehicle may have no internet | Pin `paho-mqtt==2.1.0` and install from a copied wheel (P5). The version comes from general knowledge, so verify it | P5 |
| O13 | **Reset after an E-stop on a station trip.** By current code a Reset outside IDLE aborts the trip (`job.py:799-802`, `test_reset_mid_trip_aborts_it`). Operation manual 10.7 says to release, press RESET, then START, "then the vehicle continues". So every E-stop on a station trip ends Aborted, with recovery by hand | Keep the current code. Correct manual 10.7 (section 18) | P6 |

Contract section 11 stays flagged as written. Items 2, 3, 5, 8, 9 and 10 touch the AGV. Items 1, 4, 6,
7 and 11 are for the station plan.

## 1. Scope

**In scope, on the AGV:**

- `trip_calls` 1 in the mission.
- One new way to leave home: an accepted station order.
- A rear lidar: scanner driver instance, frames, trolley detection, interlocks.
- An MQTT bridge node that speaks the contract.
- A feature switch, new alarms, documents and tests.

**Out of scope:**

| Item | Where it belongs |
|---|---|
| Buttons, trolley types, LEDs, station screen, call list, first DIO write (a named approval under `PROTOCOL.md`) | Station plan, `gvievo-sta` |
| Mosquitto install and configuration on the station PC | Station plan. Contract section 1 gives the settings |
| Scanner safety configuration in Safety Designer, FX3 logic, wiring | Owner and safety engineer (O1, O2). Humans only |
| Traffic control, factsheet, `startPause`/`stopPause` | Not built. Section 20 keeps traffic control possible |
| Any claim of compliance with a standard or with VDA5050 | Not made here |

## 2. What the code does today

These facts shape the plan. Check them again before relying on them.

| Fact | Where | Consequence |
|---|---|---|
| The trip engine is off in the repo profile, so `job.site` and `job.calls` stay `None` and every call is refused | `profiles/agv-01.json:214`, `line_follow_node.py:345-348`, `job.py:338-339` | P0 must turn it on before anything can be proved |
| `FollowJob._start` has one caller, at `tick` in IDLE/DONE, on a physical Start edge | `job.py:805-807` | The new entry sits right beside it |
| `_begin_premove` has three callers | `job.py:530`, `:935`, `:974` | The new one makes four. A test pins the list |
| `_premove_tick` re-checks every tick. A violated front field cancels at once, other failures after the debounce. It goes when `hold_policy.premove_ready` is true | `job.py:582-613` | The new entry inherits this, with the horn and power |
| The horn and drive power follow `LineState.state`, not the edge. The mux and arm policy never read `start_edge` | `amr_base/arm_policy.py:54-71`; a grep of `start_edge` finds only panel, job, commissioning and executor code | Nothing below the job needs changing |
| The node runs single-threaded, so a service callback and `tick` cannot interleave | `line_follow_node.py:848-849`, `amr_base/lean_node.py` `run` | A plain attribute works as the latch |
| A cancelled "start" warning restores calls to the queue. `Trip.called` is always filled, so a station trip would land there too | `job.py:575-577`, `trip.py:84` | The order path must take its own branch |
| The selector leaving AUTO during ARMED goes to FAULT through `_taken_over`, not through `_premove_cancel`. A later tick aborts the trip | `job.py:825-829`, `:813-816` | See 4.5 R1 |
| `_trip_abort` does not reset `Payload`. Only `_arrive_home` does | `job.py:420-425`, `:983` | Hand trips keep this. The lidar replaces it when the switch is on |
| A press refused at a station changes only `reason`, and no event is raised | `job.py:972-976` | `START_REFUSED` needs new reporting |
| `LineState` publishes on state change and at 1 Hz, so `v_mps` can be up to 1 s old | `line_follow_node.py:305`, `:720-727`, `:797-800` | `driving` cannot come from it (4.5 R4) |
| Job state is not saved. A new line layer process has no trip or calls, and the locator stays off until At home | `tape_runtime.py:134-135`, `:184-192` | An order is lost on restart. Contract section 9 expects this |
| No code exists for MQTT, a rear lidar, a trolley sensor or automatic departure | Grep of `.py`, `.json`, `.msg` | All new |
| `paho` is not a dependency. `pyproject.toml` pins nothing, on purpose | `alpha-setup.md:636-662` | P5 |

**Stale text found:**

- `line_follow_node.py:13-15` still says tape localization is shadow only.
- D14 cites a `CLAUDE.md` that is not in this repo.
- `alpha-setup.md:174,451,456` lists the Wi-Fi gateway as `192.168.2.10`, which is now DIO module 1.

## 3. The one exception to physical START

This section is the reviewable change record. It should be read and signed off as one item (O3).

### 3.1 The change

**Today.** Every autonomous move needs AUTO and a fresh physical Start (`README.md:43-47`).

**After, with `station.enabled: true` only.** One move needs no Start: leaving home for ATT, once,
when a station order has been accepted.

| Stays exactly as it is, switch on or off |
|---|
| Every stop other than the start of an order waits for a physical START: ATT, MW-n, ME-n |
| Every hold that waits for START still waits for START. Only `field` resumes by itself |
| No web page can start the vehicle directly. `/api/line/trip` still takes no start action. With an order waiting, though, a web action can remove a block on it: Clear, local call cancel or mission selection. With the switch on, each of those restarts the full 5 s `SETTLING`, and Clear is refused in FAULT |
| Nothing sent over the network can resume, continue or pause a run. `stopPause`, `startPause` and `trigger` are not implemented |
| The 2 s warning horn and every scanner stop apply to the automatic departure |
| This software does not change FX3, STO, E-stop, selector or Reset. The rear scanner hardware (O1, O2) does change the chain, and needs its own verification and SISTEMA update |
| Nothing in this repo is in the safety path (`README.md:59-64`) |

### 3.2 The safety argument

The software adds a *reason to move*. It adds no protection. Protection stays with the scanner
OSSD, FX3 and STO chain. This software does not change that chain. The rear scanner hardware does,
and its verification is a named prerequisite of O3. The departure logic is not safety rated and must
not be presented as if it were.

What leaving home loses is a person's look around (`documentation/operation-manual/operation-manual.md:745`,
"Check the path is clear and nobody is at the hitch"). Nothing fully replaces that look. The measures
below reduce the risk, and the residual column is what the risk assessment (O3) has to accept or
answer.

| Hazard | Measures | Residual, for O3 |
|---|---|---|
| Someone at the hitch or behind the AGV when a call arrives | Rear safety field must be clear. No trolley detected. `SETTLING` 5 s. Horn 2 s | The rear field does not exist yet and its towing behaviour is open (O1). A person beside the vehicle may be outside every field |
| Someone in front | Front field proven clear before and during the warning. The field going clear restarts `SETTLING`. Violated cancels at once (`job.py:599`). OSSD stop in hardware | Scanner coverage only |
| A towing monitoring case left selected after unhitching, so the rear field reads clear with a person at the hitch | Rear case gate (3.3). Case selection never comes from the trolley detection. Unknown case gives `REAR_FIELD_UNKNOWN` | If the driver does not report the case, the gate rests on the safety engineer's hardware proof |
| Someone unhitching the full trolley at HOME, with a call waiting | Departure needs the trolley out of the zone, then 5 s, then 2 s of horn. That is at least 7 s after the trolley leaves the zone | The person may still be close. Hence the warning text in section 18 and O3 |
| Someone working on the vehicle at HOME, selector left in AUTO | Procedure: MANUAL at HOME to keep it still. Selector leaving AUTO stops the warning | Depends on training. Section 18 states it as a warning |
| An old or replayed order moves the vehicle later | QoS 0, no retain, retain-flag discard, `seenStateHeaderId` window, one-tick latch, single use (section 9.3, P2) | None found in design. The vehicle test is P9 |
| A forged order | Broker password and ACL, no vehicle listener, WPA on Wi-Fi | Plain MQTT over a shared PSK network (section 19) |
| A bug fires the departure in the wrong place | At-home check, IDLE/DONE only, pinned single entry (section 16). `LOCALIZATION_NOT_READY` until a fresh scan match. `TAPE_NOT_SEEN` without tape under the sensor | At home can be pressed in error, so it is gated on MANUAL (O11) |
| The AGV pivoted or moved at HOME, then left in AUTO, so it departs the wrong way | Any wheel movement after At home or after a trip's arrival gives `NOT_AT_HOME` until a person looking at the vehicle presses At home again | This is a procedural check. **Heading is not measured.** A person can press At home with the AGV facing the wrong way |
| Trolley state wrong or unknown | Unknown refuses. Stale becomes unknown. `stale_s` has a ceiling tied to `FRESH_FIELD_S` | Trolley detection is not personnel protection. A person in the zone reads as a trolley. A scanner or driver that keeps publishing frozen content is caught only if the driver exposes a scan counter (11.3, not verified) |
| An E-stop pressed at HOME with a call waiting. `NOT_READY` stays empty, because the job cannot see the chain and standby torque-off looks the same | One horn cycle: the order is accepted, the warning is cancelled at `order_torque_wait_s`, and `TORQUE_TIMEOUT` is latched until a physical Reset edge. The station stops after 3 requeues (contract section 11) | One horn cycle around someone who pressed the E-stop to work on the vehicle |
| An E-stop released while an order is still ARMED. RESET closes the FX3 in hardware, but `panel_io` can suppress the edge as suspect (`test_a_start_the_scan_after_another_change_is_ignored_and_a_reset_too`) | `order_torque_wait_s` cancels the warning if torque has not arrived, so a later release cannot move a stale order. A Reset edge the job does see ends the warning | **For the safety engineer:** a release and reset inside `order_torque_wait_s` of acceptance can still lead to a departure with no `SETTLING`. The value must be measured on the vehicle at P8 |
| The horn repeating | `HOLDOFF` 15 s after a cancelled warning. `SETTLING` 5 s after any warning ended by a cancel or `cancelOrder`. `TORQUE_TIMEOUT` latch. Station requeue limit | A second attempt after `cancelOrder` can sound the horn again 5 s later, with no `HOLDOFF` (4.5 R8) |

### 3.3 Conditions for the automatic departure

All must hold. Section 9 of this plan gives the code. Refused means nothing is stored.

| Condition | How |
|---|---|
| `station.enabled` true | Otherwise no service, no bridge, no code path reachable |
| An order passed the bridge checks 0 to 4 | `amr_station/vda_order.py` |
| State is IDLE or DONE, with no trip and no local call | `FollowJob._order_gate` |
| AUTO on a valid panel, with LEASE_LINE | Same checks as a physical Start |
| At HOME by the existing check, with no wheel movement since At home or since a trip's arrival | `job._site_at_home`, `FollowJob._home_moved` |
| Route compiles | `compile_trip` |
| Scan match confirmed, tape under the sensor, no fault, no latched `TORQUE_TIMEOUT` | `FollowJob._order_not_ready` |
| No trolley, rear field clear with the rear case gate met, `SETTLING` and `HOLDOFF` elapsed | `FollowJob._order_not_ready` |
| Through ARMED: horn, power, torque check, torque inside `order_torque_wait_s` | `_begin_premove(i, "start")` |

**Rear case gate (named safety gate for P8 and P9).** `rear_clear` counts only when the no-trolley
monitoring case is proven active. Reading one field index does not prove it. If a towing case with a
reduced or muted field stayed selected after unhitching, the field would read clear with a person at
the hitch.

- Case selection must never come from the trolley detection in 11.3, which is not safety rated and reads a person as a trolley.
- If the driver exposes the active case, `trolley_node` reports it in `TrolleyState.rear_case`. Not verified: the driver is not in this repo (V18).
- If it does not, the safety engineer proves in hardware that no towing case can stay selected with no trolley, and records it. Only then is `rear.case_proven` set true on the vehicle.
- Case unknown and not proven gives `REAR_FIELD_UNKNOWN`, so every order and local trip is refused.
- Tested in hardware group E as "trolley gone, towing case still selected", with a stand-in target, never a person.

### 3.4 Invariant text that changes

Reword each of these in P6, in the same change set as the code. The new wording must say the
exception exists only with the switch on.

| Where | Today | Change |
|---|---|---|
| `README.md:43-47` | "every autonomous start ... needs the selector in AUTO and a fresh physical Start press" | State the exception. "No web page can start the vehicle" stays true and stays |
| `amr_ws/RUNBOOK.md:7`, `:16`, `:106`, `:131` | LINE moves only on Start | Add the exception, and the `station.enabled` line |
| `manuals/site-layout-103.md` D14 (`:36`), `:81`, `:154` | Leaving home needs a physical Start | Section 18 |
| `manuals/tape-localization-runbook.md:25`, section 4.2 | "Every autonomous move is AUTO + a physical Start" | Add the exception |
| `manuals/rfid-tag-table.md:82` | "No web page starts the vehicle" | True. No change, but check it |
| `amr_line/job.py:15-23`, `:507-513`, `:61-62` | Docstrings on moves after Start, and the `payload` hold | Add the order path |
| `amr_line/line_follow_node.py:13-15`, `:17-24`, `:274-275` | "follows only on a fresh physical Start edge"; the stale shadow text | Fix both |
| `amr_line/site_run.py:27-29` | "the run is moving on AUTO + the physical Start" | Add "or an accepted station order at HOME" |
| `amr_line/trip.py:3-5`, `:9-11`, `:17-18` | Calls from the display, no sensor, "may it leave the bay" | Add the lidar and the station order |
| `agv_core/mission.py:550` | `trip_calls` D3/D4/D18 | New decision reference |
| `amr_web/amr_web/server.py:477-479`, `adapter.py:889-891` | "leaves HOME only on AUTO + the physical Start" | Still true of that API. Reword so it does not claim more |
| `amr_web/amr_web/templates/run.html:18-22`, `:38`, `:43`, `:162` | Warn box "Motion starts only from the physical panel"; confirmation text | Text depends on the switch (P3) |
| `amr_bringup/mode_fsm.py:136-138`, `supervisor_node.py:579-581` | Entering a layer moves nothing | Still true. Entering a layer does not create an order. No change |
| `amr_base/panel_node.py:11-14` (not opened) | No edge faking | Still true, and this plan keeps it. No change |

**Tests that pin the rule.** With the switch off, which is the default, every existing test must pass,
and **no existing test body changes except those listed in section 16**. The list below is the part
that pins this rule most directly, not the limit of the rule:

| File | Tests |
|---|---|
| `amr_line/test/test_line_authority.py` | `test_an_estop_hold_waits_for_a_human`, `test_device_holds_wait_for_a_person`, `test_the_warning_runs_its_full_time_and_waits_for_torque`, `test_a_field_trip_during_the_warning_cancels_at_once`, `test_reset_and_the_selector_end_the_warning`, `test_a_cancelled_resume_returns_to_its_hold`, `test_a_start_from_idle_runs`, `test_start_refuses_without_each_prerequisite`, `test_a_refused_start_does_not_run_later`, `test_idle_shows_live_readiness_and_never_enters_armed`, `test_a_start_in_fault_is_ignored_until_reset`, `test_a_start_under_manual_is_refused_not_faulted`, `test_reset_wins_over_a_start_in_the_same_tick`, `test_idle_asks_for_no_power_and_a_start_does_not_need_torque`, `test_no_torque_within_the_timeout_cancels_the_start`, `test_a_hold_waiting_for_start_drops_power_and_resumes_through_the_warning` |
| `amr_line/test/test_site_run.py` | `test_a_trip_start_is_refused_until_everything_is_in_place`, `test_an_untaught_trip_is_refused_and_its_calls_wait_again`, `test_a_one_call_trip_stops_turns_mid_line_and_ends_at_home`, `test_a_release_not_recorded_holds_payload_at_the_u_turn_point`, `test_reset_mid_trip_aborts_it`, `test_doubt_before_a_stop_holds_before_it_and_start_rechecks` |
| `amr_line/test/test_marker_run.py`, `test_control.py`; `amr_bringup/test/test_unified_sim.py`; `amr_mission/test/test_auto_resume.py`, `test_run_fsm.py` | The whole file. The last two share `hold_policy`, which P2 edits |
| `amr_line/test/test_mission_engine.py` | `test_a_full_job_home_to_mru2_and_back` |
| `amr_line/test/test_guided_run.py` | `test_a_forced_u_turn_turns_at_the_next_tape_end_without_a_strip`, `test_a_run_that_ended_at_the_tape_end_u_turns_on_the_next_start`, `test_a_run_that_ended_after_the_u_turn_continues_home_on_start` |
| `amr_web/test/test_operator_ux.py` | `test_run_has_no_arm_button_and_no_arm_api`, `test_line_apis_reach_the_layer_and_never_move_anything` |
| `amr_web/test/test_teach_page.py` | `test_calls_and_confirmations_are_open_to_the_operator_and_checked` |
| `amr_web/test/test_server.py` | `test_state_and_page_addresses` |
| `amr_base/test/test_panel_io.py` | `test_first_image_is_a_baseline_with_no_edges_even_if_start_is_held`, `test_edges_fire_once_and_need_debounce`, `test_comms_loss_invalidates_and_reconnect_rebaselines_without_an_edge`, `test_a_start_with_manual_arm_dropping_in_the_same_scan_is_ignored`, `test_a_start_the_scan_after_another_change_is_ignored_and_a_reset_too`, `test_a_repeated_image_does_not_advance_debounce_or_repeat_an_edge` |
| `amr_base/test/test_gating_line.py` | `test_the_selector_must_be_in_auto`, `test_a_stale_panel_refuses_everything`, `test_drives_must_be_operational`, `test_an_inhibited_lease_beats_the_line_branch` |

No test reads the invariant text in `README.md` or the manuals. `tests/test_alarms.py:77-87` pins
only the generated alarm block in RUNBOOK section 4. So the wording change above is a review item,
not something a test will catch.

**Gap.** No test today asserts that a waiting call with no Start edge stays IDLE. P1 adds it.

## 4. Design

### 4.1 Parts

```text
station PC                 AGV (ROS on loopback only)
 Mosquitto  <-- Wi-Fi -->  station_bridge_node (new package amr_station; base launch; only if enabled)
 192.168.2.5:1883            | /amr/line/order (LineTeach service)     ^ /amr/line/order_state (OrderState)
                             v                                         |
                           line_follow_node --> FollowJob.tick --> _order_start --> ARMED --> RUNNING
                             ^ /amr/rear/trolley (TrolleyState)
                           trolley_node <-- /rear/scan, /rear/output_paths <-- rear scanner driver
```

| Part | Motion authority |
|---|---|
| `FollowJob` (`amr_line/job.py`, pure) | The only decider. The node stays a marshaller, as `line_follow_node.py:26-31` requires |
| `amr_line/order.py` (new, pure) | None. Records one order's progress and the settle timers |
| `station_bridge_node` | None except the one service action `depart`. No lease, no command topic, no panel input |
| `trolley_node` | None. Reports a state |

The bridge sits in the base launch, not the line layer. It must survive layer changes and report
`STARTUP` through them.

### 4.2 The switch

`station.enabled` in the profile, default `false`.

| Thing | `false` (the P0 baseline) | `true` |
|---|---|---|
| `station_bridge_node`, MQTT client | Not launched, no import of paho | Launched in base, respawning |
| `/amr/line/order`, `/amr/line/order_state`, `/amr/rear/trolley` subscription | Not created. New messages are not imported | Created |
| `FollowJob(calling=...)` | `False`. `order_request` refuses and latches nothing. `Inputs.trolley` is never read | `True` |
| Leaving home on physical Start | Needs `Payload.may_leave()` (`job.py:399`) | Needs no trolley and rear field clear |
| `confirm_released`, `confirm_off` | Work as today | Refused: "the rear lidar decides" |
| Pivot guard | `Trip.may_pivot()` only | Also trolley absent (O7) |
| START at ATT, MW-n, ME-n | As today | Interlocked |
| At home | As today | Needs selector MANUAL (O11) |
| Clear in FAULT | As today | Refused: "press Reset on the panel" |
| Run page | As today | Shows trolley state and the order, and swaps the warn box |

`rear.source` and the FX3 do not follow the switch:

| Thing | `station.enabled` false | Why it differs from S3 |
|---|---|---|
| `rear.source: "scanner"` | The rear driver and `trolley_node` still launch, can raise `REAR_SCANNER_SILENT`, and add N97 CPU load | Set at P8, not by the switch |
| Rear OSSDs in the FX3 | A rear field stop still happens on hand trips, reading as `estop` (O8) | Hardware |

**Baseline.** Hand-trip results compared with hardware S3 are valid until group E. Differences caused
by rear hardware are recorded separately, and the baseline is taken again after E.

**Rollback.** P0: set `trip_calls` back in the mission and `tape_loc.live` false in the profile, then
restart, and undo the two P0 test edits if the repo was changed. Rear hardware: set `rear.source: "none"`
and `rear_lidar` false, then restart. Taking rear OSSDs back out of the FX3 is the safety engineer's
job, with its own verification.

`station.enabled: true` is refused unless `tape_loc.live` is true.

Rear lidar not fitted, switch on: trolley state is unknown, so every order is refused **and** every
hand trip is refused. There is no bypass on the vehicle (contract section 7). To run hand trips
before the lidar exists, turn the switch off.

### 4.3 Run → Calls and manual operation

| Situation | Behaviour |
|---|---|
| Switch off | As the P0 baseline, including the second-call quirk (`CallQueue.call` looks at `pending` only) |
| Switch on, local call tapped, no order active | Accepted. Forms a trip, leaves on physical START. Lidar interlocks apply. Orders are refused with `OTHER_ORDER_ACTIVE`, reason `LOCAL_TRIP`, and `NOT_READY` shows `LOCAL_TRIP` until the local call or trip ends |
| Switch on, local call tapped, order active | Refused: "a station order is being served" |
| BTU | Only from Run → Calls (contract section 10). Physical START at HOME, then ATT interlock. No interlock at swap stops (O10) |
| Physical START at HOME, no local call, station idle | Refused as today: "no trip formed". A press never starts a station order |
| Physical START in the same tick as an order arriving | The press is handled and the order is refused. The station resends. A person at the panel wins |
| Clear on the web during an order | Allowed, except in FAULT. It stops the run and aborts the order (`TRIP_ABORTED`), as Clear does for any trip, and restarts `SETTLING` |
| Clear on the web in FAULT, switch on | Refused: "press Reset on the panel". Today `clear()` goes from any state to IDLE with no Reset (`job.py:657-675`), which would release a waiting order with only the 2 s horn. Off, as today |
| Local call cancelled on Run → Calls, switch on | As today, and restarts `SETTLING`, because it can clear `LOCAL_TRIP` |
| Selector to MANUAL during an order | FAULT and abort, as for any trip (`job.py:825-829`). The call closes aborted. Jogging works as today after Reset. Any wheel movement then needs At home again before an order |
| E-stop during an order | Moving stages: hold `estop`, `AGV_HOLD`, call state unchanged. Parked at ATT, MW-n or ME-n: the hold stays `station`, so no `AGV_HOLD`. In the warning: no hold, the warning is cancelled at `order_torque_wait_s`, `DEPARTURE_CANCELLED`. RESET aborts the trip on every active stage (O13) |
| Mission changed on the Run page | Only in IDLE/DONE, as today. `NOT_READY` shows `SITE_NOT_LIVE` while another mission is the job. Selecting a mission restarts `SETTLING` |
| At home | Needs MANUAL with the switch on. After a restart: MANUAL, At home, confirm the scans align, AUTO, then 5 s of `SETTLING`. Press it looking at the vehicle: heading is not measured |

### 4.4 New ROS interfaces

All are additive. `LineState.msg` does not change, so a switched-off vehicle publishes byte-identical
line state.

**`/amr/line/order`**, type `LineTeach` (the `/amr/line/trip` pattern, `line_follow_node.py:276`):

| action | arg | Effect |
|---|---|---|
| `depart` | `<orderId> <machine>` | Latches one request. The reply says only "taken" or "calling is off". The result appears in `OrderState` |
| `cancel` | `<orderId> <actionId>` | Latches one cancel. Result in `OrderState` |

**`amr_interfaces/msg/TrolleyState.msg`**, on `/amr/rear/trolley`:

```text
uint8 UNKNOWN=0
uint8 ABSENT=1
uint8 PRESENT=2
uint8 FIELD_UNKNOWN=0
uint8 FIELD_CLEAR=1
uint8 FIELD_VIOLATED=2
uint8 CASE_UNKNOWN=0
uint8 CASE_NO_TROLLEY=1
uint8 CASE_OTHER=2
std_msgs/Header header
uint8 state
uint8 rear_field       # FIELD_CLEAR only with the rear case gate met (3.3)
uint8 rear_case        # CASE_UNKNOWN if the driver does not report it
uint16 roi_points      # beams inside the zone, last scan
string detail          # why UNKNOWN, for the screen
```

Add `wire.TROLLEY_NAMES` to `amr_base/wire.py`. `TrolleyState` has three constant groups, so give it
its own pinned test next to `test_each_table_is_exactly_the_msg_constants`.

**`amr_interfaces/msg/OrderState.msg`**, on `/amr/line/order_state`, latched, on change and at 1 Hz:

| Field | Meaning |
|---|---|
| `header`, `generation` | Consumers drop other generations, as for `LineState` |
| `order_id`, `machine` | Current or last accepted order. `""` in a new process |
| `active`, `departed` | Order running; has left HOME |
| `att_status`, `mw_status`, `me_status` | `WAITING`, `RUNNING`, `FINISHED`, `FAILED`, or `""` |
| `last_node_id`, `last_node_seq` | Contract section 5 |
| `driving` | Wheel command non-zero this tick, RUNNING only |
| `trolley`, `rear_field` | As fresh on this tick, `UNKNOWN` when stale |
| `not_ready` (string array) | Contract section 8 reasons, in that table's order |
| `refusal_seq`, `refusal_type`, `refusal_order_id`, `refusal_reason` | Latest job-level refusal |
| `cancelled_reason`, `aborted_reason`, `aborted_text` | `DEPARTURE_CANCELLED` and `TRIP_ABORTED` content |
| `start_refused_node`, `start_refused_reason` | `START_REFUSED` content, `""` when none |
| `cancel_seq`, `cancel_action_id`, `cancel_status`, `cancel_error` | Latest `cancelOrder` result |

### 4.5 Readings of the contract that the code forces

The contract is embedded unchanged. These are the places where code and contract needed a choice.

| # | Point | Reading |
|---|---|---|
| R1 | The selector leaving AUTO, or a Reset or Clear, during the warning. The code goes through `_taken_over`/`reset`/`clear`, not `_premove_cancel`. The contract says a warning that stops ends with `DEPARTURE_CANCELLED` | `_trip_abort` checks `order.departed`. Not departed gives `DEPARTURE_CANCELLED`, `HOLDOFF` and a `SETTLING` restart. Departed gives `TRIP_ABORTED`. The FAULT itself stays and needs Reset: with the switch on, Clear is refused in FAULT (4.3) |
| R2 | The "Aborted (selector left AUTO)" example in contract 6.2 has no `AGV_FAULT` and no `FAULT` reason, yet the job will be in FAULT | The real message follows contract 6.3 and carries both. Row 5 of the mapping table reads the same either way. The contract-example test adds them for this one example, with a comment |
| R3 | The bridge restarts, or the line layer is down. Publishing `orderId: ""` would look like row 2 (Aborted) to the station | Until a fresh `OrderState` arrives, and whenever it is older than 3 s, `operatingMode` is `STARTUP`. The station ignores those messages. A new process then publishes `orderId: ""`, which correctly gives row 2 |
| R4 | `driving` must update within 200 ms, and `LineState` can be 1 s old | `driving` comes from `OrderState`, set each tick |
| R5 | `fieldViolation` with the rear scanner absent | True, as the contract's example shows. It covers front and rear. Display only |
| R6 | Check 6 is written on `operatingMode`, which the job cannot see | The job checks panel valid, AUTO and LEASE_LINE. The supervisor grants that lease only in LINE (`supervisor_node.py:314-329`, `_allowed`). The bridge's `operatingMode` uses the same facts plus `ModeState` |
| R7 | The orderId is opaque to the AGV | The bridge finds the machine from `MW-n` and `ME-n` in the site mission. It never parses the id |
| R8 | `cancelOrder` during the warning | No `HOLDOFF` and no `DEPARTURE_CANCELLED`, as the contract's "Cancelled" example shows. `SETTLING` restarts, as the same example shows, so the next queued call waits at least 5 s |

## 5. Phases and order

The manual proof comes first. Each later phase leaves the job, node and web at the P0 baseline while
the switch is off.

| Phase | What | Who or what it needs | Vehicle affected |
|---|---|---|---|
| P0 | One complete trip by hand; `trip_calls` 1 | **Human and real AGV** | Yes, as an owner-approved step |
| P1 | The switch, baselines, negative pins | Dev box | No |
| P2 | Job: order entry and interlocks | Dev box | No (code present, switch off) |
| P3 | Node, messages, web, fake trolley | Dev box | No |
| P4 | Trolley detection and rear scanner software | Dev box | No |
| P5 | MQTT bridge | Dev box with Mosquitto | No |
| P6 | Alarms and documents | Dev box, owner review | No |
| P7 | Sim end to end; deploy off; link test with orders refused | **Human and real AGV**, station PC | Yes, switch on only for the test, lidar absent |
| P8 | Rear scanner fitted and calibrated | **Owner (O1, O2), human, real AGV** | Yes |
| P9 | First real automatic departure | **Named approval (O3), witnessed** | Yes |

**Order on real hardware.** Code may proceed in parallel on simulators. On real hardware:

- Hardware group B (read-only buttons) may run at any time, because it cannot move anything.
- Hardware group S, the hand trip, comes before group C, group D and everything later. Group S includes the MRU4 trip and the repeat without At home, so passing S means P0 is done.
- The real station first sends to the real AGV at P7 step 5 (hardware D7 to D9, station plan S8), through `tools/test_sender.py`. Every order there is refused, because the lidar is absent.
- The first send that can turn the wheels is hardware G3, with the wheels lifted, and then G4 on the floor. Both start from a real button. `mosquitto_pub` and `tools/test_sender.py` are never used to start the real AGV moving.

## 6. P0: prove one trip by hand

**Scope.** No MRU machine run has been done yet. Prove the existing engine on the floor before
anything is added. No new feature code.

**Files.**

| File | Change |
|---|---|
| `missions/site-103.json:6` | `"trip_calls": 1`. No other line changes, so the BTU group is untouched |
| `tests/test_mission.py:234` | Expect 1; retitle the check ("one call a trip"). The check count does not change |
| `amr_ws/src/amr_web/test/test_teach_page.py:35` | Expect 1 |
| `manuals/site-layout-103.md` D4, D18 | Section 18 |
| `manuals/tracked-plan-4-position-engine.md:20`, `:62` | Note the change of default |

**Behaviour of `trip_calls` 1.**

- The first call of any group forms a trip (`CallQueue.ready_group`, `trip.py:46-58`). Across groups this is first come, first served.
- It is global, so BTU also becomes one machine per trip. `_parse_site` accepts 1 (`agv_core/mission.py:716-720`), and `missions/test-mru-straight.json:6` already uses it.
- D3 stays as written ("at most 2"). Only the setting changes.
- `_parse_site` validates all groups at load, so C-BTU must stay intact. This change does not touch it.
- Known behaviour, not new: `_trip_take` calls `take()` with no `available` argument. A call that cannot compile (an untaught BTU stop, for example) stays at the head and refuses every Start until someone cancels it on Run → Calls. `test_an_untaught_trip_is_refused_and_its_calls_wait_again` pins it.

**Is this a mission file change on the vehicle? Yes.**

- `MISSION_DIR` is `missions/` beside `agv_core` (`agv_core/mission.py:87`). The vehicle reads its own repo copy.
- No `colcon build` is needed for the file.
- It is read at line layer start (`line_follow_node.py:_tape_runtime`), so restart the tape layer or the service after copying it.
- The tape graph binds to the map only (`tape_graph.py:211`, `BINDING_KEYS`), so the taught graph should stay valid. Confirm by seeing the trip compile.

**`tape_loc.live`.** Follow `manuals/tracked-plan-4-position-engine.md:202-204`. Build
`amr_interfaces`, set `tape_loc.live: true` on the vehicle (O4), restart. With it on, the site mission
is the job at line layer start, so a guided or plain job has to be selected on the Run page.

**Floor procedure (human, real AGV, all on the AGV's own screen).** Hardware group S is the record of
this procedure:

1. Do checks V1 to V7 in section 21. Teach HOME-N if it is missing. Build, Publish, Make active.
2. Run the E2 laps if they are not recorded (`manuals/tape-localization-runbook.md` section 3.5 item 4).
2b. Run the 10 empty pivots (`manuals/tracked-plan-4-position-engine.md` E4, hardware S0).
3. MANUAL at HOME-N. Press At home and confirm the scans align. Confirm "Trolleys off at HOME". Selector AUTO.
4. Run → Calls: tap MRU1. Press START at HOME. Check horn, then the drive through R717 to ATT.
5. Hitch the empty trolley. START. Drive to MW-1.
6. Unhitch and move the trolley clear. START. Short move, measured stop, pivot at UT-MRU1, stop at ME-1. No "Released" confirmation should be needed, since the Start at MW-1 records it.
7. Hitch a trolley. START. Drive to HOME-N. Unhitch. Confirm "Trolleys off at HOME".
8. Repeat from step 4 **without** pressing At home. Nothing I read shows the locator staying usable at HOME after a trip on a vehicle: `tape_runtime.py:224-230` is code only, and `test_the_locator_moves_onto_a_trips_route_where_it_stands` covers only the move onto the route.
9. Repeat once for MRU4, which turns at the tape end (U-MRU).

Keep the event log, `<state_dir>/logs/line_trace` and the stop errors. Note that today's trip takes
four physical Starts: HOME, ATT, MW, ME.

**Tests first.** The two test edits above, failing before the mission edit.

**Done when.** Hardware group S has passed: two MRU1 trips in a row, the second without At home, and one
MRU4 trip finish with no unexplained `position` hold or FAULT, with stop errors recorded. The owner has
seen it, and `python3 tests/run_all.py` still reports 869 checks.

## 7. P1: the switch and the baselines

**Scope.** Config only, plus pins that prove "off is unchanged". No behaviour.

**Files.**

| File | Change |
|---|---|
| `agv_core/config.py` | `_SCHEMA` block `station` (near `:569`), docstring paragraph in the format of `:292-323`, checks in `_validate` (near `:986-989`) |
| `profiles/agv-01.json` | New block, below. Strict both ways (`_parse`, `:815`), so config and profile change together |
| `tests/test_config.py` | 11 new checks, using `refuses(...)` as at `:245-258` |
| `tests/run_all.py:154` | `EXPECTED_CHECKS` from 869 to 880, with a dated comment |
| `amr_ws/src/amr_line/test/test_station_off.py` | New |
| `amr_ws/src/amr_line/test/golden/` | New, recorded traces |

```json
"station": {
  "enabled": false,
  "broker_host": "192.168.2.5",
  "broker_port": 1883,
  "manufacturer": "gvi",
  "serial_number": "agv1",
  "settle_s": 5.0,
  "holdoff_s": 15.0,
  "order_torque_wait_s": 4.0
}
```

Keepalive 10 s, reconnect 2 s and the 5 s order window are contract values and stay constants in
code. `settle_s` and `holdoff_s` can only be lengthened from the contract's 5 s and 15 s. The
`order_torque_wait_s` default of 4.0 s is a placeholder, and must be replaced at P8 by a value measured
on the vehicle.

**Behaviour.** `/params` lists the block. Nothing else reads it yet.

**Tests first.**

`tests/test_config.py`, 11 checks:

1. `enabled` true with `tape_loc.live` false is refused.
2. A profile without the block is refused ("missing top-level").
3. An unknown key is refused.
4. `settle_s` outside [5, 60] is refused.
5. `holdoff_s` outside [15, 300] is refused.
6. `broker_host` not a dotted IPv4 address is refused.
7. `broker_port` outside 1..65535 is refused.
8. `manufacturer` not a plain MQTT topic level is refused.
9. `serial_number` not matching `PROFILE_NAME` (`agv-01` gives `agv1`) is refused.
10. `profiles/agv-01.json` ships with `enabled` false.
11. `order_torque_wait_s` not above `timing.auto_start_delay_s`, or above `timing.premove_timeout_s`, is refused.

`amr_line/test/test_station_off.py`:

- `test_a_waiting_call_with_no_start_stays_idle`: a formed trip, 60 s of ticks, no edge. State stays IDLE, `trip` is None, the wheel command is zero.
- `test_a_waiting_call_stays_idle_after_reset_clear_and_a_selector_return`: the three landing points a level trigger would fire on.
- `test_the_one_call_trip_matches_the_baseline` and `test_the_two_call_trip_matches_the_baseline`: run the `test_site_run.py` scenarios and compare each tick's `(state, hold_cause, left_rpm, right_rpm, reason)` with a CSV in `golden/`. **Record the CSVs at `c41afb3`, before any job code changes.** Tolerance 1e-9 on rpm, exact on text.

**Done when.** `run_all` reports 880, the new pytest file passes against unchanged job code, and the
golden CSVs exist.

## 8. P2: the job (pure, no ROS)

**Scope.** All decisions: the order entry, the interlocks, the settle timers. Tested with `Inputs`
only. This is where the fake lives until the lidar exists: a test sets `Inputs.trolley` and
`Inputs.rear_clear` directly.

**Files.**

| File | Change |
|---|---|
| `amr_line/order.py` | New, pure: `OrderRequest`, `OrderRun` (action statuses, last node, departed, ends), `Settle` (timers), reason constants |
| `amr_line/job.py` | `Inputs` fields, constructor, `order_request`, `order_cancel`, `_order_take`, `_order_start`, `_order_gate`, `_order_not_ready`, `_order_not_ready_first`, `_order_refuse`, `_order_refuse_in_state`, `_leave_check`, `_start_interlock`, `_home_moved`, `at_home_pressed`, `order_snapshot`, and hooks listed in section 9.4 |
| `amr_line/tape_runtime.py` | `at_home` gains a guarded readiness clear (9.2) |
| `amr_line/site_run.py` | Pivot guard in `at_rest`, `_tape_end_approach`, its `stopping` phase, and `tape_ended` |
| `amr_base/hold_policy.py` | `CAUSE_DEVICE["trolley"] = "rear_scanner"` |
| `agv_core/alarms.py` | Hold code and rows, because `test_hold_causes_all_map_to_a_catalogue_code` needs them (section 17). RUNBOOK section 4 regenerated |
| `amr_line/test/test_station_order.py`, `test_station_interlocks.py` | New |

`Inputs` gains three defaulted fields at the end (the pattern at `job.py:158-175`), so every existing
caller, including `World.inputs` in `test_mission_engine.py:111-121`, is unchanged:

```python
trolley: str = "unknown"          # "absent" | "present" | "unknown"; the node maps stale to unknown
rear_clear: bool | None = None    # None = unknown, as field_clear
loc_ready: bool = False           # TapeRuntime.ready; read for orders only
```

## 9. P2 detail: automatic departure

### 9.1 Entry point

`FollowJob._order_start(i, req)` is the only new way into ARMED. It has one call site, in `tick`:

```python
req = self._order_take(i)          # always None when calling is False; empties the latch every tick
if i.reset_edge and self.state != IDLE:
    self._order_refuse(req, "DEPARTURE_REFUSED", "PREREQUISITE")
    self.reset()
    self.reason = "reset"
    return 0.0, 0.0
if self.state in (IDLE, DONE):
    if i.start_edge:
        self._order_refuse(req, "DEPARTURE_REFUSED", "PREREQUISITE")
        return self._start(i)
    if req is not None:
        return self._order_start(i, req)
    ...                            # the existing IDLE text, unchanged
self._order_refuse_in_state(i, req)   # every other state: never reaches _begin_premove
```

```python
def _order_start(self, i, req):
    why = self._order_gate(i, req)                       # site and machine guards, contract checks 5, 6, 7
    trip = route = None
    if not why:
        trip = tripmod.Trip(self.site, self.site["MACHINES"][req.machine], [req.machine])
        try:
            route = self._site_cfg["compile"](trip)      # check 8
        except ValueError:
            why = ("NO_ROUTE_TO_TARGET", "ROUTE")
    why = why or self._order_not_ready_first(i)          # check 9
    if why:
        return self._order_refuse(req, *why)             # nothing stored, nothing retried
    self.trip, self.trip_route, self.trip_new = trip, route, route
    self.trip_note = ""
    self.order = order.OrderRun(req)
    self._binding = i.authority
    return self._begin_premove(i, "start")               # always "start": never uturn or continue
```

Not used, on purpose:

- `_start` is unchanged. `N._inputs` never synthesises `start_edge`.
- `CallQueue` is not touched. A station trip never enters `calls`, so nothing can be restored into it and no later Start can pick it up.
- `_trip_check`'s "formed trip" test does not apply, because the trip is set before ARMED.

**Inherited from ARMED, unchanged:** the 2 s horn (`panel_io.alarm_wanted`), `wants_power`, locator
seeding (`line_follow_node.py:692-697`), `_binding`, and the re-check of prerequisites every tick.

**Not inherited: the torque wait.** A physical Start keeps `timing.premove_timeout_s` (8 s). An order uses
the shorter `station.order_torque_wait_s` in `_premove_tick`. If torque has not arrived by then the warning
is cancelled, so an E-stop released later cannot let a stale ARMED order move. What remains is in 3.2.

### 9.2 Refusals

Contract checks 0 to 4 are in the bridge (P5). The job runs the rest, in contract order. The first
failure ends it. `_order_refuse` does nothing when the request is None. `_order_gate` tests `site is None`
first and the machine second, because checks 5, 7 and 8 need both.

| Check | Condition | errorType | reason |
|---|---|---|---|
| 5 | `self.order` active | `OTHER_ORDER_ACTIVE` | the active order id |
| 5 | `self.trip` set, or `self.calls.pending` not empty | `OTHER_ORDER_ACTIVE` | `LOCAL_TRIP` |
| 6 | Not (`panel_valid` and `panel_auto` and lease has LINE) | `MOBILE_ROBOT_NOT_AVAILABLE` | `NOT_AUTO` |
| 7 | `_site_at_home(i.loc)` false, or `_home_moved` | `START_NODE_OUT_OF_RANGE` | `NOT_AT_HOME` |
| 8 | `compile` raises `ValueError` | `NO_ROUTE_TO_TARGET` | `ROUTE` |
| 9 | First entry of `_order_not_ready(i)` | `DEPARTURE_REFUSED` | that entry |
| any | State is not IDLE or DONE, with no active trip | `DEPARTURE_REFUSED` | `FAULT`, or `SITE_NOT_LIVE` for a non-site run |
| any | `site` is None | `DEPARTURE_REFUSED` | `SITE_NOT_LIVE` |
| any | `req.machine` not in `site["MACHINES"]`, or its record has no `release` (a swap machine). A second guard behind bridge check 3 | `VALIDATION_FAILURE` | `MACHINE` |
| same id | `req.order_id` equals the current or last order | Dropped, no error | Bridge check 2 reports it. This is a second guard |

`_order_not_ready(i)` runs every tick while no order is active, and returns the contract section 8
reasons in that table's order. With `self.site` None it returns only `SITE_NOT_LIVE`, because the rows
below read `self.site`, `self._site_cfg` and `self.calls`, and the node runs with `catch_runtime=False`.

| Reason | Test |
|---|---|
| `NOT_AUTO` | Not (`panel_valid` and `panel_auto`). A stale panel therefore gives `NOT_AUTO`, not `PREREQUISITE` |
| `NOT_AT_HOME` | `_site_at_home(i.loc)` false, or `_home_moved` |
| `LOCALIZATION_NOT_READY` | Not `i.loc_ready`. Orders only |
| `TAPE_NOT_SEEN` | Not `i.sensor["has_track"]`. Orders only |
| `FAULT` | `state == FAULT` |
| `TORQUE_TIMEOUT` | Latched by a torque-wait cancel, cleared only by `i.reset_edge` |
| `TROLLEY_PRESENT` / `TROLLEY_UNKNOWN` | `i.trolley` |
| `REAR_FIELD_NOT_CLEAR` / `REAR_FIELD_UNKNOWN` | `i.rear_clear` |
| `PREREQUISITE` | `_prerequisite(replace(i, panel_valid=True, panel_auto=True), torque=False) or _rfid_check(i)` |
| `SITE_NOT_LIVE` | `self.site is None` |
| `LOCAL_TRIP` | `self.trip` or `self.calls.pending` |
| `SETTLING` | `Settle.settling(now)` |
| `HOLDOFF` | `now < self._holdoff_until` |

`Settle` restarts its 5 s on:

- the selector entering AUTO, a Reset edge;
- a web Clear, a local call cancel, a mission selection;
- the trolley going to absent, the rear field going to clear, the front field going to clear;
- `_arrive_home`;
- any warning ended by a cancel or by `cancelOrder`.

It also starts running at the first tick after construction, because the selector's history is unknown
then. The timers read `i.now`, which is monotonic. The risk assessment (O3) reviews this list.

**`_home_moved` (orders only).** `at_home_pressed()`, called from `_srv_at_home` on success, and
`_arrive_home` each save `i.counts` as the baseline. Any wheel's count moving more than `HOME_STILL_M`
from the baseline clears it, and with no baseline or no fresh counts `_home_moved` is true. Only At home
sets it again. `HOME_STILL_M` is a constant in `order.py`, 0.02 m of wheel travel as a placeholder,
checked against encoder noise at P8. A pivot adds about 0 to S (`tape_locator.py:168-178`), but both
wheels' counts change, so it is caught. Not verified: whether a jog runs with the line layer up or after a
layer change. A new process has no locator, so both cases end at `NOT_AT_HOME`. This is a procedural check
that a person looked at the vehicle. Heading itself is not measured (3.2).

**`LOCALIZATION_NOT_READY`.** The job's check reads `TapeRuntime.ready`. If readiness was already READY when
At home is pressed, the locator could start on the next tick, before `/initialpose` has moved it to
CHECKING (`tape_runtime.py:134-135`, `:169-176`). So with the switch on, `at_home` also clears `ready`, and
the locator waits for a fresh READY. With the switch off, the code path is as today. Not verified: whether an
old READY can still arrive just after `/initialpose`. Check at P7.

**`TORQUE_TIMEOUT`.** The latch is not saved. A new process needs At home anyway. A Reset edge suppressed
by `panel_io` as suspect leaves it latched, which is the safe side.

Cost to measure: check 8 compiles a route and reads `areas.json` inside the tick (`tape_runtime.py:195-206`).
The physical Start path does the same once per press. The station resends every 2 s, but holds back
while `NOT_READY` shows. Measure the compile time on the N97 in P7. I have not measured it.

### 9.3 Single use

- One request lives for one tick. `_order_take` empties the latch each tick, in every state. This is the rule `_start` documents (`job.py:509-513`): a refused press is dropped.
- A refused order stores nothing. Only a new message can try again, and it must pass bridge check 4.
- An accepted order is recorded in `self.order`. The same id can never start again, from the job or the bridge.
- An order is never resumed. Nothing in `_hold_tick`, `_station_tick` or `_premove_go` reads the latch.

**It cannot resume a hold or leave any other stop:** the only read of the request leading to motion is
inside `if self.state in (IDLE, DONE)`, and `_order_gate` requires no trip and at HOME. A static test
pins this (section 16).

### 9.4 Hooks in existing code

Each is guarded so the switch-off path is the same code as today.

| Place | Hook |
|---|---|
| `_premove_cancel`, `job.py:575-577` | `if kind == "start" and self.order is live`: end it `DEPARTURE_CANCELLED`, set `trip`, `trip_route` to None, set `HOLDOFF`, restart `Settle`, no restore. Otherwise the existing lines |
| `_premove_tick`, `:607-609` | With `pm["kind"] == "start"` and a live order not yet departed, the limit is `order_torque_wait_s` instead of `premove_timeout_s`, and the cancel reason is `TORQUE_TIMEOUT`, which latches. Any other premove kind keeps `premove_timeout_s` and never latches |
| `_tape_end` run branch, `:1088-1091` | With calling on, trolley not absent before `begin_spin` gives the `trolley` hold (9.6) |
| `_trip_abort`, `:420-425` | Order not departed: `DEPARTURE_CANCELLED`, `HOLDOFF`, `Settle` restart. Departed: `TRIP_ABORTED`, keeping the text |
| `clear`, `:657-675`, through `_srv_clear` | With calling on: refused in FAULT, otherwise restarts `Settle` |
| `trip_cancel`, `:342`; `set_mission`, `:427` | With calling on: restarts `Settle` when it succeeds |
| `_depart`, `:532-551` | `order.departed = True`. `lastNodeId` stays `HOME-N`, seq 0 |
| `_run`, line 1293, the `station` hold | `order.at_rest(sid)`: action `RUNNING`, `lastNodeId` and seq set |
| `_premove_go`, `kind == "station"`, `:643-651` | `order.left(sid)`: action `FINISHED`, as the warning ends and the vehicle moves |
| `_arrive_home`, `:978-994` | `order.home()`: seq 8, not active. Restarts `Settle` and saves the `_home_moved` baseline. `payload.trip_ended()` stays for the switch-off path |
| `_trip_check`, `:398-401` | See 9.6 |
| `_station_tick`, `:972-974` | See 9.6 |
| `trip_status`, `:376-378` | With calling on, `trip_payload` shows the trolley reason instead of the `Payload` text |
| `trip_call`, `confirm_released`, `confirm_off`, `:337-365` | With calling on: refused as in 4.2 and 4.3 |
| Head of `tick` | Store `i.now` and `i.counts` for the hooks with no `Inputs`. `Settle.update(i)`, the `_home_moved` update, the `TORQUE_TIMEOUT` clear, `_order_not_ready(i)` |

Cancel, on the tick after `order_cancel`:

| Situation | Result |
|---|---|
| Order id matches, ARMED, `_premove["kind"] == "start"`, not departed | State back to `_premove["back"]`, trip cleared, actions `FAILED`, `cancel_status` `FINISHED`, no `HOLDOFF`, `Settle` restarted (4.5 R8) |
| Order id matches, departed | `FAILED`, `CANCEL_REFUSED`. The order continues |
| No active order or another id | `FAILED`, `NO_ORDER_TO_CANCEL` |

### 9.5 Tests first: `amr_line/test/test_station_order.py`

Uses a new `CallingWorld(TripWorld)` from `test_site_run.py`, built with `calling=True`, and the
`site_fixture` circuit.

| Test | Pins |
|---|---|
| `test_off_an_order_is_refused_and_nothing_is_latched` | Default `FollowJob`; the next ticks are identical |
| `test_an_order_at_home_goes_through_armed_with_no_start_edge` | ARMED, then RUNNING only after `premove_s` and torque |
| `test_an_order_arms_the_same_warning_as_a_start` | Same `wants_power`, same LineState state, zero command while ARMED |
| `test_only_the_first_stop_is_automatic` | Parks at ATT, holds, no further order or time moves it; START does |
| `test_a_refused_order_does_not_run_later` | Blocked by the field, field clears, stays IDLE |
| `test_a_request_lives_for_one_tick` | Any tick consumes it |
| `test_the_same_order_id_never_starts_twice` | After finish, after cancel, after refusal-free replay |
| `test_each_contract_check_refuses_with_its_error[...]` | One case per row of 9.2 |
| `test_an_order_is_refused_in_every_other_state[...]` | ARMED, RUNNING, FAULT, and HOLD for each cause, including `station` |
| `test_an_order_cannot_resume_a_hold_or_leave_a_stop[...]` | Each hold cause: state and command unchanged |
| `test_a_start_in_the_same_tick_refuses_the_order` | The press handled, the order refused |
| `test_a_reset_in_the_same_tick_refuses_the_order` | |
| `test_a_cancelled_warning_ends_the_order[...]` | Front field, rear field, trolley, torque timeout, panel link, selector, Reset, Clear. No motion, `DEPARTURE_CANCELLED`, `HOLDOFF` |
| `test_a_cancelled_order_restores_no_call` | `calls.pending` stays empty |
| `test_holdoff_and_settling_block_for_their_time[...]` | Each restart cause in 9.2, the web actions, front field, arrival and `cancelOrder` included |
| `test_settling_runs_from_start_up` | First ticks show `SETTLING` |
| `test_clear_in_fault_is_refused_with_calling_on`, `test_clear_in_fault_unchanged_with_calling_off` | 4.3. A waiting order gets no release from Clear |
| `test_a_torque_timeout_latches_until_a_reset_edge` | One cycle only. `TORQUE_TIMEOUT` holds through `HOLDOFF` and clears only on `reset_edge` |
| `test_an_order_cancels_at_its_own_torque_wait`, `test_a_physical_start_keeps_the_premove_timeout`, `test_a_station_warning_in_an_order_keeps_the_premove_timeout` | `order_torque_wait_s` for orders only. Torque arriving after the wait moves nothing |
| `test_at_home_needs_a_fresh_ready` | Readiness READY when pressed, then order: `LOCALIZATION_NOT_READY`, no horn, until a new READY |
| `test_no_tape_refuses_an_order`, `test_no_tape_or_readiness_check_on_a_physical_start` | `TAPE_NOT_SEEN` and `LOCALIZATION_NOT_READY` are for orders only |
| `test_any_wheel_movement_clears_at_home_for_orders[jog,pivot,after_arrival,no_counts]` | `NOT_AT_HOME` until `at_home_pressed`. S unchanged by the pivot |
| `test_no_site_gives_only_site_not_live` | Non-site mission or no graph: no exception in the tick, one reason |
| `test_a_stale_panel_gives_not_auto` | Contract section 8, not `PREREQUISITE` |
| `test_cancel_in_the_warning`, `test_cancel_after_departure_is_refused`, `test_cancel_with_no_order` | 9.4 table |
| `test_action_states_follow_the_trip` | WAITING, RUNNING, FINISHED at each stage, the warning included |
| `test_a_cancelled_warning_at_a_stop_keeps_the_action_running` | `START_REFUSED`, reason `WARNING_CANCELLED` |
| `test_an_abort_after_departure_reports_trip_aborted` | Selector, tape loss, wrong branch, Clear |
| `test_an_order_to_the_tape_end_machine` | Machine with no U-turn point |
| `test_a_machine_with_no_release_is_refused[unknown,swap]` | `VALIDATION_FAILURE`, reason `MACHINE`. A swap machine cannot be ordered |
| `test_the_order_entry_has_one_call_site` | Static, section 16 |

### 9.6 Interlocks

These replace `Payload.may_leave` and the release confirmation when the switch is on. With the switch
off, `Payload` and `confirm_*` work as today and the lidar is never read.

**Leaving home**, for orders and local trips, `_trip_check`:

```python
if self.calling:
    why = self._leave_check(i)          # also runs every tick of the warning
    if why:
        return why
elif self.trip is None:
    ok, why = self.payload.may_leave()  # existing lines
    if not ok:
        return why
if self.trip is None and self.calls.ready_group() is None:
    ...                                 # existing lines
```

A rear field or trolley failure during the warning follows `_premove_tick`'s rules: a violated rear
field cancels at once, as the front field does at `job.py:599`, and others after the debounce.
`SETTLING` and `HOLDOFF` apply only to orders. A local trip has a person at the panel.

**START at a stop**, in `_station_tick`. Today's `pre` handling stays. With `calling` on it also runs:

| Stop | Identified by | Needs | Refused reason |
|---|---|---|---|
| ATT | `tape.stop["plan_role"] == "attach"` | present | `NO_TROLLEY`, `TROLLEY_UNKNOWN` |
| MW-n | `plan_role == "machine"`, `trip.work(tag)` holds `release` | absent | `TROLLEY_STILL_ON`, `TROLLEY_UNKNOWN` |
| ME-n | `plan_role == "machine"`, `trip.work(tag)` holds `take` | present | `NO_TROLLEY`, `TROLLEY_UNKNOWN` |
| R2-n (BTU) | `trip.work(tag)` holds `swap` | Nothing (O10) | |

- A refused press is dropped and not remembered. It raises an event, and sets `start_refused_*` until the next press.
- A press refused for `pre` also reports `START_REFUSED`, reason `PREREQUISITE`. Today it is silent (`job.py:972-976`). With the switch off it stays silent.
- The check also runs through the station warning. A failure there is `WARNING_CANCELLED`, with the debounce as above.

**The pivot (O7).** `SiteRun` gets `self.trolley = None`. `_run` sets it from `i.trolley` only when
`calling` is on. In `at_rest` (after `may_pivot` passes) and in `_tape_end_approach`, if `trolley` is
set and not `"absent"`, the result is a hold with the new cause `trolley`. It waits for START like every
hold not in `AUTO_CAUSES` (`job.py:926-939`), and at rest the check runs again. `trolley` None gives
today's code path. Two more places need the same check:

- `tape_ended` (`site_run.py:345-362`), a third entry reached from `job._tape_end_tick` (`job.py:1159-1171`). It checks only `may_pivot()` and calls `_turn`. Not absent sets `self.fault`, as its `may_pivot` failure does.
- The tape-end approach. `_tape_end_approach` checks at its start, `lead_m` before the pivot (1.5 m on `site-103`). So the check runs again before `begin_spin` (`job.py:1089`), and not absent gives the `trolley` hold.

**While driving.** Nothing. Trolley state is reported in `loads` only (O10).

**Rear field stops.** Stopping is the OSSD's job, if wired (O2). `_safety_cause` is not changed (O8).

**Tests first: `amr_line/test/test_station_interlocks.py`.**

| Test | Pins |
|---|---|
| `test_off_the_lidar_is_never_read` | `Inputs.trolley` varied, trace identical; `confirm_off` still required |
| `test_on_a_local_trip_leaves_only_with_no_trolley_and_rear_clear[...]` | Present, unknown, violated, unknown field |
| `test_on_the_confirmations_are_refused` | Both, with the text |
| `test_start_at_attach_needs_a_trolley[...]`, `test_start_at_take_needs_a_trolley[...]`, `test_start_at_release_needs_no_trolley[...]` | Each reason |
| `test_a_refused_press_is_not_remembered` | Trolley appears later, nothing moves |
| `test_a_start_refusal_clears_on_the_next_press` | |
| `test_trolley_lost_in_the_station_warning_cancels_it` | Back to the station hold, `WARNING_CANCELLED` |
| `test_a_swap_stop_has_no_interlock` | BTU fixture |
| `test_no_pivot_unless_the_trolley_is_absent[midline,tapeend,tapeend_stopping,tape_ended]` | Hold `trolley`, then START with absent pivots. `tape_ended` faults instead, with no pivot |
| `test_a_rear_stop_reads_as_estop_and_waits_for_start` | O8, front clear with torque lost |

**Done when.** Both files pass, the P1 baselines still match, every test in section 3.4 passes, and no
existing test body has changed except those listed in section 16.

## 10. P3: node, messages, web, fake trolley

**Scope.** Wire the job to ROS with the switch. Sim only.

**Files.**

| File | Change |
|---|---|
| `amr_interfaces/msg/OrderState.msg`, `TrolleyState.msg`, `CMakeLists.txt` (`:11-45`) | New |
| `amr_base/amr_base/wire.py` | `TROLLEY_NAMES`, append only |
| `amr_base/test/test_wire_contract.py` | New pinned test |
| `amr_line/amr_line/line_follow_node.py` | Below |
| `amr_sim/amr_sim/fake_trolley_node.py`, `amr_sim/setup.py` | New fake |
| `amr_bringup/launch/base.launch.py` | Fake in the sim branch only, when enabled |
| `amr_web/amr_web/server.py`, `adapter.py`, `templates/run.html` | Below |
| `amr_web/tools/demo_server.py` | Check it still works; I did not confirm it implements `line_trip` |

**Node behaviour.** Only under `if vehicle_config.STATION_ENABLED:`, importing `OrderState` and
`TrolleyState` lazily, so a stale `amr_interfaces` build cannot hurt a switched-off vehicle:

- `FollowJob(calling=True, settle_s=..., holdoff_s=..., order_torque_wait_s=...)`.
- Service `/amr/line/order`, handled as `_srv_trip` is (`line_follow_node.py:360-383`), and logged with an event.
- Subscribe to `/amr/rear/trolley`. Age it in `_inputs`: older than `rear_field_fresh` (0.5 s, the front field's `field_s`) gives `trolley="unknown"`, `rear_clear=None`. `_inputs` also fills `loc_ready` from `TapeRuntime.ready`.
- Publish `/amr/line/order_state`, latched, on change and at 1 Hz. `driving` is set from `left`/`right` in `_tick`.
- `_srv_at_home`: refused unless the panel is fresh, valid and not AUTO (O11). On success it calls `job.at_home_pressed()`.
- `_srv_clear`: in FAULT, replies refused with "press Reset on the panel" (`line_follow_node.py:636`).

`_inputs` still hands out `start_edge` only from `_on_panel`.

**Fake trolley.** `fake_trolley_node` publishes `TrolleyState` at 10 Hz, starts `UNKNOWN`, and takes
`/sim/trolley/set` in the style of `fake_panel_node`. It is launched only from the `else:` (sim)
branch of `_compose` in `base.launch.py`, and never on `real:=true`. There is no real-vehicle bypass
(contract section 7).

**Web.** `/api/line/site` gains `"calling": config.STATION_ENABLED`. `/api/state` gains `order` only
when on, through a subscription made only when on. On `/run` with `calling` true:

- The warn box says the vehicle can leave HOME on a station call with nobody at the panel.
- The Released and Trolleys off buttons are disabled, with the reason.
- New tiles show trolley state, rear field, and order with stage.

The page markup stays, so `test_calls_and_confirmations_are_open_to_the_operator_and_checked` is
untouched. `TRIP_ACTIONS` does not change.

**Tests first.**

| Test | File | Pins |
|---|---|---|
| `test_trolley_names_are_the_msg_constants` | `amr_base/test/test_wire_contract.py` | Table |
| `test_off_the_node_has_no_order_service_or_topic` | `amr_line/test/test_line_node_station.py` (new, `importorskip("rclpy")`) | Names absent |
| `test_on_a_stale_trolley_message_is_unknown` | Same | Freshness |
| `test_at_home_needs_manual_with_calling_on`, `test_at_home_unchanged_with_calling_off` | Same | O11 |
| `test_clear_in_fault_replies_refused_with_calling_on` | Same | 4.3 |
| `test_off_base_launches_todays_nodes`, `test_on_sim_adds_the_fake_trolley`, `test_the_fake_trolley_is_never_launched_on_a_vehicle` | `amr_bringup/test/test_launch_layers.py` | `compose` (`:104`), with `config.STATION_ENABLED` monkeypatched |
| `test_no_web_route_reaches_the_order_service` | `amr_web/test/test_station_web.py` (new) | `/amr/line/order` appears nowhere under `amr_web`; `TRIP_ACTIONS` is exactly today's five. It only searches for the service name. The indirect path, a web action removing a block, is pinned by `test_holdoff_and_settling_block_for_their_time[...]` and `test_clear_in_fault_is_refused_with_calling_on` |
| `test_run_page_text_follows_the_switch` | `amr_web/test/test_station_web.py` | `site.calling` both ways |

**Done when.** The tests pass, `colcon build --packages-select amr_interfaces amr_line amr_sim amr_web`
is clean, and the full `amr_ws` pytest run passes with `station.enabled` false.

## 11. P4: rear lidar software

**Scope.** Everything that can be written without hardware. The rear lidar is assumed and not fitted.
I assume it is a second nanoScan3, because the drawings name `-BG2` and the driver and field model
exist. Confirm the model at P8.

### 11.1 Scanner driver instance and frames

| File | Change |
|---|---|
| `amr_bringup/launch/rear_scanner.launch.py` | New: one node, `name="sick_safetyscanners2_rear_node"`, namespace `rear`, `respawn=True`, as `scanner.launch.py:23-32` |
| `amr_bringup/config/nanoscan3_rear.yaml` | New. Own node key, because the key in `nanoscan3.yaml:14` will not match a renamed node. `frame_id: rear_laser_frame`, `host_udp_port` not 6060, `sensor_ip` placeholder |
| `amr_bringup/launch/base.launch.py` | Include it only when `rear.source == "scanner"` |
| `amr_description/urdf/amr.urdf.xacro` | `rear_laser_frame`, joint from `base_link`, yaw pi, behind a `rear_lidar` arg defaulting false. Geometry args marked MEASURE |
| `amr_description/launch/description.launch.py` | Expose the arg |
| `amr_description/test/test_urdf.py:12` | Both cases. The default output keeps today's links |
| `amr_bringup/test/test_launch_layers.py` | Additions only. `test_scanner_layer_has_no_description` (`scanner.launch.py` stays one node) unchanged |

Not verified, and the driver package is not in this repo: how `sick_safetyscanners2` namespaces its
topics. The stack's consumers use absolute `/output_paths` and `/scan`
(`line_follow_node.py:237`, `cmd_mux_kinematics_node.py:259`, `gating.py:406-422`), and nothing may
collide with them. Check on the vehicle that the rear unit publishes under `/rear` and the front
topics are unchanged. If namespacing does not work, use remaps.

`scanner_fields.py` assumes exactly one scanner (`ROLES`, `:18`, `:40`). Do not extend it. The rear
field's index goes in the `rear` block.

The rear scanner feeds no costmap, AMCL or mux. Only `trolley_node` subscribes.

### 11.2 Safety chain and FX3 (owner, not software)

| Item | Fact | Source |
|---|---|---|
| Safe inputs | All 8 used. Q3 placeholder, Q4 spare | `documentation/electrical/01-schematic/io-mapping.md:72-90` |
| Drawings | "Rear scanner (-BG2, SF3) Not fitted ... No OSSD inputs reserved on -KE2" | `documentation/electrical/01-schematic-iec/iec-page-41.html:58-60`; `sheet-plan.md:89`, decided 2026-10-30 |
| PFHd | About 7.8e-7 against 1e-6, with placeholder SICK values. "No room for a third series subsystem ... Model before adding" | `code_ce/sick_lidar/safety-system-brief.md:210-218`. The brief is older than current wiring in places |
| Field switching | Listed as not built | Same file, section 10 |
| Towing field | Open in the manual | `documentation/operation-manual/operation-manual.md:297`, `:498`, `:1107` |
| Scanner capacity | NANS3-AAAZ30AN1 (nanoScan3 Core I/O) is the device named in the brief. Its datasheet: 2 monitoring cases, 8 fields, 1 OSSD pair. Whether the fitted unit is that variant is not confirmed | `safety-system-brief.md:46`; datasheet figures second-hand |

Safety Designer stays humans only (`nanoscan3.yaml:6-10`). The software reads what the field says and
decides nothing about what it should be.

### 11.3 Trolley detection node

**Files.**

| File | Change |
|---|---|
| `amr_base/amr_base/trolley_detect.py` | New, pure, clock-fed |
| `amr_base/amr_base/trolley_node.py`, `amr_base/setup.py` | New node |
| `agv_core/config.py`, `profiles/agv-01.json` | `rear` block; `source` is `"none"` by default |
| `tests/test_config.py`, `tests/run_all.py` | 6 more checks, 886 |
| `tools/trolley_calibrate.py` | New |
| `amr_base/test/test_trolley_detect.py` | New |

**Algorithm.** Per scan on `/rear/scan`, in the scanner's frame:

1. Take each beam with a finite range inside `[range_min, range_max]`. Convert it to x, y.
2. Count the beams inside the rectangle `roi_x_min_m..roi_x_max_m`, `|y| <= roi_half_width_m`. The rectangle covers where a hitched trolley sits.
3. Raw reading: `count >= present_points` is present; `count <= absent_points` is absent; between is neither.
4. State changes only after the raw reading has held continuously: `present_s` to go present, `absent_s` to go absent. A "between" scan resets the timer and keeps the state.

**States.**

| State | When |
|---|---|
| `UNKNOWN` | At start. No scan for `stale_s`. Malformed scan. More than `max_invalid_ratio` of the zone's beams invalid. A repeated scan counter beyond `stale_s`, if the driver exposes one. It then needs a full debounce to leave |
| `ABSENT` | As above |
| `PRESENT` | As above |

Rear field comes from `/rear/output_paths` through `drive_state.field_clear(status, index)`, the
function the front field uses, with the same `field_s` freshness: clear, violated or unknown. Polarity
must be checked against the rear scanner's configuration at P8. The front's is pinned in
`scanner_fields.yaml`. It reports clear only with the rear case gate met (3.3): `rear_case` is
`CASE_NO_TROLLEY`, or `rear_case` is `CASE_UNKNOWN` and `rear.case_proven` is true. `CASE_OTHER` is never clear, whatever `case_proven` says. Otherwise clear becomes unknown. `trolley_detect` state
never feeds this.

**Frozen scans.** Freshness catches silence, not a scanner or driver that keeps publishing frozen content.
If the driver exposes a scan counter (not verified, V18), a counter that repeats beyond `stale_s` gives
`UNKNOWN`. If it does not, this residual goes to O3 (3.2).

Publishes `/amr/rear/trolley` at 10 Hz and on change. Launched only when `rear.source == "scanner"`,
`respawn=True`, not `required` (the `rfid_node` pattern, `base.launch.py:85-94`).

**Values.** All zone, count and time values are placeholders until calibration at P8. Do not treat any
default as measured. `validate` checks only their order and range: `absent_points < present_points`,
`roi_x_min_m < roi_x_max_m`, and times above 0. `stale_s` also has a ceiling: it must not exceed
`FRESH_FIELD_S` (`freshness.field_s`, 0.5 s in the profile), so `trolley_node` cannot keep publishing an
old state as fresh. `rear.case_proven` is a boolean, default false, set only under the gate in 3.3.

**Calibration (human, P8).** `tools/trolley_calibrate.py` prints the beam count in the zone over
30 s. Record it for each case:

| Case | Why |
|---|---|
| No trolley, at HOME-N, ATT, every MW-n and ME-n | Walls, machines or parked trolleys inside the zone would read as present |
| Types A, B, C, E, F, G, empty and full, hitched | The scan plane must meet every type. The repo has no trolley geometry |
| Unhitched, standing in place | O9 |
| Moved clear | The distance operators must be told |
| A person at the hitch; a person where the trolley would be | Confirms the limit below |
| Vibration: hitched, rolling slowly | Beam count while moving |

Trolley detection is not personnel protection. A person in the zone reads as a trolley, and the check
cannot tell them apart. The rear safety field does that job.

**Test fake.** `test_trolley_detect.py` builds synthetic scans from a list of rectangles. It needs no
ROS. The system-level fake is `fake_trolley_node` (P3).

**Tests first.**

| Test | Pins |
|---|---|
| `test_starts_unknown` | First state |
| `test_present_needs_the_debounce`, `test_absent_needs_the_debounce` | Time |
| `test_one_bad_scan_does_not_flip_it` | Debounce |
| `test_between_keeps_the_state_and_resets_the_timer` | Hysteresis |
| `test_a_stale_scan_is_unknown`, `test_a_malformed_scan_is_unknown`, `test_too_many_invalid_beams_is_unknown` | Fail safe |
| `test_a_frozen_scan_is_unknown` | A repeated counter beyond `stale_s`. Skip it, and record the residual, if the driver has no counter |
| `test_rear_clear_needs_the_case_gate[no_trolley,other,unknown,proven,other_with_proven]` | Clear stays clear only for `no_trolley`, or for an unknown case with `proven`. `other` and `other_with_proven` read unknown |
| `test_the_trolley_state_never_selects_a_case` | Static: `trolley_detect` and `trolley_node` publish no case input |
| `test_leaving_unknown_needs_a_full_debounce` | Fail safe |
| `test_points_outside_the_zone_do_not_count` | Geometry |
| `test_rear_field_is_unknown_when_stale`, `test_rear_field_malformed_is_no_evidence` | As the front |
| `test_config`: 6 refusals | Source value, count order, zone order, time above 0, index range, `stale_s` above `FRESH_FIELD_S` |

**Done when.** These pass. Launch with `rear.source: "none"` is unchanged (`test_off_base_launches_todays_nodes`).

**What runs against a fake until the lidar exists:** all of P2, P3 and P5, and the P7 sim. On the real
vehicle nothing fakes it. With the switch on and no lidar, trolley state is unknown and every departure
is refused.

## 12. P5: the MQTT bridge

**Scope.** A new package that speaks the contract. It has no motion authority except the one action.

### 12.1 Files

| File | Change |
|---|---|
| `amr_ws/src/amr_station/` (`package.xml`, `setup.py`, `setup.cfg`, `resource/`) | New package |
| `amr_station/vda_order.py` | Pure: parse, checks 0 to 4, canonical order for a machine |
| `amr_station/vda_state.py` | Pure: `state`, `connection` and `instantActionStates` builders |
| `amr_station/mqtt_link.py` | paho wrapper. Lazy import, injected client |
| `amr_station/station_bridge_node.py` | The node |
| `amr_bringup/launch/base.launch.py` | Conditional `Node`, below |
| `amr_bringup/package.xml` | `exec_depend amr_station` |
| `amr_bringup/test/test_launch_layers.py` | On and off cases; `HW_EXES` gains it only in the "on" case |
| `amr_ws/deploy/validate.sh` | Check below |
| `alpha-setup.md` section 5.2 | Row and install commands |

`amr_station/package.xml` declares no pip dependency. `alpha-setup.md:700` skips pip keys in rosdep, so
a new key would need a skip.

### 12.2 Launch and deploy

`if config.STATION_ENABLED:` in `base.launch.py`, for both real and sim:

```python
Node(package="amr_station", executable="station_bridge_node", name="station_bridge",
     output="screen", respawn=True, respawn_delay=5.0,
     parameters=[{"state_dir": paths.state_dir()}])
```

- Not `required`. A dead bridge must not end the base (`base.launch.py:12-13`). Same pattern as `rfid_node`.
- It is launched by `ros2 launch` under the supervisor, so `process_supervisor.ALLOWED_EXECUTABLES` (`:29`) does not change.
- `amr.service`, `amr-supervisor.sh`, `amr.env` and `UNITS` in `install.sh:9` and `validate.sh:7` do not change. There is no new service.
- `install.sh` does not change.
- `validate.sh` gains: read `station.enabled` from the profile. If true, check `python3 -c "import paho.mqtt.client"` and that `$AMR_STATE_DIR/station-mqtt.json` exists with mode 600. Failure stops validation, with a message naming what is missing. If false, say nothing.

**Credentials.** `<state_dir>/station-mqtt.json`, `{"username": "agv1", "password": "..."}`, mode 600,
never in the repo. The node refuses to connect if the mode is wider, and raises `STATION_LINK_DOWN`.

### 12.3 Installing paho on a vehicle that may have no internet

Verify these on a real vehicle. They come from general knowledge, and I have not run them.

| Option | Commands |
|---|---|
| Copied wheel (default) | On a PC with internet: `pip download paho-mqtt==2.1.0 --no-deps -d wheels/`. Copy with `scp`. On the vehicle: `pip3 install --user --no-index --find-links wheels/ paho-mqtt==2.1.0` |
| Phone tether | With `usb0` up: `pip3 install --user paho-mqtt==2.1.0` |

- The service runs as the same user, so user-site should resolve. This is my inference, so check with `python3 -c` under `amr.service`'s environment.
- Do not use apt `python3-paho-mqtt` (1.x, per the code map): the 1.x and 2.x callback APIs differ. Use `CallbackAPIVersion.VERSION2` explicitly, so a wrong version fails at once.
- Pin it in `alpha-setup.md` section 5.2.

### 12.4 Threading

| Thread | Does | Must not |
|---|---|---|
| paho network (`loop_start`) | `on_connect`: set flag. `on_message`: append `(topic, bytes, retain)` to a bounded `deque(maxlen=32)`. `on_disconnect`: clear flag | Parse, call ROS, block |
| rclpy single-threaded executor | Everything else: 20 Hz drain timer, 10 Hz state timer, subscriptions, service client, all publishing | Block on the network. Use `connect_async`, and `call_async` for the service |

`client.publish` is called only from the ROS thread and only when `connected` is true. So a publish
while disconnected is dropped, as contract section 1 requires, QoS 1 included. Verify against the real
broker that nothing queues.

### 12.5 Connection

- `manufacturer`, `serial_number` and host come from `agv_core.config`. Topics are built from those, and no code has the literal `agv1`.
- MQTT 3.1.1, clean session, keepalive 10 s, `reconnect_delay_set(2, 2)`.
- Last will set before connect: `connection`, QoS 1, retain, `CONNECTION_BROKEN`, with the header as of connect.
- On connect, in order: subscribe `order` and `instantActions`; publish `ONLINE` (QoS 1, retain); publish `state`.
- On shutdown (`before_destroy`): publish `OFFLINE`, then disconnect.
- `headerId` per topic, +1 per send, from 0 at process start.

### 12.6 Order handling

Run in the drain timer. Checks 0 to 4 are here, and the job runs 5 to 10.

| Check | Rule | Failure |
|---|---|---|
| 0 | Retain flag not set. MQTT 3.1.1 sets the flag only for delivery caused by a new subscription, so this catches a retained order on re-subscribe. A retained publish while the bridge is connected arrives with the flag clear and goes on to the other checks, check 4 included | Discard, no report |
| 1 | Valid JSON under 64 kB. Required fields. `manufacturer`, `serialNumber` are ours. `version` starts `3.` | `VALIDATION_FAILURE` |
| 2 | `orderId` differs from `state.orderId` | Same id: compare `nodes` and `edges` with `canonical_order(state machine)`, ignoring the header and `seenStateHeaderId`. Same: ignore. Different: `SAME_ORDER_UPDATE_ID` |
| 3 | Exact shape of contract section 2. Machine found from the nodes in `mission.load_site(config.TAPE_LOC_SITE_MISSION)`: `release == MW-n` and `take == ME-n` | Shape: `VALIDATION_FAILURE`. Action type or params: `INVALID_ORDER_ACTION` |
| 4 | `seenStateHeaderId` is in a ring of `(headerId, monotonic)` from the last 5 s of our own `state` sends | `STALE_ORDER` |
| then | Service `depart`, with no wait | Service absent: `MOBILE_ROBOT_NOT_AVAILABLE`, reason `LINE_LAYER_DOWN` |

**Duplicates and resend.** The station resends every 2 s until `state.orderId` shows the order. The
AGV never retries. A resend arriving after acceptance fails at check 2 with no error. A resend that
beats the `OrderState` reply is dropped by the job's same-id guard. Refusals: one slot, with the newest
replacing, cleared on accept (contract 6.3).

**Why it cannot wait anywhere.** Contract section 8 lists the transport rules. On the AGV: bounded deque,
retain discard, ring window, nothing stored on refusal, one-tick latch.

### 12.7 Mapping to `state`

The bridge caches the latest of each input and builds a message on a 10 Hz timer. It publishes when
the body changed, or 1 s has passed. That meets "within 200 ms" and "at least once per second".

| Field | Source |
|---|---|
| `orderId`, `orderUpdateId` | `OrderState.order_id`, 0 |
| `lastNodeId`, `lastNodeSequenceId` | `OrderState.last_node_id`, `last_node_seq` |
| `nodeStates`, `edgeStates` | `canonical_order(machine)`, keeping items with sequence above `last_node_seq` while `active`, else empty |
| `loads` | `trolley`: absent `[]`; present one `TROLLEY` row; unknown key omitted (contract section 7) |
| `driving` | `OrderState.driving` |
| `actionStates` | `att_status`, `mw_status`, `me_status`, with ids `<orderId>:ATT`, `:MW`, `:ME`. Empty when `""` |
| `instantActionStates` | Bridge: last 5 by `actionId`, cleared on the first state showing a new accepted order |
| `powerSupply` | Fixed `0`, `false`, as the contract says. Not displayed by the station |
| `operatingMode` | No fresh `OrderState` (over 3 s), `ModeState` `STARTING`, `TRANSITIONING` or `STOPPING`: `STARTUP`. `ModeState` `LINE`, `layer_ready`, `PanelState.valid` and `mode_auto`: `AUTOMATIC`. Otherwise `MANUAL` |
| `errors` | Below |
| `safetyState.activeEmergencyStop` | `MANUAL` if `LineState.hold_cause == "estop"`, else `NONE` |
| `safetyState.fieldViolation` | Not (`MuxState.field_fresh` and `protective_clear`), or rear field not clear |

| errorType | From |
|---|---|
| `NOT_READY` | `OrderState.not_ready`, one `reason` per entry, when no order is active |
| Refusals in contract 6.3 | Bridge slot, fed by bridge checks and by `refusal_seq` from the job |
| `DEPARTURE_CANCELLED`, `TRIP_ABORTED` | `cancelled_reason`, `aborted_reason`, until the next accepted order |
| `START_REFUSED` | `start_refused_*`, with `actionId` `<orderId>:<ATT, MW or ME>` |
| `AGV_HOLD` | `LineState.state == HOLD` and `hold_cause != "station"`: `holdCause`, `code` |
| `AGV_FAULT` | `LineState.state == FAULT`: `code` |
| `CANCEL_REFUSED`, `NO_ORDER_TO_CANCEL`, `INVALID_INSTANT_ACTION` | Bridge, until the next accepted order |

Subscriptions: `/amr/line/order_state`, `/amr/line_state`, `/amr/mode_state`, `/amr/panel_state_ui`,
`/amr/mux_state`. Drop `OrderState` and `LineState` from another generation.

### 12.8 instantActions

`cancelOrder` only. Acts once per `actionId`: remembers the last 5 and repeats the stored result. Sends
`cancel` to the service, and fills `instantActionStates` from `OrderState.cancel_*`. `RUNNING` until the
job answers. Every other `actionType`: `FAILED`, `INVALID_INSTANT_ACTION`, with no service call. Retain
flag set: discard.

### 12.9 Offline behaviour

| Event | Bridge | Job |
|---|---|---|
| Wi-Fi or broker down | Flag cleared, nothing published, event `STATION_LINK_DOWN` on the change. Retries every 2 s | Not affected. The job has no network input. An active order finishes |
| Link back | `ONLINE`, `state`. Old buffered orders fail check 4 | |
| Bridge crash | Respawn in 5 s, `headerId` from 0, `STARTUP` until `OrderState` arrives | Not affected |
| Line layer restart | `STARTUP`, then `orderId ""` | New process, order lost |
| paho missing or credentials wrong | Logs, raises `STATION_LINK_DOWN`, exits, respawns | Not affected |

### 12.10 Authority limit

The bridge may publish only: MQTT, and `/amr/events`. It may call only `/amr/line/order`. It must not
touch `/amr/line_cmd`, `/amr/manual_command`, `/amr/line/clear`, `/amr/line/trip`, `/amr/line/at_home`,
`/amr/panel_state`, the lease or any mode request. A static test reads the node source and pins this
allow-list.

### 12.11 Tests first

Fakes: `FakeMqttClient` injected into `mqtt_link`, in the style of `tests/test_dio.py:22`. No test
needs a broker except the last group.

| File | Tests |
|---|---|
| `test_vda_order.py` | `test_the_contract_order_passes_for_each_machine[1..4]`; `test_each_check_refuses_with_its_error[...]` (malformed JSON, missing field, other serial, version 2, `released:false`, `orderUpdateId` 1, `nodePosition`, edge action, BTU node, two machines, `FLEET_CONTROL`); `test_a_retained_order_is_discarded_silently`; `test_a_stale_seen_header_is_refused`; `test_a_seen_header_inside_the_window_passes`; `test_same_id_same_content_is_ignored`; `test_same_id_other_content_is_reported`; `test_header_and_seen_header_do_not_count_as_content`; `test_the_machine_comes_from_the_nodes_not_the_order_id` |
| `test_vda_state.py` | `test_each_contract_example_is_reproduced[...]` for all 15 state examples in contract 6.2, built from a matching `OrderState`, comparing all but header fields and `driving` (R2 noted in the test); `test_loads_has_three_forms`; `test_power_supply_is_the_fixed_placeholder`; `test_a_missing_order_state_is_startup`; `test_a_hold_at_a_stop_is_not_an_agv_hold` |
| `test_vda_schema.py` | `importorskip("jsonschema")`; schema directory from env `VDA5050_SCHEMAS`, skip if unset. Every built message validates. Run it on the dev box with the station repo's `VDA5050/json_schemas` |
| `test_mapping_table.py` | Contract 6.1 coded as written, fed by a simulated trip from the job, expecting each call state in order. Same table the contract's validation used |
| `test_mqtt_link.py` | `test_will_is_set_before_connect`; `test_connect_order`; `test_offline_then_disconnect_on_shutdown`; `test_no_publish_while_disconnected`; `test_on_message_only_queues`; `test_header_ids_count_per_topic`; `test_topics_use_the_configured_serial` |
| `test_bridge_instant_actions.py` | `test_a_cancel_acts_once_per_action_id`; `test_results_for_each_situation[...]`; `test_any_other_action_is_refused[startPause,stopPause,trigger,factsheetRequest,stateRequest,initPosition]`; `test_last_five_kept_and_cleared_on_accept` |
| `test_bridge_authority.py` | `test_the_node_uses_only_its_allowed_names`; `test_no_literal_agv1_in_code`; `test_paho_is_imported_lazily` |
| `test_mosquitto_loop.py` | Skipped unless `mosquitto` is on the path and `AMR_MQTT_TESTS=1`. A real broker on loopback with the contract's ACL: `test_last_will_arrives_after_kill`; `test_no_offline_queue`; `test_retained_order_is_discarded`; `test_acl_refuses_a_wrong_user`; `test_order_after_reconnect_needs_a_fresh_state`. `test_retained_order_is_discarded` publishes with the bridge disconnected, then reconnects: discarded, no report. Add `test_a_retained_publish_while_connected_is_a_normal_order`: flag clear on delivery, needs a fresh `seenStateHeaderId`. Add `test_the_watch_user_reads_and_cannot_publish` |

**Done when.** All pass, the mosquitto group included on a dev box, and the bridge runs against the sim
with messages checked by hand against contract section 6.2.

## 13. P6: alarms and documents

**Scope.** Everything in sections 17 and 18. Do this before any vehicle runs this code with the switch
on. Include the section 3.4 rewording.

**Files.** As listed in those sections.

**Behaviour.** None beyond catalogue text. Run `python3 -m agv_core.alarms --md` and paste it between the
markers in RUNBOOK section 4; run `--card` (RUNBOOK `:748-756`).

**Tests first.** `tests/test_alarms.py`: `test_station_codes_have_rows` (section 17).

**Done when.** `tests/test_alarms.py` passes, the owner has reviewed the section 3.4 wording and the new
warning text, and `tests/run_all.py` reports 886.

## 14. P7: sim end to end, deploy off, link test

**Scope.** Prove the whole chain in sim. Deploy with the switch off and show no change. Then prove on the
real vehicle that orders are refused while the lidar is absent.

**Files.** `amr_bringup/test/test_station_call_sim.py` (new, in the `AMR_SIM_TESTS=1` group of
`test_unified_sim.py`; I did not read that file in depth, so follow its pattern). The vehicle's
profile, for the steps below only. `tools/test_sender.py` belongs to the station plan: it reads the newest
`state` and publishes a chosen order, `cancelOrder` or a raw body, with a fresh `seenStateHeaderId` where one applies, under its own client
id and user `station`, and refuses a real broker without `--real`.

**Behaviour.** No new code. With the switch on and no lidar the real AGV must refuse every order and
every hand trip from HOME.

**Tests first (sim).** `test_a_full_call_in_sim`: real bridge, real job, `fake_panel_node`,
`fake_trolley_node`, loopback Mosquitto. Order; `TO_PICKUP`; `AT_PICKUP`; refused START with no trolley;
trolley set; `/sim/panel/press_start`; and so on to Closed. Then
`test_trolley_still_on_blocks_the_next_order`, `test_bridge_killed_mid_trip_finishes_the_trip`,
`test_layer_restart_shows_order_lost`, `test_wifi_style_broker_stop_mid_trip`.

**Vehicle steps (human, real AGV).**

| Step | Do | Pass |
|---|---|---|
| 1 | Deploy with `station.enabled: false`: `git pull`, `colcon build`, `validate.sh`, restart | `/params` shows the block. `ros2 node list` has no bridge or trolley node. `ros2 service list` has no `/amr/line/order` |
| 2 | Repeat the P0 trip by hand | Same result as P0. `Trolleys off` and `Released` still work |
| 3 | Run checks V8 to V13. Install paho and credentials. Broker running on the station PC | `validate.sh` passes |
| 4 | `station.enabled: true`, restart. Selector MANUAL at HOME: `NOT_AT_HOME` shows. Press At home, confirm READY. Selector AUTO, wait 5 s | `mosquitto_sub`, as user `watch`, on the station PC shows `ONLINE`, then `state` with `loads` omitted, `fieldViolation: true`, `NOT_READY` with `TROLLEY_UNKNOWN` and `REAR_FIELD_UNKNOWN`. `NOT_AT_HOME` has cleared |
| 5 | From the station PC, `tools/test_sender.py --real` sends a contract order with a current `seenStateHeaderId`. This is the first time the real station sends to the real AGV | `DEPARTURE_REFUSED`, reason `TROLLEY_UNKNOWN`. **The AGV does not move, no horn.** Person at the E-stop throughout |
| 6 | `tools/test_sender.py`: same order with an old `seenStateHeaderId`. Then a retained order published with the bridge stopped, bridge restarted. Then a retained order with a fresh `seenStateHeaderId` and the bridge connected. Clear the retained message from the broker after each | `STALE_ORDER`. Discarded, no report. Handled as a normal order: `DEPARTURE_REFUSED`, `TROLLEY_UNKNOWN` |
| 7 | `mosquitto_pub` with a wrong password | Refused by the broker |
| 8 | Wi-Fi off at the AP. `tools/test_sender.py` sends one order at the start of the outage. Wi-Fi back after 8 to 12 s, above the 5 s window and below the will time | `STALE_ORDER`, with the order seen in the bridge log. Vehicle unaffected |
| 8b | Wi-Fi off at the AP for 30 s, with one order sent as in step 8 | Last will on the station PC about 15 s after silence. Vehicle unaffected. `ONLINE` on return. The order never arrives |
| 9 | Physical START at HOME with a local call | Refused, `TROLLEY_UNKNOWN` |
| 10 | CPU load per `manuals/cpu-load-plan.md`. Compile time of a route | Recorded |
| 11 | `station.enabled: false`, restart | Back to step 1's result |

**Done when.** The sim tests pass, all vehicle steps pass, the owner has seen step 5, and the switch is off
again.

## 15. P8 and P9: hardware and the first real departure

### 15.1 P8: rear scanner fitted (owner, human, real AGV)

**Scope.** O1 and O2 decided and built by the owner and safety engineer.

**Files.** Vehicle profile `rear` block and frame args, `nanoscan3_rear.yaml` address values.

**Behaviour.** No new code. `trolley_node` and the interlocks from P2 and P4 now see real data.

**Steps.**

1. Safety engineer: fields, monitoring cases, FX3, wiring, verification report and SISTEMA update. This rear scanner chain verification is a named prerequisite of O3. Include the rear case gate (3.3): either the driver reports the active case, or the proof that no towing case can stay selected with no trolley. Software is not involved.
2. Network. `enp3s0` has one peer (`alpha-setup.md:173`), and there are only two wired LANs. A second scanner needs a switch or NIC, and none is documented. Pick a sensor IP and a host UDP port.
3. Set `rear.source: "scanner"`, the measured frame args, and `rear_lidar` true. Restart with `station.enabled: false`.
4. Check `/rear/scan`, `/rear/output_paths`, and that the front topics did not move. Check CPU (`manuals/cpu-load-plan.md`, the N97 thermal limit).
5. Run the calibration table in 11.3. Write the values into the profile.
6. With the station PC not sending, `station.enabled: true`. Local trip by hand: each interlock refused and passed with a real trolley. Cable pull gives `UNKNOWN` and refusal. Killing `trolley_node` gives unknown within 0.5 s, and a full debounce after it respawns.
7. Measure the time from power request to torque, over at least ten warnings from standby. Replace the `order_torque_wait_s` placeholder with that time plus a margin the safety engineer accepts. Check `HOME_STILL_M` against encoder noise at rest.
8. Update `amr_description/config/footprint.yaml` only if the owner decides to. Nothing in this plan needs it.

**Tests first.** `test_urdf.py` and `test_launch_layers.py` from P4, on the real profile.

**Done when.** Each row of the calibration table is recorded, each interlock has been seen refusing, the
rear case gate is met, `order_torque_wait_s` is a measured value, and the owner accepts the verification
report.

### 15.2 P9: first real automatic departure (named approval)

**Scope.** The first time the real AGV moves with no START. This is a named approval by the owner, recorded
in this file with date and name. O1, O2 and O3 must be closed. The new manual text must be issued to
everyone working at HOME.

**Files.** This file, for the approval record. No code, unless a step fails.

**Behaviour.** As P2 and contract section 8 describe. `station.enabled` true.

**Tests first.** The sim test `test_a_full_call_in_sim` passes on the build deployed. P7 steps 4 to 8b are
repeated through `tools/test_sender.py` with the lidar fitted, a trolley hitched and nobody in the zone, so
every order is refused with `TROLLEY_PRESENT`, and they pass. Step 6's retained order with the bridge connected is left out: it is never run once the lidar is fitted. Neither `tools/test_sender.py` nor
`mosquitto_pub` is used to start the real AGV moving.

**Steps (witnessed).** Hardware groups G and J are the single acceptance list for this phase. This plan keeps
no separate table, so the two cannot disagree. All of their safety rules apply: one person at the E-stop,
nobody in the bay except the test team, a roped stand-in target and never a person in a field while the AGV
can move.

| Hardware | What it proves here |
|---|---|
| G1 to G4 | The first departure in stages: E-stop pressed, wheels lifted, then on the floor. Every start is from a real button. G2's expected result is outcome (a), one horn cycle only: `DEPARTURE_CANCELLED`, `HOLDOFF`, `TORQUE_TIMEOUT` latched until a physical Reset edge. G3 is the first send that can turn the wheels |
| G5 to G8 | Every refusal, every `SETTLING` restart and every cancelled warning, including the 180 degree pivot at HOME (no person in front, someone ready at the E-stop) |
| J5 to J8, then J1 to J3 | The hazard at the hitch is rehearsed before the queue tests. **No person goes to the hitch with a call waiting and the selector in AUTO until the J rehearsal has passed** |

**Done when.** Groups G and J have passed, and the owner records the approval and any limits on use. Only then
may `station.enabled` stay on.

## 16. Test plan

**Proof that off is unchanged.**

| Proof | Test |
|---|---|
| Every existing test passes, and no existing test body changes except those listed under "Pinned tests that do change" below | All of section 3.4 and the rest of the suites. `git diff` shows no other change inside an existing test function |
| Trip traces identical to `c41afb3` | `test_the_one_call_trip_matches_the_baseline`, `test_the_two_call_trip_matches_the_baseline` |
| A waiting call never moves | `test_a_waiting_call_with_no_start_stays_idle`, `test_a_waiting_call_stays_idle_after_reset_clear_and_a_selector_return` |
| No new surface | `test_off_the_node_has_no_order_service_or_topic`, `test_off_base_launches_todays_nodes`, `test_off_an_order_is_refused_and_nothing_is_latched` |
| Lidar ignored | `test_off_the_lidar_is_never_read` |
| Profile default | `test_config` check 10 |
| On the floor | P7 steps 1 and 2 |

**Static pin: `test_the_order_entry_has_one_call_site`** (AST over `job.py`):

- `_order_start` is called exactly once, inside `tick`, under `if self.state in (IDLE, DONE)`.
- `_begin_premove` is called from exactly `_start`, `_order_start`, `_hold_tick` and `_station_tick`.
- `_order_start` passes the literal `"start"`.
- `line_follow_node.py` sets `start_edge` only from `start_edge_t`.
- `_order_req` is read only in `_order_take`.

**New test files.** Named in their phases:

| Package | File |
|---|---|
| `amr_line` | `test_station_off.py`, `test_station_order.py`, `test_station_interlocks.py`, `test_line_node_station.py` |
| `amr_base` | `test_trolley_detect.py` |
| `amr_station` | `test_vda_order.py`, `test_vda_state.py`, `test_vda_schema.py`, `test_mapping_table.py`, `test_mqtt_link.py`, `test_bridge_instant_actions.py`, `test_bridge_authority.py`, `test_mosquitto_loop.py` |
| `amr_bringup` | `test_station_call_sim.py` |
| `amr_web` | `test_station_web.py` |

**Pinned tests that do change.**

| Test | Change | Phase |
|---|---|---|
| `tests/test_mission.py:234` | `TRIP_CALLS == 1` | P0 |
| `amr_web/test/test_teach_page.py:35` | `trip_calls == 1` | P0 |
| `amr_web/test/test_teach_page.py:36` | `live` follows the repo profile, only when O4 lands | P0 or later |
| `tests/test_config.py` | 11, then 6 more checks | P1, P4 |
| `amr_base/test/test_wire_contract.py` | New pinned test added; the existing ones stay | P3 |
| `amr_bringup/test/test_launch_layers.py` | New tests added; existing ones stay | P3, P4, P5 |
| `amr_description/test/test_urdf.py` | Case for the `rear_lidar` arg | P4 |
| `tests/test_alarms.py` | New test; RUNBOOK block regenerated, not edited | P2, P6 |

**`EXPECTED_CHECKS` (`tests/run_all.py:154`).** Raise it deliberately, with a dated comment in the history
above it. The expected path:

| After | Value | Comment |
|---|---|---|
| Today | 869 | Read from the file. The suite was not run for this plan; this PC has only a Store Python stub as `python` |
| P0 | 869 | A check edited, none added |
| P1 | 880 | `+ 11 (date): station plan P1, test_config - the station block` |
| P4 | 886 | `+ 6 (date): station plan P4, test_config - the rear block` |

If `run_all` reports another number, find out why. Do not paste the number in.

**How to run.** `python3 tests/run_all.py`. In `amr_ws`: `colcon build --symlink-install`, then
`env AMR_SIM_TESTS=0 ROS_DOMAIN_ID=89 python3 -m pytest -q src/*/test` (`alpha-setup.md:706`, second-hand).
`AMR_SIM_TESTS=1` for the sim group. `AMR_MQTT_TESTS=1` for the broker group.

## 17. New alarms and events

Add rows in `agv_core/alarms.py` `_rows()` (`:56`), with `CLEARS` from `:38`. `PAYLOAD_UNCONFIRMED` (`:216`)
is the template. All text is a state, then one imperative.

| Code | Severity | clears_by | Title | Action | Phase |
|---|---|---|---|---|---|
| `TROLLEY_AT_PIVOT` | warn | `start_button` | Stopped before the U-turn: a trolley is detected or unknown | Check the trolley is off and clear, then press Start. | P2 |
| `START_REFUSED_NO_TROLLEY` | info | `start_button` | Start refused: no trolley detected | Hitch the trolley, then press Start. | P2 |
| `START_REFUSED_TROLLEY_ON` | info | `start_button` | Start refused: a trolley is still detected | Unhitch the trolley and move it clear, then press Start. | P2 |
| `TROLLEY_UNKNOWN` | warn | `auto` | Trolley state unknown | Call maintenance if it does not clear. | P2 |
| `ORDER_DEPARTING` | info | `auto` | Leaving HOME for a station call | Stay clear of the vehicle. | P2 |
| `ORDER_REFUSED` | info | `auto` | A station order was refused | Check the reason on the Run page. | P2 |
| `DEPARTURE_CANCELLED` | warn | `auto` | Automatic departure cancelled | Clear the cause. The station can send it again. | P2 |
| `ORDER_ABORTED` | warn | `operator` | A station trip was aborted | Bring the vehicle to HOME by hand. | P2 |
| `STATION_LINK_DOWN` | info | `auto` | No link to the station | Check Wi-Fi and the station PC. The vehicle keeps working. | P5 |
| `REAR_SCANNER_SILENT` | warn | `auto` | No data from the rear scanner | Call maintenance. | P4 |

- New hold cause: `HOLD_CODES["trolley"] = "TROLLEY_AT_PIVOT"` (`alarms.py:455`). Otherwise it falls back to `WAITING_FOR_PREREQ` (`:478`).
- `PAYLOAD_UNCONFIRMED` stays for the switch-off path.
- `test_every_code_emitted_by_a_node_has_a_catalogue_row` does not catch `self._event("CODE", ...)` in `line_follow_node.py`: none of `CODE_PATTERNS` (`tests/test_alarms.py:19-32`) matches that form. So add `test_station_codes_have_rows`, with this table as an explicit list.
- Regenerate RUNBOOK section 4 (`test_runbook_section_4_matches_the_catalogue` compares it byte for byte) and the card.
- Each row also needs an engineer's `hint` (`test_the_catalogue_is_well_formed`). Write it with the code.
- Regenerate in every phase that adds a row, not only in P6.
- Add the operator-facing ones to the hand-written table in `documentation/operation-manual/operation-manual.md` section 14 (`:905`).

## 18. Documents to update

| Document | Change |
|---|---|
| `manuals/site-layout-103.md` | Decisions below. Section 3 flow (`:78-94`). Section 4 "Both U-turns have a payload guard" (`:136-143`). Section 5 rows (`:153-154`) |
| `README.md` | Safety model (`:40-47`): the exception, MQTT, broker. Tests row. New package in the tree if listed |
| `amr_ws/RUNBOOK.md` | `:7`, `:16`, `:21-22`, `:106`, `:131`. New section: station calling, switch on and off, how to read `NOT_READY`, what to do after an aborted call. Section 4 regenerated |
| `amr_ws/README.md` | New package and node |
| `alpha-setup.md` | Section 5.2 paho row and install. Wi-Fi gateway at `:174`, `:451`, `:456` after check V9. Broker address note |
| `documentation/operation-manual/operation-manual.md` | Below |
| `documentation/operation-manual/operation-manual-doc.md`, `.docx` | Parallel copies (not opened). Keep in step by the manual's own process. This manual is in a TÜV SÜD preliminary check (`operation-manual-context.md:12`), so the owner decides when a new revision goes out |
| `documentation/operation-manual/operation-manual-context.md:253,349,365` | Rear scanner: planned, not fitted, field open |
| `manuals/tracked-plan-4-position-engine.md:20,21,62` | F7 and F8 superseded, pointing here |
| `manuals/tape-localization-runbook.md:25`, section 4.2 | Exception; one call a trip |
| `manuals/external-features-survey.md:885-887` | VDA 5050 item: now a subset, why, not compliant |
| `amr_ws/deploy/validate.sh` | P5 |
| `amr_line/line_follow_node.py:1-15` | Module docstring, the stale shadow text |

**`manuals/site-layout-103.md` decisions.** Do not delete rows. Mark what they are replaced by, with the date.

| # | New text |
|---|---|
| D3 | Unchanged. It still bounds the setting |
| D4 | Replaced 2026-11-05: one machine per trip (`trip_calls` 1). No waiting for a second call. No batching |
| D5 | Replaced 2026-11-05: MRU calls come from buttons on the machines, through the station PC. BTU calls stay on the AGV's display. Run → Calls stays. Applies only with `station.enabled` |
| D10 | Replaced 2026-11-05, as an assumption: a rear lidar will detect the trolley and carry the rear safety field. Not fitted yet. Trolley detection is not personnel protection. Applies only with `station.enabled`; with it off, the confirmations stand |
| D13 | AGV-01 only for now, no collision or priority logic. Topics and profile are per AGV (`manuals/station-call-plan.md` section 20) so a second AGV is not closed off |
| D14 | Replaced 2026-11-05 for one case: with `station.enabled`, an accepted station order leaves HOME by itself, only from HOME, only in AUTO, once, through the 2 s horn, and with no trolley and the rear field clear. Everything else still needs a physical Start. Remove the citation of `CLAUDE.md`, which is not in the repo |
| D18 | `trip_calls` 1 |

**Operation manual.**

| Section | Change |
|---|---|
| 3.3, 3.4 (`:285`, `:297`, `:310`) | Rear scanner: open items stay open until O1, O2. No values invented |
| 9 | Station calling described as an operating state |
| 10.4 (`:710-738`) | Lidar interlocks: START refused with and without a trolley. Confirmation steps 6 and 5 apply only with station calling off. `:738` pivot sentence |
| 10.5 (`:742-746`) | Second path: leaving by a station call |
| 10.7 (`:768-774`) | "then the vehicle continues" is wrong for a site trip: RESET aborts the trip (O13). State it: release, RESET, then recover by hand. Wording follows the owner's answer to O13 |
| New 10.x | Station calls: what the operator sees, the three START presses, what to do on an aborted call, and pressing At home again, looking at the vehicle, after any wheel movement at HOME |
| 14 (`:905`) | New rows |
| [REVIEW] 4 (`:1107`) | Owner's answer to `operation-manual-context.md:365` |

New warning, for 10.5 and the sign at HOME. It goes out only with O3:

> **WARNING — The vehicle can start from HOME with nobody at the panel.**
> With station calling switched on, a call from a machine can send the vehicle away from HOME with no one pressing **START**. The horn sounds for 2 s, then the vehicle moves off.
> - With the selector in **AUTO** at HOME, treat the vehicle as about to move.
> - Before you work on or around the vehicle at HOME, set the selector to **MANUAL**.
> - The vehicle can leave a few seconds after you move a trolley clear, step out of a scanner field or release a block from the web page, or a few seconds after it arrives home. Do not stay in front of it or behind it.
> - At every other stop it waits for **START**.

## 19. Security

**What exists today.** `README.md:40-41`: no authentication on port 5001, and anyone who can reach it can
drive the vehicle under MANUAL. Over the same network: Clear, calls, At home. `alpha-setup.md:174`: all on
`agv_field`, one PSK.

**What this adds.** An order now moves the vehicle with nobody at the panel, so a network message is
worth more than before.

| Surface | Control | Residual |
|---|---|---|
| Broker on the station PC | Bound to 192.168.2.5, `allow_anonymous false`, password file and ACL outside both repos (contract section 1) | Station plan |
| Topics | ACL per user: AGV only its own `order`, `instantActions` in; `state`, `connection` out. `watch` reads all topics and publishes nothing (contract section 1) | Anyone with the `watch` password can read orders, as anyone with the PSK can |
| Traffic | Plain MQTT on TCP 1883. Passwords and orders are readable by anyone with the Wi-Fi PSK | Owner accepts or adds TLS later. Protect the PSK |
| Vehicle | The bridge makes one outbound connection. No new listener | |
| `/amr/line/order` | Loopback DDS only (`config/cyclonedds-local.xml:12`). Reachable only by a local user | Shell access to the vehicle means full control, as today |
| `/api/line/at_home` | Unauthenticated, and now part of a departure precondition. Gated on MANUAL with the switch on (O11) | |
| Port 5001 | No web route reaches orders (`test_no_web_route_reaches_the_order_service`). With the switch on, Clear is refused in FAULT, and Clear, local call cancel and mission selection restart `SETTLING` | A web action can abort a station trip, and can remove a block on a waiting order. It cannot skip the 5 s and the horn. Someone on the network can still jog under MANUAL, as today, which then needs At home again |
| Credentials on the vehicle | `station-mqtt.json`, mode 600, outside the repo | |
| Station hotspot | The broker's bind excludes it. Verify from a hotspot client | Station plan |

## 20. AGV 2

Traffic control is not built. These points keep it possible:

| Point | How |
|---|---|
| Topics | Built from `station.manufacturer` and `station.serial_number`. `agv2` is a profile change |
| Profile | `profiles/agv-02.json`. `load` requires the file name to match `profile_name` (`agv_core/config.py:1291`). Check 9 of `test_config` ties `serial_number` to it |
| Address | 192.168.2.30 (`alpha-setup.md:174`) |
| Broker | New user `agv2`, its own ACL lines (contract section 1) |
| Bridge | One per vehicle, in that vehicle's base launch. No shared state |
| Mission | `AGV-02` has its own site mission and home bay (D1, D2, D11). Machine lookup goes through the mission, so nothing assumes MRU1 to MRU4 |
| Order shape | Fixed in `vda_order.py` from the mission's home and attach |
| Traffic control later | Could use `released: false` horizons or a zone lock on the station. Refused today with `VALIDATION_FAILURE`. Changing that is a contract change |
| Hard-coded `HOME-N` | `canonical_order` reads `site["HOME"]`, never a literal |

## 21. Checks on the vehicle

The repo cannot show these. Do them on the AGV (`gvipc-evo-01`, `192.168.2.20`).

| # | Check | How | Why, and what it blocks |
|---|---|---|---|
| V1 | Commit and local edits | `git status`, `git log -1` in `~/agv_can` | The vehicle's copy may differ. P0 |
| V2 | HOME-N taught, marks present | Teach page, or `<state_dir>/teach/<map>-rev<R>/stations.json`. Last record (2026-10-25): "HOME-N itself is not taught yet", M1, M8 to M18 assigned, graph g1 (`documentation/layout-reference/tape-graph-g1/README.md:38-39`, second-hand; `tracked-plan-4:218-230`) | Compile refuses without it (`trip_route.py:148-149`). P0 |
| V3 | Active graph | `cat ~/.amr/line_graph.json` | Which graph is live. P0 |
| V4 | `tape_loc.live`, `site_mission` in the vehicle's profile | `grep` the file; `/params` | Repo says `false`, `site-103`. `AGV_PROFILE` is unset, so the default applies (`alpha-setup.md:690-693`). P0 |
| V5 | `amr_interfaces` built with trip fields | Run page shows Calls, not "rebuild amr_interfaces" (`run.html:180-181`) | P0 |
| V6 | E2 laps and E3 recorded | `tracked-plan-4:202-204` says pending | P0 |
| V7 | J-R2E position, C-BTU teaching | `tracked-plan-4:244-247` (second-hand) | MRU route passes J-R2E; BTU not confirmed. P0 for MRU |
| V8 | Broker reachable | `ip route get 192.168.2.5` uses `wlp1s0`; `nc -zv 192.168.2.5 1883` | `usb0` is the first default route, but the /24 on Wi-Fi should win. P7 |
| V9 | Gateway address | `nmcli -g ipv4.gateway con show agv-net` | `alpha-setup.md` says 192.168.2.10, now DIO 1. The AP was noted as 192.168.2.254 on 2026-11-05. A wrong gateway should not affect the /24, but it is wrong. Owner to pick the AP or none. P7 |
| V10 | Clock | `timedatectl`, `chronyc tracking` | Sources are Ubuntu defaults, and the floor has no internet. Timestamps are for logs only (contract section 1), so a wrong clock must not block anything. Record the offset so logs can be lined up. Do not add a clock comparison. P7 |
| V11 | Wi-Fi rejoin | `systemctl is-enabled agv-wifi-reconnect` | It is enabled by hand (`install.sh:53`). P7 |
| V12 | Wi-Fi along the route | Walk it, or watch the link during P0 | A drop must not matter; confirm by P7 step 8 |
| V13 | paho, pip, tether | `python3 -c "import paho.mqtt.client"`; `ip a show usb0` | Code map: presence unknown. P7 |
| V14 | Scanner model and static inputs, front and rear | Label and Safety Designer (humans) | O1. P8 |
| V15 | Free port for a second scanner | `enp3s0` has one peer | P8 |
| V16 | Hitch position, trolley shapes, scan plane | Measure | No geometry in the repo; `amr_description/config/footprint.yaml` (second-hand) is a placeholder without a trolley. P8 |
| V17 | Selector polarity | `io-mapping.md` "Things the sheets do not settle" | The panel already reads it, so this is only a check. P7 |
| V18 | Whether the rear driver exposes the active monitoring case and a scan counter | `ros2 topic echo` on `/rear/output_paths` and its other topics. The driver is not in this repo | Decides the rear case gate route (3.3) and the frozen-scan residual (11.3). P4, P8 |

---

The contract follows, word for word. It is the interface both repos build to. Its validation report is
not part of it and is left out.

## Interface contract

**Contract version 1.2, 2026-11-11.** Between the station (`gvievo-sta`) and the AGV (`gvievo-01`).

**Changes from 1.1.** A pair order serves two MRU machines in one trip (sections 2, 5, 6.1, 7, 8, 10). The home node
is named by the site (section 2). MRU4 turns mid-line. Row 11's LED is solid. A waiting call is kept through a link
loss, and an unseen order is resent with the same orderId (sections 8 and 9). `station.no_trolley_run` is described
(section 7). A one-machine order is unchanged.

**Status.** This is a subset of VDA5050 3.0.0 over MQTT. It is not VDA5050 compliant and must not be called compliant. Section 10 lists what is missing and where it deviates. Buttons, trolley types, LEDs, the screen and the call list are outside this contract and stay on the station. The trolley type is never sent to the AGV.

### 1. Transport

**Broker.** Mosquitto on the station PC, MQTT 3.1.1, TCP `192.168.2.5:1883`, listener bound to that address only. Settings: `persistence false`, `allow_anonymous false`, a password file and an ACL file kept outside both repos.

**Topics.** `manufacturer` is `gvi`. `serialNumber` is `agv1`, and `agv2` for AGV 2. The `version` field in every message is `"3.0.0"`.

| Topic | Published by | Subscribed by | QoS | Retain |
|---|---|---|---|---|
| `vda5050/v3/gvi/agv1/order` | station | AGV | 0 | no |
| `vda5050/v3/gvi/agv1/instantActions` | station | AGV | 0 | no |
| `vda5050/v3/gvi/agv1/state` | AGV | station | 0 | no |
| `vda5050/v3/gvi/agv1/connection` | AGV, and the broker for the last will | station | 1 | yes |

AGV 2 uses the same four topics with `agv2` in place of `agv1`. No other topic exists.

**Clients.**

| Client id | Username | Address | May publish | May subscribe |
|---|---|---|---|---|
| `gvi-station` | `station` | 192.168.2.5 | `.../+/order`, `.../+/instantActions` | `.../+/state`, `.../+/connection` |
| `gvi-agv1` | `agv1` | 192.168.2.20 | own `state`, `connection` | own `order`, `instantActions` |
| `gvi-agv2` (later) | `agv2` | 192.168.2.30 | own `state`, `connection` | own `order`, `instantActions` |
| any test tool id, never a client id above | `watch` | the station PC (the firewall allows only the two AGV addresses from elsewhere) | nothing | `vda5050/v3/gvi/#`, read only, for test watchers and logs |

**Session.** Clean session true, keepalive 10 s, reconnect every 2 s. Neither client keeps an offline queue: a publish while disconnected is dropped.

**Connect order on the AGV.** (1) Connect with the last will set. (2) Subscribe. (3) Publish `ONLINE`. (4) Publish `state`. The last will is on the `connection` topic, QoS 1, retain true. To leave in an orderly way, publish `OFFLINE`, then disconnect. The station has no last will.

**Receive rules on the AGV.** An `order` or `instantActions` message with the MQTT retain flag set is discarded with no effect and no report.

**Clocks.** `timestamp` is UTC, `YYYY-MM-DDTHH:mm:ss.fffZ`, for logs only. No rule on either side compares a timestamp with a clock. `headerId` is per topic, +1 on each send, and restarts at 0 when the process restarts.

### 2. Order

The station builds an order from this table. The AGV owns its route, its junctions and its U-turn.

| Machine | Release node | Take node | U-turn, on the AGV only, never sent |
|---|---|---|---|
| MRU1 | `MW-1` | `ME-1` | mid-line `UT-MRU1` |
| MRU2 | `MW-2` | `ME-2` | mid-line `UT-MRU2` |
| MRU3 | `MW-3` | `ME-3` | mid-line `UT-MRU3` |
| MRU4 | `MW-4` | `ME-4` | mid-line `UT-MRU4` (since 2026-11-11, was the tape end `U-MRU`) |

**Home node.** The examples use `HOME-N`. The live site's home node is `HOME-N2`. The station takes it from its
config (`home_node`) and the AGV checks it against its own mission, so the name is the site's, not the contract's.

A one-machine order has exactly this shape, with `n` = 1 to 4:

| sequenceId | Item | Action |
|---|---|---|
| 0 | node `HOME-N` | none |
| 1 | edge `HOME-N:ATT` | none |
| 2 | node `ATT` | `waitForTrigger`, id `<orderId>:ATT` |
| 3 | edge `ATT:MW-n` | none |
| 4 | node `MW-n` | `waitForTrigger`, id `<orderId>:MW` |
| 5 | edge `MW-n:ME-n` | none |
| 6 | node `ME-n` | `waitForTrigger`, id `<orderId>:ME` |
| 7 | edge `ME-n:HOME-N` | none |
| 8 | node `HOME-N` | none |

**U-turn.** The U-turn lies inside edge `MW-n:ME-n`. There is no U-turn node or action. The AGV looks up how to turn in its own mission, so every turn looks the same on the wire.

**Pair order.** Two different MRU machines, `a` and `b`, where `a` is the closer one: its release comes first in circuit order (`MW-1`, `MW-2`, `MW-3`, `MW-4`), whoever called first. The AGV releases at both, turns, takes at `b`, then at `a`, and goes home. It stops at `a` twice. The shape is exactly:

| sequenceId | Item | Action |
|---|---|---|
| 0 | node `HOME-N` | none |
| 1 | edge `HOME-N:ATT` | none |
| 2 | node `ATT` | `waitForTrigger`, id `<orderId>:ATT` |
| 3 | edge `ATT:MW-a` | none |
| 4 | node `MW-a` | `waitForTrigger`, id `<orderId>:MW-a` |
| 5 | edge `MW-a:MW-b` | none |
| 6 | node `MW-b` | `waitForTrigger`, id `<orderId>:MW-b` |
| 7 | edge `MW-b:ME-b` | none |
| 8 | node `ME-b` | `waitForTrigger`, id `<orderId>:ME-b` |
| 9 | edge `ME-b:ME-a` | none |
| 10 | node `ME-a` | `waitForTrigger`, id `<orderId>:ME-a` |
| 11 | edge `ME-a:HOME-N` | none |
| 12 | node `HOME-N` | none |

In a pair the action id ends in the node id (`:MW-1`), because there are two releases and two takes. The U-turn lies inside edge `MW-b:ME-b`, at `b`'s turn point. Each machine gets one empty trolley and sends one full trolley, so at most two trolleys are towed, in a row, in any order. Which calls make a pair, and how long the station waits for a second call, is the station's business and outside this contract. The AGV never waits for or picks a second machine.

**Fixed values.** All nodes and edges are `released: true`. `orderUpdateId` is always 0. `waitForTrigger` is always `blockingType: "HARD"` with `triggerType: ["LOCAL"]`, and each one is one physical START press. No `nodePosition`, `trajectory`, descriptors or other optional fields are sent.

**orderId.** `MRUn-YYYYMMDDTHHMMSS` for one machine, `MRUa+MRUb-YYYYMMDDTHHMMSS` for a pair (closer machine first), from the station clock when the order is created. It is unique and opaque to the AGV, which reads the machines from the nodes. Only the station reads the machines out of it. A resend keeps the orderId (section 8). A new attempt, after `DEPARTURE_CANCELLED`, gets a new one.

**`seenStateHeaderId` (extension, not in the spec).** The `headerId` of the newest `state` the station has received. It proves freshness without clocks (section 8).

Order for MRU3:

```json
{
  "headerId": 12,
  "timestamp": "2026-11-05T01:15:31.200Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "seenStateHeaderId": 1042,
  "nodes": [
    {"nodeId": "HOME-N", "sequenceId": 0, "released": true, "actions": []},
    {"nodeId": "ATT", "sequenceId": 2, "released": true, "actions": [{"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "blockingType": "HARD", "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}]}]},
    {"nodeId": "MW-3", "sequenceId": 4, "released": true, "actions": [{"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "blockingType": "HARD", "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}]}]},
    {"nodeId": "ME-3", "sequenceId": 6, "released": true, "actions": [{"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "blockingType": "HARD", "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}]}]},
    {"nodeId": "HOME-N", "sequenceId": 8, "released": true, "actions": []}
  ],
  "edges": [
    {"edgeId": "HOME-N:ATT", "sequenceId": 1, "released": true, "actions": []},
    {"edgeId": "ATT:MW-3", "sequenceId": 3, "released": true, "actions": []},
    {"edgeId": "MW-3:ME-3", "sequenceId": 5, "released": true, "actions": []},
    {"edgeId": "ME-3:HOME-N", "sequenceId": 7, "released": true, "actions": []}
  ]
}
```

Order for MRU1 and MRU3, a pair:

```json
{
  "headerId": 12,
  "timestamp": "2026-11-11T03:15:01.200Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU1+MRU3-20261111T101500",
  "orderUpdateId": 0,
  "seenStateHeaderId": 1042,
  "nodes": [
    {"nodeId": "HOME-N", "sequenceId": 0, "released": true, "actions": []},
    {"nodeId": "ATT", "sequenceId": 2, "released": true, "actions": [{"actionId": "MRU1+MRU3-20261111T101500:ATT", "actionType": "waitForTrigger", "blockingType": "HARD", "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}]}]},
    {"nodeId": "MW-1", "sequenceId": 4, "released": true, "actions": [{"actionId": "MRU1+MRU3-20261111T101500:MW-1", "actionType": "waitForTrigger", "blockingType": "HARD", "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}]}]},
    {"nodeId": "MW-3", "sequenceId": 6, "released": true, "actions": [{"actionId": "MRU1+MRU3-20261111T101500:MW-3", "actionType": "waitForTrigger", "blockingType": "HARD", "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}]}]},
    {"nodeId": "ME-3", "sequenceId": 8, "released": true, "actions": [{"actionId": "MRU1+MRU3-20261111T101500:ME-3", "actionType": "waitForTrigger", "blockingType": "HARD", "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}]}]},
    {"nodeId": "ME-1", "sequenceId": 10, "released": true, "actions": [{"actionId": "MRU1+MRU3-20261111T101500:ME-1", "actionType": "waitForTrigger", "blockingType": "HARD", "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}]}]},
    {"nodeId": "HOME-N", "sequenceId": 12, "released": true, "actions": []}
  ],
  "edges": [
    {"edgeId": "HOME-N:ATT", "sequenceId": 1, "released": true, "actions": []},
    {"edgeId": "ATT:MW-1", "sequenceId": 3, "released": true, "actions": []},
    {"edgeId": "MW-1:MW-3", "sequenceId": 5, "released": true, "actions": []},
    {"edgeId": "MW-3:ME-3", "sequenceId": 7, "released": true, "actions": []},
    {"edgeId": "ME-3:ME-1", "sequenceId": 9, "released": true, "actions": []},
    {"edgeId": "ME-1:HOME-N", "sequenceId": 11, "released": true, "actions": []}
  ]
}
```

### 3. Connection messages

Online, retained:

```json
{
  "headerId": 0,
  "timestamp": "2026-11-05T00:58:02.100Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "connectionState": "ONLINE"
}
```

Orderly offline, retained:

```json
{
  "headerId": 1,
  "timestamp": "2026-11-05T09:30:00.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "connectionState": "OFFLINE"
}
```

Last will, set at connect, so its `headerId` and `timestamp` are old by the time it is delivered:

```json
{
  "headerId": 0,
  "timestamp": "2026-11-05T00:58:02.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "connectionState": "CONNECTION_BROKEN"
}
```

The station treats a missing retained message, after a broker restart, as not online.

### 4. instantActions

`cancelOrder` is the only instant action, and its `orderId` parameter is required. The rules are in section 9.

```json
{
  "headerId": 3,
  "timestamp": "2026-11-05T01:15:33.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "actions": [{"actionId": "cancel-MRU3-20261105T081530", "actionType": "cancelOrder", "blockingType": "NONE", "actionParameters": [{"key": "orderId", "value": "MRU3-20261105T081530"}]}]
}
```

### 5. How the AGV fills state

**Publishing.** Within 200 ms of a change to any field below, and at least once per second. Related changes go in one message.

| Field | Value |
|---|---|
| `orderId`, `orderUpdateId` | Current or last accepted order. `""` and 0 after a restart. Kept after the order ends. |
| `lastNodeId`, `lastNodeSequenceId` | Last order node reached at rest. `HOME-N` and 0 on acceptance. `""` and 0 after a restart. Not blanked by a mode change. |
| `nodeStates`, `edgeStates` | Nodes and edges not yet passed. A node and the edge leading to it go together on arrival. Both are empty when no order is active. |
| `loads` | Section 7. |
| `driving` | True when the commanded `v_mps` or `omega_rad_s` is not zero. This is commanded speed, not measured speed. False during the warning horn and any hold. |
| `actionStates` | The order's wait actions, three for one machine and five for a pair, kept until the next accepted order. `WAITING` until the AGV stops at the node. `RUNNING` while stopped there. `FINISHED` when the warning ends and the AGV starts to move, not at the press. `FAILED` if the order ends first. |
| `instantActionStates` | The last 5 cancel results. Cleared on an accepted order. |
| `powerSupply` | **`stateOfCharge: 0`, `charging: false`, fixed.** The AGV has no battery reading and no charge detection. The schema requires both fields, so these are placeholders. The station must ignore `powerSupply` and must not display it. |
| `operatingMode` | `AUTOMATIC` when the line layer is running, the panel is valid and the selector is AUTO. `STARTUP` while the supervisor is starting, changing layer or stopping. `MANUAL` in every other case. Other enum values are not used. |
| `errors` | Section 6.3. |
| `safetyState.activeEmergencyStop` | **`MANUAL` only while the hold cause is `estop`, otherwise `NONE`.** The AGV infers this from drive torque being gone with the field clear. It does not read the E-stop chain, so `NONE` does not prove that no E-stop is pressed. Display only. |
| `safetyState.fieldViolation` | True when a protective field is violated or its state is unknown. Display only. |

Not sent: `paused`, `maps`, `zoneSets`, `mobileRobotPosition`, `velocity`, `information`, and all other optional fields.

### 6. State and call states

#### 6.1 Mapping rule

The station runs this table on every `state` message whose `operatingMode` is not `STARTUP`. `O` is the call's current orderId. ATT, MW and ME are the `actionStatus` of `O:ATT`, `O:MW` and `O:ME`. In a pair, each of the two calls runs the table on its own, with `O:MW-n` and `O:ME-n` of its own machine as MW and ME, and `O:ATT` shared. The first matching row wins. Each row reads one message only, so a lost QoS 0 message can delay a call state but cannot make it wrong. "Shown" is set and saved the first time `state.orderId` equals `O`.

| # | Condition | Call state | What happened | LED |
|---|---|---|---|---|
| 1 | `orderId != O`, not shown | QUEUED | No order sent, or not yet accepted | blink |
| 2 | `orderId != O`, shown | Aborted | AGV restarted and lost the order | off |
| 3 | `nodeStates` empty, `lastNodeSequenceId == 8`, or `== 12` for a pair | Closed | AGV reached home | off |
| 4 | `nodeStates` empty, `errors` has `DEPARTURE_CANCELLED` for `O` | QUEUED with a new orderId, same queue place | Warning at home was cancelled, AGV never moved | blink |
| 5 | `nodeStates` empty, any other case | Aborted | Trip ended early | off |
| 6 | ME is `FINISHED` | RETURNING | Third START passed, AGV moving | off |
| 7 | ME is `RUNNING` | AT_ATTACH | Stopped at `ME-n`, waiting for full trolley and START | off |
| 8 | MW is `FINISHED` | TURNING, or AWAY (row 13) for the closer machine of a pair | Second START passed, moving through the U-turn | off |
| 9 | MW is `RUNNING` | AT_RELEASE | Stopped at `MW-n`, waiting for trolley removal and START | off |
| 10 | ATT is `FINISHED` | TO_MACHINE | First START passed, AGV left pickup | solid |
| 11 | ATT is `RUNNING` | AT_PICKUP | Stopped at `ATT`, waiting for trolley and START | solid |
| 12 | any other case | TO_PICKUP | Accepted, warning horn or driving to `ATT` | blink |
| 13 | (in row 8) the closer machine of a pair, MW is `FINISHED` | AWAY | Released here, AGV serving the other machine, back later for the full trolley | off |

**A pair, call by call.** `a` is the closer machine, `b` the farther one.

| AGV reports | Call for `a` | Call for `b` |
|---|---|---|
| ATT `WAITING`, then `RUNNING` | TO_PICKUP, AT_PICKUP | TO_PICKUP, AT_PICKUP |
| ATT `FINISHED` | TO_MACHINE | TO_MACHINE |
| `O:MW-a` `RUNNING` | AT_RELEASE | TO_MACHINE |
| `O:MW-a` `FINISHED` | AWAY | TO_MACHINE |
| `O:MW-b` `RUNNING`, then `FINISHED` | AWAY | AT_RELEASE, then TURNING |
| `O:ME-b` `RUNNING`, then `FINISHED` | AWAY | AT_ATTACH, then RETURNING |
| `O:ME-a` `RUNNING`, then `FINISHED` | AT_ATTACH, then RETURNING | RETURNING |
| `nodeStates` empty, `lastNodeSequenceId == 12` | Closed | Closed |
| `nodeStates` empty, any other sequence, 8 included | Aborted, both | Aborted, both |
| `nodeStates` empty, `DEPARTURE_CANCELLED` for `O` | QUEUED, both, and the next send has a new orderId | |

The two calls of a pair end together: one aborted trip is one abort for both.

The LED going off at arrival at the machine (row 9) is an assumption. See section 11.

**Refused START.** The action stays `RUNNING`, so the call state does not change. `errors` gains `START_REFUSED`, published at once and cleared by the next START press. The station shows the reason. A START that passes but whose warning is then cancelled reports the same way, with reason `WARNING_CANCELLED`.

**Holds while moving.** A field stop or other hold does not change the call state. The station shows the `AGV_HOLD` error and `fieldViolation` beside it.

**No fresh state.** The call state freezes and the screen shows "AGV link lost". When state returns, the table catches up, even as far as Closed.

**Aborted.** The call closes as aborted and leaves the open list. The station does not retry, and the machine's button is live again. The AGV may be anywhere, may be holding a trolley, and is recovered by hand. It is not free until its own checks pass at home.

**Cancelling.** For a call the station has marked cancelling (section 9), including one saved that way across a restart, the station first looks in `instantActionStates` on each fresh `state`. If `cancel-O` has a final status, that result applies as in section 9 and the table is not run. The "Cancelled" example in 6.2 therefore deletes the call. Without the cancelling mark, the same message is row 5.

**Station restart.** The table reads the same after a restart. `DEPARTURE_CANCELLED` stays until the next accepted order, so a saved call with `O` that finds it is row 4, not row 5: requeued with a new orderId, same queue place.

**Examples.** The examples in 6.2 are for one machine. A pair reports the same fields, with five wait actions.

#### 6.2 State at each stage

Each message is the complete message. Values that vary in real use are the header fields and `driving`. `NOT_READY` also varies: `SETTLING` is present for 5 s after each event listed in section 8, and an example shows it only where its stage always starts one.

**QUEUED, AGV free:**

```json
{
  "headerId": 1042,
  "timestamp": "2026-11-05T01:15:31.010Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "",
  "orderUpdateId": 0,
  "lastNodeId": "",
  "lastNodeSequenceId": 0,
  "nodeStates": [],
  "edgeStates": [],
  "loads": [],
  "driving": false,
  "actionStates": [],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**QUEUED, AGV not free (rear lidar not fitted or data stale):**

```json
{
  "headerId": 1050,
  "timestamp": "2026-11-05T01:15:39.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "",
  "orderUpdateId": 0,
  "lastNodeId": "",
  "lastNodeSequenceId": 0,
  "nodeStates": [],
  "edgeStates": [],
  "driving": false,
  "actionStates": [],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [{"errorType": "NOT_READY", "errorLevel": "WARNING", "errorReferences": [{"referenceKey": "reason", "referenceValue": "TROLLEY_UNKNOWN"}, {"referenceKey": "reason", "referenceValue": "REAR_FIELD_UNKNOWN"}]}],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": true}
}
```

**QUEUED, order refused (a race: the station sent it just before seeing `NOT_READY`):**

```json
{
  "headerId": 1051,
  "timestamp": "2026-11-05T01:15:39.300Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "",
  "orderUpdateId": 0,
  "lastNodeId": "",
  "lastNodeSequenceId": 0,
  "nodeStates": [],
  "edgeStates": [],
  "driving": false,
  "actionStates": [],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [
    {"errorType": "NOT_READY", "errorLevel": "WARNING", "errorReferences": [{"referenceKey": "reason", "referenceValue": "TROLLEY_UNKNOWN"}, {"referenceKey": "reason", "referenceValue": "REAR_FIELD_UNKNOWN"}]},
    {"errorType": "DEPARTURE_REFUSED", "errorLevel": "WARNING", "errorReferences": [{"referenceKey": "orderId", "referenceValue": "MRU3-20261105T081530"}, {"referenceKey": "orderUpdateId", "referenceValue": "0"}, {"referenceKey": "reason", "referenceValue": "TROLLEY_UNKNOWN"}]}
  ],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": true}
}
```

**TO_PICKUP (warning horn, `driving` becomes true after 2 s):**

```json
{
  "headerId": 1043,
  "timestamp": "2026-11-05T01:15:31.300Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "HOME-N",
  "lastNodeSequenceId": 0,
  "nodeStates": [
    {"nodeId": "ATT", "sequenceId": 2, "released": true},
    {"nodeId": "MW-3", "sequenceId": 4, "released": true},
    {"nodeId": "ME-3", "sequenceId": 6, "released": true},
    {"nodeId": "HOME-N", "sequenceId": 8, "released": true}
  ],
  "edgeStates": [
    {"edgeId": "HOME-N:ATT", "sequenceId": 1, "released": true},
    {"edgeId": "ATT:MW-3", "sequenceId": 3, "released": true},
    {"edgeId": "MW-3:ME-3", "sequenceId": 5, "released": true},
    {"edgeId": "ME-3:HOME-N", "sequenceId": 7, "released": true}
  ],
  "loads": [],
  "driving": false,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "WAITING"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "WAITING"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "WAITING"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**AT_PICKUP:**

```json
{
  "headerId": 1101,
  "timestamp": "2026-11-05T01:16:40.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "ATT",
  "lastNodeSequenceId": 2,
  "nodeStates": [
    {"nodeId": "MW-3", "sequenceId": 4, "released": true},
    {"nodeId": "ME-3", "sequenceId": 6, "released": true},
    {"nodeId": "HOME-N", "sequenceId": 8, "released": true}
  ],
  "edgeStates": [
    {"edgeId": "ATT:MW-3", "sequenceId": 3, "released": true},
    {"edgeId": "MW-3:ME-3", "sequenceId": 5, "released": true},
    {"edgeId": "ME-3:HOME-N", "sequenceId": 7, "released": true}
  ],
  "loads": [],
  "driving": false,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "RUNNING"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "WAITING"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "WAITING"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**AT_PICKUP, START refused (no trolley detected):**

```json
{
  "headerId": 1130,
  "timestamp": "2026-11-05T01:17:05.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "ATT",
  "lastNodeSequenceId": 2,
  "nodeStates": [
    {"nodeId": "MW-3", "sequenceId": 4, "released": true},
    {"nodeId": "ME-3", "sequenceId": 6, "released": true},
    {"nodeId": "HOME-N", "sequenceId": 8, "released": true}
  ],
  "edgeStates": [
    {"edgeId": "ATT:MW-3", "sequenceId": 3, "released": true},
    {"edgeId": "MW-3:ME-3", "sequenceId": 5, "released": true},
    {"edgeId": "ME-3:HOME-N", "sequenceId": 7, "released": true}
  ],
  "loads": [],
  "driving": false,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "RUNNING"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "WAITING"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "WAITING"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [{"errorType": "START_REFUSED", "errorLevel": "WARNING", "errorReferences": [{"referenceKey": "nodeId", "referenceValue": "ATT"}, {"referenceKey": "actionId", "referenceValue": "MRU3-20261105T081530:ATT"}, {"referenceKey": "reason", "referenceValue": "NO_TROLLEY"}]}],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**TO_MACHINE:**

```json
{
  "headerId": 1190,
  "timestamp": "2026-11-05T01:18:12.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "ATT",
  "lastNodeSequenceId": 2,
  "nodeStates": [
    {"nodeId": "MW-3", "sequenceId": 4, "released": true},
    {"nodeId": "ME-3", "sequenceId": 6, "released": true},
    {"nodeId": "HOME-N", "sequenceId": 8, "released": true}
  ],
  "edgeStates": [
    {"edgeId": "ATT:MW-3", "sequenceId": 3, "released": true},
    {"edgeId": "MW-3:ME-3", "sequenceId": 5, "released": true},
    {"edgeId": "ME-3:HOME-N", "sequenceId": 7, "released": true}
  ],
  "loads": [{"loadType": "TROLLEY", "loadPosition": "rear"}],
  "driving": true,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "WAITING"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "WAITING"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**AT_RELEASE:**

```json
{
  "headerId": 1320,
  "timestamp": "2026-11-05T01:20:30.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "MW-3",
  "lastNodeSequenceId": 4,
  "nodeStates": [
    {"nodeId": "ME-3", "sequenceId": 6, "released": true},
    {"nodeId": "HOME-N", "sequenceId": 8, "released": true}
  ],
  "edgeStates": [
    {"edgeId": "MW-3:ME-3", "sequenceId": 5, "released": true},
    {"edgeId": "ME-3:HOME-N", "sequenceId": 7, "released": true}
  ],
  "loads": [{"loadType": "TROLLEY", "loadPosition": "rear"}],
  "driving": false,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "RUNNING"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "WAITING"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**TURNING:**

```json
{
  "headerId": 1402,
  "timestamp": "2026-11-05T01:21:50.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "MW-3",
  "lastNodeSequenceId": 4,
  "nodeStates": [
    {"nodeId": "ME-3", "sequenceId": 6, "released": true},
    {"nodeId": "HOME-N", "sequenceId": 8, "released": true}
  ],
  "edgeStates": [
    {"edgeId": "MW-3:ME-3", "sequenceId": 5, "released": true},
    {"edgeId": "ME-3:HOME-N", "sequenceId": 7, "released": true}
  ],
  "loads": [],
  "driving": true,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "WAITING"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**AT_ATTACH:**

```json
{
  "headerId": 1440,
  "timestamp": "2026-11-05T01:22:30.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "ME-3",
  "lastNodeSequenceId": 6,
  "nodeStates": [{"nodeId": "HOME-N", "sequenceId": 8, "released": true}],
  "edgeStates": [{"edgeId": "ME-3:HOME-N", "sequenceId": 7, "released": true}],
  "loads": [],
  "driving": false,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "RUNNING"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**RETURNING:**

```json
{
  "headerId": 1510,
  "timestamp": "2026-11-05T01:23:40.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "ME-3",
  "lastNodeSequenceId": 6,
  "nodeStates": [{"nodeId": "HOME-N", "sequenceId": 8, "released": true}],
  "edgeStates": [{"edgeId": "ME-3:HOME-N", "sequenceId": 7, "released": true}],
  "loads": [{"loadType": "TROLLEY", "loadPosition": "rear"}],
  "driving": true,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "FINISHED"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**Closed (full trolley still hitched, so the AGV is not free yet):**

```json
{
  "headerId": 1690,
  "timestamp": "2026-11-05T01:26:40.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "HOME-N",
  "lastNodeSequenceId": 8,
  "nodeStates": [],
  "edgeStates": [],
  "loads": [{"loadType": "TROLLEY", "loadPosition": "rear"}],
  "driving": false,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "FINISHED"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [{"errorType": "NOT_READY", "errorLevel": "WARNING", "errorReferences": [{"referenceKey": "reason", "referenceValue": "TROLLEY_PRESENT"}, {"referenceKey": "reason", "referenceValue": "SETTLING"}]}],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**Aborted (selector left AUTO on the way to the machine):**

```json
{
  "headerId": 1250,
  "timestamp": "2026-11-05T01:19:15.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "ATT",
  "lastNodeSequenceId": 2,
  "nodeStates": [],
  "edgeStates": [],
  "loads": [{"loadType": "TROLLEY", "loadPosition": "rear"}],
  "driving": false,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "FINISHED"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "FAILED"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "FAILED"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "MANUAL",
  "errors": [
    {"errorType": "TRIP_ABORTED", "errorLevel": "CRITICAL", "errorReferences": [{"referenceKey": "orderId", "referenceValue": "MRU3-20261105T081530"}], "errorDescription": "Selector left AUTO during a trip"},
    {"errorType": "NOT_READY", "errorLevel": "WARNING", "errorReferences": [{"referenceKey": "reason", "referenceValue": "NOT_AUTO"}, {"referenceKey": "reason", "referenceValue": "NOT_AT_HOME"}, {"referenceKey": "reason", "referenceValue": "TROLLEY_PRESENT"}]}
  ],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

**Requeued (departure cancelled during the warning):**

```json
{
  "headerId": 1046,
  "timestamp": "2026-11-05T01:15:33.000Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "HOME-N",
  "lastNodeSequenceId": 0,
  "nodeStates": [],
  "edgeStates": [],
  "loads": [],
  "driving": false,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "FAILED"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "FAILED"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "FAILED"}
  ],
  "instantActionStates": [],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [
    {"errorType": "DEPARTURE_CANCELLED", "errorLevel": "WARNING", "errorReferences": [{"referenceKey": "orderId", "referenceValue": "MRU3-20261105T081530"}, {"referenceKey": "reason", "referenceValue": "PREREQUISITE"}], "errorDescription": "Front field not clear during the warning"},
    {"errorType": "NOT_READY", "errorLevel": "WARNING", "errorReferences": [{"referenceKey": "reason", "referenceValue": "PREREQUISITE"}, {"referenceKey": "reason", "referenceValue": "SETTLING"}, {"referenceKey": "reason", "referenceValue": "HOLDOFF"}]}
  ],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": true}
}
```

**Cancelled (cancelOrder accepted during the warning; the call is already gone from the station's list):**

```json
{
  "headerId": 1047,
  "timestamp": "2026-11-05T01:15:33.200Z",
  "version": "3.0.0",
  "manufacturer": "gvi",
  "serialNumber": "agv1",
  "orderId": "MRU3-20261105T081530",
  "orderUpdateId": 0,
  "lastNodeId": "HOME-N",
  "lastNodeSequenceId": 0,
  "nodeStates": [],
  "edgeStates": [],
  "loads": [],
  "driving": false,
  "actionStates": [
    {"actionId": "MRU3-20261105T081530:ATT", "actionType": "waitForTrigger", "actionStatus": "FAILED"},
    {"actionId": "MRU3-20261105T081530:MW", "actionType": "waitForTrigger", "actionStatus": "FAILED"},
    {"actionId": "MRU3-20261105T081530:ME", "actionType": "waitForTrigger", "actionStatus": "FAILED"}
  ],
  "instantActionStates": [{"actionId": "cancel-MRU3-20261105T081530", "actionType": "cancelOrder", "actionStatus": "FINISHED"}],
  "powerSupply": {"stateOfCharge": 0, "charging": false},
  "operatingMode": "AUTOMATIC",
  "errors": [{"errorType": "NOT_READY", "errorLevel": "WARNING", "errorReferences": [{"referenceKey": "reason", "referenceValue": "SETTLING"}]}],
  "safetyState": {"activeEmergencyStop": "NONE", "fieldViolation": false}
}
```

#### 6.3 Errors

Each error's references use exactly these keys. `errorDescription` is free text for the screen and is never used in logic.

| errorType | Level | Active | References |
|---|---|---|---|
| `NOT_READY` | WARNING | While no order is active and the AGV could not accept one | one `reason` per cause (section 8) |
| `VALIDATION_FAILURE`, `INVALID_ORDER_ACTION`, `SAME_ORDER_UPDATE_ID`, `STALE_ORDER`, `OTHER_ORDER_ACTIVE`, `MOBILE_ROBOT_NOT_AVAILABLE`, `START_NODE_OUT_OF_RANGE`, `NO_ROUTE_TO_TARGET`, `DEPARTURE_REFUSED` | WARNING | Until the next accepted order. A new refusal replaces the old one, so at most one is present | `orderId`, `orderUpdateId`, `reason` |
| `DEPARTURE_CANCELLED` | WARNING | Until the next accepted order | `orderId`, `reason` |
| `START_REFUSED` | WARNING | Until the next START press | `nodeId`, `actionId`, `reason`: `NO_TROLLEY`, `TROLLEY_STILL_ON`, `TROLLEY_UNKNOWN`, `PREREQUISITE`, `WARNING_CANCELLED` |
| `AGV_HOLD` | WARNING | While a hold is active, except the normal stop at an order node | `holdCause`, `code` |
| `AGV_FAULT` | CRITICAL | While the job is in FAULT | `code` |
| `TRIP_ABORTED` | CRITICAL | Until the next accepted order | `orderId` |
| `CANCEL_REFUSED`, `NO_ORDER_TO_CANCEL` | WARNING | Until the next accepted order | `actionId`, `orderId` |
| `INVALID_INSTANT_ACTION` | WARNING | Until the next accepted order | `actionId` |

### 7. Trolley state in loads

| Rear lidar reports | `loads` |
|---|---|
| No trolley | `"loads": []` |
| Trolley | `"loads": [{"loadType": "TROLLEY", "loadPosition": "rear"}]` |
| Unknown, stale, or lidar not fitted | The `loads` key is left out |

These are three different values, as the spec requires. `loadType` is always `TROLLEY`, and never A to G. `loadId` is never sent. `loads` does not say whether a trolley is empty or full.

**Interlocks, all on the AGV, active only with the calling switch on.**

| Moment | Needs | Refused with |
|---|---|---|
| Departure from home | No trolley, and rear safety field clear | `TROLLEY_PRESENT`, `TROLLEY_UNKNOWN`, `REAR_FIELD_NOT_CLEAR`, `REAR_FIELD_UNKNOWN` |
| START at `ATT` and `ME-n` | Trolley present | `NO_TROLLEY`, `TROLLEY_UNKNOWN` |
| START at `MW-n`, the last release of the order | No trolley | `TROLLEY_STILL_ON`, `TROLLEY_UNKNOWN` |
| START at `MW-a`, the first release of a pair | Trolley present, because `b`'s trolley stays on | `NO_TROLLEY`, `TROLLEY_UNKNOWN` |

`loads` is the same for a pair: one `TROLLEY` entry, present or absent, or the key left out. It never counts trolleys.

Trolley detection is not personnel protection. The rear safety field does that job. Until the rear lidar is fitted, `loads` is always left out.

**`station.no_trolley_run`** (AGV profile, owner's decision of 2026-11-06, on today for runs with no rear scanner): an unknown trolley and an unknown rear field no longer block departure or a START. A sensor that reports a trolley or a violated field still blocks. With it off, every check above stands, and with the lidar not fitted every order is refused.

### 8. Order acceptance

The AGV is the only authority on motion. It runs these checks once per received order, in this order. The first failure ends processing.

| # | Check | On failure |
|---|---|---|
| 0 | MQTT retain flag not set | Discard, no report |
| 1 | Valid JSON, required fields present, `manufacturer` and `serialNumber` are this AGV's, `version` starts with `3.` | `VALIDATION_FAILURE` |
| 2 | `orderId` differs from `state.orderId` | Same id, same `nodes` and `edges`: ignore with no error. Same id, different `nodes` or `edges`: ignore and report `SAME_ORDER_UPDATE_ID`. Neither can restart anything. |
| 3 | Exact shape of section 2: one machine (5 nodes), or a pair (7 nodes) of two different machines with the closer one first. Every machine in the mission's MRU machines | Shape: `VALIDATION_FAILURE`. Action type or parameters: `INVALID_ORDER_ACTION` |
| 4 | `seenStateHeaderId` matches a `state` this AGV sent in the last 5 s of its own monotonic clock | `STALE_ORDER` |
| 5 | No active order, no local trip, no local queued call | `OTHER_ORDER_ACTIVE` |
| 6 | `operatingMode` is `AUTOMATIC` | `MOBILE_ROBOT_NOT_AVAILABLE` |
| 7 | At home, by the AGV's existing at-home check | `START_NODE_OUT_OF_RANGE` |
| 8 | Route compiles (all stops taught) | `NO_ROUTE_TO_TARGET` |
| 9 | Every other `NOT_READY` reason is clear | `DEPARTURE_REFUSED` with the first `reason` |
| 10 | Enter the same path as a physical START at home: prerequisites, 2 s horn, torque check | Prerequisite failure: `DEPARTURE_REFUSED`, `reason` `PREREQUISITE` |

**Refused** means nothing is stored and nothing is retried by the AGV. There is no separate reject message: the refusal appears in `errors`, in a `state` published at once.

**Accepted** means the AGV entered the warning. Acceptance and the warning start together, so an accepted order never sits at home waiting. `state.orderId` shows it at once.

**Cancelled warning.** If the warning stops because a field, the trolley, the torque wait or any prerequisite fails, the order ends with no motion: all actions `FAILED`, arrays empty, `DEPARTURE_CANCELLED` raised, `SETTLING` restarted, and `HOLDOFF` set for 15 s so the horn cannot repeat quickly. A cancel because torque did not arrive also latches `TORQUE_TIMEOUT` until a physical Reset edge, so an E-stop that stays pressed gives one horn cycle only.

**After departure** the AGV finishes the order with its existing scanner stops and holds. Only the three STARTs release it from a wait.

**Where each precondition is checked.** The station never judges a motion precondition. It reads `NOT_READY` and holds back.

| Precondition | Station | AGV | `NOT_READY` reason |
|---|---|---|---|
| Calling switch on | Sees no fresh state, so AGV not free | Switch off: the MQTT client does not start at all, and behaviour is the P0 baseline (AGV plan 4.2) | none |
| Selector AUTO on a valid panel | Reads `operatingMode` | Check 6, rechecked through the warning. A stale panel gives `NOT_AUTO` | `NOT_AUTO` |
| At home. Any wheel movement under MANUAL or jog after At home or after a trip's arrival clears this until a person presses At home again. Heading is not measured | Reads `NOT_READY` | Check 7, rechecked through the warning | `NOT_AT_HOME` |
| Scan match confirmed since At home | Reads `NOT_READY` | Check 9 | `LOCALIZATION_NOT_READY` |
| Tape seen by the line sensor | Reads `NOT_READY` | Check 9 | `TAPE_NOT_SEEN` |
| No fault | Reads `NOT_READY` | Check 9 | `FAULT` |
| Physical Reset edge since a torque-wait cancel | Reads `NOT_READY` | Check 9 | `TORQUE_TIMEOUT` |
| No trolley | Reads `NOT_READY` | Check 9, rechecked through the warning | `TROLLEY_PRESENT`, `TROLLEY_UNKNOWN` |
| Rear safety field clear | Reads `NOT_READY` | Check 9, rechecked through the warning | `REAR_FIELD_NOT_CLEAR`, `REAR_FIELD_UNKNOWN` |
| Front field, drives, lease, track | Reads `NOT_READY` | Checks 9 and 10, as for a physical START | `PREREQUISITE` |
| Trip engine live on this profile | Reads `NOT_READY` | Check 9 | `SITE_NOT_LIVE` |
| No local trip or call | Reads `NOT_READY` | Check 5 | `LOCAL_TRIP` |
| 5 s since the selector entered AUTO, a Reset, a web Clear, a local call being cancelled, a mission being selected, the trolley going absent, the rear field clearing, the front field clearing, arrival at home, or a warning ending by a cancel or `cancelOrder` | Reads `NOT_READY` | Check 9 | `SETTLING` |
| 15 s since a cancelled warning | Reads `NOT_READY` | Check 9 | `HOLDOFF` |
| One open call per machine, first come first served, cancel rules | Station only | Not known | none |

**AGV free, on the station.** All of these must hold:

1. The retained `connection` shows `ONLINE`.
2. A `state` arrived in the last 3 s by the station's monotonic clock.
3. `operatingMode` is `AUTOMATIC`.
4. `nodeStates` and `edgeStates` are empty.
5. `errors` has no `NOT_READY`.
6. No call on this AGV is past QUEUED.

**Sending and resending.** When the head call is QUEUED and the AGV is free, the station sends the order at once, then every 2 s. Each send has `headerId` +1, a new `timestamp` and the newest `seenStateHeaderId`. Sending stops as soon as `state.orderId` equals the orderId, the AGV stops being free, or the call is cancelled. It resumes with the same orderId and the newest `seenStateHeaderId` when the AGV is free again, after a link loss too. The AGV takes that resend if no earlier copy reached it, ignores it if it holds that orderId already (check 2), and can take an id it refused before, because nothing is stored on refusal. After `DEPARTURE_CANCELLED` the AGV treats the id as held, so the station always uses a new orderId then. A pair's two calls share one order and one orderId. It also stops, until a person acts on the station screen, after a refusal other than `DEPARTURE_REFUSED` and `STALE_ORDER`, or at the requeue limit in section 11.

**Stale orders.** Check 4 stops an old order that was held in a TCP buffer during a Wi-Fi drop: only an order written after the station saw a recent `state` passes. Neither side compares clocks. State goes out at least once per second, so a live link always passes.

**An order cannot wait anywhere.** QoS 0, retain off, clean sessions, `persistence false`, no client offline queue, retain-flag discard, nothing stored on refusal, and check 4 all apply. If the station stops sending, no order can start the AGV more than 5 s later.

### 9. Failures and cancel

| Event | AGV | Station | Later motion from it |
|---|---|---|---|
| Wi-Fi loss, order active | Finishes the released order. START, stops and scanners are all local. | After 3 s: link lost, call state frozen, no sends. Broker delivers the last will about 15 s after silence. | None |
| Wi-Fi loss, no order | Stays put | Queue waits. Presses are still taken and queued. An order sent but not yet shown is not resent until a fresh `state`, then resent with the same orderId (section 8) | None |
| Wi-Fi returns | Reconnects, `ONLINE`, `state`. Buffered old orders fail check 4. | Table catches up | None |
| AGV reboot or line layer restart | Order lost, `STARTUP`, then `orderId ""`. Not at home until someone presses At home. | Shown call goes to Aborted (row 2). Queued calls wait. | Only a new fresh order, after all checks |
| Station restart | Notices nothing | Reloads its saved call list (orderId, machine, type, shown, press order), waits for a fresh `state`, runs the table. An active order it does not know is adopted with the machine from the orderId (two calls for a pair) and type shown as unknown. Nothing is ever sent for an adopted call. | None: sends had stopped |
| Broker restart or broker down | Same as Wi-Fi loss. Reconnects and republishes `ONLINE`. | Same as Wi-Fi loss | None |

**Cancel.** Calls are cancelled from the screen only while QUEUED. If no order was ever sent, the call is deleted. If one was sent:

1. The station stops sending and marks the call cancelling. Presses from that machine stay ignored.
2. It watches `state` for 6 s (the 5 s window plus 1 s).
3. If `state.orderId` never equals the orderId, the call is deleted.
4. If it does, with `nodeStates` not empty, the station sends `cancelOrder` every 2 s with the same `actionId` until `instantActionStates` shows the result. The AGV acts once per `actionId`.

| AGV situation | Result | Station |
|---|---|---|
| In the warning, not yet moving | Stops the warning. `cancelOrder` `FINISHED`, wait actions `FAILED`, arrays empty, no `DEPARTURE_CANCELLED` and no `HOLDOFF`. `SETTLING` restarts, so `NOT_READY` shows it for 5 s | Deletes the call |
| Already moving | `cancelOrder` `FAILED`, `CANCEL_REFUSED`. The order continues. | Restores the call at its real state, screen says "too late to cancel" |
| No active order or a different orderId | `cancelOrder` `FAILED`, `NO_ORDER_TO_CANCEL` | Deletes the call |

Cancelling one call of a pair cancels the order. The other call waits again with its press time.

No other case sends `cancelOrder`, a link coming back included. It is not a stop command: stopping is physical.

**Two AGVs later.** Each AGV has its own topics, client, `headerId` counters and free check. Traffic control is not built, and nothing in this contract assumes there is only one AGV. Today the station sends to `agv1` only.

### 10. Not implemented

| Received or expected | AGV behaviour |
|---|---|
| Any order not exactly a shape in section 2: BTU or other nodes, more than two machines, a pair with the farther machine first, the same machine twice, machines from two groups, takes in call order, `released: false`, `orderUpdateId` above 0, `nodePosition`, `trajectory`, edge actions, zones | Refused, `VALIDATION_FAILURE`. No motion. |
| Any order action other than `waitForTrigger` with `["LOCAL"]`, including `FLEET_CONTROL` | Refused, `INVALID_ORDER_ACTION`. No motion. |
| `startPause`, `stopPause`, `trigger`, `factsheetRequest`, `stateRequest`, `initPosition` and every other instant action | No effect. Reported in `instantActionStates` as `FAILED`, with `INVALID_INSTANT_ACTION`. |
| `factsheet`, `visualization`, `zoneSet`, `responses` topics | Not published, not subscribed |

BTU trips stay on the AGV's own screen and are not part of this contract.

**Why this is not compliant, and other deviations:**

- `factsheet`, `startPause` and `stopPause` are mandatory in the spec and absent here.
- `cancelOrder` is refused once the AGV moves. The spec says to stop as soon as possible.
- Any trip abort clears the order, including a fault in AUTOMATIC. The spec clears an order on a mode change or cancel, not on an error.
- `NOT_READY` and the other custom error types use the spec's extensible `errorType`, and `NOT_READY` is a WARNING even though it blocks new orders.
- `seenStateHeaderId` is a custom field in `order`.
- `stateOfCharge` is a placeholder.
- `instantActionStates` are cleared on an accepted order and there is no `clearInstantActions`.
- `order` content comparison ignores the header and `seenStateHeaderId`.
- `waitForTrigger` becomes `FINISHED` when the warning ends and the AGV starts to move, not at the press. The spec says `FINISHED` means the trigger has been triggered.
- The spec makes fleet control responsible for the wait timeout and for cancelling a wait. This station has no wait timeout, and `cancelOrder` is refused once the AGV has moved.
- The spec says `connection` is not for checking mobile robot health. Check 1 of AGV free on the station gates on it.
- `INVALID_INSTANT_ACTION` and `MOBILE_ROBOT_NOT_AVAILABLE` clear on the next accepted order. The spec clears them when a new instant action is accepted and when the operating mode allows new orders.

### 11. Flagged for the owner

Each item below is a value this contract picks so that work can go on, or a decision that is not software's to make.

1. **LED off point.** Off from arrival at the machine onward is an assumption.
2. **Rear field while towing.** The trolley sits in the rear scanner's view. How that field behaves when towing is a safety hardware decision. The rear scanner also has no safe inputs reserved on the FX3 today. This contract only reports what the field says.
3. **No lidar, no automatic departure, unless `no_trolley_run`.** With it off, unknown trolley state refuses every order, so the MQTT flow cannot move the real AGV until the rear lidar is fitted. With it on (section 7, on today), orders run with no trolley detection. Hand trips with the calling switch off behave as the P0 baseline.
4. **Relay rating.** No rating for the DO relays was found, and the LED load wiring is not documented. Slow blink is the station's job. The blink rate must be checked against the rating before the named first-write approval.
5. **Added by this contract, for your risk assessment:** the 5 s `SETTLING` wait and the 15 s `HOLDOFF`. Your decisions did not name them. They stop a waiting call from leaving the moment someone returns the selector to AUTO, presses Reset, unhitches a trolley, clears a block from the web, or walks out of a field, or the moment the AGV arrives home. The 2 s horn and scanners still apply.
6. **Aborted calls** close with no retry, and the machine must press again.
7. **Late cancel.** A cancel that loses the race to departure is refused and the trip continues.
8. **Broker passwords and ACL** go beyond your decisions, because an order now moves the vehicle by itself. Plain MQTT is not encrypted, so Wi-Fi security still matters.
9. **`manufacturer` = `gvi`** is a label chosen from the repo names. Change it before first use if you want another one, because it is part of every topic.
10. **Reset after an E-stop on a station trip.** By current code, the Reset needed after an E-stop aborts the trip, so the call ends Aborted and is recovered by hand. Item O13 of the AGV plan keeps this as the default and asks you to confirm it.
11. **Requeue limit.** After 3 consecutive row 4 requeues of one call, the station stops sending that call and raises a banner that needs an acknowledge. The number 3 is yours to change.
12. **Two trolleys, one sensor.** The rear lidar cannot count trolleys. At the first release of a pair it wants a trolley present, because one stays on, so the AGV cannot tell whether the release there really happened. The operator's START is the only proof.
13. **Pair wait.** The station waits up to `pair_wait_s` (6 minutes, owner, 2026-11-11) from the first MRU press for a second one. It is 0, one machine per trip, until the AGV's pair build and a site test with no trolleys are done.
