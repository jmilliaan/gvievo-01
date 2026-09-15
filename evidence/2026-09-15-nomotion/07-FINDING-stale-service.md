# Finding F1: the running service is NOT on the checked-out revision

Recorded 2026-09-15 ~15:27 WIB, before any case was run.

## Evidence

| Fact | Value |
|---|---|
| Checked-out HEAD (disk) | `534e58d` on branch `gy-demo`, working tree clean |
| Service PID / start time | 892, started 2026-09-15 15:01:51 WIB |
| Working tree checkout time | 2026-09-15 15:17:43 WIB (`git reflog`: reset to origin/gy-demo 15:17:03, checkout 15:17:43) |
| HEAD at service start | `fe1cf74` ("tests") |
| Diff fe1cf74 -> 534e58d | 40 files, +4792 / -303 lines |

The running process therefore holds `fe1cf74` code in memory. That revision has
**no `missions/` directory at all**, no `core/uturn.py`, no `core/blindrun.py`,
no `core/manualturn.py` and no `/blind` page.

## Independent confirmations

1. `app/server.py:421-422` (checked out) puts `"mission"` and `"mission_path"`
   into the `/api/config` payload. The live `/api/config`
   (`03-api-config-baseline.json`) contains **neither key**.
2. Live `/api/config` reports `speed_switch_accel_decel_s: 2.0` and
   `speed_switch_rpm_s: 500.0`. The checked-out `missions/gy-demo.json` sets
   `speed.speed_switch_accel_decel_s: 3.0` (~333 rpm/s, per handoff section 1).
   The live value comes from the old monolithic profile.

## Consequence

Nothing observed from this process describes the software under test. Every
Phase N case depends on the new code (the dry-run `_eto_scan` fix, the mission
split, the U-turn, `/blind`). The service must be restarted onto `534e58d`
before any case is run.

The remedy is inside the session: N01 sets `autopilot.dry_run: true` and
restarts. `/api/restart` refuses while armed, so the selector must go to AUTO
(disarming) first.

## Second observation at session start

`/api/state` at baseline: `armed: true`, `mode: "manual"`, both drives
**Operation enabled**, `target` 0/0, both `rpm` 0, `speed_zero` true.
The vehicle has been armed in MANUAL with the drives energised since
15:01:54 (events seq 12-14). This is an allowed state, but while the selector
is in MANUAL an arrow key on `/manual` would jog the wheels.
