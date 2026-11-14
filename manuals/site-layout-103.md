# Site layout: 103 Tyre Building (tape network, stations, trip flow)

Status: agreed with the operator 2026-10-17. **Scope now: AGV-01 only.** AGV-02 is recorded for
completeness; two-AGV traffic (zone lock, priority) is deferred until AGV-02 starts.

The current `missions/line-a.json` and branch config do NOT implement this layout. RFID trials
gave poor results, so the stops and junction orders here are to come from tape-graph localization,
not from RFID.

Localization plan: `manuals/tracked-plan-3-tape-localization.md`; procedures: `manuals/tape-localization-runbook.md`.

Sources: the simplified site plan (operator image, 2026-10-17, not in the repo; partly outdated)
and the HOME-area projection `documentation/layout-reference/homepos-area-projection/layout-projection.svg`.
Where they disagree, the projection wins. The operator's correction of the same day removes the
site plan's outer trunk: there is **one trunk**, entering the HOME complex at merge L (from the
north) and merge R (from the south).

Compass: site-plan north = the MRU line at the top. The projection is rotated: its up = east,
left = north, right = south, down = west. Projection coordinates below are mm, as printed on it.

## 0. Decisions

| # | Decision | Source |
|---|---|---|
| D1 | Two AGVs, fixed halves split along the middle line ("103 TYRE BUILDING"). No AGV serves the other's machines | operator |
| D2 | AGV-01: BTU9–24 and MRU1–4 (20 machines), the north side. AGV-02: BTU1–8, STU1–10 (18 machines). Confirmed by the owner 2026-11-14. Row 3: BTU1–6 face STU1–6 (same numbering), BTU7 and BTU8 face nothing; STU7–10 are served like MRU (release, take back, pairs allowed) | operator; owner 2026-11-14 |
| D3 | A trip serves **at most 2 machines, both from one group**. AGV-01 groups: **MRU** (MRU1–4) and **BTU** (BTU9–24). Never mixed: the track and flow are too complicated | operator |
| D4 | ~~The AGV waits at HOME until two machines of one group have called. Cycle time and capacity are out of scope for now~~ **Replaced 2026-11-05:** one machine per trip (`trip_calls` 1). No waiting for a second call. No batching | operator |
| D5 | ~~Calls are entered on the AGV's own display (or the web page from a laptop). No call buttons, no central system~~ **Replaced 2026-11-05, with `station.enabled` only:** MRU calls come from buttons on the machines, through the station PC. BTU calls stay on the AGV's display. Run → Calls stays | operator |
| D6 | Facing machines share one stop point; the AGV stops in the same place for both | operator |
| D7 | **BTU:** at a stop the AGV waits; the operator swaps the trolley; panel Start continues | operator |
| D8 | **MRU:** westbound, the AGV stops at each called machine and the trolley is **released**. It drives on empty to the end of the MRU line, U-turns, and on the eastbound pass stops again at the same machines to **take the trolley back** | operator |
| D9 | **The AGV cannot U-turn with a payload, at either U-turn.** The MRU-end U-turn is a pivot at the tape end (as `line-a`'s `u_turn`), so every release must be done before it. The HOME U-turn R717 is driven empty: the trolley is attached after it (D11) | operator |
| D10 | ~~There is no payload detection. A rear lidar may later detect the trolley; ignored for now~~ **Replaced 2026-11-05, as an assumption, with `station.enabled` only:** a rear lidar will detect the trolley and carry the rear safety field. Not fitted yet. Trolley detection is not personnel protection. With it off, the confirmations stand | operator |
| D11 | AGV-01's **home position is HOME-N2 in the south bay** (right at J-SPLIT, since 2026-11-06; it was the north bay), where it parks **empty**. The **attach point** is on the departure lane after the U-turn. The operator's mark-up puts it at ≈ projection (2474, 3250–5190), from about 0.8 m to 2.8 m before J-N; the exact stop is taught on the floor. **Trolleys are released at each AGV's own home position.** Owner 2026-11-14: AGV-01 stays at HOME-N2 (right bay), AGV-02 parks at HOME-N (left bay) | operator, 2026-10-17 mark-ups |
| D14 | **Leaving home needs a physical Start.** A call (or a formed trip) on the display never moves the vehicle (safety invariant: no web page starts the vehicle; autonomous motion only under AUTO + a fresh panel Start). When a trip forms, the HMI shows it; the operator presses Start at the bay, and the AGV drives empty through the U-turn to the attach point. **Replaced 2026-11-05 for one case:** with `station.enabled`, an accepted station order leaves HOME by itself, only from HOME, only in AUTO, once, through the 2 s horn, and with no trolley and the rear field clear. Everything else still needs a physical Start | safety invariants (CLAUDE.md); owner 2026-11-05 |
| D12 | ~~Tape is laid only as far as MRU~~ **All tape is laid (2026-11-07).** Row 2, the left vertical and the middle line are down, but not yet taught: no graph has them (section 4) | operator |
| D13 | AGV-01 only for now: no collision or priority logic. Topics and profile are per AGV (`manuals/station-call-plan.md` section 20), so a second AGV is not closed off | operator |
| D15 | **Positions are marked from the moving AGV** (Guide page M key, ±10 cm at 0.3–0.4 m/s) and given roles later: stop + panel Start (machines, ATT), end-of-cycle stop (HOME-N), mid-line U-turn point, high-speed area. Branch approach points are NOT marked: the order for the trip's destination is armed from the taught junction positions | operator, 2026-10-24 |
| D16 | **MRU mid-line U-turn:** after the LAST release of the trip (the farthest called machine), the empty AGV pivots at that machine's own **U-turn mark**, a few metres past its outbound stop and clear of the released trolley, instead of driving to the tape end. The tape-end U-turn (U-MRU, code 3) stays as the fallback. Supersedes D8's "drives on to the end" | operator, 2026-10-24 |
| D17 | **MRU stops are directional and separate:** OUTBOUND (home → machine, westbound) = trolley released; INBOUND (machine → home, eastbound, after the U-turn) = trolley attached, at a **different spot**. Both are marked | operator, 2026-10-24 |
| D18 | **Trip size is a setting:** 1 or 2 MRU machines per trip (`trip_calls` in `missions/site-103.json`), ~~2 for now~~ 1 since 2026-11-05 | operator, 2026-10-24 |
| D19 | **High-speed zones are areas, not latched markers:** a range on the taught path (from one mark to another), checked against the AGV's position; no set/reset strips | operator, 2026-10-24 |

## 1. Tape network (AGV-01's half and HOME)

| Segment | Description |
|---|---|
| **HOME complex** | Per the projection. Arrival stem → bay split → two parallel bays (~1750 mm drawn; 1.32 m apart measured on the floor, 2026-11-06; home positions) → bay merge → U-turn R717 → departure lane heading west (attach point, then three exits: R2434 north, R1570 south, straight on to the middle line). Two crossings: X1, X2 |
| **Trunk** | One tape (the site plan's outer trunk does not exist). North of HOME: bidirectional, AGV-01 only, from merge L to the MRU line's NE corner; row 2 joins it from the west at J-ML. South of HOME: from merge R, AGV-02 (deferred) |
| **Middle line** | From the departure lane west to the left vertical. Westbound only |
| **Left vertical** | x≈45 on the site plan. From the middle line, north leads to row 2 (AGV-01) and south to row 3 (AGV-02) |
| **Row 2** | BTU17–24 above / BTU9–16 below. Driven eastbound, from the left vertical, then curving south to the trunk at J-ML |
| **MRU line** | MRU1–4 (single-sided, machines south of the line, owner 2026-11-07). From the trunk's NE corner west to a tape end, where the empty AGV pivots and comes back east on the same tape |

## 2. Stop positions (AGV-01: 16 at machines, plus home and attach)

Listed in the order the AGV meets them on its circuit. Each is a separate taught position: the
eastbound MRU stops face the other way and need not coincide with the westbound ones.

| Position | Machines | Circuit | Pass | Operator action |
|---|---|---|---|---|
| HOME-N2 | – | both | right bay beside the old HOME-N (2026-11-06, operator), end of the trip | release the trolleys; park (trip ends) |
| ATT | – | both | departure lane, after the U-turn | attach the trolleys, Start |
| R2-1 | BTU24 / BTU16 | BTU | row 2 eastbound | swap |
| R2-2 | BTU23 / BTU15 | BTU | | swap |
| R2-3 | BTU22 / BTU14 | BTU | | swap |
| R2-4 | BTU21 / BTU13 | BTU | | swap |
| R2-5 | BTU20 / BTU12 | BTU | | swap |
| R2-6 | BTU19 / BTU11 | BTU | | swap |
| R2-7 | BTU18 / BTU10 | BTU | | swap |
| R2-8 | BTU17 / BTU9 | BTU | | swap |
| MW-1 … MW-4 | MRU1 … MRU4 | MRU | MRU line westbound | release |
| ME-4 … ME-1 | MRU4 … MRU1 | MRU | MRU line eastbound | take back |

## 3. Trip flow (AGV-01)

(With `station.enabled`, an MRU call comes from the station instead, and step 3's Start at the bay is replaced by the accepted order: `manuals/station-call-plan.md` section 3. Steps 4 to 8 are the same, with the rear lidar checking each Start.)

1. The AGV is parked empty at HOME-N2 in the south (right) bay. Operators enter calls on the display.
2. A trip forms when **`trip_calls` calls (one since 2026-11-05) of the same group** are pending. Calls of the other group keep
   waiting. A duplicate call for a machine already pending is refused.
3. The HMI shows the formed trip; the operator presses panel Start at the bay (D14). The AGV drives
   **empty** out of the bay, through the bay merge and the U-turn R717, and stops at the attach point.
4. The operator attaches the trolleys and presses panel Start.
5. The AGV drives its group's circuit and serves the calls **in circuit order**, not call order.
6. **BTU trip:** at each called point (R2-1 first, R2-8 last) the operator swaps the trolley, then
   presses panel Start. If both calls are at one shared point (e.g. BTU24 and BTU16), the AGV makes
   **one stop** and both swaps happen there.
7. **MRU trip:**
   - **Westbound:** at each called MW stop the trolley is released, then panel Start.
   - **At the tape end:** the empty AGV pivots.
   - **Eastbound:** it stops at the same machines, in reverse order, to take the trolleys back,
     then panel Start at each.
8. After the last stop the AGV finishes the circuit to HOME-N2 without stopping. The
   operator releases the trolleys there, so the AGV is empty before its next trip's U-turn.

## 4. Circuits and junction orders (AGV-01)

Junctions in travel order. Sides are as seen in the direction of travel. "Merge" means another
tape joins and there is no choice to make.

| Id | Where | Kind |
|---|---|---|
| J-BMERGE | bay merge, projection (1040, 8450) | merge |
| J-N | departure lane × R2434, (2474, 2434) | diverge: R2434 on the right (to the north trunk) |
| J-S | departure lane × R1570, (2474, 1570) | diverge: R1570 on the left (to AGV-02's south trunk) |
| X1 | R2624 × R2434, (1995, 984) | crossing, non-90° |
| X2 | R2624 × departure lane, (2474, 522) | crossing, non-90° |
| J-ML | merge L, (40, 0), map (-10.56, 12.5) | where row 2 joins the trunk, from the west (owner, 2026-11-07). Northbound: the row 2 tape opens on the left. Southbound: it closes in from the right |
| J-STEM | R2624 joins the stem, (1420, 2624) | merge from the right |
| J-SMERGE | a tape joins from the right, map (-10.59, -0.31); taught as J-SPLIT until 2026-11-06 | merge |
| J-SPLIT | bay split, about 5 m after J-SMERGE, map (-5.55, -0.39) | diverge: AGV-01 goes **right** to HOME-N2 since 2026-11-06 (left was the old HOME-N) |
| J-LV | middle line × left vertical, map (-75.78, 3.13), 64 m past X2 | a curve (owner, 2026-11-07): north on the right, south on the left. Mission shape stays `T`, approach stem: no straight on |
| U-MRU | MRU line west end | tape end: pivot U-turn, empty only |

**C-BTU:** bay → J-BMERGE → U-turn R717 (empty) → ATT → J-N **straight, holding LEFT** → J-S **straight, holding RIGHT** → X2 **straight** →
middle line west → J-LV **right** → row 2 east (R2-1…R2-8) → curve south →
J-ML **right** (joins the trunk) → J-STEM **left** → J-SMERGE → J-SPLIT **right** → HOME-N2 (south bay).

**C-MRU:** bay → J-BMERGE → U-turn R717 (empty) → ATT → J-N **right** → X1 **straight** → J-ML (straight) → trunk
north → MRU line west (MW stops) → U-MRU **pivot** → MRU line east (ME stops)
→ trunk south → J-ML **left** → J-STEM **left** → J-SMERGE → J-SPLIT **right** → HOME-N2 (south bay).
Every MRU trip releases and pivots at one place (2026-11-11, graph g9): the AGV stops at `MW-n`, the operator releases the trolley and presses Start, and the AGV pivots where it stands at `UT-MRUn`, 0.02 m further on (a point at its release is refused), then drives to `ME-n` to attach. MRU1-3: at the midpoint of the old release and U-turn point. MRU4: 0.3 m past the old tape end; the tape was extended 1 m west (g8), so the AGV stops 0.7 m short of the new end and never reaches it. `ME-1`..`ME-3` unchanged; `ME-4` 1 m east of the old tape end. No trip uses U-MRU any more; it stays the circuit's end.

All tape is laid (D12). Two C-BTU laps ran on 2026-11-07 (194 m) and graph g7 holds the route (`documentation/layout-reference/tape-graph-g4/g7-overview.png`), added with `amr_line.tape_merge`,
not Build (`manuals/tape-localization-runbook.md` section 3.2B). `J-LV` is `laid: true`; C-MRU does not pass it.

**How row 2 joins (owner, 2026-11-07):** row 2 curves south and joins the trunk from the west at `J-ML`. It has no junction
of its own: the mission's `J-R2E` came out on 2026-11-07, and C-BTU arrives at `J-ML` on `order: merge` with `steer: right`,
as on both laps, so the AGV holds its own tape while the trunk tape closes in from its left. The sensor agrees on all 5 served MRU trips checked: northbound a second tape opens on the left at
`J-ML`, from about 10 mm to 110 mm in about 0.23 m; southbound it closes in from the right. Between `J-ML` and the MRU
line it reads one track, both ways. The taught `X1→J-ML` and `J-ML→J-STEM` legs stay within 4 cm of each other for the
first 7.5 m south of `J-ML`, so R2434 and R1380 do not visibly split at `J-ML` as the site plan draws them. An unnamed
crossing is also logged on R2434 about 1 m after `J-N`, map (-11.3, -0.6).

Consequences:

- **Only one branch decision depends on the job: J-N**, and it depends on the group, not the
  machine (MRU → right, BTU → straight). Every other order is fixed for AGV-01.
- **A single standing default cannot drive this site.** C-BTU alone needs straight at J-N and J-S,
  right at J-LV, left at J-STEM and right at J-SPLIT. Every diverge needs its own order.
- **J-N and J-S are one chain (2026-11-11).** They are about 0.4 m apart on the floor, and only 0.15 m
  of one tape lies between the end of J-N's fork and the start of J-S's. In that gap the STU tape lies
  against the lane, so the MLS reads one track sliding about 16 mm to the left. When it splits, the
  two tracks are 6 mm apart either side of where the AGV is, so plain straight on is a coin toss.
  Under AUTO it usually went left to STU (owner). The C-BTU teach lap of 2026-11-07 (11:41) went
  through on a LEFT then a RIGHT pressed by hand. The mission now says it: J-N `straight` +
  `steer: left`, J-S `straight` + `steer: right`. Both legs keep their straight names, so g7 is
  unchanged. Position cannot arm J-S's order inside 0.15 m, so the engine chains it
  (`trip_route.decision_points`, `site_run._chain_tick`):
  - J-S's RIGHT is armed on the tick J-N's LEFT is taken by its fork, wherever S is.
  - An order in the chain is taken only once its fork has opened (the last two-track reading at
    least 30 mm apart). One track before that stands the order again.
  - From J-N, wheel travel is the ruler. J-S must show two tracks within 0.5 m and be through within
    0.8 m, else FAULT. On the lap it opened at 0.15 m and was through at 0.49 m. X2, whose crossing
    tape shows on the right first, came at 1.27 m.
  - If the other tape left on the wrong side (by the MLS #LCP code), the result is FAULT.
  - Every fault is a stop. Recovery: MANUAL, jog back to the junction, Reset, Start.
  - The tests replay the lap's readings with S exact, 0.3 m early and 0.3 m late
    (`amr_ws/src/amr_line/test/test_site_chain.py`, `golden/lap2_jn_js_x2.json`).
- **The stem end is a wrong-way hazard.** Taking R2434 instead of the stem southbound drives the AGV
  backwards up a departure curve. `J-STEM` is the first logged fork south of `J-ML` (other tape 121 mm to the
  right, 2026-11-07), and it must be an explicit LEFT, never "nearest track". `J-ML` keeps its LEFT order too.
- **J-S is a territory hazard.** Taking R1570 sends AGV-01 into AGV-02's half.
- **X1 and X2** are oblique crossings. Following straight through them needs a floor check
  (as in MLS bench test B7) before any trip uses them.
- **Both U-turns have a payload guard.**
  - **U-MRU:** the pivot may start only when every called MW release is recorded as done. A
    missed release means a trolley is still attached, so the AGV HOLDs before the tape end for the
    operator. It never pivots.
  - **HOME U-turn R717:** a trip may leave the bay only if the previous trip ended with its
    trolleys detached at home.
  - Without payload detection (D10), "released" and "detached" are records of the stops having been
    served. With `station.enabled` the rear lidar replaces both, and the pivot also needs it to read no trolley.

## 5. What this needs from the code (today vs site)

| Area | Today | Site needs |
|---|---|---|
| Destinations per job | one (`TagTable.destination`) | up to 2 machines per trip, served in circuit order; one shared stop can serve two calls; MRU machines are served twice (release, take back) |
| Branch orders | `branch_default` plus RFID `branch_latch` pairs | an order at every diverge (section 4); the J-N order comes from the trip's group |
| U-turn | triggered by RFID 0180/0190; pivot until the tape is back | triggered by position ahead of the MRU tape end; the pivot is gated on all releases done (payload guard) |
| Missed stop | detected when the U-turn tag is read (`TagTable.note_u_turn`) | BTU: end of row 2 → report. MRU release missed → HOLD before U-MRU. MRU take-back missed → report on arrival at HOME |
| Call queue | none: the job is chosen directly | calls queue on the display; a trip forms at `trip_calls` (1) calls of one group; or a station order with `station.enabled` |
| HOME | RFID 0010, role `home` | the north bay at the end of the stem (park, empty); a separate attach stop after the U-turn; leaving the bay needs a panel Start or, with `station.enabled`, an accepted station order (D14) |
| Position source | RFID tags | 16 machine stops + home + attach + 6 junction orders + the U-turn trigger: tape-graph localization (the localization plan, after P0) |

## 6. Open items

1. ~~**AGV-02 (deferred):** the operator gives the row 3 group as BTU1–8 + STU1–4, but the site plan
   shows STU1–6 on row 3.~~ **Settled 2026-11-14 (owner):** row 3 is BTU1–8 against STU1–6; STU7–10 are a separate line, the
   projection's former "STU 1-4" exit (label corrected).
