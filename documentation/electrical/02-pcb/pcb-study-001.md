# PCB study 001: what can replace the terminal blocks

Date: 2026-11-16. Status: sections 1 to 6 are the study. The first board, IB-01, is designed and routed (section 7, files in `ib01/`); it is not ordered yet. No vehicle schematic or drawing is changed.

Owner decisions 2026-11-16: scope, connectors, fuses and order are settled (section 7). Protection: the board carries the 48 V lines too. It gets fuses only where a line has no protection of its own today. The breakers stay. Details in section 3 E and section 7. Owner answers to the open points of section 5 are recorded there (2026-11-16).

Aim: find which parts of the electrical box wiring a PCB can take over, in what order, and what must be known before design starts.

## 1. What this is based on

- JIS sheets `../01-schematic/proj01-sheet-00..10.html` and `io-mapping.md` (the only place the terminal numbers are recorded).
- IEC set `../01-schematic-iec/` (circuit diagram IGP-IPR-CD-001), including the Q4 controlled-stop plan `q4-controlled-stop-plan.md`.
- Harness-board drawing `../01-schematic/source/evot-hb-front-panel-A3.pdf`.

Not checked:

- **The vehicle.** The terminal numbers are not marked on it. The front-panel drawing shows about 37 terminal positions in four groups, the sheets list 69 terminals in use. Either the terminals are multi-level or the drawing is simplified. Count them on the harness board before sizing anything.
- **Load currents.** None of the documents gives the current of each 24 V or 12 V load, and there are no measurements (owner, 2026-11-16). They are estimated from the datasheets and marked as estimates.
- **Standards.** Section 6 is my reading, not checked against the text of a standard.

## 2. What the terminal blocks do today

The sheets number TB01 to TB71 and show two more without a number (MANUAL ARM, «TB?»). TB09/TB10 belong to the rear scanner that is not fitted and TB27/TB28 are spare. That leaves **69 terminals in use**.

Sorted by what each terminal really does:

| Job | Terminals | Count | What it is electrically |
| --- | --- | --- | --- |
| Hand out 1P24 | TB07, 11, 13, 15, 17, 19, 21, 23, 25, 48, 54, 55, 67, MANUAL ARM feed | 14 | One potential, fourteen taps |
| Hand out 1N24 | TB08, 12, 14, 16, 18, 20, 22, 24, 26, 44, 47, 50, 53, 57, 64, 65, 66, 68, 69 | 19 | One potential, nineteen taps |
| Hand out 12 V | TB29–TB32 | 4 | Two potentials, two taps each |
| CAN bus | TB33–TB42 | 10 | Three bus lines with drops to four devices |
| Signal pass-through, not safety | TB56, 58, 59, 60, 61, 62, 63, 70, 71, MANUAL ARM signal | 10 | One wire in, one wire out |
| Signal pass-through, safety | TB43, 45, 46, 49, 51, 52 | 6 | HWTO1 / HWTO2 to both drivers (with two jumpers), EDM back |
| 48 V driver feeders | TB01–TB06 | 6 | Panel wire to LC03D06A cable, 2.5 mm² |
| **Total** | | **69** | |

Two things follow from the table:

- **37 of 69 terminals only hand out three potentials** (24 V, 0 V, 12 V). This is the plainest job for a PCB: one copper area per potential.
- **Only 6 terminals carry a safety signal.** The other safety wires (E-stop, selector, reset, scanner OSSD) have no terminal block today; they run straight from the device to the safety controller.

## 3. What a PCB can take over

Five candidate functions. Each could be its own board or a zone of one board.

| | Function | Replaces | Parts on the board | Safety signals | Difficulty |
| --- | --- | --- | --- | --- | --- |
| A | 24 V / 12 V distribution | 37 terminals | Connectors, one fuse per load | None. It does feed the safety devices | Low |
| B | CAN backbone | 10 terminals | Connectors, one switchable 120 Ω terminator | None | Low |
| C | Control I/O interconnect: I/O module to START, pendant, horn, second contacts of RESET and selector | 10 terminals | Connectors only | None | Low to medium |
| D | Safety interconnect: safety controller to E-stop, selector, RESET, scanner OSSD, both drivers (HWTO, EDM, later QSTOP), Q3 to DI09 | 6 terminals, plus about 20 point-to-point wires that have no terminal today | Connectors only | All of them | High, because of the safety argument (section 6), not the electronics |
| E | 48 V power zone: motor feeders passed through, converter inputs fused | 6 terminals | High-current connectors and tracks, two fuses | None | Medium |

### A. 24 V / 12 V distribution

- One input for P24 / N24 after MCB-04 (`-FC3`), one for P12 / N12 after MCB-05 (`-FC4`). One keyed plug per load: scanner, safety controller, horn, I/O module, display, line sensor, three fans, both driver network supplies, vehicle controller, RFID reader.
- The supply-side wires of each load disappear into the board. Each load keeps one cable.
- **One fuse per load (decided).** Today every 24 V branch hangs on one 6 A breaker, so a short in one load drops the whole bus. With a fuse per load, only that fuse blows. MCB-04 and MCB-05 stay in front of the board; no second device goes in series with them on the incoming line. Each fused branch also gets an indicator LED (decided, P3).
- N24 and N12 are joined today at the converter outputs. The board must keep that as it is. 48 V is floating and the converters are isolated, so the 48 V zone (function E) is kept apart from this zone by spacing; no track joins them.
- Six of the 37 terminals feed the drivers' safety inputs: the HWTO returns (TB44, 47, 50, 53, on 1N24) and the EDM feeds (TB48, 54, on 1P24). They carry a potential, not a signal, but they are part of the torque-off circuit. If they are kept with the safety wiring, function A replaces 31 terminals, not 37.

### B. CAN backbone

- CAN H / CAN L / CAN GND as three tracks with a plug for the USB-CAN interface, each driver, the line sensor and the battery.
- **It can close an open point:** the bus has one terminator today (inside the USB-CAN interface) and the far end is open. A 120 Ω resistor with a jumper at the far end of the board fixes that.
- To settle: the bus order and stub lengths, and where the Belden screen lands.

### C. Control I/O interconnect

- Routes the I/O module's inputs and outputs to the panel buttons, the pendant cable and the horn, and ties the input commons (COM0, COM1) and the output commons.
- Terminal layout of the CK-TP5162, from the module's wiring diagram (photo from the owner, 2026-11-16). Sheet 09 draws a simplified block. Two 20-pole terminal rows:

  | Pin | DI row (16 inputs) | DO row (16 outputs, NPN, sinking) |
  | --- | --- | --- |
  | 1–8 | DI0–DI7 | DO0–DO7 |
  | 9, 10 | DI_COM0 (common of DI0–DI7, 24 V or 0 V) | 9: + (12/24 V), 10: − (0 V) |
  | 11–18 | DI8–DIF | DO8–DOF |
  | 19, 20 | DI_COM1 (common of DI8–DIF, 24 V or 0 V) | 19: + (12/24 V), 20: − (0 V) |

  - The inputs take either polarity: with the common on 24 V a switch to 0 V turns the input on, and the other way round. Today the panel and pendant buttons on DI00–DI06 switch to 1N24, so DI_COM0 sits on 1P24. DI08 (MANUAL ARM) and DI09 (Q3) switch 24 V onto their inputs, so DI_COM1 sits on 1N24 (`io-mapping.md`).
  - The outputs switch to 0 V: a load sits between + and its DO pin. The horn and any lamp on a DO output are wired that way.
  - On the diagram, 9/10 of the DI row are drawn as one common, and so are 19/20. Whether the DO row's 9 and 19 (and 10 and 20) are joined inside the module is not shown. IB-01 wires pins 9 and 10 only (J23), which supply DO0–DO7; DO0 and DO1 are the only outputs in use. If DO8–DOF are ever used, pins 19 and 20 need their own supply wires.
- The pendant cable (7 of 8 cores) becomes one plug. The two unnumbered MANUAL ARM terminals disappear.

### D. Safety interconnect

- Largest saving in hand wiring: each driver's control connections (CAN, network supply, HWTO, EDM, QSTOP) could come from one plug, and the HWTO jumpers between the drivers become tracks.
- It is a passive board, but it carries both STO channels, the E-stop channels and the mode input side by side. That needs a written argument and a new validation (section 6).
- The Q4 controlled stop is planned but not wired, and its input polarity is still to verify. A safety board drawn now would have to be redrawn.

### E. 48 V power zone

Decided 2026-11-16: the 48 V lines run breaker → board → load. The board fuses only what has no protection of its own.

| Line | Protected by | On the board |
| --- | --- | --- |
| Motor L feeder (2P48) | MCB-02 (`-FC1`), 13 A | Passed through, **no fuse**. Replaces TB01, TB02 |
| Motor R feeder (3P48) | MCB-03 (`-FC2`), 13 A | Passed through, **no fuse**. Replaces TB03, TB04 |
| 48 V input of the 24 V converter (`-TA3`) | Nothing of its own: 1.5 mm² behind the 32 A main | **Fuse** |
| 48 V input of the 12 V converter (`-TA4`) | Nothing of its own: 1.5 mm² behind the 32 A main | **Fuse** |

- **Why no fuse on the motor feeders.** The driver brochure gives 10.4 A rated and 16 A maximum input current for the 400 W driver at 48 V (`manuals/bldc/569 BLV-R Brochure.pdf`, page 18). A fuse that survives that is 15–20 A, above the 13 A breaker in front of it, so the breaker always opens first. The tracks and connectors are sized for the breaker: 13 A continuous and its let-through on a short.
- **Why the breakers stay.** They can be reset, and the operation manual (14.2) uses MCB-02 and MCB-03 to power-cycle the drivers after a drive alarm.
- **Converter input fuses close a known gap** (point R6 in `../../submission/improvement-plan-001.md`). Values in section 5, point 1a.
- **The 24 V converter is a SD-100C-24** (100 W, 24 V 4.2 A out; owner, 2026-11-16), not the SD-150C-24 (6.3 A) that the circuit diagram, the JIS sheets and the component list show. The documents need correcting; recorded in the improvement plan.
- **Fuse type.** DC-rated for at least 60 V (the battery reaches 58 V). Ordinary automotive blade fuses are 32 V parts and are not suitable. The breaking capacity must cover the battery's short-circuit current.
- **Earth.** The PE core of each LC03D06A cable (TB05, TB06 today) goes to the chassis bar, not through the board.
- **Main switch.** `-QA1` stays on the rail, in front of everything.

## 4. What changes beyond the terminals

- **Plugs per cable instead of screws per wire.** The open-ended supplier cables (SICK scanner and line-sensor cables, Belden CAN, pendant cable) each end in one plug. A mis-wired core becomes a mis-pinned plug, found once at the bench, not on every vehicle.
- **Space.** The front-panel drawing has four terminal groups on two DIN rails. A, B and C remove most of three of them.
- **Wire markers and the rewire.** The planned rewire (48 V black, control and safety blue) and the wire-marker reprint are both still open. A board replaces much of the wiring those two jobs would touch. Decide the order: rewire first and then PCB means doing part of the work twice.
- **Documents.**
  - The IEC circuit diagram shows no terminals, so its circuits stay as drawn. It gains the board as a device, the connector designations and a cable for each plug.
  - The JIS sheets change most: terminal numbers become connector and pin numbers.
  - The component list gains the board and the connectors.
  - The board needs its own schematic, layout and parts list.
- **The review package.** Rev A describes the vehicle without a PCB. A board with no safety signals changes how wires are joined, not what is connected. A board in the safety circuits is a design change the reviewer will want to see and assess.

## 5. What must be known before design

| # | Open point | Why it matters | Where it comes from |
| --- | --- | --- | --- |
| 1 | Current of each 24 V and 12 V load, and its inrush | Track width, connector rating, value of each load fuse | Datasheets |
| 1a | Input current and inrush of both converters at 36–58 V | Value of the two converter input fuses | Mean Well datasheets |
| 1b | Short-circuit current of the battery (what the BMS lets through) | Breaking capacity of the 48 V fuses, and whether the ABB breakers are rated for it at DC | Battery / BMS data, ABB datasheet |
| 2 | Real terminal count and layout on the harness board | Board size and where it mounts | The vehicle |
| 3 | Space and fixing in the electrical box | DIN-rail carrier or standoffs; board outline | `evot-hb-front.dxf`, the vehicle |
| 4 | Connector family | Sets the board size, the tooling and the harness cost. Needs locking and keying so two plugs cannot be swapped | Owner decision (section 7) |
| 5 | Wire sizes that must fit | 2.5 mm² motor feeders, 1.5 mm² converter inputs, AWG22 control, 0.5 mm² scanner supply, supplier cable cores down to 0.25 mm² | Sheets, cable datasheets |
| 6 | CK-TP5162 terminal layout | Needed for function C | The module or its manual |
| 7 | Mating part of the driver's 28-pin control connector | Needed for a per-driver cable in function D | BLV-R driver manual (not found in `manuals/bldc/`) |
| 8 | Q4 / QSTOP: input polarity and the decision to wire it | Function D cannot be frozen before this | `q4-controlled-stop-plan.md` |
| 9 | CAN bus order, stub lengths, screen | Function B | The vehicle |
| 10 | Vibration and temperature in the box; coating or not | Connector choice, board fixing | Owner, vehicle data |
| 11 | Number of vehicles and who builds the boards and harnesses | Decides how much effort the board deserves, and crimp versus screw | Owner |

Answers (owner, 2026-11-16). Points 7 and 8 belong to function D and are not needed for the first board.

| # | Answer | What it means for the board |
| --- | --- | --- |
| 1 | No measured data. **Estimate from the datasheets**, mark every value as an estimate, confirm on the vehicle later | Done: section 8. A measuring round with a clamp meter per branch confirms them |
| 1a | Both converters are 100 W: **SD-100C-24** (24 V 4.2 A out) and **SD-100C-12** (12 V 8.4 A out). **Inrush 30 A** each | Input current about 100 W ÷ 0.86 ÷ 36 V ≈ 3.2 A at the lowest input, about 2.4 A at 48 V (efficiency estimated). **5 A MINI 58 V fuse** per converter (section 8) |
| 1b | Unknown. **Assume the worst case** | 48 V fuses with the highest breaking capacity the 58 V blade range offers; recorded as an assumption. The same question stays open for the ABB breakers at DC |
| 2, 3 | **Standoffs on the back plate**, board at most **150 × 250 mm** | Board outline 150 × 250 mm maximum, fixing holes at the corners and at mid-length. The terminal count on the vehicle is still to be counted, but the size limit now governs |
| 4 | Pluggable terminal blocks (P2) | — |
| 5 | Known (table above) | 2.5 mm² feeders need a 7.5 mm or larger pitch plug; supplier cores down to 0.25 mm² need ferrules. As built on IB-01: 7.62 mm for the 48 V lines, 5.08 mm for the 24 V and 12 V inputs and the IPC, 3.5 mm for the loads, CAN and I/O (up to 1.5 mm²) |
| 6 | **Settled:** wiring diagram of the module, table in section 3 C | Function C can be drawn |
| 9 | **The board defines the bus:** USB-CAN interface at one end, 120 Ω terminator (with jumper) at the other, the two drivers, the line sensor and the battery as short stubs in between. Screen to chassis at the board | Bus order is fixed by the layout, not by the existing wiring |
| 10 | **Indoor factory, 0–45 °C, dry. No conformal coating** | Locking plugs; screw-flange plugs on the heavy cables against vibration |
| 11 | **A few vehicles (about 2–10). The PCB maker assembles the board** (SMD and through-hole); harnesses are made in-house with screw-type plugs | Standard footprints, parts available at the board maker; no crimp housings |

## 6. Safety and review notes

My reading; to be checked with the reviewer before a safety board is drawn.

- **A passive board is wiring.** With connectors only, the safety architecture stays what it is: the same devices, the same channels, the same safety controller logic.
- **Short circuits between tracks.** In a cable duct, a short between two safety wires is a fault to consider. On a board, the usual way is to exclude it by spacing and by protecting the board from dirt and moisture, or to show that it is detected. The E-stop inputs (test pulses X1 / X2) and the STO outputs Q1 / Q2 are monitored by the safety controller. The mode input I7 is a single wire without test pulses: a short from 24 V onto it mutes the protective field in AUTO. That weakness exists today (point R5 in `../../submission/improvement-plan-001.md`); a board must not make it more likely, so that track needs distance or a guard.
- **Keep the two channels apart.** HWTO1 and HWTO2, and the two E-stop channels, should not share a connector pin row or run side by side for the length of the board.
- **Revalidation.** Any board in the safety circuits means the safety functions are validated again and the documents go to a new revision.

## 7. Recommendation

1. **First board: A + B + C + E, no safety signals.** Two zones kept apart: 48 V (E), and 24 V / 12 V with CAN and I/O (A, B, C). It takes over 61 of the 69 terminals; the two PE terminals move to the chassis bar, so 63 go in all and only the six safety-signal terminals remain. If the six supply terminals of the drivers' safety inputs also stay with the safety wiring, the board takes over 55. If the I/O module layout (point 6) holds things up, C can follow later: 10 terminals fewer.
2. **Leave D for a second step,** after the Q4 decision and after the reviewer has seen the Rev A package. Until then the six safety terminals stay as they are.
3. **Protection (decided 2026-11-16):** fuses on the two converter inputs and one per 24 V / 12 V load; motor feeders pass through unfused; all five breakers stay.

Owner decisions (2026-11-16):

| | Decision | Decided |
| --- | --- | --- |
| P1 | Scope of the first board | **A + B + C + E.** No safety signals; D is a later step |
| P2 | Connector family | **Pluggable terminal blocks.** No crimp tool; they take the supplier cables' bare cores. Screw or push-in, pitch and coding are design choices |
| P3 | Indicator LED per fused branch | **Yes** |
| P3a | Fuse style | **Blade fuses** in PCB holders. On the 48 V side they must be a 58 V or higher type |
| P4 | Order against the planned rewire and marker reprint | **PCB first.** Rewire and re-mark only what is left afterwards |
| P5 | Timing against the review | **Not tied to the review.** The first board carries no safety signal |
| P6 | Fans | **One 2 A fuse for all three fans** |
| P7 | Battery short-circuit current above the fuses' 1000 A | **Main breaker `-QA1` is the backup** |

Design started 2026-11-16: schematic of the first board, **IB-01**, in `ib01/` (`ib01.kicad_sch`, generated by `ib01/gen_schematic.py`; `ib01.pdf` for reading). ERC clean, schematic reviewed by the owner. Board started the same day: `ib01.kicad_pcb` from `ib01/gen_board.py` (250 × 150 mm, 2 layers, 2 oz copper, vertical pluggable headers so the plugs face the front, 48 V zone on the left behind an 8 mm copper keep-out, fuse row at the top of the 24 V / 12 V zone, six M4 holes to chassis). Same day, owner additions: spare outputs 3 × 24 V (F14–F16, 2 A), 2 × 12 V (F17–F18, 3 A), 1 × 48 V (F19, 5 A), each with fuse and LED. Routed with Freerouting 2.5.0 (`ib01/route.py`): bottom pours 1N48 / 1N24 / 1N12, top pours for the motor feeders (13 A), 2.0 mm 24 V bus, 2.5 mm 12 V bus and IPC, 1.5 mm fused 48 V converter feeds. KiCad DRC: 0 violations, 0 unconnected. Mounting holes H1/H4 in the 48 V zone are unplated.

Parts and fabrication (2026-11-16): Phoenix was too expensive, so the board uses parts stocked by LCSC and is ordered from JLCPCB with full assembly (top side only, through-hole parts wave-soldered).

| Item | Part | LCSC |
| --- | --- | --- |
| 48 V headers (J1–J8) | Kefa KF2EDGVM-7.62-2P, plug KF2EDGKM-7.62-2P (15 A IEC, 10 A UL) | C441450 / C441150 |
| 24 V and 12 V inputs, IPC (J10, J11, J27) | Degson 2EDGVM-5.08-02P, plug 2EDGKM-5.08-02P (20 A IEC) | C699489 / C699500 |
| Load, CAN and I/O headers | Kefa KF2EDGVM-3.5-nP, plug KF2EDGKM-3.5-nP (7 A IEC) | C4414xx / C4411xx |
| Fuse holder (F1–F19) | XFCN XF-508P-B-B MINI, 500 V (replaces Keystone 3568: out of stock) | C19727305 |
| Fuses | Littelfuse 0997 MINI 58 V, 2 / 3 / 5 / 7.5 A | C3661386 / C3661685 / C2680609 / C2680610 |

Footprints are drawn from the makers' drawings (`ib01/gen_footprints.py`, library `ib01.pretty`). J22 uses a 12-pin header (no 11-pin plug in stock; pin 12 spare). Order files from `ib01/make_fab.py` in `ib01/fab/`: Gerber zip, JLC BOM, JLC placement file, and the loose-parts list (cable plugs, fuses, jumper shunt, ordered from LCSC and fitted by hand). DRC after rerouting: 0 violations, 0 unconnected.

Assessment and draft 2 (2026-11-16). The routed board was checked against the sources before ordering. The netlist matches `../01-schematic/io-mapping.md` pin by pin (only J22 pin 12 is unconnected), and the board matches the schematic. The layout was changed as below and the board rerouted. The circuit did not change. Schematic, board and silkscreen now read "draft 2", and the order files in `ib01/fab/` are the draft 2 files:

| Finding | Change in draft 2 |
| --- | --- |
| The 1N48 copper on the bottom ran to 0.25 mm from the unplated holes H1 and H4. A metal standoff would have sat on it with only solder mask between chassis and the floating 48 V return | No copper within 6.5 mm of the centre of H1 and H4, both layers |
| The 1P48 track from J3 to the fuses F12, F13, F19 was 1.5 mm wide. It sits in front of 15 A of fuses with only the 32 A main breaker ahead | Laid as 5 mm of top copper (about 20 K rise at 15 A, estimate) |
| Fuse-holder holes were 1.7 mm for a pin that is 1.65 mm across its diagonal | 1.8 mm holes, 2.8 mm pads |
| The 24 V feed from J10 to the first fuse, the only way into the 24 V bus, was necked to 1.5 mm by the autorouter | Laid at the full 2.0 mm |

DRC on draft 2: 0 violations, 0 unconnected. As routed, the 12 V bus has one 10 mm stretch at 1.9 mm (class width 2.5 mm; about 20 K rise at the converter's full 8.4 A, estimate), and each branch track carries its fuse rating at 0.6 mm or wider.

Open before the order:

- **The footprints of the headers and the fuse holder are not checked against a real part.** They are drawn from datasheet dimensions. With full assembly a wrong footprint scraps every board. Buy one of each header and one fuse holder, or print the board 1:1 and lay the parts on it. With a 7.62 mm header in hand, also check the underside of its flange ears: the 48 V copper runs under the left ears of J3 and J6, and they must not have bare metal there.
- **The board is not free of the safety circuit's supplies.** It carries the safety controller supply (J13), the 24 V feeds of the mode selector and the reset button (J14), and on J15 / J16 the EDM+ supply and both HWTO returns of each driver. Section 3 A counts the last two as part of the torque-off circuit. A lost connection on any of them fails to the safe side, but the owner should confirm that P5 (not tied to the review) still holds with these on the board.
- **Fuse selectivity is not tested.** The converters limit their own current, so a branch fuse may not open before the converter shuts the whole bus down. Bench test: short a spare output and see whether only that fuse opens.
- **JLCPCB assembly stock** is confirmed for the fuse holder only. The BOM upload shows it for the headers.
- **The 24 V and 12 V returns** are connected by 1.0 mm and 2.5 mm tracks; the bottom copper areas are cut into several pieces by other tracks and only add to them. That is enough for the 4.2 A and 8.4 A the converters can give.
- The vehicle checks of section 1 (terminal count, load currents) and the depth of the box above the upright plugs are still open.

Next: owner review of the routed board in KiCad, the footprint check, then the order.

## 8. Load currents and fuse values (estimate, 2026-11-16)

Every current below is an **estimate** from datasheets or from similar products. Nothing is measured. A measuring round on the vehicle (clamp meter per branch, at start-up and in normal running) confirms or corrects them.

### Fuse part

- **One family for the whole board: Littelfuse MINI 58 V, series 0997xxx.WXN** (fast-acting, 2–30 A, 58 V DC, interrupting rating 1000 A at 58 V DC). It fits a standard PCB MINI-fuse holder (on IB-01: XFCN XF-508P-B-B, see section 7).
- Using the 58 V type on the 24 V and 12 V side too costs a little more, but nobody can put a 32 V fuse into a 48 V holder by mistake: there is only one kind of fuse on the vehicle.
- The fuse protects the track, the connector and the wire. It does not protect the device. That is why the smallest value is 2 A even for a 30 mA sensor.
- A blade fuse should run at no more than about 75 % of its rating continuously, and less in a warm box. The values below keep the estimated maximum under that.

### 48 V side

| Branch | Estimated input current | Fuse |
| --- | --- | --- |
| `-TA3` SD-100C-24 input | 100 W ÷ 0.86 (efficiency, estimated) ÷ 36 V ≈ **3.2 A** at the lowest input voltage, ≈ 2.4 A at 48 V; inrush 30 A (owner) | **5 A** (0997005.WXN) |
| `-TA4` SD-100C-12 input | same, ≈ **3.2 A** max, ≈ 2.4 A at 48 V; inrush 30 A | **5 A** (0997005.WXN) |
| Motor feeders | 10.4 A rated, 16 A max (section 3 E) | none, protected by the 13 A breakers |

- **Inrush.** The 30 A inrush charges the converter's input capacitors and lasts well under a millisecond. Its I²t is far below what melts a 5 A MINI fuse. To check against the I²t value in the Littelfuse datasheet once the part is ordered.
- **Battery short-circuit current: the main breaker is the backup (decided, owner 2026-11-16).** The battery's short-circuit current is unknown (section 5, 1b). Above 1000 A the fuse alone is not rated to break it. The main breaker `-QA1` (32 A, C curve) trips magnetically at a few hundred amperes and breaks faults above the fuse's rating. The battery's BMS will most likely cut a short circuit before either of them. For the file: the DC breaking capacity of `-QA1` from the ABB S200 data.

### 24 V side (`-TA3` SD-100C-24, 4.2 A)

| Branch | Load | Estimate | Source | Fuse |
| --- | --- | --- | --- | --- |
| 1 | Safety laser scanner `-BG1`, nanoScan3 NANS3-AAAZ30AN1 | 0.2 A (3.9 W typical without output load), 0.3 A with margin | SICK datasheet | 2 A |
| 2 | Safety controller `-KE1`, `-KE2`, `-KE5`, with both encoders | 0.5 A (CPU ≤ 2.5 W, XTIO ≤ 2.2 W, MOC and encoders estimated about 7 W) | SICK datasheets; MOC and encoder figures estimated | 3 A. SICK asks for at most 4 A on the system supply |
| 3 | I/O module `-KE4`, CK-TP5162 | 0.1 A | estimated, no datasheet | 2 A |
| 4 | Horn `-PJ1`, PATLITE BK-24AE-K | 0.1 A | estimated, no figure found | 2 A |
| 5 | Display `-PH1`, Jawest JWS080 | 0.6 A (5–15 W for an 8-inch industrial display) | estimated from similar displays | 2 A |
| 6 | Line sensor `-BG3`, MLSE | 0.03 A (0.6 W) | SICK datasheet of the MLSE family | 2 A |
| 7 | Fans `-GQ1`, `-GQ2`, `-GQ3`, NMB 3110KL-05W-B60 | 3 × 0.18 A = 0.54 A | distributor listings (0.14–0.18 A each) | 2 A, one branch for all three (decided) |
| 8 | Driver `-TA1` network supply (NET-VIN) | 0.25 A | estimated, figure not found | 2 A |
| 9 | Driver `-TA2` network supply (NET-VIN) | 0.25 A | estimated, figure not found | 2 A |
| | **Total** | **about 2.6 A** of 4.2 A | | |

### 12 V side (`-TA4` SD-100C-12, 8.4 A)

| Branch | Load | Estimate | Source | Fuse |
| --- | --- | --- | --- | --- |
| 10 | Vehicle controller `-KE3`, NEXCOM NEU-X102-N97, with the USB-CAN interface and other USB devices | 1.5–2 A typical, **5 A maximum (60 W)** | Distributor listings give 60 W maximum; typical draw estimated | 7.5 A |
| 11 | RFID reader `-BG4`, Chafon CF821 | 0.5–1.2 A | similar Chafon readers (no CF821 datasheet found) | 3 A |
| | **Total** | **about 2–3 A typical, 6.2 A maximum** of 8.4 A | | |

### What follows from the numbers

- **The 24 V converter has less room than the documents suggest.** With 100 W (4.2 A) in place of 150 W, the estimated 2.6 A is about 60 % of its rating. That is enough, but there is less room for new 24 V loads. The measuring round settles it.
- **The 6 A breaker `-FC3` is larger than the 4.2 A converter behind it.** That does no harm: the converter limits the current. It does mean the breaker never trips on an overload, only the converter's own protection does. The branch fuses on the board now give the selective protection.
- **The IPC branch needs heavy copper.** For 7.5 A, the track, the connector and the wire to the IPC are sized like a feeder (1.0 mm² wire or more).
- **Fans on one branch (decided, owner 2026-11-16).** The one exception to one fuse per load: three fans on one 2 A fuse. A fan short takes out only the fans.
- **Branch count:** 9 on 24 V, 2 on 12 V, 2 on 48 V: 13 fuses and 13 LEDs for the loads. With the six spare outputs (section 7: three on 24 V, two on 12 V, one on 48 V) IB-01 has 19 fuses and 19 LEDs.
