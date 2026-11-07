# Position readiness: Home page At home, automatic confirm, recovery at home (2026-11-07)

Coding plan, built 2026-11-07. The owner's vehicle checks in section 12 are still to run. AGV-01, LINE mode, graph g6 on map rev2.

| Part | Today | After this |
|---|---|---|
| A. At home | On Mapping and Teach, followed by a separate Confirm | On the Home page, confirmed automatically after about 3 s of good evidence |
| B. Recovery at home | Once the monitor is `LOST`, only At home clears it, and the next station call is refused until then | Parked at HOME after a loop, the AGV re-seeds AMCL and confirms by itself |

No lidar view is added to Home, which has none today. Mapping keeps it for diagnosis. The monitor's code does not
change, so NAVIGATION is unaffected. Nothing new happens during a trip.

## 1. Operator flow

**Setting the position:**

1. Selector to MANUAL, with the AGV parked at HOME.
2. Press **At home** on the Home page.
3. Home shows `Checking position...`, then `Position OK` about 3 to 6 s later, with no second press.
4. Selector to AUTO.

If the check fails, Home says why and offers At home again.

**After a trip that lost the monitor:** nothing to do in the normal case. Once the AGV is parked at HOME, Home shows
`Position lost, rechecking at home`, then `Position OK`, and the next station call is accepted. If the check keeps
failing, Home says why, which also warns that the AGV thinks it's home but the scans disagree.

## 2. Evidence

### The person's check needs a replacement

`/amr/localization/confirm` is already refused unless `can_confirm` is true. That already means: state CHECKING,
fresh streams, AMCL covariance in limits, scan match at least 60 %, at most 15 % of beams through obstacles, all
stable for 2 s (`readiness.py`). Automatic confirm calls the same service, so it **loosens no thresholds**. What the
person added was catching a wrong position, so that was tested.

The live scan with the AGV parked at N2 was scored at other positions, using the monitor's own `compare()` and the
rev2 mask:

| Pose tested, relative to HOME-N2 | Match | Through obstacles | Scans alone would pass |
|---|---|---|---|
| At N2 | 92 % | 3.3 % | Yes |
| 0.25 to 1 m along the lane, either way | 70 to 97 % | 0.3 to 11.8 % | **Yes** |
| 2, 3 or 5 m along the lane, either way | 2 to 55 % | 3.2 to 23.7 % | No |
| 0.3 or 0.6 m to the side | 7 to 37 % | 14.6 to 44 % | No |
| The HOME-N lane, 1.3 m to the side | 19 % | 8.3 % | No |
| The other way round | 17 % | 4.2 % | No |
| 3 m along and 1.3 m to the side | 57 % | 0 % | No, but close to the 60 % limit |

Limits of this test: one parked position, one moment, no AMCL convergence simulated.

- A wrong lane or a position 2 m or more away is caught. The near-miss at 57 % is why AMCL's pose also has to stay
  near HOME.
- An error of up to 1 m along the lane is not caught. This is acceptable: stop tolerances are loose, and the first
  junction resync corrects S.
- 304 of the 575 endpoints within 10 m lie outside the dynamic areas, so the mask leaves enough to judge by.

### Recovery at home is likely to work

From the six most recent trip logs (three on 2026-11-06, three on 2026-11-07):

| Trip | Monitor went `LOST` | Monitor at the end | Match at the end, at home |
|---|---|---|---|
| 08:40 MRU3 | S 137.4, 16 % through obstacles | `LOST` | 95 % |
| 09:06 MRU2 | S 118.7, 16 % through obstacles | `LOST` | 96 % |
| The other four | Never | `READY` | |

Limits: these are the scan figures only. The re-seed and settling need testing on the vehicle.

`LOST` also happens while parked: at 09:05:55 AMCL corrected by 0.03 m and 6.1 degrees, over the 5 degree jump limit.
Part B covers that too. The limit itself is left alone.

## 3. Part A: the rule for an At home press

A new pure, clock-fed module, `amr_line/position_confirm.py`. An At home press arms it once. All of these must hold
together for `confirm_hold_s`:

| # | Condition | Source |
|---|---|---|
| 1 | Monitor is CHECKING and `can_confirm`, from a message received after the seed | `LocalizationState` |
| 2 | The job is IDLE or DONE, with no trip | `FollowJob` |
| 3 | The sensor sees the tape | `Inputs.sensor` `has_track` |
| 4 | The latest AMCL pose is within `confirm_max_offset_m` and 15 degrees of the taught HOME pose | `/amcl_pose`, the active graph |
| 5 | The wheels have not moved since the seed | `order.wheels_moved` |

Then it calls `/amr/localization/confirm` once, with no wait. The monitor checks again, so a change in between is
refused there and treated as a failure.

Rule 1 matters because `/amr/localization_state` is latched: a `can_confirm` from an earlier attempt must not
count. The monitor clears its evidence when the initial pose arrives, so a message from after the seed is clean.

Outcomes:

- **Confirmed:** a `LINE_LOC` event with the numbers, for example `position confirmed at home: match 94 %, through
  2 %, pose 0.13 m from HOME`.
- **Timed out:** after `confirm_timeout_s`, with the blocking condition as the reason. It stays CHECKING.
- **Cancelled:** by the wheels moving, Reset, or leaving the IDLE or DONE state.

A manual Confirm during the window just ends the wait. An At home press never retries by itself.

## 4. Part B: recovery at home

### When it starts

`position_confirm.py` starts a recovery when all of these hold together for `recover_settle_s`:

| # | Condition | Source |
|---|---|---|
| 1 | Monitor is LOST, or CHECKING after a failed recovery. UNLOCALIZED never starts one | `LocalizationState` |
| 2 | The job is IDLE or DONE, with no trip and no active order | `FollowJob` |
| 3 | The locator is running, not lost, within 0.5 m of HOME, with sigma in limits | `job._site_at_home(i.loc)` |
| 4 | The wheel baseline still holds: not moved since the last At home or arrival | `job._home_moved(i)` |
| 5 | The wheels are still | `Inputs.wheels_still` |
| 6 | The sensor sees the tape | `Inputs.sensor` `has_track` |
| 7 | No At home press is being checked | `position_confirm.py` |

A served trip ends in `DONE` with the locator at HOME, so this is how a finished loop is detected. The same rule also
covers a `LOST` while parked. No selector position is required, since nothing here moves the AGV.

### What it does

1. Publishes the taught HOME pose on `/initialpose`, which puts the monitor in CHECKING.
2. Applies the rule in section 3, with the same five conditions and the same timeout.
3. On a timeout, logs the reason and tries again after `recover_retry_s`, while the conditions in the table above
   still hold.

The event reads, for example, `position recovered at home: match 95 %, through 1 %, pose 0.08 m from HOME`.

### What it must not do

- **It does not call `tapeloc.at_home()`.** That wipes the locator, and the locator is the evidence that the AGV is
  home. Only the AMCL pose is re-seeded.
- **It does not call `job.at_home_pressed()`.** That records a person looking at the vehicle, and this isn't one. If
  the AGV was moved by hand, the baseline stays invalid, recovery won't start, and a person has to press At home.
- **It never starts after a service restart.** The monitor is UNLOCALIZED and the locator isn't running, so a person
  has to press At home. Each chain of trips still begins with a person.
- **It never starts after a wrong-branch verdict.** The locator counts as lost.

### What this gives up

- **Mid-trip protection stays as it is today.** After a mid-trip `LOST`, the pose-based wrong-branch check stays off
  until home. The wrong-lane and fork checks don't depend on the monitor, and those are what caught the wrong-lane
  runs.
- **No person checks the position between trips.** It relies on wheels, tape and the scan check.

### Scope

Part B needs `station.enabled`. Only station orders read the monitor's READY, and the job only keeps the wheel
baseline with calling on. A Start from the panel doesn't need READY, so with calling off nothing changes.

Station orders stay safe during a recovery: they are refused with `LOCALIZATION_NOT_READY` until the monitor is READY.

## 5. A bug to fix first

`_srv_at_home` has no job-state check. With calling on it only requires MANUAL, and with calling off nothing at all,
so At home during a held trip wipes the locator (`self.loc = self.shadow = None`). A button on Home makes that
easier to hit.

Fix: refuse At home unless the job is IDLE or DONE with no trip and the wheels are still. Refuse with a reason.

## 6. Design decisions

- **The rule runs in `line_follow_node`, not the monitor.** The monitor also serves NAVIGATION and knows nothing of
  HOME, tape or trips.
- **The monitor is unchanged.** It already goes from any state to CHECKING on `/initialpose`.
- **Every At home press uses Part A,** from Home, Mapping or Teach, because they share one service. A pose set by
  hand on Mapping still needs a person's Confirm.
- **No message change.** `LineState.home_detail` already exists and carries the status, so no `colcon build`.
- **Manual Confirm stays** on Mapping and Teach, for poses set by hand and for the switches being off. The monitor's
  reason still reads `operator confirmed scan alignment` after an automatic confirm. The `LINE_LOC` event records
  which it was.
- **At home keeps its current access.** No PIN, and with calling on the physical selector must be in MANUAL. A
  browser on a laptop can still press it, as on Teach today, but the AGV can't leave until someone turns the
  selector to AUTO.

## 7. Profile keys

In the `tape_loc` block, with schema, validation and a refusal test in `tests/test_config.py`:

| Key | Value | Validation | Meaning |
|---|---|---|---|
| `auto_confirm_home` | `true` | bool | `false` returns At home to today's manual flow |
| `auto_recover_home` | `true` | bool, needs `auto_confirm_home` | `false` keeps `LOST` until a person presses At home |
| `recover_settle_s` | `3.0` | 1 to 30 | Parked at HOME this long before a recovery starts |
| `recover_retry_s` | `60.0` | 30 to 600 | Between recovery attempts |
| `confirm_hold_s` | `1.0` | 0.5 to 5 | On top of the monitor's 2 s |
| `confirm_timeout_s` | `20.0` | 5 to 120 | Give up and say why |
| `confirm_max_offset_m` | `1.0` | 0.2 to 2 | AMCL pose against the taught HOME pose |

`EXPECTED_CHECKS` in `tests/run_all.py` changes with the new tests.

## 8. Home page

- `amr_web/alarms.py`: a pure `home_position(state)` returning the button's enabled state and reason, the status
  text and a level. `/api/alarms` carries it, so the page re-derives nothing.
- `home.html`: a position row in `home-act` with the At home button and status, posting `/api/line/at_home`. It
  shows only in LINE mode on a tracked profile.
- Styling in `amr.css`, reusing `.big` and the existing level classes. It must fit at UI scale `l` at 1280 x 720
  with no scrolling.

| Status | Shown when | Button |
|---|---|---|
| `Position not set` | UNLOCALIZED | Enabled in MANUAL, otherwise `turn the selector to MANUAL` |
| `Checking position...` | Armed by At home | Disabled |
| `Position OK` | READY, at home | Enabled, to set it again |
| `Position check failed: <reason>` | At home timed out or cancelled | Enabled in MANUAL |
| `Position lost, rechecking at home` | A recovery is running or waiting to retry | Enabled in MANUAL |
| `Position lost: <reason>` | LOST and recovery can't start, for example moved by hand | Enabled in MANUAL |
| `Away from home` | READY, not at home, with no trip | Disabled |
| `On a trip` | A trip is active, whatever the monitor says | Disabled |

## 9. Failure modes and recovery

| Failure | Result | Recovery |
|---|---|---|
| Too many unmapped trolleys, match under 60 % | Times out with the percentage. Recovery retries every 60 s | Clear them or add a dynamic area. A retry or At home then passes |
| AGV off the tape | Times out, or recovery won't start: `tape not seen` | Put it on the tape, press At home |
| AGV in the wrong lane | Times out on the scan or pose | Drive to HOME, press At home |
| AGV moved by hand after arriving | Recovery won't start, `NOT_AT_HOME` | Press At home |
| AGV moved during a check | Cancelled | At home again, or a person if the baseline is gone |
| Scans disagree at the end of a loop | Keeps retrying, next call refused, Home says why | Look at the AGV, press At home |
| Station PC sends a call during a check | Refused, `LOCALIZATION_NOT_READY` | The station sends it again |
| Monitor down | No message, so it times out | The supervisor's own recovery |
| Confirm service refuses or fails | Logged as a failure | Retry, or another At home press |
| Service restarted | Position not set, recovery never starts | At home |
| Web page closed mid-check | Nothing, because the node runs the check | Status shows on reopening |
| The rule misbehaves | Set the matching switch false and restart | Today's behaviour |

Nothing here commands motion. FX3 and STO, the selector, `gating.py` and the mux are untouched.

## 10. Work packages

| WP | Content | Files |
|---|---|---|
| 1 | At home guard (section 5) | `line_follow_node.py`, its tests |
| 2 | Pure rule, At home and recovery (sections 3 and 4) | new `amr_line/position_confirm.py`, new `test_position_confirm.py` |
| 3 | Profile keys (section 7) | `agv_core/config.py`, `profiles/agv-01.json`, `tests/test_config.py`, `tests/run_all.py` |
| 4 | Node wiring: arm, feed, seed, call confirm, `home_detail`, events | `line_follow_node.py`, a node test |
| 5 | Home page (section 8) | `amr_web/alarms.py`, `home.html`, `amr.css`, `test_operator_ux.py` |
| 6 | Docs | `amr_ws/RUNBOOK.md`, `manuals/tape-localization-runbook.md`, operator card |

Build in that order. WP 1 is worth having even if the rest waits.

## 11. Tests

`test_position_confirm.py`, pure.

At home:

- Confirms only after the hold, and only once.
- Never confirms without a press, however good the scans.
- A latched `can_confirm` from before the seed does not count.
- Each of the five conditions alone blocks it, and a dropout restarts the hold.
- Timeout reports the blocking condition, and nothing retries afterwards.
- Wheels moving, Reset and leaving IDLE or DONE each cancel it.

Recovery:

- Starts at the end of a served trip with the monitor LOST.
- Starts for a LOST while parked, with no selector requirement.
- Each of the seven conditions alone blocks the start.
- Never starts from UNLOCALIZED, with a wrong-branch verdict, with the baseline gone, or during a trip.
- Never starts with the monitor READY.
- Retries only after `recover_retry_s`, and stops when a condition fails.
- Never touches the locator or the wheel baseline. This pins "not a person's press".

Both:

- A refused confirm is a failure, and each switch off disables its trigger.

Others:

- At home is refused in RUNNING, ARMED, HOLD and FAULT, with a trip, and with wheels moving.
- A pose from Mapping is never auto-confirmed.
- A station order during a recovery is refused with `LOCALIZATION_NOT_READY`.
- `home_position()` for each row of the table in section 8.
- Home page renders the row, and a test pins that it has no scan view.
- Refusal tests for each profile key.

Run the focused files, `python3 tests/run_all.py`, and `ruff check` from both roots. One unified sim run at the end.

## 12. On the vehicle

All by the owner.

**At home, AGV idle:**

1. Parked at N2 with trolleys in place: press At home on Home. Expect `Position OK` in about 3 to 6 s.
2. Repeat 5 times, to see whether it's consistent.
3. Drive about 3 m along the lane and press At home. Expect a failure with a reason.
4. Park on the HOME-N lane and press At home. Expect a failure.
5. Press At home, then jog within the window. Expect it to cancel.

**Recovery, on normal trips:**

6. Run far trips until the monitor goes `LOST`, as it did on 2 of the last 6.
7. On arriving at HOME, expect `Position lost, rechecking at home`, then `Position OK`, with `position recovered at
   home` in the log.
8. Confirm the next station call is accepted with nobody touching the HMI.
9. Jog the AGV after a trip that lost the monitor. Expect recovery not to start, and `NOT_AT_HOME` until At home.

The events and trip log give the numbers, and a step the operator saw pass counts as passed.
