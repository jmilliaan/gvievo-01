# Plan: controlled stop from the safety controller (`-KE2:Q4` → both motor drivers)

**Aim:** wire safety-controller output Q4 to a stop input on both motor drivers, so the vehicle decelerates under drive control before the safety controller removes torque (STO via Q1/Q2). Then update the circuit diagrams and the documents that describe the stop.

Status 2026-11-15: plan only, nothing changed. Sources: `manuals/bldc/` (BLV-R function manual and CANopen manual; `mvc01.pdf` not used), the current IEC set and `01-schematic/io-mapping.md`.

Markers: **[decide]** = owner choice. **[verify]** = check in a document we do not have, or on the vehicle.

---

## 1. What the driver manuals say

| Topic | Finding | Source |
| --- | --- | --- |
| Why a controlled stop is needed | "Be sure to check the motor is in a standstill state before transitioning to the power removal status. Transitioning to the power removal status while the motor is rotating may cause damage to the motor, driver, or equipment." The holding brake "is used for the purpose to hold the position. Do not use the brake … for braking the motor rotation." STO at speed (stop category 0) is therefore against the vendor's instructions. | function manual p.211, p.214 (power removal function) |
| Direct inputs | 4 photocoupler inputs on the 28-pin control connector CN4: pin 15 **IN-COM** (common), pins 16–19 **IN0–IN3** = DIN0–DIN3. Factory assignment: DIN0 ID-SEL0, DIN1 ID-SEL1, **DIN2 (pin 18) STOP**, DIN3 (pin 19) FREE. All unwired today (page 50). | function manual p.162 (3-1 Direct I/O), p.212 pinout; brochure p.25 |
| Stop signals | **STOP** (assignment no. 5): stops per "STOP input action"; the drive stays enabled and runs again when STOP turns off. **QSTOP** (no. 4): stops per "QSTOP input action". The default is 2 = deceleration at the quick stop rate, **current cut off after stopping**. | function manual p.36–37, p.153, p.169–171 |
| Under CANopen | The direct QSTOP input drives the CiA 402 state machine: transition 11 → **Quick stop active**, then 12 → **Switch on disabled** when the stop is done. While QSTOP is active the drive cannot be enabled (transitions 7, 10). The direct STOP input only sets status bit 11 "internal limit active". | CANopen manual §6.2 state transitions, statusword bit 11 |
| Fail-safe polarity | "DIN inverting mode" per input (0 = not invert, 1 = invert). With 1, a de-energised input = signal active: a broken wire or a dead Q4 = stop. | function manual p.151 (I/O parameters) |
| Input timing | An input must be on for 2 ms or more to be recognised. "ON signal dead-time" filter 0–250 ms. | function manual p.151, p.170 |
| Input circuit | Photocoupler input. **Not stated** in the manuals we have: input current, and whether IN-COM may go to 0 V (source logic, current flows IN→IN-COM) or must go to +24 V. **[verify]** in the BLV-R driver hardware manual (not in `manuals/bldc/`), or measure on the bench. | brochure p.25 ("4 points, photocoupler input") only |

## 2. Proposed design

### 2.1 Choice of input signal: QSTOP, not STOP (recommended)

| | QSTOP (recommended) | STOP |
| --- | --- | --- |
| When Q4 returns | The drive stays in Switch on disabled until the software re-enables it. No restart without RESET (SF5) | The drive runs again at the speed the software is still sending. **Unexpected restart risk** |
| After the stop | Current cut off (action 2). Fits with STO that follows | Motor stays excited |
| Software | Same path as today's STO: SWITCH_ON_DISABLED already means "held by the safety chain or not yet reset" (`amr_base/drive_state.py`) | New state to handle (status bit 11) |
| Deceleration | Quick stop rate (6085h), 1600 (r/min)/s in the RUNBOOK PP table (`amr_ws/RUNBOOK.md`) | STOP action and rate (separate parameters) |

**[decide 1]** QSTOP or STOP. This plan assumes QSTOP.

### 2.2 Wiring

```
-KE2:Q4 ──QSTOP──┬──────────── -TA1:18 (IN2)
                 └──────────── -TA2:18 (IN2)
1N24 ─────────────┬─────────── -TA1:15 (IN-COM)
                  └─────────── -TA2:15 (IN-COM)
```

- Q4 sources 24 V (Flexi Soft outputs are high-side). Loop it to IN2 of both drivers, the same way HWTO1 and HWTO2 are looped (junctions, page 42).
- IN-COM of each driver goes to 1N24. **[verify]** that the input works this way round (§1, last row). If the drivers need IN-COM on +24 V, Q4 cannot drive them directly and an interface relay is needed. Settle this before drawing.
- Conductor: AWG22 blue. Wire marker **QSTOP** at every end (page 76).
- **Q4 test pulses OFF.** With inverting mode, every test pulse is a short QSTOP. The driver needs 2 ms to recognise an input, and Flexi Soft test pulses are shorter, but the margin is not documented. Mark "TEST PULSES OFF" on the sheet with the reason (conventions §8), as for Q3.
- Load: two photocoupler inputs, a few mA each **[verify]**. Well within a Flexi Soft output.
- The 24 V reference is shared: the drivers' network supply (pins 20/21) is already on 1P24/1N24, and Q4's supply is A1/A2 on the same bus.

### 2.3 Driver parameters (both drivers, MEXE02, saved and power-cycled)

| MEXE02 parameter | Value | Why |
| --- | --- | --- |
| DIN2 input function | 4: QSTOP | Q4 → IN2 |
| DIN2 inverting mode | 1: Invert | 0 V = stop: a broken wire, a dead Q4 or the safety controller off all stop the vehicle |
| QSTOP input action | 2: Deceleration rate stop, current cut off after stopping (default) | Controlled stop, then no torque |
| Quick stop rate (6085h) | 1600 (r/min)/s, the value in the RUNBOOK PP table; read it back from both drives **[decide 3]** | Sets the stopping distance. Check against the 1 000 kg towed load |
| DIN2 ON signal dead-time | 0 (default) | No delay on the stop |

The software never writes these (`agv_core/drivers/canbus/guard.py` forbids 4000h–4FFFh). They go into the MEXE02 table in `amr_ws/RUNBOOK.md`, and optionally into the drive read-back check like `pp.expect`.

### 2.4 Safety controller logic (Flexi Soft project)

- **Q4 = run permitted.** Q4 is ON only while every stop condition is clear and after RESET. It drops **at once** on any stop demand: E-stop (SF1), protective field in AUTO (SF2), overspeed (SF6).
- **Q1/Q2 (STO) drop after a delay** = safe stop 1 (SS1, stop category 1). **[decide 2]**:
  - **SS1-t:** a fixed off-delay t, longer than the deceleration time from top speed plus a margin. Simple.
  - **SS1-r:** STO as soon as `-KE5` (FX3-MOC0) sees both wheels at standstill, with t as the maximum. Shorter coasting on the brake, and the deceleration is monitored.
- If the drive ignores QSTOP or Q4 sticks on, STO still comes after t. The safety function stays the delayed STO. Q4 is a functional path ahead of it, single channel, not safety-rated.
- **Restart order:** after RESET, Q1/Q2 on first, then Q4. The software then enables the drives (SF5 unchanged).
- SF7 (standstill) and SF8 (EDM) are unchanged: the vehicle is already stopped.
- After the change: download the project, update the Flexi Soft report and checksum, and **re-verify all safety functions** (operation manual 8.5).

## 3. Schematic update (IEC set, `01-schematic-iec/`)

| Page | Change |
| --- | --- |
| 42 | Draw Q4 → QSTOP marker → junction → `-TA1:18`, `-TA2:18`. Add pins 15 (IN-COM) and 18 (IN2) to both driver boxes; IN-COM → 1N24. Add "TEST PULSES OFF" at Q4. Notes: what Q4 does, inverting mode, test pulses. Function text: "Safe torque off, controlled stop and EDM …". Page description → "Safety: safe torque off, controlled stop and feedback (EDM)" (`project.js` pages) |
| 50 | Pin table rows 15 and 18: connected to, wire marker, page. Connector face: pins 15 and 18 drawn as wired. Note 2 ("take no commands on their digital inputs") is reworded: only IN2 is used, for the controlled stop |
| 44 | Q4 row (`PROJECT.safetyIO`): signal "Controlled stop (QSTOP)", device `-TA1:18, -TA2:18 IN2`, test pulse "off", safety fn. "SF1, 2, 6 (stop sequence)", marker QSTOP, off means "Both drivers decelerate (quick stop)" |
| 12 | Arrow Q4 → QSTOP to both drivers. Replace the stop line with "Stop: controlled deceleration (Q4), then torque removed (STO) after t, holding brakes apply". This settles the red "stop category" item (README) |
| 5 | Safety-function table, Result column for SF1, SF2, SF6: "Controlled stop, then torque off (SS1)" |
| 40 | `-KE2` "Other terminals" line: Q4 /42.x |
| 76 | `PROJECT.markers`: `['QSTOP', '-KE2:Q4', '-TA1:18, -TA2:18', '42']` |
| 4 | No new symbol needed |
| all | `check-set.ps1`, then rebuild `circuit-diagrams.pdf` (26 pages, no new page) |

Text files in the same folder: `conventions.md` §8 (Q4 assigned, test pulses off, SS1), `sheet-plan.md` row 42, `designation-map.md` `-TA1`/`-TA2` (IN2 QSTOP), `README.md` open items (stop category resolved).

## 4. Schematic update (JIS set, `01-schematic/`, the as-built record until the rewire)

Follow `documentation/electrical/agent/SKILL.md`: interpretation first, then build, preview and checklist.

| Item | Change |
| --- | --- |
| `proj01-sheet-07.html` | Driver connector: pins 15 (IN-COM) and 18 (IN2) wired, with destinations |
| `proj01-sheet-08.html` | Safety PLC Q4 → both drivers IN2, with a terminal pair (the JIS set still uses TB numbers: next free numbers **[decide on the vehicle]**) |
| `io-mapping.md` §1 | "Not connected: … 15–19" → 15 and 18 connected. Add the four driver parameters |
| `io-mapping.md` §2 | Q4 row: controlled stop to both drivers, test pulses off |

## 5. Other documents

| Document | Change |
| --- | --- |
| Operation manual `operation-manual-doc.md` 3.3 | Effect for E-stop, personnel detection and speed limit: "the vehicle brakes to a stop, then motor power is cut and the holding brakes apply". Also "Torque off at once" on page 5 and in any text that says "at once". Stopping distances, if quoted, recomputed |
| Operation manual figure IMG-03-01 | Add Q4 → both drivers |
| Operation manual 8.5 / periodic tests | New checks: Q4 wire broken → the drives will not enable; a stop from speed decelerates before torque off |
| `amr_ws/RUNBOOK.md` MEXE02 table | The §2.3 parameters |
| Component list `component-list.xlsx` (hand-edited) | Safety data / open questions: stop category 1, SS1 delay, Q4 test pulses off. Owner edits |
| Flexi Soft report (separate document) | New logic, Q4 configuration, checksum |
| Submission copy | Rev A not yet sent: replace the CD and manual PDFs in `documentation/submission/2026-11-09_preliminary-review/` after the rebuild |

## 6. Software to check (no change expected, test on the vehicle)

- The arm/enable sequence must wait while a drive refuses to enable because QSTOP is active (Q4 off at power-up until RESET). Today this looks the same as STO held (Switch on disabled).
- **Quick stop active** (`cia402.py` 0x07) is a new transient state during a safety stop. Check that the supervisor, alarms (`agv_core/alarms.py`, `amr_web/alarms.py`) and the web status call it a safety stop and not a fault.
- Optional: read back DIN2 function, DIN2 inverting and QSTOP action from both drives at start-up and refuse to arm on a mismatch (same pattern as `pp.expect`).

## 7. Tests on the vehicle (wheels off the ground first, then on the floor with an area clear)

1. **Bench polarity** (before wiring both): Q4 forced off and on in the Flexi Soft simulation or online. The driver status in MEXE02 shows QSTOP active when Q4 is off.
2. **Broken wire:** disconnect the QSTOP conductor at one driver → that driver will not enable and shows Quick stop active.
3. **E-stop at top speed (AUTO, 1.1 m/s, with load):** decelerates, then STO after t; EDM (SF8) sees both drives off; brakes applied. Measure the stopping distance.
4. **Protective field at speed:** same sequence. The field auto-resume still works only through RESET/START as today.
5. **Overspeed (SF6)**, if it can be provoked safely: same sequence.
6. **QSTOP ignored** (DIN2 function temporarily 0 on one drive, bench only): STO still comes after t.
7. **Restart:** release E-stop, RESET, START → normal enable, no motion before START.
8. Re-verify all safety functions per operation manual 8.5 and record it.

## 8. Order of work

1. Settle **[verify]** input polarity and current (§1), and **[decide 1–3]**.
2. Flexi Soft project change and drive parameters on one vehicle; bench tests 1, 2 and 6.
3. Wire Q4 and IN-COM on both drivers; tests 3–5 and 7–8.
4. Update the JIS sheets and `io-mapping.md` (as built), then the IEC set (§3), then the manual and the other documents (§5).
5. Rebuild the PDFs; replace the submission copies.

## 9. Decisions (owner, 2026-11-15)

1. **QSTOP** on IN2 (DIN2 input function 4, inverting mode 1, QSTOP input action 2).
2. **SS1-r with `-KE5`:** Q4 drops at once. Q1/Q2 (STO) drop when `-KE5` reports both wheels at standstill (the SF7 threshold, 20 mm/s), or at the latest after a maximum time t_max, whichever comes first. Used for SF1, SF2 and SF6. t_max is still open: set it from the measured deceleration time at top speed with load, plus a margin.
3. **Quick stop rate stays 1600 (r/min)/s.**

Still open: **[verify]** the IN-COM polarity and input current (§1); t_max; the Flexi Soft project change.

## 10. Status (2026-11-15)

Done in the documents (design, not yet on the vehicle):
- IEC set: pages 5, 12, 40, 42, 43, 44, 45, 50 and 76 (`data/project.js`: page 42 title, SF1/SF2/SF6/SF7 results, Q4 row, QSTOP marker). On page 42 the IN-COM → 1N24 connection is marked red "?", and «t max» is red on pages 12 and 42. `check-set.ps1` passes for all 26 pages, and `circuit-diagrams.pdf` has been rebuilt.
- `README.md` (open items: «t max» and IN-COM replace "stop category"), `conventions.md` §8, `sheet-plan.md` row 42 and issue 9, `designation-map.md`.
- Operation manual: 3.1, 3.3, 3.4 (field table and [REVIEW] note), 4.2 drivers row, 4.3 E-STOP row, 8.5, 10.6, 11.1, 13 [REVIEW] note. The manual PDF has been rebuilt.
- `amr_ws/RUNBOOK.md`: new subsection "Controlled stop input QSTOP", with the §2.3 parameters and a warning not to set DIN2 before the wiring.

Still open:
- **[verify]** IN-COM polarity and input current (BLV-R hardware manual or bench test 1);
- t_max;
- the Flexi Soft project change, report and revalidation;
- the MEXE02 settings and wiring on the vehicle, then the tests in §7;
- JIS sheets 07/08 and `io-mapping.md` (as built, after wiring);
- figure IMG-03-01, the component list (owner edits), the manual's new periodic check rows (only a [REVIEW] note so far), §6 software checks;
- the copies in the submission folder.
