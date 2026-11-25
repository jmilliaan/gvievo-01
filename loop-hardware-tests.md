# Loop site: real-hardware test list

Status: written 2026-11-25. **No test here has been run yet.** It tests the loop site of commit
`04e7dc2` (branch `gvievo-ce`): one closed tape loop, no junction, no U-turn, no MLS marker; each
Start at HOME drives one lap and stops at HOME.

Read with: `manuals/loop-track-plan.md` (design, as built) and
`manuals/tape-localization-runbook.md` section 6A (the operating steps).

Roles: **A** = the coding agent on the vehicle PC (terminal only), **E** = engineer, **O** =
operator at the vehicle with the E-stop in reach.

## 0. Rules for the coding agent

- **Part 1 is yours.** Nothing in it moves a wheel. Run it top to bottom and record every result.
- **Part 2 is the people's.** You run only the commands a step gives you (logs, service calls
  that move nothing) and record what E and O report. You never move the vehicle.
- Results go in a copy of the table in section 3: `~/.amr/runs/loop-hw-<date>.md`. Do not edit
  this file on the vehicle.

**STOP and call the engineer** when:
- a check fails, or fails again after one redo;
- a step needs `amr.service` restarted: only on O's go, said in this session;
- a step needs a profile change (`profiles/*.json`): E decides, and says the value;
- output shows `ERROR`, `Traceback` or `FAIL` that the step does not say is expected.

**NEVER:**
- run any command with `--go`, or any `set-*` bench command;
- edit `agv_core/`, `amr_ws/src/`, `missions/` or `amr_ws/deploy/`;
- delete anything under `~/.amr` or `~/amr_maps`;
- `git commit`, `git push`, `git reset`, `git clean`.

Logs, for every part:

```bash
journalctl -u amr.service -b --no-pager | tail -200        # the service
journalctl -u amr.service -b --no-pager | grep -E "LINE_MISSION|LINE_LOC|end lap|loop" | tail -100
```

## Part 1 — agent alone, nothing moves

| # | Check | Command | Pass |
|---|---|---|---|
| 1.1 | The code is the loop commit or later | `cd ~/agv_can && git log --oneline -3 && git status --short` | `04e7dc2` in the history; no modified tracked files |
| 1.2 | Build | `source ~/.bashrc && cd ~/agv_can/amr_ws && colcon build --symlink-install && source install/setup.bash` | `Summary: N packages finished`, no `failed` |
| 1.3 | Root offline suite | `cd ~/agv_can && python3 tests/run_all.py` | ends with every check passed and the count equal to `EXPECTED_CHECKS` |
| 1.4 | The loop tests | `cd ~/agv_can && python3 -m pytest -q amr_ws/src/amr_line/test/test_loop_track.py` | `21 passed`. `test_the_runtime_teaches_a_loop_and_shadows_it_lap_after_lap` was **never run unpatched** before: it uses the real file system here |
| 1.5 | End lap on the web | `cd ~/agv_can/amr_ws && python3 -m pytest -q src/amr_web/test/test_server.py src/amr_web/test/test_teach_page.py` | all pass, including `test_guided_end_lap_needs_the_engineer` |
| 1.6 | Every package suite | `cd ~/agv_can/amr_ws && env AMR_SIM_TESTS=0 ROS_DOMAIN_ID=89 python3 -m pytest -q src/*/test` | all pass. Record any failure with its name: it may predate the loop work |
| 1.7 | Lint | `ruff check ~/agv_can/agv_core ~/agv_can/tests && (cd ~/agv_can/amr_ws && ruff check src)` | no findings |
| 1.8 | The loop files load | `cd ~/agv_can && python3 -c "from agv_core import mission as m; s=m.load_site('loop-site'); g=m.load('c-loop-guided'); print(m.is_loop(s), list(s['CIRCUITS']), s['CIRCUITS']['C-LOOP']['legs'][0]['id'], g['GUIDED'])"` | `True ['C-LOOP'] HOME:loop>HOME {... 'end_stop_m': 0.5}` |
| 1.9 | Which mission the profile names | `cd ~/agv_can && python3 -c "from agv_core import config as c; print(c.TAPE_LOC_SITE_MISSION, c.TAPE_LOC_SHADOW_CIRCUIT, c.TAPE_LOC_LIVE, c.STATION_ENABLED)"` | record it. Expected before step 2.0: `site-103 C-MRU False False` |
| 1.10 | The service runs this build | `systemctl show amr.service -p ActiveEnterTimestamp` against the build time of 1.2 | started after the build. If not: **STOP**, a restart needs O's go |
| 1.11 | End lap service exists, refuses while idle | service up, selector MANUAL, vehicle standing: `ros2 service call /amr/line/end/here std_srvs/srv/Trigger` | `success=False`, message `End lap only while a guided run is running` (or `no mission loaded`). Nothing moves |

Part 1 passes when 1.1–1.8 and 1.10–1.11 pass. Hand the results to E before Part 2.

## Part 2 — at the vehicle (E and O drive, A supports)

Empty, no trolleys. O keeps the E-stop in reach for every step marked "moves".

| # | Moves | Who | Do | Pass |
|---|---|---|---|---|
| 2.0 | No | E, A | E decides the profile change. A edits `profiles/<unit>.json` → `tape_loc.site_mission: "loop-site"`, `shadow_circuit: "C-LOOP"`, `live: false`; `station.enabled` stays false. Restart `amr.service` on O's go. A: rerun 1.9 | `loop-site C-LOOP False False`. Teach page names `loop-site`; Run → Calls says "A loop: no calls, no trolleys…", no Trolleys-off buttons |
| 2.1 | Yes | O, E | **Corner check, before anything is taught.** Run page → mission `c-loop-guided`. AGV on the tape at the HOME arrow. AUTO → Start. Walk one full lap beside it. Past the arrow: E presses **End lap** (Teach page or E key) | Every corner taken with no FAULT. A: list the `corner:` / `kink:` events from the log. A corner that FAULTs ("no tape within 75 deg") = **STOP**: the tape layout needs a radius, not a code change |
| 2.2 | Yes | O, E | End lap again, on a second lap, at a straight | stops within ~0.5 m of the press, run DONE ("run complete"); a second Start begins a new run |
| 2.3 | Yes | E, O | Survey (`amr_ws/RUNBOOK.md` §2.A): floor arrow at HOME, preset moves, both directions, back to the arrow, **Returned to start** | closure a few cm and ≤ 2°. A: record `dx dy dyaw` and the saved revision `rev N` |
| 2.4 | No | E, A | Dynamic areas if wanted: `ros2 run amr_mission map_edit --map <id> --rev <N> --dynamic-rect …` | a new revision. Teach on the newest one only |
| 2.5 | No | E | Teach → map, rev → **Select map** → Restart tape layer. AGV on the arrow: initial pose by hand (first time) → **Scans align** | Readiness READY. Teach Status: "teaching on <map> rev<N>: no graph active" |
| 2.6 | Yes | E, O | **Three passes.** Circuit `C-LOOP` → **Record pass** → AUTO + Start on `c-loop-guided` → past the arrow **End lap** → **Stop pass**. Start passes 2 and 3 where the last one stopped (no jog back) | each Stop pass: `pass … saved: … ; loop closed, <L> m`, L the same within ~0.2 m each time. A: record the three L |
| 2.7 | Yes | E, O | **A refused pass** (optional): Record pass, End lap ~2 m **before** the arrow, Stop pass. Then Teach → delete that pass (`pass_delete <name>`) | `saved but it does NOT match yet: … ended … m from where it started` |
| 2.8 | No | E | **Build** | one leg `HOME:loop>HOME`, 3 passes, spread ≤ 0.050 m, no `REFUSED`. A: record length and spread |
| 2.9 | Yes, then still | O, E | Jog onto the arrow, drive the last metre forward onto it, hold still 3 s. Station `HOME` → **Teach here** → **Build** | `HOME taught on HOME:loop>HOME at s …` (expected near 0), `every circuit compiles` |
| 2.10 | No | E | High-speed areas if wanted (`/tape-areas`), only on straights, ending ≥ 2 m before HOME. **Publish** → **Make active** → Restart tape layer | Status names the graph; Locator tile IDLE |
| 2.11 | Yes | E, O | **Five shadow laps**, `c-loop-guided`, End lap after the arrow each time. Someone stands at the arrow and calls out when the AGV's sensor passes it | each lap: `shadow: lap complete`, one `stop HOME` decision ending `ok`; no `would HOLD`, no `LOST`, no `fork with no taught junction`; Locator HEALTHY all lap, including across HOME. A: record sigma at each lap end |
| 2.12 | No | E, A | E decides `tape_loc.live: true`. A edits it; restart on O's go | Run page lists `loop-site` with "a loop: each Start at HOME drives one lap" |
| 2.13 | No | O, E | At home (automatic with `auto_confirm_home`, else by hand) | Localisation READY |
| 2.14 | Yes | O | **Live lap.** Selector AUTO → Start at HOME | 2 s horn, one lap at the cruise (0.5 m/s), HIGH only inside drawn areas, stops at HOME, run DONE "lap of C-LOOP: back at HOME". **Measure the stop against the arrow** (tape measure, along the tape): target ±10 cm |
| 2.15 | Yes | O | Start again at HOME, four more laps, no At home in between | each a full lap, each stop measured. A: record the five errors; pass if all within ±10 cm and none drifts lap after lap |
| 2.16 | Yes, then no | O | Jog the AGV 1 m along the tape from HOME, selector AUTO, Start | refused, `not at HOME (+1.0 m from it)`. Nothing moves |
| 2.17 | Yes | O | Lap with a person stepping into the protective field mid-straight, then out | protective stop, resumes by itself when clear, lap ends at HOME as usual |
| 2.18 | Yes | O, E | Lap with the E-stop pressed mid-lap; release, Reset, Start (`amr_ws/RUNBOOK.md` §4) | record exactly what happens: the lap goes on to HOME, or is ended with a message. It must never drive on by itself after the release |
| 2.19 | No | E | Rollback rehearsal (optional): `tape_loc.live: false`, restart on O's go | Start at HOME no longer drives a lap; the taught graph stays in `~/amr_maps` |

Part 2 passes when 2.0–2.6, 2.8–2.9, 2.11–2.18 pass; 2.4, 2.7, 2.10 and 2.19 only if done.

## 3. Results (copy to `~/.amr/runs/loop-hw-<date>.md`)

| # | Date / time | Result (PASS / FAIL / N/A) | Values (lengths, errors, sigma, messages) | Who |
|---|---|---|---|---|
| 1.1 | | | | |
| 1.2 | | | | |
| 1.3 | | | | |
| 1.4 | | | | |
| 1.5 | | | | |
| 1.6 | | | | |
| 1.7 | | | | |
| 1.8 | | | | |
| 1.9 | | | | |
| 1.10 | | | | |
| 1.11 | | | | |
| 2.0 | | | | |
| 2.1 | | | | |
| 2.2 | | | | |
| 2.3 | | | | |
| 2.4 | | | | |
| 2.5 | | | | |
| 2.6 | | | | |
| 2.7 | | | | |
| 2.8 | | | | |
| 2.9 | | | | |
| 2.10 | | | | |
| 2.11 | | | | |
| 2.12 | | | | |
| 2.13 | | | | |
| 2.14 | | | | |
| 2.15 | | | | |
| 2.16 | | | | |
| 2.17 | | | | |
| 2.18 | | | | |
| 2.19 | | | | |

## 4. What to send back

The results file, the log lines of 2.1, 2.6, 2.8, 2.11 and 2.14–2.15, and the five HOME stop
errors. A failure: the step, the exact message, and `journalctl -u amr.service -b` around it.
