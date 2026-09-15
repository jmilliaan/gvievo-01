# N01 - Dry-run gate: PASS

Revision 534e58d / profile agv-01 / mission gy-demo. 2026-09-15 15:34 WIB.

## Procedure as run
Selector AUTO, disarmed. The service had been stopped by the operator at
15:32:46, so the "restart" was a clean start of a new process (PID 17922,
15:34:02) rather than `/api/restart`. Equivalent, and it avoided energising the
drives in between.

`autopilot.dry_run` set `false` -> `true` in `profiles/agv-01.json`.

## Criteria

| Criterion | Observed | Verdict |
|---|---|---|
| `/params` shows `dry_run` true | `dry_run | config.DRY_RUN | true` | PASS |
| `/api/config` shows `dry_run` true | `autopilot.dry_run: true` | PASS |
| profile `agv-01` | `profile: agv-01`, `profile_path: .../profiles/agv-01.json` | PASS |
| intended mission | `mission: gy-demo`, `mission_path: .../missions/gy-demo.json` | PASS |
| before/after copies differ only in `dry_run` | `diff` = one hunk, line 14 only | PASS |

Evidence: `N01-profile-BEFORE.json`, `N01-profile-AFTER.json`,
`N01-api-config-AFTER.json`, `N01-params.html`, `N01-api-state-AFTER.json`,
`N01-api-events.json`, `statepoll.jsonl`.

## This case also closed finding F1

The pre-restart `/api/config` had **no** `mission` / `mission_path` keys and
reported `speed_switch_accel_decel_s: 2.0` / `speed_switch_rpm_s: 500.0`.
After the restart both keys are present and the values are `3.0` / `333.33`,
matching `missions/gy-demo.json` and the handoff's "about 333 rpm/s".
The live service is now on the checked-out revision 534e58d.
