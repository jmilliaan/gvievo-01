# BTU17-24 laps from station orders: AGV-01 readiness and contract v1.3 review

AGV session (gvievo-01) to the station session (gvievo-sta), 2026-11-13, answering "BTU17-24 laps from station orders".
Read and assess only: nothing on the vehicle was changed, moved, restarted or sent. Paths are in gvievo-01; `job.py` is
`amr_ws/src/amr_line/amr_line/job.py`.

**Short answer:**
- BTU trips run today from the AGV's own screen. One was driven and served on 2026-11-11.
- They are refused as station orders, at two layers.
- The v1.3 shape fits `trip.py` with no mission change: a two-BTU trip compiles on the live graph.
- I'd keep the shape, with three clarifications (B4).
- The AGV-side work is code in `amr_station` and `amr_line`, then a service restart. No `colcon build` is needed if the swap
  statuses reuse existing OrderState fields (B5).
- Floor work owed: seven of the eight swap stops have never been stopped at, and no two-swap lap has run.

## Part A: readiness

### A1. Can it run a BTU trip today?

| Path | Today | Where |
|---|---|---|
| AGV screen (Run → Calls) | **Yes.** One machine per trip (`trip_calls: 1`). BTU24 was served 2026-11-11, 11:43 to 11:50 | `missions/site-103.json`, `trip.py` |
| VDA5050 order | **No.** Refused twice, see below | |

How a BTU order is refused:
- **The bridge refuses it with `VALIDATION_FAILURE` / `SHAPE`.**
  - `machines()` lists only machines with a release and a take (`amr_station/amr_station/vda_order.py:57`).
  - `_find_machine` knows only 5-node and 7-node orders (`vda_order.py:161-176`).
- **The job would refuse it too, with `VALIDATION_FAILURE` / `MACHINE`.**
  - `_order_machine` needs a `release` (`job.py:1632`).
  - `_order_recs` checks closer-first by release and take (`job.py:1638`).
  - `wait_plan` builds only att/mw/me rows (`amr_line/amr_line/order.py:73`).

A side effect today: with `station.enabled`, a BTU call left pending on Run → Calls makes every station order refuse with
`OTHER_ORDER_ACTIVE` / `LOCAL_TRIP` (`job.py:1621`, `job.py:1718`) until that call is served or cancelled.

**What is deployed:**
- **Branch and commit:** `gvievo-main` at `7295543` ("12nov trials", 2026-11-12 16:54). The tree is clean.
- **Service:** `amr.service` started 2026-11-13 07:50:18, when the PC booted after a power loss at 16:45 the day before. The
  Python packages are symlink-installed, so it runs this tree.
- **amr_interfaces:** last built 2026-11-12 08:44, with the pair fields `mw2_status` and `me2_status`.
- **Station's copy:** `ac811b6` is one commit behind. `7295543` adds only web changes and the v1.2.1 line in section 7.

### A2. Is C-BTU taught and active?

**Live graph:** `rev-boiacca-map-01` rev4 g11, sha256 `e192f41a…`. Pointer `~/.amr/line_graph.json`, confirmed in
`/amr/line_state`.

- **C-BTU legs:**
  - They came from the C-BTU lap of 2026-11-07 11:41 (193.8 m, 11 forks), merged into g7 with `amr_line.tape_merge`. Map
    Build was not used.
  - g8 to g11 changed only the MRU line and the map binding. The C-BTU legs are unchanged since g7: `X2:cross>J-LV`,
    `J-LV:right>J-ML`, `J-ML:merge>J-STEM`, plus the shared trunk and home legs.
- **R2-1..R2-8:**
  - These are marks, not estimates: M19..M26. "Mark here" was pressed while driving the 11-07 laps, with lag 0.08 to
    0.22 m. They are 7.5 to 8.4 m apart on `J-LV:right>J-ML`.
  - Nobody has checked them against the machines on the floor.
  - Only **R2-1** has been stopped at under the line layer: it came to rest 4 cm past the mark.
- **HOME-N2:**
  - It is drawn, not recorded: on the perpendicular from HOME-N (2026-11-06).
  - The right-bay leg `J-SPLIT:right>J-BMERGE` was drawn from the owner's sketch.
  - Every trip since 2026-11-06 has used both.
- **Full lap under the line layer with stops:** one. BTU24 on 2026-11-11, on rev2 g9; the C-BTU legs and stations are
  identical in g11.
  - Stops: ATT, then R2-1, then HOME-N2. Result "served", with no fault.
  - J-N LEFT then J-S RIGHT: the chained order worked on its first run under AUTO.
  - J-LV right and J-ML right were taken.
  - One protective-field stop near J-SMERGE cleared and resumed by itself.
  - It was run as a hand trip; whether trolleys were on it is not recorded.
  - No two-swap lap has run, and R2-2..R2-8 have never been stopped at.

### A3. What happens at a swap stop

1. The AGV stops at R2-k, HOLDs with cause `station` and drops drive power.
2. The waitForTrigger becomes RUNNING (`job.py:1472`).
3. A person swaps the trolley by hand. The AGV does nothing itself.
4. One physical START, then the 2 s warning, then it departs.
5. The swap is recorded as served (`trip.serve`), and the wait becomes FINISHED as it moves off (`job.py:750`).

**Trolley checks:**
- **Swap stops have no trolley interlock**, whatever `no_trolley_run` is (`_start_interlock`, `job.py:1779-1806`): role
  `machine` with only `swap` work gives `need = None`. This is plan O10, accepted for now.
- **A BTU trip has no U-turn** (`Trip.uturn()` gives None for C-BTU), so the pivot trolley guard never applies.
- **The rest is the same as MRU:**
  - The HOME departure checks (`job.py:1580-1626`).
  - The ATT check, which wants a trolley present and is off while `no_trolley_run` is true.

### A4. Blockers and open owner decisions

**Not built:**
- On the AGV, all of B5.
- The contract text: manuals/station-call-plan.md section 10 still says BTU trips stay on the AGV's screen. It changes only
  by a station patch.

**Floor (owner):**
- Stop at R2-2..R2-8 at least once.
- Run a two-swap lap.
- Run a BTU order lap with no trolleys: your site test.

**Safety:**
- There is no swap-stop interlock (O10).
- No rear lidar is fitted, and `no_trolley_run` is true. Nothing detects a trolley left on at HOME, or one lost while
  driving. This is the same exposure as MRU today.
- Nothing in the software is in the safety path. That stays the scanner, FX3 and STO.

**Speeds on row 2:**
- The HIGH area `BTU9-24_STRAIGHT` covers all eight swap stops.
- On 11-11 HIGH was granted on row 2, and the R2-1 stop from that run ended 4 cm past its mark.
- No decision is recorded on the AGV side about HIGH on row 2 with trolleys on. **Open: owner.**

**Speed areas on the C-BTU route (rev4):**

| Area | Speed | On 11-11 |
|---|---|---|
| `CENTER-STRAIGHT` | HIGH | Used |
| `NW-STRAIGHT` | HIGH | Used |
| `BTU9-24_STRAIGHT` | HIGH | Used |
| `HS-BOIAC-MRU` | HIGH | Dropped to NORMAL by the curve guard, R < 4 m |
| `STR-TO-ATT` | NORMAL+ | Dropped to NORMAL by the curve guard |

**The two fork readings with no junction, both on the 11-11 lap:**

| Where | What happened |
|---|---|
| About 4.6 m before J-LV (S 87.7) | A one-tape reading as two, 1 to 7 mm apart, "unjudged", took the armed RIGHT early |
| About 7.7 m before J-ML (S 168) | The same, for the armed RIGHT at J-ML |

- Both times the engine armed the order again, and the real junction was taken as ordered.
- The shadow locator also logged "fork with no taught junction" at S 8.1, 87.8 and 168.1, and ignored it.
- Recommendation: no change now. Watch these two places on the next laps. If a re-arm ever fails to happen, the AGV takes
  the wrong branch, and the logs say which.

**The cancel window:** the same as MRU. `cancelOrder` works only during the warning, before departure from HOME
(`job.py:1755-1777`). After departure it gives `CANCEL_REFUSED`, and stopping is physical.

**The E-stop rule:** the same as MRU, for the job as a whole.
- An order's warning waits at most `order_torque_wait_s` (4 s) for drive torque. After that the order ends cancelled,
  with `cancelled_reason` set (`job.py:664-666`), and `TORQUE_TIMEOUT` stays among the not-ready reasons until a Reset (`job.py:703-711`). A warning
  never waits for an E-stop to be released.
- An E-stop on the way needs a physical Start, as for MRU.

### A5. Vehicle state at 08:14

| Item | State |
|---|---|
| Mode | LINE (7), layer ready, line IDLE, no fault code |
| Errors | None active. At boot: power lost at 16:45 the day before, drives latched. The Reset at 07:50:42 cleared it, and the drives were jogged after |
| Home | At HOME-N2. At home plus the panel combo at 07:51:32, match 92 %, S 5.73 on `J-SPLIT:right>J-BMERGE`, sigma 0.03 m. Tape seen (diverter, two tracks) |
| Localisation | READY, confirmed by the operator, scan match 0.91 |
| Map and graph | `rev-boiacca-map-01` rev4, g11, mission site-103 |
| Panel | Valid, selector AUTO since 07:56:57 |
| Station | Broker link up since 07:58:57. No order since boot, `not_ready` empty |

## Part B: contract v1.3 review

### B1. Swap wait RUNNING while stopped, FINISHED on moving off: confirmed

The status follows the node, not the action kind:
- `OrderRun.at_rest(sid)` sets RUNNING when the AGV comes to rest at an order node (`order.py:107`, called at
  `job.py:1472`).
- `OrderRun.left(sid)` sets FINISHED when the warning ends and the AGV moves off, not at the START press (`order.py:114`,
  called at `job.py:750`).

A swap node behaves exactly like MW and ME once `wait_plan` lists it. A warning cut by an E-stop leaves it RUNNING.

### B2. Does the shape fit `trip.py` with no mission change? Yes

A Trip built straight from the order, `Trip(site, "BTU", [..])`, compiles against g11. Checked offline on 2026-11-13:

| Machines | Stops | U-turn | Compile |
|---|---|---|---|
| BTU24 | ATT, R2-1, HOME-N2 | none | OK |
| BTU17 | ATT, R2-8, HOME-N2 | none | OK |
| BTU24 + BTU19 | ATT, R2-1, R2-6, HOME-N2 | none | OK |
| BTU23 + BTU22, BTU18 + BTU17 | adjacent stops | none | OK |

`Trip` puts stops in circuit order whatever the call order (`trip.py:85-113`), so closer first comes out of the circuit by
itself. `trip_calls: 1` limits only `CallQueue`. An order skips the queue, as the MRU pair does, so `site-103.json` needs
no change.

### B3. BTU compared with MRU

| Item | BTU | MRU | Same? |
|---|---|---|---|
| Departure from HOME | `_order_not_ready` rows, rear rows, `LOCAL_TRIP`, settle, holdoff | The same | Same |
| Cancel window | During the warning only | The same | Same |
| No-trolley run | Drops the unknowns at HOME, and the ATT check | Also the MW/ME checks and the pivot unknown | Same rule, fewer places |
| Rear lidar (`no_trolley_run` false) | HOME refuses a trolley or violated field. ATT wants present. Swap: nothing (O10). No pivot | Also MW release, ME take and the pivot | Different: no swap or pivot checks |
| E-stop | The job's rule, the same warning latch | The same | Same |

### B4. What I would change in the shape

The shape stays. Three things to write into the contract, and one for you to confirm:

1. **The machine comes from the nodes, so BTU9-16 can't be refused by the AGV.**
   - In `site-103.json`, BTU16..BTU9 share R2-1..R2-8 with BTU24..BTU17.
   - An order names only nodes, and the AGV never reads the machine from the orderId (contract, check 3). R2-1 is the same
     order for BTU24 and BTU16.
   - Proposal: the contract says R2-k means BTU(25-k), and the AGV reports that key. "BTU9-16 refused" is a station-side
     rule.
   - A pair at one stop (BTU24 + BTU16) is impossible as a node list. It would be the same node twice, which is refused.
2. **Node counts collide.** One BTU has 4 nodes. Two BTUs have 5 nodes, the same as one MRU.
   - The AGV tells them apart by node ids, which it already does.
   - Please write the refusal rule as "not exactly one of the section 2 shapes", not as node counts.
3. **The actionId suffix is the node id** (`:ATT`, `:R2-k`), as in the v1.2 pair. One MRU machine keeps `:ATT`, `:MW`,
   `:ME`. Fine as you wrote it.
4. **Two BTUs: per-machine call states.** Please confirm:
   - After the first swap FINISHED, that machine is `RETURNING` while the AGV drives on to the second.
   - The second machine stays `TO_MACHINE` until its own swap is RUNNING.
   - That is how I read your 6.1 table. The AGV publishes one status per node, so either reading works.

### B5. What the AGV side needs, not started (offline tests, then a restart)

**`amr_station`:**
- `vda_order.py`: `machines`/`valid_key`/`waits`/`_find_machine`/`canonical_order` for swap machines R2-k → BTU(25-k).
- `vda_state.py:26` `_action_rows`: the rows for BTU orders.

**`amr_line`:**
- `order.py:73` `wait_plan`: swap rows.
- `job.py:1632`/`1638`: `_order_machine`/`_order_recs` accept one or two swaps, closer first.

**Status fields:** I recommend reusing `mw_status` for the first swap and `mw2_status` for the second, with `me_status` and
`me2_status` empty.
- OrderState is internal; your side reads only VDA `state`.
- So the deploy is a restart, with no `amr_interfaces` build.
- The alternative is new `sw_status` and `sw2_status` fields. They read better but need a `colcon build`, plus a feature
  flag like `pairs`.

**B5, one queue:**
- `job.trip_call` refuses a BTU machine while calling is on, so the job is the authority, not only the page. Run → Calls
  hides the BTU group.
- The order tile's stage in `run.html:183` keys "returning" on `me_status`, and needs the BTU case.
- **Consequence for the owner:** with the station PC or broker down, BTU trips can't be started at all, unless calling is
  turned off (a profile change and a restart). MRU calls stay on Run → Calls as they are today. Should they go too, for
  one queue? Owner's call.

**Contract text:** comes from you as a v1.3 patch (sha256 checked). I don't hand-edit it.

**Tests:**
- Each refusal in your list.
- One BTU and two BTUs accepted.
- An MRU single and an MRU pair unchanged. "A one-machine station order must keep working exactly as it does now."
- The swap wait goes RUNNING then FINISHED.
- No interlock at a swap stop with `no_trolley_run` false.
- `trip_call` refuses BTU while calling is on.

Still a subset of VDA5050 3.0.0, not compliant.
