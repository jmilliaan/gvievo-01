# Readability plan: notes and reading aids for the IEC set

**Aim:** make the IEC set as easy to follow as the JIS set, without breaking the rules in `conventions.md`. Everything here is informative content (text, tables, references). No wiring, tag or symbol changes.

Status 2026-11-15: **done** for everything except the reprint on the vehicle. The decisions and the work done are in section 6. The plan was based on a page-by-page read of `circuit-diagrams.pdf` (Rev A draft, 24 pages) and the page sources; the set now has 26 pages.

Markers: **[decide]** = owner choice needed. **[verify]** = check on the vehicle or in a document before drawing it.

---

## 0. Limits (what the additions must not do)

| Rule | Source | Consequence for this plan |
| --- | --- | --- |
| Black on white; red only for open items | conventions §1 | No colour coding for safety wiring or function groups. Grouping is done with text and position only |
| Text 2.5 mm, terminal numbers 2.0 mm minimum | conventions §1 | New text uses the same sizes. If a page runs out of room, use `{ textScale: 1.1 }` or move notes; never go below the minimum |
| Contacts drawn at rest, supplies off | conventions §1, IEC 60204-1 | Notes may explain a state; they never show the device in another position |
| No terminal strip / TB numbers | owner, 2026-10-31 | Wires are found by wire marker and device terminal only (item B) |
| No SF IDs, no standards list, no document-kind codes on the sheets | owner, 2026-11-09 simplification | Function text (item A) is plain words, **not** SF1…SF7 and **not** an `=` function designation. **[decide]** if the owner wants SF IDs back on the safety pages |
| One source for data | README, `data/project.js` | New tables and "also on" lines are generated from `project.js`, not typed on each page |
| Notes are informative | IEC 61082-1 practice | A note never states something the drawing contradicts. If they disagree, fix the drawing |
| Rev A package sent-ready 2026-11-09 | memory / submission folder | **[decide]** If Rev A of IGP-IPR-CD-001 has already gone to TÜV SÜD, these changes become Rev B, with a revision-table row and the new revision letter in every title block. If it has not gone, keep it as Rev A |

---

## 1. Additions on every page (set-wide)

### A. Function text above each circuit (biggest win)

A short plain-language caption under the top column grid, over the columns that circuit uses. EPLAN calls this "path function text". It replaces the job the JIS sheet layout did, which was telling you what each line is for at a glance.

- **Kit:** new `s.pathText(c1, c2, text)` in `../kit/iec-sheet.js`. It writes 2.5 mm text centred over columns `c1…c2`, just below the grid strip, with a thin tick at each end of the span.
- **Wording:** a noun phrase saying what the circuit does, not a tag. Examples: "Emergency stop, 2 channels"; "24 V supply: safety controller".
- The texts for each page are listed in section 3.

### B. Wire markers drawn to match the vehicle

Since the TB numbers were dropped (2026-10-31), the wire marker is the only thing that links a drawn conductor to a real wire. Today it is drawn on pages 41, 42 and 50 only.

- Put the marker on every signal conductor that leaves a contact or a module terminal. A conductor that runs straight from a named rail is already identified by the rail name, so it needs no marker.
- **[verify]** The markers that are on the vehicle now (from `../01-schematic/outputs-may-be-stale/proj01-cable-labels.xlsx`) do not match what the IEC pages print:

| Signal | On the vehicle (cable-label list) | Drawn on IEC pages |
| --- | --- | --- |
| STO left | `L.HWTO1+`, `L.HWTO1-`, `L.HWTO2+` … | `HWTO1`, `HWTO2` (page 42) |
| EDM | `L.EDM+`, `L.EDM-`, `R.EDM+` … | `EDM-L`, `EDM-R` (page 42) |
| Scanner OSSD | `F.OSSD1`, `F.OSSD2` | `OSSD1`, `OSSD2` (page 41) |
| Front panel | `P.EMG`, `P.STA`, `P.RST`, `SS.MAN` | not drawn (pages 40, 60) |
| I/O module | `DI.00` … `DI.08`, `DO.00`, `DO.01` | not drawn (pages 60, 61) |
| Driver network supply | `NET-VIN-01/02`, `NET-GND-01/02` | not drawn (page 31) |

  **[decide]** Either keep the vehicle markers and draw them exactly as they are, or reprint the markers during the rewiring. Rewiring has to happen before issue anyway (conventions §6). Whichever you choose, drawing and vehicle must say the same thing.
- **Kit:** the existing `wl(x, y, t)` covers it. Add a `markers` array to `project.js` (signal, marker text, pages) so that the I/O tables can show the same text.

### C. Every cross-reference written as `/page.column`

Many references now point only to a page, so the reader has to search that page. The convention (§1) is `/page.column`.

| Page | References to complete |
| --- | --- |
| 10 | all box references (`/20`, `/21, /42`, `/30`, `/32`) |
| 11 | `/32`, `/51`, "page 41" |
| 12 | `/40`, `/41`, `/45`, `/40 … /45`; add `/42.x` to `-TA1`, `-TA2` |
| 20 | `1N48 → /21`; add the missing continuation on `1P48` |
| 21 | `Control /50 · CAN /51 · STO /42` |
| 30 | rail ends `/31`; device boxes `/43`, `/61`, `/60, /61` |
| 31 | rail ends `/40`; `CAN /51` |
| 32 | `CAN /51 · Ethernet /11` |
| 40 | rail ends `/42`; the "Other terminals" line |
| 41 | `/11`; "Other terminals: /40, /42, /43" |
| 42 | rail start `/40` and end `/60` |
| 60 | rail start `/42` and end `/61`; "outputs /61 · I/O table /62" |
| 61 | rail start `/60`; `supply /30.7` (already full) |

- **Kit:** `check-set.ps1` gets one more check. It warns on any reference in the drawing area that matches `/NN` with no `.column`. Table "Page" columns are exempt.

### D. Device boxes: same four lines everywhere

1. Tag, for example `-KE2`.
2. **What it is, in words**, for example "Safety controller I/O module".
3. Maker and type, for example "SICK FX3-XTIO84002".
4. **Also on:** the other pages where the device appears.

Line 4 can be generated: `PROJECT.devices[n][6]` already holds the page list. The kit prints it minus the current page.

Boxes that are missing line 2 or line 4 today:

| Page | Box | Missing |
| --- | --- | --- |
| 30 | `-KE1`, `-KE2` | plain name (shows only "FX3-CPU0", "FX3-XTIO84002") |
| 30 | `-KE4` | plain name |
| 31 | `-TA1`, `-TA2` | "network" → "Motor driver left: network supply only"; also on /21, /42, /50, /51 |
| 42 | `-KE2` | plain name; also on /40, /41, /43, /44 |
| 42 | `-TA1`, `-TA2` | also on /21, /31, /51 |
| 51 | `-KE3`, `-TA1`, `-TA2`, `-BG3`, `-GB1` | also on |
| 61 | `-KE4` | also on /30, /60, /62 |

### E. Interruption points name the signal, not just the target

A reader following an arrow should know what is on the wire without turning the page.

| Page | Now | Becomes |
| --- | --- | --- |
| 40 | `-KE4:DI02 /60.2` | `MANUAL → -KE4:DI02 /60.2` |
| 40 | `-KE4:DI01 /60.1` | `RESET → -KE4:DI01 /60.1` |
| 60 | `-SJ3:24 /40.8` | `RESET, from -SJ3:24 /40.8` |
| 60 | `-SJ4:24 /40.5` | `MANUAL, from -SJ4:24 /40.5` |
| 41 | `-KE3 enp1s0 (-WG9) /11` | keep (already says what it is) |

- **Kit:** `offDown()` and `fromTop()` take an optional signal name and print it above the tag.

### F. Notes block: same place, same order

Notes now sit in different places on each page: top middle (40, 42, 60), right (32, 61), bottom left (30, 31, 41). Put them **bottom left, columns 0–3** on every circuit page, where there is room. Use this order:

1. Page-specific explanation (what this circuit does, any state that is not obvious).
2. Open items (red).
3. Standing lines, worded the same on every page: "Wiring AWG22 (0.34 mm²) blue unless marked." and "All devices in +EB unless boxed."

Exceptions: page 21 (the right side is the only free area) and page 61 (rails at the bottom, see section 4).

### G. Optional: clickable references in the PDF

On paper the reader still has to turn pages. In the PDF, every `/page.column` can be a link.

- **Kit:** while rendering, `iec-sheet.js` records each reference's text box (mm) and target page in `window.__refs`.
- `print-set.ps1` collects them and adds `/Link` annotations with pypdf after merging. pypdf is already used there.
- About half a day of work. It does not change the printed look.

---

## 2. Front matter

### Page 2: add a "How to read this circuit diagram" panel

Columns 6–9, beside the contents table, where there is free space now. Content (from `project.js`, new key `readingGuide`):

| Item | Text |
| --- | --- |
| Device tag | `+FR-SJ1:11`: `+FR` = where it is (front panel), `-SJ1` = which device, `:11` = which terminal. Tags are printed on the devices |
| Reference | `/40.3` = page 40, column 3. `.3` = this page, column 3 |
| Potential rail | Name and source at the left (`1P24 /31.9`); the arrow at the right edge means it continues on the page shown |
| Arrow down, off the circuit | The conductor continues at the page shown under the arrow |
| Arrow down, at the top | The conductor comes from the page shown above the arrow |
| Contacts | Drawn at rest with all supplies off. Selector: see its position table |
| Wire marker | Text written along a conductor = the marker on that wire |
| Boxes | Dash-dot = location. Dashed = not fitted in this revision |
| Finding things | A device: parts list, page 80 ("Pages" column). A signal: I/O tables, pages 44 and 62. A cable: page 75. Start with the overviews, pages 10–12 |

### Page 4: complete the legend

- **Symbols used but not in the legend:** incoming interruption point (arrow at the top, pages 30, 32, 43, 60); not-fitted dashed box (12, 41); FLEXBUS+ dashed link (43); connector bar (45, "M12 8-pin · head B"); DC/AC driver box `=/~` (21); drive-control connector front view (50).
- **Potentials table:** add `P24 / N24` and `P12 / N12`, the converter outputs before `-FC3`/`-FC4`. They are drawn on pages 20, 30 and 32 but not explained.
- **Wire colours table:** `PROJECT.colours` exists but is not printed. **[decide]** where it goes: page 4 is full. Options:
  - shrink the symbol grid by one row;
  - or move "Locations", "Potentials" and "Colours" to a new **page 5, "Designation key"**. This partly restores the page 3 that was archived on 11-09, but without standards text, SF IDs or document-kind codes.

---

## 3. Page by page

Function text (item A) per page, plus anything specific to that page. Columns are the 0–9 grid.

| Page | Function text (columns → text) | Also on this page |
| --- | --- | --- |
| 10 | none (block diagram) | C |
| 11 | none (block diagram) | C |
| 12 | none (block diagram) | C. Add `/42` to the `-TA1`/`-TA2` boxes. One line under the controller box: "Inputs left, outputs right; any input off → Q1, Q2 off → torque removed" |
| 20 | 0–1 Battery and main switch · 2–3 Feeder, left driver · 4 Feeder, right driver · 5–6 Converter 48 → 24 V · 7–9 Converter 48 → 12 V | C (`1P48` has no continuation arrow, `1N48` has one) |
| 21 | 0–4 Left drive: power and motor · 5–9 Right drive: power and motor | C, D |
| 30 | 0–1 24 V breaker · 1–2 Front scanner supply · 4–6 Safety controller supply · 7 Horn supply · 8–9 I/O module supply | C, D |
| 31 | 0–1 Display · 2 Line sensor · 3–6 Cabinet fans · 7–9 Motor driver network supply | B (`NET-VIN-01/02`), C, D |
| 32 | 0–1 12 V breaker · 2–3 Vehicle controller · 4–5 RFID reader | C |
| 40 | 0–3 Emergency stop, 2 channels · 3–6 Mode selector MANUAL / AUTO · 6–9 Reset | B (`P.EMG`/X1…I2, `SS.MAN`, `P.RST`), C, E, F |
| 41 | 1–2 Scanner supply · 3–4 Personnel detection, OSSD pair · 6 Scanner data (not safety) | B, C, D |
| 42 | 0–1 STO channels 1 and 2 · 2–3 Feedback (EDM) · 3–4 Left driver STO return · 5–9 Right driver | B, C, D, F |
| 43 | 1–3 Safety controller supply | **Bug:** the "Page" column of both `-KE2` tables is empty (section 4) |
| 44 | none (table) | Optional column "Off state means", e.g. I1 off = E-stop pressed or wire broken; I5 off = protective field occupied. Helps fault-finding; generated from `project.js` |
| 45 | 0–4 Left wheel encoder · 5–9 Right wheel encoder | — |
| 50 | none (table) | — |
| 51 | 0–3 USB-to-CAN interface · 4–5 Left driver · 6 Right driver · 7 Line sensor · 8–9 Battery BMS | D |
| 60 | 0–1 Start · 2 Reset (2nd contact) · 3 Mode (2nd contact) · 4–6 Pendant drive buttons · 7 Manual arm · 8–9 Input commons | B (`P.STA`, `DI.00` …), C, E, F |
| 61 | 0–1 Horn sounds · 2–7 Spare outputs, commons wired | B (`DO.00`, `DO.01`), C, D, F; see section 4 on the rails |
| 62 | none (table) | Optional "Off state means" column, as on page 44 |
| 75 | none (table) | — |
| 80 | none (table) | — |

---

## 4. Faults found during the review (fix together with the plan)

1. **Page 43, empty "Page" column.** `row()` returns `r[5]`, but `PROJECT.safetyIO` rows have 5 fields since the SF column was removed. It should be `r[4]`. One-character fix.
2. **Page 61, rails at the bottom.** Every other page has its potential rails at the top. This page puts 1P24 / 1N24 at the bottom, which is why it reads differently. Move them to the top, or say why in a note.
3. **Page 61, mixed commons [verify].** Common C of DO2/DO3 goes to 1P24, but C of DO0/DO1, DO4/DO5 and DO6/DO7 goes to 1N24. Check it on the vehicle against JIS sheet 09 (TB66–TB69). If it is right, add a note saying why.
4. **Page 20.** `1P48` ends without a continuation arrow, but `1N48` continues to `/21`. The drawing is correct: 1P48 feeds `-FC1`/`-FC2` on this page, and they continue as 2P48/3P48. Add a short note so it doesn't look like a mistake.
5. **Wire marker mismatch** between the vehicle and the drawings (item B table).

---

## 5. Order of work

| Step | Work | Files | Effort |
| --- | --- | --- | --- |
| 1 | Fix faults 1, 2 and 4 (no owner input needed) | `iec-page-43.html`, `iec-page-61.html`, `iec-page-20.html` | small |
| 2 | Kit: `pathText`, signal name on `offDown`/`fromTop`, auto "Also on" line, reference lint in `check-set.ps1` | `../kit/iec-sheet.js`, `../kit/check-set.ps1` | ½ day |
| 3 | `project.js`: `readingGuide`, `markers`, P24/N24/P12/N12 in `potentials` | `data/project.js` | small |
| 4 | Pages 2 and 4 (and 5 if chosen) | `iec-page-02.html`, `iec-page-04.html` | small |
| 5 | Items A, C, D, E, F page by page, in page order | all `iec-page-NN.html` | 1 day |
| 6 | Item B (wire markers), after the marker decision and a check on the vehicle | pages 31, 40, 41, 42, 60, 61 | ½ day + vehicle check |
| 7 | Optional item G (PDF links) | `../kit/iec-sheet.js`, `../kit/print-set.ps1` | ½ day |
| 8 | Run `..\kit\check-set.ps1 -Dir .` (no overlaps), rebuild with `..\kit\print-set.ps1 -Dir . -Out circuit-diagrams.pdf`, and read every page once on paper at A3 | — | — |

## 6. Decisions (owner, 2026-11-15) and what was done

| # | Question | Decision | Done |
| --- | --- | --- | --- |
| 1 | Rev A or Rev B | **Rev A**: the set has not gone to TÜV SÜD | Revision unchanged |
| 2 | Wire markers | **Reprint** the vehicle markers to the drawings | Page 76 (`PROJECT.markers`), markers drawn on pages 40, 41, 42, 60, 61. Scheme in `conventions.md` §4. **Open: reprint on the vehicle** (red item on page 76) |
| 3 | Designation key | **Page 5 is back** | Page 5: locations, potentials (with P24/N24, P12/N12 and IEC 60445), wire colours, product classes, safety functions. Page 4 is now symbols only, with 8 more symbols |
| 4 | SF IDs | **Back on the sheets** | SF1–SF8 (SF8 = EDM is new). Badges on pages 12, 40–45; columns on pages 44 and 80; list on page 5 |
| 5 | "Off (0) means" column | **Add** | Pages 44 and 62 |
| 6 | PDF links | **No** | Item G dropped |

Also done: items A, C, D, E, F on every circuit page; the reading guide on page 2; the `check-set.ps1` reference check (all 26 pages report OK); faults 1, 2 and 4 from section 4. Page 61 now has its rails at the top, with commons on the top edge of `-KE4` and outputs on the bottom edge.

Found and fixed along the way:
- Page 21 printed motor cable CCM**010**B1AAF. The cable list and page 50 say CCM**020**B1AAF, 2 m. Page 21 now reads the cable list.
- Page 32 gave N12 as `/20.8`. It is `/20.9`.
- Page 45 note 1 said `-KE1` switches Q1, Q2. The outputs are on `-KE2`.
- Parts-list page lists: `-TA1`/`-TA2` now include page 31 and `-KE1`/`-KE2` include page 30.

Fault 3 (page 61 mixed commons) checked against JIS sheet 09: C of DO2/DO3 is on 1P24 as built. It is noted on the page, not flagged.

Still open:
- Reprint the wire markers on the vehicle (page 76).
- The operation manual 3.3 table does not print the SF IDs yet.
- SF8 as its own ID: confirm it in the risk assessment / Flexi Soft report.
