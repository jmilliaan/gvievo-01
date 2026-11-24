# Interface contract v1.6: SIGNED (2026-11-24)

Status: **signed off by the owner on 2026-11-24** ("ok F agreed. v1.6 signed off, start building"). This is r2, with the station's review A-F and every section 11 item decided. It was written by the AGV-2 session after the owner approved the two-zone
concept, and reviewed by the station session. **This file holds the v1.6 changes. Every section of v1.5 not
listed here applies unchanged.** The embedded contract at the end of `manuals/station-call-plan.md` points here.
The station keeps its copy as `docs/agv/agv-reply-contract-v1.6.md`.

Diagrams: `home-traffic-concept.png` (zones, wait and release points) and `home-traffic-two-zones.png`
(step by step), both at the repo root.

**Changes from 1.5.**

1. Traffic control between AGV 1 and AGV 2 at HOME:
   - zone **Z1 DEPART**, a station dispatch rule only (section 12);
   - zone **CLUSTER**, a VDA5050 3.0.0 RELEASE zone (section 13).
2. New topic `responses` (sections 1 and 13).
3. New `state.zoneRequests`, new AGV_HOLD cause `traffic`, new errors, and a new `NOT_READY` reason (sections 5, 6 and 13).
4. AGV 2's order shapes (section 2a).
5. The broker moves to 192.168.2.250, with ACL lines for `agv2` and `responses` (section 1).

Every v1.5 order and every v1.5 state field is unchanged, byte for byte.

Sections not listed here are unchanged from v1.5.

---

## 1. Transport (changes only)

**Broker.** Mosquitto on the station PC (gvipc-evo-sta), TCP `192.168.2.250:1883`, listener bound to that
address only. The other settings are as in v1.5.

**Topics.** One topic is added per AGV:

| Topic | Published by | Subscribed by | QoS | Retain |
|---|---|---|---|---|
| `vda5050/v3/gvi/agvN/responses` | station | AGV N | 0 | no |

The other four topics are unchanged. With `responses`, each AGV has five topics; no other topic exists.

**ACL** (Mosquitto `acl_file`, kept outside both repos):

```
user station
topic write vda5050/v3/gvi/+/order
topic write vda5050/v3/gvi/+/instantActions
topic write vda5050/v3/gvi/+/responses
topic read  vda5050/v3/gvi/+/state
topic read  vda5050/v3/gvi/+/connection

user agv1
topic write vda5050/v3/gvi/agv1/state
topic write vda5050/v3/gvi/agv1/connection
topic read  vda5050/v3/gvi/agv1/order
topic read  vda5050/v3/gvi/agv1/instantActions
topic read  vda5050/v3/gvi/agv1/responses

user agv2
topic write vda5050/v3/gvi/agv2/state
topic write vda5050/v3/gvi/agv2/connection
topic read  vda5050/v3/gvi/agv2/order
topic read  vda5050/v3/gvi/agv2/instantActions
topic read  vda5050/v3/gvi/agv2/responses

user watch
topic read  vda5050/v3/gvi/#
```

**Receive rules on the AGV.** A `responses` message with the MQTT retain flag set is discarded with no
effect and no report, the same as `order` and `instantActions`.

## 2a. AGV 2 orders

AGV 2 (`serialNumber` `agv2`) serves the south machines, AGV 1 the north ones (owner, 2026-11-14 and
2026-11-24). The station routes each call by machine:

| AGV | Machines |
|---|---|
| `agv1` | MRU1-4, BTU9-24 (as in v1.5) |
| `agv2` | BTU1-8 and STU1-6 (group ROW3, swap); STU7-10 (group STU, release and take) |

Rules for AGV 2:
- Its home node is `HOME-N` and its attach node `ATT`.
- **One machine per order.** The site mission has `trip_calls` 1. AGV 2 never receives a pair, and the AGV
  refuses one with `VALIDATION_FAILURE`. The station needs a per-AGV "one machine per order" setting, which is
  station work.

**ROW3: a swap stop per machine.** Each machine has its own stop, so there is never a `machines` parameter.
The stops in travel order:

| Swap node | R3-1 | R3-2 | R3-3 | R3-4 | R3-5 | R3-6 | R3-7 | R3-8 | R3-9 | R3-10 | R3-11 | R3-12 | R3-13 | R3-14 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Machine | BTU8 | BTU7 | STU6 | BTU6 | STU5 | BTU5 | STU4 | BTU4 | STU3 | BTU3 | STU2 | BTU2 | STU1 | BTU1 |

The shape is the v1.5 one-BTU-stop shape, with `HOME-N` and `R3-k`:

| sequenceId | Item | Action |
|---|---|---|
| 0 | node `HOME-N` | none |
| 1 | edge `HOME-N:ATT` | none |
| 2 | node `ATT` | `waitForTrigger`, id `<orderId>:ATT` |
| 3 | edge `ATT:R3-k` | none |
| 4 | node `R3-k` | `waitForTrigger`, id `<orderId>:R3-k` |
| 5 | edge `R3-k:HOME-N` | none |
| 6 | node `HOME-N` | none |

**STU7-10: release and take, with the U-turn on the AGV.** The shape is the v1.5 one-MRU shape, with
`HOME-N`, `SW-n` and `SE-n` for n = 7 to 10:

| sequenceId | Item | Action |
|---|---|---|
| 0 | node `HOME-N` | none |
| 1 | edge `HOME-N:ATT` | none |
| 2 | node `ATT` | `waitForTrigger`, id `<orderId>:ATT` |
| 3 | edge `ATT:SW-n` | none |
| 4 | node `SW-n` | `waitForTrigger`, id `<orderId>:MW` |
| 5 | edge `SW-n:SE-n` | none |
| 6 | node `SE-n` | `waitForTrigger`, id `<orderId>:ME` |
| 7 | edge `SE-n:HOME-N` | none |
| 8 | node `HOME-N` | none |

The action ids keep the generic `:MW` (the release wait) and `:ME` (the take wait), so the release-and-take
rules of section 6.1 apply unchanged. The U-turn (counter-clockwise, 0.1 m past the release) lies inside edge
`SW-n:SE-n` and is never sent.

**orderId.** `<machine>-YYYYMMDDTHHMMSS`, for example `BTU5-20261125T081500`, `STU3-...` (ROW3) or
`STU8-...` (STU). The machine name tells the shape apart. Section 6.1's table applies as for BTU (swap rows)
and MRU (release-and-take rows).

## 5. How the AGV fills state (additions)

| Field | Value |
|---|---|
| `zoneRequests` | Always present, `[]` when there is no request. See section 13 |
| `errors` → `AGV_HOLD` | Adds the hold cause `traffic`: stopped before CLUSTER and waiting for a grant |

## 6.3 Errors (additions)

| errorType | Level | When |
|---|---|---|
| `NOT_READY` reason `ZONE_HELD` | WARNING | The AGV holds a zone with no trip, after a restart (13.6). It takes no order until the zone is released |
| `ZONE_REQUEST_REJECTED` | WARNING | The station answered `REJECTED`. The AGV holds as `traffic` and does not enter. References `requestId` |
| `ZONE_RELEASE_LOST` | CRITICAL | The station revoked a grant while the AGV was inside the zone. The AGV stops (13.7). References `requestId` |

## 12. Z1 DEPART: one AGV leaving home at a time (new)

**Z1 is not a message.** It is a station rule added to "AGV free" (section 8): **an order may be sent to AGV A
only when Z1 is clear of the other AGV B.**

The station decides "Z1 clear of B" from B's newest state and B's current or last orderId `O`:

| B's state | Z1 |
|---|---|
| No active order (`nodeStates` empty), and B's last order is Closed, or reached ATT FINISHED | clear |
| `O:ATT` is `FINISHED` | clear **4 s** after the first state that showed it, by the station's monotonic clock |
| `O:ATT` is `WAITING` or `RUNNING` (driving to ATT, or stopped there) | **held** |
| The order ended early: `O:ATT` is `FAILED`, and `errors` has `DEPARTURE_CANCELLED` for `O` (the warning was cancelled at home and B never moved) | clear |
| The order ended early: `O:ATT` is `FAILED`, with `TRIP_ABORTED` for `O` or no error (B moved and may stand anywhere between its bay and ATT) | **held until an operator clears Z1** (13.8) |
| B restarted mid-order: `state.orderId` changed to `""` while `O:ATT` was not `FINISHED` (row 2: Aborted) | **held until an operator clears Z1** |
| The station has an order out to B that B's states have not yet shown (`state.orderId` ≠ that orderId), sent or still being resent (section 8) | **held** (review B: B may have taken the order and gone quiet before any state showed it) |
| B not fresh (no state for 3 s), `OFFLINE`, or `CONNECTION_BROKEN`, while its last fresh state had Z1 held | **held** (fail closed). Shown on the screen |
| B not fresh, but its last fresh state had Z1 clear and no order is out to B | clear: a stale, idle AGV cannot move by an order, and local trips are outside this contract (owner flag 1) |

**When ATT turns FINISHED.** `O:ATT` turns `FINISHED` only when the AGV actually starts to move off ATT, after
the warning. An AGV that holds at ATT for CLUSTER (section 13) keeps `O:ATT` as `RUNNING`, so Z1 stays held
during that wait.

**Local trips** (Run → Calls on the AGV screen) are outside this contract: they neither hold nor wait for Z1
or CLUSTER (owner, 2026-11-24). With `station.enabled` on, the AGV screen takes no new calls anyway (v1.2), so a
local trip exists only on an AGV with the station off. Keeping that clear of the other AGV is the
**operator's responsibility**, under the rule in section 11 item 5.

## 13. CLUSTER: a RELEASE zone (new)

### 13.1 The zone

| Item | Value |
|---|---|
| `zoneSetId` | `SITE103-TRAFFIC-1` |
| `zoneId` | `CLUSTER` |
| VDA5050 type | RELEASE (3.0.0, section 6.4.1.1), contour-based: the AGV and its load are in the zone while any part of them is |
| Covers | junctions J-N, J-S, X2, X3, X1, J-MR, J-STEM and J-SMERGE, and the tape east to J-SPLIT |
| Geometry | A polygon drawn on each AGV's own map. It is not sent: no `zoneSet` topic and no `downloadZoneSet`. The two maps agree within 0.10 m at the cluster |
| Holder | One AGV at a time. The station is the only arbiter |

### 13.2 Request (AGV, in `state.zoneRequests`)

```json
{"requestId": "<orderId>:CLUSTER:1", "requestType": "ACCESS", "zoneId": "CLUSTER",
 "zoneSetId": "SITE103-TRAFFIC-1", "requestStatus": "REQUESTED"}
```

**requestId.** `<orderId>:CLUSTER:<n>`, where `n` counts this order's CLUSTER requests from 1. A normal trip
makes two: 1 on the way out and 2 on the way home. A fresh request after a `REVOKED` (13.7) gets the next
`n`. The orderId is unique and made from the station clock, so a requestId is unique across AGV restarts.

**One id covers one cycle.** A requestId lives from the request, through the grant and the time inside, to
the release, when the entry is removed. It is never reused.

| When the AGV asks | Point |
|---|---|
| Leaving | The first START at ATT. The AGV stands 1.0 m outside the zone |
| Home-bound | The front 10 m before the zone, measured along its route (Wi-Fi assumed good there, owner) |

**Statuses the AGV reports.** `REQUESTED`, then `GRANTED` once it has a grant (inside, or about to enter),
then the entry is **removed** on release. `REVOKED` appears only in 13.7. The AGV never reports `QUEUED`
(the state schema has no such value) or `EXPIRED` (no `leaseExpiry` is used).

### 13.3 Response (station, on `responses`)

```json
{"headerId": 41, "timestamp": "...", "version": "3.0.0", "manufacturer": "gvi", "serialNumber": "agv2",
 "responses": [{"requestId": "STU8-20261125T081500:CLUSTER:2", "grantType": "GRANTED"}]}
```

- The field is **`grantType`**, as in the 3.0.0 schema. The spec prose calls it `responseType`; the schema wins.
- `grantType` is `GRANTED`, `QUEUED` (heard, wait), `REJECTED` (13.7) or `REVOKED` (13.7).
- No `leaseExpiry` is sent, because the contract never compares clocks.

**Resend.** On every state from an AGV that lists a request as `REQUESTED`, the station answers with its
current decision for that requestId, `GRANTED` or `QUEUED`, at most once per second per requestId.
- `QUEUED` is resent under the same rule, so the AGV screen can show "queued".
- The station also resends `REVOKED` under this rule while an entry it revoked is still listed `GRANTED`.
- It sends nothing for an entry already listed `GRANTED` that it has not revoked.

**On the AGV:**
- A response for a requestId it does not hold is ignored.
- A repeated `GRANTED` changes nothing.
- `QUEUED` changes nothing except the display.

### 13.4 Arbitration (station)

1. **Grant:** CLUSTER is free and requests are waiting. The station grants the oldest, by the station
   monotonic time when the station first saw it. On a tie within 1 s, the home-bound request goes first: a
   request with `n` ≥ 2, or one from an AGV past its ATT FINISHED.
2. **Queue:** the others get `QUEUED`.
3. **Held:** CLUSTER is held by H from the first `GRANTED` sent to H until it is freed under 13.5. It is
   never granted to two AGVs.

### 13.5 Release and the unbroken link (station)

**How the AGV releases.** It removes the entry from `zoneRequests`:
- **leaving:** when the last trolley is out of the zone;
- **home-bound:** when the AGV is parked at HOME **and** the operator has confirmed "trolleys off" (owner,
  2026-11-24). The parked train's tail sits in the narrow bay lanes until then.

**When the station frees CLUSTER.** When a state from H no longer lists H's granted requestId, **and the
link to H has been unbroken since the station first sent that `GRANTED`.**

**The link to H is broken** if any of these happened since that first `GRANTED` (review A, 2026-11-24):
1. the station's own MQTT client reconnected to the broker;
2. a state from H with `headerId` not greater than the previous state's `headerId` from H. This is the
   signature of a restart: the bridge's headerId starts again at 0;
3. a gap of more than **60 s** between two consecutive states from H, by the station monotonic clock. A
   long gap could hide a restart whose headerId has since climbed past the old one; at 1 Hz, 60 s keeps that
   window small.

**`connection` messages alone do not break the link.** Wi-Fi blips at HOME are common: on 2026-11-24 the
station's log shows `CONNECTION_BROKEN` for 12 s and for 54 min while AGV 1 was parked. A reconnect without a
restart leaves the AGV's own state, and so its `zoneRequests`, intact. A restart is caught by rule 2, and the
grant survives it in the AGV's file (13.6).

**If the link was broken and the entry is gone,** CLUSTER stays held with status "release unconfirmed" until
an operator clears it (13.8).

**If the entry is still listed `GRANTED`,** H still holds the zone, whatever happened to the link.

### 13.6 The AGV side

**Grant kept across restarts.** On `GRANTED`, the AGV writes `{requestId, zoneId, zoneSetId}` to a file in its
state directory. On release it deletes the file. On start-up, if the file exists:
- the AGV reports that entry as `GRANTED`, with no trip, and raises `NOT_READY` `ZONE_HELD`;
- it keeps doing so until an operator releases it on the AGV's Run page, after checking that the AGV and its
  trolleys are clear of the cluster, or until a `REVOKED` arrives (13.7).

**Waiting.** No `GRANTED` by the time the front reaches the zone means a measured stop **before** the zone
and AGV_HOLD `traffic`. When `GRANTED` arrives: the pre-move warning horn, then go, with no START (owner,
2026-11-24).

**Entering needs a live link.** The AGV enters only if its MQTT link is up at that moment. A grant that has
not been used yet, with the link down at the zone edge, counts as not granted: the AGV waits. Once inside, it
carries on whatever happens to the link. So an AGV that is offline never enters.

**Not in the safety path.** The zone only adds stops. The scanners stay the safety function.

### 13.7 REJECTED and REVOKED

| Response | AGV state | AGV does |
|---|---|---|
| `REJECTED` | any | Does not enter. Holds `traffic`, raises `ZONE_REQUEST_REJECTED`, keeps the entry as `REQUESTED`. An operator Reset ends the trip (v1.5 rules) |
| `REVOKED` | no trip (13.6) | Removes the entry. That is the release |
| `REVOKED` | trip, not yet in the zone | Removes the entry, then requests again with the next `n` |
| `REVOKED` | trip, inside the zone | Stops. Raises `ZONE_RELEASE_LOST` (CRITICAL). Keeps the entry as `REVOKED` until an operator Reset. The VDA5050 `releaseLossBehavior` is `STOP` |

The station sends `REJECTED` only for a request it cannot place: an unknown zone or zoneSetId, or a malformed
requestId. It treats a revoked zone as still held by H until H reports `REVOKED` or drops the entry (VDA5050
6.4.3).

### 13.8 Operator actions on the station screen

| Action | Allowed when | Station | What the AGV sees |
|---|---|---|---|
| **Clear Z1** | Z1 held after an early end or a restart (section 12) | Z1 clear for B | nothing |
| **Clear CLUSTER** | "release unconfirmed": the holder no longer lists the entry, but the link was broken (13.5) | CLUSTER free | nothing (the AGV already dropped it) |
| **Revoke CLUSTER** | The holder still lists `GRANTED`, or is `OFFLINE`, and the operator has checked on the floor that it is not inside the cluster. **An `OFFLINE` holder may be revoked only after it has been offline for more than 60 s, longer than a full crossing (review E).** The screen shows "offline for N s" | Sends `REVOKED` for the requestId (13.3 resend rule). With the holder `OFFLINE`: CLUSTER free at once. Otherwise: free when the AGV drops the entry | `REVOKED`, handled as in 13.7 |

Each action asks for confirmation: "checked on the floor". Each is logged.

### 13.9 Station restart (review C)

**What the station saves** in its state directory, as it does for calls, on every change:
- the CLUSTER holder, its requestId and the "release unconfirmed" flag;
- each Z1 hold that needs an operator, with its reason. The reason "orderId reset before ATT finished" is
  not visible in state again after a restart.

**At start-up**, before granting anything, it waits for a fresh state from each configured AGV, or for 3 s:

| Found | Station |
|---|---|
| An AGV lists `GRANTED` for CLUSTER | That AGV is the holder |
| The remembered holder no longer lists the entry | "Release unconfirmed" (13.5): operator |
| **Two AGVs list `GRANTED` at once** | **CRITICAL station alert**: send nothing to either AGV and grant nothing until an operator resolves it |
| A saved Z1 operator hold | Kept |

### 13.10 Roll-out with mixed contract versions (review D)

An AGV is **zone-capable** when its states carry the `zoneRequests` field, even if it is `[]`. A v1.5 AGV's
states have no such field.

**With two AGVs configured and one of them not zone-capable:**
- the zone-capable AGV's CLUSTER requests get `QUEUED`, and its orders are held, while the other AGV is
  `ONLINE` and **not idle at HOME**;
- "Idle at HOME" means: no active order, and `lastNodeId` is its home node. A `lastNodeId` of `""` after a
  restart does not count.
- Z1 works with both versions, because it reads only ATT action states.

The effect is one AGV on the floor at a time until both run v1.6. The owner may instead run one AGV at a time
by hand, which is the same rule.

### 13.11 Timing (for the screen and for planning)

All at 0.4 m/s, with a 5.4 m train (AGV 1.2 m, two 1.7 m trolleys, 0.4 m bars) and a 2 s horn.

| Move | Holds CLUSTER |
|---|---|
| Leaving ATT (BTU, MRU, ROW3, STU) | 39-42 s |
| Home-bound, up to parked at HOME | 36-37 s, plus the time to unhitch the trolleys |

## 10. Not implemented (additions)

From VDA5050 3.0.0, not used:
- the `zoneSet` topic and `downloadZoneSet`;
- the factsheet `supportedZones`;
- `leaseExpiry`;
- `REPLANNING` requests and trajectories;
- every zone type except RELEASE.

`zoneRequests` and `responses` follow the 3.0.0 schemas. The v1.5 row "`factsheet`, `visualization`, `zoneSet`, `responses` topics: not published, not subscribed" now reads: `responses` is subscribed by the AGV (section 1); `factsheet`, `visualization` and `zoneSet` remain unused.

## 11. Flagged for the owner (all decided 2026-11-24)

1. **Z1 for a stale, idle AGV: DECIDED, clear** (owner, 2026-11-24: "z1 clear when other agv is off"). This
   holds only with no order out to it (section 12, review B).
2. **The AGV Run page "release zone" (13.6): DECIDED, any operator** (owner, 2026-11-24). No PIN; the floor
   check stays in the confirmation text.
3. **The tie window (13.4): DECIDED, 1 s, home-bound first** (owner, 2026-11-24).
4. **Roll-out (13.10): DECIDED.** AGV 2 and the station are built and proven first. AGV 1 is the only item
   left after that (owner, 2026-11-24). Rule 13.10 stays as the safety net while AGV 1 is still on v1.5.
5. **Local trips (section 12, review F): DECIDED, as recommended** (owner, 2026-11-24). With `station.enabled` on, the AGV
   screen already takes no new calls (v1.2). So a local trip exists only on an AGV with the station off, which
   the station cannot tell from a switched-off AGV. The rule: at site 103, both AGVs run on the station, or
   only one AGV is in use at all. The screens show it:
   - the AGV screen, with the station off, shows a permanent banner: "Station off: this AGV is not
     traffic-controlled. The other AGV must not be running";
   - the station screen marks a configured AGV that is silent: "not connected: the station can't see it".
