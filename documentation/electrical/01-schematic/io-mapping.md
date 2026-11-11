# IO mapping: motor drivers, safety PLC, drive monitor, digital IO module

Source: `proj01-sheet-00..10.html`, updated 2026-11-09 to the owner-confirmed hardware and the IEC set (`../01-schematic-iec/`). PNG, PDF and anything in the root codebase can be stale and were not used.
Terminal-block numbers are left out on purpose. This is just what goes where.

Net names used below: `1P24` / `1N24` = 24 V / 0 V after MCB-04 (1-pole: only + is switched). `1N48` = 48 V return.
Driver 01 = LEFT motor, Driver 02 = RIGHT motor.

---

## 1. Motor drivers (2 × BLVD-KRD, Oriental Motor)

Sheets 02, 04, 06, 07.

### Power (driver power connector, cable LC03D06A)

| Driver | 48 V + | 48 V − | Earth |
|---|---|---|---|
| Driver 01 (left) | 2P48 (battery → MCB-01 → MCB-02, ABB S201-C13, 1P 13 A) | 1N48 | PE |
| Driver 02 (right) | 3P48 (battery → MCB-01 → MCB-03, ABB S201-C13, 1P 13 A) | 1N48 | PE |

- All motor and brake power comes in on the LC03D06A cables, through the driver.
- Motors: BLMR6400SKM-GFV-B with gearhead GFS6G30FR (1:30).
- The motor itself (UVW and encoder) connects with the Oriental Motor cable CCM020B1AAF (2 m). The 28-pin connector below is for control only.

### 28-pin control connector: wired pins

Same on both drivers. Only the pins below are connected.

| Pin | Signal | Goes to | What it is |
|---|---|---|---|
| 5 | CAN_L | CAN L bus (sheet 06) | Drive command and feedback from the IPC |
| 6 | CAN_H | CAN H bus (sheet 06) | same |
| 7 | CAN_GND | CAN GND bus (sheet 06) | same |
| 20 | NET-VIN | 1P24 | 24 V supply for the driver's control and network side |
| 21 | NET-GND | 1N24 | its 0 V |
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

- The USB-CAN interface is a **CANable V2.0S** on the **IPC USB port** (NEXCOM NEU-X102-N97). It feeds a single CAN H / L / GND bus, 125 kbit/s, CANopen.
- The 120 Ω termination is **built into the CANable V2.0S**. There is no separate terminating resistor at that end.
- On the bus: Driver 01 (node 1), Driver 02 (node 2), the **MLSE line sensor** (node 10) and the **battery BMS**.
- The line sensor **SICK MLSE-0200A2NQ0** has **no internal terminator**, so the far bus end is open «confirm».
- Line sensor cable: SICK YF2A14-020UB3XLEAX (M12 4-pin female → open end). It carries power and CAN:

| M12 pin | Core | Signal | Goes to |
|---|---|---|---|
| 1 | brown | L+ | 1P24 (sheet 04) |
| 2 | white | CAN-H | CAN H bus (sheet 06) |
| 3 | blue | GND | 1N24 (sheet 04) |
| 4 | black | CAN-L | CAN L bus (sheet 06) |

---

## 2. Safety PLC (SICK Flexi Soft)

Sheets 03, 07, 08, 10.

- **FX3-CPU0** main module, with system plug **FX3-MPL000001**: only 24 V power (A1 = 1P24, A2 = 1N24, in parallel with the XTIO). No field IO is drawn on it.
- **FX3-XTIO84002**: all the field safety IO, below.
- **FX3-MOC0** drive monitor: supplied over FLEXBUS+ (no wiring). It reads the two safety encoders (section 3).

### Supply

| Terminal | Goes to |
|---|---|
| A1 | 1P24 |
| A2 | 1N24 |

### Inputs

| Terminal | Goes to | What is connected |
|---|---|---|
| X1 → I1 | E-stop push-button contact 1 (NC) | **Emergency stop**, red, turn to release, 2 NC. Test output X1 goes through the first NC pole and returns on I1. |
| X2 → I2 | E-stop push-button contact 2 (NC) | Same E-stop, second pole. X2 goes through it and returns on I2. |
| I3 | Driver 01 EDM− (pin 14) | Left motor driver feedback |
| I4 | Driver 02 EDM− (pin 14) | Right motor driver feedback |
| I5 | SAFETY LIDAR 01 **OSSD1.A** (M12 pin 2) | Lidar safety output, via SICK cable YF2A18-050UA5XLEAX |
| I6 | SAFETY LIDAR 01 **OSSD1.B** (M12 pin 4) | same |
| I7 | **MANUAL/AUTO selector switch**, pole 1 (NO) | Fed from 1P24. The sheet labels this line "MANUAL". |
| I8 | **RESET push-button** (yellow), pole 1 (NO) | Fed from 1P24 |

The selector and the reset button each have two NO poles. Pole 1 goes to the safety PLC (above). Pole 2 goes to the digital IO module (section 4), wired to 1N24 on the other side.

### Outputs

| Terminal | Goes to | What it does |
|---|---|---|
| Q1 | HWTO1+ on Driver 01 **and** Driver 02 | Safe torque-off channel 1 |
| Q2 | HWTO2+ on Driver 01 **and** Driver 02 | Safe torque-off channel 2 |
| Q3 | not connected | spare |
| Q4 | not connected | spare |

Q1 / Q2 also switch off on overspeed in AUTO (safely-limited speed, FX3-MOC0, section 3).

### Safety lidars (sheet 03)

- **SAFETY LIDAR 01** (front): SICK nanoScan3 Core I/O **NANS3-AAAZ30AN1**, system plug **NANSX-AAABAEZZ1**.
  - Power and OSSD: M12 8-pin, cable SICK YF2A18-050UA5XLEAX (open end). Pin 1 = +24 V (1P24), pin 3 = 0 V (1N24), pin 2 = OSSD1.A → I5, pin 4 = OSSD1.B → I6.
  - Ethernet (scanner data only, not safety): cable SICK YM2D24-020PN1MRJA4 (M12 D-coded → RJ45) to the IPC port **enp1s0**.
- **SAFETY LIDAR 02** (rear): **NOT FITTED** in this revision. Its 24 V supply on sheet 03 is drawn dashed. No OSSD inputs are reserved for it.

---

## 3. Drive monitor FX3-MOC0 and safety encoders (sheet 10)

- Two **SICK DFS60S-BAOL01024** safety encoders (sin/cos, 1024 periods), one per wheel shaft. ENC1 = left wheel, ENC2 = right wheel «confirm».
- Encoder supply is 24 V from the MOC0.
- Each encoder cable has an M12 8-pin plug. The **SICK FX3-MOC Y-CABLE 2116199** joins both to the MOC0's Micro D-sub 15. **All 8 encoder wires go through.**
- Functions: safely-limited speed in AUTO (overspeed → STO via XTIO Q1 / Q2) and standstill monitoring. Limits: Flexi Soft configuration «confirm».
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

## 4. Digital IO module (CKDZ-IoT CK-TP5162, 16 DI / 16 DO, Ethernet)

Sheets 03, 08, 09. Field wiring is AWG22 blue, except the Ethernet and pendant cables. The terminal layout of the CK-TP5162 is not documented here; sheet 09 shows it as a simplified block.

The audio horn (sheet 03, PATLITE BK-24AE-K) is powered from 1P24 / 1N24. Its COM is jumpered to 1N24 at the horn; a sound plays while its sound input is connected to COM, which DO0 / DO1 do.

### Supply and Ethernet

| Port | Goes to |
|---|---|
| 24V | 1P24 |
| 0V | 1N24 |
| PE | not connected |
| Ethernet IN | **IPC** port **enp2s0** |
| Ethernet OUT | **RFID reader** (Chafon CF821, 12 V) |

### Digital inputs

COM0 is tied to 1P24. Each input DI00–DI07 is a normally-open contact that pulls the input to 1N24 when pressed.

| Input | Device | Notes |
|---|---|---|
| DI00 | **PB START** (green) | Other side to 1N24 |
| DI01 | **PB RESET** (yellow), pole 2 (NO) | Same push-button as safety PLC I8 |
| DI02 | **MANUAL/AUTO selector**, pole 2 (NO) | Same switch as safety PLC I7 |
| DI03 | Pendant **FORWARD** (NO) | Pendant = 4 × 1NO direction buttons, all sharing one 1N24 return |
| DI04 | Pendant **REVERSE** (NO) | |
| DI05 | Pendant **LEFT** (NO) | |
| DI06 | Pendant **RIGHT** (NO) | |
| DI07 | not used | |
| DI08 | **MANUAL ARM**, on the **pendant** | Black mushroom push-button, latching, turn to release, 1 NC (contact 11-12). **Not an emergency stop.** 1P24 → 11-12 → DI08 (COM1 group, COM1 = 1N24). Released (contact closed) = 24 V on DI08 = drives on in MANUAL; pressed = drives off. Terminal-block numbers for its two cores: «TB?». The software reads it as Manual Arm (`profiles/agv-01.json` di_names[8]). |
| DI09–DI0F | not used | |
| COM0 | 1P24 | Common for DI00–DI07 |
| COM1 | 1N24 | Common for DI08–DI0F |

Pendant cable: Delta 8 × 0.5 mm², 7 cores used = common (1N24) + 4 direction buttons (DI03–DI06) + 2 for MANUAL ARM (1P24 and DI08).

### Digital outputs

Each output closes to the common C of its pair.

| Output | Status |
|---|---|
| DO0 | **Audio horn 01, sound 1 (movement)** (closes 1N24 onto the horn's sound 1 input) |
| DO1 | **Audio horn 01, sound 2 (alarm)** (closes 1N24 onto the horn's sound 2 input) |
| DO2–DO7 | **Spare, nothing connected.** Only the commons are wired (below). |
| DO8–DOF | Not wired. The software also switches DO8 with motion; nothing is connected to it. |

| Output common | Goes to |
|---|---|
| C of DO0 / DO1 | 1N24 |
| C of DO2 / DO3 | 1P24 |
| C of DO4 / DO5 | 1N24 |
| C of DO6 / DO7 | 1N24 |

---

## Things the sheets do not settle

- **Selector polarity.** Sheet 08 labels the I7 line "MANUAL". The IEC set (page 40) takes the contacts as closed in MANUAL; the JIS sheet does not show it.
- **MANUAL ARM terminal blocks.** Its two cores in the pendant cable have no TB numbers yet («TB?» on sheet 09).
- **CAN far bus end.** Open, because the MLSE has no terminator «confirm».
- **Encoder sides.** ENC1 = left, ENC2 = right «confirm».
- **Speed and standstill limits.** In the Flexi Soft configuration «confirm».
- **CK-TP5162 terminal layout.** Not documented; sheet 09 draws a simplified block.
