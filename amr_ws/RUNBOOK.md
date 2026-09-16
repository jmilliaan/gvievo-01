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

## 2. Survey and save a map

Prepare a marked floor position and heading. Clear the area, select **MANUAL**,
open `/maps`, then:

1. Enter a map ID and description and request **Start survey**.
2. Wait for the operation to succeed and mode to become `MAPPING`.
3. Hold the browser jog control to survey at low speed. Revisit junctions and
   observe the live scan/map overlay. Releasing the control must stop motion.
4. Return physically to the marked pose, stop, and select **Returned to start**.
5. Review the closure evidence and map. If acceptable, select **Save**.
6. Wait for save success and automatic return to `IDLE`. Record the immutable
   map ID, revision and SHA-256 identity shown by the UI.

An unsaved survey blocks mode replacement. Use **Abort survey** to discard it.
A second survey can start from the same service process after the first save or
abort; restarting the service is not part of the workflow.

## 3. Create and run a route

On `/editor`, select the exact saved map revision, author the route, validate
the footprint/turn sweep, save a route revision, then create its mission.

On `/run`:

1. From `IDLE`, request **Navigation** for that exact map revision.
2. Wait for `NAVIGATION` and verify the active map identity.
3. Under **MANUAL**, set the initial pose and jog briefly so localization can
   converge. Confirm only when the scan overlay agrees and the page permits it.
4. Load a mission whose map ID, revision and hash match the active map.
5. Select **AUTO** and press physical **Start** once.

Use **Pause** to inhibit an executing route. After the reason is clear, select
**Prepare resume** and press physical **Start** again. Use **Abort** to end a
run before requesting another mode. Mode replacement is refused while a run is
active or resumable.

| State | Operator action |
|---|---|
| `BLOCKED` | Clear the obstruction, wait for stable clearance, prepare resume, press physical Start. |
| `PAUSED` | Prepare resume, then press physical Start. |
| `FAULT` | Read Monitor/Events, correct the cause, then use scoped recovery or fault acknowledgement. |
| `DONE` | Load another mission (another physical Start is required), or return to IDLE. |

## 4. Diagnostics and commissioning

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

## 5. Fault recovery

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

## 6. Install rehearsal and validation

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

## 7. Witnessed first cutover

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

## 8. Rollback during the migration window

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
