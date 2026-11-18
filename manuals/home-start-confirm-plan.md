# START at HOME confirms the trolleys are off (station calling, no rear lidar)

Owner, 2026-11-17: after a trip ends at HOME the AGV takes the next station order whether or not the
trolleys were unhitched. The operator must press the physical START at HOME to say "trolleys off,
ready to go to ATT". Until then no order may depart.

## 1. Why it happens today

| Mode | What holds the next trip at HOME |
|---|---|
| Calling off (screen calls) | `trip.Payload`: `trip_ended()` at HOME, cleared by Run → Calls "trolleys off" (`job.confirm_off`) |
| Calling on, rear lidar fitted | `TROLLEY_PRESENT` from the rear lidar (`job._rear_rows`) |
| **Calling on, `station.no_trolley_run` (agv-01 today)** | **Nothing.** `confirm_off` answers "the rear lidar decides", and `_rear_rows` drops `TROLLEY_UNKNOWN`. After the 5 s `SETTLING` from the arrival, `NOT_READY` is empty and the station sends the next order |

## 2. Rule

With calling on **and** `station.no_trolley_run` true, the existing `Payload` holds the bay again:

- Arrival at HOME after a trip (already: `_arrive_home` → `payload.trip_ended()`), and service start
  (`Payload()` starts unconfirmed), leave it **not confirmed**.
- While not confirmed, `NOT_READY` carries a new reason **`TROLLEY_NOT_CONFIRMED`**. The station sends
  nothing (contract: it sends only with no `NOT_READY`), so no order departs. No station logic changes.
- The **physical START** confirms it, when all of these hold at the press:
  - job IDLE or DONE, no trip, no active order, no call waiting;
  - parked at HOME (`parked_at_home`: locator at HOME, no wheel movement since arrival or At home).
  The press then does exactly this: `payload.confirm_off()`, `SETTLING` restarted (5 s before an order
  can come, so the operator can step away), one operator event "trolleys off at HOME confirmed (START)".
  It never starts motion. Selector position does not matter (MANUAL or AUTO); an order still needs AUTO.
- A START that does not meet the conditions keeps today's behaviour (refused with its reason).
- Nothing else confirms it: not At home, not Reset, not the web, not the station.
- With the rear lidar fitted (`no_trolley_run` false) nothing changes: `TROLLEY_PRESENT` decides, the
  new reason is never raised. Calling off: unchanged (web confirm).

Safety: this only withholds orders; it adds no path to motion. A START press that confirms is consumed
by the confirmation and is never also a run start.

## 3. Work items

| # | File | Change |
|---|---|---|
| H1 | `amr_line/order.py` | `TROLLEY_NOT_CONFIRMED = "TROLLEY_NOT_CONFIRMED"` |
| H2 | `amr_line/job.py` `_order_not_ready` | after `_rear_rows`: if `no_trolley_run` and not `payload.may_leave()[0]`, add it |
| H3 | `amr_line/job.py` `_start` (IDLE/DONE path) | calling + `no_trolley_run` + payload not confirmed + the §2 conditions → confirm, restart `SETTLING`, event, return zero. Checked **before** `_prerequisite`, so a field or drive state cannot turn the confirmation into a refusal |
| H4 | `amr_line/job.py` `confirm_off` | keeps refusing with calling on (the web never confirms); text "press START at HOME" when `no_trolley_run` |
| H5 | `job.trip_status` / `LineState.reason` | while not confirmed at HOME: "at HOME-N2: unhitch the trolleys, then press START" (Home tile and Run → Calls show it) |
| H6 | `amr_station` state | the reason passes through like every other `NOT_READY` reason (no code: reasons are a list) |
| H7 | Tests (`amr_line/test`) | arrival → reason present, no order accepted (`DEPARTURE_REFUSED`, `TROLLEY_NOT_CONFIRMED`); START at HOME → reason gone after `SETTLING`, order accepted; START moved off HOME → refused, reason stays; START never arms (state stays IDLE/DONE, wheels zero); boot → reason present; lidar fitted → never raised; calling off → web confirm unchanged; the confirming press is not also a trip start |
| H8 | Docs | RUNBOOK operator steps, the operation manual's station-trip page |

Build mark: restart only.

## 4. Contract (station patch, v1.6)

The reason string is a contract value (section 8). The station sends the patch, as for v1.5:

- Section 8 precondition table: a row "Trolleys confirmed off at HOME by a physical START after a
  trip's arrival or a service start (only without the rear lidar)" → AGV check 9 → `TROLLEY_NOT_CONFIRMED`.
- The reasons list and the operator text on the station screen: "unhitch the trolleys, press START on
  the AGV".
- No order, state or action shape changes.

Until the patch, the AGV may already raise the reason: the station holds back on any `NOT_READY`.

## 5. Order

H1–H8 on the AGV, tests → station patch v1.6 applied and its sha checked → owner restarts amr.service.

## 6. Status

**Built 2026-11-17, uncommitted, restart owed.** H1–H5 and H7 as above:
- `order.TROLLEY_NOT_CONFIRMED`, `job._home_confirm_needed` / `_home_confirm`;
- the arrival and IDLE texts; `confirm_off` text;
- catalogue row `HOME_TROLLEYS_CONFIRMED` (RUNBOOK section 4 regenerated).

Tests:
- `test_no_trolley_run`: service start holds; START confirms, never moves, restarts SETTLING; moved off HOME refuses; arrival holds again; rear lidar never raises it; the web never confirms.
- The other no-lidar worlds confirm once at start-up.
- amr_line 750 passed; run_all 991 checks.

Open:
- H8 operator manual text;
- the station's v1.6 patch (reason string and screen text).
