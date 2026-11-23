# IO mapping: motor drivers, safety PLC, drive monitor, digital IO module

Source: `proj01-sheet-00..10.html`, updated 2026-11-15 to the owner-confirmed hardware and the IEC set (`../01-schematic-iec/`, circuit diagram IGP-IPR-CD-001). The IEC tag of each device is given in brackets after its JIS name, as on the sheets; the full list is `../01-schematic-iec/designation-map.md`. PNG, PDF and anything in the root codebase can be stale and were not used.
Terminal-block numbers are left out on purpose. This is just what goes where.

Net names used below: `1P24` / `1N24` = 24 V / 0 V after MCB-04 (1-pole: only + is switched). `1N48` = 48 V return.
Driver 01 = LEFT motor, Driver 02 = RIGHT motor.

---

## 1. Motor drivers (2 × BLVD-KRD, Oriental Motor): DRIVER 01 (-TA1), DRIVER 02 (-TA2)

Sheets 02, 04, 06, 07.

### Power (driver power connector, cable LC03D06A)

| Driver | 48 V + | 48 V − | Earth |
|---|---|---|---|
| Driver 01 (-TA1, left) | 2P48 (battery -GB1 → MCB-01 (-QA1) → MCB-02 (-FC1), ABB S201-C13, 1P 13 A) | 1N48 | PE |
| Driver 02 (-TA2, right) | 3P48 (battery -GB1 → MCB-01 (-QA1) → MCB-03 (-FC2), ABB S201-C13, 1P 13 A) | 1N48 | PE |

- All motor and brake power comes in on the LC03D06A cables, through the driver.
- Motors (-MA1 left, -MA2 right): BLMR6400SKM-GFV-B with gearhead GFS6G30FR (1:30).
- The motor itself (UVW and encoder) connects with the Oriental Motor cable CCM020B1AAF (2 m). The 28-pin connector below is for control only.

### 28-pin control connector: wired pins

Same on both drivers. Only the pins below are connected.

| Pin | Signal | Goes to | What it is |
|---|---|---|---|
| 5 | CAN_L | CAN L bus (sheet 06) | Drive command and feedback from the IPC |
| 6 | CAN_H | CAN H bus (sheet 06) | same |
| 7 | CAN_GND | CAN GND bus (sheet 06) | same |
| 20 | NET-VIN | 1P24 | 24 V supply for the driver's control and network side. Wire marker at the driver: 1P24 |
| 21 | NET-GND | 1N24 | its 0 V. Wire marker at the driver: 1N24 |
| 11 | HWTO1+ | Safety PLC **Q1** | Hardwired torque-off channel 1 |
| 12 | HWTO1− | 1N24 | HWTO1 return |
| 26 | HWTO2+ | Safety PLC **Q2** | Hardwired torque-off channel 2 |
| 27 | HWTO2− | 1N24 | HWTO2 return |
| 14 | EDM− | Safety PLC **I3** (driver 01) or **I4** (driver 02) | Feedback so the PLC can check that torque-off really happened |
| 28 | EDM+ | 1P24 | EDM supply |

- Q1 and Q2 each feed both drivers in parallel. Driver 02's HWTO+ is jumpered on the terminal block from Driver 01's.
- The factory jumpers 11–25, 12–26 and 13–27 are **removed** on both drivers.
- Not connected: pins 1–4 (OUT0/OUT1), 8–10 and 22–24 (485 / TR), 13 (0V), 15–19 (IN-COM, IN0–IN3), 25 (+V). The drivers take no commands on their own digital inputs. Motion comes only over CAN.
- All safety wiring is AWG22 orange.

### CAN bus (sheet 06)

- The USB-CAN interface (-TF1) is a **CANable V2.0S** on the **IPC USB port** (-KE3, NEXCOM NEU-X102-N97). It feeds a single CAN H / L / GND bus, 125 kbit/s, CANopen.
- The 120 Ω termination is **built into the CANable V2.0S**. There is no separate terminating resistor at that end.
- On the bus: Driver 01 (node 1), Driver 02 (node 2), the **MLSE line sensor** (-BG3, node 10) and the **battery BMS** (-GB1).
- The line sensor **SICK MLSE-0200A2NQ0** has **no internal terminator**, so the far bus end is open «confirm».
- Line sensor cable: SICK YF2A14-020UB3XLEAX (M12 4-pin female → open end). It carries power and CAN:

| M12 pin | Core | Signal | Goes to |
|---|---|---|---|
| 1 | brown | L+ | 1P24 (sheet 04) |
| 2 | white | CAN-H | CAN H bus (sheet 06) |
| 3 | blue | GND | 1N24 (sheet 04) |
| 4 | black | CAN-L | CAN L bus (sheet 06) |

---

## 2. Safety PLC (SICK Flexi Soft): -KE1, -KE2, -KE5

Sheets 03, 07, 08, 10.

- **FX3-CPU0** main module (-KE1), with system plug **FX3-MPL000001**: only 24 V power (A1 = 1P24, A2 = 1N24, in parallel with the XTIO). No field IO is drawn on it.
- **FX3-XTIO84002** (-KE2): all the field safety IO, below.
- **FX3-MOC0** drive monitor (-KE5): supplied over FLEXBUS+ (no wiring). It reads the two safety encoders (section 3).

### Supply

| Terminal | Goes to |
|---|---|
| A1 | 1P24 |
| A2 | 1N24 |

### Inputs

| Terminal | Goes to | What is connected |
|---|---|---|
| X1 → I1 | E-stop push-button contact 1 (NC) | **Emergency stop** (-SJ1), red, turn to release, 2 NC. Test output X1 goes through the first NC pole and returns on I1. Wire markers: X1 out, ESTOP1 back. |
| X2 → I2 | E-stop push-button contact 2 (NC) | Same E-stop, second pole. X2 goes through it and returns on I2. Wire markers: X2 out, ESTOP2 back. |
| I3 | Driver 01 EDM− (pin 14) | Left motor driver feedback |
| I4 | Driver 02 EDM− (pin 14) | Right motor driver feedback |
| I5 | SAFETY LIDAR 01 **OSSD1.A** (M12 pin 2) | Lidar safety output, via SICK cable YF2A18-050UA5XLEAX |
| I6 | SAFETY LIDAR 01 **OSSD1.B** (M12 pin 4) | same |
| I7 | **MANUAL/AUTO selector switch** (-SJ4), pole 1 (NO) | Fed from 1P24. Wire marker: MANUAL. |
| I8 | **RESET push-button** (-SJ3, yellow), pole 1 (NO) | Fed from 1P24. Wire marker: RESET. |

The selector and the reset button each have two NO poles. Pole 1 goes to the safety PLC (above). Pole 2 goes to the digital IO module (section 4), wired to 1N24 on the other side.

### Outputs

| Terminal | Goes to | What it does |
|---|---|---|
| Q1 | HWTO1+ on Driver 01 **and** Driver 02 | Safe torque-off channel 1 |
| Q2 | HWTO2+ on Driver 01 **and** Driver 02 | Safe torque-off channel 2 |
| Q3 | **DI09** on the DIO module (section 4) | E-stop status for the vehicle software, ON = E-stop not pressed. Follows E-stop I1/I2 only (not the scanner), not latched, **test pulses off** (feeds a standard input). Not a safety function. Added 2026-11-15; the wire is fitted (owner, 2026-11-15). Wire marker: DI09 |
| Q4 | not connected | spare |

Q1 / Q2 also switch off on overspeed in AUTO (safely-limited speed, FX3-MOC0, section 3).

### Safety lidars (sheet 03)

- **SAFETY LIDAR 01** (-BG1, front): SICK nanoScan3 Core I/O **NANS3-AAAZ30AN1**, system plug **NANSX-AAABAEZZ1**.
  - Power and OSSD: M12 8-pin, cable SICK YF2A18-050UA5XLEAX (open end). Pin 1 = +24 V (1P24), pin 3 = 0 V (1N24), pin 2 = OSSD1.A → I5, pin 4 = OSSD1.B → I6.
  - Ethernet (scanner data only, not safety): cable SICK YM2D24-020PN1MRJA4 (M12 D-coded → RJ45) to the IPC port **enp1s0**.
- **SAFETY LIDAR 02** (-BG2, rear): **NOT FITTED** in this revision. Its 24 V supply on sheet 03 is drawn dashed. No OSSD inputs are reserved for it.

---

## 3. Drive monitor FX3-MOC0 (-KE5) and safety encoders (-BG5, -BG6) (sheet 10)

- Two **SICK DFS60S-BAOL01024** safety encoders (sin/cos, 1024 periods), one per wheel shaft. ENC1 = -BG5 = left wheel, ENC2 = -BG6 = right wheel «confirm».
- Encoder supply is 24 V from the MOC0.
- Each encoder cable has an M12 8-pin plug. The **SICK FX3-MOC Y-CABLE 2116199** joins both to the MOC0's Micro D-sub 15. **All 8 encoder wires go through.**
- Functions: safely-limited speed in AUTO (overspeed → STO via XTIO Q1 / Q2) and standstill monitoring. Limits: 1.1 m/s overspeed, 20 mm/s standstill (circuit diagram page 45, operation manual 3.3).
- No terminal blocks: plug-in cables only.

| Encoder M12 pin | Core | Encoder signal | ENC1 D-sub pin | ENC2 D-sub pin | MOC0 signal |
|---|---|---|---|---|---|
| 2 | white | COS+ | 1 | 8 | A+ |
| 1 | brown | COS− | 9 | 15 | A− |
| 4 | pink | SIN+ | 2 | 7 | B+ |
| 3 | black | SIN− | 10 | 14 | B− |
| 5 | yellow | Z̄ | 3 | 6 | C+ |
| 6 | violet | Z | 11 | 13 | C− |
| 8 | red | +US | 4 | 5 | 24 V |
| 7 | blue | GND | 12 | 12 | 0 V (shared) |

Z̄ goes to C+ and Z to C−. The C input is not evaluated in sin/cos mode.

---

## 4. Digital IO module (-KE4, CKDZ-IoT CK-TP5162, 16 DI / 16 DO, Ethernet)

> **gvievo-ce branch: this section describes the kyb unit (host `gvipc-evo-01`, ex `kyb-trackless`),
> updated 2026-11-23.** It is the vehicle this branch runs on; the rest of this file is still the
> gvievo-main unit's drawing set. The software map is `profiles/agv-01.json`.

The audio horn's two sound inputs are switched by DO0 (movement) and DO1 (alarm).

### Supply and Ethernet

| Port | Goes to |
|---|---|
| Ethernet | **IPC** (-KE3) port **enp1s0** (host 192.168.1.100/24), module at **192.168.1.40:502**, unit 1 |

IPC ports on this unit: enp1s0 = this module, enp2s0 = nanoScan3 (host 192.168.3.1, scanner
192.168.3.10), enp3s0 = empty (the GLS621 camera is gone). CAN (`can0`): drivers 1 and 2, MLSE
node 10 (IMU only: this unit runs trackless, `tracked: false`).

### Digital inputs

| Input | Device | Notes |
|---|---|---|
| DI00 | **PB START** | |
| DI01 | **MANUAL/AUTO selector** | ON = MANUAL (`panel.auto_when_on` false) |
| DI02 | **PB RESET** | |
| DI03 | Pendant **FORWARD** | |
| DI04 | Pendant **REVERSE** | |
| DI05 | Pendant **LEFT** | |
| DI06 | Pendant **RIGHT** | |
| DI07 | not used | |
| DI08 | **ESTOP OK** from safety PLC **Q3** | COM1 group. HIGH = E-stop released, LOW = pressed (or wire broken): profile `panel.di_estop` 8, `estop_active_high` false. Checked on the vehicle 2026-11-23: press LOW / release HIGH, no dips over 20 s |
| DI09 | not used: pendant arm switch | Still wired, **not read** (owner 2026-11-23). There is no Manual Arm input: MANUAL is always armed unless an emergency |
| DI0A–DI0F | not used | The kyb destination buttons (DI0A–DI0C) and Continue (DI0D) were removed from the software 2026-11-23 |

### Digital outputs

| Output | Status |
|---|---|
| DO0 | **Audio horn, sound 1 (movement)**: on while the motors turn (`dio.motion_on`, `movement_horn`) |
| DO1 | **Audio horn, sound 2 (alarm)**: pre-move warning, occupied field in AUTO, operator call (`dio.alarm_on`) |
| DO2–DO7 | Spare, not used by the software. |
| DO8–DOF | Not wired. |

---

## Wire markers

The sheets use the marker names of circuit diagram page 76: X1, X2, ESTOP1, ESTOP2, MANUAL, RESET, OSSD1, OSSD2, EDM-L, EDM-R, HWTO1, HWTO2, DI00–DI06, DI08, DI09, DO0, DO1, CAN H, CAN L, CAN GND. A conductor on a potential carries the potential name (1P24, 1N24, 2P48 …). Changed on 2026-11-15 to match: the E-stop return wires were I1 / I2, the driver network-supply ends were NET-VIN-01 / NET-GND-01 and -02.

Wire colours and terminal-block numbers on the sheets are as built (48 V red, safety orange, control blue; TB01–TB71). The IEC set shows the planned colours and no terminal numbers.

## Things the sheets do not settle

- **Selector polarity.** Sheet 08 labels the I7 line "MANUAL". The IEC set (page 40) takes the contacts as closed in MANUAL; the JIS sheet does not show it.
- **CAN far bus end.** Open, because the MLSE has no terminator «confirm».
- **Encoder sides.** ENC1 = left, ENC2 = right «confirm».
- **CK-TP5162 terminal layout.** Not documented; sheet 09 draws a simplified block.
