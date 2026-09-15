# Prompt: no-motion hardware session

Paste everything below the line into a new coding-agent session on the
vehicle's computer.

---

You are working in the AGV line-following controller repository on the vehicle's
own computer. Hardware is connected. This is a fresh session with no prior
context: build it from the repository, not from assumptions.

## This session: no motion

**The motors must not turn at any point in this session.** Arming and disarming
are allowed.

Your job is to run the no-motion hardware session:
- exercise, on the real hardware, everything that does not need a wheel to turn
- collect evidence
- report honestly

You are not here to make tests pass. Nothing you observe in this session passes
a case that needs motion.

## What this system is

Python controller (Flask HMI + dedicated threads) for a differential-drive tow AGV:
- two Oriental Motor BLV-R drives and a SICK MLS magnetic line sensor on 125 kbps
  CANopen (nodes 1 left, 2 right, 10 MLS)
- Chafon RFID reader; Modbus DIO for the physical panel (Start, Reset, AUTO/MANUAL
  selector)
- SICK nanoScan3 lidar data (diagnostic only; the hardware safety chain is separate)

It runs as the systemd service `agv_controller.service`.

Tested offline only, never on hardware:
- direction-aware route
- high-speed zones
- route guards (disabled in the shipped mission)
- the Auto page summary
- differential U-turns (tags `0030` cw / `0031` ccw, replacing the balloon loops)
- `/blind`: encoder-only test moves, a 90°/180° U-turn set from the page, and an
  MLS IMU display
- configuration split into a vehicle profile and a mission file
- the dry-run fix: a dry-run AUTO run no longer treats its de-energised drives as
  a safety-chain stop and no longer re-enables them

## Read these first, in this order

1. `manuals/today_priority/hardware-test-runsheet.md`: "Pick the session type
   first", then "No-motion session" (prerequisites, order, closing state).
2. `manuals/today_priority/route-hardware-acceptance.md`:
   - section 4, preparation and evidence
   - Phase N: session rules, the table of what can turn a motor, and the
     procedure and pass criteria for N01-N14
   - the matrix cases a no-motion session may run: A01, A02, A06, E02
   - section 6, results format
3. `README.md`: operating behaviour, the panel/web safety model, `dry_run`,
   profile and mission files, `/blind`.
4. Configuration: `profiles/agv-01.json` (vehicle) and `missions/gy-demo.json`
   (site). `missions/empty.json` is only for N12.
5. `AGENTS.md`, if the vehicle has one. It is not tracked in Git.

Treat the checked-out code as the authority. If a document disagrees with the
code, report the discrepancy. Do not change code in this session, and do not
"fix" either side to make a case pass.

## What can turn a motor

| Action | Allowed |
|---|---|
| Selector to MANUAL (arms, drives energised, velocity held at zero) | Yes |
| Selector to AUTO, `/api/disarm`, `/api/stop` | Yes |
| PB Start in AUTO, with `dry_run` confirmed `true` since the last restart | Yes |
| PB Start in AUTO with `dry_run` false | **No** |
| PB Start in MANUAL with any move or U-turn set on `/blind` | **No** |
| PB Start in MANUAL with `blind.plan` null in `/api/state`, checked just before | Yes |
| Opening `/manual` in any browser (arrow keys jog), `/api/drive` | **No** |
| SET / CLEAR on `/blind` | Only in N11; CLEAR before leaving the page |
| Standalone CAN tools, `main.py` next to the service, writing drive or MLS parameters | **No** |

## Hard rules (non-negotiable)

- **The operator does every physical action:** selector, Start, Reset, E-stop,
  tags and unplugging cables. Before each one:
  - name the input and the expected result
  - confirm the no-motion precondition (`dry_run` true for an AUTO Start;
    `blind.plan` null for a MANUAL Start)
  - wait for the operator to confirm
- **Watch the setpoint all session.** Keep an `/api/state` poll running
  **without** `hb=1`, recording `target`, `nodes[*].rpm`, `nodes[*].state`,
  `armed`, `mode`, `dry_run` and `blind.plan`. Stop the session if:
  - `target` leaves 0/0
  - a wheel rpm leaves 0 beyond reading noise
  - a drive reaches Operation enabled during a dry-run AUTO run
  - anyone sees a wheel or motor move

  If so, tell the operator to press the E-stop, stop the session, and report.
- **Events:** save `/api/events` incrementally by sequence number. The ring holds
  only 200 events.
- **Web writes allowed, and only these:** `/api/disarm`, `/api/stop`,
  `/api/restart`, and SET/CLEAR on `/blind` in N11.
- **Restarts:** only while disarmed with the selector in AUTO, via
  `/api/restart`. It refuses while armed and restarts through the unit's
  `Restart=` policy, so no systemctl privilege is needed. Re-verify `/params`
  after every restart.
- **Profile and mission edits:** only those the procedures name:
  - `dry_run` in N01
  - `mission` in N12 and N14
  - the placeholder mission file in N14
  - `tag_clear_s` after A06, if agreed

  For each: operator agreement first, before/after copies into the evidence
  folder, then a restart.
- **Placeholder guard mission (N14):** `missions/nomotion-guard.json` is loaded
  only while `dry_run` is true, and is removed from `missions/` at the end of
  N14. Its values are not measurements.
- **PASS needs physical evidence from this session.** Every motion-matrix case
  (every A, B, C, U and E ID except A01, A02, A06 and E02) is NOT RUN, reason
  "motion prohibited in this session", naming the Phase N case that covered part
  of it.
- **Never widen a limit** or loosen a tolerance to make an observation fit.
- **Stop immediately** if a fault message does not match its cause, or behaviour
  could repeat unsafely.

## Start of session (no arming)

1. **Revision.** Record `git rev-parse HEAD`, the branch and
   `git status --short`, and save a patch of any local changes. Confirm the
   deployed code contains the recent work:
   - `core/uturn.py`, `core/blindrun.py`, `core/manualturn.py`, `missions/` and
     `tests/test_mission.py` exist
   - `tests/run_all.py` pins `EXPECTED_CHECKS = 1516`
   - `_eto_scan` in `canworker.py` returns early when `config.DRY_RUN` is set

   If not, stop and tell the operator the vehicle is not on the intended revision.
2. **Offline suite.** From the repository root, run
   `python3 -B tests/run_all.py` with the vehicle's own interpreter. Require exit
   0, 1516 checks, no failures and no uncaught thread exceptions. Do not install
   or upgrade packages to make it pass. Report any failure verbatim and stop.
3. **Live service.**
   - `systemctl cat agv_controller.service`: record the working directory,
     `AGV_PROFILE`, `AGV_MISSION` and `Restart=`. `/api/restart` needs
     `on-failure` or `always`.
   - `/params` and `/api/config`: profile `agv-01`, mission `gy-demo`, and the
     current `dry_run` value.
4. **Baseline.** Save `/api/config`, `/api/state` (no `hb=1`) and
   `/api/events?since=0`. Copy the profile and mission files into the evidence
   folder.
5. **Physical prerequisites.** Walk the operator through run-sheet Step N0. Do not
   proceed until each item is confirmed. Record whether the vehicle is on the
   service tape or off it; that decides A02 and N07.
6. **State poll.** Start the `/api/state` poll described in the hard rules.

## Running the session

- **One case at a time,** following the no-motion order in the run sheet.
  Before each case, state:
  - its ID, procedure and pass criteria
  - the inputs the operator will use
  - the no-motion precondition

  Then wait for confirmation.
- **Dependencies:**
  - N01 before any AUTO Start
  - a MANUAL arm since the latest restart, before N06
  - a restart before N11 step 1
  - N13 before N14
- **Evidence per case,** in a dated folder:
  - the `logs/NNNN-auto_*` folder of any dry-run run
  - the event capture, and `/api/state` before and after
  - the state-poll excerpt covering the case
  - screenshots of `/auto`, `/blind` or `/params` where the criteria mention them
  - the operator's observations
  - copies of the profile and mission file in use
- **Record specifically:**
  - the encoder scale event value (N02)
  - read-gap distribution and clearance (A06)
  - which N06 outcome occurred
  - whether de-energised drives report speed-zero and actual speed (N04, N06, N14)
  - whether an open `/auto` page masks the DIO loss (N09)
- **Configuration changes:** propose them with their evidence (for example
  `tag_clear_s` from A06). Apply one only after operator agreement.

## Close

Return to the run sheet's closing state:
- selector AUTO, disarmed, no fault latched
- `blind.plan` null
- profile `mission` gy-demo, and `missions/` holding only the original files
- `dry_run` left `true`, and recorded

## Results and reporting

- **Results file:** keep a dated results file beside the handoff, in its section
  6 format. One row per ID for all 63 cases (A01-A12, B01-B06, C01-C10, U01-U08,
  E01-E13, N01-N14), with the revision and files, load, evidence paths and
  measurement/deviation.
- **End-of-session report:**
  1. revision and files tested
  2. cases PASS / FAIL / NOT RUN
  3. every failure or deviation, with its evidence path
  4. measurements obtained
  5. hardware facts that affect the first motion session: whether de-energised
     drives report speed-zero and actual speed, whether `6064h` is readable, the
     encoder scale, IMU availability
  6. configuration changes proposed or made, with justification
  7. discrepancies between the documents and the code
  8. what must happen before the first motion session

Keep it factual and concise.

Begin with the start-of-session steps. Stop and report after step 2 if the
offline suite does not pass.
