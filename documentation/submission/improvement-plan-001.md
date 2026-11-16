# Improvement plan 001 — Rev A preliminary-review package

Date: 2026-11-15. Status: the P1 fixes and the owner decisions D1–D11 are implemented in the documents (section 0). Open: the software side of D1, two items waiting for data, and all P2 and P3 items.

This file is internal. It sits beside the package folder, not in it, so it is not zipped with the package.

## 0. Status after the first pass (2026-11-15)

The masters were edited, the three PDFs rebuilt and the four files copied into the package folder. The manual is now 43 pages. Sections 1 to 9 below describe the documents as they were before this pass.

**Done**

| ID | What was changed |
| --- | --- |
| X3, X4, C5 | `-TA3` is 6.3 A and `-TA4` is 8.5 A on diagram page 80 and in the component list. The `-TA3` box on page 20 now shows "SD-150C-24, 150 W, isolated". The 8.5 A is from distributor listings, not from the Mean Well datasheet itself. |
| X5 | Motor drivers read "24–48 V DC (at 48 V)" in both lists. |
| X6 | Component list page lists for `-TA1`, `-TA2`, `-KE1`, `-KE2` now match diagram page 80. The wider question, whether overview pages 10–12 belong in the lists, is still open: both lists are equally uneven on it. |
| X7 | Wi-Fi card page reference is "—". |
| X8 (part) | Y-cable number 2116199 added to Cables row 25. |
| X9 | Stop-point pulsing added to page 61 note 2 and page 62 row DO1. |
| X10 | Manual 4.2: safety controller row extended; new row for the safety encoders. |
| X11 | `+EB-XE1` added to the component list as row 47; the mechanical rows are now 48–50. |
| X12, L10 | Cover says "one row per component". |
| M1 | Chapter 17 and Annex E exist as `[REVIEW]` stubs, so the Contents and 14.2 resolve. The drafts in section 9 are not used yet. |
| M3 | 7.2 step 3 has its full stop and a `[REVIEW]` box under the list. |
| M4 | The 8.4 list is closed. No new bullets were added. |
| M5 | A `[REVIEW]` box under the chapter 13 table names the three checks that 10.1, 15.2 and 15.4 point to. No test procedures were written. |
| M6 | "O = operator, M = maintenance personnel." under the tables in 13, 15.2 and 15.4. |
| M7 | 4.3 RESET: "stops the vehicle and ends the run (chapter 10.6)". |
| M8 | **Recover** added to the Home row in 4.5. |
| C2 | Page 44: Q1 and Q2 carry "SF1, 2, 6–8". |
| C3 | Page 62: "DO9–DOF". |
| C4 | Page 61 note 5: the reference to the other drawing set is gone. |
| L1 | Footer reads "Page n of 4" on all four pages. The total is now typed into the footer of each sheet, because Excel's own count came out as 5. **Change it by hand if the page count changes.** |

`designation-map.md` was changed to 6.3 A as well, to keep it in step.

**Owner decisions D1–D11 (2026-11-15)**

| ID | Decision | What it means, and what was done |
| --- | --- | --- |
| D1 | The scanner has the **manual's field set**: protective semicircle R 400 mm, warning field 2 0.80 × 1.10 m, warning field 1 1.20 × 1.30 m, chamfered. | Diagram page 41 changes to this set (length × width for all three). Manual 3.4, 8.4 and 13 stay. `amr_ws/src/amr_bringup/config/scanner_fields.yaml` is stale: it holds rectangles and feeds the software. With the new set the gap warning field 2 − protective field is 0.80 − 0.40 = 0.40 m, equal to `stop_m` 0.40, so the 0.07 m latency margin noted in that file is gone. **Done in the documents:** page 41 now reads "semicircle R 0.40 m (0.80 m wide)" and "0.80 × 1.10 m, 1.20 × 1.30 m". **Not done in the software:** the field file takes rectangles only (`scanner_fields.py`, `rect`), so the new shapes cannot be entered as values, and `test_field_limit.py` pins the old reach figures. Only a STALE note was added at the top of the file; its values and the vehicle's behaviour are unchanged. Next: read the set out of Safety Designer, decide how shapes are stored, decide `stop_m`. |
| D2 | Unladen mass **150 kg**. | **Done:** manual 16.1 and the nameplate figure (`images/labels/nameplate.svg`) say 150 kg. |
| D3 | Coupling height **285 mm**. | **Done:** component list row 50 (towing hook) says 285 mm. |
| D4 | Floor gradient **0 %**, floor gap **10 mm**. | **Done:** manual 5.1 says "Level only (0 %)"; 6.1 says 10 mm. |
| D5 | Low-voltage warning **48 V; the profiles change**. | `monitor.bus_v_warn_low` becomes 48.0 in `profiles/agv-01.json` and `agv-02.json`. The manual stays. **Done in the repo:** both profiles say 48.0 and load through `agv_core.config` validation. **Not deployed:** the owner puts it on the vehicles and watches for low-voltage warnings under load. |
| D6 | Service contact is **sales@igp-astra.co.id** in both places. | **Done:** manual 1.1 reads "Sales and service: sales@igp-astra.co.id". 14.4 stays. |
| D7 | Trolley brakes are **not required**. | **Done:** "braked trolleys" is out of manual 3.5; the towing limits remain as the measure. 5.2, 5.3 and 10.4 stay. Reviewer point R1 (traction with an unbraked 1 000 kg train) stands and is now sharper. |
| D8 | GVI-1T0 is a **type code**; the software range **stays**. | **Done:** "Applies to: Model AGV I-PRIME, type GVI-1T0, all serial numbers, vehicle software V1.0.0 to V2.0.0". |
| D9 | Drive monitor, encoders and the Q3 → DI09 wire are **all fitted**. | The diagram stays as drawn; C12 is closed. `dio.di_names[9]` is still `[SPARE]` in both profiles. It was left alone: naming and reading DI09 is step E1 of `manuals/emergency-suite-plan.md`. |
| D10 | A **battery display on the Home page is coming**. | **Done:** manual 10.1 row 5 reads "30 % or more on the **Home** page", with a `[REVIEW]` box under the table until the display exists. |
| D11 | The 0.65 m/s speed is **left out** of the manual. | No manual change. Expect the question if the reviewer sees the vehicle run at 0.65 m/s. |

**Still open**

- Software side of D1 (scanner field file), and deploying D5 to the vehicles.
- Waiting for data: X8 and L2, the real type of the M12 plug (rows 23 and 24 still say "MOC-Y-CABLE"); M9, where the motor-driver circuit breakers are and who may operate them.
- All P2 and P3 items.
- **New 2026-11-16:** the 24 V converter `-TA3` is a **SD-100C-24** (100 W, 4.2 A out), owner statement. The circuit diagram (pages 20, 30, 80, `data/project.js`), the JIS sheets (00, 01), `designation-map.md`, the component list and the X3 fix above say SD-150C-24, 6.3 A (150 W). All of them need correcting. Check the nameplate first.

Backups of every file as it was before this pass are in the session scratchpad only; the package files are tracked in git, but their previous state was uncommitted.

## 1. What was checked

Package: `documentation/submission/2026-11-09_preliminary-review/`

| Document | File | Master it is built from |
| --- | --- | --- |
| Operation manual IGP-IPR-OM-001 (42 pages) | `IGP-IPR-OM-001_RevA_Operation-manual.pdf` | `documentation/operation-manual/operation-manual-doc.md` |
| Circuit diagram IGP-IPR-CD-001 (26 pages) | `IGP-IPR-CD-001_RevA_Circuit-diagram.pdf` | `documentation/electrical/01-schematic-iec/iec-page-NN.html`, `data/project.js` |
| Component list IGP-IPR-CL-001 (4 pages) | `IGP-IPR-CL-001_RevA_Component-list.pdf` and `.xlsx` | `documentation/component-list/component-list.xlsx` |

Method: every page of the three PDFs was read as text, the component-list PDF and two other pages were also looked at as images, and disputed values were compared with the vehicle software (`amr_ws/src/amr_bringup/config/scanner_fields.yaml`, `profiles/agv-01.json`, `profiles/agv-02.json`, `agv_core/alarms.py`, `agv_core/config.py`). Four datasheet values were looked up on the web.

Not checked: most circuit pages were read as text only, so drawing errors that do not show in the text (a line to the wrong terminal, overlapping graphics) are not covered. Nothing was checked on the vehicle.

Two things are in order:

- The four files in the package are byte-identical to their masters.
- Every alarm code in the manual exists in `agv_core/alarms.py` (37 codes; `READY` and `DISCONNECTED` are states, not alarms).

## 2. How to read the priorities

The package is unfinished on purpose. The rule used here: a gap may stay, but it must look deliberate.

- **P1**: the documents contradict each other or themselves, or a reference points at nothing. Fix before sending.
- **P2**: missing data. Either fill it in (a value is proposed where one could be found) or mark it as an open point in a `[REVIEW]` box.
- **P3**: wording and format.

## 3. Decisions needed from the owner first

These block the P1 fixes. Each has a recommendation.

| ID | Question | Recommendation |
| --- | --- | --- |
| D1 | **Which scanner field set is on the vehicle?** The manual and the circuit diagram give two different sets (see X1). | Read the field set out of Safety Designer and use that everywhere. If the manual's set is the real one, `scanner_fields.yaml` is stale and must change with it, because the software uses its distances. |
| D2 | Unladen mass: 150 kg (manual 1.3) or 160 kg (manual 16.1)? | 150 kg; `agv_core/config.py` also says 150 kg. Better: weigh the vehicle. |
| D3 | Coupling height: 285 mm (manual 4.6 and the hitch figure) or 250 mm (component list row 49)? | 285 mm, because it is the dimensioned figure. |
| D4 | Floor gradient: 0 % (manual 2.2, 6.1) or 2 % (manual 5.1)? Floor gap: 10 mm (2.2) or 15 mm (6.1)? | 0 % and 10 mm: the stricter values, and nothing has been tested on a slope. |
| D5 | Low-voltage warning: the manual 12.1 says 48 V, both vehicle profiles say 42.0 V. | Change the manual to 42 V, or change the profiles. 56 V high matches. |
| D6 | Service contact: `iprime-service@igp-astra.co.id` (manual 1.1) or `sales@igp-astra.co.id` (manual 14.4)? | The service address in both places. |
| D7 | Are trolley brakes required? Manual 3.5 lists "braked trolleys" as the protection against overrun; 5.2, 5.3 and 10.4 say "if available". | Decide with the stopping test (R1). Until then write "if available" in 3.5 too and add the point to the `[REVIEW]` box in 3.4. |
| D8 | "Applies to: serial numbers GVI-1T0, vehicle software V1.0.0-V2.0.0" (manual, document information). `GVI-1T0` reads like a type code, not a serial range. | Give the real serial format and the software version on the vehicle. |
| D9 | As-built state: are the drive monitor `-KE5`, the encoders `-BG5`/`-BG6` and the wire `-KE2:Q3` → `-KE4:DI09` fitted? The diagram draws them as fitted. The notes from 2026-11-15 say the Q3 change is not yet in the Flexi Soft project, and both profiles still name DI09 `[SPARE]`. | If not fitted when the package is sent, draw them dashed ("not fitted in this revision", the convention on diagram page 2) or add a note on pages 42 and 45. |
| D10 | Where does the operator read the battery charge? Manual 10.1 row 5 stops mid-sentence ("30 % or more on"), and the web pages have no battery display. | Name the indicator, or change the check to a voltage. |
| D11 | Third automatic speed: both profiles have `auto_plus_ratio` 1.3, which is 0.65 m/s. The manual knows only 0.50 and 0.85 m/s. | If the 0.65 m/s zones are used on site, add them to manual 2.2, 9.1, 10.5 and 16.1. |

## 4. Contradictions between the documents (P1)

| ID | Where | What disagrees | Fix |
| --- | --- | --- | --- |
| X1 | Manual 3.4, figure IMG-03-02, 8.4, 13 · Diagram page 41 | Manual: protective field semicircle radius 400 mm (0.40 m long, 0.80 m wide), warning field 2 0.80 × 1.10 m, warning field 1 1.20 × 1.30 m, chamfered. Diagram: "Protective field 0.50 × 0.80 m, warning fields 0.97 m, 1.77 m". The diagram follows `scanner_fields.yaml` (rectangles 0.50 × 0.80, 0.97 × 1.20, 1.77 × 1.50 m, "as configured 2026-10-02"). The manual's set came in with the commit of 2026-11-14. | After D1. If the yaml set is right, the manual changes in 3.4 (table, the three reach values 1.70 / 0.90 / 0.43 m, the `[REVIEW]` box), 8.4 and 13 (0.33 m becomes 0.43 m) and the figure. If the manual is right, page 41 and the yaml change. |
| X2 | Manual 4.6 · Component list row 49 | Coupling height 285 mm against 250 mm. | D3. |
| X3 | Diagram pages 20, 80 · Component list row 7 | `-TA3` output 6.25 A against 6.3 A. | 6.3 A (Mean Well rating for SD-150C-24) in all three places. |
| X4 | Diagram page 80 · Component list row 8 | `-TA4` "12 V 8.3 A (100 W)" in the diagram; no current in the list. Distributor data for SD-100C-12: 12 V, 8.5 A, 102 W. | 8.5 A (102 W) in both, after a look at the Mean Well datasheet. |
| X5 | Diagram page 80 · Component list rows 9, 10 | Motor drivers: "48 V DC, 400 W" against "24–48 V DC". | One wording: "24–48 V DC (used at 48 V); 400 W motor". |
| X6 | Diagram page 80 · Component list "Diagram pages" | Page lists differ: `-TA1`/`-TA2` have page 31 in the diagram only; `-KE1` is "30, 43" against "43"; `-KE2` is "30, 40–44" against "40–44". Overview pages are listed for some devices (`-KE5`, `-BG5`, `-KE3`) and not for others (`-SJ1`, `-BG1`, `-TA1`). | One rule for both lists. Proposed: every page where the tag is drawn, overview pages 10–12 included. |
| X7 | Component list row 39 | The Wi-Fi card points to diagram page 11, but page 11 does not show Wi-Fi. | Add the Wi-Fi link and the antennas to page 11, or change the page reference to "—". |
| X8 | Component list rows 23, 24 | "M12 plug, 8-pin" has the type "MOC-Y-CABLE". That is the Y-cable `-WG13`, not the plug. | Enter the plug's real type. The Y-cable number 2116199 (diagram page 45) is missing in Cables row 25: add it there. |
| X9 | Manual 3.8 · Diagram pages 61, 62 | The manual says the alarm sound also pulses (1 s on, 2 s off) while the vehicle waits at a stop point. The diagram notes for DO1 do not. | Add the stop-point pulsing to page 61 note 2 and page 62 row DO1. |
| X10 | Manual 4.2 · Manual 3.3, diagram page 12 | The 4.2 row for the safety controller says it evaluates "E-STOP, front scanner and mode selector". 3.3 and the diagram also have the wheel encoders, RESET and the driver feedback. 4.2 has no row for the safety encoders. | Extend the row; add a row "Safety encoders — speed limit and standstill — Yes". |
| X11 | Diagram page 80 · Component list | `-XE1` (chassis earth point) is in the diagram's parts list and not in the component list. | Add a row. |
| X12 | Component list cover · Components sheet | Cover: "one row per occurrence". Sheet heading: "One row per component". Rows 47 and 48 have quantity 2. | "One row per component" in both. |

## 5. Operation manual

### 5.1 Broken or dangling (P1)

| ID | Where | Problem | Fix |
| --- | --- | --- | --- |
| M1 | Contents · end of the body | Contents lists "17. Decommissioning and disposal" and "Annexes A–E". The body ends at chapter 16 and Annex D. 14.2 sends the reader to Annex E. | Add both (drafts in section 9), or take them out of the Contents and out of 14.2. |
| M2 | 10.1 row 5 | "30 % or more on" stops mid-sentence. | D10. |
| M3 | 7.2 step 3 | "Connect the battery" has no full stop and no method. The battery connector is in neither the diagram nor the list (see G3). | Write the step, or mark it `[REVIEW]`. |
| M4 | 8.4 | The list ends with ";" and nothing after it. | Close the list. Add the checks for the speed limit, standstill and power-off check (M5). |
| M5 | 10.1 row 8 · 15.2 · 15.4 | Three references to checks that chapter 13 does not have: "Chapter 13, daily test" for the protective field; "Motor power cut-off: Check (chapter 13)"; "safe speed check (chapter 13)" and "STO check". | Add the rows to chapter 13 (drafts in section 9). |
| M6 | 13, 15.2, 15.4 | The "By" column uses O and M with no key. | One line under each table: "O = operator, M = maintenance personnel". |
| M7 | 4.3 · 10.6 | RESET "ends a stopped run" (4.3) against "RESET while a run is active: run ends; vehicle stops" (10.6). | Use the 10.6 wording in 4.3. |
| M8 | 14.2 · 4.5 | The alarm list tells the reader to press **Recover**. 4.5 names only Acknowledge and Restart. | Add Recover to the Home row in 4.5. |
| M9 | 14.2 `UNCLEAN_SHUTDOWN`, drive faults | The action is to switch the motor-driver circuit breakers off and on. Nothing says where they are, and 15.1 allows work in the electrical box only for an electrically skilled person. | Say where the breakers are and who may operate them. |

### 5.2 Missing data (P2)

| ID | Where | Missing | Proposed content |
| --- | --- | --- | --- |
| M10 | Related documents | "Software documentation" is cited six times (1.2, 4.5, 4.7, 6.2, 8.3, 14.2) and is not in the table. Also cited and not listed: the "verification report" (13) and the "commissioning record" (8.6). The nanoScan3 and MLS rows have no document number. | Add three rows. Fill the two SICK numbers from the PDFs in hand. |
| M11 | 1.3 nameplate figure | Serial number and unladen mass are blank; the table under it says 150 kg. | Fill the figure after D2. Consider adding rated drawbar pull and battery mass to the plate. |
| M12 | 2.2 ambient temperature | "+5 °C to +40 °C for short periods; +30 °C 24 h average" reads as if +5 to +40 were only for short periods. | "+5 °C to +40 °C; average over 24 h not above +30 °C". Confirm 30. |
| M13 | 3.8 | Signals are "tone 1" and "tone 2". | Describe the two sounds as an operator hears them (which melody, continuous or pulsed). |
| M14 | 4.3, 15.1 | The main switch is in the controls table, but nothing says where it is. 15.1 says to padlock it, and the component list has no lock-out device for `-QA1`. | Add the position to 4.1 or 4.3. Add the lock-out device to the component list, or change 15.1. |
| M15 | 5.1 | "Maximum train length 4000 mm": the hazard-zone figure uses trolleys 1550 mm long, so two trolleys with drawbars already come to about 4000 mm without the vehicle. | State "trolleys only, without the vehicle" or correct the value. |
| M16 | 12 | No charging procedure. No charger type or output. No charging socket position. Nothing on whether the vehicle can drive with the charger connected. "16-cell LiFePO₄" is 51.2 V nominal, the text says 48 V. | Add 12.3 "Charging" (connect, indications, disconnect) and a charger row. Write "48 V class (51.2 V nominal)". Mark the drive-inhibit question `[REVIEW]`. |
| M17 | 14.2 | No operator alarm for low battery, although 12.1 says "the vehicle warns". `agv_core/alarms.py` has no battery code. No word on what the operator sees after a speed-limit or standstill trip. | State what is shown today. If nothing: say so in a `[REVIEW]` box. |
| M18 | 7, 11.3 | No transport or lifting instructions (lifting points, mass). 11.3 says the brakes cannot be released by hand, so there is no way described to move a vehicle with a flat battery. | Add 7.3 "Transport and lifting" and a line on recovering a dead vehicle. Values needed from the mechanical design. |
| M19 | 15.2 | No rows for the battery (terminals, charge state in storage), the fans, or the E-STOP and safety controller beyond chapter 13. | Add the rows. |
| M20 | 16.1, 16.2 | Not given: rated drawbar pull, ground clearance, protection rating, battery mass, floor loading (6.1 asks for "load capacity" without a figure), the vehicle's own noise level. Horn "85 dB(A) at 1 m" is not confirmed: PATLITE BK-series sheets found give up to 95 dB at 1 m. | Fill from the mechanical data. Check the horn value against the BK-24AE-K sheet and the volume setting. |
| M21 | Document information | Language is English only, and the vehicle is for the Indonesian market. | Add "Original instructions" and one line that an Indonesian edition follows. Owner's call. |
| M22 | Annex D | STO is defined, but the text says "motor power cut". 16.1 uses "HWTO" and 15.4 uses "STO check" and "STO wiring jumpers". BMS is not defined. | Either use "motor power cut" in 15.4 and 16.1 too, or add HWTO and BMS to the glossary. |

### 5.3 Wording and format (P3)

- 16.1: "Web interface over Wi-Fi 2.4/5 GHz;" ends with a semicolon; "holding brake." ends with a full stop inside a table.
- 12.1: "8-10   h" (hyphen, extra spaces). 6.1: "+/- 5mm over 2m" against "±5 mm over 2 m" in 2.2. 6.2: "30-50 mm" against "30–50 mm" in the figure.
- Thousands: "1 000 kg" and "2 100 mm" against "1000 mm", "2100 mm", "2500 mm", "4000 mm". Pick one.
- "About this manual" says distances are in mm; 3.4 gives the fields in m.
- 4.5: write the address as `http://192.168.2.110:5001/` and say it is set per site.
- "Keep this manual": "Request manufacturer for latest version." → "Ask the manufacturer for the latest version."
- 10.2 step 2 does not say "E-STOP released"; 8.2 step 1 does.

## 6. Circuit diagram

| ID | Page | Problem | Fix | Prio |
| --- | --- | --- | --- | --- |
| C1 | 41 | Field sizes (X1). Only lengths are given for the warning fields. | After D1; give length × width for all three. | P1 |
| C2 | 44 | Q1 and Q2 carry "SF1, 2, 6". Pages 12, 42 and 80 put "SF1, 2, 6–8" on the same path. | "SF1, 2, 6–8" on page 44. | P1 |
| C3 | 62 | "DO9–DOB spare, not wired". The module has DO0…DOF and page 61 says "DO8 … DOF not wired". | "DO9–DOF". | P1 |
| C4 | 61 | Note 5 cites "JIS sheet 09", a drawing that is not part of this set. | Delete the reference; keep "as built". | P1 |
| C5 | 20, 80 | `-TA3` 6.25 A, `-TA4` 8.3 A (X3, X4). On page 20 the `-TA3` box has no type, the `-TA4` box has. | Correct the currents; print "SD-150C-24" in the `-TA3` box. | P1 |
| C6 | 60 | `-SJ5` MANUAL ARM is "1 NC" with no position table. Note 3 says OFF = DI08 off, but a break contact drawn at rest is closed. The reader cannot tell which position closes 11-12. | Add a position table like the one for `-SJ4` on page 40. | P2 |
| C7 | 11, 51 | One CAN termination only (in `-TF1`). The far end is not shown. The battery BMS has no node ID and no protocol. | Add the far-end terminator when known (`-RA1` is reserved), or a note "far-end termination: open point". Add the BMS node ID. | P2 |
| C8 | 5 | The earthing of the 24 V / 12 V side is not stated. Page 5 says only that 48 V is floating; page 30 says "`-KE4` PE not connected". | One line under Potentials: 1N24 / 1N12 joined to the chassis or floating. | P2 |
| C9 | 20 | No charging socket, no battery connector or battery switch (manual 7.2 "connect the battery", 14.3 "battery switched off"). | Draw them on page 20 (`-XD1` is reserved for the charging socket), or note them as not yet drawn. | P2 |
| C10 | 11, 75 | The display `-PH1` has a supply (page 31) and no data connection to `-KE3`, although it shows the web pages. | Add the video / touch cable to page 11 and page 75. | P2 |
| C11 | 45 | "ENC1 = left wheel" was still marked to confirm on 2026-11-09. | Confirm on the vehicle. | P2 |
| C12 | 42, 45 | As-built state of `-KE5`, encoders and Q3 → DI09 (D9). | After D9. | P1 |
| C13 | 75 | Most lengths are blank. Note 2 already says why. | Leave. | — |
| C14 | 76 | "Open: reprint the wire markers…" is an internal to-do printed on the sheet. | Leave if the reprint is still open when the package is sent; it is honest. | — |

## 7. Component list

| ID | Where | Problem | Fix | Prio |
| --- | --- | --- | --- | --- |
| L1 | PDF footer | Pages 1–3 say "Page n of 5", page 4 says "Page 4 of 4". The PDF has 4 pages. | Export the whole workbook in one go, and check the Cover and Components sheets for a blank extra page. | P1 |
| L2 | Rows 23, 24 | Wrong type (X8). | X8. | P1 |
| L3 | Row 49 | 250 mm (X2). | D3. | P1 |
| L4 | Rows 7–10, page lists | X3, X4, X5, X6. | As in section 4. | P1 |
| L5 | Row 1 | Battery type is "48 V 50 Ah LFP", a description and not a model. | Model number from the battery label; add the mass. | P2 |
| L6 | Rows 29–33 | The MANUAL ARM selector and the four buttons all have the type HY-PA04. | If HY-PA04 is the whole pendant station, list it once as the station and the selector with its own type. | P2 |
| L7 | SICK rows | Only the scanner has an order number (1100333). | Add: FX3-CPU000000 = 1043783, FX3-XTIO84002 = 1044125, FX3-MPL000001 = 1043700 (all three confirmed in distributor listings). FX3-MOC000000, the encoders, the line sensor, the plugs and cables: take from the delivery notes. | P2 |
| L8 | Missing rows | `-XE1`; charging socket; lock-out device for `-QA1`; Wi-Fi antennas; display data cable; far-end CAN terminator; battery connector. | Add as they are settled (C7, C9, C10, M14). | P2 |
| L9 | Cables rows 1–5 | Manufacturer "First cable". | Confirm it is the brand on the reel. | P3 |
| L10 | Cover | Cover wording (X12). | X12. | P3 |

## 8. Points the reviewer is likely to raise

These are design questions, not editing errors. They are listed so the answers can be prepared. They are my reading of the documents; none was checked against the text of a standard.

| ID | Point | What the documents say now |
| --- | --- | --- |
| R1 | **Stopping.** At 0.85 m/s the vehicle moves 0.11 m in the scanner response time alone, so a 0.33 m (or 0.43 m) protective field cannot be met at that speed. Also: holding 1.0 m/s² with a 1 000 kg unbraked train needs about 1 150 N at the two drive wheels, and the vehicle weighs about 1 470 N in total. The same doubt applies to "maximum drawbar force 1 200 N" in 5.1. | The `[REVIEW]` box in 3.4 covers the first half. Add the traction point and D7 to it. |
| R2 | **Field width.** The protective field is 0.80 m wide and the trolleys may be 1.20 m wide. With the semicircle, the field reaches only about 0.21 m ahead of the front corners of the 574 mm body. | 3.5 lists the side risk in general terms. |
| R3 | **MANUAL mode.** The protective field is muted, hold-to-run is a software function, the speed limit applies in AUTO only, the speed is 0.60 m/s, and the web jog works for anyone on the network. | Stated openly in 3.3, 3.5, 4.5, 9.3. |
| R4 | **Emergency stop.** One device, on the control panel. None on the pendant; MANUAL ARM is expressly not one. | 4.4. |
| R5 | **Mode selector.** One contact into `-KE2:I7`, not test-pulsed. A short to 24 V on that wire mutes the protective field in AUTO. The second contact goes to the non-safety I/O module. | Pages 40, 44. |
| R6 | **Converter feeders.** `-WD4` and `-WD5` (1.5 mm²) branch off 1P48 behind the 32 A main breaker only. `-FC3` and `-FC4` sit on the converter outputs, where the converters limit the current themselves. | Page 20. |
| R7 | **Floating 48 V.** CAN GND runs from the drivers to the controller's 12 V side, and the BMS shares the CAN bus. If the driver or the BMS joins CAN ground to battery minus inside, 48 V is not floating. | Pages 5, 20, 51. Check the BLV and battery manuals. |
| R8 | **Battery voltage.** The battery runs up to 58 V; the drivers are listed as 24–48 V DC. `agv_core/config.py` notes a 63 V overvoltage trip, so it probably fits, but the list should give the permitted range. | Component list rows 9, 10. |
| R9 | **No validation data.** No performance levels, no Flexi Soft configuration report or checksum, no scanner configuration report. They were taken out on purpose on 2026-11-09. | Have them ready as separate sheets. |
| R10 | **Charging.** No drive inhibit with the charger connected is shown. | M16, C9. |
| R11 | **RESET is yellow.** Blue is the usual colour for a reset button; yellow normally means "abnormal condition". | 4.3, component list row 27. |

## 9. Drafts for the missing pieces

All drafts follow the manual's plain style. Items in `[brackets]` need the owner.

**Chapter 13, new rows** (M5)

| Check | How | Pass criterion | Interval | By |
| --- | --- | --- | --- | --- |
| Protective field, daily | In AUTO, with the vehicle waiting for START, put the test object (50 mm diameter) in the protective field and press START | The vehicle does not move; Home shows `FIELD_PROTECTIVE`. It moves 2 s after the object is taken away | Daily | O |
| RESET and restart | After E-STOP, release it and press START without RESET | The vehicle does not move until RESET, then START | Weekly | O |
| Motor power-off check | `[method: e.g. unplug the feedback wire of one driver, then RESET]` | RESET is not accepted | Every 3 months and after any change | M |
| Speed limit and standstill | `[method: compare both encoder speeds with the vehicle speed in the safety controller diagnostics; trip test with a lowered limit]` | Both encoders agree; power is cut above the limit; RESET is refused while a wheel turns | At commissioning and after any change | Commissioning engineer |

**Chapter 8.4, closing bullets** (M4): "check the speed limit, the standstill monitoring and the motor power-off check (chapter 13); record the configuration checksums of the safety controller and the scanner in the commissioning record."

**Chapter 17, Decommissioning and disposal** (M1)

1. Take the vehicle out of service: switch off, lock out (chapter 15.1), disconnect and remove the battery.
2. Delete the site data from the vehicle controller (routes, network names and passwords).
3. Battery: lithium iron phosphate. Do not put it in general waste. Hand it to a licensed hazardous-waste handler under the rules in force at the site, or return it to the manufacturer.
4. Electronics (controllers, drivers, scanner, sensors): electronic waste.
5. Chassis, wheels, covers: sort by material and recycle.
6. Tell the manufacturer the serial number of the scrapped vehicle.

**Annex E, Alarm list** (M1): generate with `python3.11 -m agv_core.alarms --md` and paste. The catalogue has 105 codes; the manual's operator list has 37. The generated list also holds codes for features this edition leaves out (map navigation, RFID, station link, rear scanner), so filter it to the tape product or head the annex "all codes of the vehicle software".

## 10. Order of work and rebuild

1. Get the answers to D1–D11.
2. Do the P1 items of sections 4 to 7 in the masters, in this order: `operation-manual-doc.md`, the `iec-page-NN.html` files with `data/project.js`, `component-list.xlsx` (by hand; do not regenerate it).
3. Do the P2 items that have a value; put the rest in `[REVIEW]` boxes.
4. Rebuild:
   - manual: `documentation/operation-manual/build/build-pdf.ps1`;
   - diagram: `documentation/electrical/kit/check-set.ps1`, then `kit/print-set.ps1`;
   - component list: Excel export of the whole workbook to PDF.
5. Copy the four files into the package folder under their `IGP-IPR-…_RevA_…` names.
6. Check again: page counts (manual page n of N, diagram "Number of pages", list footer); every "chapter n" and "page n" reference resolves; the values in D1–D5 read the same in all three documents.

Rules that still apply while editing: no reviewer's name in the documents or folder names; no standards citations beyond the manual's short list; no performance levels; tags stay out of the manual; the revision stays A until the package has gone out.

## 11. Sources for the looked-up values

- Mean Well SD-100C-12, 12 V 8.5 A: <https://www.bravoelectro.com/sd-100c-12.html>, <https://masterelectronics.com/en/mean-well/sd100c12-11953221.html>
- PATLITE BK series sound level: <https://www.wolfautomation.com/content/patlite-bkseries-datasheet.pdf> (series sheet, not the BK-24AE-K itself)
- Oriental Motor BLVD-KRD supply 24–48 V DC: <https://catalog.orientalmotor.com/item/all-categories/blvd-krd-brushless-dc-motor-driver/blvd-krd>
- SICK FX3-MPL000001 = 1043700: <https://uk.farnell.com/sick/fx3-mpl000001/system-plug-safety-controller/dp/4400518>; FX3-XTIO84002 = 1044125: <https://bpx.ie/store/product/1044125>; FX3-CPU000000 = 1043783: <https://www.all4sps.com/mediafiles/Sonstiges/FX3-CPU000000.pdf>
