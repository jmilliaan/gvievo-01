# Code review — `gy-demo` vs `refactor02`

**Repo:** `jmilliaan/gvievo-01`
**Under review:** `origin/gy-demo` @ `85f1bab` ("gpt6 updates for gy demo")
**Baseline:** `origin/refactor02` @ `7950936` — the last branch validated on hardware
**Relationship:** `gy-demo` is `refactor02` plus exactly one commit. Merge base is `refactor02`'s HEAD. Revert is trivial.
**Reviewed against:** the agreed 7-point route/direction/high-speed implementation plan.
**Status of the code:** never run on the vehicle.

Reproduce the review environment: `pip install python-can flask`, then `python3 tests/run_all.py` from the repo root.

---

## 1. Verdict

The implementation is structurally sound and unusually well tested for an unverified agent commit. All seven plan items are present. The route core is pure, the encounter model is correct, config validation is strict, and the speed ramp defers properly to the slow zone, the startup ramp, the measured stop and the hard stop.

It is **not ready for a hardware trial as delivered.** Four items block:

- The test suite exits non-zero.
- The README's safety model was deleted.
- A missed station tag is undetectable and silent.
- Nothing prevents the vehicle from arriving at a station at 2000 rpm.

Fix those four, address the high-severity items, and this is a good branch.

---

## 2. Plan coverage

| # | Plan item | Status | Note |
|---|---|---|---|
| 1 | `core/route.py`; stations and order in profile data | Done | Pure computation, no clocks or IO, owned by the CAN thread |
| 2 | Deliberate transitions; cancelled Start does not advance; startup parked at point 2 outbound | Done | First Start departs point 2 without needing another read of its tag |
| 3 | Encounter detection replacing global `ignore_t` suppression | Done | Two independent guards, stronger than asked. See H3 |
| 4 | Direction-qualified high-speed latch, reused tag pair, priority order | Done | Latch cleared on arrival, hold, disarm, direction change |
| 5 | 500 rpm/s transition inside the existing jerk-limited ramp | Done | No second ramp added; startup and measured stop keep their own rates |
| 6 | Recovery matrix | Mostly | Reconnect row is under-specified in effect. See H2 |
| 7 | Files, validation, tests, README | Partial | README regressed (B2); check count not updated (B1) |

---

## 3. Blocking findings

### B1 — Test suite exits 1

`tests/run_all.py:40` still reads `EXPECTED_CHECKS = 1085`. The branch now runs 1190 checks across 107 test functions. Every individual check passes; the only failure is the meta-assertion that guards against a module silently going missing.

Baseline for comparison: `refactor02` runs 101 functions / 1085 checks and exits 0.

The project's own convention (`tests/run_all.py:12`) says to raise this deliberately when checks are added. The agent added `test_route.py` and registered it in `MODULES` but never raised the counter.

**Fix:** set `EXPECTED_CHECKS = 1190`. Re-verify the count after any further test changes in this review.

---

### B2 — README gutted: 617 → 326 lines

The README was replaced rather than extended. Sections deleted outright:

| Deleted section | What it held |
|---|---|
| `## ⚠️ Safety model` | No authentication on port 5000; arm preflight; manual direction is held not latched (`manual_watchdog_s`); auto heartbeat is opt-in via `window.CLAIM_HEARTBEAT`; **`dry_run` does not free the motors** and the instruction to check error sign with a magnet under a stationary vehicle |
| `## Invariants` | The design rules a future change must not break |
| `## Known gaps` | Honest limitations list |
| `### Guards on the tick` | Why each guard exists |
| `### Saturation and the inner wheel` | Control behaviour at limits |
| `### Drive monitoring`, `### What the vehicle may write over CAN` | Drive interaction boundary |
| `### The control law`, `## Curve capability`, `## Layout`, `## Testing` | Derivations and structure |

The plan said "document the settled behavior and profile format." It did not authorise removing the safety model from a document that accompanies a 150 kg vehicle.

The same deletion happened in `config.py`: the long `stop_until_start_button.*` tuning note — including the arithmetic showing what a blind window costs in metres — was replaced with five lines. Some of that is correctly obsolete (`ignore_t` is gone), but the distance-vs-time reasoning for `stop_distance_m` is still live and was cut with it.

**Fix:** restore `refactor02`'s README wholesale, then append the new sections (`Route and station identity`, `State across interruptions`, `Repeated RFID reads`, `High-speed zones and control`). Do not merge by rewriting. In `config.py`, keep the new direction-qualified text but restore the "distance, not time" paragraph and the note that station tags belong on track that has been straight for a metre or so.

---

### B3 — A missed station tag is undetectable and silent

**Location:** `core/route.py:51`

Arrival is decided by tag value alone. The direction term in that condition is a tautology and can never reject anything:

- `depart()` (`core/route.py:40`) always assigns `self.direction = self.next.direction`.
- `encounter()` returns early whenever `parked` is true.
- Therefore, at every point where the condition is evaluated, `self.direction == self.next.direction` is true by construction.

The comparison reads like a guard against wrong-direction reads. It is not one. Direction is derived from the route's own bookkeeping, never from the physical world, so it cannot detect that the bookkeeping has drifted.

**Consequence.** Suppose station 3's `0010` is missed. The vehicle continues; `0011` at station 4 and `0011` at station 1 both fail the `next.tag` match and are discarded; then station 2's `0010` matches and is recorded as "arrived at 3". The route is now one leg out of phase. From there:

- Stops happen at the wrong physical points.
- `laps` is wrong.
- `high_speed_to_next` permission is attached to the wrong physical legs. A phase error in the other direction (missing station 1) enables high speed on a leg that ends in a U-turn.
- Because the tag pattern (`0010, 0010, 0011, 0011`) has the same period as the route, the phase error sometimes self-corrects after a lap or two. That makes it *intermittent*, which is worse for diagnosis, not better.

Nothing logs, warns or faults at any point.

**Fix.** Gate arrivals on plausible travelled distance. The follower already integrates distance (`_track_gap_m` and the measured-stop path use it), so the vehicle knows roughly how far it has gone since departure. Add per-leg minimum and maximum travel to the route rows, and in the controller:

- Reject an arrival-matching tag read below the minimum — it is the departed tag or a spurious read.
- Fault the run when the maximum is exceeded without an arrival, with a message naming the expected station. That converts a silent phase error into a stop the operator can act on.

If per-leg distances are too much for this pass, a single global minimum-travel-before-arrival value is a large improvement over nothing and is cheap.

Separately: either delete the direction term at `core/route.py:51` or make it meaningful. Leaving a tautology that looks like a safety check is worse than having no check, because the next reader will trust it.

---

### B4 — Nothing prevents arriving at a station at high speed

**Location:** `canworker.py:1427`, `profiles/agv-01.json` `stop_until_start_button`

`stop_distance_m` is fixed at 0.4 m and is qualified by direction and tag but **not by speed mode**. The arithmetic:

| Approach | Speed | Deceleration into 0.4 m | Equivalent rate |
|---|---|---|---|
| Normal, 1000 rpm | 0.314 m/s | 0.123 m/s² | ~790 rpm/s |
| High, 2000 rpm | 0.628 m/s | **0.494 m/s²** | ~1570 rpm/s |

Four times the deceleration, on a tow tractor with trailers. The drive can execute it — `6084h` is 3200 rpm/s — so there is no fault, just a much harsher stop than the one validated on hardware, and a stopping point that will overshoot if the trailers push.

This is reachable by design, not only by fault: **both high-speed legs (2→3 and 4→1) terminate at stations.** One missed `0021`/`0020` exit tag puts the vehicle into a station at full speed. `route.encounter()` clears the latch on arrival, but by then the deceleration has already been computed from the actual speed.

Geometry the exit tags must satisfy: high→normal takes 2.0 s at 500 rpm/s, covering **0.94 m**. So an exit tag needs roughly 1 m of margin *before* the point where normal speed is required, plus the 0.4 m station stop on top.

**Fix — do at least one, preferably both:**

1. **Distance failsafe on the latch.** After N metres in high speed with no exit tag, drop to normal and emit a warning. N is a profile value; derive a starting point from the measured length of each blue segment plus margin. This makes a missed exit tag a logged degradation instead of a hazard.
2. **Speed-qualified stop distance.** Add a second stop distance used when the latch is set on approach, or validate at load time that `stop_distance_m` yields an acceptable deceleration at `auto_rpm_high`, not just at `auto_rpm`.

Also add a load-time check that any route row with `high_speed_to_next` true has an exit rule for the direction of that leg — currently only the *entry* side is validated (`config.py` `_read_route`, the final loop checks a rule exists for the direction, not that both contacts are usable on that leg).

---

## 4. High-severity findings

### H1 — Suppressed tags no longer reach the branch ladder

**Location:** `canworker.py:1013` and `canworker.py:1019`

`refactor02` suppressed the *stop*, never the *read*, and said why in a comment the rewrite deleted: a window that exists to stop a station re-triggering has no business deciding which way the vehicle steers on the way out of it.

In `_scan_route`, both `continue` paths drop the tag before it is appended to `tags`, and `tags` is what feeds `_branch_scan` at `canworker.py:1044`. So a branch entry or exit tag read during a hold, or while the departed-tag suppression is active, never reaches the ladder.

`branch_latch` is `[]` in `agv-01.json`, so there is no impact today. The slow-zone latch runs on the same ladder, so this regression surfaces the moment a junction or slow zone is configured — and it will present as a diverter that intermittently fails to latch, which is a bad thing to debug in a factory.

**Fix:** append every consumed encounter to `tags` and let `_branch_scan` see it. Apply the suppression only to the route decision and `_begin_station_stop`.

---

### H2 — RFID reconnect can silently skip a station

**Location:** `drivers/rfid.py:352-353`, `drivers/rfid.py:382`, `canworker.py` `_scan_route` generation check

Two mechanisms combine:

- `_rebaseline` swallows the first tag read after a reconnect, and sets `_encounter_tag`/`_encounter_at` from it — so repeats of that same value within `tag_clear_s` are suppressed too.
- `_scan_route` discards the entire pending batch when `generation` changes.

Both are individually correct and match the plan's rule that disconnection is not proof of departure. The combined effect is that a reconnect landing on a station tag drops that arrival with **no warning event and no hold**. At 0.63 m/s the vehicle keeps going, and the route is now in the B3 phase-error state.

**Fix:** on reconnect while `_auto_running`, emit a warn naming the risk ("RFID link re-established mid-run; a station may have been missed"). Consider holding the run until the next confirmed encounter. At minimum this must not be silent — an operator watching the AGV drive past a station needs to be able to tell that from a tag that failed to read.

---

### H3 — `tag_clear_s = 0.5` is provisional and is now load-bearing

**Location:** `profiles/agv-01.json:83`

The design here is good: two independent guards, not one.

1. `drivers/rfid.py:356` — a same-valued tag becomes a new encounter only after `tag_clear_s` with no read.
2. `canworker.py` `_departure_tag` — holds suppression of the departed tag's value until the reader has been silent for `tag_clear_s`, and releases early on any different tag.

That correctly satisfies the plan's requirement that suppression must not be keyed permanently by value, so point 2 cannot suppress point 3.

But `tag_clear_s` is the only thing separating stations that share a value, and 0.5 s is an untested placeholder. At normal speed it corresponds to **0.157 m of travel**; at high speed, 0.314 m. That is comparable to the reader's field width, which is the parameter it has to outlast.

**Fix (commissioning, not code):** before the first lap, measure on the actual reader —

- the maximum gap between consecutive reads of a stationary tag in the field;
- the physical length of the field along the direction of travel;
- both at 1000 and at 2000 rpm.

`tag_clear_s` must sit comfortably above the first and correspond to a travel distance comfortably above the second. Record the measured values in the README section that replaces the deleted tuning note. If this number is wrong, the symptom is the AGV parking twice at the same station, or departing and immediately re-parking — the exact failure `ignore_t` existed to prevent.

---

## 5. Minor findings

| # | Finding | Location | Suggested action |
|---|---|---|---|
| M1 | Undefended dict lookup on the 50 Hz path. Config validation currently guarantees the key exists, but a `KeyError` here would surface as a thread death rather than a fault. | `canworker.py:1427` | Use a lookup that faults cleanly with a message naming the direction and tag |
| M2 | `running` is read under the lock, then re-read unlocked three lines later because `_scan_route` can end the run. Correct, but it shadows the earlier value with no explanation. | `canworker.py:1042` | Add a one-line comment, or rename |
| M3 | The `_run_autopilot` early return gained an `age <= SENSOR_TIMEOUT_S` term. This is a genuine behaviour change to the sensor-loss path on a hardware-validated branch, and it was not in the plan. Covered only by `test_stale_sensor_at_high_speed`. | `canworker.py:1060` | Keep it — it looks like a real fix — but bench-verify the sensor-silence path separately before the route trial, and document it in the README |
| M4 | `_scan_route` emits events (`canworker.py:1028`, plus `_end_auto_run`/`_set_fault` on overrun) from inside the 50 Hz path. `refactor02` had an explicit rule that `_run_autopilot`'s body contains no events call, pinned by `test_logging`. The new emits are edge-driven so the ring buffer should survive, but the rule is now bent. | `canworker.py:1028` | Confirm `test_logging` still enforces what it was written to enforce, or update it deliberately |
| M5 | Test doubles in `test_panel.py` and `test_branch.py` now call `super().__init__()`, building a real `Controller` inside what were deliberately lightweight fakes. Passes, but the fakes are heavier and harder to reason about. | `tests/test_panel.py:142`, `tests/test_branch.py:411` | Acceptable; consider a dedicated route-injection hook instead |
| M6 | `auto.html` / `auto.js` operator text changed from "press Reset to arm, Start to run" to "press Start to arm and run". This is **correct** against `_panel_start` (which arms), so `refactor02`'s text was stale — but it is unrequested scope on a safety-relevant operator instruction. | `app/templates/auto.html:14`, `app/static/auto.js:3` | Keep, but verify against the physical panel labelling before the trial |

---

## 6. Test gaps

`tests/test_route.py` is good work: two full laps, both blue segments in both directions, cancelled Start, line-loss hold, disarm and restart continuity, interrupted speed ramps, encounter batching, reconnect baseline, sequence overrun. Keep all of it.

Missing cases, each corresponding to a finding above:

| Case | Covers | Expected behaviour after fix |
|---|---|---|
| Station tag missed; subsequent same-value tag read | B3 | Rejected on travel distance, or run faulted — not recorded as an arrival |
| Arrival at a station with the high-speed latch still set | B4 | Latch dropped by distance failsafe before arrival, or a speed-appropriate stop distance used |
| Branch/slow entry tag read during a hold, and during departed-tag suppression | H1 | Tag still reaches `_branch_scan`; only the route decision is suppressed |
| Reconnect whose first read is the next station's tag | H2 | Warning emitted; arrival not silently lost |
| Two encounters of the same value separated by less than `tag_clear_s` while moving | H3 | Single encounter |

---

## 7. Do not change

Listed so this review is not read as licence to rewrite working parts.

- The pure, IO-free design of `core/route.py` and the rule that all route decisions happen on the CAN thread from one frozen RFID batch per scan. This was the right call and the tests depend on it.
- The ordered encounter sequence with the gap check that **faults instead of guessing position** (`canworker.py` `_scan_route`). Faulting is correct here; do not soften it to a recovery heuristic.
- The two-layer departure suppression described in H3. It is stronger than the plan required. The problem is the *value* of `tag_clear_s`, not the mechanism.
- Config validation in `_read_route` and `_read_stop_tags`: route ↔ stop-rule cross-checks, tag-type exclusivity, rejection of legacy `ignore_t`, `auto_rpm_high` bounds, `speed_switch` rate ceiling against `ramp_accel_rpm_s`.
- The speed-selection priority in `core/autopilot.py`: slow zone overrides high, startup keeps the ordinary ramp below `auto_rpm`, the measured stop keeps its own derived rate, hard stop bypasses everything.
- `route.encounter()` clearing the latch on any encounter during a non-high-speed leg. That is a useful belt-and-braces behaviour.

---

## 8. Fix order

**Before any hardware trial:**

1. B2 — restore `refactor02`'s README, then append. Restore the `config.py` distance-vs-time note.
2. B1 — `EXPECTED_CHECKS = 1190` (re-count after the other fixes).
3. B3 — travel-distance gate on arrivals; remove or repair the tautological direction check.
4. B4 — distance failsafe on the high-speed latch, and/or speed-qualified stop distance.
5. H2 — warn on mid-run RFID reconnect.
6. H1 — restore tag delivery to the branch ladder.

**During commissioning, before the first full lap:**

7. H3 — measure reader field length and read-gap distribution at 1000 and 2000 rpm; set `tag_clear_s` from data and record the measurements.
8. Confirm exit-tag placement gives ≥1 m of margin for the 0.94 m high→normal transition, plus the 0.4 m station stop.
9. M3 — bench-verify the sensor-silence path.
10. M6 — verify the panel text against the physical labels.

**Acceptance for this branch:** `python3 tests/run_all.py` exits 0; the five test cases in section 6 exist and pass; the README contains the safety model plus the new route sections; and a deliberately covered station tag produces a fault or a rejected arrival rather than a silent phase error.
