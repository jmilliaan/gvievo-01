# Designation map: JIS names → IEC 81346 tags

One row per component, taken from the current sheets `../01-schematic/proj01-sheet-00..09.html` and `../01-schematic/io-mapping.md`. This table feeds three things:
- the IEC sheets;
- the component list;
- the `[tag]` placeholders in the operation manual.

**How to read the columns:**
- **Class codes:** IEC 81346-2:2019. **[verify]** = the code is from a secondary source and must be checked against the purchased standard.
- **Location:** a proposal; confirm it physically (see `conventions.md` section 4).
- **Old ref:** where the device is drawn now, as JIS sheet + line. "SH.08" = sheet 08.
- **Safety:** Y = part of a safety function (SF IDs from `conventions.md` section 8).

## Power

| New tag | Old name | Device | Location | Old ref | Safety | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `+BT-GB1` | BATTERY | Battery 48 V with BMS (BMS on CAN) | +BT | 0102, 0618 | N | Capacity unknown |
| `+EB-QA1` | MCB-01 | Circuit breaker 2P 32 A, battery main / supply disconnecting device | +EB | 0102 | N | Decided 2026-10-30: the supply disconnecting device (QA). It is the main switch that is locked off in the operation manual 15.1. Lockable handle `[confirm]` |
| `+EB-FC1` | MCB-02 | Circuit breaker 1P 13 A ABB S201-C13, feeder left motor driver (2P48) | +EB | 0105 | N | |
| `+EB-FC2` | MCB-03 | Circuit breaker 1P 13 A ABB S201-C13, feeder right motor driver (3P48) | +EB | 0107 | N | |
| `+EB-TA3` | BUCK01 | DC/DC converter 48 → 24 V, 6.25 A (150 W) | +EB | 0110 | N | Feeds the safety controller, so its failure behaviour matters to the risk assessment |
| `+EB-FC3` | MCB-04 | Circuit breaker 1P 6 A ABB S201-C6, 24 V bus | +EB | 0302 | N | |
| `+EB-TA4` | BUCK02 | DC/DC converter 48 → 12 V, Mean Well SD-100C-12, 100 W | +EB | 0114 | N | |
| `+EB-FC4` | MCB-05 | Circuit breaker 1P 10 A ABB S201-C10, 12 V bus | +EB | 0502 | N | |

## Drives

| New tag | Old name | Device | Location | Old ref | Safety | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `+EB-TA1` | DRIVER 01 | Motor driver BLVD-KRD, left | +EB | 0202, SH.07 | Y (STO: SF1, SF2) | **[verify]** TA (converter) vs TB (inverter) |
| `+EB-TA2` | DRIVER 02 | Motor driver BLVD-KRD, right | +EB | 0207, SH.07 | Y (STO: SF1, SF2) | as above |
| `+VH-MA1` | LEFT MOTOR | Motor BLMR6400SKM-GFV-B, 400 W, gearhead 1:30, holding brake | +VH | SH.02 | **[decide]** | The brake holds the vehicle after STO. Whether it counts in the stop function is a risk-assessment decision |
| `+VH-MA2` | RIGHT MOTOR | as above, right | +VH | SH.02 | **[decide]** | |

## Safety

| New tag | Old name | Device | Location | Old ref | Safety | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `+EB-KE1` | SAFETY PLC (CPU MODULE) | Safety controller main module SICK Flexi Soft FX3-CPU0 | +EB | 0313 | Y (all SF) | **[verify]** KE (2019) vs KF (2009) |
| `+EB-KE2` | SAFETY PLC (XTIO MODULE) | Safety I/O module SICK FX3-XTIO84002 | +EB | 0311, SH.08 | Y (all SF) | Module variant `[confirm]` |
| `+FR-SJ1` | EMERGENCY STOP PB | E-stop push-button, turn to release, 2 NC (11-12, 21-22) | +FR | 0802 | Y (SF1) | Positive-opening symbol required |
| `+VH-BG1` | SAFETY LIDAR 01 | Safety laser scanner SICK nanoScan3, front | +VH | 0305 | Y (SF2) | OSSD to `-KE2:I5/I6` |
| (`+VH-BG2`) | SAFETY LIDAR 02 | Safety laser scanner, rear | — | 0308 | — | **Not fitted in this revision** (owner, 2026-10-30). Tag reserved. The old sheet 03 still shows its 24 V supply |
| `+FR-SJ3` | PB RESET | Push-button RESET, yellow, 2 NO (13-14 → `-KE2:I8`; 23-24 → `-KE4:DI01`) | +FR | 0813 | Y (SF5) | |
| `+FR-SJ4` | SS MANUAL/AUTO | Selector switch, 2 positions, 2 NO (13-14 → `-KE2:I7`; 23-24 → `-KE4:DI02`) | +FR | 0812 | Y (SF4) | **[verify]** SJ vs SG. Polarity open: which position closes the contacts |

## Control

| New tag | Old name | Device | Location | Old ref | Safety | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `+EB-KE3` | IPC | Vehicle controller, industrial PC | +EB | 0505 | N | Model unknown |
| `+EB-KE4` | DIGITAL IO | I/O module CKDZ-IoT CK-TP5162, 16 DI / 16 DO, Ethernet | +EB | 0318, SH.09 | N | |
| `+EB-KE5` | — | Flexi Soft drive monitor FX3-MOC0, 2 encoder inputs, supply via FLEXBUS+ | +EB | — | Y (SF6, SF7) | Added 2026-11-09. Cables `-WG11`, `-WG12` (encoder cables, M12 plug fitted), `-WG13` (FX3-MOC Y-CABLE 2116199) |
| `+EB-TF1` | CAN-USB ADAPTER | USB-to-CAN interface, on the IPC USB port | +EB | SH.06 | N | **[verify]** class (signal converter) |
| `+FR-SJ2` | PB START | Push-button START, NO → `-KE4:DI00` | +FR | SH.09 | N | Colour `[confirm]` |
| `+PD-SJ5` | MANUAL ARM SW | Push-button MANUAL ARM on the pendant: mushroom, black, latching, turn to release, 1 NC → `-KE4:DI08` | +PD | SH.09 | N | Owner, 2026-11-09: it is the turn-to-release button on the pendant. Changed from a red emergency-stop look to black so it is not taken for an emergency stop. Pressed = DI08 off = drives off in MANUAL |
| `+PD-SJ6` | PENDANT FORWARD | Pendant button, NO → `-KE4:DI03` | +PD | SH.09 | N | |
| `+PD-SJ7` | PENDANT REVERSE | Pendant button, NO → `-KE4:DI04` | +PD | SH.09 | N | |
| `+PD-SJ8` | PENDANT LEFT | Pendant button, NO → `-KE4:DI05` | +PD | SH.09 | N | |
| `+PD-SJ9` | PENDANT RIGHT | Pendant button, NO → `-KE4:DI06` | +PD | SH.09 | N | Common return on one wire (old TB64) |
| `+VH-PJ1` | AUDIO HORN 01 | Audio horn PATLITE. Sound 1 (DO0) = movement, sound 2 (DO1) = alarm | +VH **[confirm]** | 0315 | N | Software-driven warning device |
| `+FR-PH1` | DISPLAY | Display, 24 V barrel jack | +FR **[confirm]** | 0402 | N | |

## Sensors

| New tag | Old name | Device | Location | Old ref | Safety | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `+VH-BG3` | LINE SENSOR 01 | Magnetic line sensor SICK MLSE, on CAN | +VH | 0405, SH.06 | N | |
| `+VH-BG4` | RFID READER | RFID reader, 12 V, Ethernet | +VH **[confirm]** | 0508 | N | **[verify]** class. Navigation feature, not safety |
| `+VH-BG5` | — | Safety encoder, left wheel shaft, SICK DFS60S-BAOL01024 (sin/cos, 1 024 periods) → `-KE5` ENC1 | +VH | — | Y (SF6, SF7) | Added 2026-11-09 (owner: implemented). ENC1 = left **[confirm]** |
| `+VH-BG6` | — | Safety encoder, right wheel shaft, SICK DFS60S-BAOL01024 → `-KE5` ENC2 | +VH | — | Y (SF6, SF7) | Added 2026-11-09 |

## Other

| New tag | Old name | Device | Location | Old ref | Safety | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `+EB-GQ1` | FAN 01 | Fan NMB-MAT, 24 V | +EB | 0408 | N | **[verify]** GQ for fans |
| `+EB-GQ2` | FAN 02 | Fan NMB-MAT, 24 V | +EB | SH.04 | N | |
| `+EB-GQ3` | FAN 03 | Fan NMB-MAT, 24 V | +EB | SH.04 | N | |
| — | TB01 – TB72 | Not drawn (owner decision, 2026-10-31): wires are identified by their wire markers | +EB | all | — | See `conventions.md` section 4 |
| `+EB-XE1` | PE | PE / chassis earth point | +EB | — | N | Drawn on page 21; its physical position is not documented (owner decision, 2026-10-31) |

## Cables (to be numbered from the cable list)

| New tag | Cable now | Between |
| --- | --- | --- |
| `-WD1`… | NYAF 4 / 2.5 / 1.5 mm² red | Battery, breakers, drivers, converters |
| `-WD…` | Oriental Motor LC03D06A | Driver power |
| `-WD…` | Oriental Motor CCM010B1AAF | Motor power / encoder |
| `-WG…` | Belden 9841 | CAN bus |
| `-WG…` | SICK connection cables | Scanners |
| `-WG…` | SICK MLSE power & comm cable | Line sensor |
| `-WG…` | Ethernet | IPC → I/O module → RFID reader |

**[verify]** whether the fieldbus and Ethernet cables take WG or WF.

## Not tagged here

- Mechanical parts: chassis, wheels, castors, hitch.
- The pendant housing, as a `+PD` location.
- Labels and the cable markers themselves.
