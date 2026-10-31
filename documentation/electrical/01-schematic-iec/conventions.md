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
- **Safety-function IDs:** written beside each device on the safety pages and in the I/O table. **[decide]** They are aligned with the operation manual, chapter 3.3:

| ID | Safety function | Devices |
| --- | --- | --- |
| SF1 | Emergency stop | `-SJ1`, `-KE1`/`-KE2`, STO of `-TA1`/`-TA2` |
| SF2 | Personnel detection, front | `-BG1`, `-KE1`/`-KE2`, STO |
| SF3 | Personnel detection, rear | Not fitted in this revision. ID reserved |
| SF4 | Mode selection (protective field active only in AUTO) | `-SJ4`, `-KE2` |
| SF5 | Prevention of unexpected start-up (reset) | `-SJ3`, `-KE2` |

- **Channels:** each channel is a separate conductor to a separate terminal. Test outputs X1 / X2 are drawn as the source of each E-stop channel.
- **STO:** both channels to both drives, with the EDM feedback to I3 / I4 drawn.
- **Test pulses:** any output with test pulses switched off is marked "TEST PULSES OFF", with the reason in a note. Q3 and Q4 are spare in this revision.
- **Unresolved safety wiring is drawn in red with a note.** Do not leave it out.
- **Page 44:** one I/O table for the safety controller, with columns for terminal, signal, device tag, test pulse, safety function and page reference.
