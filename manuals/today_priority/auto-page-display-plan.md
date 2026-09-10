# Auto page: direction, RFID and route progress

Status: **implemented and verified offline; hardware case A11 NOT RUN**. This
was a display-focused follow-up to the route/high-speed work. Sections 1-5
below describe the delivered behavior; section 6 records how it is covered.

Offline evidence, 2026-09-10: `tests/run_all.py` 117 test functions / 1275
checks, exit 0; `tests/browser_auto.py` 44 real-DOM checks at 1440x1000 and
390x844, 0 failed. Neither exercises a vehicle, a reader or a drive.

## 1. Operator-facing priority

Make the first section on `/auto` answer, at a glance:

1. Which point is the AGV travelling to, stopping at, or waiting at?
2. Is the logical travel direction OUTBOUND or INBOUND?
3. What RFID value was recently read, and did it cause a route action?
4. Where is the AGV in the repeating sequence 2 -> 3 -> 4 -> 1 -> 2?

Use large point numbers and direction text, with a compact, persistent
sequence row. Place PID values, gains, detailed wheel telemetry and MLS data
below this operating summary. Keep faults/holds prominent above or within it;
they must not be hidden by the larger route display. Retain the physical-panel
instruction. This change adds no motion controls.

## 2. Main display behavior

| State | Main point text | Supporting information |
|---|---|---|
| Controller startup | `POINT 2 - INITIAL POSITION ASSUMED` | OUTBOUND; next point 3; waiting for physical Start |
| Travelling from 2 to 3 | `TO POINT 3` | OUTBOUND; last route station 2; current leg 2 -> 3 |
| Station tag accepted, deceleration underway | `STOPPING AT POINT 3` | Arrival direction OUTBOUND; do not claim already stopped |
| Station dwell with stopped feedback | `AT POINT 3 - WAITING FOR START` | Current direction OUTBOUND; next departure INBOUND through upper U-turn to point 4 |
| Start delay at point 3 | `POINT 3 - STARTING` | Remaining delay; direction stays OUTBOUND until departure is committed |
| Departing point 3 | `TO POINT 4` | INBOUND; upper U-turn; current leg 3 -> 4 |
| Temporary hold | `HOLD - [reason]` | Retain route point/leg and direction underneath; indicate recovery behavior from existing state |
| Reset/manual/disarmed | `STOPPED` / `MANUAL` / `DISARMED` as appropriate | Retained route stage; never label the AGV as travelling solely because route.parked is false |
| Route position fault | `POSITION CHECK REQUIRED` | Last logical stage for diagnosis; return to point 2 and restart; suppress confident position wording |
| HTTP state updates fail or become stale | `LIVE STATE UNAVAILABLE` | Last received values explicitly stale; no animated progress or live-reading badge |

Direction is logical route direction, not a compass measurement or reverse
motor command. Use full words; do not imply physical heading from an arrow.
At points 1 and 3, distinguish the retained arrival direction from the next
departure direction. Cancelled Start must leave the displayed stage unchanged.

`route.parked` becomes true when the station tag is accepted, before the vehicle
finishes decelerating. It also starts true at process initialization. The display
must not interpret that flag alone as proof of a stationary, confirmed location.
Use fresh drive stopped feedback for dwell wording; show stopping/status unknown
if feedback is unavailable. Do not invent a new motion threshold in JavaScript.

## 3. Sequence display

- Render the ordered point IDs from `/api/config.route`, including the return
  to the first point. Current configuration is 2 -> 3 -> 4 -> 1 -> 2.
- During travel, emphasize the current leg and label its destination `NEXT`.
  During dwell, emphasize the route station and label it `WAITING`.
- Show the completed lap count separately. The final 2 is the return boundary,
  not a fifth physical station; it increments the lap count on arrival.
- Use text and emphasis as well as color. Make it readable at the installed
  HMI resolution and on a narrow phone without horizontal overflow.
- Do not draw a moving position marker or percentage-complete bar from the
  distance estimate. Reused tags and wheel-speed integration do not provide
  continuous physical localization.

## 4. RFID display

Place a large four-character, zero-padded hexadecimal value beside the route
summary, with three separate facts:

| Fact | Display rule |
|---|---|
| Recent read | Show `rfid.tag` as `RECENT READ`, with age; its existing 2 s hold is not proof that a tag is physically under the reader |
| Last read | When the recent-read window expires, retain `rfid.last_tag` with `LAST READ` and age; never disguise it as live |
| Reader health | Show connection status separately. No recent tag is normal between stations; link loss makes any retained value historical |
| Route effect | Show the controller's last processed encounter and outcome separately from the raw read: station accepted, high selected, normal selected, early arrival rejected, or no route action |

Point IDs and RFID values must never be interchangeable labels: points 2/3
share 0010, and points 1/4 share 0011. A raw read alone cannot prove arrival.
Keep raw receive count and distinct encounter count in secondary diagnostics.
Continuous reads should not flash/reanimate the main panel on every HTTP poll.

For reliable route-effect wording, add a small structured **last processed
encounter** record to the controller snapshot: encounter sequence, tag,
processing age/time, resulting action, station ID if accepted, and reason if
suppressed/rejected. This record does not exist in the current snapshot.
Update it on the CAN thread when an encounter is consumed; distinguish a raw
last read from an older processed encounter after batching or reconnect.
Do not infer actions by parsing event strings or advancing a browser-side route.
Driver-ignored tags may not reach the current public snapshot; exposing every
raw wire frame is outside this display change.

## 5. Implementation boundaries

| File | Planned work |
|---|---|
| `app/templates/auto.html` | Place the operating summary and sequence first; move detailed diagnostics below; retain unique DOM IDs |
| `app/static/auto.js` | Render explicit operating states, logical direction, active point/leg and sequence from server snapshots |
| `app/static/app.css` | Add Auto-specific responsive styles for large point/direction/tag text and readable fault/hold states |
| `app/static/common.js` | Preserve Manual page RFID behavior; scope any new last-read presentation to Auto so shared rendering cannot overwrite it |
| `canworker.py` / `core/route.py` | Expose only the structured display metadata needed for processed encounters/startup assumptions; keep route decisions on CAN thread |
| `tests/test_web.py`, route/controller tests | Cover state rendering inputs, structured outcomes, data freshness and preservation of read-only panel policy |

Use existing `/api/state` polling and `/api/config`; no new transport, control
endpoint, browser-owned state machine, or route mutation is needed. Preserve
the existing heartbeat behavior during this layout work; do not change watchdog
ownership as an incidental UI edit. Freshness should use the existing polling
failure policy and an explicitly defined age condition if one must be added.

Keep normal/high/slow mode and route-guard on/off visible as secondary status.
PID diagnostics remain available below; avoid repeating competing point/tag
headlines elsewhere on the page.

## 6. Acceptance tests for this follow-up

1. Offline fixtures cover startup, all four legs/dwells, deceleration, cancelled
   Start, direction-changing departures, completed lap and process restart.
2. Raw 0010/0011 reads at pass-through points never claim arrival without the
   matching controller outcome. Test repeated reads, early rejection, batching,
   reconnect baseline, and last-read ageing.
3. Station deceleration is visibly different from stopped dwell. Missing speed
   feedback cannot produce a confident `WAITING FOR START` claim.
4. Fault, line/drive hold, manual mode, disarm and stale HTTP state override
   normal travel wording while preserving useful last-known route context.
5. Browser tests check large/small viewport layouts, text without color cues,
   no duplicate DOM IDs, no competing shared RFID updates, and no new motion
   POSTs. Reload mid-leg must reproduce the server state immediately.
6. On hardware, the operator verifies point/direction/tag visibility from the
   normal viewing position during a full lap and each U-turn departure. This is
   recorded as case **A11** in the hardware handoff and is **NOT RUN**; it is
   additional to that document's original 26 motion/fault cases.

Coverage of 1-5 (all passing offline, none on hardware): items 1-4 in
`tests/test_auto_display.py` (controller-side outcomes: startup assumption,
drive-feedback dwell verdict, suppressed/high/normal/pass-through/accepted
actions, batching, repeated reads, early-arrival rejection, reconnect baseline,
encounter ageing) and in `tests/auto-page.browser.js` (rendered wording for all
four legs, dwell versus deceleration, unknown feedback, pending and cancelled
Start, hold, manual, disarm, controller fault, route fault, lap count and return
boundary). Item 5 is the same browser fixture at both viewports: unique DOM IDs,
no horizontal overflow, no motion requests, the shared `showRfid` renderer
unable to overwrite the Auto headline, and a mid-leg reload reproduced from
polling alone.

Definition of done: the operator can identify direction, destination/current
stop, latest tag and route stage from the first visible section, with no need
to interpret PID fields and no false claim of physical location or live data.
