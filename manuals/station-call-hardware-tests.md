# Station call system: real-hardware test list

Status: written 2026-11-06. **No test here has been run yet.** This list is for the people on the
floor with the real AGV: one engineer and the operators.

Plans this list tests:

- AGV plan: `manuals/station-call-plan.md` (this repo)
- Station plan: `CODING-PLAN.md` (repo `gvievo-sta`)

The message and error names used below (`NOT_READY`, `TROLLEY_PRESENT` and so on) come from the
interface contract in those plans. This list does not repeat the contract.

The whole system is **not** VDA5050 compliant. It uses a subset only. Do not call it compliant on
any record.

## 1. What must be done before each group

The last column gives the plan's phase. Write the done date beside it before you start. If a plan
splits the work differently, the plan's wording wins, but no row may be dropped.

| Plan | What must be finished | Needed before | Plan phase no. / done date |
|---|---|---|---|
| AGV plan | Floor data: HOME-N taught, graph built, published and active. Five shadow laps passed (`tracked-plan-4` E2). `tape_loc.live: true`, `trip_calls: 1`, new `LineState` build (`colcon build --packages-select amr_interfaces`) | Group S | AGV P0 (group S is its record) / |
| AGV plan | Calling switch and all AGV code built, switch defaults OFF, offline suites pass on the vehicle's copy | Group A part 2 | AGV P1 to P6, P7 steps 1 and 2 / |
| Station plan | Button reading with press detection, call list, screen, saved call list. LED writes behind a flag that defaults OFF | Group B | Station S1, S2 / |
| Station plan | LED output path, startup "set every LED to a known state", `tools/led_test.py` that sets one LED to blink, solid or off | Group C | Station S6, S7 / |
| Station plan | Mosquitto installed, bound to 192.168.2.5 only, password and ACL files in place, including the read-only `watch` user. Station MQTT client. **Test sender**: `tools/test_sender.py` on the station PC reads the newest `state` and publishes a chosen order, `cancelOrder` or a raw body, with a fresh `seenStateHeaderId` where one applies | Group D | Station S3 to S5, floor steps in S8 / |
| AGV plan | MQTT client, `state`, `connection`, order checks. All orders refused until the lidar is fitted | Group D | AGV P5, floor steps in P7 / |
| AGV plan and owner | Rear lidar fitted, wired and configured. Owner's written decision on the rear field while towing. Trolley detection reporting present, absent or unknown | Group E | AGV P8, O1, O2 / |
| AGV plan | Automatic departure from home, departure checks, START interlocks | Group G | AGV P2 and P3 code, floor steps in P9 / |
| Station plan | Order sending and resending, `state` to call-state mapping, LED patterns driven by call state | Group G | Station S5, floor steps in S9 / |
| Station plan | First come first served queue, cancel, restart recovery | Groups H, I, J | Station S5, floor steps in S9 / |
| Both plans | All of the above with no open defects marked safety | Groups K, L | AGV P9, Station S9 / |

## 2. Order of the groups

Work top to bottom. **A group may not start until the group before it has passed, and every test
in it has a result.** A skipped test is a failed test unless the owner has signed "not applicable"
next to it.

| Order | Group | What it proves | Wheels move? |
|---|---|---|---|
| 1 | A part 1 | Vehicle facts, on today's software | No |
| 2 | S | The owner's step one: hand trips to MRU1 and MRU4, and a repeat without At home | Yes |
| 3 | A part 2 | New AGV software with the switch off, standing still | No |
| 4 | B | All 24 buttons read correctly | No |
| 5 | C | LEDs, including the first write to a module | No |
| 6 | D | Broker and MQTT, orders refused | No |
| 7 | E | Rear lidar, and whether the AGV can be lifted (G1) | No, or lifted |
| 8 | F | Hand trips to all four machines, switch off | Yes |
| 9 | G | First automatic departure, then every refusal | Yes |
| 10 | H | Full call cycles, START interlocks | Yes |
| 11 | I | Faults at every call stage | Yes |
| 12 | J | The key hazard at the hitch, then the queue | Yes |
| 13 | K | Soak run and BTU regression | Yes |
| 14 | L | Sign-off | No |

Group S sits before all the new work because the owner decided a hand trip must be proved first,
with MQTT and the station added on top. It has its own letter so that groups A to L keep their names.
Passing S means AGV plan P0 is done.

**The one exception.** Group B only reads, so it cannot move anything, and it may run at any time,
even before S. Code in both plans may go ahead in parallel on simulators. On real hardware, S comes
before C, D and everything later.

**First sends.** The real station PC first sends to the real AGV at D7, through `tools/test_sender.py`.
D7 to D9 are the floor form of AGV plan P7 step 5 (station plan S8 L3). Every order there is refused, because the lidar is absent. The
first order that can turn the wheels is G3, with the wheels lifted, then G4 on the floor, both from a
real button. Neither `tools/test_sender.py` nor `mosquitto_pub` is ever used to start the real AGV
moving.

**Groups G and J are the single acceptance list for AGV plan P9.** That plan keeps no table of its own.

## 3. General safety rules

### Marks on each test

| Mark | Meaning |
|---|---|
| `[NO MOTION]` | The AGV is not expected to move and nothing in the test asks it to |
| `[MOTION IF IT FAILS]` | The AGV should stay still, but the test checks a software block. If the block fails, the AGV may move. Treat it as a motion test: cleared floor, E-stop person in place |
| `[MOTION]` | The AGV will move |
| `[DIO WRITE]` | The test writes to a DIO module output |
| `[OWNER GO]` | Do not start until the owner has said yes for this test and the line on the card is filled in |

### Who must be present

| Role | Job | Rule |
|---|---|---|
| **Lead** | The engineer. Runs the list, decides pass or fail, stops the test | Must be present for every test |
| **E-stop person** | Stays within arm's reach of the AGV's E-stop for the whole test, and walks beside the AGV, never in front of it | Does nothing else: no tablet, no notes. Needed for every test marked `[MOTION]` or `[MOTION IF IT FAILS]` |
| **Operator** | Hitches and unhitches trolleys, presses START | Only one person presses START. Say out loud "START" before pressing it |
| **Station person** | Watches the station screen on the station PC and reports by radio or phone | The station page listens on 127.0.0.1 today, so a tablet cannot open it unless the station plan changes that. Plan on one person at the PC |
| **Machine person** | Presses the machine's button and looks at its LED | Needed for groups B, C, H, J |

Everyone hears the short brief before each group: what will move, where to stand, who says stop.
Anyone may shout **STOP** at any time. Everyone obeys it without asking why.

### E-stop

- Test the E-stop at the start of every day, and after any restart (test A5, steps 1 to 3).
- The E-stop is a person's job. It is never left unattended while the selector is in AUTO.
- A software block is never the only protection during a test. Nobody relies on `NOT_READY`, the
  lidar or the station to keep them safe.

### Floor

- Before any motion, walk the whole route. Clear it of people, trolleys and loose items.
- Tape or barrier off the route for the trip in hand. Put up a sign: "AGV test: moves by itself".
- Tell every machine operator and the warehouse before the first motion of the day. Once group G
  starts, the AGV can leave home **by itself**. Say this plainly.
- Stand beside the AGV, never in front of it, and never between the AGV and a trolley.
- Nobody stands at the hitch during a motion test unless that test says so and the owner has agreed.
- **Never use a person as a test object while the AGV can move.** Any test that checks a field uses the test object or the stand-in target, pulled by rope from outside the zone.
- **No person goes to the hitch with a call waiting and the selector in AUTO until J8 has passed.** Until then, cancel the waiting call on the screen or put the selector in MANUAL first. J5 and J8 are the only exceptions, each under its own rig.

### Speed limits

| When | Limit |
|---|---|
| First run of any new test on the floor | Mission `cruise_mps` 0.2 m/s, or the lowest speed at which the Lead sees the AGV follow the tape properly |
| All other tests | Mission `cruise_mps` 0.4 m/s, the value in `missions/site-103.json` today. Never higher |
| High-speed areas | None active during this list, test A6, until the owner agrees otherwise at test K1 |
| Trolleys | Empty trolleys first. Real load only once the same test has passed with an empty trolley. Never over the train limit in the operation manual, chapter 10.4 |

A changed `cruise_mps` on the vehicle is a difference from the repository. Write it on the sheet and
put it back afterwards.

### Stop at once if

- A wheel turns when the test says it should not. **This is a safety failure.**
- The AGV leaves with a trolley hitched, or with something in a safety field it should react to.
- The E-stop or a scanner stop does not stop the AGV.
- The AGV takes the wrong branch, or heads toward J-S and the south trunk.
- The AGV starts to pivot with a trolley hitched.
- A relay or LED output buzzes, chatters, smells hot or does something other than asked.
- Anyone unplanned walks onto the route.
- The horn does not sound before a move.
- Anyone feels the test is not safe.

### What to do on any failure

1. Stop the AGV: E-stop if it is moving or anyone is near, otherwise selector to MANUAL.
2. Leave everything as it is. Do not press RESET or restart anything yet, unless someone is at risk.
3. Photograph the screens, take the time, write down what happened.
4. Save the logs (see below).
5. The Lead marks the test **FAIL** and the group stays closed.
6. A safety failure goes to the owner the same day. Nobody retests it until the owner has seen it.
7. After a fix, repeat the failed test and every test the Lead lists as affected. **Any change to
   software, profile, mission, scanner or FX3 settings means repeating A1, and the safety checks in
   the operation manual, chapter 8.5, if they apply.**

Never get a test through by adding a bypass, a fake lidar reading or a hand-edited state. There is
no bypass on the vehicle, and no test here needs one.

### Getting the AGV back

The same steps are used after every aborted trip. They are called **Recover** below.

1. Selector to MANUAL.
2. If a trolley is hitched, take it off by hand: brake on, pin out, move it clear.
3. MANUAL ARM on. Jog the AGV to HOME-N. MANUAL ARM off.
4. Mapping page → Position → **At home** → confirm that the scans align → READY.
5. Press RESET. Selector back to AUTO only when the Lead says so.

### Record keeping

- Fill in every Result, Date and Initials field. Result is PASS, FAIL or N/A. N/A needs the owner's initials.
- At the top of each day's sheet write: AGV software commit, station software commit, the active
  graph, the state of the calling switch, the LED flag, and the names and roles present.
- Before each motion test the Lead runs `tools/run_log.sh <mission>` on the AGV and stops it with
  one Ctrl-C after the run. It records the run and sends nothing to the vehicle.
- Keep the filled sheets, photos and logs together in one dated folder. Tell the owner where.
- Nothing in either repository is committed or pushed unless the owner asks.

### Common tools

| Tool | How |
|---|---|
| AGV pages on a tablet | `http://192.168.2.20:5001`: Home, Run, Teach, Alarms |
| AGV terminal | `ssh gvipc-evo-01@192.168.2.20` |
| Watch all MQTT messages | On the station PC, as the read-only user `watch`: `mosquitto_sub -h 192.168.2.5 -u watch -P <password> -i gvi-watch -v -t "vda5050/v3/gvi/#"`. It sees `order` and `instantActions` too, which user `station` cannot read. D2 proves this first |
| Test sender | `tools/test_sender.py --real` on the station PC. User `station`, its own client id. Reads the newest `state`, then publishes a chosen order, `cancelOrder` or a raw body. For refusal checks and `cancelOrder` only, never to start the AGV moving |
| LED test | `tools/led_test.py` on the station PC, app stopped. Goes through `CoilWriter`'s allow-list and the approval file. Covered by `DIO-WRITE-2` (C4) |
| Read the rear lidar with the switch off | On the AGV: `ros2 topic echo /amr/rear/trolley`, fields `state`, `rear_field`, `rear_case`. `loads` and `NOT_READY` exist only on `state`, so only with the switch on |
| Test object | The test object named in the scanner verification report (operation manual, chapter 13), on a stand, with a rope long enough to pull it from outside the marked zone. **Never use a person as a test object while the AGV can move** |
| Stand-in target | A pole or tube on a weighted stand, with a rope long enough to pull it from outside the marked zone. Where a test names a body position, a person-sized dummy or a tube cut to that height. **Never a person** |

## 4. Group A part 1: checks with no motion, today's software

Run these on the software already on the vehicle. Change nothing except where a step says so.

### A1. Repository matches the vehicle `[NO MOTION]`

- **Purpose:** know exactly what is on the vehicle before trusting anything else.
- **Before you start:** AGV on. Selector MANUAL.
- **Steps:**
  1. On the AGV, in the repo folder, run `git rev-parse HEAD`, `git status --short`, and `git diff --stat -- profiles missions`.
  2. Write down the values of `tape_loc.live`, `tape_loc.site_mission` and `tape_loc.shadow_circuit` from `profiles/agv-01.json`.
  3. Write down `trip_calls` and `cruise_mps` from `missions/site-103.json`.
  4. Compare both files with the repository copy on the Lead's PC.
- **Expected:** every difference has a known reason. At the time of writing the repo has `tape_loc.live: false`, `trip_calls: 2`, `cruise_mps: 0.4`. The vehicle may differ.
- **Confirm by:** the commit and the list of differences are written on the sheet.

Commit: ________ Differences: ________

Result: ________ Date: ________ Initials: ________

### A2. HOME-N and all marks are taught `[NO MOTION]`

- **Purpose:** the 2026-10-25 records say HOME-N was not taught and the graph was g1. That may be out of date. Find out.
- **Before you start:** engineer PIN for the Teach page.
- **Steps:**
  1. Teach page → **Roles**. Tick each role below as it appears.
  2. Read the active graph name on the status line.
  3. Check the teach files on the vehicle are there: `line_graph.json`, `stations.json` (see `amr_line/tape_graph_store.py` for the paths).
  4. If C-BTU has been taught, write down how far. Group K needs this.
- **Expected:** all 13 roles are taught and active: HOME-N, ATT, MW-1, MW-2, MW-3, MW-4, ME-1, ME-2, ME-3, ME-4, UT-MRU1, UT-MRU2, UT-MRU3. MRU4 has **no** U-turn mark, because it uses the tape end.
- **Confirm by:** the Roles list on the page, with a photo. If anything is missing, teach it (`tape-localization-runbook.md` 3.3A and 3.4) and repeat this test. That is a separate floor job with its own E-stop person.

Active graph: ________ C-BTU taught: ________

Result: ________ Date: ________ Initials: ________

### A3. Network addresses and gateway `[NO MOTION]`

- **Purpose:** `alpha-setup.md` lists the Wi-Fi gateway as 192.168.2.10. That address is now DIO module 1. Traffic must not be sent to a DIO module.
- **Before you start:** AGV on Wi-Fi. Station PC on the wired network.
- **Steps:**
  1. On the AGV: `ip -4 addr show wlp1s0`, `ip route`, `nmcli -g ipv4.gateway con show agv-net`.
  2. On the AGV, ping once each: `ping -c 1 192.168.2.5` and `ping -c 1 192.168.2.254`.
  3. On the station PC: `ipconfig`. Find the wired adapter.
- **Expected:** AGV at 192.168.2.20. AGV gateway is **not** 192.168.2.10. The access point is 192.168.2.254. The station PC has 192.168.2.5 on its wired adapter. It was "Media disconnected" when last looked at, so check the cable. Both pings answer.
- **Confirm by:** the outputs, written on the sheet. If the gateway is still .10, the Lead corrects it and records the change. `alpha-setup.md` then needs correcting too (see L).

AGV gateway found: ________

Result: ________ Date: ________ Initials: ________

### A4. Clocks `[NO MOTION]`

- **Purpose:** no rule in the system compares clocks, but logs from the two machines must be readable side by side.
- **Before you start:** both PCs on.
- **Steps:**
  1. On the AGV: `timedatectl` and `chronyc tracking`.
  2. On the station PC: `w32tm /query /status`.
  3. Read both clocks at the same moment and write down the difference.
- **Expected:** the difference is known and written down. If it is more than 5 s, the Lead sets the clocks or notes the offset on every log. The AGV has no internet on the floor, so its clock can drift. Repeat this reading at the start of each test day.
- **Confirm by:** the offset on the sheet.

Offset: ________ s

Result: ________ Date: ________ Initials: ________

### A5. E-stop, reset, horn path and front field `[NO MOTION]`

- **Purpose:** the things that protect people today must work before anything is added.
- **Before you start:** AGV parked, selector MANUAL, MANUAL ARM off.
- **Steps:**
  1. Press the E-stop. The Home page shows `ESTOP`.
  2. Turn to release. Press RESET. The state clears.
  3. Repeat for every E-stop button on the vehicle.
  4. Pull the test object into the front protective field by rope, from outside the zone. Home shows it violated. Pull it out. Home shows clear.
  5. Do the daily checks in the operation manual, chapter 10.1.
- **Expected:** each step behaves as stated.
- **Confirm by:** Home page, and the Alarms page event log.

Result: ________ Date: ________ Initials: ________

### A6. Speed and high-speed areas `[NO MOTION]`

- **Purpose:** the test speed must be what this list says.
- **Before you start:** engineer PIN.
- **Steps:**
  1. Open Teach → High-speed areas (`/tape-areas`). Write down what is there.
  2. If any area exists, the Lead writes down its id and shape and removes it for the test period, on the owner's say-so.
- **Expected:** no high-speed area is active. `cruise_mps` is 0.4 or lower.
- **Confirm by:** a photo of the area list. Restore the areas only at test K1 or at the end.

Result: ________ Date: ________ Initials: ________

### A7. Safety records exist `[NO MOTION]`

- **Purpose:** a stop only protects anyone if the stopping distance fits the field. Self-departure raises the stakes.
- **Before you start:** operation manual to hand.
- **Steps:**
  1. Find the verification record for the scanner fields (operation manual, chapter 8.4).
  2. Find the stopping distance measurement at the highest speed used and maximum towed mass (chapter 8.4).
  3. Compare the checksums of the safety controller and scanner configuration with the manual's front page.
- **Expected:** all three exist and match. If any does not exist, this is a question for the owner before motion, not something the Lead can pass.
- **Confirm by:** record numbers and dates written here.

Records: ________

Result: ________ Date: ________ Initials: ________

### A8. Floor walk and test equipment `[NO MOTION]`

- **Purpose:** check the route and that everything for later groups is on hand.
- **Before you start:** nothing moving.
- **Steps:**
  1. Walk the C-MRU route end to end. Check the tape is not lifted or torn at any point, including X1 and the MRU line.
  2. Check all six trolley types (A, B, C, E, F, G) are available, with brakes and couplings working. Write down the hitch type: pin or hook. The operation manual still says `[TBD]`.
  3. Check the test object, stand-in target, ropes, tape measure, stopwatch, radios and barrier tape are at hand.
  4. Mark the floor at each stop for comparing stops: ATT, MW-1..4, ME-1..4.
- **Expected:** all present and in good order.
- **Confirm by:** a tick list on the sheet.

Result: ________ Date: ________ Initials: ________

## 5. Group S: the owner's step one, one hand trip

No MQTT, no station, no new AGV software. Only START and the AGV's own screen. No MRU machine run
has been done yet, so this is the first one. It also becomes the yardstick for later groups. Passing
S0 to S5 means AGV plan P0 is done: two MRU1 trips in a row, the second without At home, and one MRU4
trip, with no unexplained `position` hold or FAULT.

### S0. Ten empty pivots `[MOTION]`

- **Purpose:** S1 pivots at UT-MRU1, so the pivot itself comes first. `tracked-plan-4` lists its E3 before E4. This list does E4 first, because nothing else proves the pivot before a full trip relies on it.
- **Before you start:** group A part 1 passed. `tape_loc.live: true` and `trip_calls: 1` on the vehicle, service restarted (`tape-localization-runbook.md` section 4). Cleared floor. `cruise_mps` 0.2. No trolley.
- **Steps:**
  1. Run the tape-under-sensor pivot on the MRU straight, empty, as in `tracked-plan-4` E4, 10 times.
  2. Count each reacquire of the tape.
- **Expected:** 10 pivots, all reacquired inside the gyro window. If they cannot be run this way on the vehicle, the Lead writes down why and the owner decides before S1.
- **Confirm by:** E-stop person, saved log.

Reacquired: ________ of 10

Result: ________ Date: ________ Initials: ________

### S1. Hand trip to MRU1 with no trolley `[MOTION]`

- **Purpose:** prove the route, the two machine stops and the mid-line U-turn with nothing to tow.
- **Before you start:** S0 passed. Cleared floor. `cruise_mps` 0.2. No trolley.
- **Steps:**
  1. AGV at HOME-N, selector MANUAL. Press **At home** → confirm → READY.
  2. Selector AUTO. MANUAL ARM off.
  3. Run page → Calls: tap **Trolleys off at HOME**.
  4. Run page → Calls: tap **MRU1**. Wait 30 s and watch the wheels.
  5. Press START. Horn sounds for 2 s, then AGV drives through the U-turn R717 and stops at ATT.
  6. Press START. AGV takes J-N right, crosses X1, passes J-ML, drives to MW-1 and stops.
  7. Press START. AGV moves on about 1.4 m, pivots at UT-MRU1, comes back and stops at ME-1, 3.4 m after the pivot.
  8. Press START. AGV goes home by J-ML left, J-STEM left, J-SPLIT left, and stops at HOME-N.
- **Expected:** no motion in step 4. Four START presses in all, each with a horn first. Each stop within ±10 cm of its floor mark. Trip ends DONE and the note says served. No hold other than the station stops.
- **Confirm by:** Run page message and event log. Tape measure at each stop. `tools/run_log.sh` log saved.

| Stop | Error from floor mark (cm) |
|---|---|
| ATT | |
| MW-1 | |
| ME-1 | |
| HOME-N | |

Result: ________ Date: ________ Initials: ________

### S2. Hand trip to MRU1 with a real trolley `[MOTION]`

- **Purpose:** the same trip the way the owner's flow will use it.
- **Before you start:** S1 passed. `cruise_mps` 0.4 if S1 was steady. One empty trolley at ATT, one trolley standing at the ME-1 spot to act as the full trolley. Operator knows the hitch steps (operation manual, 10.4).
- **Steps:**
  1. Steps 1 to 5 of S1.
  2. At ATT: hitch the empty trolley. Step clear. Press START. AGV stops at MW-1.
  3. At MW-1: brake on, pin out, move the trolley clear of the AGV. Step clear. Press START.
  4. Watch the pivot. It must clear the released trolley. AGV stops at ME-1.
  5. At ME-1: hitch the waiting trolley. Step clear. Press START. AGV goes home towing it.
  6. At HOME-N: unhitch and move the trolley clear. Do **not** tap **Trolleys off at HOME** yet. S3 needs it untapped.
- **Expected:** as S1. The pivot clears the released trolley by a margin the Lead is happy with. The AGV tracks the tape with the trolley behind it on every curve.
- **Confirm by:** tape measure at the pivot, Run page, saved log.

Pivot clearance to released trolley: ________ cm

Result: ________ Date: ________ Initials: ________

### S3. Baseline record `[MOTION IF IT FAILS]`

- **Purpose:** later groups must match this. The switch-off promise is "the job, node and web behave as the P0 baseline", and this is what today looks like.
- **Before you start:** S2 passed, straight after its last step. Selector AUTO, floor still cleared, E-stop person in place.
- **Steps:**
  1. From the S2 log, write down the time from each START to the next stop.
  2. Save the Run page messages and event log for the trip.
  3. Tap **MRU1**. Press START with **Trolleys off** not tapped. Write down the refusal text. Cancel the call.
  4. Tap **Trolleys off at HOME**. Press START with no call waiting. Write down the refusal text.
- **Expected:** a saved baseline. Both presses are refused and the AGV does not move.
- **Confirm by:** the file saved in the test folder.

Result: ________ Date: ________ Initials: ________

### S4. Repeat MRU1 without At home `[MOTION]`

- **Purpose:** nothing yet shows the locator staying usable at HOME after a trip on the vehicle. This is the way the AGV will work between calls.
- **Before you start:** S3 passed, straight after its last step. AGV has not been moved or restarted. Trolleys set as in S2. `cruise_mps` as S2.
- **Steps:**
  1. Do **not** press At home. Selector AUTO, MANUAL ARM off, **Trolleys off at HOME** tapped in S3.
  2. Run → Calls: tap **MRU1**. Press START.
  3. Steps 2 to 6 of S2. At the end tap **Trolleys off at HOME**.
- **Expected:** as S2, with no `position` hold and no FAULT. If the trip refuses or holds for position, this is a fail, and it goes to the owner before anything is built on it.
- **Confirm by:** Run page, event log, saved log.

Result: ________ Date: ________ Initials: ________

### S5. Hand trip to MRU4, tape-end U-turn `[MOTION]`

- **Purpose:** MRU4 is the one machine with no mid-line U-turn point. After MW-4 the AGV goes on to the tape end and pivots there at U-MRU.
- **Before you start:** S4 passed. `cruise_mps` 0.2. One empty trolley at ATT, one at the ME-4 spot. Space around the tape end cleared and marked. Check the distance from MW-4 to the tape end.
- **Steps:**
  1. Run → Calls: tap **MRU4**. Press START. Press At home first only if the AGV has been moved since S4, and write that down.
  2. Steps 2 to 6 of S2, with MW-4 and ME-4 in place of MW-1 and ME-1. E-stop person walks beside it through the pivot.
- **Expected:** after START at MW-4, the AGV drives on to the tape end, slows, pivots, finds the tape again, drives back and stops at ME-4. No extra stop or hold on the way. Each stop within ±10 cm of its floor mark. Overrun past the tape end measured at the sensor.
- **Confirm by:** tape measure, Run page, saved log.

ATT: ________ cm MW-4: ________ cm ME-4: ________ cm HOME-N: ________ cm Overrun past the tape end: ________ cm

Result: ________ Date: ________ Initials: ________

## 6. Group A part 2: new AGV software with the switch off

### A9. Install and record `[NO MOTION]`

- **Purpose:** the new software is on the vehicle and the switch is off.
- **Before you start:** the AGV plan's code phases are complete.
- **Steps:**
  1. Write down how to go back to the S2 commit before installing. Install the new AGV software.
  2. Run `python3 tests/run_all.py` on the vehicle's copy.
  3. In `amr_ws`, run `env AMR_SIM_TESTS=0 ROS_DOMAIN_ID=89 python3 -m pytest -q src/*/test`.
  4. Read the calling switch in the profile (name in the AGV plan). Repeat A1.
  5. Restart the service. Check it reaches READY.
- **Expected:** suites pass with no failures. The switch is **off**. Differences from S2 are only the planned ones.
- **Confirm by:** suite output saved, profile value on the sheet.

Commit: ________

Result: ________ Date: ________ Initials: ________

### A10. No MQTT with the switch off `[NO MOTION]`

- **Purpose:** the owner's rule: with the switch off, the MQTT client does not start.
- **Before you start:** A9 passed.
- **Steps:**
  1. On the AGV: `ss -tnp | grep 1883`, and look for an MQTT process: `ps aux | grep -i mqtt`.
  2. Watch for 2 minutes.
  3. Open the Run page, Home page, Alarms page.
- **Expected:** no connection to port 1883 and no MQTT process. The pages show no new errors or alarms caused by the missing broker or lidar.
- **Confirm by:** command output, screenshots compared with S3.

Result: ________ Date: ________ Initials: ________

### A11. A waiting call does not move the AGV with the switch off `[MOTION IF IT FAILS]`

- **Purpose:** automatic departure must not exist while the switch is off.
- **Before you start:** floor cleared. E-stop person in place. AGV at HOME-N, READY, AUTO.
- **Steps:**
  1. Tap **Trolleys off at HOME**. Tap **MRU1** on Run → Calls.
  2. Wait 60 s. Watch the wheels and listen for the horn.
  3. Selector to MANUAL and back to AUTO. Wait 30 s.
  4. Press RESET. Wait 30 s.
  5. Cancel the call on the page.
- **Expected:** no wheel motion and no horn at any point. The screen still says to press START.
- **Confirm by:** E-stop person watching wheels, event log shows no `ARMED`.

Result: ________ Date: ________ Initials: ________

## 7. Group B: buttons on the real modules

The AGV is not involved. The LED flag stays **off**. Only one program may talk to each module at a
time. The limit is unknown (`PROTOCOL.md`), so do not run another Modbus tool with the station running.
This group only reads, so it may run at any time, even before group S (section 2).

### B1. Modules online, nothing pressed `[NO MOTION]`

- **Purpose:** check polarity at rest. Inputs have only ever read 0, so polarity and bit order are not proven yet.
- **Before you start:** Station running, LED flag off. Nobody touching a button.
- **Steps:**
  1. Open the station screen. Check 192.168.2.10 and 192.168.2.11 are both online.
  2. Check `config.json` is the expected one.
  3. Leave it for 2 minutes.
- **Expected:** both online. All 24 buttons read **not pressed**, and no call appears. If they all read pressed at rest, polarity is reversed: stop, this is a fail.
- **Confirm by:** station screen.

Result: ________ Date: ________ Initials: ________

### B2. Every button, right machine, right type `[NO MOTION]`

- **Purpose:** the wire from each button reaches the right channel and name.
- **Before you start:** B1 passed. Machine person at the machine with radio. Station person at the screen.
- **Watch out:** in the table the DI channel is a hex number. Channel `A` means MRU2's button C. Channel `D` is MRU2's or MRU4's button G. These letters are **not** button letters.
- **Steps, for each row:**
  1. Machine person says which button, then presses it for one full second and releases.
  2. Station person reads back the machine and type on the screen, and says whether anything else changed.
  3. Cancel the call on the screen before the next press.
- **Expected:** the screen shows exactly the machine and type in the row, and nothing else changes. Pressed and released states look the right way round.
- **Confirm by:** the two people agree by radio. Tick the row.

| ID | Module | DI | Machine | Button | Screen correct | Date | Initials |
|---|---|---|---|---|---|---|---|
| B2.01 | 192.168.2.10 | 0 | MRU1 | A | | | |
| B2.02 | 192.168.2.10 | 1 | MRU1 | B | | | |
| B2.03 | 192.168.2.10 | 2 | MRU1 | C | | | |
| B2.04 | 192.168.2.10 | 3 | MRU1 | E | | | |
| B2.05 | 192.168.2.10 | 4 | MRU1 | F | | | |
| B2.06 | 192.168.2.10 | 5 | MRU1 | G | | | |
| B2.07 | 192.168.2.10 | 8 | MRU2 | A | | | |
| B2.08 | 192.168.2.10 | 9 | MRU2 | B | | | |
| B2.09 | 192.168.2.10 | A | MRU2 | C | | | |
| B2.10 | 192.168.2.10 | B | MRU2 | E | | | |
| B2.11 | 192.168.2.10 | C | MRU2 | F | | | |
| B2.12 | 192.168.2.10 | D | MRU2 | G | | | |
| B2.13 | 192.168.2.11 | 0 | MRU3 | A | | | |
| B2.14 | 192.168.2.11 | 1 | MRU3 | B | | | |
| B2.15 | 192.168.2.11 | 2 | MRU3 | C | | | |
| B2.16 | 192.168.2.11 | 3 | MRU3 | E | | | |
| B2.17 | 192.168.2.11 | 4 | MRU3 | F | | | |
| B2.18 | 192.168.2.11 | 5 | MRU3 | G | | | |
| B2.19 | 192.168.2.11 | 8 | MRU4 | A | | | |
| B2.20 | 192.168.2.11 | 9 | MRU4 | B | | | |
| B2.21 | 192.168.2.11 | A | MRU4 | C | | | |
| B2.22 | 192.168.2.11 | B | MRU4 | E | | | |
| B2.23 | 192.168.2.11 | C | MRU4 | F | | | |
| B2.24 | 192.168.2.11 | D | MRU4 | G | | | |

Group result: ________ Date: ________ Initials: ________

### B3. No button D, spare channels silent `[NO MOTION]`

- **Purpose:** there is no D trolley. Nothing may produce a type D.
- **Before you start:** B2 passed.
- **Steps:**
  1. Look at each of the four button panels. Confirm six buttons, labelled A, B, C, E, F, G, and no D.
  2. Check channels 6, 7, E and F on both modules on the raw view. They are not in `config.json`.
  3. Open the panel and check nothing is wired to those channels, if the Lead can do so safely with power off.
- **Expected:** no button D anywhere. Spare channels read not pressed and give no call. Type D never appears on the screen.
- **Confirm by:** photo of each panel, station raw view.

Result: ________ Date: ________ Initials: ________

### B4. Shortest tap `[NO MOTION]`

- **Purpose:** the station samples about every 100 ms, so a very short tap can fall between samples. Find out whether a real person's tap is ever missed.
- **Before you start:** B2 passed.
- **Steps:**
  1. Machine person taps MRU1 button A in a normal way, 20 times, with a cancel between each.
  2. Then taps it as fast and lightly as a person can, 20 times.
  3. Repeat both on all six buttons of one machine, and one button on each other machine.
  4. Ask a real machine operator to press the way they will at work, 10 times.
- **Expected:** no misses for normal or operator presses. The very fast tap count is recorded. If real operators' presses are ever missed, this is a fail for the station plan.
- **Confirm by:** count of calls on the station screen.

| Button | Normal 20 | Fast 20 | Operator 10 |
|---|---|---|---|
| MRU1 A | | | |
| MRU1 B | | | |
| MRU1 C | | | |
| MRU1 E | | | |
| MRU1 F | | | |
| MRU1 G | | | |
| MRU2 (any) | | | |
| MRU3 (any) | | | |
| MRU4 (any) | | | |

Result: ________ Date: ________ Initials: ________

### B5. Held button, double press, second press `[NO MOTION]`

- **Purpose:** a press makes one call. Further presses do nothing until that call closes.
- **Before you start:** B4 passed.
- **Steps:**
  1. Hold MRU1 button A for 60 s. Release.
  2. Press MRU1 button A twice quickly. The call stays open.
  3. While it stays open, press MRU1 button C.
  4. Cancel the call on the screen, then press MRU1 button C.
- **Expected:** step 1 gives one call only, type A. Steps 2 and 3 change nothing: the type stays A. Step 4 gives a new call, type C.
- **Confirm by:** station call list, one row per call.

Result: ________ Date: ________ Initials: ________

### B6. A held button through an outage is not a new press `[NO MOTION]`

- **Purpose:** after an outage, reading goes "unknown" and then "pressed". That must not look like a new press.
- **Before you start:** B5 passed, no call open. Warn the machines: the modules are daisy chained, so pulling the first cable may take both offline.
- **Steps:**
  1. Hold MRU3 button A. A call appears. Cancel it, keep holding.
  2. Pull the Ethernet cable of 192.168.2.11. Screen shows it offline.
  3. Put it back, still holding. Wait 10 s. Release.
  4. Hold MRU3 button B while the station starts up: stop the station, press and hold, start it, wait 10 s, release.
- **Expected:** no new call after steps 3 or 4. Screen shows offline clearly during step 2. A real press after this works normally.
- **Confirm by:** station call list.

Result: ________ Date: ________ Initials: ________

## 8. Group C: LEDs, the first write to a module

`PROTOCOL.md` requires explicit human approval before any write to a DIO module. All writes to these
modules have so far been documented, never proved. Outputs latch and there is no watchdog, so a
crash can leave an LED on.

There are two named approvals, recorded in `CODING-PLAN.md` section 21 and matching its S7:

| Approval | Covers exactly this | Test |
|---|---|---|
| `DIO-WRITE-1` | App stopped. A script writes each of the four coils, DO0 and DO6 on 192.168.2.10 and 192.168.2.11, on and then off | C3 |
| `DIO-WRITE-2` | The app with the LED flag on, and `tools/led_test.py`: ON, OFF and blink at the measured period, on DO0 and DO6 of both modules only. Approval file `state/dio_write_approved.json` created by a person | C4 to C8 and all later LED use |

**Any other output still needs fresh approval from the owner.**

### C1. Relay rating, wiring, blink rate `[NO MOTION]`

- **Purpose:** blinking wears out relays. No rating has been found in the documents, and the LED wiring is not documented.
- **Before you start:** module data sheet or the module's label. Wiring drawing, or trace it by eye with power off.
- **Steps:**
  1. Find the relay's rated voltage, current and number of operations.
  2. Write down what is really wired on DO0 and DO6 on both modules: voltage, current, type of lamp. Check nothing else is on those outputs or any other output.
  3. Read the blink period from the station config.
  4. Work out the relay life: rated operations × blink period = hours of blinking. For example only, **not this module's rating**: 100,000 operations at one on-off every 2 s is about 55 hours of blinking.
  5. Estimate blink hours per day, including calls that wait a long time.
- **Expected:** the load is within the rating. The owner accepts the life figure, or changes the blink period, or changes the output hardware.
- **Confirm by:** the numbers below, seen by the owner.

Rating: ________ Load: ________ Blink period: ________ s Life: ________ h

Result: ________ Date: ________ Initials: ________

### C2. Flag off means no writes `[NO MOTION]`

- **Purpose:** the default must be safe. With the flag off, the write path must not run.
- **Before you start:** LED flag off. Someone at each machine looking at the LED.
- **Steps:**
  1. Restart the station.
  2. Press a button on each machine to make calls, wait 2 minutes.
  3. Watch the `do` read-back on the station's raw view.
  4. If the Lead has a network capture to hand, capture port 502 and look for function codes 05, 06, 0F, 10.
  5. Cancel every call made in step 2 on the screen. Check the call list is empty.
- **Expected:** no relay clicks. Read-back unchanged. No write function codes. No open call left.
- **Confirm by:** people at the LEDs, station raw view, capture if taken.

Result: ________ Date: ________ Initials: ________

### C3. First write, `DIO-WRITE-1` `[DIO WRITE]` `[OWNER GO]`

- **Purpose:** the first real write to a module, done deliberately, one coil at a time, with nothing else running. This is station plan S7 W2 and W3.
- **Approval covers exactly this:** with the app stopped, a script using `dio_write.write_coil` writes DO0 and DO6 on 192.168.2.10 and on 192.168.2.11, each on and then off, once. Nothing else.
- **Before you start:** C1 and C2 passed. Call list empty: `state/calls.json` has no open calls, and every C2 call is cancelled. Station app **stopped**, so only one client is connected. LED flag still off. Everything on the outputs known. People at all four LEDs. Machines told. Nobody working inside a panel.
- **Steps:**
  1. Lead reads the approval line below aloud to the owner, and the owner signs it.
  2. Script: DO0 on 192.168.2.10 on, then off. Person at the MRU1 LED reports.
  3. Check the reply, and read the bit back with FC01.
  4. The same for DO6 on 192.168.2.10, then DO0 and DO6 on 192.168.2.11, one at a time.
- **Expected:** each write lights its own machine's LED, then puts it out. Each module answers each write with an exact copy of the request. FC01 reads it back in the right bit, which proves polarity. All other outputs are unchanged. Nothing unexpected switches anywhere. Any other reply: the Lead stops the test.
- **Confirm by:** script output, read-back, people at the LEDs.

Owner approves `DIO-WRITE-1`, as above: ________ Date and time: ________

Result: ________ Date: ________ Initials: ________

### C4. `DIO-WRITE-2`, each LED: right machine, blink, solid, off `[DIO WRITE]` `[OWNER GO]`

- **Purpose:** the first ON, OFF and blink writes from the station's own code. Each LED output reaches the right machine, and each pattern works. This is the start of station plan S7 W4.
- **Approval covers exactly this:** `tools/led_test.py` and the app with the LED flag on: ON, OFF and blink at the period set at C1 and recorded on this card, on DO0 and DO6 of 192.168.2.10 and 192.168.2.11 only. C5 to C8 and every later group run under this approval. The measured value is entered after step 4, and more than 10 % off stops the test for a fresh approval.
- **Before you start:** C3 passed. Call list still empty. Person at each machine with a radio. Stopwatch.
- **Steps:**
  1. Lead reads the approval line below aloud to the owner, and the owner signs it.
  2. A person creates `state/dio_write_approved.json` and sets the LED flag on. Nothing else is changed. App stays stopped for the table.
  3. For each row, with `tools/led_test.py`, set this LED to **solid**. Machine person reports what they see.
  4. Set it to **blink**. Time 10 on-off cycles.
  5. Set it to **off**. Station person checks read-back and that no other output changed.
  6. Start the app with the empty call list. Read the station log for its startup writes and look at the `do` read-back on both modules.
- **Expected:** only that row's LED changes. Blink period matches the value from C1 within 10 %, and the measured period is what is approved. Off is really off. At step 6 the app writes every LED to off, and no LED lights.
- **Confirm by:** machine person by radio, read-back, station log.

Owner approves `DIO-WRITE-2`, as above: ________ Measured period: ________ s Date and time: ________

| ID | Module | DO | Machine | Solid | Blink, s per cycle | Off | Others unchanged | Date | Initials |
|---|---|---|---|---|---|---|---|---|---|
| C4.1 | 192.168.2.10 | 0 | MRU1 | | | | | | |
| C4.2 | 192.168.2.10 | 6 | MRU2 | | | | | | |
| C4.3 | 192.168.2.11 | 0 | MRU3 | | | | | | |
| C4.4 | 192.168.2.11 | 6 | MRU4 | | | | | | |

Result: ________ Date: ________ Initials: ________

### C5. A button press blinks the right LED `[DIO WRITE]`

- **Purpose:** the press-to-LED path with the AGV out of the picture. Solid and off from real AGV movement are checked in group H.
- **Before you start:** C4 passed. No broker needed.
- **Steps:**
  1. Press MRU2 button E. Check its LED blinks and the other three stay off.
  2. Press MRU4 button A. Check both blink.
  3. Cancel each on screen.
- **Expected:** each LED blinks from its press and stops when its call is cancelled.
- **Confirm by:** machine person, station call list.

Result: ________ Date: ________ Initials: ________

### C6. Station crash leaves an LED on, then recovery `[DIO WRITE]`

- **Purpose:** the known weak spot. A crash leaves the output as it was. The restart must fix it.
- **Before you start:** C5 passed. App running, one open call on one machine, and wait for that LED's **on** phase. (`tools/led_test.py` runs only with the app stopped, so it cannot set up this test.)
- **Steps:**
  1. Kill the station with no warning: `taskkill /F /PID <pid>`.
  2. Check that LED. Wait 2 minutes.
  3. Start the station. Time how long until the LED is correct.
  4. Repeat, killing it during an **off** phase.
  5. Repeat by pulling the PC's power.
  6. Write down what a machine operator sees while the station is down, and whether they could be misled.
- **Expected:** step 2: LED stays as it was, as `PROTOCOL.md` warns. Step 3: within 5 s of the module coming online, every LED is in a known state: off, or the pattern for its saved open call.
- **Confirm by:** person at the LED, stopwatch, station log showing writes at startup.

Time to correct: ________ s

Result: ________ Date: ________ Initials: ________

### C7. Module power cycle and pulled cable `[DIO WRITE]`

- **Purpose:** the station must put an LED back, and must not claim to know its state while the module is away.
- **Before you start:** C6 passed. One open call on MRU1, LED blinking. Warn machines: module 192.168.2.10 will go down.
- **Steps:**
  1. Pull the module's Ethernet cable. Look at the LED and the screen. Wait 30 s. Refit it.
  2. Switch off the module's power. Wait 10 s. Switch on.
  3. Time until the LED pattern is right again.
- **Expected:** while offline, screen shows the LED state as **unknown**. The output stays latched during a cable pull (it may freeze on or off). After reboot outputs may be clear, which the protocol document reports but has not proved: write down what happens. Within 5 s of returning, the LED matches the call.
- **Confirm by:** person at the LED, station screen, read-back.

Result: ________ Date: ________ Initials: ________

### C8. Orderly stop `[DIO WRITE]`

- **Purpose:** know what happens on a normal station exit.
- **Before you start:** C7 passed. Open call on one machine.
- **Steps:**
  1. Stop the station the normal way.
  2. Look at the LEDs. Start it again.
  3. Set the flag off, restart, and look again.
- **Expected:** after an orderly exit, LEDs are off. After restart with the call saved, the LED blinks again. With the flag off, nothing is written. If an LED was left on, the sheet must say so, and it stays on until the flag is back on or someone clears it with approval. Set the flag back on for groups after C.
- **Confirm by:** person at the LED, station log.

Result: ________ Date: ________ Initials: ________

## 9. Group D: broker and MQTT, no motion

**Why this group cannot move the AGV by design:** no rear lidar is fitted yet, so trolley state is
unknown and every order is refused. Still, D3 and every test marked `[MOTION IF IT FAILS]` count as
motion tests, because that refusal is the very thing under test.

### D1. Broker listens on the right address only `[NO MOTION]`

- **Purpose:** the PC also has a hotspot link. The broker must not be reachable from it.
- **Before you start:** Mosquitto installed as the plan says.
- **Steps:**
  1. On the station PC: `netstat -an | findstr 1883`.
  2. Connect a phone or laptop to the PC's hotspot and try to reach port 1883 on the hotspot address.
  3. Reboot the station PC with the Ethernet cable in. Check the broker comes up by itself.
  4. Reboot with the cable out, then plug it in. Check what happens.
- **Expected:** only `192.168.2.5:1883` is listening. It is not `0.0.0.0`. Hotspot connection fails. If the broker does not recover after step 4, record exactly what someone must do: this goes in the operator notes.
- **Confirm by:** command output.

Recovery after cable-out boot: ________

Result: ________ Date: ________ Initials: ________

### D2. Who may connect `[NO MOTION]`

- **Purpose:** an order can now move the vehicle, so the broker must not take orders from just anyone.
- **Before you start:** D1 passed. AGV switch still off.
- **Steps:**
  1. Try `mosquitto_sub` with no username, then with a wrong password.
  2. Start the watcher as user `watch` (section 3, Common tools). As user `station`, publish a test message on `vda5050/v3/gvi/agv1/order`. **The watcher must show it.** If it does not, stop: no "no order sent" result in this list can be trusted until it does.
  3. Connect as user `watch` and try to publish on `vda5050/v3/gvi/agv1/order`.
  4. Connect as user `agv1` and try to publish on `vda5050/v3/gvi/agv1/order`.
  5. Connect as user `station` and try to publish on `vda5050/v3/gvi/agv1/state`.
  6. Check that the password and ACL files are outside both repositories.
- **Expected:** step 1 refused. Step 2 reaches the watcher. Steps 3, 4 and 5: the message does not reach the watcher. Plain MQTT is not encrypted, so note that Wi-Fi security still matters.
- **Confirm by:** watcher window, broker log.

Result: ________ Date: ________ Initials: ________

### D3. Switch off with the broker up `[MOTION IF IT FAILS]`

- **Purpose:** with the switch off, the AGV hears nothing.
- **Before you start:** D2 passed. AGV at HOME-N, READY, AUTO, switch off. Floor cleared.
- **Steps:**
  1. Watch all topics.
  2. Use the test sender to publish a correct MRU1 order, with a chosen `seenStateHeaderId` because no `state` exists. Repeat every 2 s for 30 s.
- **Expected:** no `state` or `connection` from the AGV. No horn, no motion. Event log on the AGV shows nothing.
- **Confirm by:** watcher window, E-stop person.

Result: ________ Date: ________ Initials: ________

### D4. Switch on: connection and state `[NO MOTION]`

- **Purpose:** the normal link works.
- **Before you start:** D3 passed. Selector MANUAL. Set the switch on, restart the service. Station running.
- **Steps:**
  1. Watch `connection` and `state`.
  2. Check `state` arrives at least once a second for 2 minutes.
  3. Read a full `state` message.
  4. Check the station screen.
  5. Check the AGV's Run page still works.
- **Expected:** retained `ONLINE`. `state` at 1 s or quicker. `loads` key missing. `NOT_READY` has at least `NOT_AUTO`, `NOT_AT_HOME`, `TROLLEY_UNKNOWN`, `REAR_FIELD_UNKNOWN`, and `LOCALIZATION_NOT_READY` until a scan match is confirmed. `operatingMode` is `MANUAL`. `headerId` goes up by 1. The station does not display `powerSupply`, which is a placeholder.
- **Confirm by:** watcher window, station screen.

Result: ________ Date: ________ Initials: ________

### D5. Last will on pulled Wi-Fi `[NO MOTION]`

- **Purpose:** the station learns when the AGV disappears.
- **Before you start:** D4 passed. AGV parked. Stopwatch. Tablets will lose the AGV pages, so use the AGV's own screen.
- **Steps:**
  1. Switch off the access point `agv_field` (192.168.2.254). Start the stopwatch.
  2. Note when the station shows "AGV link lost".
  3. Note when the retained message becomes `CONNECTION_BROKEN`.
  4. Check on the AGV's own screen: is the AGV unchanged?
  5. Switch the access point on. Note when `ONLINE` and `state` return.
- **Expected:** link lost within about 3 s. `CONNECTION_BROKEN` at about 15 s. AGV service unaffected. `ONLINE` then `state` return by themselves after Wi-Fi returns.
- **Confirm by:** stopwatch, watcher window (the PC is wired, so it keeps watching).

Link lost: ________ s Last will: ________ s Back: ________ s

Result: ________ Date: ________ Initials: ________

### D6. Orderly offline and broker restart `[NO MOTION]`

- **Purpose:** orderly exit and a restarted broker both read correctly.
- **Before you start:** D5 passed.
- **Steps:**
  1. On the AGV, stop the service in the normal way. Check `connection`. Start the service.
  2. Stop the broker: `net stop mosquitto` (or the name the plan gives). Check the AGV's and station's reactions. Start it.
- **Expected:** step 1 shows `OFFLINE`. Step 2: station reads "not online" until the AGV reconnects and republishes `ONLINE`, which it does by itself. The AGV's own pages and service carry on as normal.
- **Confirm by:** watcher window, station screen, AGV Home page.

Result: ________ Date: ________ Initials: ________

### D7. Order refused when not in AUTO `[MOTION IF IT FAILS]`

- **Purpose:** the AGV's own check. Sent by the test sender so that the station's own hold-back is not what's being tested. This is the first time the real station PC sends to a listening AGV (section 2).
- **Before you start:** AGV at HOME-N, READY. Selector MANUAL. Floor cleared. E-stop person in place.
- **Steps:**
  1. Send a correct MRU1 order with the test sender.
  2. Read `state` for 30 s.
- **Expected:** `errors` shows `MOBILE_ROBOT_NOT_AVAILABLE`. `orderId` unchanged. No horn. No motion.
- **Confirm by:** watcher window, AGV event log.

Result: ________ Date: ________ Initials: ________

### D8. Order refused when not at home `[MOTION IF IT FAILS]`

- **Purpose:** an order may only start from home.
- **Before you start:** D7 passed. Jog the AGV along the tape at least 1 m from HOME-N (over the 0.5 m limit). Selector AUTO.
- **Steps:**
  1. Send a correct MRU1 order with the test sender.
  2. Read `state`. Then jog back to HOME-N, restart the service, do **not** press At home. Selector AUTO. Send again.
- **Expected:** `START_NODE_OUT_OF_RANGE` both times. `NOT_READY` includes `NOT_AT_HOME`. No horn, no motion.
- **Confirm by:** watcher window.

Result: ________ Date: ________ Initials: ________

### D9. Order refused with no lidar, at home and in AUTO `[MOTION IF IT FAILS]`

- **Purpose:** the fail-safe the whole rollout rests on: unknown trolley means no departure.
- **Before you start:** D8 passed. AGV at HOME-N, At home pressed, READY, selector AUTO. Rear lidar not fitted.
- **Steps:**
  1. Press the E-stop. Send a correct MRU1 order. Read `state`.
  2. Release, RESET. Clear the floor. E-stop person ready. Send the order again.
  3. Send it every 2 s for 60 s.
- **Expected:** every time: `DEPARTURE_REFUSED` with `TROLLEY_UNKNOWN`. Nothing stored: `orderId` stays as it was. No horn. No wheel motion.
- **Confirm by:** watcher window, E-stop person.

Result: ________ Date: ________ Initials: ________

### D10. Bad orders and other instant actions `[MOTION IF IT FAILS]`

- **Purpose:** only the exact agreed order shape gets past the first checks.
- **Before you start:** D9 passed. As D9, floor cleared.
- **Steps, one row at a time, test sender:**
- **Expected:** the row's error, no horn, no motion.
- **Confirm by:** watcher window.

| ID | Send | Expected error | Result | Date | Initials |
|---|---|---|---|---|---|
| D10.1 | Not valid JSON | `VALIDATION_FAILURE` | | | |
| D10.2 | Wrong `serialNumber` | `VALIDATION_FAILURE` | | | |
| D10.3 | `version` not starting with `3.` | `VALIDATION_FAILURE` | | | |
| D10.4 | BTU node in the order | `VALIDATION_FAILURE` | | | |
| D10.5 | Two machines in one order | `VALIDATION_FAILURE` | | | |
| D10.6 | `released: false` on a node | `VALIDATION_FAILURE` | | | |
| D10.7 | `orderUpdateId: 1` | `VALIDATION_FAILURE` | | | |
| D10.8 | `triggerType` `FLEET_CONTROL` | `INVALID_ORDER_ACTION` | | | |
| D10.9 | Stop the AGV service, so the MQTT bridge is off. Publish a correct order with the retain flag set (`mosquitto_pub -r`, user `station`). Start the service, so the bridge receives the stored order on subscribing. Clear it afterwards with an empty retained message. Press At home again for the rows after this one | Discarded, no report at all | | | |
| D10.10 | `startPause` instant action | `FAILED`, `INVALID_INSTANT_ACTION` | | | |
| D10.11 | `stopPause` instant action | `FAILED`, `INVALID_INSTANT_ACTION` | | | |
| D10.12 | `trigger` instant action | `FAILED`, `INVALID_INSTANT_ACTION` | | | |
| D10.13 | `cancelOrder` with no order active | `FAILED`, `NO_ORDER_TO_CANCEL` | | | |
| D10.14 | Bridge connected. Publish the order with the retain flag set and a fresh `seenStateHeaderId`. MQTT 3.1.1 clears the flag on delivery to a subscription that already exists, so the AGV sees a normal order. **Only with the lidar absent, never later.** Clear it at once with an empty retained message | Handled as a normal order: `DEPARTURE_REFUSED`, `TROLLEY_UNKNOWN` | | | |

### D11. Station holds back `[MOTION IF IT FAILS]`

- **Purpose:** with `NOT_READY` showing, the station sends nothing.
- **Before you start:** D9 passed. AGV at home in AUTO, floor cleared, E-stop person in place. Real station running. Test sender closed.
- **Steps:**
  1. Press MRU1 button A.
  2. Watch the `order` topic for 60 s, as user `watch`. D2 proved this watcher would show an order.
  3. Read the station screen.
- **Expected:** no message on `order`. The call shows QUEUED, type A. LED blinks. Screen shows why the AGV is not free: unknown trolley.
- **Confirm by:** watcher window, station screen, machine person. Cancel the call afterwards.

Result: ________ Date: ________ Initials: ________

## 10. Group E: rear lidar

**This group is the first time the "no lidar, every order refused" fail-safe is gone.** A healthy lidar
means a button or a saved call could cause the first automatic departure before G's owner go-ahead.

**For every test in this group, unless the test says otherwise:**

- Real station app **stopped** and test sender closed, so no call and no order can exist.
- Selector MANUAL, MANUAL ARM off.
- Calling switch **off**. Read the lidar with `ros2 topic echo /amr/rear/trolley` (Common tools). In these tests "`loads`" means its `state` field, and "field state" means its `rear_field` field.
- Switch **on**, with the station still stopped, only for E3 step 4, E7, E8, E9 and E10, because `loads` and `NOT_READY` exist only on `state`. Restart the service after each change. The switch goes back off for E11 and group F.
- People at the hitch only with the selector in MANUAL. Field tests use the test object or the stand-in target, by rope (section 3).

### E1. Owner's decision on the rear field while towing `[NO MOTION]` `[OWNER GO]`

- **Purpose:** the hitched trolley sits in the scanner's view. How that field behaves when towing is a **safety hardware decision. Software does not decide it.** Today no safe inputs are reserved for a rear scanner on the safety controller, and the safety budget has little room left for one more device.
- **Before you start:** nothing is fitted until this decision is written.
- **Steps:**
  1. The owner writes down: the rear field's size with no trolley and with one, how it is switched, what happens to the vehicle when it is broken (does it stop the wheels by hardware, or only report?), and who verifies it.
  2. Write down how the rear scanner reaches the AGV PC. `enp3s0` has one peer today, so a switch or a network card is needed.
  3. Write down the monitoring cases and what selects them. **Case selection must never come from the lidar's trolley detection, which is not safety rated and reads a person as a trolley.** Write down the route for the rear case gate (AGV plan 3.3): the driver reports the active case in `rear_case` (not verified, the driver is not in the repo, AGV plan V18), or the safety engineer proves in hardware that no towing case can stay selected with no trolley.
- **Expected:** a dated decision. Groups E to L use that decision for their "per decision" results.
- **Confirm by:** owner's signature.

Decision reference: ________ Owner: ________ Date: ________

### E2. Mounting `[NO MOTION]`

- **Purpose:** the scanner is secure, and it sees what it must see.
- **Before you start:** E1 decided. AGV on stands or power off during fitting.
- **Steps:**
  1. Check the mount is rigid: push on it by hand.
  2. Measure scanner height and write it down. Check it's level.
  3. Hitch the largest and smallest trolley. Swing each to its full angle by hand. Check nothing touches the scanner or its cable.
  4. Check the window is clean and nothing on the AGV blocks the view. Compare with the safety configuration's blanked areas.
- **Expected:** rigid, level, clear of every trolley, cable protected.
- **Confirm by:** photos, measurements.

Height: ________ mm

Result: ________ Date: ________ Initials: ________

### E3. Front side unchanged `[NO MOTION]`

- **Purpose:** adding a scanner must not disturb the front one or heat up the PC.
- **Before you start:** E2 passed. Rear scanner running.
- **Steps:**
  1. On the AGV: `ros2 topic hz /scan`, `ros2 topic hz /output_paths`. Compare with what they gave before.
  2. Repeat the front field check of A5, step 4.
  3. Check CPU load and temperature with `manuals/cpu-load-plan.md`. The N97 has been seen above 80 C.
  4. Switch on, restart, station still stopped. Check `NOT_READY` no longer lists `TROLLEY_UNKNOWN` or `REAR_FIELD_UNKNOWN` while healthy. If the rear case gate is not met yet, `REAR_FIELD_UNKNOWN` stays, and that is correct: write it down. Switch off, restart.
- **Expected:** front topics as before. Front field as before. Temperature within the plan's limit.
- **Confirm by:** command output.

CPU temperature: ________ C

Result: ________ Date: ________ Initials: ________

### E4. Safety field with no trolley `[NO MOTION]`

- **Purpose:** the field is where the configuration says it is.
- **Before you start:** E3 passed. Selector MANUAL, MANUAL ARM off. No trolley.
- **Steps:**
  1. With the test object on its stand, start outside the field and pull it in slowly by rope from straight behind, 45 degrees left, 45 degrees right, directly left, directly right.
  2. Mark on the floor where the state changes, once the object has been stopped and nobody else is in the zone.
  3. Measure each mark against the configuration.
- **Expected:** marks match the configured field within the verification tolerance. `rear_field` shows violated in the field, clear out of it. Polarity checked against the rear scanner's configuration.
- **Confirm by:** floor marks, `/amr/rear/trolley`.

Result: ________ Date: ________ Initials: ________

### E5. Safety field with a trolley hitched `[NO MOTION]`

- **Purpose:** check what the field really does with a trolley in view, for every type.
- **Before you start:** E4 passed. All six types.
- **Steps, for each type:**
  1. Hitch the trolley in straight line.
  2. Read the rear field state.
  3. Pull the test object in by rope from behind the trolley and from each side of the trolley. For the gap between AGV and trolley, press the E-stop, set the object in the gap, leave the zone, then read.
  4. Swing the trolley to its full left and right angle and repeat step 2.
- **Expected:** per the E1 decision. Whatever is found, the table must say what the field does and where the object is **not** seen. Every unseen area goes to the owner at L. The case of the trolley gone with the towing case still selected is in E11.
- **Confirm by:** AGV page, floor sketch for each type.

| Type | Field with trolley hitched | Object seen behind | Object seen at sides | Object seen in gap | Result | Date | Initials |
|---|---|---|---|---|---|---|---|
| A | | | | | | | |
| B | | | | | | | |
| C | | | | | | | |
| E | | | | | | | |
| F | | | | | | | |
| G | | | | | | | |

### G1. Can the drive wheels be lifted? `[NO MOTION]` `[OWNER GO]`

- **Purpose:** decide whether the wheels-off-the-floor stage is possible, before relying on it. It sits here, and keeps its name, because E6 needs the answer as well as G3. Drive wheels on chocks while powered is **not** allowed. Blocks means lifted, wheels spinning free.
- **Before you start:** E5 passed. AGV off. Selector MANUAL. A rated jack and stands. Bench work "on blocks" has been done on this vehicle before (RUNBOOK and README), but check again with today's fit-out, including the rear lidar.
- **Steps:**
  1. Lift the AGV on stands so that both drive wheels spin free.
  2. Check it's stable. Push it from both sides.
  3. Power on. Check the Home page: does the line sensor still read the tape? Lifting raises the sensor off the tape.
  4. If not, try a loose strip of tape on packing under the sensor, at the normal gap. Check the reading.
  5. Press **At home** and look at the at-home check. Does the locator still accept it?
  6. Write down what's available: `AGV lifted` and `line reading good` and `at home accepted`. All three are needed for G3.
- **Expected:** a clear yes or no. If no, G3 is marked N/A with the reason and the owner's initials, and G4's risk is discussed with the owner.
- **Confirm by:** photos, Home page.

Possible: ________ Owner go-ahead for lifting: ________ Date: ________

Result: ________ Date: ________ Initials: ________

### E6. Does the field stop the wheels? `[MOTION]` `[OWNER GO]`

- **Purpose:** a field that only reports is not protection. This test proves the stop path that E1 decided on.
- **Before you start:** G1 done. AGV lifted if G1 said yes for lifting (only `AGV lifted` is needed here), otherwise at 0.2 m/s on a cleared floor in manual jog with the E-stop person ready. Test object on stand, with its rope.
- **Steps:**
  1. Run the wheels slowly with no trolley.
  2. Pull the test object into the rear field by rope.
  3. Note what stops the wheels and how quickly. Clear the field. Note how it restarts.
  4. Repeat with a trolley hitched, if E1 says the field is active when towing.
- **Expected:** per the E1 decision. If E1 chose a reporting-only field, this test records that plainly, and the owner signs that fact at L.
- **Confirm by:** stopwatch, AGV event log, safety controller status.

Owner go-ahead: ________ Date: ________

Result: ________ Date: ________ Initials: ________

### E7. Detects each of the six trolley types `[NO MOTION]`

- **Purpose:** the AGV must say "trolley" for all six, empty and full.
- **Before you start:** E6 passed. Switch on, station stopped, selector MANUAL. All six types, one empty and one loaded with a real load, if possible.
- **Steps, for each row, three times:**
  1. Bring the trolley to the hitch and hitch it. Time until `loads` shows the trolley.
  2. Swing it left and right by hand. `loads` must not change.
  3. Unhitch and take it right away. Time until `loads` shows `[]`.
- **Expected:** present every time, absent every time. `loadType` is `TROLLEY`, never the letter. Latency is short and repeatable. The screen does not flicker between states.
- **Confirm by:** AGV page, watcher window for `loads`.

| Type | Empty: hitched, removed, 3 of 3 | Full: hitched, removed, 3 of 3 | Latency in, out (s) | Result | Date | Initials |
|---|---|---|---|---|---|---|
| A | | | | | | |
| B | | | | | | |
| C | | | | | | |
| E | | | | | | |
| F | | | | | | |
| G | | | | | | |

### E8. False "present": no trolley, but the lidar says one `[NO MOTION]`

- **Purpose:** this is a nuisance, not a danger: the AGV refuses to leave. Learn how often it happens and where.
- **Before you start:** E7 passed. Switch on, station stopped, selector MANUAL. Nobody in the zone when reading.
- **Steps, one row at a time, reading `loads`:**
- **Expected:** `[]` in every row, except E8.1, where a person-sized target may well read as a trolley (AGV plan 3.2): write down what it reads. Record any exceptions and show the owner. Rows E8.7 to E8.9 need the AGV at real stops, so they are done on card F5.
- **Confirm by:** AGV page.

| ID | Set-up | `loads` | Result | Date | Initials |
|---|---|---|---|---|---|
| E8.1 | Stand-in target, person-sized, set where a trolley would be. **Never a person** | | | | |
| E8.2 | Unhitched trolley 0.5 m behind | | | | |
| E8.3 | Unhitched trolley 1 m behind | | | | |
| E8.4 | Unhitched trolley 2 m behind | | | | |
| E8.5 | Pallet or crate behind the AGV | | | | |
| E8.6 | AGV parked at HOME-N: wall and bay surroundings | | | | |

### E9. False "absent": trolley hitched, but the lidar says none `[NO MOTION]`

- **Purpose:** **this one is dangerous.** A hitched trolley reported as absent could allow a departure with it on, and a U-turn with a payload, which the AGV cannot do. There must be no such case.
- **Before you start:** E7 passed. Switch on, station stopped, selector MANUAL. Nobody in the zone when reading.
- **Steps, one row at a time. Hold for 60 s and watch `loads` the whole time:**
- **Expected:** `loads` shows `TROLLEY` for the whole 60 s, in every row. **One false "absent" fails group E**, and the Lead goes to the owner.
- **Confirm by:** watcher window with `loads`, saved to a file.

| ID | Set-up | Any "absent" seen? | Result | Date | Initials |
|---|---|---|---|---|---|
| E9.1 | Each of 6 types, empty, at full left swing (6 readings) | | | | |
| E9.2 | Each of 6 types, empty, at full right swing (6 readings) | | | | |
| E9.3 | Narrowest trolley frame, light load | | | | |
| E9.4 | Black or dull surface trolley or load | | | | |
| E9.5 | Shiny or reflective trolley or load | | | | |
| E9.6 | Trolley hitched, stand-in target beside it | | | | |
| E9.7 | Trolley hitched, stand-in target blocking the scanner's view of it | | | | |
| E9.8 | Trolley hitched, a second trolley behind it | | | | |
| E9.9 | Bright light or sun on the scanner if it occurs on site | | | | |
| E9.10 | Trolley pin out, trolley still touching the hitch (should read present) | | | | |

### E10. Unknown when the scanner goes away `[MOTION IF IT FAILS]`

- **Purpose:** the fail-safe. No fresh data means unknown, never "no trolley".
- **Before you start:** E9 passed. Switch on. **Real station app stopped and test sender closed, and no button can make a call.** Selector AUTO at HOME-N with no trolley. Floor cleared, because this tests the AUTO state with a healthy lidar. E-stop person in place.
- **Steps:**
  1. Note `loads` and `NOT_READY`.
  2. Pull the rear scanner's Ethernet cable. Time until `loads` is gone from `state`.
  3. Refit. Time until it comes back.
  4. Switch off the rear scanner's power. Repeat.
  5. On the AGV, stop only the rear scanner's driver if the plan gives a way. Repeat.
  6. Kill `trolley_node` on the AGV (find it with `pgrep -f trolley_node`). It respawns by itself. Time until `loads` goes, and until it comes back.
  7. Check the front scanner stays healthy in all cases.
  8. Read the result of AGV plan V18: does the driver expose a scan counter? Write it down.
- **Expected:** each time, within 2 s, the `loads` key is left out, and `NOT_READY` shows `TROLLEY_UNKNOWN` and `REAR_FIELD_UNKNOWN`. In step 6, unknown within 0.5 s, and a full debounce after the respawn before it reads present or absent. A full settle time (5 s) follows the return. No false "no trolley" in between. Watcher file shows that it never passed through `[]` while the trolley state was truly unknown. If the driver has no scan counter, a frozen scan is **not** caught, and this residual goes to the owner at L16.
- **Confirm by:** watcher window saved to a file, stopwatch.

Unknown after: ________ s `trolley_node` killed, unknown after: ________ s Scan counter exposed: ________

Result: ________ Date: ________ Initials: ________

### E11. Where a body is seen at the hitch `[NO MOTION]`

- **Purpose:** find out where a body at the hitch is, and is not, seen. The later hazard test depends on this. This test uses a stand-in target, never a person.
- **Before you start:** E9 passed. Switch back off. **E-stop pressed the whole time, so no torque is possible.** Selector MANUAL. Stand-in targets: person-sized dummy or tube, and tubes cut to crouching and kneeling height.
- **Steps, with and without a trolley hitched:**
  1. Set the stand-in at each position in the table, then everyone leaves the zone. Hold for 10 s. Use a dark cover for one pass and a light cover for another.
  2. Read the rear field state and the `loads` value.
- **Expected:** per the E1 decision. Every position that is **not** seen is written down and goes to the owner. Trolley detection is not personnel protection: `loads` is never counted as "person seen".
- **Confirm by:** `/amr/rear/trolley`, floor sketch.

| Position | Field state, no trolley | Field state, trolley hitched | `loads` | Date | Initials |
|---|---|---|---|---|---|
| Standing behind, at the hitch | | | | | |
| Crouched at the hitch, reaching for the pin | | | | | |
| Kneeling at the hitch | | | | | |
| Bent over the hitch, feet back | | | | | |
| Between AGV and trolley | | | | | |
| Beside the hitch, left | | | | | |
| Beside the hitch, right | | | | | |
| Beside the AGV body, left | | | | | |
| Beside the AGV body, right | | | | | |

Result: ________ Date: ________ Initials: ________

**Named safety gate: trolley gone, towing case still selected.** A towing case with a reduced or muted
field, left selected after unhitching, could read clear with someone at the hitch (AGV plan 3.3). If E1
has no such case, the owner signs these rows N/A. Otherwise, E-stop still pressed and no trolley:

1. The safety engineer leaves the towing case selected, by the method written at E1. If the proof route was chosen, the engineer first tries to do this, and records whether the hardware allows it.
2. Set the stand-in at each position, and everyone leaves the zone. Read `rear_field` and `rear_case`. Then switch on, restart, and read `NOT_READY` at one position. Switch off, restart.

**Expected:** `rear_field` is never clear with the towing case selected. `rear_case` reports `CASE_OTHER` if the driver exposes it. If the driver does not report the case and the proof is not recorded, the case is unknown and `rear.case_proven` stays false, so `NOT_READY` shows `REAR_FIELD_UNKNOWN`. If the towing case can stay selected on the proof route, the gate is **not** met: this test fails, and no order may be sent. A clear reading here is a safety failure.

| ID | Position, trolley gone, towing case selected | `rear_field` | `rear_case` | Target seen? | Result | Date | Initials |
|---|---|---|---|---|---|---|---|
| E11.T1 | Standing behind, at the hitch | | | | | | |
| E11.T2 | Crouched at the hitch | | | | | | |
| E11.T3 | Kneeling at the hitch | | | | | | |
| E11.T4 | Bent over the hitch, feet back | | | | | | |
| E11.T5 | Where the gap to a trolley would be | | | | | | |
| E11.T6 | Beside the hitch, left | | | | | | |
| E11.T7 | Beside the hitch, right | | | | | | |

Route chosen at E1: ________ Safety engineer: ________ Date: ________

## 11. Group F: hand trips to all four machines, switch off

Switch **off**. This repeats S on the new software. With the switch off, the job, node and web must
behave as the P0 baseline, and nothing here may depend on the station.

That promise does not cover P0's two settings (`trip_calls` 1, `tape_loc.live` true) or the rear
hardware. The rear driver and `trolley_node` still run, `REAR_SCANNER_SILENT` can be raised, CPU load
is higher, and with rear OSSDs in the FX3 a rear field stop still happens on a hand trip and reads as
`estop`. So a difference from S3 caused by the job, node or web is a defect. A difference caused by
rear hardware is written down separately. F1 to F4 are then the new baseline after group E, and K4 is
compared with them.

### The hand-trip procedure (used by F1 to F4, with `n` = the machine)

Have card F5 to hand: read its rows at each stop.

1. AGV at HOME-N, selector MANUAL. **At home** → confirm → READY. Selector AUTO, MANUAL ARM off.
2. Run → Calls: tap **Trolleys off at HOME**. Tap **MRU`n`**.
3. Press START at home. Horn for 2 s. AGV goes through R717 and stops at ATT.
4. Hitch empty trolley. Step clear. Press START. Horn. AGV stops at MW-`n`.
5. Release: brake on, pin out, move trolley clear. Step clear. Press START. Horn.
6. Watch the U-turn. AGV stops at ME-`n`.
7. Hitch the waiting trolley. Step clear. Press START. Horn. AGV goes home.
8. At HOME-N unhitch, move it clear. Tap **Trolleys off at HOME**.

Four START presses in all with the switch off.

### F1. MRU1 by hand `[MOTION]`

- **Purpose:** MRU1 on the new software, mid-line U-turn at UT-MRU1.
- **Before you start:** group E passed. Switch off, confirmed on the AGV. `ss -tnp | grep 1883` shows nothing. Cleared floor. One empty trolley at ATT, one at ME-1. `cruise_mps` 0.2 first, then 0.4.
- **Steps:** the hand-trip procedure, `n` = 1, once at 0.2 m/s and once at 0.4 m/s.
- **Expected:** as S2. Stops within ±10 cm. Same message sequence as S3. Timing close to S3 at the same speed.
- **Confirm by:** tape measure, Run page and event log, `tools/run_log.sh` log compared with S3.

| Speed | ATT cm | MW-1 cm | ME-1 cm | HOME-N cm | Same as S3? |
|---|---|---|---|---|---|
| 0.2 | | | | | |
| 0.4 | | | | | |

Differences from S3 caused by rear hardware: ________

Result: ________ Date: ________ Initials: ________

### F2. MRU2 by hand `[MOTION]`

- **Purpose:** MRU2, mid-line U-turn at UT-MRU2.
- **Before you start:** F1 passed. Trolleys set for MRU2.
- **Steps:** the hand-trip procedure, `n` = 2, once at 0.2 m/s and once at 0.4 m/s.
- **Expected:** as F1, for stops MW-2 and ME-2. AGV drives past MW-1 and ME-1 without stopping.
- **Confirm by:** as F1.

| Speed | ATT cm | MW-2 cm | ME-2 cm | HOME-N cm |
|---|---|---|---|---|
| 0.2 | | | | |
| 0.4 | | | | |

Result: ________ Date: ________ Initials: ________

### F3. MRU3 by hand `[MOTION]`

- **Purpose:** MRU3, mid-line U-turn at UT-MRU3.
- **Before you start:** F2 passed. Trolleys set for MRU3.
- **Steps:** the hand-trip procedure, `n` = 3, once at 0.2 m/s and once at 0.4 m/s.
- **Expected:** as F1, for stops MW-3 and ME-3. Earlier machines passed without stopping.
- **Confirm by:** as F1.

| Speed | ATT cm | MW-3 cm | ME-3 cm | HOME-N cm |
|---|---|---|---|---|
| 0.2 | | | | |
| 0.4 | | | | |

Result: ________ Date: ________ Initials: ________

### F4. MRU4 by hand, tape-end U-turn `[MOTION]`

- **Purpose:** MRU4 is different: it has no mid-line U-turn point, so after MW-4 the AGV goes on to the tape end and pivots there at U-MRU. S5 did this first, on today's software.
- **Before you start:** F3 passed. Trolleys set for MRU4. Space around the tape end cleared and marked. Check the distance from MW-4 to the tape end.
- **Steps:** the hand-trip procedure, `n` = 4, once at 0.2 m/s and once at 0.4 m/s. E-stop person walks beside it through the pivot. Watch that it doesn't overrun the tape end.
- **Expected:** after START at MW-4, the AGV drives on to the tape end, slows, pivots clockwise, finds the tape again, drives back and stops at ME-4. No extra stop or hold on the way. The rest as F1.
- **Confirm by:** as F1, plus overrun past the tape end measured at the sensor.

| Speed | ATT cm | MW-4 cm | ME-4 cm | HOME-N cm | Overrun cm |
|---|---|---|---|---|---|
| 0.2 | | | | | |
| 0.4 | | | | | |

Result: ________ Date: ________ Initials: ________

### F5. Trolley state during hand trips `[MOTION]`

- **Purpose:** before any automatic use, see what the lidar reports through a real trip. The interlocks are inactive with the switch off, so this observes only.
- **Before you start:** have this card to hand before F1; the rows below are read during F1 to F4. Rear scanner running. Logging on.
- **Steps:**
  1. Run the hand-trip procedure for MRU1 and MRU4, towing a real load.
  2. Log the trolley state and the rear field state through the whole trip.
  3. Look at every curve, R717, X1, J-ML, J-STEM and J-SPLIT, and at each stop.
  4. E8 rows moved here because they need real stops: during F1 to F4, read the trolley `state` in the rows below, with the AGV stopped and no trolley hitched. Read ATT and ME-n before hitching, and MW-n after the trolley is moved clear.
- **Expected:** with trolley on: present throughout, and absent only with no trolley. **Any "absent" while hitched fails as E9.** The rear field does as the E1 decision says. Flicker on curves is written down for the owner. In the table: absent in every row. Exceptions go to the owner, as E8.
- **Confirm by:** saved log, graphed or read through by the Lead.

| ID | Set-up | Trolley `state` | Result | Date | Initials |
|---|---|---|---|---|---|
| E8.7 | AGV at ATT: real surroundings | | | | |
| E8.8 | AGV at each MW-n: machines and stands behind (4 readings) | | | | |
| E8.9 | AGV at each ME-n: released trolley nearby (4 readings) | | | | |

Result: ________ Date: ________ Initials: ________

### F6. Torque time and home-still check `[MOTION]`

- **Purpose:** record AGV plan P8 step 7, which G2 and sign-off L8 rely on.
- **Before you start:** F1 to F4 passed.
- **Steps:** measure the time from power request to torque over at least ten warnings from standby, using the warnings of F1 to F4 if the log shows them; otherwise run more warnings on a hand trip. With the AGV at rest, check `HOME_STILL_M` against encoder noise.
- **Expected:** a measured time and a margin the safety engineer accepts, which replace the `order_torque_wait_s` placeholder. No false `NOT_AT_HOME` at rest.
- **Confirm by:** log files kept with this card.

Measured torque time: ________ `order_torque_wait_s` set to: ________ Safety engineer: ________

Result: ________ Date: ________ Initials: ________

## 12. Group G: first automatic departure, then every refusal

From here on, switch **on**. The AGV can leave home by itself. Repeat the floor warning to everyone,
every day: "If a button is pressed, this AGV can move with no one touching it."

Only one departure is automatic. It happens only from home, only in AUTO, and keeps the 2 s horn and
all scanner stops. All other moves still need a physical START.

G1, the lifting check, was already run in group E before E6.

Before G2: repeat AGV plan P7 steps 4 to 8b with `tools/test_sender.py`, the trolley hitched and pin in, and record them here. Leave out step 6's retained order with the bridge connected. Card F6 must be done.

Result: ________ Date: ________ Initials: ________

### G2. Departure with the E-stop pressed: no torque possible `[MOTION IF IT FAILS]`

- **Purpose:** the first full order-to-horn run, and the first order the AGV can accept, with hardware making sure the wheels can't turn. The safety chain cuts torque whatever the software asks.
- **Before you start:** F passed. Switch on, restarted. AGV at HOME-N on the floor, READY, AUTO. No trolley. Rear field clear. Everyone outside the marked zone. **E-stop pressed and left pressed.** Write down the measured `order_torque_wait_s` from the profile: the 4.0 s default is a placeholder that P8 must have replaced. Check `NOT_READY` is empty, or record what it shows.
- **Watch out:** do not release the E-stop during the horn. A release and reset inside `order_torque_wait_s` can still lead to a departure with no `SETTLING`. That residual is with the safety engineer (AGV plan 3.2).
- **Steps:**
  1. Machine person presses MRU1 button A.
  2. Watch the station: the order is sent. Watch `state`.
  3. Listen for the horn. Time it. Watch the wheels.
  4. When the warning ends, read `errors` and `NOT_READY`. Time how long before `HOLDOFF` ends.
  5. Keep the E-stop pressed. Watch for 60 s after `HOLDOFF` ends: listen for a second horn, and watch the `order` topic.
  6. Cancel the call on the screen, with the E-stop still pressed, so that nothing can depart.
  7. Release the E-stop and press RESET. Read `NOT_READY`.
- **Expected:** no wheel motion. **One horn cycle only.** Horn for up to `order_torque_wait_s`, then `DEPARTURE_CANCELLED`, `HOLDOFF` for 15 s, and `TORQUE_TIMEOUT` latched. The call returns to QUEUED with a new orderId and the station holds back, so step 5 gives no second horn and no second order. Step 7: the RESET edge clears `TORQUE_TIMEOUT`, and `SETTLING` runs for 5 s. Any second horn is a fail.
- **Confirm by:** E-stop person, stopwatch, watcher window file.

Horn: ________ s `order_torque_wait_s`: ________ s Second horn seen: ________

Result: ________ Date: ________ Initials: ________

### G3. Departure with wheels lifted `[MOTION]` `[OWNER GO]`

- **Purpose:** the order reaches the real drives, with no chance of the AGV travelling. This is the first order that can turn the wheels (section 2).
- **Before you start:** G1 says yes. G2 passed. AGV on stands, E-stop person at the button. Nobody near the wheels. Agreed: selector goes to MANUAL 5 s after the wheels start, because the odometer will drift away from the real position with the AGV standing still.
- **Steps:**
  1. Machine person presses MRU1 button A.
  2. Time from order to horn, and from horn to first wheel turn.
  3. Check the wheels turn forward, both the same way.
  4. After 5 s: selector to MANUAL.
  5. Read the AGV state and the station.
- **Expected:** horn at least 2 s before any wheel turn. Wheels forward. Selector stops them at once, FAULT, trip aborted. `TRIP_ABORTED` appears. Station shows the call Aborted, LED off, no retry.
- **Confirm by:** E-stop person, stopwatch, event log.

Owner go-ahead: ________ Date: ________

Horn to wheels: ________ s

Result: ________ Date: ________ Initials: ________

### G4. First automatic departure on the floor `[MOTION]` `[OWNER GO]`

- **Purpose:** the owner's flow step 1, for real: a button, and the AGV leaves by itself and waits at ATT.
- **Before you start:** G2 passed, and G3 passed or N/A. `cruise_mps` 0.2. Route HOME-N to ATT cleared and marked. No trolley. E-stop person walking beside the AGV. Lead holds a radio to the machine person. Plan to stop at ATT.
- **Steps:**
  1. Lead calls "Button" on the radio. Machine person presses MRU1 button A once.
  2. Time horn. Watch the AGV leave and pass through R717.
  3. AGV stops at ATT. Wait 30 s. It must stay.
  4. With the owner watching, selector to MANUAL. **Recover.** The call goes Aborted.
  5. Repeat steps 1 to 4 twice.
- **Expected:** horn at least 2 s before motion. Moves at no more than 0.2 m/s. Stops at ATT within ±10 cm. Stays there. Wait action `RUNNING` and call shows AT_PICKUP, with the type on the screen and the LED blinking.
- **Confirm by:** stopwatch, tape measure, station screen, watcher window file, saved log.

Owner go-ahead: ________ Date: ________

| Run | Horn s | ATT error cm | Stays at ATT | Date | Initials |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

Result: ________ Date: ________ Initials: ________

### G5. Refusal for every precondition, one by one `[MOTION IF IT FAILS]`

- **Purpose:** each block works by itself. Each row tests two layers: the station holds back, and the AGV refuses even if an order is forced.
- **Before you start:** G4 passed. Cleared floor. E-stop person in place. Start every row from: AGV at HOME-N, READY, AUTO, no trolley, rear field clear, no call, `NOT_READY` empty.
- **Steps, for each row:**
  1. Set up the condition in the row.
  2. Read `NOT_READY`.
  3. Press MRU1 button A. Watch 15 s: the `order` topic, as user `watch`, must stay silent.
  4. Cancel that call on the screen. Force the order with the test sender. Read `errors`.
  5. Watch for horn and wheels the whole time.
  6. Undo the condition. After any jog or pivot: selector MANUAL, At home again, READY, AUTO. Check `NOT_READY` clears. Reset anything needed.
- **Expected:** the row's reason, among any others the row brings with it. No horn. No wheel motion. Refused means nothing stored: nothing happens later when the condition clears, unless a new order arrives.
- **Confirm by:** watcher window saved, E-stop person, stopwatch for the timed rows.

| ID | Condition, and how to make it | `NOT_READY` reason | Forced order gives | Result | Date | Initials |
|---|---|---|---|---|---|---|
| G5.01 | Selector MANUAL | `NOT_AUTO` | `MOBILE_ROBOT_NOT_AVAILABLE` | | | |
| G5.02 | Jog 1 m from HOME-N | `NOT_AT_HOME` | `START_NODE_OUT_OF_RANGE` | | | |
| G5.03 | After a restart, At home not pressed | `NOT_AT_HOME` | `START_NODE_OUT_OF_RANGE` | | | |
| G5.04 | Job in FAULT with no wheel movement: during a warning, selector to MANUAL and back to AUTO, as G7.5. Do not RESET | `FAULT` | `DEPARTURE_REFUSED` | | | |
| G5.05 | Trolley hitched | `TROLLEY_PRESENT` | `DEPARTURE_REFUSED` | | | |
| G5.06 | Rear scanner cable pulled | `TROLLEY_UNKNOWN`, `REAR_FIELD_UNKNOWN` | `DEPARTURE_REFUSED` | | | |
| G5.07 | Test object in rear field by rope, no trolley | `REAR_FIELD_NOT_CLEAR` | `DEPARTURE_REFUSED` | | | |
| G5.08 | Test object in front protective field by rope | `PREREQUISITE` | `DEPARTURE_REFUSED` | | | |
| G5.09 | Front scanner cable pulled: field unknown | `PREREQUISITE` | `DEPARTURE_REFUSED` | | | |
| G5.10 | Line sensor off the tape: turn the AGV slightly by jog, still within the home limit. Selector MANUAL, At home again, READY, AUTO, so that the jog's `NOT_AT_HOME` has cleared | `TAPE_NOT_SEEN` | `DEPARTURE_REFUSED` | | | |
| G5.11 | I/O island link pulled: panel stale. **Lead does this** | `NOT_AUTO` | `MOBILE_ROBOT_NOT_AVAILABLE` | | | |
| G5.12 | Drive link not healthy. **Lead picks the method and records it** | `PREREQUISITE` | `DEPARTURE_REFUSED` | | | |
| G5.13 | Control layer not LINE: Mapping mode | `operatingMode` `MANUAL` or `STARTUP` | `MOBILE_ROBOT_NOT_AVAILABLE` | | | |
| G5.14 | `tape_loc.live: false` with switch on, if the profile allows it. If it refuses to load, that is also a pass: write it down | `SITE_NOT_LIVE` | `DEPARTURE_REFUSED` | | | |
| G5.15 | Non-site mission selected on Run page | `SITE_NOT_LIVE` | `DEPARTURE_REFUSED` | | | |
| G5.16 | Call tapped on the AGV's own Run → Calls | `LOCAL_TRIP` | `OTHER_ORDER_ACTIVE` | | | |
| G5.17 | Stop the MQTT client's link: access point off | No fresh state at station | No order can reach it | | | |
| G5.18 | Selector MANUAL. Press At home, do **not** confirm that the scans align. Selector AUTO | `LOCALIZATION_NOT_READY` | `DEPARTURE_REFUSED` | | | |
| G5.19 | Small jog, a few cm, still inside the 0.5 m home limit. No At home | `NOT_AT_HOME` | `START_NODE_OUT_OF_RANGE` | | | |
| G5.20 | **AGV pivoted 180 degrees at HOME.** Selector MANUAL, jog the pivot, MANUAL ARM off, selector AUTO. Do **not** press At home. No person in front: only the stand-in target. E-stop person ready at the E-stop. Pivot it back afterwards, then step 6 | `NOT_AT_HOME`, and `TAPE_NOT_SEEN` if the sensor has lost the tape | `START_NODE_OUT_OF_RANGE` | | | |
| G5.21 | As G5.04, with the call left waiting. `POST /api/line/clear` from a PC, which is refused: "press Reset on the panel". Cancel the call before any RESET | `FAULT` stays. The `order` topic stays silent | `DEPARTURE_REFUSED` | | | |
| G5.22 | `TORQUE_TIMEOUT` latched: G2's end state, E-stop released, RESET not pressed | `TORQUE_TIMEOUT` | `DEPARTURE_REFUSED` | | | |
| G5.23 | The rear case gate not met: towing case left selected, no trolley, as E11.T1, by the safety engineer. N/A on the E11 route that makes this impossible, with owner's initials | `REAR_FIELD_UNKNOWN` | `DEPARTURE_REFUSED` | | | |

G5.20 leaves one thing untested on purpose: **heading is not measured.** A person pressing At home with the
AGV facing the wrong way would clear `NOT_AT_HOME`. At home is a procedural check by a person looking at the
vehicle. That residual goes to the owner at L16.

### G6. Settling time, one by one `[MOTION IF IT FAILS]`

- **Purpose:** a waiting call must not leave the moment any block clears, whether by the selector, Reset, an unhitch, a field going clear, a web action or an arrival. The 5 s wait was added for this and is on the owner's list to accept.
- **Before you start:** G5 passed. Stopwatch. Start each row from a ready AGV. For each row use a real waiting call and be ready: **when the wait ends the AGV will go.** Floor cleared. `cruise_mps` 0.2. Selector goes to MANUAL at ATT, then **Recover.**
- **Steps, for each row:**
  1. Put the condition in place. Press MRU1 button A. Call waits.
  2. Remove the condition and start the stopwatch at that instant.
  3. Note when `SETTLING` clears, when the horn starts, and when the wheels turn.
- **Expected:** `NOT_READY` shows `SETTLING` for 5 s, then the horn, then wheels at no less than 7 s. A second trigger during those 5 s restarts the wait.
- **Confirm by:** stopwatch, watcher window file.

| ID | Trigger | Settle s | Horn s | Wheels s | Restarted by a second trigger? | Result | Date | Initials |
|---|---|---|---|---|---|---|---|---|
| G6.1 | Selector back to AUTO | | | | | | | |
| G6.2 | RESET pressed | | | | | | | |
| G6.3 | Trolley taken away by rope. Rig it first: E-stop pressed, pin out, trolley left in place, everyone out, E-stop released, RESET, then press the button | | | | | | | |
| G6.4 | Rear field cleared (rope) | | | | | | | |
| G6.5 | Front field cleared (rope). Pull the target well clear of the route | | | | | | | |
| G6.6 | Local call cancelled on Run → Calls, so `LOCAL_TRIP` clears | | | | | | | |
| G6.7 | Site mission selected on the Run page, so `SITE_NOT_LIVE` clears | | | | | | | |
| G6.8 | Web Clear: during another row's settling wait, at about 3 s, `POST /api/line/clear` from a PC. Time from the Clear | | | | | | | |
| G6.9 | Arrival at home with no trolley, call waiting. This row is the first full called trip, so MRU1 at `cruise_mps` 0.2, as the H procedure's steps 1 to 8. At ME-1, leave a trolley in the hitch position with the pin out, so the lidar reads present and START passes. Press START, and the AGV leaves the trolley behind. Press MRU2 button A on the way home. Time from the stop at HOME-N. Nobody goes to the AGV. Write down anything the trolley going absent raises on the way | | | | | | | |
| G6.10 | Warning ended by `cancelOrder`. Queue two calls. During the first call's horn, send `cancelOrder` with the test sender. The first call goes Aborted, because the station had not marked it cancelling. There is no `HOLDOFF`. Time to the second call's horn | | | | | | | |

### G7. Warning cancelled, one by one `[MOTION IF IT FAILS]`

- **Purpose:** every check stays active during the 2 s horn. These things happen quickly, so use a rope or a helper outside the zone. Practise the timing with the AGV off first.
- **Before you start:** G6 passed. Stand-in target, rope. Floor cleared. Nobody in the zone. Use a new call for each row, because the station stops sending a call after 3 requeues in a row (G7.8).
- **Steps, for each row:**
  1. Press the button. As soon as the horn starts, cause the condition.
  2. Watch the wheels.
  3. Read `errors` and the call state.
  4. Time `HOLDOFF` if shown. If the AGV leaves after the holdoff, let it go to ATT, then selector MANUAL. **Recover.**
- **Expected:** no wheel motion from the cancelled warning. `DEPARTURE_CANCELLED`, then `SETTLING` restarted and `HOLDOFF` for 15 s. Same queue place and a new orderId, as the row says. A horn does not start again within 15 s.
- **Confirm by:** watcher window file, E-stop person, stopwatch.

| ID | During the horn | Expected | Result | Date | Initials |
|---|---|---|---|---|---|
| G7.1 | Pull stand-in target into the front field | `DEPARTURE_CANCELLED`, re-queued, `HOLDOFF` 15 s | | | |
| G7.2 | Pull stand-in target into the rear field | `DEPARTURE_CANCELLED`, re-queued, `HOLDOFF` 15 s | | | |
| G7.3 | Rear scanner link broken from outside the zone: a pull cord rigged on the connector with the E-stop pressed beforehand, or a switch port or patch point outside the zone. Nobody at the AGV. If neither can be rigged, the Lead marks the row N/A with the owner's initials | `DEPARTURE_CANCELLED`, re-queued | | | |
| G7.4 | Press START | No effect on the warning, no second horn | | | |
| G7.5 | Selector to MANUAL. Back to AUTO afterwards, and RESET for the FAULT. **Be ready: the requeued call re-sends by itself once `SETTLING` and `HOLDOFF` end** | No motion from the warning. `DEPARTURE_CANCELLED`, re-queued, `HOLDOFF` 15 s (AGV plan R1). `FAULT` stays in `NOT_READY` until RESET. Never `TRIP_ABORTED` | | | |
| G7.6 | Press RESET. **Be ready: with no further action, the requeued call re-sends and the AGV leaves once `HOLDOFF` ends** | No motion from the warning. `DEPARTURE_CANCELLED`, re-queued, `HOLDOFF` 15 s (AGV plan R1). Never `TRIP_ABORTED` | | | |
| G7.7 | Press E-stop. Keep it pressed until the warning has ended. Cancel the call on the screen, then release and RESET | No motion. No hold. Warning cancelled at `order_torque_wait_s`, `DEPARTURE_CANCELLED`, `TORQUE_TIMEOUT` latched until the RESET | | | |
| G7.8 | One call, and repeat G7.1 three times on it, waiting out each `HOLDOFF` | Requeued each time. After the third, the station stops sending that call and raises a banner that needs an acknowledge. No fourth horn until a person acknowledges | | | |

### G8. A route that cannot be built `[MOTION IF IT FAILS]` `[OWNER GO]`

- **Purpose:** the "route not taught" refusal. It takes a change to taught data, so the owner decides whether it's worth doing on the vehicle.
- **Before you start:** G7 passed. Back-up of marks and stations taken. The active graph name written down.
- **Steps:**
  1. On the Teach page, make a test graph with ME-4's role removed: Set role → `-`, Build, Publish, Make active. A published graph never changes, so the old one stays safe.
  2. Restart the tape layer. Force an MRU4 order.
  3. Put the old graph back, restart the tape layer. Check Roles. Repeat A2.
- **Expected:** step 2 gives `NO_ROUTE_TO_TARGET`, no horn, no motion. After step 3 Roles shows all 13 again.
- **Confirm by:** watcher window, Teach page.

Owner go-ahead: ________ Date: ________

Result: ________ Date: ________ Initials: ________

## 13. Group H: full call cycles

### The call-cycle procedure (used across this group)

| Step | Who | Does what | AGV state | Call state on screen | LED |
|---|---|---|---|---|---|
| 1 | Machine | Presses button of the wanted empty trolley type | At HOME-N | QUEUED, right type | Blink |
| 2 | Nobody | The AGV gives 2 s horn and leaves by itself | Driving | TO_PICKUP | Blink |
| 3 | Warehouse | Reads the type on screen. Hitches that trolley. Steps clear. Presses START | Stopped at ATT | AT_PICKUP | Blink |
| 4 | Nobody | Horn, then AGV drives to the machine | Driving | TO_MACHINE | **Solid** |
| 5 | Machine | Takes the empty trolley. Steps clear. Presses START | Stopped at MW-n | AT_RELEASE | **Off** |
| 6 | Nobody | Horn, moves a little, U-turns empty | Driving | TURNING | Off |
| 7 | Machine | Hitches the full trolley. Steps clear. Presses START | Stopped at ME-n | AT_ATTACH | Off |
| 8 | Nobody | Horn, returns home | Driving | RETURNING | Off |
| 9 | Warehouse | Unhitches the full trolley, moves it clear | At HOME-N | Closed | Off |

Three physical START presses with the switch on. The LED off point at step 5 is an assumption. See H6.

Step 9 puts a person at the hitch at home. Until J8 has passed, no other call may be waiting then: cancel it on the screen, or selector to MANUAL first (section 3). The "unhitch with a call waiting" job is first done in J5 to J8.

### H1 to H4. First full cycle on each machine `[MOTION]`

- **Purpose:** the whole owner's flow, with everything watched and recorded at every step.
- **Before you start:** group G passed. LED flag on. One empty trolley of the right type at ATT, one "full" trolley at the ME-n spot. `cruise_mps` 0.2 for the first run on each machine, then 0.4. No "Trolleys off" tap is needed with the switch on: the lidar does that job. Confirm that.
- **Steps:** the call-cycle procedure, once for each machine, at each speed.
- **Expected:** each row of the table is true at each step. Press from that machine ignored at every step. Stops within ±10 cm. Call closes on arrival at home with the full trolley still hitched.
- **Confirm by:** station screen, machine person on LED, `state` saved through the run, tape measure at stops.

| ID | Machine | U-turn | Type | Speed | All 9 steps right | Press ignored | Stops within ±10 cm | Date | Initials |
|---|---|---|---|---|---|---|---|---|---|
| H1.a | MRU1 | UT-MRU1 | A | 0.2 | | | | | |
| H1.b | MRU1 | UT-MRU1 | A | 0.4 | | | | | |
| H2.a | MRU2 | UT-MRU2 | B | 0.2 | | | | | |
| H2.b | MRU2 | UT-MRU2 | B | 0.4 | | | | | |
| H3.a | MRU3 | UT-MRU3 | C | 0.2 | | | | | |
| H3.b | MRU3 | UT-MRU3 | C | 0.4 | | | | | |
| H4.a | MRU4 | tape end U-MRU | E | 0.2 | | | | | |
| H4.b | MRU4 | tape end U-MRU | E | 0.4 | | | | | |

Check with the watcher window, as user `watch`, at least once, on `order` and on `state`: **the trolley
type is never sent to the AGV.** The word "TROLLEY" is the only load type on the wire.

### H5. Every button type on every machine `[MOTION]`

- **Purpose:** every one of the 24 button-to-screen paths works through a real trip. These trips also count toward the soak trips in K1.
- **Before you start:** H1 to H4 passed. `cruise_mps` 0.4. Warehouse has all six types. Trolleys need not match if none is available. Nothing checks that, as H9 shows.
- **Steps, for each row:**
  1. Press the row's button. Warehouse person reads the type aloud from the screen.
  2. Run the call-cycle procedure.
- **Expected:** the screen type matches the button at every stage. Call closes at home.
- **Confirm by:** Station person, Warehouse person.

| Machine | A | B | C | E | F | G |
|---|---|---|---|---|---|---|
| MRU1 | | | | | | |
| MRU2 | | | | | | |
| MRU3 | | | | | | |
| MRU4 | | | | | | |

(Write date and initials in each cell.)

Group result: ________ Date: ________ Initials: ________

### H6. LED off point, seen by the owner `[MOTION]` `[OWNER GO]`

- **Purpose:** "LED off from arrival at the machine onward" is an assumption. The owner watches it and decides.
- **Before you start:** H1 passed. Owner and a real machine operator at the machine.
- **Steps:**
  1. Run one call cycle.
  2. Watch the LED: blink at press, solid from the time the AGV leaves pickup, off on arrival.
  3. Ask the operator: does this tell you what you need? Should it stay on until the AGV leaves?
- **Expected:** the owner accepts it as is, or asks for a change, which then goes back through the station plan and this group.
- **Confirm by:** owner's decision below.

Owner go-ahead: ________ Decision: ________ Date: ________

Result: ________ Date: ________ Initials: ________

### H7. START interlocks `[MOTION IF IT FAILS]`

- **Purpose:** the lidar stops a START in the wrong trolley state. A refused START gives no horn and no motion.
- **Before you start:** H1 passed. Run a cycle to the stop in each row, then do the row. Machine MRU1, and again with MRU4.
- **Steps, for each row:**
  1. Put the trolley in the wrong state.
  2. Press START. Listen for horn, watch wheels. Read `errors`.
  3. Correct the trolley state.
  4. Press START again and check the AGV moves on normally.
- **Expected:** no horn and no motion at step 2. Call state unchanged, and action stays `RUNNING`. `START_REFUSED` shows at once with the reason. The station shows the reason. The next press clears it. H7.8 happens on the move, so it follows its own row, not steps 1 to 4.
- **Confirm by:** E-stop person, watcher window, station screen.

| ID | Stop | Wrong state | Reason | MRU1 | MRU4 | Date | Initials |
|---|---|---|---|---|---|---|---|
| H7.1 | ATT | No trolley | `NO_TROLLEY` | | | | |
| H7.2 | ATT | Rear scanner cable pulled | `TROLLEY_UNKNOWN` | | | | |
| H7.3 | MW-n | Trolley still hitched | `TROLLEY_STILL_ON` | | | | |
| H7.4 | MW-n | Trolley unhitched but left in the hitch position | `TROLLEY_STILL_ON` | | | | |
| H7.5 | MW-n | Rear scanner cable pulled | `TROLLEY_UNKNOWN` | | | | |
| H7.6 | ME-n | No trolley | `NO_TROLLEY` | | | | |
| H7.7 | ME-n | Rear scanner cable pulled | `TROLLEY_UNKNOWN` | | | | |
| H7.8 | Between MW-4 and the tape end, MRU4 only. **This row is `[MOTION]`:** cleared floor, `cruise_mps` 0.2. Mark the floor 1.5 m before the tape end. With START at MW-4 passed and the trolley absent, kill `trolley_node` over SSH as the AGV passes the mark, so the state goes `UNKNOWN`. Write down the distance left. If it reads absent again before the pivot point, repeat with a later kill | Not absent | No pivot. Either a hold with cause `trolley` before the pivot, or FAULT from the tape-end check. Write down which | n/a | | | |

### H8. START passes, then the warning is cancelled `[MOTION IF IT FAILS]`

- **Purpose:** a stop's own warning can still be cancelled, and the AGV must stay put.
- **Before you start:** H7 passed. Stand-in target and rope. AGV stopped at ATT with trolley hitched.
- **Steps:**
  1. Press START. As the horn starts, pull the target into the front field.
  2. Read `errors`. Clear the field. Press START.
  3. Repeat at MW-n and ME-n.
- **Expected:** no motion from the cancelled warning. `START_REFUSED` with `WARNING_CANCELLED`. Action stays `RUNNING`. Next START works. Call state unchanged.
- **Confirm by:** watcher window, E-stop person.

Result: ________ Date: ________ Initials: ________

### H9. Wrong type hitched `[MOTION]`

- **Purpose:** record the known limit. The AGV doesn't know the type.
- **Before you start:** H1 passed.
- **Steps:**
  1. Call type A from MRU1.
  2. At ATT, hitch type B. Press START.
- **Expected:** the AGV goes on. This is by design: type goes only as far as the screen. If the owner wants a check, that's a new decision.
- **Confirm by:** the AGV leaves with type B. The owner sees the note at L.

Result: ________ Date: ________ Initials: ________

## 14. Group I: faults at every call stage

**Reminder of the stages:** QUEUED, TO_PICKUP (warning), TO_PICKUP (moving), AT_PICKUP, TO_MACHINE,
AT_RELEASE, TURNING, AT_ATTACH, RETURNING.

Every card below has one row per stage. Run one cycle to that stage, do the fault, read the result,
then **Recover** if the call aborted. `cruise_mps` 0.4 unless a card says less. Use a machine with a
mid-line U-turn for all rows. Repeat the TURNING rows once on MRU4 for its tape-end turn. "n/a" in a
row with a stated reason needs no owner's initials.

After each row check: the LED matches the call state, and after the call closes the machine's button
works again. **On any row: an AGV moving after an abort, or a new move with no fresh order or
START, is a safety failure.**

### I1. Wi-Fi lost `[MOTION]`

- **Purpose:** the AGV finishes its released order on its own. Its local safety stays in charge.
- **Before you start:** group H passed. How to do it: switch off access point `agv_field`. Tablets lose AGV pages, so use the AGV's own screen.
- **Steps:** at each stage: switch off the access point. Carry on with the normal physical STARTs for 1 minute, or until the trip ends. Switch on again.
- **Expected:** AGV carries on as if nothing happened: START, stops and scanners are all local. Station shows "AGV link lost" within 3 s and freezes the call state. When Wi-Fi returns, the state catches up by itself, even as far as Closed. QUEUED: no order sent while lost, and it's sent when the AGV is free again.
- **Confirm by:** AGV's own screen, station screen, stopwatch.

| Stage | Result | Link lost s | Caught up to | Date | Initials |
|---|---|---|---|---|---|
| QUEUED | | | | | |
| TO_PICKUP warning | | | | | |
| TO_PICKUP moving | | | | | |
| AT_PICKUP | | | | | |
| TO_MACHINE | | | | | |
| AT_RELEASE | | | | | |
| TURNING | | | | | |
| AT_ATTACH | | | | | |
| RETURNING | | | | | |

### I2. Broker stopped `[MOTION]`

- **Purpose:** same as I1, seen from the other end.
- **Before you start:** I1 passed. How to do it: `net stop mosquitto` on the station PC.
- **Steps:** at each stage: stop the broker. Carry on for 1 minute or until the trip ends. Start the broker.
- **Expected:** as I1. After the restart there is no retained message, so the station reads not online until the AGV reconnects and publishes `ONLINE`. Nothing moves because of the broker coming back.
- **Confirm by:** station screen, AGV Home page.

| Stage | Result | Reconnect s | Date | Initials |
|---|---|---|---|---|
| QUEUED | | | | |
| TO_PICKUP warning | | | | |
| TO_PICKUP moving | | | | |
| AT_PICKUP | | | | |
| TO_MACHINE | | | | |
| AT_RELEASE | | | | |
| TURNING | | | | |
| AT_ATTACH | | | | |
| RETURNING | | | | |

### I3. Station restart `[MOTION]`

- **Purpose:** the AGV doesn't notice. The station reloads its call list and catches up.
- **Before you start:** I2 passed. How to do it: stop the station with `taskkill /F /PID <pid>`, start again after 30 s.
- **Steps:** at each stage: kill the station. Carry on 30 s. Start it again. Read the screen. Then, on the TO_MACHINE row only, kill it again, delete the saved call list, and start.
- **Expected:** call restored with machine and type, and the right state and LED, within 5 s of `state` arriving. No order re-sent for a call the AGV has. Presses during the outage are lost, and the operator presses again. With the file deleted: the active order is adopted, with the machine from the orderId and type shown as unknown.
- **Confirm by:** station screen, machine person on LED.

| Stage | Result | Restored state | LED right | Date | Initials |
|---|---|---|---|---|---|
| QUEUED | | | | | |
| TO_PICKUP warning | | | | | |
| TO_PICKUP moving | | | | | |
| AT_PICKUP | | | | | |
| TO_MACHINE | | | | | |
| TO_MACHINE, list deleted | | | | | |
| AT_RELEASE | | | | | |
| TURNING | | | | | |
| AT_ATTACH | | | | | |
| RETURNING | | | | | |

### I4. AGV reboot `[MOTION]` `[OWNER GO]`

- **Purpose:** an AGV restart loses the order, and it must stay still afterwards.
- **Before you start:** I3 passed. Lower speed, `cruise_mps` 0.2, on the moving rows. How to do it: `sudo reboot` over SSH. E-stop person at hand. Have the AGV on a straight, for the moving rows.
- **Steps:** at each stage: reboot. Watch how the AGV stops, and how quickly. Wait for the service. Read `state`. Read the station. **Recover.**
- **Expected:** a moving AGV stops (drive heartbeat). It does not move again by itself. `state` goes through `STARTUP`, then `orderId ""`. Call goes to Aborted, LED off, no retry. If the call was only QUEUED, it stays and waits. Nothing moves until a fresh order after At home and all checks.
- **Confirm by:** stopwatch, E-stop person, watcher window, station screen.

Owner go-ahead for reboot while moving: ________ Date: ________

| Stage | Result | Stopped in s | Call became | Date | Initials |
|---|---|---|---|---|---|
| QUEUED | | n/a | | | |
| TO_PICKUP warning | | | | | |
| TO_PICKUP moving | | | | | |
| AT_PICKUP | | n/a | | | |
| TO_MACHINE | | | | | |
| AT_RELEASE | | n/a | | | |
| TURNING | | | | | |
| AT_ATTACH | | n/a | | | |
| RETURNING | | | | | |

### I5. Selector out of AUTO `[MOTION]`

- **Purpose:** in a trip, leaving AUTO stops the vehicle and ends the trip, even when parked at a stop.
- **Before you start:** I4 passed.
- **Steps:** at each stage: selector to MANUAL. Read `state` and the station. Selector back to AUTO. Check nothing moves. **Recover.**
- **Expected:** immediate stop. Job goes FAULT. `TRIP_ABORTED` with the orderId. Call goes Aborted, LED off, no retry. Moving AGV stops at once. A trolley may be on: it's taken off by hand. QUEUED row: call stays, `NOT_AUTO`, then waits 5 s after return (`SETTLING`) and goes ahead. Be ready for it. TO_PICKUP warning row: see G7.5: `DEPARTURE_CANCELLED` and re-queued, per AGV plan R1, not Aborted.
- **Confirm by:** Run page, watcher window, station screen.

| Stage | Result | Call became | Date | Initials |
|---|---|---|---|---|
| QUEUED | | | | |
| TO_PICKUP warning | | | | |
| TO_PICKUP moving | | | | |
| AT_PICKUP | | | | |
| TO_MACHINE | | | | |
| AT_RELEASE | | | | |
| TURNING | | | | |
| AT_ATTACH | | | | |
| RETURNING | | | | |

### I6. RESET pressed `[MOTION]`

- **Purpose:** RESET ends the trip. Other waiting calls stay.
- **Before you start:** I5 passed. A second waiting call from another machine for at least one row.
- **Steps:** at each stage: press RESET. Read `state` and the station. **Recover.**
- **Expected:** AGV stops. `TRIP_ABORTED`. Call goes Aborted. Other queued calls stay in place, in order. They don't move the AGV until it's home, READY and past the settling time. QUEUED row: pressing RESET gives `SETTLING` for 5 s only. TO_PICKUP warning row: see G7.6: `DEPARTURE_CANCELLED` and re-queued, per AGV plan R1, not Aborted. Be ready: it re-sends by itself after `HOLDOFF`.
- **Confirm by:** Run page, watcher window, station list.

| Stage | Result | Call became | Other call kept | Date | Initials |
|---|---|---|---|---|---|
| QUEUED | | | | | |
| TO_PICKUP warning | | | | | |
| TO_PICKUP moving | | | | | |
| AT_PICKUP | | | | | |
| TO_MACHINE | | | | | |
| AT_RELEASE | | | | | |
| TURNING | | | | | |
| AT_ATTACH | | | | | |
| RETURNING | | | | | |

### I7. E-stop `[MOTION]`

- **Purpose:** the stop works, and what happens next is as AGV plan O13 says.
- **Before you start:** I6 passed.
- **Known mismatch:** the operation manual, 10.7, says that after an E-stop you press RESET and then START and the vehicle continues. By current code any RESET outside IDLE ends the job, so every E-stop on a station trip ends Aborted, recovered by hand. AGV plan O13 keeps this as the default, and the manual is to be corrected. If the owner answers O13 differently, these rows change first. Bring the result to the owner at L.
- **Steps:** at each stage: E-stop person presses the E-stop. On the QUEUED row, press it first and then the machine's button. Read `state`. On the QUEUED and warning rows, wait until the warning has ended, and cancel the waiting call on the screen before the RESET, because otherwise it re-sends by itself. Release it. Press RESET. Read `state` and the station. **Recover** if the call is gone.
- **Expected:** wheels stop at once by hardware, and the row's result. `activeEmergencyStop` is shown only and is inferred: `NONE` does not prove that no E-stop is pressed. No motion after RESET without a fresh order or START in any case.
- **Confirm by:** E-stop person, watcher window, station.

| Stage | Expected during the E-stop | Expected after RESET | Result | During hold, as seen | After RESET, as seen | Date | Initials |
|---|---|---|---|---|---|---|---|
| QUEUED | No hold, job stays idle, `NOT_READY` stays empty, so the order goes out. One horn cycle, then `DEPARTURE_CANCELLED` at `order_torque_wait_s`, `TORQUE_TIMEOUT` latched, call re-queued, as G2 | `TORQUE_TIMEOUT` clears, `SETTLING` 5 s | | | | | |
| TO_PICKUP warning | No hold. Warning cancelled at `order_torque_wait_s`, `DEPARTURE_CANCELLED`, `TORQUE_TIMEOUT` latched, call re-queued, as G7.7 | `TORQUE_TIMEOUT` clears, `SETTLING` 5 s | | | | | |
| TO_PICKUP moving | Hold `estop`, `AGV_HOLD`, `activeEmergencyStop` `MANUAL`. Call state unchanged | `TRIP_ABORTED`, call Aborted | | | | | |
| AT_PICKUP | Parked: the hold stays `station`, no `AGV_HOLD`. Call state unchanged | `TRIP_ABORTED`, call Aborted | | | | | |
| TO_MACHINE | Hold `estop`, `AGV_HOLD`, `activeEmergencyStop` `MANUAL`. Call state unchanged | `TRIP_ABORTED`, call Aborted | | | | | |
| AT_RELEASE | Parked: the hold stays `station`, no `AGV_HOLD`. Call state unchanged | `TRIP_ABORTED`, call Aborted | | | | | |
| TURNING | Hold `estop`, `AGV_HOLD`, `activeEmergencyStop` `MANUAL`. Call state unchanged | `TRIP_ABORTED`, call Aborted | | | | | |
| AT_ATTACH | Parked: the hold stays `station`, no `AGV_HOLD`. Call state unchanged | `TRIP_ABORTED`, call Aborted | | | | | |
| RETURNING | Hold `estop`, `AGV_HOLD`, `activeEmergencyStop` `MANUAL`. Call state unchanged | `TRIP_ABORTED`, call Aborted | | | | | |

### I8. Protective field `[MOTION]`

- **Purpose:** the scanner stop keeps working through every stage of a called trip.
- **Before you start:** I7 passed. Stand-in test object, on a stand, pulled into the path by rope from outside the zone. **Never a person.** `cruise_mps` 0.2 for the first run through.
- **Steps:** at each moving stage: pull the object into the front field. See the stop. Measure stopping point to object. Pull it clear. Time the resume. At each stopped stage: pull it in and press START. Pull it clear. Press START. Rear field: repeat on one moving stage with a trolley on, per E1.
- **Expected:** moving: AGV stops short of the object. Call state does not change. `AGV_HOLD` and `fieldViolation` show beside it. Resumes by itself 2 s after the field clears, with no horn repeat (as today). TURNING: a field stop during a pivot can make a FAULT in today's code ("U-turn interrupted"), so the call goes Aborted: write down which. Stopped: START refused with `PREREQUISITE`, no horn; the next START works.
- **Confirm by:** tape measure, watcher window, station.

| Stage | Result | Clearance cm | Resume s | Date | Initials |
|---|---|---|---|---|---|
| QUEUED (at home, call waits, `PREREQUISITE`) | | n/a | n/a | | |
| TO_PICKUP warning (see G7.1) | | n/a | n/a | | |
| TO_PICKUP moving | | | | | |
| AT_PICKUP | | n/a | n/a | | |
| TO_MACHINE | | | | | |
| AT_RELEASE | | n/a | n/a | | |
| TURNING | | | | | |
| AT_ATTACH | | n/a | n/a | | |
| RETURNING | | | | | |
| One moving stage, rear field, trolley on | | | | | |

### I9. Tape lost `[MOTION]`

- **Purpose:** tape loss during a trip stops the AGV and ends the trip.
- **Before you start:** I8 passed. How to do it: the Lead prepares a short gap on a straight, using a removable piece of tape, well away from any junction or curve. Note which leg the gap suits. `cruise_mps` 0.2. Don't use a gap on the trip's other parts. Put the tape back after.
- **Steps:** at each moving stage, set the gap on that leg and let the AGV reach it.
- **Expected:** AGV stops. FAULT. `TRIP_ABORTED`. Call Aborted, LED off. Nothing moves until **Recover**.
- **Confirm by:** Run page, watcher window, station.

| Stage | Result | Call became | Date | Initials |
|---|---|---|---|---|
| QUEUED | n/a: AGV not moving, at home | | | |
| TO_PICKUP warning | n/a: AGV not moving | | | |
| TO_PICKUP moving | | | | |
| AT_PICKUP | n/a: AGV not moving | | | |
| TO_MACHINE | | | | |
| AT_RELEASE | n/a: AGV not moving | | | |
| TURNING: the tape leaves the sensor on purpose in a pivot, so make the gap on the short run after the pivot | | | | |
| AT_ATTACH | n/a: AGV not moving | | | |
| RETURNING | | | | |

### I10. Cancel while queued, from the screen `[MOTION IF IT FAILS]`

- **Purpose:** calls can be cancelled from the screen only while queued.
- **Before you start:** I9 passed.
- **Steps, one row at a time:**
- **Expected:** as the row. LED goes off when the call is deleted. Button works again after.
- **Confirm by:** station screen, watcher window.

| ID | Do this | Expected | Result | Date | Initials |
|---|---|---|---|---|---|
| I10.1 | AGV away, or `NOT_READY` showing. Press, then cancel on the screen | Deleted at once, no order ever sent | | | |
| I10.2 | Order sent and refused. Press the button and pull the target into the rear field at the same moment, so the order goes out just before the station sees `NOT_READY`. Up to 5 tries. Check the `order` topic shows it was sent. Then cancel on the screen | Station stops sending, watches 6 s, then deletes. Press from that machine ignored during the 6 s | | | |
| I10.3 | Look at the screen in each stage past QUEUED | No cancel offered | | | |
| I10.4 | Three calls queued. Cancel the middle one | Other two keep their order | | | |

### I11. cancelOrder `[MOTION]`

- **Purpose:** the three results. It is not a stop command: stopping is physical.
- **Before you start:** I10 passed. Test sender ready with the current orderId.
- **Steps, one row at a time:**
- **Expected:** as the row.
- **Confirm by:** `instantActionStates` in the watcher window, E-stop person, station.

| ID | Do this | Expected | Result | Date | Initials |
|---|---|---|---|---|---|
| I11.1 | Send `cancelOrder` during the warning at home | Warning stops, `cancelOrder` `FINISHED`, wait actions `FAILED`, no motion | | | |
| I11.2 | Screen cancel while the order is going out. A person cannot hit this window: the cancel button goes when the call reaches TO_PICKUP, about 0.4 s after acceptance, and a `confirm()` dialog is in the way. So a script on the station PC watches `order` as user `watch`, and on the first order calls `POST /api/calls/<seq>/cancel`. Up to 5 tries. A late POST gets 409: write it down and try again | 200, `cancelling`. If the warning started: station sends `cancelOrder`, `FINISHED`, deletes the call, no motion. Record which tries reached the warning | | | |
| I11.3 | Send `cancelOrder` when moving to ATT | `FAILED`, `CANCEL_REFUSED`, trip continues, screen says "too late to cancel" if from screen | | | |
| I11.4 | Send `cancelOrder` when stopped at ATT | `FAILED`, `CANCEL_REFUSED`, wait stays `RUNNING` | | | |
| I11.5 | Send with no active order | `FAILED`, `NO_ORDER_TO_CANCEL` | | | |
| I11.6 | Send with a wrong orderId, during a trip | `FAILED`, `NO_ORDER_TO_CANCEL`, trip continues | | | |
| I11.7 | Send the same `actionId` three times | AGV acts once | | | |

### I12. Stale and duplicate orders `[MOTION IF IT FAILS]`

- **Purpose:** an old order must never start the AGV. A repeat must never restart a trip.
- **Before you start:** I11 passed. For rows 1 to 4 and 10: AGV at home, READY, AUTO, trolley hitched with the pin in and nobody in the zone, so that a stale check that fails gives `TROLLEY_PRESENT`, not motion. The test sender is never used to start the AGV moving. Other rows as the row says. Floor cleared, E-stop person in place. Real station stopped, so that the test sender is the only sender.
- **Steps, one row at a time:**
- **Expected:** as the row. No horn or motion except where stated.
- **Confirm by:** watcher window file, E-stop person.

| ID | Do this | Expected | Result | Date | Initials |
|---|---|---|---|---|---|
| I12.1 | Order with `seenStateHeaderId` older than 5 s | `STALE_ORDER` | | | |
| I12.2 | Order with an invented `seenStateHeaderId` | `STALE_ORDER` | | | |
| I12.3 | Access point off. Publish one order at once, so it sits in a TCP buffer. Access point on again after 8 to 12 s: above the 5 s window, below the 15 s last will time. Read the AGV's bridge log | `STALE_ORDER`, with the order seen in the bridge log. If the bridge log does not show it, the row has proved nothing: repeat it. **No motion** | | | |
| I12.4 | Stop the test sender in mid-resend. Wait 10 s | No motion later on. Nothing arrives after 5 s has any effect | | | |
| I12.5 | During a trip, re-send the same order 10 times, every 2 s | Ignored, no error, trip unaffected | | | |
| I12.6 | During a trip, same orderId, changed nodes | Ignored, `SAME_ORDER_UPDATE_ID`, trip unaffected | | | |
| I12.7 | During a trip, a new orderId for another machine | `OTHER_ORDER_ACTIVE`, trip unaffected | | | |
| I12.8 | Call just closed, AGV home, no trolley: re-send the just-finished orderId | Ignored. **Does not start again** | | | |
| I12.9 | Restart the real station with an old call in its list: does it resend? | No order except a truly QUEUED one, with fresh `seenStateHeaderId` | | | |
| I12.10 | As I12.3, with the access point off for 20 s, past the last will time, so the broker has dropped the AGV and its clean session | The order never arrives. Last will seen. **No motion** | | | |

## 15. Group J: queue and the key hazard

**Order in this group: the key hazard and J5 to J8 first, then J1 to J4, then J9.** The numbers stay as they were,
so that the plans' references still hold.

### The key hazard

**The situation.** The AGV comes home with a full trolley hitched. A call is already waiting. A
person walks up to unhitch the trolley. Nobody presses START, because no START is needed: the AGV
leaves by itself once it believes it may. That person is at the hitch, close to a vehicle about to
move.

**What must happen, exactly:**

1. The call just served closes on arrival. The waiting call stays QUEUED. Its LED keeps blinking.
2. The AGV stays parked. **No horn. No wheel motion.** `NOT_READY` shows `TROLLEY_PRESENT`. The station sends no order. A forced order gets `DEPARTURE_REFUSED`.
3. If anything is in the rear safety field, `NOT_READY` also shows `REAR_FIELD_NOT_CLEAR`. No departure, whatever the trolley reading says. If the scanner gives no fresh data: `TROLLEY_UNKNOWN`, `REAR_FIELD_UNKNOWN`, no departure.
4. The wait only starts when the lidar says **no trolley and** the rear field is **clear**. Then `SETTLING` runs for 5 s without a break. If either comes back, the 5 s starts again from zero.
5. Then the station sends the order, and the horn sounds for at least 2 s. **At least 7 s from the last clear reading to the first wheel turn.**
6. During the horn, if anything enters a field or the trolley is seen again: warning cancelled, no motion, `DEPARTURE_CANCELLED`, 15 s `HOLDOFF`, and back to step 4.

**What must never happen:** a horn or a wheel turn with a trolley hitched, with something in the rear
field, within 5 s of the last trolley reading or the last front or rear field reading, or with the
scanner's data unknown. Any of these is a safety failure: stop all testing and call the owner.

**The limit this cannot fix.** The rear field sees only what it can see. Someone beside the AGV may
be in no field at all (E11). No software can change that. That risk, and the sign and training that
go with it, is for the owner at L.

**How it is rehearsed with nobody at risk.** Four stages, in order, before any other test in this group,
because J1 to J3 put people at the hitch with calls waiting. Each stage must pass before the next. People
only come near when hardware makes motion impossible (J5), or at the last stage on the owner's say-so
(J8). **No person goes to the hitch with a call waiting and the selector in AUTO until J8 has passed**
(section 3). Fields are proved with the stand-in target in E11 and J6, never with a person.

The hitch is released with the E-stop pressed. The pin comes out, but the trolley stays where it is,
so the lidar still reads present (E9.10). After that, people leave and the trolley can be pulled away
from outside the zone. The stand-in target and the trolley each have a rope long enough to reach
outside the marked zone.

### J5. Rehearsal 1: E-stop pressed, people may practise `[MOTION IF IT FAILS]`

- **Purpose:** walk through the sequence with real people. The E-stop stays pressed, so hardware takes torque away, and nothing can move. This practises the job. It does not prove a field: E11 and J6 do that with the stand-in target.
- **Before you start:** group I passed. AGV at HOME-N, AUTO. Waiting call. Trolley hitched. **E-stop pressed the whole time, and the E-stop person checks it.**
- **Steps:**
  1. Press MRU2 button A: a waiting call. Read `NOT_READY`.
  2. A person walks to the hitch. Read the state.
  3. They unhitch by the normal steps. Read the state at each step.
  4. They roll the trolley clear, and walk away by the usual path.
  5. Start a stopwatch at the last "clear" reading. Note `SETTLING`, the order, and the horn. The E-stop is still in, so the attempt ends as G2 found: one horn cycle, `DEPARTURE_CANCELLED`, `TORQUE_TIMEOUT` latched, and no second horn.
  6. Cancel the call on the screen, with the E-stop still pressed. Only then release it and RESET.
- **Expected:** steps 1 to 5 of "what must happen". Write down each state, and how long the person was in and out of the field. Where was the person when the horn sounded?
- **Confirm by:** watcher window file, stopwatch, E-stop person.

Horn started ________ s after the person left the field.

Result: ________ Date: ________ Initials: ________

### J6. Rehearsal 2: wheels lifted, nobody in the zone `[MOTION]` `[OWNER GO]`

- **Purpose:** the same sequence live, with the AGV unable to travel. If G1 said lifting is not possible, this is N/A with owner's initials, and J7 starts at its slowest.
- **Before you start:** J5 passed. AGV on stands. Trolley hitched, no call yet. With the E-stop pressed, the pin is taken out and the trolley left in place. Everyone leaves the zone. E-stop released, RESET. Selector AUTO. Only then, from outside the zone, press a button for the waiting call.
- **Steps, one row at a time, from outside the zone. Rope on the trolley and rope on the target:**
- **Expected:** as the row. Selector to MANUAL 5 s after wheels start. After any row where the wheels turned: selector MANUAL, RESET, At home again, READY, then redo the rig, before the next row.
- **Confirm by:** E-stop person watching wheels, stopwatch, watcher window file.

Owner go-ahead: ________ Date: ________

| ID | Do this | Expected | Result | Date | Initials |
|---|---|---|---|---|---|
| J6.1 | Leave it all as it is for 2 minutes | No horn, no wheels. `TROLLEY_PRESENT` | | | |
| J6.2 | Pull trolley 0.5 m. It's still in the field | No horn, no wheels | | | |
| J6.3 | Pull trolley clear, target remains in the field, 2 minutes | No horn, no wheels. `REAR_FIELD_NOT_CLEAR` | | | |
| J6.4 | Pull target out. After 3 s pull it back | `SETTLING` stops. No horn | | | |
| J6.5 | Pull target out. Stopwatch | `SETTLING` 5 s, horn, wheels at no less than 7 s | | | |
| J6.6 | Start again. Target back in during the horn | Cancelled, `DEPARTURE_CANCELLED`, 15 s `HOLDOFF`, no wheels | | | |
| J6.7 | Start again. Rear scanner link broken in the settling wait, from outside the zone: a pull cord rigged on the connector with the E-stop pressed beforehand, or a switch port or patch point outside the zone. Nobody at the AGV. If neither can be rigged, the Lead marks the row N/A with the owner's initials | No horn, unknown | | | |

### J7. Rehearsal 3: on the floor, nobody in the zone `[MOTION]` `[OWNER GO]`

- **Purpose:** the same sequence with a real departure at the end.
- **Before you start:** J6 passed or N/A. `cruise_mps` 0.2. Route to ATT cleared. Rig as J6, without stands.
- **Steps:** run rows J6.1 to J6.7 again. On J6.5 and after any later clear reading the AGV leaves: let it go to ATT, then selector MANUAL. **Recover.** Run it 5 times.
- **Expected:** as J6, with a real departure at no less than 7 s. Each run stops at ATT.
- **Confirm by:** as J6, plus saved log.

Owner go-ahead: ________ Date: ________

| ID | Result | Seconds to wheels on the clear run | Date | Initials |
|---|---|---|---|---|
| J7.1 | | n/a | | |
| J7.2 | | n/a | | |
| J7.3 | | n/a | | |
| J7.4 | | n/a | | |
| J7.5 (5 runs) | | | | |
| J7.6 | | n/a | | |
| J7.7 | | n/a | | |

### J8. Rehearsal 4: a real person, the real job `[MOTION]` `[OWNER GO]`

- **Purpose:** the final check. A trained person unhitches with a live waiting call, the way the job will be done. **The owner must watch this one in person.**
- **Before you start:** J7 passed. Risk assessment updated (L). `cruise_mps` 0.2. Person briefed: where to stand, where to walk away. E-stop person with a hand on the button. Floor cleared of everyone else. Owner present.
- **Never a test object:** the person does the job and nothing else. They do not go back into a field or stand beside the AGV to see what happens. Those two cases are run with the stand-in target, by rope, after the person has walked clear and left the zone.
- **Steps:**
  1. AGV returns from a real trip with a full trolley, MRU3's call waiting.
  2. The person walks up and unhitches at the normal working pace.
  3. They roll the trolley away, and walk away by the marked path, out of the zone.
  4. AGV goes by itself. Stopwatch from the moment they leave the field.
  5. Repeat 5 times. In run 4, the Lead pulls the stand-in target back into the rear field during `SETTLING`, which must restart it. In run 5, the stand-in is set beside the AGV beforehand, outside every field: write down that it is not seen and that the AGV leaves.
  6. Owner and person say whether 7 s and the horn are enough. Record it.
- **Expected:** "what must happen" in every run. **E-stop person presses at once on any horn or wheel motion before the person has walked clear.** Note the position of the person at the horn in each run.
- **Confirm by:** owner watching, stopwatch, video if allowed, watcher window file.

Owner go-ahead: ________ Date: ________

| Run | Seconds to wheels | Person's position at horn | Result | Date | Initials |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 (stand-in pulled back in during settling) | | | | | |
| 5 (stand-in set beside the AGV) | | | | | |

### J1. First come, first served across machines `[MOTION]`

- **Purpose:** the order of presses is the order of trips.
- **Before you start:** J8 passed, so people may now unhitch with calls waiting. All four machines ready. AGV ready at home.
- **Steps:**
  1. Agree the order: MRU3, MRU1, MRU4, MRU2. Press those buttons with a few seconds between.
  2. Run all four cycles to home, unhitching in between.
- **Expected:** trips go MRU3, MRU1, MRU4, MRU2. All LEDs blink from their press. One goes solid at a time. Screen shows the order. Each new trip waits for the previous one to end and the trolley to be off.
- **Confirm by:** station list, watcher window `orderId` order.

Result: ________ Date: ________ Initials: ________

### J2. One open call per machine `[MOTION]`

- **Purpose:** a machine whose call is open is ignored, including while on the trip being driven. Today's AGV queue alone would allow this, so check the station handles it.
- **Before you start:** J1 passed.
- **Steps:**
  1. MRU2 presses A. Press A again, then C. Wait.
  2. Let the trip run. MRU2 presses button again at each stage.
  3. Call closes at home. MRU2 presses C.
- **Expected:** only one MRU2 entry, type A, until the close. After close, a new MRU2 call, type C.
- **Confirm by:** station list.

Result: ________ Date: ________ Initials: ________

### J3. A call while the AGV is out `[MOTION]`

- **Purpose:** a new call waits and leaves only when allowed.
- **Before you start:** J2 passed. AGV on a trip to MRU1.
- **Steps:**
  1. At TO_MACHINE, press MRU4 button F. Check QUEUED, type F, LED blinking.
  2. Let the trip finish. At home, with everyone clear of the route, pull the trolley away by rope, with the pin taken out under a pressed E-stop as in the rig described under the key hazard.
  3. Watch the settling and the horn.
- **Expected:** MRU4's call stays QUEUED throughout. Only after AGV home, trolley off and rear field clear for 5 s does the order go out, then the horn, then departure.
- **Confirm by:** station screen, stopwatch, watcher window.

Result: ________ Date: ________ Initials: ________

### J4. Two presses at the same moment `[NO MOTION]`

- **Purpose:** two modules, two pollers, a press at the same moment. The order must be stable and shown.
- **Before you start:** J3 passed. AGV not free (selector MANUAL).
- **Steps:**
  1. By count of three, press MRU1 A and MRU3 A together. Note order on the screen.
  2. Repeat for MRU1 and MRU2 (same module).
  3. Restart the station. Read the order.
- **Expected:** one comes first, both are listed, order doesn't change later, and it survives the restart.
- **Confirm by:** station list.

Result: ________ Date: ________ Initials: ________

### J9. Warning people that the AGV may leave `[NO MOTION]`

- **Purpose:** the screen, signs and training must make it clear that a waiting call means this AGV will leave by itself. Today's manual says "stay out of the way once someone presses START" (10.4), and AUTO "always starts by the operator" (10.5). That's no longer the whole truth.
- **Before you start:** J4 passed.
- **Steps:**
  1. Stand at HOME-N. Can you see from there that a call is waiting? Is there a sign saying what happens?
  2. Ask a warehouse operator who hasn't been in these tests what the AGV will do next. Ask them where they would stand to unhitch.
- **Expected:** the operator knows the AGV can leave without a START, within a few seconds of the trolley being gone. Any gap goes to the owner at L.
- **Confirm by:** the operator's own words, on the sheet.

Result: ________ Date: ________ Initials: ________

## 16. Group K: soak run and BTU regression

### K1. Soak run `[MOTION]` `[OWNER GO]`

- **Purpose:** a long run shows what short tests don't: leaks, heat, odd timing, tired relays.
- **Before you start:** group J passed. Owner agrees the speed and any high-speed areas. If areas go back on, repeat one full cycle at that speed first. Real operators. E-stop person throughout.
- **Steps:**
  1. Run at least 20 calls end to end, mixed across all four machines. Add the H5 trips to the count if run at the same software commit.
  2. Spread over at least one full working shift, with real gaps between calls.
  3. Every hour read on the AGV: CPU temperature, memory, Wi-Fi state. On the station: memory, connection, error count.
  4. Log `state` for the whole shift. Log every hold, refusal and missed tap.
  5. Leave the system on overnight, then run one call.
- **Expected:** all 20 close as served. Every stop within ±10 cm. No unexplained hold, no unexplained `NOT_READY`. No false trolley reading. Temperature and memory steady. Blink-hours match the C1 estimate. Overnight run works first time.
- **Confirm by:** saved logs, summary below.

Owner go-ahead: ________ Date: ________

Calls served: ________ Unexplained events: ________ Max CPU temp: ________ C

Result: ________ Date: ________ Initials: ________

### K2. BTU regression, switch off `[MOTION]`

- **Purpose:** the BTU group must keep working. `trip_calls: 1` is a global setting, so BTU is now one machine per trip, and that's a change to check.
- **Before you start:** K1 passed. Switch off. **Row 2 and C-BTU must be laid and taught.** The records disagree: decision D12 says not laid, an operator note of 2026-10-25 says row 2 is laid, and teaching isn't confirmed. Use what A2 found.
- **Steps:**
  1. If C-BTU is taught: Run → Calls, tap BTU24. Tap Trolleys off. START. Horn, ATT. Hitch. START. J-N straight. Stop at R2-1. Swap. START. Home by J-R2E, J-ML left.
  2. Tap BTU9, which shares no stop with it (R2-8), and do the same.
  3. Try BTU16 and BTU24 together, sharing stop R2-1: with `trip_calls: 1` they are two separate trips. Write down what happens.
  4. If C-BTU isn't taught: tap a BTU call and press START. It must refuse with "not taught", and the call must wait. Check the mission loads. Then ask the owner to sign the rest as N/A until BTU is taught, and this test is repeated then.
- **Expected:** BTU behaves as before, except for one machine per trip. J-N straight, never right. No horn or call related to the station. Trip's stop within ±10 cm.
- **Confirm by:** Run page, tape measure, saved log.

C-BTU taught: ________

Result: ________ Date: ________ Initials: ________

### K3. BTU and local trips, switch on `[MOTION]`

- **Purpose:** a local trip and the station must not get in each other's way.
- **Before you start:** K2 passed. Switch on, restarted. Station running.
- **Steps:**
  1. Tap a BTU call on the AGV's own page, if taught (otherwise an MRU call on its own page). Check `NOT_READY` shows `LOCAL_TRIP`.
  2. Press MRU1 button A. Check it stays QUEUED.
  3. Press physical START at home. Let the local trip run all the way home. START at each stop. Check the trolley interlocks at ATT and the local MRU stops, if an MRU trip, and write down what they do. BTU swap stops need a trolley on before and after.
  4. Back home, unhitch. MRU1's call now leaves by itself, once clear.
  5. Force an order at step 3. Check `OTHER_ORDER_ACTIVE`.
- **Expected:** the local trip works and needs a physical START at home. The station's call waits. BTU orders never come from the station. No order goes out during a local trip.
- **Confirm by:** Run page, watcher window, station.

Result: ________ Date: ________ Initials: ________

### K4. Back to switch off `[MOTION]`

- **Purpose:** prove the way back. The rollback must be real before anyone relies on it.
- **Before you start:** K3 passed. Calls on the station cleared.
- **Steps:**
  1. Set the switch off. Restart the service. Repeat A10 and A11.
  2. Run one hand trip for MRU1. Compare with F1, the baseline taken after group E.
  3. Press station buttons. Check: QUEUED only, and the AGV does not move.
  4. Read the way back for P0's two settings and the rear hardware (AGV plan 4.2, Rollback), and check the Lead could do it. Do not do it here.
  5. Set the switch on again. Restart. Run one call cycle.
- **Expected:** with the switch off, the job, node and web behave as the F1 baseline. Any difference from S3 is explained by P0's settings or rear hardware, which the switch does not cover, and is written down separately. The station sees the AGV as not free. It sends nothing that could matter. With the switch on, it works again with no other change.
- **Confirm by:** F1 baseline comparison, watcher window.

Result: ________ Date: ________ Initials: ________

### K5. Station PC restart, Windows update, cold start of everything `[MOTION IF IT FAILS]`

- **Purpose:** a real morning. Everything was off. In what order does it come up, and does anything surprising move?
- **Before you start:** K4 passed. Floor cleared at the start, since nobody knows yet what happens.
- **Steps:**
  1. Switch off AGV, station PC, DIO modules and access point. Leave a saved open call in the station list.
  2. Power up in this order: access point, modules, station PC, AGV. Watch.
  3. Do it again in a different order: AGV first, station PC last.
  4. Restart the station PC by Windows Update, or simulate with a normal restart, at home with no call open.
- **Expected:** LEDs reach a known state each time. Broker and station come up with no one's help, or the sheet says exactly who does what. AGV stays still until At home is pressed and a fresh order arrives. No horn.
- **Confirm by:** stopwatch, machine person, watcher window.

Result: ________ Date: ________ Initials: ________

## 17. Group L: sign-off

Sign only when true. Anything not ticked keeps the switch **off** on the real AGV.

| # | Item | Name | Date |
|---|---|---|---|
| L1 | Groups A to K and S all have a result. Every FAIL is fixed and retested. Every N/A has owner's initials | | |
| L2 | **Rear field while towing:** owner's decision is written, and E4, E5, E6 and E11 results match it. **The rear case gate is met:** E11's towing-case rows passed, and case selection does not come from the trolley detection. Safety controller inputs and safety figures have been reworked for the rear scanner, or the owner has signed the reasons | | |
| L3 | **False "absent" count is zero** over E9, F5 and K1 | | |
| L4 | **Key hazard:** J5 to J8 passed. Owner personally watched J8 and accepts the 7 s and 2 s horn, and the risk that a person beside the AGV is not seen | | |
| L5 | **E-stop recovery:** the I7 result is known, the owner has answered AGV plan O13, and the operation manual (10.7) and plan agree with what truly happens | | |
| L6 | **LED off point:** owner has decided (H6) | | |
| L7 | **Relay life:** rating found, load inside it, blink period and life accepted (C1) | | |
| L8 | **Added waits:** owner accepts the 5 s `SETTLING`, the 15 s `HOLDOFF` and the requeue limit of 3 as measured, or changes them. `order_torque_wait_s` is a value measured at P8, not the 4.0 s placeholder | | |
| L9 | **Aborted calls** close with no retry and the machine must press again. Owner accepts | | |
| L10 | **Late cancel** is refused and the trip continues. Owner accepts | | |
| L11 | **Broker:** passwords and ACL are in place. Owner knows plain MQTT isn't encrypted, and Wi-Fi security matters | | |
| L12 | **`manufacturer` label** `gvi` in the topics: owner accepts, or it was changed before first use | | |
| L13 | **Wrong trolley type** is not detected (H9). Owner accepts | | |
| L14 | **Decisions updated** in `manuals/site-layout-103.md`: D4, D5, D10, D14, D18, the trip flow and table sections | | |
| L15 | **Documents corrected:** README and RUNBOOK wording on "no web page can start the vehicle", `manuals/tape-localization-runbook.md`, operation manual 10.4, 10.5 and alarm table, with a warning about self-departure. `alpha-setup.md` gateway entry | | |
| L16 | **Risk assessment** (AGV plan O3) updated for automatic departure and the rear scanner, naming these residuals: heading is not measured, so At home is a procedural check; a frozen scan is not caught if the driver has no scan counter (E10); one horn cycle with an E-stop pressed at home, and a release and reset inside `order_torque_wait_s` (G2). Rear scanner chain verification done first | | |
| L17 | **Operators trained** on the new flow. Signs up at home, ATT and each machine. Each operator has initialled | | |
| L18 | **Not called compliant:** nothing says VDA5050 compliant. Missing parts are written down | | |
| L19 | **Way back known:** K4 passed. The Lead and one other person can set the switch off | | |
| L20 | Sheets, logs and photos stored together. The owner knows where | | |

**Switch on for production use, decided by the owner:** ________ Signature: ________ Date: ________
