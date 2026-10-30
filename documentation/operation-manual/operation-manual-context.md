# Context for editing the Operation Manual (operation-manual.docx)

This file gives an assistant or editor who has no access to the project's code, chat history or standards research everything needed to keep working on `operation-manual.docx`. Read it in full before changing the manual.

Status as of 2026-10-29: Revision A draft, 39 pages, for TÜV SÜD's preliminary review. The Word file is now the master copy. The older `operation-manual.md` in the same folder is superseded.

---

## 1. The project in brief

- **Product:** a driverless towing vehicle (AGV, a "driverless industrial truck" in ISO 3691-4 terms). It follows magnetic tape on the floor and tows trolleys. It has two driven wheels (differential drive). The product name, model and manufacturer details are still placeholders.
- **Why the manual exists now:** TÜV SÜD asked for a preliminary check of three documents: circuit diagrams, the operation manual and the component list. This is a minimum viable draft. It shows the right structure and fills in what is known today. TÜV SÜD will help build the full documentation later. Full compliance is not the goal of this revision.
- **Markets:** Indonesia now. The manual is written so that CE marking in the EU is possible later.
- **Language:** English first. Bahasa Indonesia later, where required.
- **Audience:** one manual for all readers: operators, maintenance personnel and commissioning engineers. Each chapter heading carries audience markers: [O] operator, [M] maintenance, [C] commissioning engineer.

## 2. Scope decisions (binding — do not undo)

1. **The vehicle only, not the whole system.** The manual covers the vehicle as a machine: a line-following tow tractor with a vehicle controller (industrial PC) and a safety controller.
2. **Navigation features stay out of the safety story.** The vehicle software also has these features:
   - RFID stop-point tags;
   - route markers and stop-point programming;
   - map-based navigation (SLAM/AMCL);
   - point-to-point positioning moves.

   They decide *where* the vehicle stops or how fast it drives on a section. None of them is a safety function. The manual names them only as "navigation features", says they are not safety-relevant, and refers to separate software documentation. Do not describe them in detail. Do not use the words RFID, SLAM, AMCL, ROS or any software module names in reader text.
3. **What the manual describes:** the production design as drawn on the circuit diagrams, with the safety controller fitted. It does not cover development test configurations.
4. **Design gaps are written down, not hidden.** Where the design cannot yet support what the manual must say, the text carries a **[REVIEW]** note (grey box). These notes are for discussion with TÜV SÜD. Do not remove one unless the gap is closed or the owner decides.

## 3. Owner decisions already made

| Topic | Decision |
| --- | --- |
| Product name | Placeholder `[PRODUCT NAME]` until decided |
| Application | Towing trolleys (not carrying a load on top) |
| Hitch | Manual pin or hook hitch. Which one is still open |
| Charging | Manual plug-in charging with an external charger |
| Towed mass | Max. 600 kg (all trolleys plus load) |
| Speeds | AUTO max. 0.85 m/s (0.50 m/s normal). MANUAL max. 0.60 m/s |
| Floor | Level only, 0 % gradient |
| Safety scanners | Two: one front, one rear |
| MANUAL mode | The scanner protective stop is **muted** in MANUAL. Compensation is hold-to-run controls and the reduced manual speed |
| Engineer PIN | Exists. Deliberately **not** printed in the manual. It is handed over at commissioning (manual 8.6). Never add it |
| Vehicle IP address | Site-specific. Keep it as a placeholder in the manual |

## 4. Standards frame

The manual follows these documents:

- **Structure:** ISO 20607:2019 (the safety-relevant parts of a machinery instruction handbook) and IEC/IEEE 82079-1:2019 (instructions for use).
- **Content:** the information-for-use clause (clause 6) and Annex A (operating zone) of ISO 3691-4:2023, and the Machinery Directive 2006/42/EC Annex I 1.7.4.2 checklist.
- **From 20 Jan 2027:** Regulation (EU) 2023/1230 Annex III 1.7.4.

Write to the Regulation, because it replaces the Directive during this project.

### Verified register (research done 2026-10-29)

| Standard | Edition to cite | Relevance to the manual | Notes |
| --- | --- | --- | --- |
| ISO 3691-4 | 2023 (Ed. 2) | Product standard. Clause 6 covers information for use; Annex A covers the operating zone | Harmonised C-type under the Machinery Directive from 15 May 2024 (Decision (EU) 2024/1329). Ed. 3 at DIS stage |
| ISO 20607 | 2019 | Handbook structure and safety content | Harmonised (Decision (EU) 2020/480), but only partially: noise information, item 1.7.4.2(u), is excluded |
| IEC/IEEE 82079-1 | 2019 (Ed. 2) | General rules for instructions for use | Not harmonised. Ed. 3 at committee draft |
| ISO 12100 | 2010, clause 6.4 | Information for use as a risk-reduction measure | Harmonised type-A |
| ISO 13849-1 | 2023 | Performance levels (PL) of safety functions | Harmonised. The 2015 edition stays valid in parallel until 15 May 2027 |
| ISO 13849-2 | 2012 | Validation of safety functions | — |
| **EN 1175** | **2025** | **The electrical standard for the vehicle (owner decision 2026-10-30)**: battery, wiring, electrical installation. It excludes automatic-operation functions of driverless trucks, which stay under ISO 3691-4 | Replaces EN 1175:2020 from 1 Dec 2025 |
| IEC 60204-1 | 2016 + AMD1:2021 (EN 60204-1:2018 + A1:2025) | Not the governing standard. Used only as good practice for drawings, labelling and wire colours | Ed. 7 around 2028 |
| ISO 7200 | 2004 | Title block and document-header fields (used on the manual's Document information page) | — |
| IEC 81346-1 / -2 | 2022 / 2019 | Reference designations (tags), see section 7 | IEC 81346-2 Ed. 3 at FDIS stage |
| IEC 62027 | 2011 | Parts list keyed by tag, one row per occurrence (component list) | — |
| Directive 2006/42/EC | until 19 Jan 2027 | Annex I 1.7.4 (instructions); Annex VII A (technical file includes a copy of the instructions) | — |
| Regulation (EU) 2023/1230 | from 20 Jan 2027 | Annex III 1.7.4 (instructions). Article 10(7) allows digital-only instructions, with conditions (paper copy free on request; available online for the machine's life and at least 10 years) | Article 10(7) conditions taken from secondary sources |
| ISO 3864-2, ISO 7010, ANSI Z535.6 | — | Safety message layout and safety signs | Not verified; used as general practice |

**Not yet determined:**
- **Indonesia:** whether these apply to an industrial AGV is an open question for TÜV SÜD.
  - Permendag 26/2021 Lampiran F: Bahasa Indonesia manual and warranty card for listed electronics.
  - Permendag 25/2021: Bahasa Indonesia labels.
  - Permenaker 8/2020: K3 inspection and testing (*riksa uji*) for lifting and conveying equipment, partly revoked by Permenaker 11/2026.
- **EU, other acts:** Radio Equipment Directive (only if a radio module is fitted), battery rules, EMC standard (EN 12895 is marked `[confirm]`).

**Useful facts already used in the manual:**
- ISO 3691-4 assumes normal ambient conditions: +25 °C average, +40 °C short term, altitude up to 2 000 m.
- Indonesian factory floors can exceed the +25 °C average. Manual 2.2 has a NOTICE about this.
- Safety messages use four signal words (DANGER, WARNING, CAUTION, NOTICE) and four parts: signal word, hazard, consequence, avoidance.

## 5. How the Word file is built (keep it this way)

- **Page:** A4. Margins 25 mm left, 20 mm top, bottom and right. Arial 10 pt body text, black only.
- **Styles:** use Word's built-in styles only.
  - **Title:** the cover title.
  - **Heading 1:** chapters, and the unnumbered front-matter sections.
  - **Heading 2:** sections.
  - **Table Text:** Arial 9 pt, for all table cells.
- **Numbering:** chapter and section numbers are typed into the heading text ("3.3 Safety functions"). They are not Word auto-numbering. When you insert or move a section, renumber by hand and fix the cross-references in the text ("chapter 10.4"). Cross-references are plain text, not fields.
- **Contents:** a Word table of contents field on page 3. Update it after edits (right-click, Update Field, entire table).
- **Header and footer:** the header carries the product name. The footer carries the document number, the revision, "Original instructions" and "Page X of Y".
- **Tables:** plain grid, grey header row that repeats across pages. Rows do not break across pages.
- **Safety messages:** a one-cell table with a thick black border. The first line is bold: "⚠ WARNING — Hazard." Then the consequence, then bullet points with how to avoid it.
- **[REVIEW] notes and the draft banner:** a one-cell table with a thin grey border and grey shading.
- **Image placeholders:** a one-cell table with a dashed border, about 3 cm high, holding italic text "[IMG-cc-nn] description". The image register at the end lists all 15 and whether each is needed (☐ to tick). To insert a picture, replace the text in the box.
- **Placeholders:** highlighted yellow:
  - `[TBD: …]`: text still to be written;
  - `[VALUE: …]`: a number or fact to be measured or taken from design data;
  - `[confirm]`: written from project records, must be checked on the built vehicle;
  - `[tag]`: reference designation not yet assigned;
  - `[PRODUCT NAME]`, `[MODEL]`.

  When you fill one, remove the brackets and the highlight. When you add a new placeholder, highlight it yellow.
- **Fonts for special text:**
  - Controls on the vehicle: bold CAPITALS (**E-STOP**, **RESET**, **START**, **MANUAL / AUTO**, **MANUAL ARM**).
  - Web pages: bold (**Home**, **Run**, **Manual**, **Alarms**).
  - Alarm codes and messages shown by the vehicle: Consolas (for example ESTOP, TRACK_LOST, READY).
- **Editorial sections:** the draft conventions table on page 1, the "Editorial: review notes summary" and the "Editorial: image register" are all removed before release.

## 6. Writing rules

- Plain English, short sentences, one idea per sentence. Present tense, active voice. Instructions in the imperative ("Press **RESET**.").
- Procedures are numbered steps, one action per step. A warning comes **before** the step it applies to, not after.
- Never invent a number. If a value is not in this file, write a highlighted `[VALUE: what is needed]`.
- Never state that the vehicle complies with a standard, or that a PL is achieved. Achieved PL and PFHd values are `[VALUE]` until the safety validation is done. Only design targets may be stated.
- Use the same term every time:

| Use | Do not use |
| --- | --- |
| vehicle | robot, AGV (except in the glossary and the type description), AMR, cart |
| trolley, trolley train | cart, payload, wagon |
| stop point | station (although the alarm code is AT_STATION) |
| protective field, warning field 1 / 2 | safety zone, slow zone |
| safety controller | safety PLC, Flexi Soft (except in technical data and the description) |
| vehicle controller | IPC, PC, computer, ROS |
| motor driver; "the drives" for both | servo, inverter, amplifier |
| safe torque off (STO) | HWTO (except next to the Oriental Motor name) |
| line sensor, magnetic tape | MLS, track (as a noun for the tape: "tape") |

## 7. Reference designations (tags)

Each physical component gets one IEC 81346 tag. The same tag appears on the circuit diagram, in the component list, in the manual and on the label on the vehicle. In the manual these are still `[tag]` placeholders. The tags will come from the component list, which is not yet written.

The minimum scheme agreed for the draft:
- **Product aspect (-) on every component**, for example -Q1, -K3, -B2.
- **Location (+) at enclosure level only**, for example +EB electrical box and +FR front panel.
- **Terminals** written as -X1:4 (IEC 61666).
- **Function aspect (=):** deferred.

The existing circuit diagrams use JIS-style device names (MCB-01, MCB-02 and so on). The component list will carry both until the drawings move to IEC tags.

Proposed tags (IEC 81346-2:2019 two-letter classes, from `documentation/electrical/01-schematic-iec/designation-map.md`, 2026-10-30). They are still proposals until the component list is issued:

| Tag | Component |
| --- | --- |
| `+EB-QA1` | Battery main breaker (main switch) |
| `+EB-FC1`, `-FC2` | 48 V feeder breakers, left / right drive |
| `+EB-FC3`, `-FC4` | 24 V and 12 V bus breakers |
| `+BT-GB1` | Battery |
| `+EB-TA1`, `-TA2` | Motor drivers left / right |
| `+EB-TA3`, `-TA4` | DC/DC converters 24 V / 12 V |
| `+VH-MA1`, `-MA2` | Motors left / right |
| `+EB-KE1`, `-KE2` | Safety controller main module / I/O module |
| `+EB-KE3` | Vehicle controller (industrial PC) |
| `+EB-KE4` | I/O module |
| `+FR-SJ1` | **E-STOP** |
| `+FR-SJ2` | **START** |
| `+FR-SJ3` | **RESET** |
| `+FR-SJ4` | **MANUAL / AUTO** selector |
| `+FR-SJ5` | **MANUAL ARM** |
| `+PD-SJ6`…`-SJ9` | Pendant **FORWARD**, **REVERSE**, **LEFT**, **RIGHT** |
| `+VH-BG1`, `-BG2` | Safety laser scanners front / rear |
| `+VH-BG3` | Line sensor |
| `+VH-PJ1` | Horn |
| `+EB-XD1` | Terminal strip |

Locations: `+EB` electrical box, `+FR` front panel, `+VH` vehicle body, `+BT` battery compartment, `+PD` pendant. The old single-letter classes (Q, F, K, S…) are superseded.

## 8. Vehicle facts (from the project's design files)

### 8.1 Mechanics and drive

| Item | Value | Status |
| --- | --- | --- |
| Drive | Differential drive, 2 driven wheels plus castors | castors `[confirm]` |
| Track width (wheel centres) | 487 mm | design data |
| Drive wheel diameter | 180 mm | design data |
| Motors | 2 × Oriental Motor BLMR6400SKM-GFV-B, 400 W brushless, gearhead 1:30, max. motor speed 4 000 r/min | design data |
| Holding brakes | Electromagnetic, in each motor; applied whenever the motor is not powered | `[confirm]` |
| Motor drivers | 2 × Oriental Motor BLVD-KRD, commanded over CANopen | design data |
| Pushing by hand | Not possible: the brakes stay applied when the drives are off. The drivers' brake-release ("FREE") function is deliberately blocked in the software. No manual brake release exists | design fact; see [REVIEW] 7 |
| Unladen mass | approx. 150 kg | estimate, unverified |
| Dimensions, IP rating, noise | unknown | `[VALUE]` |

### 8.2 Electrical

- **Battery:** 48 V nominal, with a battery management system. The vehicle warns below 42 V and above 56 V. Battery chemistry, capacity, charger model and charging time are unknown.
- **Power path:** battery → main breaker (MCB-01).
  - MCB-02 (10 A): left motor driver.
  - MCB-03 (10 A): right motor driver.
  - MCB-04: switched 24 V control supply.

  Whether the main breaker can be locked off, and whether it is the "main switch" in the manual, is `[confirm]`.
- **Control voltage:** 24 V DC.
- **Vehicle controller:** industrial PC, model unknown. Commands the drives over CAN. The line sensor and the battery management system are on the same CAN bus.
- **I/O module:** CK-EC5163, 16 digital inputs and 12 relay outputs, Ethernet (Modbus TCP).

| I/O module input | Device |
| --- | --- |
| DI00 | **START** push-button |
| DI01 | **RESET** push-button (second contact; the first goes to the safety controller) |
| DI02 | **MANUAL / AUTO** selector (second contact; the first goes to the safety controller) |
| DI03–DI06 | Pendant **FORWARD**, **REVERSE**, **LEFT**, **RIGHT** |
| DI08 | **MANUAL ARM** switch (switch type not yet specified) |

| I/O module output | Function |
| --- | --- |
| DO0 | Horn, sound 1 = **movement sound** |
| DO1 | Horn, sound 2 = **alarm sound** |
| DO8 | Switched on while the motors turn; nothing is connected. A free output for a future warning lamp or beacon |

The horn is a PATLITE audio horn.

### 8.3 Safety chain (hard-wired)

**Safety controller:** SICK Flexi Soft FX3-CPU0 plus an FX3-XTIO84002 I/O module `[confirm module variant]`.

| Safety controller terminal | Connected to |
| --- | --- |
| X1 → I1, X2 → I2 | **E-STOP** push-button, 2 NC contacts, turn to release (dual channel with test pulses) |
| I3 / I4 | EDM feedback from the left / right motor driver (confirms that torque is really off) |
| I5 / I6 | Scanner OSSD 1 / OSSD 2. **Only one OSSD pair is drawn for two scanners. Which scanner it belongs to and how the second is wired are open** ([REVIEW] 4) |
| I7 | **MANUAL / AUTO** selector, first contact (the line labelled "MANUAL"). Which position closes the contact is not settled on the drawing |
| I8 | **RESET** push-button, first contact |
| Q1 | STO channel 1 (HWTO1) of both motor drivers |
| Q2 | STO channel 2 (HWTO2) of both motor drivers |
| Q3 | Destination open (`[TBD]`) |
| Q4 | Spare |

- **Driver STO rating:** the BLVD-KRD hardwired torque-off is PL d, Category 3, PFHd 2.90 × 10⁻⁷/h per driver (manufacturer data). TÜV SÜD certificate number `[VALUE]`. The factory STO jumpers are removed on both drivers.
- **What the chain does:** **E-STOP** or a protective-field violation makes the safety controller switch Q1 and Q2 off. Torque is removed from both motors and the holding brakes apply. This is a Category 0 stop (`[confirm]`); see [REVIEW] 1. The vehicle controller is not part of any safety function.
- **Restart after E-STOP:** release **E-STOP**, press **RESET**, then press **START** (in AUTO).
- **Restart after a protective-field stop:** automatic, 2 s after the field is clear (AUTO).
- **Mode selector:** in MANUAL the protective field does not stop the vehicle (muted, owner decision). **E-STOP** works in every mode.

### 8.4 Safety laser scanners

- **Scanners:** 2 × SICK nanoScan3 (front and rear), type `[VALUE]`. Resolution 50 mm, response time 130 ms.
- **Front scanner fields, as configured:**

| Field | Length ahead | Width | Effect |
| --- | --- | --- | --- |
| Warning field 1 (outer) | 1.77 m | 1.50 m (±0.75 m) | AUTO speed halved (software) |
| Warning field 2 (inner) | 0.97 m | 1.20 m (±0.60 m) | Controlled stop within 0.40 m (software) |
| Protective field | 0.50 m | 0.80 m (±0.40 m) | Safety stop through the safety controller |

- **Rear scanner fields:** unknown. Its field with trolleys coupled behind is also open.
- **Field validation:** the software's own record of the field configuration is marked "not yet validated". The final values must come from the scanner verification report.

### 8.5 Speeds and motion

| Item | Value | Source |
| --- | --- | --- |
| AUTO normal speed | 0.50 m/s | software setting |
| AUTO high speed | 0.85 m/s (1.7 × normal), only in sections marked by floor markers | software setting |
| MANUAL speed | max. 0.60 m/s straight; 0.39 rad/s turning on the spot | software setting |
| Controlled deceleration | 1.0 m/s² (from the drive ramp setting; unladen) | calculated, `[confirm with load]` |
| MANUAL acceleration | about 2.3 s to full manual speed | software setting |
| MANUAL stop on release | within about 0.2 m from 0.60 m/s | estimate |
| Safety-rated speed limit | none ([REVIEW] 2) | — |
| Pivot / U-turn at track end | Only without trolleys. The vehicle refuses to pivot until the operator has confirmed that the trolleys are released | design fact |
| Stopping distances | Not measured ([REVIEW] 8). At 0.85 m/s the 130 ms scanner response alone uses about 0.11 m of the 0.50 m protective field | — |

### 8.6 Guidance

- **Tape following:** the magnetic line sensor (SICK MLS, under the front of the vehicle) reads the tape position about 50 times per second. The vehicle steers to keep the tape centred.
- **Floor markers:** markers beside the tape set the high-speed sections and pivot points.
- **Lost tape:** if the tape is lost for more than 75 mm of travel, the vehicle stops with TRACK_LOST.
- **Stop points:** programmed by the commissioning engineer, as described in the software documentation.

### 8.7 Controls

- **Control panel:**
  - **E-STOP:** red mushroom, latching, turn to release.
  - **RESET:** blue.
  - **START:** colour `[VALUE]`.
  - **MANUAL / AUTO:** 2-position selector.
  - **MANUAL ARM:** switch that powers the drives for manual driving.
  - Main switch: `[confirm]`.
- **Start-up protection:** a button held, or the selector already in AUTO, at switch-on (or when the panel connection returns) does nothing until it is released and operated again. Inputs are debounced over two 50 ms scans.
- **Pendant:**
  - Wired, four buttons: FORWARD, REVERSE, LEFT, RIGHT.
  - Works only in MANUAL with MANUAL ARM on. Hold to drive, release to stop.
  - Forward or reverse plus left or right drives a curve. Left or right alone turns on the spot. Opposite buttons pressed together cancel.
  - A button already held when the pendant becomes active must be released first.
  - The pendant has priority over the web jog pad.
  - No E-stop and no enabling device on the pendant ([REVIEW] 6).
- **Web interface:**
  - Opened in a browser on a tablet or PC on the vehicle's network, port 5001.
  - Operator pages: **Home** (state, next action, one action button), **Run** (current run, stop points, confirmations), **Manual** (hold-to-drive jog pad), **Alarms** (event log, **Save report**).
  - A status bar on each page: yellow = attention, red = fault or stale data, grey with DISCONNECTED = last known values.
  - Engineering pages (teach, monitor, I/O, parameters) are behind a PIN and described in the software documentation.
  - **No user login** (WARNING in manual 4.5).
  - The web interface **cannot** start AUTO. Only the physical **START** can.
  - The **Manual** jog stops when the browser tab changes, on Space or Esc, or when the connection drops.

### 8.8 Operating sequence (AUTO)

1. **START** pressed (AUTO, prerequisites OK). The drives power up and the **alarm sound plays for 2 s**. Then the vehicle moves.
   - If the drives do not power up within 8 s, the start is cancelled ("Start cancelled: drives did not power up").
   - If a prerequisite is missing, the start is refused, the reason is logged, and the press is not remembered.
2. While driving:
   - warning field 1 occupied: half speed;
   - warning field 2 occupied: controlled stop;
   - protective field violated: safety stop.

   It resumes by itself when the fields clear (2 s after a protective stop).
3. At a stop point the vehicle stops and waits (AT_STATION) until **START**. The drives stay on at a stop point.
4. **RESET** during a run ends the run. Turning the selector out of AUTO stops the vehicle at once and ends the run (AUTHORITY_LOST).
5. There is no trolley sensor. The operator confirms coupling or release on the **Run** page when asked (PAYLOAD_UNCONFIRMED otherwise).

### 8.9 Horn behaviour (correct version)

| Sound | When it plays |
| --- | --- |
| Sound 2, alarm sound (DO1) | (a) the 2 s after **START** before the vehicle moves; (b) during an AUTO run while the protective field is violated or warning field 1 or 2 is occupied |
| Sound 1, movement sound (DO0) | Whenever the wheels turn, **in any mode including MANUAL**. It is silenced while the alarm sound plays, so the sound changes when a field is occupied |

The horn is driven by software, so it is not safety-rated. There is no visual warning device ([REVIEW] 5).

### 8.10 Monitoring thresholds (warnings in the event log)

| Item | Warning | Trip |
| --- | --- | --- |
| Motor driver temperature | 70 °C | 85 °C |
| Motor temperature | 80 °C | 95 °C |
| Battery bus voltage | warns below 42 V and above 56 V | — |

## 9. Alarms

- **Source:** the vehicle software's alarm catalogue. The manual's table 14.2 holds the operator-relevant codes, with the vehicle's own wording shortened.
- **Excluded codes:** alarms from navigation features (stop-point tag reader, map navigation, positioning moves) are deliberately left out. They belong in the software documentation.
- **Annex E:** will hold the complete list, generated from the software at release.
- **Known mismatch:** the software's TRACK_LOST text tells the operator to "push the vehicle back onto the tape". That is impossible (brakes). The manual says to drive it back in MANUAL. The software text is to be fixed in the code, not in the manual.

## 10. Open items

### 10.1 [REVIEW] design gaps (for TÜV SÜD; summarised at the end of the manual)

1. **Stop category:** Category 0 stops with a trolley train. A Category 1 controlled stop (SS1) is not built.
2. **Safe speed:** no safety-rated speed monitoring. The speed limits are software only.
3. **Manual mode:** the protective field is muted. Compensation (hold-to-run, 0.60 m/s, movement sound) is software only.
4. **Rear scanner:** its wiring into the safety controller, and its field with trolleys coupled, are not defined.
5. **Visual warning:** no beacon or lamp. DO8 is a free output that follows motion.
6. **Pendant:** no E-stop, no enabling device.
7. **Rescue:** no way to release the brakes without power, so freeing a trapped person depends on the vehicle being drivable (manual 11.3).
8. **Stopping distance:** not measured, against a 0.50 m protective field.
9. **Standards list:** open for Indonesian rules, the Radio Equipment Directive and battery rules.

### 10.2 Corrections still to make in the Word file

1. **Horn (section 8.9 of this file):**
   - **3.8 Warning devices:** the table has the sounds wrong. Sound 1 = movement sound while the wheels turn in any mode. Sound 2 = alarm sound, 2 s before moving after **START**, and while a field is occupied in AUTO.
   - **3.5 Residual risks**, "Unmonitored manual driving": add the movement sound to "What protects you".
   - **9.1 Overview table:** add a row "Warning sound": AUTO = alarm sound before start and at field events, movement sound while driving; MANUAL = movement sound while driving.
   - **10.1 daily check 7:** "Alarm sound for 2 s after **START**; movement sound while driving".
   - **14.1:** replace "The horn [confirm: alarm sound]" with "The alarm sound plays in AUTO while a scanner field is occupied".
2. **Electrical standard (owner decision 2026-10-30):** in "Regulations and standards" → "Standards applied in the design", replace the row "EN 60204-1:2018 | Safety of machinery — Electrical equipment of machines…" with "EN 1175:2025 | Safety of industrial trucks — Electrical/electronic requirements". Do not list EN 60204-1.
3. **Rear scanner — owner to confirm before editing:** on 2026-10-30 the owner decided, for the circuit diagrams, that the rear scanner is **not fitted in this revision**. The manual still describes front and rear scanners in 3.3, 3.4, 4.1, 4.2, 5.2, 8.4, 10.1, 13 and 16.1, and [REVIEW] 4. Ask the owner whether the manual should follow (one front scanner; rear safety function SF3 not present). Do not change it without that answer.
4. **Wire colours:** no manual text depends on them. The wiring changes to black (48 V power) and blue (control and safety) before the circuit diagrams are issued.

### 10.3 Assumptions marked [confirm] in the manual

- No driving in MANUAL with trolleys coupled.
- **RESET** or the selector is the normal way to stop between stop points; **E-STOP** is for emergencies.
- **RESET** during a run gives a controlled stop.
- There is a single **E-STOP** button.
- The main switch is the battery main breaker and can be locked off.
- How the operator power-cycles the drives for the alarms that ask for it.
- Whether the controller must be shut down before the main switch is turned off.
- **E-STOP** pressed, and main switch on or off, while charging.
- The tablet is supplied with the vehicle.
- Trolleys have a parking brake.
- EN 12895 as the EMC standard.
- Label type (ISO 7010 W014).

### 10.4 Data still missing (all `[VALUE]` / `[TBD]`)

Manufacturer details and nameplate; dimensions; mass; IP rating; ambient limits; battery chemistry, capacity, charger and charging times; hitch type, height and drawbar force; number of trolleys, train length and trolley width; floor flatness, steps and gaps; tape type and minimum curve radius; clearances and hazard-zone sizes; scanning-plane height; rear scanner fields; stopping distances and times (table 16.3); noise levels; start-up time; capacitor discharge time before opening the electrical box; horn tones; certificate numbers and safety data of the scanner, safety controller and E-STOP; achieved PL and PFHd per safety function; cleaning agent for the scanner windows; extinguisher type; service contact; document numbers of the related documents.

## 11. Related documents (in preparation, same project)

- **Circuit diagrams:** an existing 10-sheet set, JIS-style device names, sheet/line cross-references. Proposed minimum sheet order:
  1. cover and index;
  2. overview;
  3. 48 V power;
  4. 24 V control;
  5. drives;
  6. safety circuit, on its own sheet;
  7. control I/O;
  8. communication;
  9. navigation sensors;
  10. terminals.
- **Component list:** to be written. One row per component occurrence, keyed by tag (IEC 62027). Columns:
  - IEC tag;
  - JIS tag;
  - description;
  - manufacturer;
  - part number;
  - rating;
  - sheet/line;
  - location;
  - safety-related Y/N;
  - safety function served;
  - PL / category claimed by the maker;
  - MTTFd or B10d;
  - certificate.

  This is where the manual's `[tag]` placeholders will come from.
- **Software documentation:** navigation features and engineering pages. Not yet written; referenced from the manual.
