# Step N0: physical prerequisites, as confirmed by the operator

2026-09-15, revision 534e58d.

| Item | Status |
|---|---|
| E-stop tested and within the operator's reach | CONFIRMED |
| Reader and DIO network cables reachable to unplug and replug | CONFIRMED |
| No `/manual` open on any device | CONFIRMED (after deviation D1) |
| Vehicle location | OFF the service tape; loose magnetic strip available |
| Drive wheels raised or chocked | **NOT CONFIRMED** |
| Hand-held tags (`0010` x2, `0011`, `0020`, `0021`, `0030`, `0031`) | **NONE AVAILABLE** |

Operator instruction: "no tags. just run whats available."

## Consequence of no wheels raised/chocked

The run sheet calls this "a second barrier; it does not make motion allowed".
Its absence blocks no case, but it removes the mechanical backstop, so the
setpoint poll and the E-stop are the only protections. Recorded, not waived.

## Consequence of no hand-held tags

Cannot run at all - every pass criterion needs a tag presented:

| ID | Why |
|---|---|
| A06 | The case IS the tag read-gap measurement |
| N04 | Every step presents `0010` / `0011` |
| N05 | Needs `0020` / `0021` on the high legs |
| N06 | Needs `0030` / `0031` |
| N08 | Criteria need a station tag presented after reconnect |

Reduced to partial - the non-tag half can still run:

| ID | Runnable part | Blocked part |
|---|---|---|
| N12 | mission `empty` loads, `/auto` shows NO ROUTE / LINE FOLLOWING, gy-demo restored | presenting `0010`,`0011`,`0020`,`0021`,`0030` |
| N14 | guard shown on, step (2) RFID-required fault, (5) continuity-lost fault, (6) Reset/Start refusal, (7) restart, (8) restore | step (4) early-tag rejection |

## Still fully runnable

A01, N02, E02, N10, N11, A02, N03, N07, N09, N13.
