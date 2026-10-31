# AGV I-PRIME Driverless Towing Vehicle — Operation Manual

> **DRAFT — Revision A, for TÜV SÜD preliminary review. Not for release.**
> Structure: ISO 20607:2019 and IEC/IEEE 82079-1:2019. Content: ISO 3691-4:2023 (information for use, Annex A operating zone). Machinery Directive 2006/42/EC Annex I 1.7.4.2 and Regulation (EU) 2023/1230 Annex III 1.7.4 are used as reference checklists only. The vehicle is not planned for the EU market.

**Draft conventions (remove before release)**

| Token | Meaning |
| --- | --- |
| `[TBD: ...]` | Text still to be written; the note says what goes there |
| `[VALUE: ...]` | A number or fact to be filled from design data or measurement |
| `[confirm]` | Written from project records; must be checked against the built vehicle before release |
| `[IMG-cc-nn]` | Image placeholder; see the image register at the end |
| `[tag]` | Reference designation (IEC 81346) to be assigned in the component list; the same tag is used on the schematic and the vehicle label |
| **[REVIEW]** | A gap between the current design and what the manual must be able to state. For discussion with TÜV SÜD; not reader text |

Placeholders are highlighted in yellow. Review notes are in grey boxes.

**Audience markers** on each chapter: **[O]** operator · **[M]** maintenance personnel · **[C]** commissioning engineer.

---

## Document information

| Field (ISO 7200) | Value |
| --- | --- |
| Legal owner | PT INTI GANDA PERDANA |
| Document number | `[TBD: e.g. OM-xxxx]` |
| Title | AGV I-PRIME Driverless Towing Vehicle — Operation Manual |
| Document type | Instructions for use |
| Revision | A (draft) |
| Date of issue | 1 OCTOBER 2026 |
| Language | English (en) |
| Created by | JOY MILLIAAN |
| Approved by | JOKI IRAWAN |
| Applies to | Model AGV I-PRIME, serial numbers GVI-1T0, vehicle software V1.0.0-V2.0.0 |

### Revision history

| Rev | Date | Change | Author |
| --- | --- | --- | --- |
| A | 1 OCTOBER 2026 | First draft for TÜV SÜD preliminary review | JOY MILLIAAN |

### Contents

- About this manual
- Regulations and standards
- Precautions for safe use
- Precautions for correct use
- 1. Identification
- 2. Intended use and limits
- 3. Safety
- 4. Vehicle description
- 5. Towing
- 6. Operating zone and site preparation
- 7. Transport, storage and installation
- 8. Commissioning
- 9. Operating modes
- 10. Operation
- 11. Emergency situations
- 12. Battery charging
- 13. Safety-function checks
- 14. Fault finding and alarms
- 15. Maintenance
- 16. Technical data
- 17. Decommissioning and disposal
- Annexes A–E

---

## About this manual

### Who this manual is for

This manual is for everyone who works with or near the vehicle:

| Reader | Uses chapters | Must have |
| --- | --- | --- |
| **Operator** — couples and uncouples trolleys, starts and stops the vehicle, drives it by hand, charges it, does the daily checks | Safety, 1–5, 9–14, 16 | Instruction by the user's responsible person, using this manual; a documented practical introduction on the vehicle |
| **Maintenance personnel** — inspection, cleaning, part replacement, periodic safety checks | All chapters | Technical training in electrical and mechanical maintenance; work on the electrical equipment only by an electrically skilled person |
| **Commissioning engineer** — prepares the site, lays the tape, commissions and verifies the vehicle, changes settings | All chapters, in particular 6–8 | Training by the manufacturer; access to the engineering functions |

Each chapter heading shows who the chapter is for: [O] operator, [M] maintenance personnel, [C] commissioning engineer.

Persons who have not been instructed must not operate the vehicle. Persons who only work in the operating zone (pedestrians, forklift drivers) must be told about the vehicle, its warning signals and the hazard zones (chapter 3.6).

### Keep this manual

Read this manual before first use. Keep it with the vehicle or at the workplace, where operators can reach it during work, for the whole life of the vehicle. Pass it on with the vehicle. The current version is available from `[TBD: manufacturer contact / download location]`.

### Safety messages

Safety messages in this manual have four parts: signal word, the hazard, its consequence, and how to avoid it.

> **⚠ WARNING — Crushing between trolley and fixed objects.**
> The trolleys follow a tighter path than the vehicle in curves. A person standing beside the tape route can be trapped.
> - Keep the clearances in chapter 6.5.

| Signal word | Meaning |
| --- | --- |
| **DANGER** | A hazardous situation that **will** cause death or serious injury if not avoided |
| **WARNING** | A hazardous situation that **can** cause death or serious injury if not avoided |
| **CAUTION** | A hazardous situation that can cause minor or moderate injury if not avoided |
| **NOTICE** | Information on avoiding damage to property. No risk of injury |

### Other conventions

- Controls and indicators on the vehicle are written in CAPITALS: **START**, **RESET**, **MANUAL / AUTO**.
- Pages of the vehicle's web interface are written in bold: **Home**, **Alarms**.
- Messages shown by the vehicle are written in a fixed-width font, with their alarm code: `ESTOP`.
- Every component has a reference designation (tag), for example `[tag]`. The same tag is printed on the circuit diagram, the component list and the label on the vehicle.
- Units are SI. Speeds are in m/s, distances in mm unless stated otherwise.
- "Trolley train" means all trolleys coupled behind the vehicle.

### Related documents

| Document | Number | Content |
| --- | --- | --- |
| Circuit diagrams | `[TBD]` | Electrical equipment, safety circuit |
| Component list | `[TBD]` | All electrical components by tag, safety data |
| Software documentation (navigation features) | `[TBD]` | Programming of stop points and route markers, engineering pages of the web interface |
| SICK nanoScan3 operating instructions | SICK | Safety laser scanner |
| SICK Flexi Soft hardware operating instructions | SICK 8012478 | Safety controller |
| Oriental Motor BLV Series R operating manuals | Oriental Motor HP-5142 | Motor drivers, safe torque off (HWTO) |
| SICK MLS operating instructions | SICK | Magnetic line sensor |
| Battery and charger manuals | `[TBD]` | `[TBD]` |

---

## Regulations and standards

> **[REVIEW]** Draft list. The vehicle is intended for the Indonesian market. The acts and standards below are used as a design reference only. The vehicle does not yet fully meet them, and no conformity assessment has been done.

### Directives and regulations (design reference)

| Act | Scope |
| --- | --- |
| Machinery Directive 2006/42/EC; Machinery Regulation (EU) 2023/1230 from 20 Jan 2027 | Reference for the essential safety requirements and the content of this manual |
| EMC Directive 2014/30/EU | Reference for electromagnetic compatibility; not yet tested |

### Standards referred to in the design

| Standard | Title |
| --- | --- |
| ISO 3691-4:2023 | Industrial trucks — Safety requirements and verification — Part 4: Driverless industrial trucks and their systems |
| ISO 12100:2010 | Safety of machinery — General principles for design — Risk assessment and risk reduction |
| ISO 13849-1:2023 | Safety of machinery — Safety-related parts of control systems — Part 1: General principles for design |
| EN 1175:2025 | Safety of industrial trucks — Electrical/electronic requirements |

### Safety components

| Component | Rating stated by the component maker |
| --- | --- |
| Safety laser scanner SICK nanoScan3 | Type 3 (IEC 61496), SIL 2 (IEC 61508), PL d / Category 3 (ISO 13849-1), PFHd 8.0 × 10⁻⁸ /h (SICK data sheet) |
| Safety controller SICK Flexi Soft | SIL 3 (IEC 61508), PL e / Category 4 (ISO 13849-1), PFHd 1.07 × 10⁻⁹ /h for the FX3-CPU0 main module (SICK data sheet) |
| Motor driver Oriental Motor BLVD-KRD, safe torque off (HWTO) | PL d, Category 3, PFHd 2.90 × 10⁻⁷ /h per driver (Oriental Motor data) |
| Emergency stop push-button | B10d 50 000 cycles |

---

## Precautions for safe use

These rules apply at all times. Each chapter adds the rules for its task.

- Do not ride on the vehicle or on the trolleys.
- Do not step in front of a moving vehicle or train, and do not throw objects in front of it. The safety scanner stops the vehicle, but not instantly (chapter 16.3).
- Do not stand between the vehicle and a trolley, or between trolleys, while the vehicle is in **AUTO**.
- Couple and uncouple trolleys only when the vehicle is stopped at a stop point or in **MANUAL** with **MANUAL ARM** switched off.
- Do not exceed the towing limits in chapter 2.2 and chapter 5.
- Use the vehicle only on the level floor and in the operating zone prepared as in chapter 6.
- Never cover, bridge, mute or change a protective device. Never change the configuration of the safety scanner or the safety controller. Only the commissioning engineer may change them, and only with re-verification (chapter 8.5).
- In **MANUAL**, the safety scanner does **not** stop the vehicle. Drive by hand only with the vehicle and its path in view, and only as fast as the situation allows.
- Keep the operating zone free of people who have not been instructed.
- Report every damage, unusual noise, unusual behaviour or failed check to the person responsible. Take the vehicle out of service if a protective device does not work.
- Use only the charger supplied with the vehicle. Charge only in the charging area (chapter 12).
- Before any work inside the vehicle, switch it off and lock it out (chapter 15.1).
- The web interface has no user authentication. Keep the vehicle and the tablet on a closed, trusted network.

---

## Precautions for correct use

These notes protect the vehicle and its performance. They are not safety rules.

- Keep the magnetic tape clean and undamaged. Worn, lifted or dirty tape causes stops (`MLS_FIELD_WEAK`, `TRACK_LOST`).
- Clean the scanner window regularly (chapter 15.3). Dirt causes unwanted stops.
- Avoid driving over steps, gaps, cables and loose objects; they shorten the life of wheels and gearboxes.
- After a software update, reload the web pages (**↻** button) so the browser does not use old pages.
- Do not switch off the battery main switch while the vehicle is driving. A sudden loss of power latches an alarm in the motor drivers that needs a power cycle (`UNCLEAN_SHUTDOWN`).
- Store the tablet used for the web interface where unauthorised persons cannot use it.

---

## 1. Identification [O][M][C]

### 1.1 Manufacturer

PT INTI GANDA PERDANA, Jl Pegangsaan Dua Km 1.6, Jakarta Utara, Indonesia

Sales: sales@igp-astra.co.id · Service: iprime-service@igp-astra.co.id

### 1.2 Product

| Item | Value |
| --- | --- |
| Product | AGV I-PRIME driverless towing vehicle |
| Model | AGV I-PRIME |
| Type | Driverless industrial truck (as defined in ISO 3691-4), tow tractor, differential drive, guided by magnetic tape on the floor |
| Year of construction | 2026 |

This edition covers the towing vehicle with magnetic-tape guidance. Navigation features that decide *where* the vehicle stops or how fast it drives on a section (stop-point tags, route markers, map-based navigation) are described in the software documentation. They are not safety functions; the safety functions in chapter 3.3 work the same with or without them.

### 1.3 Nameplate

The nameplate is on `[TBD: position, typ. rear of the chassis beside the main switch]`. It shows: manufacturer name and address, model, serial number, year of construction, unladen mass, rated towing capacity, battery voltage, `[TBD: marking required in Indonesia, if any]`.

[IMG-01-01] Nameplate and its position on the vehicle

---

## 2. Intended use and limits [O][C]

### 2.1 Intended use

The vehicle tows trolleys along a fixed tape route, marked by magnetic tape on the floor. It is for internal transport in industrial buildings, in areas where the people present have been instructed about the vehicle.

It runs:

- **automatically** (**AUTO**): it follows the tape, stops at programmed stop points and continues when the operator presses **START**;
- **by hand** (**MANUAL**): the operator drives it with the pendant or the web interface, for positioning, moving it to the charging area, and bringing it back onto the tape.

Trolleys are coupled and uncoupled by hand by the operator at stop points.

### 2.2 Operating limits

| Item | Limit |
| --- | --- |
| Towed mass (trolleys + load) | max. 1 000 kg |
| Number of trolleys per train | 2 |
| Trolley requirements | See chapter 5.2 |
| Speed, automatic | 0.50 m/s normal; 0.85 m/s only in sections of the tape route marked for it |
| Speed, manual | max. 0.60 m/s straight; 0.39 rad/s turning on the spot |
| Driving direction, automatic | Forward along the tape. Pivot turns at the end of the tape route only without trolleys |
| Floor | Level, 0 % gradient. Dry, clean, firm; flatness ±5 mm over 2 m; steps max. 5 mm, gaps max. 10 mm |
| Ambient temperature | +5 °C to +40 °C for short periods; +30 °C 24 h average |
| Humidity | 10–90 % RH, non-condensing |
| Altitude | max. 2 000 m |
| Environment | Indoors only. No rain, spray water, dust clouds, steam or smoke that can affect the scanner |
| Lighting | No direct strong light (sunlight, spotlights) into the scanner |

### 2.3 Not intended use and reasonably foreseeable misuse

The following is not allowed:

- riding on the vehicle or on trolleys; transporting persons;
- pushing trolleys in front of the vehicle; towing in reverse;
- towing more than 1 000 kg, more trolleys than allowed, or trolleys that do not meet chapter 5.2;
- pivot turns or U-turns with trolleys coupled;
- operation on ramps, slopes or loading docks; on wet, oily or icy floors; outdoors;
- operation in public areas, on public roads, in residential areas;
- operation in explosive atmospheres, corrosive atmospheres or with ionising radiation;
- transporting hazardous goods;
- operation with a protective device bridged, muted, covered, damaged or with a changed configuration;
- operation in **AUTO** away from the tape, or on a tape route not prepared as in chapter 6;
- driving in **MANUAL** without seeing the vehicle and its path;
- operation by persons who are not instructed;
- modifying the vehicle, its software or its parameters without the manufacturer's approval;
- using the vehicle as a tool to pull, push or lift anything other than approved trolleys.

---

## 3. Safety [O][M][C]

### 3.1 General safety rules

The vehicle moves automatically and can start without anyone at the controls when the operator has pressed **START**. Everyone in the operating zone must know:

- a 2-second warning sound comes before every automatic start;
- the vehicle and its trolleys follow the floor tape;
- the vehicle stops for an obstacle directly in front of it, but **not** for a person beside the tape route or beside the trolleys;
- the **E-STOP** button stops the vehicle at once in every mode.

### 3.2 Personnel and qualifications

| Role | Allowed tasks | Required training |
| --- | --- | --- |
| Operator | Daily check, coupling and uncoupling, **START**/**RESET**, manual driving, charging, clearing operator-level alarms | Instruction with this manual and on the vehicle; record kept by the user |
| Maintenance personnel | Periodic checks (chapter 13), cleaning, inspection, replacement of parts listed in chapter 15.4 | Technical training; electrical work only by an electrically skilled person |
| Commissioning engineer | Site preparation, tape layout, commissioning, parameter changes, safety configuration, engineering pages | Manufacturer training |

### 3.3 Safety functions

As designed, the safety functions are hard-wired: the front safety laser scanner and the emergency stop are evaluated by a safety controller, which removes motor torque through the safe torque off inputs of both motor drivers. The vehicle controller and its software are **not** part of any safety function. They only add speed control, warning sounds and the restart logic for normal operation. The last three rows of the table below are software functions and are not safety-rated. The performance level of each safety function has not yet been validated; see the [REVIEW] notes below.

[IMG-03-01] Block diagram of the safety chain: E-STOP and front scanner → safety controller → STO on both drivers, feedback (EDM) to the safety controller

| Function | Device(s) | Stop type | Reset |
| --- | --- | --- | --- |
| Emergency stop | **E-STOP** push-button `[tag]` (2 NC contacts) → safety controller → STO both drivers | Category 0 `[confirm]`: torque removed, holding brakes applied | Manual: release **E-STOP**, press **RESET**, press **START** |
| Personnel detection, front | Safety laser scanner front `[tag]`, protective field → safety controller → STO | Category 0 `[confirm]` | Automatic, 2 s after the field is clear |
| Mode selection (protective field active only in **AUTO**) | **MANUAL / AUTO** selector `[tag]` → safety controller | — | — |
| Torque-off monitoring | Feedback (EDM) from both drivers → safety controller | Prevents restart if torque-off failed | — |
| Prevention of unexpected start-up | Restart only after **RESET** and a fresh **START** | — | — |
| Warning before automatic start | Alarm sound for 2 s after **START**, before the vehicle moves | — | — |
| Speed reduction near obstacles | Scanner warning fields → vehicle software: half speed, then a controlled stop | Controlled stop | Automatic |
| Hold-to-run in **MANUAL** | Pendant and web jog: releasing the button stops the vehicle | Controlled stop | — |

### 3.4 Protective fields

The front scanner monitors a protective field (safety-related) and two warning fields (not safety-related). Values as configured for the front scanner on `[VALUE: date]` `[confirm against the scanner verification report]`:

| Field | Size in front of the scanner | Width | What happens |
| --- | --- | --- | --- |
| Warning field 1 (outer) | 1.77 m | 1.50 m | Automatic speed halved |
| Warning field 2 (inner) | 0.97 m | 1.20 m | Controlled stop within 0.40 m |
| Protective field | 0.50 m | 0.80 m | Safety stop: torque removed (chapter 3.3) |

The scanner detects objects of 50 mm and larger in a plane about `[VALUE: typ. 150–200; low enough to detect the ISO 3691-4 lying test piece]` mm above the floor. It does **not** detect: objects above or below the scanning plane, glass and mirrors reliably, objects beside the vehicle outside the fields, anything behind the vehicle (there is no rear scanner), and anything beside or behind the trolleys.

[IMG-03-02] Top view: protective and warning fields of the front scanner, with a coupled trolley train

### 3.5 Residual risks

Hazards that remain despite the protective measures. Operators and users must know them.

| Hazard | Situation | What protects you |
| --- | --- | --- |
| Crushing between trolley and fixed objects | Trolleys follow a tighter curve than the vehicle; they are not monitored by any sensor | Clearances (chapter 6.5), floor marking, instruction |
| Being struck from the side | The scanner does not see a person stepping in from the side or between vehicle and trolley | Instruction, marking of the travel path, warning sound |
| Run-over by the vehicle or trolleys | A person falling in front of the vehicle closer than the stopping distance | Protective field sized for the stopping distance; speed limits |
| Uncontrolled trolley | Trolley uncouples during travel; trolley left on the tape route without brake | Coupling check (chapter 10.4), trolley parking brake |
| Trolley jack-knife or overrun | Emergency stop with full load: the train pushes into the vehicle | Towing limits, braked trolleys `[confirm]`, Category 1 stop **[REVIEW]** |
| Unmonitored manual driving | In **MANUAL** the scanner does not stop the vehicle | Hold-to-run, 0.60 m/s, movement sound, operator keeps vehicle in view |
| Trapping by a stopped vehicle | The holding brakes are applied when stopped; the vehicle cannot be pushed | Procedure in chapter 11.3 |
| Tripping | Floor tape, trolley drawbars | Flush tape, protective covering, marking |
| Electric shock, fire | Battery, charger, electrical box | Lock-out (chapter 15.1), charging rules (chapter 12) |
| Hot surfaces | Motors and drivers after long operation (up to 95 °C motor alarm limit) | Let them cool before touching |
| Unauthorised operation over the network | The web interface has no authentication | Closed network; physical **START** always required for automatic driving |

### 3.6 Hazard zones

| Zone | Extent | Rule |
| --- | --- | --- |
| Travel path | Width of the vehicle or the widest trolley + 500 mm each side, clear to a height of 2 100 mm (ISO 3691-4 Annex A), along the whole tape route, including the swept path of the trolleys in curves | Keep free; no standing, no storage |
| Pivot zone | Circle of `[VALUE: vehicle diagonal + 2 × 500]` mm diameter at each pivot point at the end of a tape route | Keep free while the vehicle is there |
| Coupling zone | Between vehicle and trolley, between trolleys | Enter only when the vehicle is stopped (chapter 10.4) |
| Charging area | `[VALUE]` | Chapter 12 |

[IMG-03-03] Top view: hazard zones along the tape route, in curves and at a pivot point

### 3.7 Safety and warning labels on the vehicle

Keep all labels clean and readable. Replace damaged labels (chapter 15.2).

| Label | Meaning | Position |
| --- | --- | --- |
| Warning: automatic vehicle (ISO 7010 W014 or equivalent `[confirm]`) | Vehicle can start without warning other than the horn | `[TBD]` |
| Warning: crushing hazard | Between vehicle and trolley | Rear, at the hitch |
| No riding | Do not ride on vehicle or trolleys | `[TBD]` |
| Electrical hazard | Electrical box, battery | Electrical box cover |
| Read the manual | — | `[TBD]` |
| Maximum towed mass 1 000 kg | — | Near the hitch |
| Tag labels | Tag of each component, matching the circuit diagram | On each component |

[IMG-03-04] Label positions

### 3.8 Warning devices

| Device | Signal | When |
| --- | --- | --- |
| Horn `[tag]`, sound 1 (movement sound) | `[VALUE: tone/pattern]` | Whenever the wheels turn, in any mode including **MANUAL**. Silenced while the alarm sound plays |
| Horn `[tag]`, sound 2 (alarm sound) | `[VALUE: tone/pattern]` | For 2 s after **START**, before the vehicle moves. In **AUTO**, while the protective field is violated or warning field 1 or 2 is occupied |
| Visual warning | Not fitted **[REVIEW]** | — |

---

## 4. Vehicle description [O][M]

### 4.1 Overview

[IMG-04-01] Vehicle overview, side and top view, with callouts

| # | Assembly | Location tag |
| --- | --- | --- |
| 1 | Chassis with two driven wheels (differential drive) and castors `[confirm]` | — |
| 2 | Drive units: 2 × motor with gearhead 1:30 and holding brake, 2 × motor driver | `[tag]` |
| 3 | Battery 48 V with battery management system | `[tag]` |
| 4 | Electrical box with vehicle controller, safety controller, I/O module, circuit breakers | `+[tag]` |
| 5 | Control panel | `+[tag]` |
| 6 | Safety laser scanner, front | `[tag]` |
| 7 | Magnetic line sensor (under the vehicle, front) | `[tag]` |
| 8 | Towing hitch | — |
| 9 | Horn | `[tag]` |
| 10 | Pendant | `[tag]` |

### 4.2 How the vehicle is controlled

| Part | What it does | Safety-related |
| --- | --- | --- |
| **Safety controller** (SICK Flexi Soft) | Evaluates **E-STOP**, front scanner and mode selector; switches off motor torque (STO) | Yes |
| **Safety laser scanner, front** (SICK nanoScan3) | Protective field → stop; warning fields → slow down | Protective field: yes |
| **Motor drivers** (2 × Oriental Motor BLVD-KRD) | Drive the motors on command from the controller; safe torque off on command from the safety controller | STO input: yes |
| **Vehicle controller** (industrial PC) | Follows the tape, controls speed, reads the control panel, shows the web interface, records events | No |
| **I/O module** | Reads the panel buttons and pendant, switches the horn | No |
| **Magnetic line sensor** (SICK MLS) | Measures the position of the tape under the vehicle; reads markers beside the tape | No |

The vehicle controller can only drive the motors while the safety controller allows torque. Whatever the software does, **E-STOP** and the protective field remove torque.

### 4.3 Control panel

[IMG-04-02] Control panel with callouts

| Control | Type | Function |
| --- | --- | --- |
| **E-STOP** `[tag]` | Red mushroom push-button, latching, turn to release | Stops the vehicle at once in every mode |
| **RESET** `[tag]` | Blue push-button | Resets the safety circuit after **E-STOP**; ends a stopped run |
| **START** `[tag]` | Push-button `[VALUE: colour; IEC 60204-1 prefers white, green also permitted]` | Starts or continues automatic operation (**AUTO** only) |
| **MANUAL / AUTO** `[tag]` | Selector switch, 2 positions | Selects the operating mode (chapter 9) |
| **MANUAL ARM** `[tag]` | Switch `[confirm type]` | In **MANUAL**: switches the motors on for manual driving. Off = the vehicle cannot be driven by hand |
| Main switch `[tag]` | `[confirm: battery main circuit breaker]` | Switches the vehicle on and off; lockable `[confirm]` (chapter 15.1) |

**Start-up protection:** a button that is held, or a selector that is already in **AUTO**, when the vehicle switches on or when the panel connection returns, does nothing. Release it and operate it again.

### 4.4 Pendant

[IMG-04-03] Pendant

The pendant is wired to the vehicle. It has four buttons: **FORWARD**, **REVERSE**, **LEFT**, **RIGHT**.

- It works only in **MANUAL** with **MANUAL ARM** on.
- Hold a button to drive; release it to stop (hold-to-run).
- **FORWARD** or **REVERSE** with **LEFT** or **RIGHT** drives a curve; **LEFT** or **RIGHT** alone turns on the spot.
- Pressing two opposite buttons together cancels both.
- A button already held when the pendant becomes active does nothing until it is released and pressed again.
- The pendant has priority over the web interface while a button is held.

> **[REVIEW]** The pendant has no emergency stop and no enabling device.

### 4.5 Web interface

The vehicle shows its state and alarms on web pages, opened on a tablet `[confirm: supplied tablet]` or a PC connected to the vehicle's network. Address: `http://[VALUE: vehicle IP]:5001/`.

| Page | Operator use |
| --- | --- |
| **Home** | State in one line, what to do next, one button for the action (for example **Acknowledge**, **Restart**) |
| **Run** | Current run and stop points; confirmations the vehicle asks for |
| **Manual** | Jog pad for driving by hand (**MANUAL**, **MANUAL ARM** on). Hold to drive, release to stop |
| **Alarms** | Event log; **Save report** for service |

Every page has a status bar on the left (mode, selector, drives, command, run). A yellow bar needs attention; a red bar is a fault or stale data. If the bar is grey and the header shows `DISCONNECTED`, the values are the last known, not live.

Engineering pages (teach, monitor, I/O, parameters) are reserved for the commissioning engineer and are opened with a PIN. They are described in the software documentation.

The web interface cannot start the vehicle in **AUTO**. Automatic driving always needs the physical **START** button.

[IMG-04-04] **Home** page

> **⚠ WARNING — Unauthorised control over the network.**
> The web interface has no user login. Anyone on the network can drive the vehicle by hand while it is in **MANUAL** with **MANUAL ARM** on.
> - Connect the vehicle only to a closed network for this purpose.
> - Switch **MANUAL ARM** off when you leave the vehicle.

### 4.6 Towing hitch

Manual pin or hook hitch `[TBD: pin or hook]`. Coupling height `[VALUE: typ. 200–350]` mm. Maximum drawbar force `[VALUE: est. ≈ 1 200]` N. Secured by `[TBD: securing device, e.g. spring cotter]`.

[IMG-04-05] Towing hitch, coupled and uncoupled

There is no sensor that detects whether a trolley is coupled. The vehicle relies on the operator's confirmation (chapter 10.4).

### 4.7 Guidance

The vehicle follows a magnetic tape on the floor. The line sensor under the front of the vehicle measures the tape position 50 times per second; the controller steers to keep the tape centred. Markers beside the tape can set speed sections and pivot points. Stop points are programmed by the commissioning engineer (software documentation).

If the tape is lost for more than 75 mm of travel, the vehicle stops (`TRACK_LOST`).

---

## 5. Towing [O][C]

### 5.1 Towing capacity

| Item | Value |
| --- | --- |
| Maximum towed mass (all trolleys + load) | 1 000 kg |
| Maximum number of trolleys | `[VALUE: max. trolleys, typ. 3]` |
| Maximum train length | `[VALUE: train length, typ. 3 000–6 000]` mm |
| Maximum drawbar force | `[VALUE: drawbar force, est. ≈ 1 200]` N |
| Floor | Level only (0 %) |

The stopping distance increases with the towed mass (chapter 16.3).

### 5.2 Trolley requirements

Trolleys used with the vehicle must:

- have a drawbar and coupling that fit the hitch (chapter 4.6) and cannot uncouple by themselves;
- have castors in good condition, suitable for the floor;
- follow the vehicle within the swept path used for the clearances (chapter 6.5);
- not be wider than `[VALUE: typ. 600–800]` mm;
- have a parking brake `[confirm]`;
- carry the load secured against sliding and tipping, centre of gravity no higher than `[VALUE: typ. 1 000]` mm.

### 5.3 Rules for towing

- Check every coupling before you press **START** (chapter 10.4).
- Never pivot or make a U-turn with trolleys coupled. Uncouple first.
- Do not drive backwards with trolleys coupled, except to free a person (chapter 11).
- Do not drive in **MANUAL** with trolleys coupled `[confirm]`.
- Uncoupled trolleys must stand clear of the travel path with their brake applied.

> **⚠ WARNING — Trolley run-away.**
> A trolley that is not coupled correctly can separate and keep rolling.
> - Check the pin or hook is fully engaged and secured.
> - Apply the parking brake of every trolley you uncouple.

---

## 6. Operating zone and site preparation [C]

The user prepares and maintains the operating zone (ISO 3691-4 Annex A). The commissioning engineer checks it before handover.

### 6.1 Floor

- Level, 0 % gradient along and across the travel path.
- Firm, dry, clean, free of oil, grease and loose material.
- Flatness `[VALUE: typ. ±5 mm over 2 m]`; no steps over `[VALUE: typ. 5]` mm, no gaps over `[VALUE: typ. 10]` mm.
- Load capacity for the vehicle plus the loaded train.

### 6.2 Magnetic tape

- Magnetic tape type `[VALUE: typ. flexible ferrite tape]`, polarity `[VALUE: N or S pole up, as set in the line sensor]`, width `[VALUE: typ. 50]` mm.
- Minimum curve radius `[VALUE: typ. 1 000]` mm.
- Tape joints flush, no gaps over `[VALUE: typ. 5]` mm.
- Where trolleys or forklifts cross, protect the tape with a protective covering `[VALUE: type, e.g. aluminium or stainless cover strip, or tape recessed into the floor]`.
- Branches and merges as described in the software documentation.

[IMG-06-01] Tape layout rules: curve radius, branch, merge, crossing

### 6.3 Speed sections and pivot points

The higher speed (0.85 m/s) may only be enabled by markers on straight sections where the clearances in 6.5 apply and no pedestrian crossings are present `[confirm]`. Pivot points need a free circle as in chapter 3.6.

### 6.4 Stop points

Place stop points where the operator can couple and uncouple safely: level floor, good lighting, space beside the vehicle and the trolleys, out of pedestrian walkways.

### 6.5 Clearances

| Location | Minimum clearance |
| --- | --- |
| Beside the vehicle and trolleys, along the tape route | 500 mm each side of the swept path, 2 100 mm high (ISO 3691-4 Annex A) |
| In curves | Swept path of the widest trolley train + 500 mm |
| Where clearance cannot be kept | Mark as hazard zone (yellow-black), warning signs, limit access |
| Pedestrian crossings | Marked, good visibility, `[VALUE: e.g. zebra marking and warning signs]` |
| Doors and gates | `[TBD: doors and gates — typ. no automatic doors in the travel path unless linked to the vehicle; warning signs on both sides]` |

[IMG-06-02] Clearance cross-section and swept path in a curve

### 6.6 Marking and signs

- Mark the travel path on the floor `[VALUE: colour, width; typ. yellow, 50–100 mm]`.
- Mark hazard zones where clearances are reduced.
- Put warning signs "Driverless vehicles" at the entrances to the operating zone and at crossings.

### 6.7 Charging area

- Level floor, out of the travel path and pedestrian walkways.
- Ventilated; no combustible material nearby; fire extinguisher `[VALUE: type]` within reach.
- Power supply for the charger `[VALUE: typ. 220–230 V AC, 50 Hz, single phase]`.

---

## 7. Transport, storage and installation [M][C]

### 7.1 Transport

- Unladen mass: `[VALUE: approx. 150 kg]` `[confirm]`.
- Lift only at the lifting points `[TBD: positions]`, with rated equipment. Do not lift under the chassis with forks unless `[TBD]`.
- For transport, switch the vehicle off and lock the main switch (chapter 15.1). Secure the vehicle against rolling and sliding.
- Battery transport rules: `[TBD: depends on chemistry; for lithium-ion: UN 38.3 test summary, vehicle shipped as UN 3171 battery-powered vehicle, class 9]`.

[IMG-07-01] Lifting and tie-down points

### 7.2 Storage

- Indoors, dry, `[VALUE: typ. +5]` °C to `[VALUE: typ. +35]` °C.
- Battery charged to `[VALUE: typ. 50]` %; main switch off; recharge every `[VALUE: typ. 3]` months.

### 7.3 Unpacking and installation

1. Check the packaging and the vehicle for transport damage. Report damage before use.
2. Check the scope of delivery: vehicle, pendant, charger, tablet `[confirm]`, this manual, `[TBD: e.g. charging cable, keys, spare fuses]`.
3. Connect the battery `[TBD: if shipped disconnected]`.
4. Continue with commissioning (chapter 8).

---

## 8. Commissioning [C]

Commissioning is done by the commissioning engineer. The vehicle must not be handed over before every step is done and recorded.

### 8.1 Prerequisites

- Operating zone prepared as in chapter 6.
- Risk assessment of the site by the user available.
- Trolleys checked against chapter 5.2.

### 8.2 First switch-on

1. Selector to **MANUAL**, **MANUAL ARM** off, **E-STOP** released.
2. Switch on the main switch.
3. Wait until the controller has started, about `[VALUE: typ. 60]` s.
4. Press **RESET** to close the safety circuit.
5. Open the **Home** page. It must show `READY` with no alarms. The status bar must show the selector position, Drives `OFF` and no red bar.

### 8.3 Tape route and stop points

1. Lay the tape as in chapter 6.2 and place the speed and pivot markers.
2. Drive along the tape in **MANUAL** and check that the line sensor reads it without `MLS_FIELD_WEAK` or `TRACK_LOST`.
3. Program the stop points (software documentation).
4. Run the tape route in **AUTO** without trolleys, then with the maximum train.

### 8.4 Safety verification

Carry out every check in chapter 13 and record the results in Annex C. In addition:

- verify the scanner fields with a test object (chapter 13) at the front;
- measure the stopping distance at the highest speed used with the maximum towed mass; it must be shorter than the protective field allows (chapter 16.3);
- verify that the safety controller and scanner configuration checksums match the values recorded in the commissioning record `[TBD: where the reference checksums are kept]`.

### 8.5 Changes after commissioning

After any change of the scanner configuration, the safety controller configuration, the speeds, or a motor driver, repeat 8.4 and record it.

### 8.6 Handover

- Instruct the operators with this manual; record the instruction.
- Hand over this manual, the commissioning record and the engineering PIN to the person responsible.

---

## 9. Operating modes [O][C]

### 9.1 Overview

| | **AUTO** | **MANUAL** |
| --- | --- | --- |
| Selected by | Selector in **AUTO** | Selector in **MANUAL** |
| Motion starts | Only with a physical **START** press, after a 2 s alarm sound | Only while a pendant or jog button is held, with **MANUAL ARM** on |
| Who steers | The vehicle, along the tape | The operator |
| Speed | 0.50 m/s; 0.85 m/s in marked sections; halved or stopped by the warning fields | max. 0.60 m/s; 0.39 rad/s on the spot |
| Protective field stop | **Active** | **Muted** |
| **E-STOP** | Active | Active |
| Trolleys | Yes | No `[confirm]` |
| Warning sound | Alarm sound before start and at field events; movement sound while driving | Movement sound while driving |

### 9.2 Changing mode

- Change mode only with the vehicle stopped.
- Turning the selector out of **AUTO** stops a running vehicle at once and ends the run (`AUTHORITY_LOST`). To continue: selector back to **AUTO**, press **START**.
- Turning the selector to **AUTO** does not start the vehicle. Only **START** does.

### 9.3 MANUAL mode

> **⚠ WARNING — No protective field in MANUAL.**
> In **MANUAL** the safety scanner does not stop the vehicle. The vehicle stops only when you release the button, or with **E-STOP**.
> - Keep the vehicle and its path in view at all times.
> - Make sure nobody is in the path before you drive.
> - Drive slowly near people and objects.
> - Switch **MANUAL ARM** off when you stop driving.

---

## 10. Operation [O]

### 10.1 Daily check before use

Do these checks at the start of every shift. Do not use the vehicle if a check fails; report it.

| # | Check | OK when |
| --- | --- | --- |
| 1 | Vehicle, hitch, wheels and castors | No visible damage, nothing loose |
| 2 | Scanner window (front) | Clean, no scratches or cracks |
| 3 | Line sensor and tape | Nothing hanging under the vehicle; tape not lifted or torn |
| 4 | Labels | Present and readable |
| 5 | Battery charge | `[VALUE: typ. 30]` % or more on `[TBD: indicator, e.g. the battery display on the Home page]` |
| 6 | **E-STOP** | Press: the **Home** page shows `ESTOP`; the vehicle cannot be started. Release, **RESET** |
| 7 | Horn | Alarm sound for 2 s after **START**; movement sound while driving |
| 8 | Protective field | Chapter 13, daily test |
| 9 | Trolleys | Couplings, castors and brakes in order |

### 10.2 Switching on

1. Check that nobody is in the travel path.
2. Selector to **MANUAL**, **MANUAL ARM** off.
3. Switch on the main switch.
4. Wait until the **Home** page shows `READY` (about `[VALUE: typ. 60]` s).
5. If the **Home** page shows `SAFETY_RESET_NEEDED` or `BASE_NOT_READY`: press **RESET**.

### 10.3 Driving by hand

1. Selector to **MANUAL**.
2. Check the path is clear.
3. Switch **MANUAL ARM** on. The drives switch on.
4. Hold a pendant button (or a jog button on the **Manual** page) to drive. Release it to stop.
5. When you have finished, switch **MANUAL ARM** off.

The vehicle accelerates gently (about 2.3 s to full manual speed) and stops within about 0.2 m from 0.60 m/s when you release the button.

On the **Manual** page, the vehicle also stops if you switch browser tab, press Space or Esc, or if the network connection drops.

### 10.4 Coupling and uncoupling trolleys

The vehicle stops at programmed stop points. At a stop point it waits (`AT_STATION`) until the operator presses **START**. The drives are not switched off at a stop point; stay out of the path in front of the vehicle.

**Coupling:**

1. Wait until the vehicle has stopped at the stop point and the **Home** page shows `AT_STATION`.
2. Bring the trolley to the hitch. Check the trolley meets chapter 5.2 and the train stays within 1 000 kg.
3. Insert the pin or hook `[TBD: as for the hitch type]` and secure it.
4. Release the trolley's parking brake `[confirm]`.
5. Check: coupling engaged and secured; nobody between the trolleys; load secured.
6. If the vehicle asks for a confirmation on the **Run** page, confirm it.
7. Step out of the travel path and press **START**.

**Uncoupling:**

1. Wait until the vehicle has stopped at the stop point.
2. Apply the trolley's parking brake.
3. Remove the pin or unhook `[TBD]`.
4. Move the trolley clear of the travel path.
5. Confirm the release on the **Run** page if asked.
6. Step out of the travel path and press **START**.

> **⚠ WARNING — Crushing between vehicle and trolley.**
> If somebody presses **START** while you are at the hitch, the vehicle moves off after 2 s.
> - Agree who presses **START** before you couple.
> - Stand beside the hitch, not between vehicle and trolley.

[IMG-10-01] Coupling sequence

The vehicle does not pivot at the end of a tape route while a release has not been confirmed (`PAYLOAD_UNCONFIRMED`).

### 10.5 Automatic operation

1. Place the vehicle on the tape in **MANUAL** (10.3), with the line sensor over the tape, facing the direction of travel.
2. Switch **MANUAL ARM** off.
3. Selector to **AUTO**.
4. Check the path is clear and nobody is at the hitch.
5. Press **START**. The alarm sound plays for 2 s, then the vehicle moves off.

While driving the vehicle:

- follows the tape at 0.50 m/s, and at 0.85 m/s in marked sections;
- halves its speed when something enters warning field 1, and stops smoothly when something enters warning field 2. It continues by itself when the fields are clear;
- stops at the protective field (safety stop) and continues by itself 2 s after the field is clear;
- stops at every programmed stop point and waits for **START**.

If **START** is refused, the reason is shown in the event log and on the **Home** page. Remove the cause and press **START** again. A refused press is not remembered.

### 10.6 Stopping

| How | Effect | To continue |
| --- | --- | --- |
| Something in the protective field | Safety stop | Automatic, 2 s after the field is clear |
| **RESET** while a run is active | Run ends; vehicle stops `[confirm: controlled]` | **START** |
| Selector out of **AUTO** | Vehicle stops at once; run ends | Selector to **AUTO**, **START** |
| **E-STOP** | Safety stop, torque removed, brakes applied | Chapter 10.7 |

For a normal stop between stop points, use **RESET** or the selector `[confirm preferred method]`. Use **E-STOP** in an emergency.

### 10.7 After an emergency stop

1. Remove the cause of the emergency.
2. Turn the **E-STOP** button to release it.
3. Press **RESET** (blue). The safety circuit closes.
4. Check that nobody is in the path.
5. In **AUTO**: press **START**. The alarm sound plays for 2 s, then the vehicle continues.

### 10.8 After the tape is lost

If the vehicle leaves the tape it stops (`TRACK_LOST`).

1. Selector to **MANUAL**, **MANUAL ARM** on.
2. Uncouple the trolleys first. Then drive the vehicle back so the line sensor is over the tape.
3. **MANUAL ARM** off, selector to **AUTO**, press **START**.

### 10.9 Switching off

1. Stop the vehicle at a stop point or in the parking position `[TBD]`, uncoupled from trolleys.
2. Selector to **MANUAL**, **MANUAL ARM** off.
3. `[TBD: shut down the controller first, if required — confirm]`
4. Switch off the main switch.

---

## 11. Emergency situations [O][M]

### 11.1 Emergency stop

Press **E-STOP**. Motor torque is removed and the holding brakes in both motors apply.

### 11.2 Fire

1. Press **E-STOP**. Switch off the main switch if it is safe to reach.
2. Raise the alarm. Leave the area.
3. Fight a fire only if trained and safe: extinguisher type `[VALUE: suitable for the battery chemistry]`.

### 11.3 Freeing a trapped person

The vehicle stops with its holding brakes applied. It **cannot be pushed** by hand: the brakes stay closed when the drives are off, and there is no manual brake release.

To move the vehicle away from a person:

1. Keep **E-STOP** pressed until you are ready.
2. Uncouple the trolley if it is part of the trap; move the trolley by hand (its brake released).
3. Release **E-STOP**, press **RESET**.
4. Selector to **MANUAL**, **MANUAL ARM** on.
5. Drive the vehicle away from the person with the pendant (**REVERSE** or **FORWARD**), slowly.
6. **MANUAL ARM** off, **E-STOP**. Give first aid; call help.

If the vehicle has no power or cannot be driven: `[TBD: procedure — lifting the vehicle, releasing the brake]`.

> **[REVIEW]** No manual brake release exists. ISO 3691-4 requires a way to free trapped persons. A brake release method with no power is needed.

### 11.4 Vehicle out of control

Press **E-STOP**. Take the vehicle out of service; inform maintenance.

### 11.5 Contact with the battery electrolyte or a damaged battery

`[TBD: depends on battery chemistry]`

---

## 12. Battery charging [O][M]

### 12.1 Battery and charger

| Item | Value |
| --- | --- |
| Battery | `[VALUE: chemistry, typ. LiFePO₄]`, 48 V nominal, `[VALUE: typ. 50–100]` Ah, with battery management system |
| Operating voltage range | `[VALUE: typ. 40–58 V for a 16-cell LiFePO₄ pack]`; the vehicle warns below 42 V and above 56 V |
| Charger | `[VALUE: model]`, input `[VALUE: typ. 220–230 V AC, 50 Hz]` |
| Charging time | `[VALUE: typ. 2–4]` h from `[VALUE: typ. 20]` % |
| Operating time per charge | `[VALUE]` h |

### 12.2 Charging procedure

1. Drive the vehicle to the charging area in **MANUAL**, uncoupled.
2. **MANUAL ARM** off, **E-STOP** pressed `[confirm]`.
3. `[TBD: main switch off or on during charging]`.
4. Connect the charger to the vehicle's charging socket `[tag]`, then switch on the charger.
5. Charging is shown by `[TBD: indicator, e.g. charger LED or the battery display on the Home page]`.
6. When charged: switch off the charger, then disconnect.
7. Release **E-STOP**, **RESET**.

[IMG-12-01] Charging socket and charger connection

### 12.3 Battery safety

> **⚠ WARNING — Fire and electric shock from the battery.**
> - Use only the supplied charger.
> - Do not charge a damaged, swollen or hot battery.
> - Do not cover the vehicle or the charger while charging.
> - Do not open the battery.

---

## 13. Safety-function checks [O][M]

Record each check in Annex C. If a check fails, take the vehicle out of service.

| Check | How | Pass criterion | Interval | By |
| --- | --- | --- | --- | --- |
| **E-STOP** | In **AUTO**, drive at normal speed, press **E-STOP** | Vehicle stops; **Home** shows `ESTOP`; **START** does nothing until **RESET** | Daily | O |
| Protective field, front | In **AUTO**, place the ISO 3691-4 test piece (cylinder 200 mm diameter, 600 mm high) `[confirm]` in the protective field in front of the stopped vehicle, press **START** | Vehicle does not move; moves off 2 s after the object is removed | Daily | O |
| Horn | Press **START** in **AUTO** | 2 s alarm sound before moving | Daily | O |
| Hold-to-run | In **MANUAL**, drive with the pendant, release | Vehicle stops at once | Daily | O |
| Mode selector | During an automatic run, turn the selector to **MANUAL** | Vehicle stops | Weekly | O |
| Scanner fields, full | Test object at the field edges of the front scanner; compare with the verification report | Stops at the configured edges | Every 3 months and after any change | M |
| Safe torque off (STO) and feedback | `[TBD: procedure from the safety controller report — each channel]` | `[TBD]` | Every 3 months | M |
| Stopping distance and brakes | At 0.85 m/s with maximum towed mass, trigger the protective field; measure | Within `[VALUE]` mm | Every 3 months | M |

---

## 14. Fault finding and alarms [O][M]

### 14.1 Where alarms are shown

- The **Home** page shows the current state, the reason and the action in one sentence, with a button if one is needed.
- The **Alarms** page shows the event log. **Save report** packs the logs for service.
- The alarm sound plays in **AUTO** while a scanner field is occupied.

### 14.2 Alarm list (operator)

Alarms from navigation features (stop-point reader, map navigation) are listed in the software documentation. The complete list is generated from the vehicle software and kept in Annex E.

| Code | The vehicle shows | What to do |
| --- | --- | --- |
| `FIELD_PROTECTIVE`, `FIELD_BLOCKED` | Stopped: something is in the protective field | Clear the area in front of the vehicle. It continues by itself |
| `FIELD_WARNING` | Slowed or stopped: something is in a warning field | Clear the area. Speed returns by itself |
| `ESTOP` | Stopped: emergency stop or safety chain | Release **E-STOP**, press **RESET**, then **START** |
| `SAFETY_RESET_NEEDED` | Motors are off: the safety circuit needs a reset | Press **RESET** (blue) |
| `DRIVES_NOT_READY` | Stopped: the motors are not powered | **MANUAL**: switch **MANUAL ARM** on. **AUTO**: press **START** (after **RESET** if **E-STOP** was used) |
| `AUTHORITY_LOST` | Stopped: the vehicle lost permission to drive | Selector back to **AUTO**, press **START** |
| `AT_STATION` | Parked at a stop point | Do the work at the stop point, press **START** |
| `PAYLOAD_UNCONFIRMED` | Stopped before the pivot: a release is not recorded | Check the trolley is uncoupled, confirm on **Run**, press **START** |
| `TRACK_LOST` | Stopped: the tape is not under the sensor | Drive back onto the tape in **MANUAL** (chapter 10.8), then **START** |
| `MLS_SILENT` | Stopped: the tape sensor stopped reporting | Check the sensor and cable; when it reports, check the position, press **START** |
| `MLS_FIELD_WEAK` | Weak tape signal | Nothing now. Maintenance checks the tape at this place |
| `TRACK_RATE_LOW` | Stopped: the tape sensor is too slow | Call maintenance |
| `PANEL_LINK_LOST` | Stopped: the control panel link dropped | Check panel and I/O module; when it answers, press **START** |
| `PANEL_STALE` | The control panel is not answering | Call maintenance |
| `FIELD_UNKNOWN`, `SCANNER_SILENT`, `SCANNER_STALE` | No scanner data | The safety stop still works. Do not run in **AUTO**; call maintenance |
| `LINE_PREREQ_LOST` | Stopped: a condition for driving lapsed | Read the reason; fix it; press **START** |
| `WAITING_FOR_PREREQ` | Waiting for a sensor or the panel | Wait. If it stays, look at **Alarms** |
| `SOURCE_TIMED_OUT` | The command stopped arriving (manual driving) | Press and hold again; check the network |
| `DRIVE_ALARM`, `DRIVE_FAULT`, `DRIVE_SILENT`, `DRIVE_LINK_FAULT`, `CAN_TX_FAILED` | Drive fault | Switch the drives off and on `[confirm: how]`, wait, then maintenance presses **Recover** |
| `DRIVE_STOP_UNCONFIRMED` | The vehicle cannot confirm it stopped | Stay clear. Power-cycle the drives; maintenance presses **Recover** |
| `UNCLEAN_SHUTDOWN` | The vehicle lost power last time | Power-cycle the drives, press **RESET** |
| `BASE_NOT_READY` | The vehicle's basics did not come up | Press **RESET** |
| `SERVICE_CRASHED` | The software restarted itself | Nothing. Tell maintenance if it repeats |
| `SUPERVISOR_DOWN`, `BASE_EXITED`, `WEB_DOWN`, `BOOT_ERROR` | Needs service: software stopped | Press **Restart** on **Home**; if it repeats, call maintenance |
| `DISK_LOW`, `DISK_FULL` | Storage low / full | Call maintenance. Driving is not affected |
| `MLS_TEMP` | Line sensor outside its temperature range | Call maintenance |

### 14.3 Faults without an alarm

| Symptom | Possible cause | Action |
| --- | --- | --- |
| Nothing lights or starts at main switch on | Battery empty; main breaker tripped; battery switched off | Charge; check breakers `[tag]` (maintenance) |
| Web page does not open | Tablet not on the vehicle's network | Connect the tablet to network `[VALUE]` |
| Vehicle does not move in **MANUAL** | **MANUAL ARM** off; button held since power-on | Switch **MANUAL ARM** on; release and press again |
| **START** does nothing | Selector not in **AUTO**; **E-STOP** pressed; button held at power-on | Check selector, **E-STOP**; release and press again |
| Frequent stops without obstacle | Dirty scanner window; strong light; reflective objects | Clean; check the area |

### 14.4 Service contact

PT INTI GANDA PERDANA service: iprime-service@igp-astra.co.id · `[TBD: phone, service hours]`

---

## 15. Maintenance [M]

### 15.1 Lock-out before maintenance

Before any work inside the vehicle, on the wheels, or on the electrical equipment:

1. Stop the vehicle off the travel path; uncouple all trolleys.
2. Selector to **MANUAL**, **MANUAL ARM** off, press **E-STOP**.
3. Switch off the main switch `[tag]`.
4. Lock it in the off position with a personal padlock `[confirm: lockable]`; attach a tag with your name.
5. Check the vehicle is dead: try **RESET** and the pendant; nothing must happen.
6. Wait `[VALUE: per the BLVD-KRD operating manual]` min for the motor drivers' capacitors to discharge before opening the electrical box.

Work on the electrical box only by an electrically skilled person. The battery stays live even when the main switch is off.

> **⚠ DANGER — Electric shock and short circuit at the battery.**
> The battery terminals and the circuit up to the main switch are always live.
> - Use insulated tools.
> - Do not short-circuit the battery terminals.

### 15.2 Maintenance schedule

| Item | Task | Interval | By |
| --- | --- | --- | --- |
| Scanner window | Clean (15.3); check for scratches | Daily, or at the scanner's contamination warning | O |
| Wheels and castors | Check tread, wear, foreign objects; tighten fixings | Monthly | M |
| Gearheads and wheel couplings | Inspect for play, noise, oil leaks | Every 3 months | M |
| Holding brakes | Stopping-distance check (chapter 13) | Every 3 months | M |
| Safe torque off and feedback | Check (chapter 13) | Every 3 months | M |
| Hitch | Check wear, pin and securing device | Monthly | M |
| Line sensor | Check height above floor `[VALUE: per SICK MLS data sheet, typ. 20–40]` mm; clean | Every 3 months | M |
| Cables and connectors | Check for damage, strain relief | Every 3 months | M |
| Labels | Readable; replace if needed | Every 3 months | M |
| Battery | `[TBD: per battery manual; typ. check connectors and cables, read the BMS log]` | `[TBD: battery interval, typ. monthly]` | M |
| Magnetic tape | Check for wear, lifting; repair | Monthly; at `MLS_FIELD_WEAK` | M |
| Motor and driver temperature | Check the **Alarms** log for temperature warnings (driver 70 °C, motor 80 °C) | Monthly | M |

### 15.3 Cleaning

- Scanner window: soft clean cloth and `[VALUE: cleaner per SICK instructions, e.g. SICK anti-static plastic cleaner and lens cloth]`. No solvents, no abrasives.
- Line sensor face: dry cloth.
- Vehicle body: damp cloth. No water jet.

### 15.4 Replacing parts

Use only spare parts from the component list.

| Part | Who | After replacement |
| --- | --- | --- |
| Wheels, castors | M | Check tape following |
| Safety laser scanner | Commissioning engineer | Load configuration, verify fields (chapter 8.4) |
| Safety controller or its system plug | Commissioning engineer | Verify configuration checksum and all safety functions |
| Motor driver | Commissioning engineer | Parameters from the reference file; check STO wiring jumpers removed; STO check |
| Motor | M + commissioning engineer | Stopping-distance check |
| **E-STOP**, **RESET**, selector | Electrically skilled person | Chapter 13 checks |

---

## 16. Technical data [O][M][C]

### 16.1 Vehicle

| Item | Value |
| --- | --- |
| Dimensions (L × W × H) | `[VALUE: L × W × H; W est. ≈ 600 from the 487 mm track width]` mm |
| Unladen mass | `[VALUE: approx. 150]` kg `[confirm]` |
| Towed mass | max. 1 000 kg |
| Track width (wheel centres) | 487 mm |
| Drive wheel diameter | 180 mm |
| Drive | 2 × Oriental Motor BLV Series R brushless motor, 400 W, gearhead 1:30, electromagnetic holding brake `[confirm]` |
| Motor drivers | 2 × Oriental Motor BLVD-KRD, CANopen, safe torque off (HWTO) |
| Speed, automatic | 0.50 m/s; 0.85 m/s in marked sections |
| Speed, manual | 0.60 m/s; 0.39 rad/s on the spot |
| Deceleration (controlled stop) | 1.0 m/s² unladen `[confirm with load]` |
| Guidance | Magnetic tape, SICK MLS line sensor |
| Battery | 48 V nominal, `[VALUE: chemistry, capacity; typ. LiFePO₄, 50–100 Ah]` |
| Control voltage | 24 V DC |
| Safety controller | SICK Flexi Soft FX3-CPU0 + FX3-XTIO84002 `[confirm]` |
| Safety laser scanner | 1 × SICK nanoScan3 (front) `[VALUE: type, e.g. Core I/O NANS3-AAAZ30AN1]`, 50 mm resolution, response time 130 ms |
| Vehicle controller | Industrial PC `[VALUE: model]` |
| I/O module | CK-EC5163, 16 DI / 12 relay DO, Modbus TCP |
| Communication | Web interface over `[VALUE: Wi-Fi / Ethernet; typ. Wi-Fi 2.4/5 GHz, which needs Indonesian radio type approval [confirm]]` |
| IP rating | `[VALUE: IP rating, typ. IP20–IP54 for indoor vehicles]` |
| Ambient conditions | Chapter 2.2 |

### 16.2 Noise

| Item | Value |
| --- | --- |
| A-weighted emission sound pressure level at the operator position | `[VALUE]` dB(A) |
| Horn sound level | `[VALUE]` dB(A) at `[VALUE]` m |

### 16.3 Stopping distance and time

Measured from the moment an object enters the protective field until standstill, on a level floor `[VALUE: surface, friction]`, battery at `[VALUE]` V.

| Speed [m/s] | Towed mass [kg] | Stopping distance [mm] | Stopping time [s] |
| --- | --- | --- | --- |
| 0.50 | 0 | `[VALUE]` | `[VALUE]` |
| 0.50 | 1 000 | `[VALUE]` | `[VALUE]` |
| 0.85 | 0 | `[VALUE]` | `[VALUE]` |
| 0.85 | 1 000 | `[VALUE]` | `[VALUE]` |
| 0.60 (manual) | 0 | `[VALUE]` | `[VALUE]` |

> **[REVIEW]** Not yet measured. At 0.85 m/s the scanner response (130 ms) alone takes about 0.11 m of the 0.50 m protective field. The stopping distance with 1 000 kg towed must be measured and the field confirmed against ISO 13855.

---

## 17. Decommissioning and disposal [M]

1. Switch off, lock out (chapter 15.1).
2. Remove the battery `[TBD: procedure]`. Return it to `[TBD: battery maker's take-back scheme or a licensed B3 hazardous-waste collector (Indonesia)]`.
3. Dispose of electrical and electronic parts separately, according to local regulations.
4. Metal parts: recycling.
5. Remove the tape from the floor if the tape route is taken out of use.

---

## Annexes

### Annex A — Component list

See document `[TBD: number]`. Not reproduced here.

### Annex B — Circuit diagrams

See document `[TBD: number]`. Not reproduced here.

### Annex C — Safety-check record

| Date | Check (chapter 13) | Result (OK / not OK) | Remarks | Name | Signature |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

### Annex D — Glossary

| Term | Meaning |
| --- | --- |
| AGV | Automated guided vehicle; here a driverless industrial truck (ISO 3691-4) |
| AUTO | Operating mode in which the vehicle follows the tape by itself |
| E-STOP | Emergency stop push-button |
| EDM | External device monitoring: feedback from the motor driver that torque is off |
| Holding brake | Spring-applied brake in each motor; closed whenever the motor is not powered |
| MANUAL | Operating mode in which the operator drives the vehicle with hold-to-run controls |
| MANUAL ARM | Switch that powers the motors for manual driving |
| OSSD | Output signal switching device: the safe output of the safety scanner |
| PL | Performance level according to ISO 13849-1 |
| Protective field | Area monitored by the safety scanner; an object in it stops the vehicle |
| STO | Safe torque off: removal of motor torque by the safety function |
| Stop point | Position on the tape route where the vehicle stops and waits for **START** |
| Trolley train | All trolleys coupled behind the vehicle |
| Warning field | Area monitored by the scanner that slows the vehicle (not safety-related) |

### Annex E — Complete alarm list

`[TBD: generated from the vehicle software alarm catalogue at release]`

---

## Editorial: review notes summary (remove before release)

| # | Topic | Where | Gap |
| --- | --- | --- | --- |
| 1 | Stop category | 3.3 | Category 0 stops with a trolley train; SS1 not built |
| 2 | Safe speed | 3.3 | No safety-rated speed monitoring |
| 3 | Manual mode | 3.3, 9.3 | Protective field muted; compensating measures are software only; 0.60 m/s |
| 4 | Rear detection | 3.3, 3.4 | No rear scanner fitted; no personnel detection behind the vehicle or the trolley train |
| 5 | Visual warning | 3.8 | No beacon or lamp fitted |
| 6 | Pendant | 4.4 | No emergency stop, no enabling device |
| 7 | Rescue / brake release | 11.3 | No way to release the brakes without power |
| 8 | Stopping distance | 16.3 | Not measured; protective field 0.50 m |
| 9 | Standards list | Regulations and standards | Indonesian requirements (radio type approval, battery rules) open |

## Editorial: image register (remove before release)

| ID | Chapter | Shows | Purpose | Needed? |
| --- | --- | --- | --- | --- |
| IMG-01-01 | 1.3 | Nameplate and its position | Identification | ☐ |
| IMG-03-01 | 3.3 | Safety chain block diagram | Explains the safety functions | ☐ |
| IMG-03-02 | 3.4 | Scanner fields, top view, with trolley train | Safety — hard to describe in words | ☐ |
| IMG-03-03 | 3.6 | Hazard zones along the tape route and at a pivot | Safety | ☐ |
| IMG-03-04 | 3.7 | Label positions | Labels | ☐ |
| IMG-04-01 | 4.1 | Vehicle overview with callouts | Orientation, tag lookup | ☐ |
| IMG-04-02 | 4.3 | Control panel with callouts | Operation | ☐ |
| IMG-04-03 | 4.4 | Pendant | Operation | ☐ |
| IMG-04-04 | 4.5 | **Home** page | Operation | ☐ |
| IMG-04-05 | 4.6 | Towing hitch, coupled and uncoupled | Coupling | ☐ |
| IMG-06-01 | 6.2 | Tape layout rules | Site preparation | ☐ |
| IMG-06-02 | 6.5 | Clearance and swept path in a curve | Site preparation | ☐ |
| IMG-07-01 | 7.1 | Lifting and tie-down points | Transport | ☐ |
| IMG-10-01 | 10.4 | Coupling sequence | Operation | ☐ |
| IMG-12-01 | 12.2 | Charging connection | Charging | ☐ |
