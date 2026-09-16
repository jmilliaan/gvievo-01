# Unified AMR operator and cutover runbook

`amr.service` is the intended production service. It starts the hardware base,
operator web app and optional Foxglove bridge, then stays in **IDLE**. It does
not load a map, start a survey, resume a commissioning job or run a route after
boot. The operator selects mapping or navigation from the web app.

The physical controls remain authoritative:

- **MANUAL** permits bounded browser jog or a held commissioning plan.
- **AUTO** permits a loaded route only after a fresh physical **Start** edge.
- E-stop and the FX3/STO chain remain the immediate physical stop path.
- A stale panel, supervisor lease, drive state or command inhibits motion.

The web app is `http://192.168.2.20:5001/`. The useful operator and diagnostic
pages are Status, Manual, Maps & survey, Route editor, Run, Monitor, I/O,
Alarms (events), Parameters and Commissioning.

## 1. Normal service operation

```bash
systemctl status amr.service
journalctl -u amr.service -f
sudo systemctl start amr.service
sudo systemctl stop amr.service
sudo systemctl restart amr.service
```

A healthy start reaches `IDLE`, with the base and web processes running and no
mapping/navigation layer. The home page must show:

- mode `IDLE` and no transition/fault reason;
- a fresh panel image and operational drives;
- mux source `none` while untouched;
- no active map, survey, localization or run.

Stopping the service revokes the control lease first. The supervisor then stops
the active layer, base, Foxglove and web process groups. The base shutdown
zeros wheel commands, clears the drive heartbeat consumer and de-energizes the
drives; the panel owner drives its output coil low. After stop, check that no
child remains:

```bash
systemctl show amr.service -p ActiveState -p SubState -p MainPID -p Result
pgrep -af 'amr_|nav2|slam_toolbox|foxglove' || true
```

Do not use process-name kills during normal operation. The supervisor owns the
child process groups and performs bounded SIGINT → SIGTERM → SIGKILL cleanup.

## 2. Survey → draw a route → run it

The complete workflow, in order. Only step C moves the vehicle on its own, and
only after a physical Start. Everything else is browser jog under **MANUAL**,
or it moves nothing.

Before you begin:

- The service is in `IDLE` (Status page) and the drives are operational.
- Someone is at the vehicle with the E-stop in reach, and the area is clear.
- The selector is on **MANUAL**.
- Mark a start position and heading on the floor (tape an arrow). The survey
  begins and ends there, and it is the easiest place to start a route from.

**Jogging.** A jog pad appears on the Manual, Maps & survey and Run pages. Hold
a pad button, or hold W/A/S/D or the arrow keys, to drive. Releasing stops the
vehicle. So does Space, Esc or the STOP button, switching browser tabs or
windows, or typing in a text field. The speed menu offers 0.10, 0.20 and
0.30 m/s. Use 0.10–0.20 m/s while surveying.

### A. Survey a map (`Maps & survey` page)

1. Park the vehicle on the floor mark, facing the marked heading, and keep it
   **still**.
2. Fill in **Map id**, using letters, digits, `_` and `-` only (for example
   `line_section`). Fill in **Start mark description** (for example "tape
   arrow A, facing the rack ends").
3. Press **New map (start survey)**. The supervisor switches to `MAPPING`, and
   this takes a few seconds. The state box then shows
   `MAPPING map <id>  surveying '<id>' from (x, y, heading)`.
   - `not ready: vehicle is moving`: stop and press again.
   - `not ready: IMU not calibrated`: the IMU calibrates during the first
     ~2.3 s of standing still after the service starts. Wait and press again.
4. Drive the area slowly with the jog pad. Watch **Live map**: grey and black
   cells grow, the green arrow is the vehicle and red points are the current
   scan.
   - Drive every aisle the routes will use, and a little beyond.
   - Pass junctions and loop back over areas you have already mapped, so SLAM
     can close the loop.
   - Avoid fast turns in place. If walls start to look doubled, slow down.
5. Drive back to the **same floor mark and heading**, stop, and press
   **Returned to start**. The page shows the closure: how far SLAM thinks the
   vehicle is from where the survey started (`dx`, `dy`, `dyaw`). The state is
   `RETURN_REVIEW`.
   - Small values, a few cm and 1–2°, with walls that look single and straight
     mean a good map.
   - If the values are large or walls look doubled, you can drive another loop
     and press **Returned to start** again, or abort.
6. Optionally fill in **Review note** (for example "span 12.00 m measured
   11.96"), then press **Save map revision**. The state goes `SAVING` → saved,
   and the supervisor returns to `IDLE` on its own.
7. The map appears under **Saved map revisions** as `<id>`, `rev N`, with a
   short SHA. A revision never changes after it is saved. Surveying the same
   map id again creates `rev N+1`.

**Abort survey** discards the survey and returns to `IDLE`. You cannot switch
to navigation while an unsaved survey exists: save it or abort it first. A new
survey can start straight away, with no service restart.

### B. Draw a route (`Route editor` page)

The route editor moves nothing. The mode can stay `IDLE`.

1. **Map**: pick the saved `<id> rev N`. **Route id**: a plain name, for
   example `route_a`. **Load saved** stays on `— new —`, or pick an existing
   route to edit it.
2. **Start pose**: click the tool, then click on the map where the route
   starts and **drag towards the heading**, then release. A green arrow and the
   vehicle's footprint appear.
   - Put the start on a spot you can mark on the floor. The survey start mark
     is the easiest.
   - When the run starts, the vehicle must be within **0.10 m and 5°** of this
     pose, or Start is refused.
3. Build the route from steps. They chain from the start pose:
   - **Straight**: select the tool, then click a point ahead. The straight runs
     along the current heading, as far as that point projected onto the
     heading. It cannot go backwards or sideways; turn first.
   - **CCW / CW 45, 90, 180, 270**: turn in place, as seen from above. CCW is
     to the left.
   - **Undo**, **Redo** and **Clear steps** edit the list. The step list
     (`s1`, `s2`, …) is shown under the buttons.
4. **Repeat count**: how many times the route runs back to back. Use 1 unless
   the route returns to its own start pose. **Speed cap**: 0.05–0.30 m/s. Use
   0.15–0.20 m/s for a first run.
5. Press **Validate**. The robot checks the route against the map, including
   the footprint along every straight and the swept area of every turn.
   Problem steps turn red and the reasons are listed. It reports the length,
   total turning, and whether the route closes on its start.
6. Press **Save revision**. The result shows `saved <route> rev M`. An invalid
   route is refused.
7. Press **Create mission from saved revision**. The result shows
   `mission <id> created`. A mission ties this exact route revision to this
   exact map revision, and the Run page lists missions.

### C. Run the route (`Run` page)

1. **Activate the map.** Under **View / activate**, pick the same
   `<id> rev N` and press **Use this map on the vehicle**. The vehicle must be
   stopped and the selector on MANUAL. The mode goes `TRANSITIONING` →
   `NAVIGATION`, and the box shows `ACTIVE: <id> rev N`. Nothing moves.
2. **Tell it where it is.** Press **Set initial pose on map**, then on the map
   click the vehicle's real position and **drag towards the way it faces**, and
   release. Localisation shows `CHECKING`. The red scan points should now lie
   on the map's walls.
   - If they don't line up, set the pose again more carefully.
   - Jog a short distance (about 0.5 m forward and back, a small turn) with the
     pad on this page. This helps it converge.
3. **Confirm.** Wait until the localisation box shows `can_confirm: true`:
   covariance small, `scan_match` ≥ 0.6, sensors fresh. Check yourself that the
   red scan overlays the walls, then press **Confirm: scans align**. The state
   becomes `READY`. **Reset** starts localisation over.
4. **Position the vehicle** on the route's start pose, within 0.10 m and 5°,
   using the jog pad. The white arrow is where the vehicle thinks it is, and
   the planned route is drawn in blue.
5. **Load.** Pick the mission in **Mission**. Only missions for the active map
   revision are listed. Press **Load (READY)**. The run state becomes `READY`.
6. **Go.** Clear the area. Switch the physical selector to **AUTO**, then press
   the physical **Start** button once. The run state becomes `EXECUTING`.
   - `Start refused: 0.23 m / 7.0 deg from the route start; reposition
     manually`: switch to MANUAL, jog onto the start, switch back to AUTO and
     press Start.
   - `localisation not READY`: go back to steps 2–3.
7. **While running**:
   - The physical controls always win: E-stop, or switching to MANUAL, stops
     it.
   - **Pause** stops it and keeps its progress. To continue: **Prepare resume**,
     then physical **Start**.
   - `BLOCKED`: something is in the path. Clear it, **Prepare resume**, then
     physical **Start**.
   - **Abort** ends the run. The mission must be loaded again.
8. **Finished.** The run state is `DONE`. Load the same or another mission and
   press Start again for another run. Every run needs its own physical Start.
   To leave navigation, **Abort** any active or paused run, then press
   **Return to idle**.

Mode changes (a new survey, another map) are refused while a run is `READY`,
`EXECUTING`, `PAUSED` or `BLOCKED`. Abort the run first.

| Run state | Meaning, and what to do |
|---|---|
| `READY` | Mission loaded, waiting for AUTO + physical Start. |
| `EXECUTING` | Driving the route. |
| `PAUSED` | Operator pause. **Prepare resume**, then physical Start. |
| `BLOCKED` | Obstruction in the path. Clear it, **Prepare resume**, then physical Start. |
| `FAULT` | Sensor, drive, panel or localisation problem, or a tolerance was exceeded (for example "passed the endpoint"). Read the reason and the Monitor/Alarms pages, fix the cause, press **Acknowledge fault**. That does not resume: localise again if needed, reposition, load, Start. |
| `DONE` | Route complete. Load a mission again for another run, or Return to idle. |

| Localisation | Meaning |
|---|---|
| `UNLOCALIZED` | No initial pose yet. Set one. |
| `CHECKING` | Pose given, converging. Confirm once `can_confirm` is true and the scans align. |
| `READY` | Confirmed. Runs can load and start. |
| `LOST` | A sensor went stale, uncertainty grew, or the pose jumped. Set the initial pose and confirm again. |

## 3. Diagnostics and commissioning

Use `/monitor`, `/io`, `/alarms` and `/params` for read-only diagnosis. The
pages consume owner-published snapshots; opening more browser clients must not
create another CAN or Modbus poller. Drive-alarm reset remains a physical power
cycle where required by the drive procedure.

`/commissioning` reuses the encoder-only straight, arc, pivot and pulse planner.
It is an exclusive IDLE substate:

1. Select **MANUAL**, ensure the vehicle is stopped and the test area is clear.
2. Enter and **Hold plan**. This validates the plan and moves nothing.
3. Review the calculated wheel count targets.
4. Press physical **Start** once to execute. Browser input cannot start it.
5. Use **Clear / abort** to stop and invalidate the held job.
6. Save the displayed evidence path with the commissioning record.

While a plan is prepared or running, ordinary jog and mapping/navigation mode
requests are refused. Selector change, lease loss, stale counts or panel loss
aborts the job. `DONE` or `ABORTED` cannot replay on another Start edge; upload
a new plan.

## 4. Fault recovery

- `BASE_NOT_READY`: inspect `~/.amr/logs/base.log`, CAN, panel/DIO, scanner and
  drive state. Correct the cause, then use supervisor recovery.
- `LAYER_EXITED` or readiness timeout: inspect `~/.amr/logs/layer.log` (the
  current mapping or navigation layer) and `~/.amr/logs/base.log`. Recovery cleans the old process group and returns to IDLE;
  it does not automatically restart the failed operation.
- `8130h` on both drives: the drive lost the PC heartbeat. Stop the service,
  correct the PC/CAN cause, perform the required drive power-cycle procedure,
  then start to IDLE.
- Panel invalid: check the DIO island at `192.168.1.30`. Reconnection must not
  create a Start edge or replay a jog.
- No ROS discovery in an engineering shell: source `env/vehicle.sh`. Hardware
  refuses any domain other than 10.

## 5. Install rehearsal and validation

Build a coherent overlay before installing unit files:

```bash
cd ~/agv_can/amr_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
./deploy/validate.sh
```

`validate.sh` checks script syntax, required paths and systemd unit syntax. It
does not touch service or hardware state. The installer backs up installed AMR
unit files, installs the source units and runs `daemon-reload`; it deliberately
does not enable, disable, start, stop or restart anything:

```bash
sudo ./deploy/install.sh
```

Record the printed `/var/backups/amr-units/<timestamp>` path. Confirm the
installer preserved current state with:

```bash
systemctl is-enabled agv_controller amr_nav amr_mapping amr
systemctl is-active agv_controller amr_nav amr_mapping amr
```

## 6. Witnessed first cutover

Perform this only after the U10 K1–K5 vehicle session passes on the same build.
Keep a person at the vehicle, clear the area, select MANUAL and engage E-stop
before changing services.

```bash
sudo systemctl disable --now agv_controller.service amr_nav.service amr_mapping.service
sudo systemctl enable --now amr.service
systemctl status amr.service --no-pager
```

Expected observations:

1. Only `amr.service` is enabled and active.
2. The web app opens on port 5001 and reaches `IDLE`.
3. No mapping/navigation layer or prior job is active.
4. Exactly one drive owner, panel owner and scanner owner exist.
5. Release E-stop only for the short K1 boot/ownership recheck.

Do not delete the legacy source or unit files during this step. Full retirement
is U11 and starts only after accepted hardware evidence.

## 7. Rollback during the migration window

Engage E-stop and stop the unified service. Restore the previously approved
unit choice; `amr_nav` is shown below. The legacy units read
`deploy/amr_legacy.env` (map selection) since 2026-09-16: if the installed copy
predates that, run `sudo ./deploy/install.sh` first or `amr_nav` fails at
launch with `malformed launch argument 'map_id:='`. Starting a conflicting unit stops
`amr.service` as an additional guard.

```bash
sudo systemctl disable --now amr.service
sudo systemctl enable --now amr_nav.service
systemctl status amr_nav.service --no-pager
```

If unit contents themselves must be restored, copy them from the backup path
printed by `install.sh`, then reload systemd:

```bash
sudo cp /var/backups/amr-units/<timestamp>/*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Re-run the prior service's documented boot check before releasing E-stop. A
rollback does not authorize automatic motion or resume any interrupted job.
