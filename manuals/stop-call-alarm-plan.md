# Stop call alarm plan: gvievo-01 (agv-01)

Branch `gvievo-main` · 2026-11-13 · **Built 2026-11-13** (uncommitted). Service restart and the §7 floor check owed. Profile keys are flat (`dio.call_alarm_on_s` / `dio.call_alarm_off_s`), not the `dio.call_alarm` object below.

**Goal (owner, 2026-11-13).** When the AGV is parked at a stop and waits for a person to attach or
release trolleys, the alarm sound plays until the physical **START** is pressed.

**Shape.** One more reason for the existing alarm output (DO1, horn sound 2), decided in
`panel_io.py` from data panel_node already gets (`LineState.state` and `hold_cause`). A
**pulsed** pattern, 1 s on and 2 s off, keeps it distinct from the continuous alarm the horn
already uses for a hazard (a field occupied in an AUTO run, the 2 s before a move). Python and
profile changes only: **no message change, no colcon build, no change to gating or the safety
path.**

## 1. Which stops call

| Hold (`LineState.hold_cause`) | What the AGV waits for | Calls? |
| --- | --- | --- |
| `station` | Parked at a trip or tag-table stop: attach, release, take or swap, then START | **yes** |
| `payload` | At a U-turn with a release not recorded: "Released" on Run → Calls, then START | **yes** |
| `trolley` | At a pivot, the rear lidar reads a trolley: move it clear, then START (no rear lidar is fitted today, so this does not occur yet) | **yes** |
| `estop`, `rfid`, `markers`, `position`, `prereq`, `authority`, `drive_fault`, … | A fault or check, then START | no: Home and Alarms explain these |
| `field` | Resumes by itself | no: it already has its own continuous alarm |
| DONE at HOME (trolleys off, the next trip waits for "trolleys off") | A confirmation on the web, not a press | no (see §6, item 1) |

The list is one tuple, `hold_policy.CALL_CAUSES = ("station", "payload", "trolley")`, beside
`AUTO_CAUSES`, so the two products share it and adding a cause later is a one-word edit.

## 2. Behaviour

- **On:** selector AUTO (valid panel) and the line layer in HOLD with a cause from `CALL_CAUSES`,
  from the tick the hold starts.
- **Pattern:** DO1 on for `on_s`, off for `off_s`, phase starting at the hold. `off_s` 0 means
  continuous.
- **Off:**
  - **START accepted:** the job goes to ARMED, and the 2 s pre-move alarm takes over without a
    break, continuous this time. The change from pulsed to continuous tells the operator that
    the press was accepted.
  - **START refused:** an interlock refusal or an unmet prerequisite keeps it calling, because
    the AGV is still waiting.
  - **Reset:** the run ends, so it stops.
  - **Selector to MANUAL:** it stops, as every alarm reason does today.
- **With the existing alarm:** `alarm = hazard_alarm or (call and phase_on)`. A person standing
  in a scanner field at a stop already sounds it continuously today (a parked stop counts as an
  active run in `alarm_wanted`). That is unchanged: continuous wins over pulsed.
- **No time limit**, as asked. A stop nobody serves calls until someone comes.

## 3. Work packages

### C1. Pure logic: `amr_base/panel_io.py`, `amr_base/hold_policy.py`
- `hold_policy.CALL_CAUSES`.
- `call_wanted(mode_auto, line_state, hold_cause, line_fresh) -> bool`.
- `call_phase(now, since, on_s, off_s) -> bool`: clock-fed, `since` is the time the call began.
- `alarm_wanted` is not changed. panel_node ORs the two, so the existing alarm tests keep their
  meaning.

### C2. Node: `amr_base/panel_node.py`
- `_on_line` also keeps `hold_cause` and the receipt time.
- **Freshness:** LineState comes on change and at 1 Hz. If it is older than 3 s, there is no call.
  Otherwise a dead or replaced line layer would leave the last parked state calling forever. The
  coil still expires through `HORN_HOLD_S` if panel_node itself dies (existing).
- Keeps `_call_since`: set on the rising edge of `call_wanted`, cleared on the falling edge.
- One log line and one INFO event, `call alarm on at <stop>` / `off`, so the event log shows how
  long each stop waited.

### C3. Profile: `profiles/agv-01.json`, `agv_core/config.py`, `tests/test_config.py`
- New key `dio.call_alarm`: `{"on_s": 1.0, "off_s": 2.0}`, or `null` for off.
- Schema and validation: `on_s` > 0, `off_s` ≥ 0, both ≤ 10. The loader refuses `dio.call_alarm`
  set while `dio.alarm_on` is empty, since there would be no output to sound.
- Refusal tests in `tests/test_config.py`. Update `EXPECTED_CHECKS` in `tests/run_all.py` on
  purpose.
- A `dio.*` docstring paragraph in `config.py`. Add it to the parameter table rows if `dio` keys
  are listed there.

### C4. Home tile: `amr_web/alarms.py` (small, uses the `press` field built 2026-11-13)
- The "stopped" tile for a `CALL_CAUSES` hold gets `press=("start",)`, so the panel drawing rings
  the green START, the button that silences the call.
- `payload` keeps its text first ("Released" on Run → Calls).

### C5. Docs
- `documentation/operation-manual/operation-manual-doc.md`, horn table: sound 2 gets "(c)
  pulsed while parked at a stop waiting for **START**". Stop procedure: "the alarm sound pulses
  until you press **START**".
- `operation-manual-context.md` §8.9.
- `amr_ws/RUNBOOK.md`: one line in the horn/DIO section.

## 4. Tests

- `amr_base/test/test_alarm_horn.py`:
  - each `CALL_CAUSES` hold calls in AUTO;
  - no call in MANUAL, on stale LineState, or for any other cause in RUNNING, ARMED, IDLE or DONE;
  - `call_phase` on/off edges, and `off_s = 0` gives continuous;
  - the hazard alarm overrides the pulse.
- `tests/test_config.py`: the refusal cases from C3.
- `amr_web/test/test_operator_ux.py`: a station hold tile has `press == ["start"]`.
- Focused tests and both lints only. No sim run: the change is a coil reason, and the sim has no
  horn.

## 5. Failure modes and recovery

| Failure | Effect | Recovery |
| --- | --- | --- |
| Line layer dies while parked | LineState goes stale, so the call stops after ≤ 3 s | Existing: the layer's fault shows on Home |
| panel_node dies | The coil expires after `HORN_HOLD_S` (existing) | Supervisor restarts the base |
| DIO island down | No sound. Nothing gates on the horn, and the vehicle stays parked | Existing PANEL alarm |
| Start pressed but refused | Keeps calling, and the refusal shows on Home | Clear the cause, then press START again |
| Horn audible for a long time at an unserved stop | Noise only | Serve the stop, or Reset |

The horn is still not a safety function, and nothing reads it back.

## 6. Open items

1. **HOME after a trip** (DONE, waiting for "trolleys off"). This is left out because it is a web
   confirmation, not a press, and an unattended HOME would otherwise call indefinitely. Adding it
   later is one more condition in C1.
2. **Sound 2's own tone setting** on the PATLITE (DIP switch). If sound 2 is already an
   intermittent tone, a 1 s / 2 s pulse may sound choppy. Check it on the floor, then set
   `off_s` 0 if so.

## 7. Deploy and acceptance

- **Deploy:** Python, template and profile changes. A service restart picks them up, with no
  colcon build.
- **Acceptance (operator, on the floor, one trip):**
  1. At the first stop: pulsed alarm from standstill.
  2. Press START: continuous for 2 s, then the movement sound.
  3. At a second stop, switch the selector to MANUAL: silent.
  4. Check that the event log shows the call on/off pair for each stop.

The operator seeing these pass is PASS.
