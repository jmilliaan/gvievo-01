# Drawing conventions for the IEC-style set

These are the rules for drawing the IEC set. `README.md` gives the reasons behind them.

Items marked **[decide]** are proposals waiting for the owner. Items marked **[verify]** need checking against the purchased standard.

## 1. Sheet

| Item | Rule |
| --- | --- |
| Format | A3 landscape, 420 × 297 mm |
| Frame | 20 mm left margin (binding), 10 mm on the other sides (ISO 5457) |
| Grid | **10 columns numbered 0–9** across the top and bottom edges. No rows. EPLAN style, decided 2026-10-30 |
| Location reference | `/page.column`, for example `/41.3`. On the same page: `.3` |
| Colour | Black on white. Red only for unresolved items (draft) |
| Text | English, mixed case (decided 2026-10-30). IBM Plex Sans; tags, terminals and potentials in IBM Plex Mono. 2.5 mm for text, 2.0 mm minimum for terminal numbers |
| Switch state | Every contact drawn with all supplies off, at rest. A selector is drawn in the position where its contacts are open, with a switch-position table beside it (X = closed). `-SJ4`: open in AUTO, both contacts closed in MANUAL |

## 2. Title block (ISO 7200 fields, plus page fields)

| Field | Content now |
| --- | --- |
| Legal owner | PT INTI GANDA PERDANA |
| Document number | `«DOC-NO»`, the same on every page. The operation manual refers to it |
| Title | `AGV I-PRIME driverless towing vehicle — circuit diagram` |
| Document type | Circuit diagram (`&EFS`) |
| Page description | One line, for example "Safety circuit: E-stop and scanners" |
| Page / of | `41` / total pages |
| Revision | One letter, the **same on every page** of an issue (A = first issue for TÜV SÜD) |
| Date of issue | YYYY-MM-DD |
| Created / checked / approved | Names |
| Language | en |
| Location of page content | `+EB` etc., when the whole page is in one location |

Revision history goes on the cover page and the revision overview page. The large empty revision grid of the JIS sheets is dropped.

## 3. Page numbering

Pages are numbered in groups, so pages can be inserted without renumbering everything. The groups are listed in `sheet-plan.md`:

| Pages | Group |
| --- | --- |
| 1–9 | Front matter |
| 10–19 | Overview |
| 20–29 | 48 V power |
| 30–39 | Control supplies |
| 40–49 | Safety |
| 50–59 | Drives |
| 60–69 | Control I/O |
| 70–79 | Terminals and cables |
| 80–89 | Lists |

"Page n of N" counts the pages that exist.

## 4. Reference designations

- **Standard and edition:** IEC 81346-1:2022 with **IEC 81346-2:2019** class codes. This is stated on the designation key page.
- **Aspects used now:**
  - **product `-`** on every device;
  - **location `+`** at enclosure level.
- **Function aspect `=`:** deferred. The page groups do the job for now.
- **Locations [decide, confirm physically]:**

| Code | Location |
| --- | --- |
| `+EB` | Electrical box (harness board) |
| `+FR` | Front control panel (E-stop, buttons, selector) |
| `+VH` | Vehicle body and chassis (motors, scanners, line sensor, horn) |
| `+BT` | Battery compartment |
| `+PD` | Pendant |

- **Numbering:** sequential within each class across the whole vehicle: `-SJ1`, `-SJ2`, … Do not restart per location.
- **Terminals:** IEC 61666, `tag:terminal`:
  - `-KE2:I5` is terminal I5 of the safety controller I/O module.
- **Wire markers (decided 2026-11-15):** the markers on the vehicle are reprinted to page 76. Potential conductors: potential name (1P24 …). Safety controller wires: signal name (X1, ESTOP1, MANUAL, RESET, OSSD1, HWTO1, EDM-L …). I/O module wires: channel name (DI00 …, DO0 …). The old markers (L.HWTO1+, F.OSSD1, P.EMG, SS.MAN, DI.00 …) are replaced.
- **No terminal strip (decided 2026-10-31):** the old TB numbers are not drawn. The vehicle carries no matching terminal numbers, so drawing them would confuse an assessor comparing drawing and vehicle. Wires are identified by the potential or signal name on their wire markers (1P24, HWTO1, DI03). A separate assembly wiring diagram will follow.
- **Full tag on the sheet:** written next to the symbol, with its type and rating underneath. For example:

  ```
  -FC1
  1P 10A
  ```

- **Labels:** the same tag goes on the physical device (IEC 60204-1 16.5). Relabelling the vehicle is part of the conversion.

## 5. Potentials

The existing net names are kept. They are consistent, and they are already printed on the cable labels. The designation key explains them and gives the IEC 60445 meaning:

| Name | Meaning | IEC 60445 |
| --- | --- | --- |
| `1P48` / `1N48` | 48 V bus after the main breaker `-QA1`, + / return | L+ / M |
| `2P48`, `3P48` | 48 V feeders after `-FC1` (left drive) and `-FC2` (right drive) | L+ |
| `1P24` / `1N24` | 24 V control bus after `-FC3` | L+ / M |
| `1P12` / `1N12` | 12 V bus after `-FC4` | L+ / M |
| `PE` | Protective earth / chassis | PE |

N24 and N12 are joined at the converter output (old sheet 01). The converters are isolated, so 1N48 is **not** joined to them. The 48 V system is floating, with no connection to the chassis (owner, 2026-10-30).

Interruption points carry the potential name and the target, for example `1P24 /30.2`.

## 6. Conductors and cables

- Each conductor shows its colour and size where it starts and wherever it changes, as now. Size in mm² where known; AWG stays as the supplier's size.
- **Colours (decided 2026-10-30): the wiring changes to IEC 60204-1 13.2.4.** This is good practice, since EN 1175 is the governing electrical standard. **[verify]** that EN 1175:2025 does not set different colours before rewiring.

| Circuit | Was | Becomes |
| --- | --- | --- |
| 48 V power (battery, breakers, drivers, converter inputs) | red | **black** |
| 24 V / 12 V control, including the safety wiring (E-stop, OSSD, STO, EDM) | blue; safety wiring orange | **blue** |
| Protective earth | — | **green-and-yellow** only |
| Orange | safety wiring | **not used**: it means "circuit that stays live when the main switch is off" |

  - Safety wiring is no longer told apart by colour. It is told apart by its tags, its own pages (40–49) and the SF IDs.
  - The IEC sheets show the new colours. **The vehicle must be rewired before the IEC set is issued.** Until then the old JIS sheets remain the record of what is built.
  - Supplier cables (SICK, Oriental Motor, Belden) keep their own core colours and are drawn as they come.
- **Wire marking:** potential name on the conductor (as now) plus target labelling at terminals where a conductor leaves the page or the enclosure.
- **Cables:** each cable gets a tag:
  - `-WD` for power cables;
  - `-WG` for control and data cables **[verify: fieldbus class]**.

  The cable list (page 75) holds type, cores, size, length, from and to. The existing `../01-schematic/outputs-may-be-stale/proj01-cable-labels.xlsx` is the starting point.

## 7. Symbols

- **Source:** IEC 60617. Our current symbols already follow it (JIS C 0617 is identical).
- **E-stop:** NC contacts with the **positive-opening mark**, mushroom actuator, latching mark, turn-to-release noted.
- **Safety controller and I/O module:** drawn as a box with the terminals in use, labelled with terminal names (I1, X1, Q1…). One module per box, with its own tag.
- **Third-party devices with a connector** (scanners, drivers, line sensor): a box with the connector tag and the pins in use. Unused pins are listed in a note, not drawn.
- **Junctions:** filled dot. Crossings without a dot are not connected.

## 8. Safety circuit

- **Pages:** all safety wiring sits in pages 40–49. Other pages refer to it; they never repeat it.
- **Safety-function IDs (decided 2026-11-15, back on the sheets):** a boxed badge (`s.sf()`) beside each safety device on pages 12 and 40–45, a column in the I/O table (page 44) and in the parts list (page 80), and the list on page 5. One ID per hardware row of the operation manual, chapter 3.3. The source is `PROJECT.safetyFunctions`:

| ID | Safety function | Devices |
| --- | --- | --- |
| SF1 | Emergency stop | `-SJ1`, `-KE1`/`-KE2`, quick stop then STO of `-TA1`/`-TA2` (SS1) |
| SF2 | Personnel detection, front | `-BG1`, `-KE1`/`-KE2`, quick stop then STO (SS1) |
| SF3 | Personnel detection, rear | Not fitted in this revision. ID reserved |
| SF4 | Mode selection (protective field active only in AUTO) | `-SJ4`, `-KE2` |
| SF5 | Prevention of unexpected start-up (reset) | `-SJ3`, `-KE2` |
| SF6 | Speed limit in AUTO (1.1 m/s) | `-BG5`, `-BG6`, `-KE5`, quick stop then STO (SS1) |
| SF7 | Standstill monitoring (also ends the quick stop) | `-BG5`, `-BG6`, `-KE5` |
| SF8 | Motor power-off check (EDM) | EDM of `-TA1`/`-TA2` → `-KE2:I3`/`I4` |

  SF8 is new (2026-11-15). The manual lists "Motor power-off check" as its own row, so it gets its own ID. The operation manual does not print the IDs yet.

- **Channels:** each channel is a separate conductor to a separate terminal. Test outputs X1 / X2 are drawn as the source of each E-stop channel.
- **STO:** both channels to both drives, with the EDM feedback to I3 / I4 drawn.
- **Controlled stop (decided 2026-11-15):** SF1, SF2 and SF6 stop with SS1. `-KE2:Q4` switches off first: QSTOP on IN2 (pin 18) of both drivers, looped like HWTO1/HWTO2, so both brake at the quick-stop rate (6085h = 1600). Q1/Q2 (STO) follow when `-KE5` reports standstill (SF7) or at the latest after «t max». Driver parameters are set in MEXE02 and listed on page 50. Plan: `q4-controlled-stop-plan.md`.
- **Test pulses:** any output with test pulses switched off is marked "TEST PULSES OFF", with the reason in a note. Q3 (E-stop status to `-KE4:DI09`, 2026-11-15) has test pulses off because it feeds a standard input: a test pulse would read as a pressed E-stop. Q4 (QSTOP, 2026-11-15) has test pulses off too: a test pulse could start a quick stop.
- **Unresolved safety wiring is drawn in red with a note.** Do not leave it out.
- **Page 44:** one I/O table for the safety controller, with columns for terminal, signal, device tag, test pulse, safety function, wire marker, "off (0) means" and page reference.

## 9. Reading aids (decided 2026-11-15)

Informative only: they never change wiring, tags or symbols. Plan and reasons: `readability-plan.md`.

- **Function text:** `s.pathText(c1, c2, text)` under the top column strip on every circuit page. It says in plain words what the circuit below does. It is not a designation: no `=`, no SF ID.
- **References:** always `/page.column` in the drawing area. `check-set.ps1` reports any `/NN` without a column. Table "Page" columns and the words "page 50" (for table pages) are exempt.
- **Device box lines:** tag; what it is in words; maker and type; `s.alsoOn(tag)` = "Also on page(s) …" from the parts list.
- **Interruption points:** `offDown()` / `fromTop()` take a signal name (bold) as a fifth argument, e.g. MANUAL → `-KE4:DI02 /60.2`.
- **Wire markers:** written along every signal conductor that leaves a contact or a module terminal, in the words of page 76 (`PROJECT.markers`). Conductors on a potential carry the potential name and are not marked on the drawing.
- **Notes:** `s.notes(x, y, items, o)` numbers the page-specific items, then adds the standing lines in the same words everywhere ("Control wiring: AWG22 blue unless marked.", "All devices in +EB unless boxed.").
- **Page 2** carries "How to read this circuit diagram" (`PROJECT.readingGuide`). **Pages 44 and 62** have an "Off (0) means" column.
