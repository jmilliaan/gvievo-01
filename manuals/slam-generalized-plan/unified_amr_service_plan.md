# Unified `amr.service` — implementation and acceptance plan

Status: proposed implementation; no runtime changes made by this study.

Prepared: 2026-09-16. Reviewed baseline: branch `slam-roadmap`, commit `29b4cfa4362b099528ff5c51dc80e1b67a2e3c0e`. Repository was clean at the start of inspection. Recheck the baseline before implementation because other Claude sessions share this checkout.

## 1. Result to deliver

Deliver one boot-enabled application service, `amr.service`, and one operator application on `http://<vehicle>:5001`. It starts the hardware, estimation chain, supervisor and web application once. The operator selects surveying or navigation through the browser. Switching modes replaces only the relevant mapping/navigation processes; CAN ownership, the panel, lidar, local odometry, gyro calibration and the web session remain running during a successful switch.

Confirmed user decisions:

- Migrate all useful operator and diagnostic pages in phases.
- Boot into **IDLE** with hardware and web available. Do not automatically load the previous navigation map.
- Fully retire `agv_controller` after unified-service acceptance. Retain it only as a temporary migration fallback.

One service means one application supervision boundary containing several processes. Keep ROS nodes separate. The OS, network services and existing `canable@can0.service` remain infrastructure dependencies; merging the serial-CAN bridge into Python is outside this change.

This is larger than a launch-file refactor. The essential additions are a transactional mode supervisor, independent motion inhibition, explicit map identity, browser jogging and live survey feedback, process cleanup, and diagnostic data supplied by the existing hardware owners.

### 1.1 Completion criteria

1. From a fresh boot, the operator can inspect the vehicle, jog under physical MANUAL, survey, return/review/save, edit a route, select its exact map revision, localize, load the mission and execute under physical AUTO + Start, using the same web address.
2. Successful IDLE/MAPPING/NAVIGATION transitions preserve base-process PIDs and odometry continuity.
3. No transition permits simultaneous mapping/navigation map or TF ownership, retained velocity commands, old localization confirmation, or old route permission.
4. A failed transition is visible and leaves motion inhibited. No automatic route, survey or commissioning-job replay after restart.
5. Monitor, I/O, alarms/events, effective parameters and useful commissioning diagnostics no longer need `canworker` or the old Flask process.
6. A clean checkout contains every deployment/environment script required to install the service.
7. Acceptance records distinguish offline/simulation evidence from measured vehicle behavior. Legacy deletion follows that evidence.

## 2. Findings from the current code

Paths below are relative to the repository root. Symbol names are included because line numbers will change.

| Finding | Evidence | Consequence for the implementation |
|---|---|---|
| Both complete mode launches construct hardware/simulation and web infrastructure | `amr_ws/src/amr_bringup/launch/mapping.launch.py::_sim_layer`; `nav.launch.py::_resolve` | Extract base and mode-only layers before adding a supervisor. Do not have it run these existing full launches unchanged. |
| Navigation already launches `web_node` | `nav.launch.py::_resolve` | The earlier chat's initial observation about missing navigation web wiring is obsolete at this baseline. |
| Hardware with lidar includes robot description twice | `drivers.launch.py` directly includes `description.launch.py`, then includes `lidar.launch.py`, which also includes it | Make the scanner-only layer independent of URDF; assert exactly one robot state publisher in composed launches. |
| Mode units conflict, but do not order their shutdown/start against each other | `amr_ws/deploy/amr_nav.service`, `amr_mapping.service` | Add explicit ordering during migration. `Conflicts=` alone is not a complete ownership handover. |
| Deployment scripts exist locally but are not tracked | `.gitignore: *.sh`; `git ls-files amr_ws/deploy amr_ws/env` lists only the two units and `amr.env` | Add narrow ignore exceptions and track wrapper, installer and environment scripts before claiming reproducible deployment. |
| Installed deployment differs from the chat snapshot | Read-only `systemctl cat` found both AMR units installed; `is-enabled` reported `amr_nav` enabled, legacy and mapping disabled | Installer/cutover must inspect actual installed units and enabled state. Do not assume the units are absent or legacy is the boot default. This does not establish which service is currently active. |
| Runtime is Ubuntu 22.04, ROS 2 Humble, systemd 249, installed SLAM Toolbox 2.6.10 | `/etc/os-release`, `/opt/ros/humble`, installed SLAM headers/package manifest, `systemctl --version` | Implement against these versions, regardless of future Jazzy preferences in personalization. |
| Installed SLAM base class is an ordinary `rclcpp::Node` | `/opt/ros/humble/include/slam_toolbox/slam_toolbox_common.hpp` | Use fresh mapping processes for each survey. Do not assume lifecycle reset functionality from newer distributions. |
| Survey abort clears coordinator state but retains the SLAM graph | `mapping_session_node.py::_srv_abort` | Supervisor must terminate the whole mapping layer on abort and spawn a new one for the next survey. |
| Survey save is blocking, toggles SLAM pause, publishes an immutable bundle, and leaves SLAM paused | `mapping_session_node.py::_srv_save`, `_pause_slam`; `map_bundle.py` | Serialize save with mode transitions; preserve result and draft information independently of the mapping process. Resolve uncertain save outcomes before retrying. |
| Web state retains old messages indefinitely, with ages exposed separately | `amr_web/adapter.py::RosAdapter.state`; `static/amr.js`, `maps.js`, `run.js` | Add generation-aware invalidation and explicit stale state. A stale READY must not remain visually or logically usable. |
| Run-page map choice only changes the canvas | `amr_web/static/run.js`, `run-map.onchange` | Provide an explicit robot map-selection operation and distinguish viewed map from active map. |
| Mission validation checks saved-file hashes but not the map active in AMCL | `route_executor_node.py::_srv_run`; `nav.launch.py` passes only `maps_dir` and footprint to executor | Bind map ID, revision, bundle hash and mode generation to the runtime executor and every mission load. |
| Mapping page has no live occupancy or scan view | `templates/maps.html`, `static/maps.js`; `MapView` loads saved bundle images | A browser-only survey needs live map, vehicle pose and scan overlay, not merely a new jog tab. |
| No manual ROS web endpoint exists | `amr_web/server.py::Adapter`, `adapter.py` | Add a bounded manual command adapter; never import `app.server`, whose module import constructs `Controller()`. |
| Mux has panel/route gating but no supervisor inhibition or drive-health subscription | `amr_base/gating.py`, `cmd_mux_kinematics_node.py` | Add a separate supervisor lease and fresh drive-state checks. Do not make the supervisor a second `MotionPermit` publisher. |
| Mux ignores the current permit's `run_id` | `cmd_mux_kinematics_node.py::_on_permit` creates `gating.Permit` with only time/source/enabled | Introduce explicit generation/run ownership; old messages cannot authorize a new mode. |
| Manual timing differs from the chat shorthand | `gating.Params`: command age 0.2 s, teleop selection window 0.5 s; `drive_node`: wheel command age 0.2 s | Do not describe 0.5 s as the sole deadman. The mux currently ramps a timed-out TELEOP selection toward zero; test and specify immediate command inhibition separately from physical deceleration. |
| Drive starts with `auto_arm=True` | `drive_node.py::__init__`, `_loop` | IDLE means no accepted motion command, not electrically de-energized. Keep the existing zero-target arm policy explicit in the UI and runbook. |
| CAN and DIO exclusivity relies on best-effort legacy detection | `amr_base/legacy_guard.py` uses systemctl and a process-name pattern | Add cooperative resource locks for actual owners. SocketCAN can be opened twice; a successful open is not exclusive ownership. |
| Diagnostics are richer in legacy than in ROS | `app/server.py`, `core/canmon.py`, `drivers/dio.py::snapshot`; current `DriveStatus`, `PanelState` | Add owner-published diagnostic snapshots; do not open diagnostic CAN/Modbus clients from Flask. |
| Horn expiry executes in the DIO driver's thread | `drivers/dio.py::set_coil`, `stop`; `panel_node.py` | It covers a lost renewal while that thread runs. It does not prove DO0 drops after a whole process/PC crash or cable loss; verify the island's actual behavior. |
| Current restart/fault language is inconsistent across docs | Root README describes legacy capabilities; implementation spec still lists old panel DI mapping | Update scoped ownership/status and DI mapping documentation as part of migration. Actual mapping is Start DI1, Reset DI2, AUTO/MANUAL DI3. |

Existing work to preserve: CAN write guards, drive-side heartbeat configuration, TPDO feedback and MLS IMU decoder, the single bus thread, panel debounce, physical motion authority, map bundle verification, route validation, fixed-route execution, and domain/DDS isolation.

## 3. Chosen process architecture

### 3.1 Supervisor as the service's main process

Add a Python supervisor executable in `amr_bringup`, with a ROS node named `amr_supervisor`. The service wrapper sources Humble, the built overlay and the vehicle environment, then **executes the supervisor directly**, for example through its Python module entry point. `systemd` must supervise its real PID, not a detached shell or an incidental outer launch process.

The supervisor owns these process groups:

| Group | Lifetime | Contents |
|---|---|---|
| Web | Whole service | One `amr_web/web_node`; remains available during ordinary layer failures. |
| Base | Whole healthy hardware session | Drive, physical panel, scanner, mux, wheel odometry, gyro bias, EKF, one URDF publisher; optional diagnostic-only RFID owner. |
| Mapping | One survey | Fresh `async_slam_toolbox_node` plus fresh `mapping_session_node`. |
| Navigation | One exact active map revision | Map server, AMCL, localization monitor, controller, behavior server, lifecycle managers and route executor. |
| Engineering viewer | Optional, whole service | One Foxglove bridge. Its failure must not restart CAN or invalidate a healthy autonomous run. |

Start web early so hardware/configuration failures can be reported. Start base after configuration and ownership checks. Do not start either mapping or navigation at boot. Never run both layers concurrently. A diagnostic commissioning job is a mutually exclusive substate of IDLE, not a third navigation stack.

The service supervisor contains policy and process orchestration, not CAN operations, map algorithms, route following or Flask request handlers. Keep it small through separation of responsibilities, but do not use a target such as “200 lines” as a correctness constraint.

### 3.2 Modules to introduce

Within `amr_ws/src/amr_bringup/amr_bringup/`:

- `mode_fsm.py`: pure transition rules, preconditions, deadlines, failure classification and recovery decisions; injected clock, no ROS or subprocesses.
- `operations.py`: bounded operation records, request deduplication, generation IDs and terminal results. Atomically journal accepted operations and important terminal outcomes to a small persistent state file; after a crash mark unfinished operations INTERRUPTED and reconcile any published map bundle, never replay their side effects.
- `process_supervisor.py`: spawn/reap, process group identities, exit events and bounded signal escalation.
- `readiness.py`: snapshots and readiness predicates for base, layers, lifecycle services, map identity and stop confirmation.
- `supervisor_node.py`: ROS adapter and single owner of orchestration state; main entry point and signal handling.
- `launch_helpers.py`: common launch construction and child exit handlers, if extraction materially reduces duplication.

Keep pure state tests independent of the built ROS interfaces. Use a serial state-machine event loop. ROS callbacks and process watchers enqueue events; bounded filesystem workers perform hash verification. Neither Flask nor a worker may mutate supervisor state directly.

### 3.3 Process lifecycle rules

- Spawn only an allowlisted executable and argument vector with `shell=False`. Map IDs, revisions and descriptions are data, never shell fragments or arbitrary launch names. Resolve map paths beneath the configured store and reject traversal, symlink escape and invalid/nonpositive revisions before calling existing bundle helpers.
- Each launch group uses its own process session/group. Record PID, process start identity, group role, supervisor instance and mode generation. Do not kill by executable name.
- Initially send SIGINT to the launch leader so launch forwards orderly shutdown. If it dies first, explicitly terminate remaining members of its recorded process group. Verify group emptiness; leader exit alone is insufficient.
- Inspect/test the installed launch behavior: its current subprocess helper does not create a fresh session for each child. Preserve this assumption with a process-tree test and forbid children that detach themselves.
- Register exit handling for every required node in each layer. A dead ROS node can otherwise leave its `ros2 launch` parent alive. An unexpected required-node exit ends the layer, even with exit code zero.
- Do not depend exclusively on launch exit codes: a clean launch shutdown may follow a failed node. The supervisor treats any unrequested layer termination as a fault.
- Startup/stop operations have explicit time budgets. At an expiry, inhibit motion, clean partial children and report failure. Never spawn the competing layer while cleanup is uncertain.
- All descendants remain in the `amr.service` cgroup. This is the final containment boundary if the supervisor itself crashes. Lock descriptors must be close-on-exec so unrelated children cannot accidentally retain another owner's resource lock.

Using fresh navigation processes on a map change is preferred over parking every lifecycle node for this first implementation. It removes retained AMCL state, map caches, action state and confirmation. Retain Nav2 lifecycle management *inside* the navigation layer. Later optimization requires evidence that restart latency matters.

## 4. Motion authority and state contracts

### 4.1 Keep three concepts separate

| Concept | Authority | Meaning |
|---|---|---|
| Operating mode | Supervisor | Which software layer exists and whether transitions are complete. |
| Route progress | Route executor | Mission/step/action state, pause/resume and current route permit. |
| Physical motion selection | Physical panel plus mux | MANUAL accepts permitted jog/commissioning commands; AUTO requires executor permission and a physical Start edge. |

Browser mode changes, map selection, mission load and fault acknowledgement do not synthesize Start, clear drive hardware faults, or restore interrupted execution.

### 4.2 Required interfaces

Add interfaces in `amr_interfaces`; register them in `CMakeLists.txt` and rebuild dependents. Final enum numbers should be frozen with interface tests.

| Interface | Proposed contents / semantics |
|---|---|
| `ModeState.msg`, `/amr/mode_state` | Supervisor instance UUID; generation; current mode; requested mode; transition phase; operation ID; base/layer readiness; active map ID/revision/hash; fault code/reason; manual/autonomous availability; last completed survey identity. Reliable/transient-local, on change and 2 Hz. Informational, not a motion lease. |
| `ControlLease.msg`, `/amr/control_lease` | Instance UUID, generation, increasing sequence, allowed manual/autonomous/commissioning classes and inhibit reason. Reliable/volatile depth 1, 10 Hz; expire by local monotonic receipt age after 0.3 s. Supervisor is the only publisher. |
| `MuxState.msg`, `/amr/mux_state` | Applied instance/generation, accepted source, inhibition state, output wheel setpoints and reason. At 10 Hz; used for transition acknowledgement and diagnostics, never as proof of physical stillness. |
| `RequestMode.srv`, `/amr/mode/request` | Request ID, expected instance/generation, target IDLE or NAVIGATION, exact map revision when applicable. Immediate accepted/rejected response with operation ID and reason. MAPPING entry is the start-survey transaction below. |
| `RequestSurvey.srv`, `/amr/supervisor/survey` | Request ID, expected instance/generation, operation START/RETURNED/SAVE/ABORT and associated map description/review note. Immediate acceptance; completion is asynchronous. |
| `OperationState.msg` plus `/amr/operations/get` query service | Operation ID, kind, phase, PENDING/SUCCEEDED/FAILED/INTERRUPTED, result map identity and diagnostic result. Bounded history. Query by ID recovers from a dropped HTTP response. |
| `ManualCommand.msg`, `/amr/manual_command` | Instance/generation, server-issued jog-session identity, increasing sequence, stamp, bounded validity, body `v` and `w`. Reliable/volatile depth 1. Receivers reject nonfinite, stale, wrong-generation and reordered input. |
| Existing `MotionPermit`, `WheelVelocities`, `RunState`, `MappingState`, `LocalizationState` | Add instance/generation where needed so supervised consumers cannot confuse data across layer replacement. `MotionPermit` retains route run ID; `WheelVelocities` carries the supervisor generation through to the drive owner. |

Separate durable UI state from expiring permission. A latched status message must never keep motion authorized. Use monotonic time for local lease/deadline checks; ROS time remains appropriate for sensor/TF stamps. A paused simulation clock must not extend a process-control timeout.

Control-lease consumers accept strictly increasing generations/sequences for the current supervisor instance. An instance change is a reset/inhibit event, never a permission-preserving update; previously retired instance IDs cannot return through delayed messages. Register/adopt a new instance only through the supervised startup/reset handshake. Validate producer age as well as local receipt age for stamped commands, and include sequence/age validation for route permits so queued old ENABLED samples cannot renew permission after a later disable.

For compatibility, existing bench launches may use an explicit unsupervised test configuration until migrated. Production always sets `require_supervisor=true` on mux and drive owner. Do not silently fall back to permissive behavior when the supervisor is absent. Terminal `/cmd_vel_teleop` remains an explicitly enabled engineering input; production browser commands use the stamped, generation-bearing interface. Migrate simulation tests to supervised control where they exercise the product path.

### 4.3 Enforcement in mux and drive owner

1. Mux requires a fresh matching supervisor lease before selecting *any* command source.
2. MANUAL also requires fresh valid panel data, fresh operational drive status and an allowed manual class. AUTO additionally requires NAVIGATION, a fresh matching executor permit and fresh corresponding command.
3. Supervisor never publishes `/amr/motion_permit`; there remains one route permit publisher.
4. Bind navigation command subscriptions to generation-specific topics, e.g. `/amr/layers/<generation>/cmd_vel` and `cmd_vel_rotate`; remap the Nav2 outputs in the layer launch. This prevents an old action publisher on a shared Twist topic from supplying a fresh-looking command to a new executor.
5. Clear cached manual/follow/rotate commands, permit and slew state on inhibition, panel-authority loss, disarm, generation change or supervisor replacement. Reopening a gate requires new input; it cannot revive held keys from before the change.
6. On command expiry or revoked authority, set wheel command output to zero at the next mux tick. Do not let the current TELEOP ramp extend an expired command. Physical ramp/deceleration remains a separate measured behavior of the drives.
7. Drive owner independently requires the matching fresh supervisor lease and fresh generation-bearing wheel command. This protects against a mux that remains alive publishing after its control-plane subscription stalls.
8. A lease heartbeat is produced only while the supervisor control loop is making progress. A separate thread must not perpetually renew a permission snapshot while the orchestration loop is deadlocked.
9. A drive or supervisor restart invalidates prior command/run state. Keep physical drive acknowledgement distinct from clearing a supervisor software fault.

These controls are application interlocks. The wired scanner/FX3/STO chain remains the hardware safety path.

## 5. State machine and transition protocol

### 5.1 States and permissions

| Supervisor state | Software layer | Manual command availability | Autonomous availability |
|---|---|---|---|
| STARTING | Base/web starting | None | None |
| IDLE | Base/web only | Fresh press under MANUAL after base readiness | None |
| MAPPING | Mapping layer ready; active survey | Under MANUAL, except save/transition inhibition | None |
| NAVIGATION | Navigation layer ready on exact map | Under MANUAL for repositioning/localization | Only through executor + physical AUTO/Start + localization READY |
| TRANSITIONING | Old layer stopping or new layer starting | None | None |
| FAULT | Base/web retained if healthy; failed layer stopped | None until explicit recovery | None |
| STOPPING | Service teardown | None | None |

Navigation readiness has two levels: **layer available** and **vehicle localized for execution**. Enter NAVIGATION when map server, lifecycle nodes and services are usable, even though AMCL is UNLOCALIZED. Otherwise the operator could never enter the mode needed to set an initial pose and jog to convergence.

### 5.2 Admissibility

- Ordinary mode switching requires fresh valid wheel feedback showing stillness continuously for 0.5 s, using a configurable initial threshold of 0.02 rad/s per wheel. A stale or invalid wheel is not “stopped.”
- Require valid panel data and MANUAL for operator-initiated map/mode replacement. Do not reinterpret selector AUTO as consent to discard a mission.
- Refuse switching while executor is READY, EXECUTING, PAUSED or BLOCKED. First use the explicit mission Abort operation, then confirm IDLE/stillness. DONE may switch once stopped; FAULT requires its acknowledgement/recovery path.
- Refuse a new mode while a survey is unsaved or SAVING. The operator must save or explicitly abort the survey first.
- Refuse any competing mode/save/commissioning operation while one is in progress. Duplicate request IDs return the existing operation; different requests get BUSY.
- A commissioning plan waiting for Start or executing also blocks mode replacement; explicitly clear/abort it first.
- Fault handling and service shutdown may bypass the *request-admission* stillness rule to inhibit and stop the system. They never wait for permission to issue zero output.

### 5.3 Common transaction

1. Validate request, expected instance/generation, map name/path and source-state prerequisites. Allocate an operation ID. Do expensive read-only map verification before tearing down a healthy layer where possible.
2. Mark TRANSITIONING, rotate the control generation and publish an inhibited lease. Revoke jog/commissioning sessions. Ask executor to cancel if this is an explicit abort/fault/shutdown path.
3. Require mux acknowledgement of the new inhibited generation and fresh stationary wheel evidence. Track command-zero and physical-stop evidence separately. If stillness cannot be established within the bounded stop deadline, latch FAULT; no new layer starts.
4. Stop old layer. Wait for process-group emptiness and required ROS endpoints to disappear. DDS discovery can lag process exit: wait with a deadline; never treat endpoint counts alone as the primary proof of process cleanup.
5. Invalidate old mapping/localization/run messages, map/scan/pose caches, preview markers and TF state in persistent consumers. Recreate the web adapter's TF buffer/listener for map-frame data so the old `map -> odom` cannot survive a switch. Base EKF/odometry remain intact.
6. Spawn the new layer with explicit instance/generation and resolved map identity, or complete IDLE with no layer.
7. Wait for concrete readiness predicates, not a fixed sleep or an existing process PID. Reject unexpected duplicate node/topic owners.
8. Commit the new stable mode. Publish the allowed lease. Commands accepted before this commit remain invalid. Complete the operation and expose its exact result to the browser.

No automatic rollback into the previous active mission. A pre-teardown validation refusal leaves the current mode unchanged. A post-teardown failure goes to FAULT with inhibition; explicit Recover-to-idle cleans remaining children and only then reopens fresh MANUAL control. A retry creates a new generation and new processes.

### 5.4 Start survey

1. From IDLE or an admissible NAVIGATION state, submit START with map ID and physical start-mark description.
2. Use the common transaction to remove navigation and start a fresh mapping layer.
3. Wait for fresh scan, corrected IMU, valid wheel stillness, map data and a new-generation map pose. The current `mapping_session._readiness()` is a starting point, not the only supervisor predicate.
4. Call the internal mapping coordinator's start service **once** when ready; record its start reference and session identity before permitting jog.
5. If coordinator start fails, stop the new layer and report FAULT. Do not silently keep an unrecorded graph collecting while the UI claims no survey.
6. Do not reset the persistent EKF/odom to zero to obtain a convenient map origin. SLAM's new map frame relates to the existing odometry frame; record the actual returned start reference.

Remap mapping coordinator services under a supervisor-owned internal namespace. The persistent public operation API must not vanish when the layer stops. Provide a compatibility adapter for existing standalone survey tests/tools during migration.

### 5.5 Return, save and abort survey

- RETURNED preserves the existing closure-evidence behavior. Confirmation never forces estimated pose equality.
- SAVE first inhibits manual control and confirms stillness, then runs the existing pause/serialize/stage/verify/publish sequence. Keep one writer per map store and one save operation at a time.
- Capture returned path, map ID, numeric revision and hash in supervisor operation state. Verify the published bundle independently before reporting success.
- After successful save, stop the mapping layer and return to IDLE. Show “Use this map for navigation” as an explicit follow-up action. Do not automatically load a mission or start navigation as a side effect of Save.
- Preserve the saved map/review/result on the page after mapping state disappears. Editing saved routes works in IDLE.
- Save failure with a responsive coordinator may return to RETURN_REVIEW after SLAM is confirmed resumed. A timeout is **unknown outcome**, not proof that saving stopped: observe operation/coordinator/bundle state before retry, teardown or another save. If pause state is uncertain, remain inhibited and require recovery.
- ABORT inhibits, stops the complete mapping layer and returns to IDLE. Preserve any `.draft-*` or abandoned `.staging-*` directories as unapproved evidence; never advertise them as revisions. Next survey always starts fresh.

### 5.6 Select navigation map

- Validate a plain map ID; resolve the requested numeric revision and verify the bundle. Prefer explicit numeric revision in the UI. If an engineering API permits `latest`, resolve it once and record the number before spawning anything.
- Pass map ID/revision/hash, footprint identity and generation to the navigation layer and executor. Verify again at layer startup to detect intervening file changes.
- Start lifecycle nodes with `autostart=false` for supervised launches. Wait for lifecycle services, invoke STARTUP on localization and navigation managers in defined order, and verify actual ACTIVE states/action endpoints. Replace reliance on the current 3 s / 6 s timers in the supervised path.
- Disable automatic lifecycle respawn/reconnection for the supervised layer; layer restart is an explicit supervisor operation. Retain appropriate bond monitoring, but do not use its current 20 s timeout as the motion-stop mechanism.
- Expect UNLOCALIZED initially. Initial pose, scan convergence and explicit confirmation remain necessary. Do not copy the last map's confirmation or assume the saved start mark is the vehicle's current position.
- Executor rejects any mission whose map ID, revision or hash differs from the **active** map, even if all its files are otherwise valid.
- Same exact map requested while already stable may return a no-op success. A revision change is a full navigation-layer replacement.

### 5.7 Timing budget to validate

| Item | Initial design budget | Evidence required |
|---|---|---|
| Manual command interval / expiry | 100 ms request cadence; 200 ms nonzero validity | Delayed/reordered HTTP and ROS traffic produces zero, never replay. |
| Supervisor lease | 10 Hz; 300 ms expiry | Lost/frozen supervisor causes inhibition at mux and drive owner independently. |
| Panel freshness | Preserve 200 ms | Cable-loss/stale-topic tests and measured vehicle stop. |
| Wheel feedback freshness | 100 ms for mode checks | No transition on missing/invalid feedback. |
| Stationary dwell | 500 ms | Stable near-zero readings, configurable after hardware measurement. |
| Controlled stopping | Initial 5 s maximum | Derive from permitted speed/deceleration and test; expiry latches fault. |
| Layer startup | Initial 30 s, including lifecycle activation | N97 startup/load measurements; UI shows phase and exact missing prerequisite. |
| Layer stop | Initial 12 s total | Accounts for launch SIGINT/TERM escalation; required for hung-child tests. |
| Map save | Initial 60 s operation budget | Large-map serialization measured; timeout handled as uncertain outcome. |
| Service stop | Initial 45 s systemd maximum | Combined supervisor stop schedule stays below it; no unbounded sum of child waits. |

These are proposed defaults, not measured guarantees. Sensor-age requirements and hardware-stop measurements govern acceptance, rather than a desired UI response time.

## 6. Web application and manual driving

### 6.1 Operator flow

| Page | Required behavior |
|---|---|
| Home/status | Shows operating mode, physical selector, energized/disarmed state, readiness/fault reasons and active map. Offers explicit Survey / Use saved map / Return to idle. |
| Manual | Hold-to-jog pad, speed selector within configured limits, command source, zero/stop action, drive de-energize action, live feedback. Available under valid MANUAL authority. |
| Maps/survey | Live occupancy, scan overlay, footprint/current pose, survey reference, closure evidence and save results; embedded instance of the same jog component. |
| Route editor | Existing map revision, line/turn tools, validation and immutable route saving. Editing a map never activates it on the vehicle. |
| Run | Shows the **active vehicle map** separately from any viewed map; initial-pose tool, convergence/scan overlay, confirmation, matching mission list, pause/abort/prepare-resume. Physical Start remains mandatory. |
| Monitor / I/O / alarms / parameters | Reimplemented against ROS data owners, as specified in section 7. |
| Commissioning | Final-phase equivalent of useful `/blind` diagnostics, guarded separately from ordinary jog and navigation. |

Use operator language such as “Starting navigation,” “Waiting for scanner,” or “Release jog control before changing mode.” Do not put ROS launch commands, service names or shell instructions in the normal operator flow. Engineering detail can remain in an expandable diagnostic view.

### 6.2 HTTP contract

- Add `POST /api/mode` with target mode, exact map selection where needed, request ID and expected generation. Return HTTP 202 plus operation ID for accepted asynchronous work; HTTP 409 for state conflict, HTTP 400/422 for invalid input, and HTTP 503 if the supervisor is unavailable.
- Preserve recognizable survey endpoint paths, but route them through supervisor operations. Update `maps.js`, which currently assumes synchronous HTTP 200 completion.
- Add `GET /api/operations/<id>` and include the current operation in `/api/state`. A browser refresh or reconnect retrieves progress; it does not resubmit the action automatically.
- UI must distinguish “accepted” from “completed.” Disable only conflicting controls, while keeping status updates and stop/abort controls usable.
- Initial pose, localization confirm/reset and mission load carry the expected current generation/map. Enforce matching state server-side and robot-side. Disallow initial-pose/reset changes during active or resumable runs unless that run has first been explicitly aborted.
- Mutating requests use strict JSON validation, size limits and same-origin checks. Do not enable permissive CORS on motion endpoints. Treat browser session tokens as concurrency controls, not user authentication.
- Service calls have bounded availability waits and explicit exceptions. Replace `RosAdapter._call()`'s “timed out therefore unavailable” ambiguity for long operations. A client timeout does not cancel a ROS server's work.
- Continue the Flask adapter protocol pattern and stubbed tests. Add an explicit ROS executor shutdown/join path in `web_node.py`; do not rely on an untracked daemon thread during service stop.
- Run one web process with the ROS adapter. Do not scale WSGI workers by forking multiple copies of the ROS node. Bound concurrent slow HTTP requests so map encoding or diagnostics cannot starve jog updates.

### 6.3 Jog command behavior

Reuse the legacy pad's interaction ideas: pointer capture, key combinations, release/blur/pagehide/hidden-tab cancellation. Port them into a shared AMR component instead of importing the legacy application.

Required changes beyond copying `manual.js`:

1. Initial maximum translation 0.30 m/s and rotation 0.30 rad/s, with selectable slower values. Validate body and resulting wheel limits using existing geometry/hardware ceilings. Do not copy the legacy RPM pad table or its different timeout as product defaults.
2. A new physical press obtains a short-lived server-issued jog session; only one browser session owns the pad. A second tab receives a conflict while the first holds it. Release, expiry, mode change, disarm or web restart invalidates the session.
3. Each refresh includes instance/generation, jog-session token and sequence. Validate under a lock, then publish once. No backend timer repeats the last browser command.
4. Reject late or reordered requests, an invalidated token, nonfinite numbers, malformed directions, and wrong-mode commands. Every rejected nonzero command must leave or restore zero as appropriate for the owning session.
5. Bound pending browser requests to prevent a slow network building a backlog. Responses are not motion leases. A fresh command must be sent while the control is still physically held.
6. Stop/release invalidates the session **before** sending zero. A delayed nonzero POST from that session must be rejected afterward. Test this race explicitly.
7. Focus in an input field disables jog keyboard shortcuts. Input restoration after mode changes/disconnect requires a new key/pointer press; it must not use a retained JavaScript `down` set.
8. Persistent header displays selector, drive state, command acceptance and stale feedback. HTTP connectivity by itself is not vehicle readiness.
9. `/api/stop` is explicitly defined: revoke the caller's manual/commissioning request; during autonomous execution use the mission Pause/Abort contract rather than a one-off zero Twist that the next action tick overwrites.
10. `/api/disarm` is an inhibit-and-de-energize operation through the supervisor and existing drive owner. It leaves `want_armed=false` until a deliberate physical-panel recovery action, documented and tested. Do not add a browser arm endpoint. Acknowledging a software latch must never perform deny-listed CAN fault reset or ETO clearing.

Keep command acceptance below ROS independent of the browser. HTTP, JavaScript and Wi-Fi are not reliable stop delivery mechanisms; the finite command lifetime is the fallback.

Specify freshness across the HTTP hop too: use a server-issued, single-use refresh ticket with a server-monotonic deadline, returned with each accepted refresh. Allow only one in-flight nonzero request per session and do not retry it automatically. After the ticket deadline, require a new press/session handshake; a delayed POST cannot acquire a fresh lifetime merely by arriving later. Carry only its remaining allowed command lifetime into the ROS command. Sequence numbers alone do not establish age, and an arbitrary browser wall clock is not a trusted timing source.

### 6.4 Live map and pose rendering

- Subscribe to `/map`, `/scan`, TF and base feedback in the adapter with their actual QoS. Tag mode-dependent caches by generation and clear them on transition.
- Extend `MapView` to accept live metadata and image frames, preserving origin yaw, resolution and image row orientation. A mapping map can grow and move its origin; metadata and image must share one snapshot ID.
- Generate an occupancy PNG in a bounded worker at at most 1–2 Hz initially; cache by snapshot ID. Serve metadata and the matching image separately. Never encode a large PNG while holding the adapter state lock or on a control callback.
- Send decimated scan points/pose at a bounded display rate, initially 5 Hz, transformed at the scan timestamp. Cap payload/queue sizes; latest data replaces older display frames.
- Display missing/stale transform data honestly. Do not place new-map scans over an old-map image after a switch.
- The live view must support seam/closure inspection during mapping and scan-to-map alignment during AMCL confirmation. Foxglove remains optional engineering tooling, not a requirement for the accepted operator workflow.
- Avoid resetting view pan/zoom on every image update. Hidden pages stop requesting display frames; this does not affect hardware acquisition.
- Bound the existing `_grids` cache in `server.py` for the newly long-lived web process. Large map lists should use verified metadata and bounded image/grid loading rather than retaining every occupancy array forever.

## 7. Diagnostic migration and legacy feature disposition

“All useful pages” requires data contracts as well as templates. Maintain a parity checklist recording each old display/control, new source, implemented behavior and test. Unsupported values display “not available,” never a plausible zero or old profile value.

| Existing capability | New owner / source | Migration decision |
|---|---|---|
| Manual jog | Web command adapter → mux → existing drive owner | Mandatory before unified hardware workflow. Shared component on manual/survey/run positioning views. |
| Drive states, faults, RPM/position | Existing drive owner and CAN router telemetry | Publish structured snapshots; use current TPDO/heartbeat/EMCY observations. |
| Voltages, temperature, current, torque/load and monitoring objects | Rate-limited reads on the **existing bus thread** | Reuse `core/canmon.py` object definitions and decoding after dependency review. Never create a second CAN owner. |
| IMU status | `MlsImu`, bias node, receipt-age monitoring | Show calibrated/raw z rate and available counters. Full legacy accelerometer/gyro axes require explicit low-rate acquisition; label absent channels until migrated. |
| CAN health / allowed and prohibited writes | Driver counters and pure guard metadata | Read-only. No generic CAN-write or arbitrary SDO endpoint. |
| All DI/DO lamps and Modbus link counters | `panel_node` snapshot from its existing `DioLink` | Publish full I/O image, ages, requested coil state and measured/readback state separately. Web creates no Modbus connection. |
| Horn/lights state | Panel owner's command and readback snapshot | Distinguish requested on/off from observed coil readback and physically verified horn/light operation. |
| Alarm/event history | Owner events + supervisor transitions | Bounded event stream with monotonic sequence, boot/instance identity and timestamps; journal retains engineering detail. No per-tick event spam. |
| Parameter/config page | Profile schema plus actual ROS parameter/launch overrides | Read-only effective configuration with source provenance. A profile value such as `can.use_rpdo=false` must not imply the ROS owner is using SDO setpoints. |
| RFID reader status/tags | One optional `rfid_node` wrapping existing `drivers/rfid.py` | Diagnostic-only, no localization or station authorization added. Reuse wire parser; isolate stale status and failures from navigation. |
| `/blind` encoder-only commissioning | ROS commissioning adapter around reusable pure `core/blindrun.py` logic | Migrate in the final feature-parity phase with exclusive authority, as below. No legacy CAN loop. |
| Preflight | Supervisor/base readiness snapshot | Read-only checks; requesting preflight never arms or changes operating mode. |
| Service restart from old alarms page | Replace with software recovery where sufficient | Routine layer recovery is supervisor-owned. Keep whole-service restart an engineering action; do not give Flask sudo/systemctl permission. |
| Former lidar page/listener | ROS lidar diagnostics and live map view | Do not resurrect the UDP listener or compete for scanner port 6060. |

### 7.1 Diagnostic transport and scheduling

- Use explicit typed messages for full I/O and raw wheel data used by commissioning. `diagnostic_msgs/DiagnosticArray` is suitable for named monitoring values, units, source timestamps, validity and error reasons. Do not make control logic parse human-readable KeyValue strings.
- Publish diagnostic snapshots at bounded rates, initially 1–5 Hz. GET requests consume snapshots only; opening more browsers cannot increase CAN/Modbus read traffic.
- The bus is currently 125 kbps and already serves TPDO/heartbeat/IMU. Add at most one bounded diagnostic SDO transaction per allocated slot, below command, feedback and heartbeat work. Measure worst-case timeout cost, not just successful reads.
- During motion, reduce or suspend optional slow monitoring if it threatens freshness. First establish detailed stationary monitoring, then admit the measured moving budget. Do not port the legacy 10 Hz round-robin schedule unchanged.
- Tighten `panel_node` drive-state freshness: its current `_armed` cache has no age. Horn claims must reflect fresh drive/command observations, while hardware fault behavior remains separately documented.
- Add event codes for startup, mode operations, readiness failures, ownership conflicts, save outcomes, layer exits, drive faults, panel loss and recovery. Bound event storage and journal volume.
- A parameter page aggregates effective configuration from the owning nodes, including supervisor/manual limits, ROS feedback rate, arm policy, DDS domain, footprint and active map. Do not add browser writes to vehicle profiles as part of this work.

### 7.2 Commissioning parity (`/blind` replacement)

This is a controlled engineering mode within IDLE. Its purpose remains encoder/geometry measurement; it is not a second autonomous route executor.

- Audit `core/blindrun.py` and preserve its straight, arc, pivot and per-wheel pulse semantics, bounds, settling checks and result recording where useful.
- Raw pulse targets require true signed raw counters, per-wheel inversion and measured counts-per-turn. Extend drive-owner telemetry with a typed raw-feedback message; do not reconstruct exact raw counts from rounded wheel radians.
- A plan upload/clear moves nothing. Execution requires fresh physical MANUAL + Start, base readiness and a distinct supervisor commissioning lease. Browser heartbeat may only maintain/expire an already physically authorized job; it cannot start it.
- While prepared/running/settling, ordinary jog and mode changes are refused. Selector change, stop/disarm, panel/drive/feedback loss, supervisor lease loss or command expiry aborts the job. No resume/replay after fault or restart.
- Commissioning output enters a dedicated mux source with the same supervisor generation, wheel limits and watchdogs; the adapter never publishes directly to CAN or `/cmd_wheel_vel`.
- Planning may produce per-wheel targets; mux enforces the applicable wheel/acceleration limits without losing the intended commissioning semantics. Test pulse wrap, reversed wiring flags, unequal wheel travel and stalled-wheel timeouts against the existing pure tests.
- Export results with raw start/end counters, scale, actual final distance/angle, gyro evidence, profile/configuration identity and abort reason. Preserve the operator's distinction between measurement and target accuracy.
- Do not delete the old commissioning page until this parity test passes or a later explicit scope decision retires it. This plan includes the migration; it is not silently deferred beyond legacy deletion.

## 8. Failure handling, shutdown and recovery

| Failure | Immediate behavior | Recovery |
|---|---|---|
| Invalid map/hash or invalid request before teardown | Reject operation; preserve current stable mode | Select/correct a valid revision. |
| New mapping/navigation layer never becomes ready | Inhibit; remove partial group; FAULT with missing prerequisites | Explicit recover to IDLE, then retry. |
| Required layer node exits, including executor or localization monitor | Inhibit via supervisor lease; stop the rest of that layer; invalidate progress and confirmation | Explicit recovery; fresh survey or map/localization/mission load. |
| Lifecycle node stays alive but becomes inactive/bond fails | Detect lifecycle/readiness loss; inhibit and fault layer | No automatic route resume or hidden reconnection. |
| Old group cannot be proven dead | Keep inhibit; never start a competing layer | Escalate cleanup; if ownership remains uncertain, whole-service stop/restart. |
| Supervisor exits or freezes | Lease expiry independently closes mux and drive gate; systemd supervises main PID | Restart only into IDLE with new instance identity. |
| Mux dies/freezes | Drive's wheel-command watchdog expires | Base fault; controlled base stop, new base generation after explicit recovery. |
| CAN/drive owner dies | Drive-side PC-loss mechanism remains the independent fallback | Stop dependent processes; software must not clear hardware alarms automatically. Recovery may require physical power cycle. |
| Physical panel/DIO loss | Invalid/stale panel closes authority | Fault active jobs; re-established comms do not revive keys, mission progress or held Start edges. |
| Lidar/bias/EKF/odom failure | Inhibit active product motion; classify as base fault | Preserve web diagnostics; clean base/layers before explicit recovery. No silent degraded driving mode in the initial release. |
| Browser/Wi-Fi disconnect during jog | Nonzero command expires; session becomes invalid | Fresh physical press after reconnection. |
| Browser/Wi-Fi disconnect during an autonomous run | Existing robot-side execution policy continues; browser is not the mission deadman | Reconnect for state; physical panel/stop path remains available. |
| Web process crash | Jog expires; no stale sessions on replacement | Supervisor may bounded-restart web. A healthy autonomous run need not depend on browser process uptime. |
| Foxglove or optional RFID diagnostics dies | Mark diagnostic degradation | Bounded optional restart; do not disturb CAN or route execution. |
| Save times out/client disconnects | Keep operation visible and observe actual completion; no duplicate save | Reconcile coordinator/bundle result before accepting retry. |
| Disk full/invalid permissions during save | No approved revision; preserve draft if possible, report error | Restore storage; retry only after outcome is known. |
| Whole-host power loss | Hardware stopping response; no software cleanup can be assumed | Boot IDLE; saved immutable revisions survive if committed, interrupted work is not replayed. |

### 8.1 Ordered service shutdown

The supervisor must keep its ROS context usable during controlled teardown; default rclpy SIGINT handling can invalidate it too early. Install explicit SIGINT/SIGTERM handling that sets a stop event, performs the bounded shutdown sequence, then shuts down the executor/context. Test both signals.

1. Stop accepting operations; publish STOPPING and revoke all command/job authority.
2. Cancel active actions where possible, confirm zero command acknowledgement and observe stopping. Failure to obtain a cancellation response does not delay inhibition.
3. Stop mapping/navigation group and confirm cleanup. Normal mode transitions use this same tested mechanism.
4. Request base disarm through the existing owner when responsive, then stop base. Allow `DriveNode.stop()` and `DriveLink.disarm()` to perform their existing cleanup, and `PanelNode.close()` to quiesce DO0.
5. Stop optional bridge and web; join workers, reap children, flush operation outcome and exit.

If shutdown interrupts an in-progress map save, the service-stop deadline takes precedence over the longer save budget: record INTERRUPTED/unknown outcome, stop within the bounded schedule, and reconcile an already atomically published bundle at next boot. Never report such a save as successful solely because shutdown completed.

Within the base group, the existing stop handlers may run concurrently. If measured cleanup ordering requires panel to outlive drive stop, implement explicit per-node ordering in the base launch rather than claiming order from list position.

Do not change the delicate `1016h` disarm sequencing as an incidental supervisor refactor. Current implementation clears the consumer heartbeat before its bounded speed-zero wait. Capture tests for clean exit and failed cleanup, and separately review any heartbeat-policy change. A SIGKILL bypasses these handlers; neither logs nor process exit alone prove the drives de-energized.

For action cancellation, fix the existing late-goal-response case: if an old goal is accepted after its run/generation is invalidated, cancel that accepted handle rather than simply returning. Keep generation/run/action identity on feedback/results. An abort service response is not proof the action server has stopped; track cancellation/completion and wheel stillness. Killing the old complete layer remains the final mode-switch boundary.

## 9. Deployment and resource ownership

### 9.1 New unit contract

Create `amr_ws/deploy/amr.service` with these reviewed properties:

| Setting | Planned value/purpose |
|---|---|
| `Type` | `simple` initially; systemd active means supervisor alive, while `/api/state` reports operational readiness. |
| `User`, `Group`, workspace | Existing `gvipc-evo-01` deployment, parameterized by the installer for future machines. |
| `ExecStart` | Tracked wrapper that sources Humble/overlay/environment and execs the supervisor as main PID. |
| `EnvironmentFile` | Installation configuration: workspace/root/profile/maps directory, host/port, optional Foxglove. Remove runtime map selection from the required environment. |
| `RuntimeDirectory` | Service scratch/state for PID metadata; map bundles remain outside `/run`. |
| `Conflicts` | `agv_controller.service amr_mapping.service amr_nav.service` during migration. |
| Ordering | Explicit `After=` relationship with conflicting units so their stop completes before this start; network/CAN infrastructure ordering is separately defined. |
| CAN dependency | Preserve correct ordering and binding to `can0`; inspect actual `canable@can0.service` provisioning rather than inventing `canable.service`. |
| `KillSignal` | `SIGINT`, handled explicitly by supervisor. |
| `KillMode` | `mixed`: main PID gets graceful signal; remaining cgroup members are the final kill boundary. |
| `TimeoutStopSec` | Initial 45 s, matched to tested internal deadlines. |
| `Restart` | `on-failure`, initial 5 s backoff and bounded start-rate limit. Always restarts IDLE; never replays persisted work. |
| Logs | stdout/stderr to journal, Python unbuffered; bounded ROS/log retention policy. |

`Conflicts=` needs ordering to guarantee completion of the old stop before the new start. `KillMode=mixed` needs a real main process that coordinates children; it is not an orphan-cleanup implementation by itself. These choices follow the installed-version [systemd 249 unit documentation](https://raw.githubusercontent.com/systemd/systemd/v249/man/systemd.unit.xml) and [kill documentation](https://raw.githubusercontent.com/systemd/systemd/v249/man/systemd.kill.xml).

Initial release retains binding to the CAN device, so a disappearing `can0` may stop the whole service, including the web UI. This limitation must be stated in the runbook; do not promise the UI survives all hardware outages. Base faults while the device remains present can retain web diagnostics. Changing CAN binding into a fully degraded UI-only service is a separate availability decision.

### 9.2 Lock ownership

- Add an application-instance lock plus separate CAN-owner and DIO-writer locks. Provision a stable local lock directory, e.g. `/run/lock/amr`, using an installed tmpfiles rule and correct service-user permissions.
- The process that actually owns a resource holds its nonblocking advisory lock for its full lifetime: drive owner holds CAN; panel owner holds DIO; temporary legacy controller must take both before starting threads. The supervisor's application lock is distinct so it does not deadlock its own children.
- A failed lock acquisition occurs before opening a socket/bus or arming. Do not unlink live lock files during recovery; locks release with descriptors/process lifetime.
- Add equivalent scanner ownership in approved launch/bench wrappers, and reject port conflict clearly. These cooperative locks cover repository entry points, not arbitrary external programs.
- Extend ownership checks to direct entry points/bench launches, not just systemd. Keep process-name detection as a diagnostic hint, not the sole exclusion guarantee.
- Production forces vehicle domain 10 and real panel; simulations run domain 20 or allocated test domains with separate ports/data/lock namespaces and no real hardware. Do not allow a request to change the running service's domain or enable a fake panel.

### 9.3 Installer and cutover

1. Add `.gitignore` exceptions for `amr_ws/deploy/*.sh` and `amr_ws/env/*.sh`; track the existing files with executable modes where appropriate. Do not globally unignore unrelated shell artifacts.
2. Make setup deterministic from a clean checkout: build/source overlay, verify package entry points, profile paths, map store permissions, lock provisioning and unit dependencies.
3. Installer stages/installs files and runs `systemctl daemon-reload` without starting hardware. Installation and vehicle cutover remain separate commands.
4. Record installed unit contents, drop-ins and enabled states before cutover. On this inspected host `amr_nav` was already enabled; disable it for the unified boot path.
5. At parked-vehicle cutover, stop the old unit, verify resource release, then start `amr.service` in IDLE. Enable only unified service once acceptance permits it.
6. Retain old units as disabled conflicting fallback during validation. No browser action switches to legacy behind the operator's back.
7. At final retirement remove old unit files/drop-ins, disable/mask obsolete entry points as appropriate, reload systemd and verify fresh boot. Remove temporary conflicts only when no legacy service can be started from the installation.
8. Update environment scripts to resolve installed paths/configuration rather than assuming every workspace is `$HOME/agv_can/amr_ws`; preserve domain 10/20 and loopback Cyclone configuration.

Rollback before retirement: stop unified service, verify its cgroup and resource owners are gone, restore the recorded previous units/configuration, then explicitly start the selected fallback. Immutable maps/routes are preserved. Interface/build rollback must restore a coherent source+overlay version; do not mix newly generated messages with old nodes.

## 10. File-level implementation work

All paths in the next table are relative to `amr_ws/` unless prefixed with “repo root.” Names of new files are proposed, not existing assets.

| Area | Files | Required work |
|---|---|---|
| Interfaces | `src/amr_interfaces/msg/{ModeState,ControlLease,MuxState,ManualCommand,OperationState}.msg`; new request/query services; existing state/command messages; `CMakeLists.txt` | Freeze enum/field/QoS contracts, instance/generation identity and operation result semantics. Add typed diagnostic/commissioning messages in their phase. |
| Supervisor | New `src/amr_bringup/amr_bringup/{mode_fsm,operations,process_supervisor,readiness,supervisor_node}.py` | Pure rules, serial orchestration, child management, readiness, timeout/outcome reconciliation, recovery and shutdown. |
| Packaging | `src/amr_bringup/{setup.py,package.xml}` and affected package manifests | Add supervisor entry point, rclpy/interfaces/lifecycle/std service dependencies and test dependencies. Avoid dependency cycles: `amr_base` consumes interface messages, not supervisor implementation. |
| Base launch | New `launch/base.launch.py` or shared base construction; existing `drivers.launch.py`, `sim.launch.py`, `lidar.launch.py` | Persistent real/fake base composition, exactly one description publisher, scanner-only include, strict real/sim selection, required-process exit handling. |
| Mode launches | New `launch/mapping_layer.launch.py`, `launch/navigation_layer.launch.py`; refactor existing mapping/nav wrappers | No base, web or Foxglove duplication. Pass generation/map identity, private command/service namespaces and lifecycle startup policy. Existing standalone wrappers compose these layers during transition. |
| Mux | `src/amr_base/amr_base/{gating,cmd_mux_kinematics_node}.py` | Supervisor lease, drive-status freshness, mode/generation/run gating, separate stamped manual input, private nav topics, command cache invalidation, zero-on-expiry and mux acknowledgement. |
| Drive owner | `src/amr_base/amr_base/drive_node.py`, targeted telemetry portions of `canopen.py` | Independent supervisor gate, generation-bearing commands, resource lock and snapshots. Preserve bus-thread ownership and guarded write/arm/disarm logic. |
| Panel | `src/amr_base/amr_base/{panel_node,panel_io}.py` | DIO lock, full I/O diagnostics, stale drive-state handling, physical recovery/commissioning edge semantics without phantom edges. |
| Resource locks | New shared pure lock helper, located where root and ROS owners can both import it; temporary root `canworker.py` change | Acquire resource locks before I/O. Preserve unique bare-module names and existing layout checks. |
| Survey coordinator | `src/amr_mission/amr_mission/mapping_session_node.py` | Generation/session reporting; internal service remaps; structured save state/outcome; robust unknown pause/save result handling. Keep map format compatibility. |
| Map storage | `src/amr_mission/amr_mission/map_bundle.py` | Shared map-ID/path containment validation, one-writer save discipline, crash-result discovery and draft classification. Retain atomic publish/hash checks. |
| Runtime executor | `src/amr_mission/amr_mission/{route_executor_node,run_fsm}.py` | Active-map binding, supervisor lease/generation prerequisite, cancellation completion/late-accept handling, correct IDLE/READY/fault transitions across teardown. |
| Localization | `src/amr_localization/amr_localization/localization_monitor_node.py`; `config/amcl.yaml` | Generation-aware state, no inherited confirmation, explicit reset/start behavior. Recreated per selected map. |
| Nav2 config | `src/amr_navigation/config/nav2_params.yaml`, launch-time overrides | Supervised lifecycle startup and reconnect policy; preserve RPP/Spin/footprint/obstacle policies. |
| Web backend | `src/amr_web/amr_web/{adapter,server,web_node}.py`; new pure manual/operation/cache helpers | Supervisor API, one-request-one-command manual adapter, live-map snapshots, effective diagnostics, bounded caches and explicit ROS-thread lifetime. |
| Web frontend | `templates/base.html`, new manual/status/diagnostic templates; `static/{amr,maps,run,mapview}.js`, shared `manual.js` | Persistent mode/status header, asynchronous operation UX, map activation, fresh-state rendering, shared jog control and diagnostic parity. Avoid blindly importing legacy scripts with incompatible state contracts. |
| Commissioning | New ROS adapter in `amr_base` plus typed raw feedback and commissioning commands; repo root `core/blindrun.py` only if an audited pure change is necessary | Reuse pure planning/measurement logic, physical Start, exclusive IDLE substate, bounded control and evidence export. |
| Deployment | `deploy/amr.service`, tracked wrapper/installer/env files, tmpfiles rule; repo root `.gitignore` | Coherent main PID, bounded shutdown, conflicts/ordering, reproducibility and staged cutover/retirement. |
| Documentation | `README.md`, `RUNBOOK.md`; repo root README and `manuals/slam-generalized-plan/amr_implementation_spec.md` | Unified workflow, revised ownership/interfaces, correct physical DI mapping, effective watchdogs, current capability status and acceptance evidence. |

`build/`, `install/` and generated message files are build outputs. Edit source files only; rebuild and source the overlay. Do not edit symlinked build copies or hand-edit installed Python artifacts.

The supervised lifecycle design uses the actual Humble manager's STARTUP/PAUSE/RESET/SHUTDOWN services and bond state, rather than assumptions from newer Nav2 documentation. See [Humble lifecycle manager implementation](https://raw.githubusercontent.com/ros-navigation/navigation2/humble/nav2_lifecycle_manager/src/lifecycle_manager.cpp). Required-process exit propagation and bounded launch escalation should be checked against [Humble launch implementation](https://raw.githubusercontent.com/ros2/launch/humble/launch/launch/actions/execute_local.py).

## 11. Ordered work packages and review gates

Implement in small reviewable commits. Each gate is a technical verification milestone, not a request for repeated user approval. Keep hardware-changing acceptance separate from offline work and schedule it with the person at the vehicle.

### U0 — Reproducible baseline and contracts

Dependencies: none.

- Record current commit, concurrent edits, installed units/enablement, hardware/environment versions and baseline tests.
- Track the missing deployment scripts through narrow ignore exceptions.
- Write interface/state contract tests first for the behaviors that can cause motion or stale-state errors. Finalize map identity, generation ownership, abort/save results and manual session behavior.
- Record acceptance fields and parameter sources in a short requirements-to-test checklist alongside this plan.

Exit gate: clean-checkout build/environment files present; agreed implementation contracts are explicit; no hardware behavior changes yet.

### U1 — Extract launch layers and repair ownership duplication

Dependencies: U0.

- Extract reusable base, mapping-only and navigation-only descriptions.
- Separate scanner from URDF startup; ensure one robot state publisher, EKF, lidar, web server and optional bridge.
- Keep existing `mapping.launch.py` and `nav.launch.py` as compatible standalone wrappers during transition; migrate tests without starting two bases.
- Add real/sim domain checks at all applicable entry points and test process exit propagation.

Exit gate: existing simulation topology and behavior remain equivalent; duplicate TF/publisher test passes; mode-only layers cannot accidentally start hardware/web.

### U2 — Motion gate and generation isolation

Dependencies: U0; U1 for integrated tests.

- Add supervisor lease, mux status, stamped manual commands and generation-bearing wheel/permit/state data.
- Gate both mux and drive owner; add drive freshness to mux; implement immediate zero output on expired commands.
- Clear stale commands on authority changes and isolate navigation command topics by layer generation.
- Add ownership locks and update temporary legacy owner to honor them.

Exit gate: fake-clock/unit and simulated fault-injection tests prove no command under absent/stale/inhibited authority, no replay after switch/restart and no duplicate resource ownership. Do not deploy the supervisor before these gates exist.

### U3 — Supervisor process management and idle service

Dependencies: U1, U2.

- Implement single-owner state loop, allowlisted child spawns, operation IDs/deduplication, SIGINT/SIGTERM handling and bounded process-group cleanup.
- Boot into STARTING then IDLE; launch persistent base/web and optional bridge.
- Implement base readiness, failure classification, inhibit acknowledgement and explicit recovery to idle.
- Test child leader death, grandchild persistence, supervisor freeze/crash, unexpected zero exit and late worker completion.

Exit gate: supervised simulation boots idle, stays stopped and cleans all descendants. Failures appear in state. No map/route layer needed for this gate.

### U4 — Survey transactions and navigation switching

Dependencies: U3.

- Implement start/return/save/abort supervisor operations and internal coordinator service remaps.
- Implement mode transition barrier, fresh survey creation, cleanup verification and stable map identity.
- Replace fixed-delay readiness with lifecycle service/active-state checks in supervised navigation.
- Bind executor to active map; correct late-goal cancellation and generation/state cache handling.
- Implement explicit save-to-IDLE, map activation and failure recovery.

Exit gate: one uninterrupted simulation service completes IDLE → MAPPING → save → IDLE → NAVIGATION → IDLE → new MAPPING with unchanged base PIDs and no retained graph/confirmation/progress.

### U5 — Browser jogging and operation UX

Dependencies: U2, U3; U4 for mode-specific UX.

- Add manual protocol/server validation, single-tab ownership, release invalidation and one-command-per-request publication.
- Implement shared jog component, physical-selector/drive-state display and stale-state behavior.
- Add mode requests, progress/status recovery and generation-aware map/mission operations.
- Keep Flask/ROS adapter tests independent of hardware.

Exit gate: browser automation proves press/release, focus loss, disconnect, two-tab conflict, malformed input, delayed command and mode-switch races. All are also stopped by robot-side expiry if browser zero delivery fails.

### U6 — Live survey and localization view

Dependencies: U4, U5.

- Add throttled live-map/image metadata, scan/pose overlays, map-origin growth handling and cache bounds.
- Integrate jog with survey and localization positioning; clear old overlays on mode changes.
- Make the active navigation map explicit and constrain mission selection to it.

Exit gate: complete browser-only simulation survey → save → editor → navigation localization → physical-panel-equivalent Start workflow. Foxglove is optional. Measure display-load impact on the N97.

### U7 — Monitor, I/O, alarms, parameters and RFID

Dependencies: U3; may be developed after U4 while retaining hardware scheduling discipline.

- Publish owner diagnostic snapshots and effective configuration.
- Add bounded diagnostic SDO schedule, monitoring-value validity and explicit readback/command distinction for I/O.
- Port event log, read-only parameter view, CAN metadata and optional RFID status.
- Replace legacy restart UI with scoped recovery behavior; define physical recovery after de-energize and software fault acknowledgement.

Exit gate: parity checklist passes for non-motion diagnostics; no extra CAN/Modbus owner; increased UI clients do not change bus poll rate; control deadlines still hold under diagnostic load.

### U8 — Commissioning feature parity

Dependencies: U2, U3, U7 raw telemetry.

- Add typed raw feedback, pure-library adapter and exclusive supervisor commissioning substate.
- Port useful blind-test planning, execution gating and measurement/export views.
- Cover counter wrap, scale/inversion, motion interruption, edge handling, latency and exactly-once plan execution.

Exit gate: simulation and controlled hardware checks match the useful legacy commissioning functions. Planning never moves; only a fresh physical Start under the permitted state can execute. No bypass of mux or drive ownership.

### U9 — Unified deployment and migration rehearsal

Dependencies: U4–U6; U7/U8 must finish before legacy retirement.

- Installable new unit/wrapper/configuration, lock directory provisioning and bounded restart policy.
- Verify stop/start ordering against each old service, cgroup cleanup, device dependency and no accidental enable/start from installer.
- Rehearse installation/rollback from a clean checkout and coherent overlay.
- Rewrite operator runbook for web workflow and service-failure recovery.

Exit gate: unit validation and simulated service fault tests pass. Hardware cutover checklist has concrete commands, expected observations and rollback files.

### U10 — Vehicle acceptance and sustained operation

Dependencies: U5–U9 complete for full scope.

- Run the hardware tests in section 12 with a person at the vehicle; record measured stopping/readiness/latency separately from expectations.
- Perform at least one real survey-to-route run and a second fresh survey without service restart.
- Complete diagnostic and commissioning parity checks and a sustained mixed-mode session.

Exit gate: all mandatory acceptance rows have evidence or a documented unresolved failure. An unresolved required row blocks retirement; a passing unit test is not substituted for a missing cable-loss/stop test.

### U11 — Retire legacy and close documentation

Dependencies: U10.

- Remove `canworker.py`, old `app/`, root `main.py` and legacy deployment references only after import/use audits show migrated equivalents.
- Preserve runtime libraries still imported through `amr_base.agv_repo`: profile loader/data, kinematics, CAN helpers/guards/decoders, DIO/RFID, panel and reused commissioning logic. Do not delete `drivers/` or `core/` as a category.
- Split or migrate legacy tests that still cover shared libraries. Update `tests/run_all.py`'s pinned module/check count deliberately with a coverage-migration explanation; do not lower it merely to make the test runner pass.
- Archive historical bench evidence/run logs and revise obsolete README claims; preserve the last deployable legacy revision/tag for engineering rollback history.
- Remove obsolete installed units and boot choices, confirm new service boot behavior, and update the ownership diagram/table in the spec using text/table form.

Exit gate: clean checkout builds/tests; `amr.service` is the only AGV application boot service; no legacy controller import, process, UI dependency or competing device owner remains.

### 11.1 Effort and sequencing expectation

For one engineer familiar with this repository, budget roughly **2–4 working weeks** for the complete scope including diagnostics, commissioning parity, failure tests and vehicle acceptance. Treat this as a planning range, not a delivery promise. The core unified workflow can reach a reviewable simulation milestone earlier; diagnostic scheduling and vehicle findings are the largest uncertainties. The earlier “one day plus jog pad” estimate does not cover this full retirement scope.

Critical order: authority contracts → launch/process ownership → supervisor transactions → web workflow → parity/acceptance → deletion. Do not remove the fallback merely because the new service can launch.

## 12. Verification and acceptance matrix

### 12.1 Offline and simulated tests

| ID | Test | Required observation |
|---|---|---|
| V01 | FSM transition table, every source/target state | Allowed transitions, explicit rejections, no implicit abort of READY/PAUSED/BLOCKED jobs or unsaved survey. |
| V02 | Duplicate/concurrent HTTP and ROS operation requests | Same request ID returns same outcome; different request rejected BUSY; bounded operation storage. |
| V03 | Stale generation/instance/sequence/manual token | Rejected at web and control consumers; a delayed release/nonzero command cannot revive or hijack a later session. |
| V04 | Lost/frozen supervisor with mux still publishing | Mux and drive owner each independently stop accepting nonzero by their lease deadline. |
| V05 | Expired manual command while source remains TELEOP | Zero output by declared command deadline plus one control tick; no software slew extension. |
| V06 | Old navigation publisher/permit and late accepted action | Generation-private topic cannot feed new run; old handle is canceled; results cannot advance a new step. |
| V07 | Same map name, different revision/hash and valid foreign mission | Load refused unless active ID/revision/hash match. Canvas selection alone does not activate robot map. |
| V08 | Abort/new survey in same service | New SLAM/coordinator PIDs and no retained graph/session reference; base PIDs/odom unchanged. |
| V09 | Save success/failure/client timeout/duplicate request/disk failure | Exactly one approved revision per operation; uncertain outcome reconciled; drafts never listed as approved. |
| V10 | Large map hashing/PNG work and slow clients | Control-lease publication and command handling remain within deadline; bounded worker/cache memory. |
| V11 | Layer startup fails halfway | All partial children cleaned, no competing map owner, FAULT visible, no automatic reopen of authority. |
| V12 | Launch leader exits while child lives; required child exits zero | Supervisor detects incomplete cleanup/failure; no new layer until all old owners are gone. |
| V13 | Child ignores SIGINT/TERM | Bounded escalation works; cgroup final cleanup on service stop; operation cannot hang forever. |
| V14 | Stale transient-local READY/RunState and old TF after switch | UI marks/clears state; robot rejects it; map transforms used only for current generation. |
| V15 | Navigation lifecycle inactive/unreachable but process alive | Readiness/permission lost; bounded transition failure; no reliance on PID alone. |
| V16 | Full simulated repeated workflow | Same base/web PIDs through map save/load/change; exactly one `/map` producer and `map -> odom` authority when relevant, none in IDLE. |
| V17 | Resource lock contention/direct legacy start | Second owner rejected before device I/O; fail-closed behavior independent of process-name matching. |
| V18 | Browser input race matrix | Release, blur, hidden tab, touch cancel, focused text field, two tabs, request reordering and network reconnection require fresh intentional press. |
| V19 | Sim/hardware isolation | Production rejects fake panel/test domain; tests do not bind physical devices, production ports, map store or locks. |
| V20 | Diagnostics load and unsupported channels | GET requests cause no bus I/O; missing values explicitly unavailable; stale status never looks live. |
| V21 | Commissioning job interruption and physical edge replay | One plan per fresh authorized Start; invalid/stale/held edges do not restart; no mode switch or jog competition. |
| V22 | SIGINT, SIGTERM, supervisor crash and reboot | New instance starts IDLE with no mission/survey/jog/commissioning replay; descendants cleaned within budget. |
| V23 | Clean-checkout deployment | Required `.sh` files tracked, executable wrapper available, unit references resolve, coherent message overlay, map files preserved on reinstall. |

Run the repository's relevant existing tests alongside these additions: root shared-library/controller tests while legacy remains; `amr_base` gating/CAN/panel tests; mission/map/FSM tests; web tests; launch/TF tests; and opt-in survey/localization/route/run-control simulation suites. Existing simulation tests pin domains 61–67: allocate new distinct test domains and ports and update `domains.TEST_RANGE`/documentation deliberately.

Use the documented `AMR_SIM_TESTS=1` and sequential simulation execution on the N97; simultaneous full navigation simulations can create resource-starvation failures. Introduce a browser-test harness only for meaningful input/state behavior, not snapshots that mirror HTML. Pure plan preparation does not require running hardware or full simulation tests; these are implementation gates.

### 12.2 Hardware acceptance

Record operator, commit/build identity, profile, active map revision/hash, timestamps and measured results for each row.

| ID | Sequence | Pass evidence |
|---|---|---|
| H01 | Fresh boot | Only unified application service enabled; UI reports IDLE; no route/commissioning execution; physical selector accurately shown. Energized zero-target state is distinguished from disarmed. |
| H02 | Manual forward/reverse/left/right at low speed | Correct wheel signs; hold/release behavior; horn/lights actual response; measured travel and stop. |
| H03 | Release / close tab / Wi-Fi loss / stale POST | Command-zero timestamp and measured physical stopping distance/time recorded separately. No restart on reconnection. |
| H04 | MANUAL → AUTO during jog; AUTO jog attempt | Output inhibited; new command cannot move under AUTO without route authorization. |
| H05 | Physical DIO cable loss and reconnection | Panel invalidity, command inhibition and actual horn/DO behavior measured. Reconnection produces no phantom Start/Reset or continued jog. This was skipped in the earlier session and remains unproven. |
| H06 | Fresh survey, drive loop, return, inspect, save | Live map remains usable in browser; closure evidence retained; saved bundle verifies; transition to IDLE preserves base process/odom. |
| H07 | Draw route, activate exact revision, initialize/confirm localization, load mission | No robot motion from editor, map activation, initial pose, confirmation or load. AUTO + fresh physical Start executes the drawn route. |
| H08 | Pause/abort, mode-change attempt during active/resumable run | Proper refusal until explicit job cleanup; no stale Nav2 command survives switching. |
| H09 | Select another saved revision, then new survey | Old localization/confirmation invalidated; new mapping graph; no base rearm cycle caused by successful mode replacement. |
| H10 | Layer crash and startup failure | Vehicle behavior agrees with inhibition design; browser shows reason; explicit recovery; no route replay. |
| H11 | Planned whole-service stop/restart | Drive de-energization/heartbeat-consumer cleanup verified and DO0 checked; no orphan scanner/CAN/panel/web processes. |
| H12 | Supervisor/drive crash and heartbeat PC-loss response | Controlled test with person at E-stop; record drive response and recovery. Prior accidental heartbeat fault is supporting evidence, not a substitute for a controlled failure-path test of the new service. |
| H13 | All diagnostic pages plus multiple browser views while driving | Sensor/command/heartbeat deadlines hold; bus/CPU/memory/log load measured; optional polls cannot starve control. |
| H14 | Commissioning parity | Straight/arc/pivot/pulse plans and aborts behave within configured bounds; evidence export and physical Start semantics validated. |
| H15 | Sustained mixed-mode use and final boot after retirement | Repeated switches do not accumulate processes, TF owners, stale operation results or memory; old service cannot start a competing controller. |

Use the existing sensor freshness targets as constraints: scan 0.15 s, wheels 0.10 s, corrected IMU 0.20 s and TF 0.20 s where applicable. Record latency distributions and failure counts under load; an average CPU percentage alone does not establish readiness. Begin sustained testing with a 60-minute session containing repeated mode switches and use observed drift/load to choose a longer production soak.

Full hardware acceptance still depends on measured footprint/clearance and the existing unresolved commissioning items. This service refactor does not establish geometric accuracy, functional safety certification, or hardware fault clearing behavior by itself.

## 13. Review checklist before implementation is considered complete

- [ ] There is one application service, one web app, one CAN owner, one DIO writer, one scanner owner and one local-odometry chain.
- [ ] Every required node exit and readiness failure reaches supervisor state; live launch parent PID is not mistaken for a healthy stack.
- [ ] Operating mode, panel selector, drive energized state, localization readiness and run state are distinct in code and UI.
- [ ] Persistent consumers reject stale generation data and reset map-dependent caches/TF between layers.
- [ ] A mode switch has an acknowledged command inhibit and independent stillness evidence.
- [ ] Saved-map identity is verified against the active runtime map, not just the files selected by a mission.
- [ ] Unknown save/cancellation outcomes are reconciled; retry never means uncontrolled duplicate work.
- [ ] Web jogging has one active owner, finite validity and release invalidation; no input replay after reconnect/restart.
- [ ] Clean shutdown and hard-failure fallback are both tested; DO and drive behavior are measured where software cannot guarantee them.
- [ ] Diagnostic and commissioning parity is complete before deleting the legacy app/loop.
- [ ] Shared root libraries/tests remain available to ROS; no dependency on a legacy controller is reintroduced.
- [ ] Deployment scripts are tracked and service cutover/rollback works from a clean checkout.
- [ ] Current source, installed overlay, installed units and runbook describe the same system.

## 14. Study limits and authoritative references

This plan is based on source inspection, local installed headers/Python launch code, Git metadata and read-only systemd configuration queries. No ROS hardware launch, actuator command, service restart, installation, runtime implementation or legacy deletion was performed during the study. The plan's proposed behavior is not claimed to exist or to have passed tests yet.

Local starting points:

- [Existing implementation specification](amr_implementation_spec.md), especially interfaces, ownership, survey storage, run state and deployment.
- [Workspace README](../../amr_ws/README.md) and [current runbook](../../amr_ws/RUNBOOK.md).
- [Hardware launch](../../amr_ws/src/amr_bringup/launch/drivers.launch.py), [mapping launch](../../amr_ws/src/amr_bringup/launch/mapping.launch.py), [navigation launch](../../amr_ws/src/amr_bringup/launch/nav.launch.py).
- [Mux](../../amr_ws/src/amr_base/amr_base/cmd_mux_kinematics_node.py), [drive owner](../../amr_ws/src/amr_base/amr_base/drive_node.py), [panel owner](../../amr_ws/src/amr_base/amr_base/panel_node.py).
- [Survey coordinator](../../amr_ws/src/amr_mission/amr_mission/mapping_session_node.py), [route executor](../../amr_ws/src/amr_mission/amr_mission/route_executor_node.py), [map bundle implementation](../../amr_ws/src/amr_mission/amr_mission/map_bundle.py).
- [Web server](../../amr_ws/src/amr_web/amr_web/server.py), [ROS web adapter](../../amr_ws/src/amr_web/amr_web/adapter.py), [legacy commissioning computation](../../core/blindrun.py).

Version-specific upstream references are linked at the design claims in sections 9 and 10. The implementation should prefer the installed Humble/systemd 249 behavior over rolling documentation and rerun the relevant process/lifecycle tests after dependency upgrades.
