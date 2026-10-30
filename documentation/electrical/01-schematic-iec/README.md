# IEC-style circuit diagrams: study and conversion plan

This folder is for the IEC-style version of the AGV circuit diagrams. The current JIS-style set lives in `../01-schematic/`. That folder remains the record of what is wired until the IEC sheets replace it.

| File | What it is |
| --- | --- |
| `README.md` | This file: how an IEC-style schematic set looks, why, and how it differs from ours |
| `conventions.md` | The rules we draw the IEC set by: sheet, grid, title block, tags, potentials, colours, cross-references |
| `designation-map.md` | Every component: old JIS name → new IEC 81346 tag, location, safety relevance |
| `sheet-plan.md` | The new page list, mapped from the old sheets 00–09, plus the issues to fix during conversion |
| `data/project.js` | **The single source of the page data:** title block, page list, locations, classes, potentials, colours and safety functions. The cover, contents and key pages are generated from it |
| `iec-page-NN.html` | One page per file. Open it in a browser; the toolbar has **Download PNG** and **Print / PDF** (choose A3 landscape, no margins) |

Drawn so far (Rev A draft): pages 1 (cover), 2 (contents), 3 (designation key) and 40 (safety: E-stop, selector, reset).

**Engine:** `../kit/iec-sheet.js` with `../kit/iec-sheet.css`. It loads after `../kit/jis-sheet.js` and reuses its primitives. It adds:
- the A3 landscape frame, the 0–9 column grid and the ISO 7200 title block;
- vertical-flow symbols: `contactV`, `operator` (push / estop / turn), `terminal`, `offDown`, `rail`, `module`, `locationBox`, `label`;
- `table` and `note`.

**To add a page:**
1. Copy `iec-page-40.html` to the new page number.
2. Set `drawn: true` for that page in `data/project.js`.
3. Replace the `draw()` body.

Draw the conductors first, then the symbols, which cut their own gaps. Column x positions come from `col(c)` (column c centre); everything is in mm.

**Preview without the browser UI:** open `iec-page-NN.html#bare` (1587 × 1123 px), or run Edge headless with `--window-size=1587,1123`.

Research date: 2026-10-30. Tags used in this folder:
- **[standard]**: backed by standard text or a publisher preview.
- **[vendor practice]**: EPLAN, SICK or Siemens convention.
- **[general practice]**: European machine-builder habit with no standard clause.
- **UNVERIFIED**: could not be confirmed.

---

## 1. What an IEC-style set is, in one paragraph

A European machine schematic set is a numbered book of A3 landscape pages. It contains a cover, a contents list, a designation key, overview diagrams, circuit diagrams grouped by function, I/O overview pages, terminal diagrams, a cable list and a parts list.

Every page has a column grid along the top edge and an ISO 7200 title block. Every device carries an IEC 81346 reference designation (for example `-FC1`, `-KE2`, `-SJ1`), and the same tag is printed on the physical device. Every link between pages is written as `/page.column`.

Current flows down the page, from the potential rails at the top to the 0 V rail at the bottom, and the pages read left to right. The safety circuit has its own pages, with both channels drawn as separate conductors.

## 2. The standards behind it

**IEC 60204-1:2016 Annex I (informative)** maps each kind of document to its standard [standard]:

| Topic | Standard |
| --- | --- |
| Structuring, reference designations | IEC 81346-1 / -2 |
| Document structure | IEC 62023 |
| Parts list, list of documents | IEC 62027 |
| Terminal designations | IEC 61666 |
| Cable and core labelling | IEC 62491 |
| Circuit diagrams, interconnection diagrams, terminal and cable lists | IEC 61082-1 |
| Graphical symbols | IEC 60617 (online database) |
| Conductor and terminal identification, colours | IEC 60445 |
| Title block fields | ISO 7200 |
| Sheet sizes, grid | ISO 5457 |
| Drive parameter lists | "no standard exists" |

**What IEC 60204-1:2016 clause 17.2 requires** [standard]. Edition 6 states this as "information to be supplied", not as a list of drawings:
- **a)** A main document that lists all the other documents.
- **b)** Identification of the equipment.
- **c)** Installation data: supply voltage, short-circuit rating, full-load current, environmental limits.
- **d)** Bonding instructions.
- **e)** An **overview of the structure** of the electrical equipment, for example a structure or overview diagram.
- **f)** Maintenance information:
  - **interconnections of replaceable components, by circuit diagrams and/or connection tables**;
  - **settings (DIP switches, parameter values)**;
  - **information for validating safety-related control functions after repair, and for periodic testing**.
- **g) to h)** Handling, storage and disposal.

The older edition (EN 60204-1:2006, 17.6) said plainly "a circuit diagram shall be provided". It also required switch symbols drawn with all supplies off and conductors identified per 13.2. Reviewers still expect all of this.

**Other clauses with consequences:**
- **IEC 60204-1 16.5:** each device is labelled with **the same reference designation as in the documentation**. Moving to IEC tags therefore means relabelling the hardware. [standard]
- **IEC 60204-1 16.4:** the enclosure marking includes the main document number. [standard]

**Electrical standard: EN 1175 (owner decision, 2026-10-30).**

- **Edition:** the current edition is **EN 1175:2025**, valid from 1 Dec 2025. It replaces EN 1175:2020, which is withdrawn but keeps presumption of conformity under 2006/42/EC until the Official Journal is amended (EVS listing). Cite EN 1175:2025.
- **Scope:** EN 1175 covers the electrical installation of self-propelled industrial trucks (ISO 5053-1:2020). It **does not apply to "functions used for the automatic operation of driverless industrial trucks"**, and refers to EN ISO 3691-4:2023 for those. For us:
  - **EN 1175** covers the battery, battery disconnection, the 48 V and 24 V installation, the wiring and the drives;
  - **ISO 3691-4 (with ISO 13849-1)** covers personnel detection, the modes and the other automatic-operation safety functions.
- **What EN 1175 means for the drawings:** IEC 60204-1 is not the governing standard. Its documentation clauses (17.2, 16.5 labelling) and colour clause (13.2.4) are used here as **good practice**, not as requirements.
- **Not verified:** whether EN 1175:2025 sets its own rules for conductor colours, documentation or the battery disconnecting device. Its text was not readable (previews blocked). An Annex A.3.10 "emergency disconnection" of the battery is mentioned in a search result. **Check the purchased EN 1175:2025** before the colour change and the `-QA1` arrangement are finalised.
- The drawing conventions in this folder (IEC 61082-1, IEC 81346, IEC 61666, IEC 60617, IEC 62491) apply whichever electrical standard governs.

Sources:
- EN 1175:2025: https://www.evs.ee/en/evs-en-1175-2025
- EN 1175:2020: https://www.evs.ee/en/evs-en-1175-2020

## 3. Page layout

- **Format:** A3 landscape [vendor practice]. EPLAN's standard frames are A3. It fits far more circuit per page than our A4 portrait.
- **Grid:**
  - ISO 5457 gives 50 mm fields: on A3, columns 1–8 across and rows A–F down, with the letters I and O not used [standard, via a secondary source].
  - Many German machine builders number columns only, 10 per page (0–9), with no rows [vendor practice].
  - A location is written `/page.column`, for example `/41.3` for page 41, column 3. On the same page the page number is dropped: `.3`.
  - The full form carries the structure, for example `=SAF+EB/41.3`.
- **Title block, ISO 7200** [standard]:
  - **Mandatory fields:** legal owner, document number, date of issue, sheet number, title, approval person, creator, document type.
  - **Optional fields:** revision, number of sheets, language, supplementary title, department, technical reference, document status, page count, paper size.
  - EPLAN-style blocks also show the page description, `=function` and `+location` of the page, page n of N, the document kind code (`&EFS` = electrical circuit diagram), and drawn / checked / approved [vendor practice].
- **Document kind codes, IEC 61355-1** [standard; replaced by ISO/IEC 81355-1:2024, but still widely understood]:

| Code | Document kind |
| --- | --- |
| &FS | Circuit diagram |
| &MA | Terminal / connection diagram |
| &MB | Cable diagram |
| &PB | Parts list |
| &AB | List of documents |
| &LU | Arrangement drawing |

## 4. Typical page order for a machine like ours [general / vendor practice]

1. Cover sheet
2. Contents (list of documents and pages)
3. Designation key: `=` functions, `+` locations, the IEC 81346-2 edition and codes used, potential names, colours, symbol legend
4. Revision overview
5. Overview diagrams: power block diagram, network / fieldbus topology
6. 48 V power distribution
7. 24 V and 12 V control supply with branch protection
8. **Safety: safety controller supply, E-stop, scanners, mode selector, reset, STO, feedback (EDM)**
9. Drives and motors
10. Vehicle controller and I/O module, with I/O overview pages
11. Sensors, operator controls, horn
12. Terminal diagrams
13. Plug diagrams
14. Cable overview and cable diagrams
15. Parts list (or a reference to the separate component list)
16. Arrangement drawing of the electrical box

Kept as separate documents (IEC 60204-1 17.2 f):
- the parameter list for the drives, scanners and safety controller;
- the Flexi Soft configuration report.

## 5. Reference designations (IEC 81346)

**Format:** `=FUNCTION +LOCATION -PRODUCT :TERMINAL`, for example `+EB-KE2:I5` is terminal I5 of the safety controller I/O module in the electrical box. Terminals follow IEC 61666, so `-XD1:43` is strip XD1, terminal 43.

**Class codes are two letters since IEC 81346-2:2009.**
- The single letters in our standards draft of 2026-10-29 (Q, F, K, S…) are the **old** IEC 61346-2 / DIN 40719 scheme. They are **superseded** by the two-letter codes in `designation-map.md`.
- The 2009 and 2019 editions differ in a few codes that matter to us:

| Device | 2009 | 2019 |
| --- | --- | --- |
| Push-button, E-stop | SF | **SJ** (confirmed separately by IHK-PAL) |
| PLC / controller | KF | **KE** ("electric signal processing"; KF now means relaying) |

**Pick one edition, state it on the designation key, and apply it everywhere.**
- We use **2019**, the current edition (EN IEC 81346-2:2020).
- Our 2019 codes come from a secondary table (Wikipedia, sourced from the Czech CCI classification). The codes marked "verify" in `designation-map.md` must be checked against the purchased standard.
- IEC 81346-2 Ed. 3 is at FDIS/DIS stage and may change codes again.

## 6. Cross-references [vendor practice; IEC 61082-1 allows it, clause text not read]

- **Interruption points:** a named arrow at the page edge, such as `+24V` or a signal name, with the target `/page.column`. Our sheets already do this as `1P24 (SH.03)`. The IEC form is `+24V /30.2`.
- **Contact image** under a relay or contactor coil: a small table of all its contacts, NO and NC, with terminal numbers and `/page.column`. Each contact refers back to its coil. Our set has almost no coils, so this is rarely needed.
- **PLC and I/O channels:**
  - Each channel is drawn on the function page where it is used, labelled with the module tag, terminal and signal name.
  - An **I/O overview page** per module lists every channel with a reference to the function page.
  - Do this for both the safety controller I/O module and the I/O module.

## 7. Potentials, wires and colours

- **IEC 60204-1 13.2.4 conductor colours** (recommended, not mandatory) [standard]:

| Colour | Use |
| --- | --- |
| BLACK | AC and DC power circuits |
| RED | AC control circuits |
| BLUE | DC control circuits |
| ORANGE | Excepted circuits: circuits that stay live when the main switch is off |
| GREEN-AND-YELLOW | PE only (13.2.2) |

- **Potential names:** IEC 60445 terminal notation uses L+, L−, M (mid-point / 0 V) and PE.
  - Siemens practice is `L+ / M`; SICK writes `+24 V DC / 0 V DC`.
  - What matters is choosing one scheme, explaining it on the designation key, and giving every fused or switched branch its own name.
- **Wire numbers:** three accepted schemes [vendor practice]:
  - potential-based (every conductor on a potential carries its name);
  - location-based (page.column-counter, for example `41.3-1`);
  - **target labelling**, where each conductor end is marked with the far end's tag and terminal, for example `-KE2:I5` (IEC 62491 "remote-end connection labelling").
- **Cables:** named with their own tag (for example `-WD1`, `-WG3`). Cores are identified by number or colour.

## 8. Symbols

- IEC 60617 is the symbol source.
- **JIS C 0617 is an identical adoption of IEC 60617** [standard], so our symbols are mostly already IEC. What makes our sheets look "JIS" is the layout conventions, not the symbols (section 9).
- **E-stop symbol:** an NC contact with the **positive-opening mark** (arrow in a circle, IEC 60947-5-1 Annex K), a mushroom actuator and the latching mark (ISO 13850, IEC 60947-5-5).
- **Switch positions:** draw every switch and contact with all supplies off and in its rest position.

## 9. How our current JIS sheets differ

| Topic | Our JIS sheets (`../01-schematic/`) | IEC style |
| --- | --- | --- |
| Format | A4 portrait | A3 landscape |
| Location grid | Line numbers 00–21 down the left; reference `0305` = sheet 03, line 05 | Column numbers across the top; reference `/30.5` |
| Current direction | Horizontal rungs from vertical rails, left to right | Vertical paths from potential rails at the top to 0 V at the bottom, pages read left to right |
| Device names | JIS prefixes: MCB-01, BUCK01, TB43, PB RESET, SAFETY PLC | IEC 81346-2 tags: `-QA1`, `-TA3`, `-XD1:43`, `-SJ3`, `-KE2` |
| Location aspect | None | `+EB` electrical box, `+FR` front panel, … |
| Title block | Customer / designer / content / approval / checked / designed / drawn / date / scale / model / dwg / sheet | ISO 7200 fields plus page description, revision and document kind |
| Revision grid | Large empty grid above the title block | Revision fields in the title block, plus a revision overview page |
| Front matter | Sheet 00 single-line diagram only | Cover, contents, designation key, revision overview |
| I/O | Drawn per terminal on sheets 08 and 09 | Same, plus one I/O overview table per module |
| Terminals, cables | TB numbers on the sheets; a separate cable-label spreadsheet | Terminal diagram per strip, cable overview, cable diagrams |
| Wire colours | 48 V power **red**, safety wiring **orange**, 24 V control blue | 60204-1 recommends **black** for DC power, **blue** for DC control. **Orange means "excepted circuit"**, so orange safety wiring will be queried |
| Text | All capitals | Mixed case is normal; capitals are allowed |

The symbol content, the junction dots, the "drawn de-energised" rule and the interruption-point idea carry over unchanged.

## 10. What a TÜV reviewer will look for on the safety pages [general practice + SICK manual]

- A separate safety section, for example `=SAF`.
- **Both channels drawn as separate conductors** to separate terminals. Test-output sources (X1, X2) shown.
- The SICK Flexi Soft pairing rule: odd inputs on odd test outputs, even inputs on even test outputs, from the same module. Ours is correct: X1 → I1, X2 → I2. Series E-stop contacts may total at most 100 Ω.
- Scanner OSSD1 / OSSD2 to a dual-channel input pair, **for each scanner**.
- STO: both channels to each drive, with the feedback (EDM) loop drawn.
- A safety-function ID written beside the devices, for example SF1 E-stop, SF2 personnel detection (front), SF3 personnel detection (rear), SF4 safe torque off.
- An I/O table for the safety controller listing terminal, device, test pulse and safety function.
- Any output with test pulses switched off (our Q3) explicitly marked, with the reason. Switching test pulses off reduces fault detection.
- No temporary bench wiring left undrawn. If it exists, it is drawn and labelled "temporary, not for release".

IFA Report 2/2017e (DGUV) has component-level example circuits for Categories B to 4. They are a good model for how to present the safety pages.

## 11. Sources

- IEC 60204-1:2016 clauses 13.2, 16.4, 16.5, 17 and Annex I. Read from a BS EN 60204-1:2018 copy; official preview at https://cdn.standards.iteh.ai/samples/18875/90805b617b194c79a353f317536a34d5/IEC-60204-1-2016.pdf
- Siemens white paper on IEC 60204-1 Ed. 6: https://assets.new.siemens.com/siemens/assets/api/uuid:a1cc807c-925e-4108-be0a-e3ec32e7960c/iec60204-whitepaper-icp-us.pdf
- ISO 7200 fields (IS 11665, identical adoption): https://law.resource.org/pub/in/bis/S01/is.11665.2010.pdf
- ISO 5457 grid (secondary summary): https://cadsetterout.com/drawing-standards/grid-reference-frame/
- EPLAN help:
  - cross-references: https://www.eplan.help/en-us/infoportal/content/Plattform/2.9/Content/htm/xessettingsgui_k_querverweisarten.htm
  - structure identifiers: https://www.eplan.help/en-us/infoportal/content/Plattform/2.9/Content/htm/projectstructure_k_hauptkundunterk.htm
  - wire numbering: https://www.eplan.help/en-us/infoportal/content/Plattform/2.9/Content/htm/wirenumberinggui_k_prinzip.htm
- IEC 81346-2:2009 tables (IG EVU-001): https://ww3.cad.de/foren/ubb/uploads/robroy55/IEC81346IGEVU.pdf
- IEC 81346-2:2019 classes (secondary): https://en.wikipedia.org/wiki/IEC_81346
- IHK-PAL note on DIN EN IEC 81346-2:2020 (SF → SJ): https://www.ihk.de/blueprint/servlet/resource/blob/5090560/af6d215e5541c178ce0faaf628c6f919/din-en-iec-81346-2-2020-10-referenzkennzeichnung-data.pdf
- IEC 61355 document kinds: https://en.wikipedia.org/wiki/IEC_61355
- IEC 62491 scope: https://iteh.es/catalog/standards/sist/6591143f-7387-43f9-b4b1-6ac77f912ec8/sist-en-62491-2008
- JIS C 0617 = IEC 60617: https://webdesk.jsa.or.jp/preview/pre_jis_c_00617_001_000_2011_j_ed10_ch.pdf
- SICK Flexi Soft hardware operating instructions 8012478 (2025-07): https://docs.rs-online.com/265c/A700000014719532.pdf
- IFA Report 2/2017e: https://publikationen.dguv.de/widgets/pdf/download/article/4150

**Not verified:**
- the IEC 61082-1 clause text on grids and cross-references (EPLAN used as the proxy);
- the IEC 60445 DC colour values;
- whether the three-letter "leaf" codes are in IEC 81346-2:2019 itself;
- the 2019 class for the E-stop, selector, scanner and motor driver;
- the ISO 3691-4 / EN 1175 / IEC 60204-1 relationship.
