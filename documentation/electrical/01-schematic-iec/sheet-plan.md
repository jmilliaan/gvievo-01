# Sheet plan: JIS sheets 00–09 → IEC pages

**Format:** A3 landscape. Page numbers are grouped (`conventions.md` section 3), so the numbers have gaps.

**"Source" column:** the JIS sheet the content comes from. "new" means the content is not on any current sheet.

## Front matter (1–9)

| Page | Content | Source | Kind |
| --- | --- | --- | --- |
| 1 | Cover: product, document number, revision table, "circuit diagram", list of the other documents (component list, operation manual, Flexi Soft report, parameter list) | new | &AB |
| 2 | Contents: every page with its description and revision | new | &AB |
| 3 | Designation key: locations `+EB +FR +VH +BT +PD`, the IEC 81346-2:2019 classes used, potential names and the IEC 60445 meaning, which returns are common, wire colours and any deviation, cross-reference format, safety-function IDs SF1–SF5 | new | &AB |
| 4 | Symbol legend: only the symbols used in this set | new | &AB |

## Overview (10–19)

| Page | Content | Source | Kind |
| --- | --- | --- | --- |
| 10 | Power overview (single-line): battery → `-QA1` → 48 V bus → `-FC1`/`-FC2` → drives; `-TA3` → `-FC3` → 24 V loads; `-TA4` → `-FC4` → 12 V loads | 00 | &EFS |
| 11 | Communication overview: CAN bus (`-TF1`, `-TA1`, `-TA2`, `-BG3`, BMS, with termination resistors); Ethernet (`-KE3` → `-KE4` → `-BG4`); scanner configuration and data network | new, from 06 and 09 | &EFS |
| 12 | Safety overview (block diagram): `-SJ1`, `-BG1`, `-SJ3`, `-SJ4` → `-KE1`/`-KE2` → STO of `-TA1`/`-TA2` with EDM. The same chain as the manual's figure IMG-03-01 | new | &EFS |

## 48 V power (20–29)

| Page | Content | Source | Kind |
| --- | --- | --- | --- |
| 20 | Battery, main breaker, 48 V bus, feeders `-FC1`/`-FC2`, converter inputs | 01 | &EFS |
| 21 | Motor drivers: power connector and motor cable for `-TA1`/`-TA2`, motors `-MA1`/`-MA2` with brake | 02 | &EFS |

## Control supplies (30–39)

| Page | Content | Source | Kind |
| --- | --- | --- | --- |
| 30 | 24 V bus part 1: `-TA3`, `-FC3`, scanners, safety controller supply, horn, I/O module supply | 03 | &EFS |
| 31 | 24 V bus part 2: display, line sensor, fans, driver network supply (NET-VIN) | 04 | &EFS |
| 32 | 12 V bus: `-TA4`, `-FC4`, IPC, RFID reader | 05 | &EFS |

Pages 30 and 31 may fit on one A3 page.

## Safety (40–49)

| Page | Content | Source | Kind |
| --- | --- | --- | --- |
| 40 | E-stop `-SJ1`: both channels X1→I1 and X2→I2. Mode selector `-SJ4` → I7. RESET `-SJ3` → I8 | 08 | &EFS |
| 41 | Front scanner `-BG1`: supply and OSSD1/OSSD2 → `-KE2:I5/I6`. The rear scanner is not fitted in this revision | 08, 03 | &EFS |
| 42 | STO: Q1/Q2 → HWTO1/HWTO2 on both drives. EDM `-TA1` → I3, `-TA2` → I4. Removed factory jumpers noted. Q3, Q4 spare | 08, 07 | &EFS |
| 43 | Safety controller modules `-KE1`/`-KE2`: supply, module front view | 08, 03 | &EFS |
| 44 | Safety controller I/O table: terminal, signal, device, test pulse, safety function, page | new | table |

## Drives (50–59)

| Page | Content | Source | Kind |
| --- | --- | --- | --- |
| 50 | Drive control connector (28 pins) for `-TA1`/`-TA2`. Only the wired pins drawn; the unused pins listed in a note | 07 | &EFS |
| 51 | CAN bus: `-TF1`, `-TA1`, `-TA2`, `-BG3`, BMS, shield and termination | 06 | &EFS |

## Control I/O (60–69)

| Page | Content | Source | Kind |
| --- | --- | --- | --- |
| 60 | I/O module `-KE4` inputs: START `-SJ2`, RESET second contact, selector second contact, pendant `-SJ6`…`-SJ9`, MANUAL ARM `-SJ5` | 09 | &EFS |
| 61 | I/O module `-KE4` outputs: horn `-PJ1` sound 1 / sound 2, relay commons, spare DO2–DO7. DO8 (on while the motors turn, nothing connected) noted | 09 | &EFS |
| 62 | I/O module I/O table: channel, signal, device, page | new, from `io-mapping.md` | table |

## Terminals and cables (70–79)

| Page | Content | Source | Kind |
| --- | --- | --- | --- |
| ~~70–71~~ | ~~Terminal diagram `-XD1`~~: removed 2026-10-31 (no terminal strip drawn). A separate assembly wiring diagram will follow | — | — |
| 75 | Cable overview: tag, type, cores × size, shield, length, from, to, page | `proj01-cable-labels.xlsx` | &MB |

## Lists (80–89)

| Page | Content | Source | Kind |
| --- | --- | --- | --- |
| 80 | Parts list: tag, description, manufacturer, part number, rating, location, page. Or one line referring to the separate component list | new | &PB |

That is about 28 pages, against 10 JIS sheets. Most of the growth is front matter and tables, not drawing.

## Minimum for the TÜV SÜD preliminary check

If time is short, draw these first: 1, 2, 3, 10, 12, 20, 21, 30, 32, 40, 41, 42, 44 and 70. The safety pages (40–44) matter most to the reviewer.

## Issues to resolve during the conversion

These are visible on the current sheets. The IEC pages must show them; they must not hide them.

1. ~~Rear scanner OSSDs~~ Decided 2026-10-30: the rear scanner is not fitted in this revision. I5/I6 belong to the front scanner `-BG1`.
2. ~~Q3~~ Decided 2026-10-30: Q3 is spare, like Q4. The "test pulses off" note is dropped. Check that the Flexi Soft configuration matches.
3. ~~Selector polarity~~ Settled: both contacts of `-SJ4` close in MANUAL. Source: the software reads DI02 = ON as MANUAL (`profile panel.auto_when_on = false`), and the I7 line is labelled MANUAL.
4. **Wire colours:** decided to rewire to IEC 60204-1 13.2.4: black 48 V power, blue control and safety wiring, no orange (`conventions.md` section 6). The rewiring is a production task, to be done before the IEC set is issued.
5. **PE / chassis earth:** not drawn on any sheet. It must appear on page 20 or 30, including the scanner and driver earths.
6. ~~Common returns~~ Decided 2026-10-30: the converters are isolated. 1N48 is not joined to 1N24 / 1N12. The 48 V system is floating (not connected to the chassis).
7. **Title-block data:** manufacturer, document number, names and dates are all placeholders.
8. **Physical relabelling:** the vehicle must carry the new tags before the IEC set is released (IEC 60204-1 16.5).

## Drawing tool

The `../kit/jis-sheet.js` engine draws A4 portrait JIS frames. The symbols (contacts, breakers, terminals, E-stop) can be reused. The IEC set needs three new pieces:
- an A3 landscape frame;
- a column grid;
- an ISO 7200 title block.

Decided 2026-10-30: **extend the HTML kit.** Add an IEC frame module next to the JIS one, reusing the symbols. Keep one HTML file per page in this folder, as now.
