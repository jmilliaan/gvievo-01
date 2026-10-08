# RFID tag table — tracked (LINE) product

Status 2026-10-08. Source of truth: `missions/<name>.json` (validated by `agv_core/mission.py`,
schema v2.1) and the `autopilot` block of `profiles/agv-01.json`. This page describes them;
if they disagree, the files win.

One tag id has one meaning per mission. Tags only do three independent things: **stop**,
**speed** (NORMAL / HIGH zone) and **branch** (plus the U-turn).

## Site tags (mission `line-a`)

| Tag | Action | Meaning | Stops / acts when | Ignore after read | Restart |
|---|---|---|---|---|---|
| `0010` | stop, role `home` | Home: decelerate to a stop over 0.5 m | every pass; ends the run (DONE) | 2 s | new job, then panel Start at Home |
| `0020` | stop, role `always` | Trolley release: stop over 0.5 m | every pass | 2 s | panel Start (+0.6 s start delay) |
| `0180` | `u_turn`, cw | U-turn CW: slow to 0.1 m/s within 0.3 m, stop the moment the tape is gone (creep reached or not), pivot CW until the tape is back and centred | every pass, **also with no mission**; its own tag is ignored once on the way back | 2 s | continues by itself |
| `0190` | `u_turn`, ccw | U-turn CCW: as `0180`, pivoting CCW | as `0180` | 2 s | continues by itself |
| `0110` | stop, role `destination` | MRU1: stop over 0.5 m | only when MRU1 is the job's destination, once | 4 s | panel Start (+0.6 s start delay) |
| `0120` | stop, role `destination` | MRU2 | as MRU1 | 4 s | as MRU1 |
| `0130` | stop, role `destination` | MRU3 | as MRU1 | 4 s | as MRU1 |
| `0140` | stop, role `destination` | MRU4 | as MRU1 | 4 s | as MRU1 |

`branch_default` for `line-a` (and `empty`) is `left` (2026-10-08); no branch-latch tags yet.

## Speed zone tags (in `line-a` since 2026-10-08: shortest straight 10 m, HIGH budget 7.65 m)

| Tag | Action | Placement | Effect |
|---|---|---|---|
| `0060` | `zone_outer` | 0.5 m from the tangent point / edge of a NORMAL area, on the NORMAL side | arms the zone; HIGH only if `0040` follows within 1.5 m |
| `0040` | `zone_inner` | 0.5 m further into the straight | after `0060`: HIGH for the budget. Read while HIGH: late exit at 0.5 m/s² |

- Same ids at every straight end; the read order gives the direction (60→40 enters, 40→60 leaves).
- HIGH budget = `shortest_straight_m` (inner to inner) − brake 1.35 m − margin 1.0 m, counted in wheel travel.
- `0060` read while HIGH (inner missed): urgent drop to NORMAL.
- `ignore_s` ≤ 2 s (line-a: 2 s; the same id is read twice through one corner, ≥ 1.8 m apart).
- Each id is a cluster of 4 tags in a 10 cm square. Overlapping read zones are tolerated:
  a zone id seen again within 1.5 m of travel is the same pass, and 60 within 1.5 m after
  40 means leaving a zone (never arms). Entry needs the first 40 read within 1.5 m of the
  first 60 read (0.5 m spacing + 1.0 m leniency: first reads measured 0.65-0.99 m apart
  on 0.5 m pairs, 2026-10-08).
- Drawing: `documentation/layout-reference/corner-tag-placement.html`. Detail: `manuals/tracked-speed-plan-1-no-slam.md`.

## Speeds

| | Speed | Gains |
|---|---|---|
| NORMAL (default, corners, busy areas) | 0.50 m/s (1592 r/min) | K 11.3 / Kd 0.95 |
| HIGH (inside a zone only) | 0.85 m/s (+70 %) | K 11.3 / Kd 0.94 |

- A run from Home always starts NORMAL.
- A station stop (`always`, `destination`) departs at the speed it arrived at, with the budget
  left; any other hold, a zone tag, missing encoder counts or Reset in between makes it NORMAL.
- U-turn, any hold, a junction slow zone or a curve-guard trip drops HIGH.

## Rules that apply to every tag

- **Start**: with a mission, the AGV must be at Home (last tag `0010`, ≤ 0.8 m travelled since)
  and a destination chosen when the mission has destinations; then the physical panel Start
  under AUTO. No web page starts the vehicle.
- **No mission** (plain line following, `missions/empty.json`): only the U-turn tags `0180`/`0190`
  act; every other tag is ignored. NORMAL speed, no Home check, no RFID link needed to start
  (a missed U-turn tag ends at the tape end, where the line-loss stop halts the vehicle).
- **U-turn end**: the encoders only gate the pivot (tape accepted from 150°, fault at 225°, or
  past twice the nominal spin time); it ends when the tape is back under the sensor and
  centred within ±10 mm for 1 s. With the axle on the tape line that is 180° by geometry.
- **Departure**: the stop being left is not acted on again, however slowly the AGV pulls away.
- **Held / stopped**: reads cannot start a stop, U-turn or zone entry (branch exits still count).
- **Destination missed**: if the U-turn tag comes first, the destination is reported missed and
  not served on the return leg.
- **RFID link lost while driving** (mission with tags): hold `rfid`, panel Start to resume.
