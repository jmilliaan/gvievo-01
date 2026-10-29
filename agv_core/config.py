"""The vehicle profile. Every tunable parameter in the system lives here.

Reads profiles/<name>.json and publishes it as flat module-level constants, so
call sites read `config.TRACK_M` rather than digging through nested dicts.
Everything else imports this; this imports nothing but the standard library,
which is what keeps the dependency graph acyclic.

WHICH VEHICLE
=============
The profile is chosen by the AGV_PROFILE environment variable, falling back to
DEFAULT_PROFILE:

    (unset)                 # profiles/agv-01.json
    AGV_PROFILE=agv-02      # profiles/agv-02.json (amr.env for the service, or the shell)

and in the systemd unit, Environment=AGV_PROFILE=agv-01. There is no CLI flag
and no fallback to a profile that does not exist - a missing file is fatal and
lists the names that ARE present.

Five rules the loader enforces, in order of how much trouble they save:

  1. Unknown and missing keys are BOTH fatal. A profile with "k_rato" would
     otherwise leave the gain at whatever the code last defaulted to, and the
     vehicle would drive off with a number nobody chose. This is the main thing
     the JSON buys over .py constants and the main way it could bite.
  2. Only primitives are stored. Anything derivable is derived here, so the file
     cannot hold a geometry that disagrees with itself - no MPS_PER_RPM that
     contradicts the wheel diameter it was supposedly computed from.
  3. Validation runs before anything is published. A bad profile stops the
     process at import with the failing check named, rather than surfacing as
     strange behaviour halfway down a length of tape.
  4. profile_name must match the filename. A profile copied for a second
     vehicle and not renamed would report the old identity in the event log and
     in every run CSV header, and nothing would look wrong until two runs were
     compared weeks later.
  5. `tracked` (top level, true/false/null) says which product this vehicle is.
     false = trackless: the SLAM AMR, boots to IDLE, MAPPING/NAVIGATION are
     offered and LINE is refused. true = the magnetic-tape AGV: the supervisor
     enters LINE by itself once the base is up, and NAVIGATION/surveys are
     refused. null = both (2026-10-02): enters LINE by itself like true (since
     2026-10-08), every mode is offered, and the web shows Run and Mapping. It is read at boot;
     changing it means restarting amr.service.

load() is written as an atomic swap - parse and validate into a fresh namespace,
publish only on success - so nothing observes a half-applied profile. Only
called once today; a reload endpoint would be a caller, not a rewrite.


TUNING NOTES
============
JSON cannot carry comments, so the reasoning behind the settings that are not
self-evident lives here. Read this before editing a profile.

vehicle.invert_left / invert_right
    Both drivers take a POSITIVE 60FFh to travel forward on this AGV. If you swap
    a motor, re-flash a driver or remount a wheel, re-verify on blocks and set
    these rather than editing kinematics - everything above it stays in vehicle terms.

drivers.ramp
    6083h/6084h, written at arm time. One mode, "auto" (2026-10-02: the "manual"
    block went with canworker - drive_node always arms with this one, and the
    manual S-curve lives in cmd_mux). Set as transparent as is safe, on the
    assumption that the motion profile is shaped in software above it. A STOP
    falls through to this decel rate.
    CAUTION: with a 400 W motor on a gearhead the Function Edition warns the motor
    can be damaged by a hard decel while demand and actual velocity differ a lot
    (opman_fun:2951). This vehicle IS that combination (BLMR6400SKM-GFV-B, 1:30):
    the drives run in motion extension (drive_forward.PVCM_MOTION_EXTENSION), and
    the auto decel should not be raised far above its accel.
    CAUTION (auto): 6083h also caps how fast the wheel DIFFERENCE can slew, so
    it is the ceiling on YAW ACCELERATION as well as on forward ramp -
    kinematics.max_yaw_accel() turns it into rad/s^2 and gives 2.59 at the
    present 2400. A controller that commands a yaw rate the drives cannot slew
    to diverges, so derive the limit from this rather than hardcoding one; and
    raising this without re-checking traction is a different kind of mistake.


panel.di_manual_arm
    The Manual Arm input (DI08 on agv-01). Under MANUAL the drives are powered
    only while this input is HIGH; LOW leaves them in standby (CANopen up,
    encoders read, power stage off), so a jog, a pendant press, a survey move
    or a commissioning pp move does nothing until it is switched on. Under
    AUTO it is ignored: power follows the run (amr_base/arm_policy.py).

    It replaces manual_auto_arm (the selector in MANUAL was itself the arm
    command, 2026-10-08): the drives are no longer powered while idle.

    *** Power is not motion. *** A powered manual vehicle holds zero; every
    millimetre still needs a jog HELD (a stream older than 0.2 s is zero). And nothing here can
    power through the safety chain: an FX3 demand leaves the drives in ETO, the
    enable fails, and it is retried on a slow backoff, never latched.

timing.loop_period_s
    The 50 Hz bus loop in drive_node. Statusword, velocity, position and the error
    register arrive on drive TPDO1/TPDO2 (amr_base.canopen), so the loop carries no
    blocking telemetry poll.

rfid.*  (Chafon CF821, UHF EPC Gen2, TCP 2022)
    CF821 protocol captured from this unit on 2026-10-08 and CRC-verified; the
    framing and command codes are in agv_core/drivers/rfid.py. The reader streams tags on
    its own because its WorkMode is "active" - nothing we send starts it. The
    driver only ever QUERIES the reader (device info, parameters, heartbeat);
    reader settings are changed with the vendor tool, never from this code.

    tag_len is how many trailing EPC bytes form the tag id. Our tags carry a
    4-byte EPC and the route tables use the last 2 ("0020").

    ignore_tags discards ids before they become encounters. It used to hold
    "3130", an artifact of fixed-length framing chewing the device-info reply;
    length + CRC framing cannot produce it, so the list is normally empty.

rfid.heartbeat_s / heartbeat_timeout_s
    heartbeat_s > 0 sends the 0x0050 "online" query that often. Once the reader
    has answered one on a connection, a gap longer than heartbeat_timeout_s
    drops and reconnects the link - that is how a reader wedged behind a live
    TCP stack becomes rfid_comms_lost. A reader that never answers is reported
    once and not asked again. Ships 0 (off) until a bench run confirms the query
    does not interrupt active-mode streaming.

rfid.expect_work_mode / expect_region / expect_power_dbm
    What the reader is SUPPOSED to be configured as. The driver reads the real
    values (0x0072) on every connect and raises a warning event per mismatch -
    a swapped or factory-reset unit shows up on the dashboard. Never a stop.
    work mode 0 answer / 1 active / 2 trigger; region 0 custom / 1 US / 2 Korea /
    3 EU / 4 Japan / 5 Malaysia / 6 EU3 / 7-8 China. The unit shipped on US
    (902.75-927.25 MHz); Indonesia permits 920-923 MHz, which needs region 0.

timing.driver_timeout_s
    How long a drive's feedback may be missing before it is declared silent and
    the vehicle is stopped. This is HARDWARE health and has nothing to do with
    the operator's command freshness - that covers an absent operator, this
    covers an absent driver. Must sit above twice can.heartbeat_ms; _validate()
    enforces that.

can.heartbeat_ms
    Producer heartbeat time (1017h), written to each drive at bus-up. The
    driver default is 0 = OFF, and with it off a drive that has stopped
    responding looks identical to one that is simply idle - which is exactly
    the hole health.py was working around by inferring liveness from whether an
    SDO happened to answer. 200 ms is the plan's recommendation.

    Must be under half timing.driver_timeout_s or one missed heartbeat reads as
    a dead driver; _validate() enforces that. 0 leaves the drive's own setting
    alone.

freshness.*  (unified plan WP-A10, 2026-10-28; values unchanged from the ROS defaults)
    How old an input may be before it counts as absent. The GATE limits are the mux's
    (cmd_s, lease_s, permit_s, panel_s, drives_s) plus the protective field's (field_s):
    expiry means zero at once. Hard ceilings, refused above: cmd_s 0.2 s (a held manual
    command), lease_s and permit_s 0.3 s. The CONSUMER limits (line_*, executor_*) may only
    be at or above the gate limit they mirror: a consumer that calls an input stale while
    the mux still passes it would hold on what the mux lets through, and one tighter than
    the gate is a widening edit waiting to happen the other way. pc_heartbeat_ms is the
    PC's heartbeat to the drives and pc_loss_ms the drives' 1016h window (0 is refused:
    the drives would have no response to losing this PC); the heartbeat must be under
    half the window. feedback_hz is the drives' TPDO rate; timing.driver_timeout_s must
    cover at least three of its periods.

monitor.*
    Drive health monitoring - see manuals/obsolete/can-monitoring-plan.txt.

    *** DIAGNOSTIC ONLY. Nothing here may decide whether it is safe to move. ***
    The safety chain is lidar/encoders -> FX3 -> HWTO1/HWTO2 -> STO, in
    hardware. CAN is the channel beside it that records what happened and warns
    before a trip.

    The analogue objects are polled ONE PER NODE per poll, round-robin
    (canmon.MonitorPoller.step), paced by drive_node's monitor_period_* params.
    At tick rate that would be two SDO round-trips out of every 20 ms budget -
    about 4 ms of tick and a fifth of a 125 kbps bus - for values that move on
    a thermal timescale.

    Temperature warns are the plan's: driver trips at 85 C so warn at 70, motor
    trips at 95 so warn at 80. Bus voltage is two-sided - low is battery sag
    with stopping distance already degraded, high is regen the battery is
    refusing to take, and the high warn wants to sit well below the drive's
    own 63 V overvoltage trip.

horn.*
    The only output this software energises. One DO drives the horn AND the
    running lights together - one channel, one meaning - and it goes high
    whenever motion is COMMANDED: manual jog or auto run, no distinction,
    because the hazard is the same 150 kg either way and a horn that means two
    different things means neither.

    *** It follows the setpoint, not the wheels. *** The coil is raised from the
    commanded target, so it sounds at the instant motion is asked for rather
    than once the vehicle is already rolling - which is the whole point of a
    warning device. It also means the horn goes quiet while the drives are
    still decelerating, and that is the right way round: the warning ends when
    the vehicle stops being commanded to move, and what remains is a coast that
    is already ending.

    *** Not a safety function. *** The stop is the OSSD chain into the FX3, in
    hardware. This is an audible and visible warning and nothing gates on it: a
    horn that failed to sound must not be able to prevent a jog, or a broken
    lamp becomes a stranded vehicle.

    Renewal, not level. The command carries HORN_HOLD_S and the CAN tick renews
    it every 20 ms; a tick that stops renewing drops the coil at the DIO scan
    rather than leaving it energised. See the derived value.

blind_run.*
    Encoder-only test moves from /blind, to measure the encoders before SLAM
    relies on them. The page only SETS a plan; PB Start runs it, with the
    selector in MANUAL and the vehicle armed. Reset, a selector move, web Stop,
    a fault or lost 6064h feedback stops it. The plan survives a stop so the
    same move can be run again.

    Profile velocity mode with a software position loop: the faster wheel runs
    a trapezoid on its REMAINING counts at accel_rpm_s, capped at max_rpm; the
    other follows the planned ratio plus sync_kp (1/s) times its progress lag.
    A segment ends within stop_tolerance_mm, then waits settle_s at standstill
    before its counts are recorded. Overrunning by overrun_margin, or taking
    twice the planned time, aborts. max_distance_m caps each wheel per segment.

    Nothing steers on a sensor. The IMU yaw rate is written beside the encoder
    heading in the run CSV so the two can be compared afterwards - see imu.* -
    and that is the whole of its involvement.

    max_speed_mps caps the centre-path speed of a blind move on either backend
    (the commissioning node accepts up to this). Above ~0.4 m/s the protective
    field sizing of the nanoScan3/FX3 must be confirmed first; that is a check
    on the vehicle, not something this file can know.

pp.*
    Profile position (CiA 402 pp) blind moves, executed INSIDE the drives: the
    drive's own position loop runs each wheel to a count target. LOCKED by
    default (enabled false). The motor is a 400 W BLM with a 1:30 gearhead, and
    the BLV-R manual (function edition 3-4/3-6) requires motion-extension mode
    for that combination, which no positioning type offers. There is no vendor
    confirmation: enabling pp is an INTERNAL engineering decision to accept
    that risk, bounded by the settings below, the speed cap and a bench test
    on blocks first. vendor_ref records who decided, when and on what basis;
    the loader refuses enabled=true while it is empty.

    expect.* are the values a human sets IN THE DRIVES with MEXE02 (and saves).
    This software never writes them - they are on no allow-list in guard.py -
    it reads them back from both drives before every pp move and refuses on
    any difference, or while any of them is still null:
      max_torque_permille     6072h  caps motor torque so torque x 30 stays
                                     inside the gearhead's permissible torque
      following_error_counts  6065h  how far a wheel may lag before bit 13
      position_window_counts  6067h  "target reached" band
      halt_option             605Dh  Halt decelerates on the profile ramp (1)
      fault_reaction          605Eh  2 = quick-stop ramp (6085h), never 0 on a gear
      quick_stop_decel        6085h  r/min/s
    max_speed_mps is the pp cap, at most blind_run.max_speed_mps.

timing.auto_start_delay_s
    The pre-move warning (2026-10-08): every move that follows an operator's
    Start under AUTO - a run from Home, a station departure, a resume after an
    E-stop or an RFID hold - first powers the drives and sounds the ALARM horn
    for at least this long, then switches to the movement horn and moves. Tape
    (LineState ARMED) and trackless (RunState.premove) alike. A Reset, a
    selector move or a lapsed prerequisite during it cancels the start.
    Holds that resume by themselves (protective field, controller abort) keep
    their power and do not repeat the warning: nobody pressed anything.

timing.premove_timeout_s
    How long the pre-move phase waits for the drives to report Operation
    enabled before the start is refused ("drives did not power up"). Usually
    the safety chain: E-stop pressed or not yet reset. Must exceed
    auto_start_delay_s; the enable retry backoff is 2 s, so give it two tries.

mls.*  (SICK MLS line sensor, can.sensor_node; manuals/mls-marker-plan.md)
    What the sensor is expected to be configured as. drive_node only READS these
    objects and compares; the bench tool read_mls writes them (set-variant,
    set-markers), through guard.check_sensor.

    variant is 2006h:01, the TPDO1 packing (3 = Standard enhanced since
    2026-10-07). A difference is logged and decoded as reported.

    Marker events are always on (2026-10-23; markers_enabled is retired and refused):
    the sensor's own decoded code (2028h, standard mode, FailSafe) becomes
    /amr/line_marker events. The sensor not configured as below means NO events and a
    warning naming the fix - never a guess. Whether a marker changes a run is the
    mission's choice (high_zone, marker_run), not the profile's.
    marker_codes lists the codes laid on the floor (1-3 with the MLSE-0200,
    15 mm markers); any other code read is a reject, counted, never an event.
    polarity_lock expects 202Dh:05 = 1 (only north track seen): leave false until
    a full lap has shown north-up tape everywhere, because south-up track
    becomes invisible with it. teach_lock expects 2029h = 1 (keypad locked).

    event_clear (manuals/mls-diagnostics-plan.md E2): the value drive_node writes to
    2080h:01 to reset the sensor's latched event flag after reading its cause, or
    -1 = never write (only the first event after power-up is seen). 0 or 1, as
    the bench step E0.5 found; -1 until then. The only runtime MLS write.

    Nothing here is in the safety path or changes motion.

tape_loc.*  (tracked plan 3, manuals/tracked-plan-3-tape-localization.md)
    Tape-graph localization in LINE mode: AMCL on a frozen map revision, reduced to
    the distance along the taught tape (amr_line.tape_locator). enabled starts the
    localization group with the LINE layer (map_server, AMCL, localization monitor)
    on the map of the active tape graph ($AMR_STATE_DIR/line_graph.json); off, LINE
    runs exactly as before. Today it only TEACHES and SHADOWS (P1): the locator logs
    where it would stop and branch, and nothing it says changes motion.

    The rest are PROVISIONAL until P0 has measured them (plan section 5):
      k_odo               sigma growth per metre of wheel travel (P0 M6)
      amcl_sigma_floor_m  AMCL's along-track sigma floor; its covariance is optimistic (M1)
      max_lateral_m       a pose farther from the taught path is rejected (M2)
      innov_min_m         innovation gate floor; the gate is max(3 sigma, this)
      pose_max_age_s      an older /amcl_pose is not used
      sigma_station_m     a station stop needs sigma at most this when braking starts. At most
                          0.05 (2 sigma = the operator's +-10 cm); 0.05 since 2026-10-25, the
                          operator's choice: fewer `position` holds, the stop's own error on top
      sigma_junction_m    a junction order needs sigma at most this by S_fork - junction_lead_m
      lost_rejects        this many corrections rejected in a row = LOST
      sigma_lost_m        sigma above this = LOST
      healthy_window_m    HEALTHY needs an accepted correction within this much travel
      lost_fault_s        reserved, not read yet: LOST while held longer than this is to become a FAULT
      amcl_params         "default" (amr_localization/config/amcl.yaml) or "lean" (fewer
                          particles, update every 0.10 m: plan section 2.7)
      site_mission        the site-3 mission taught and shadowed: "test-mru-straight" while
                          only the straight in front of MRU is free (plan section 7),
                          "site-103" once the plant is
      shadow_circuit      the circuit of that mission the shadow locator follows
      live                tracked plan 4: false = shadow only; true = the site mission is a job
                          (Run → Calls): trips stop, branch, turn and speed up by position

    Not in the safety path (plan D6): every decision it feeds turns doubt into a hold.

imu.*
    The yaw-rate gyro inside the SICK MLS on can.sensor_node (amr_base.mls_imu):
    by TPDO when 1806h carries 2034h:03, else polled by SDO at drive_node's
    imu_poll_hz. A sensor that stops answering is backed off and probed again
    (mls_track.SdoProbe). See drivers/canbus/read_imu.py for the scaling.

can.channel / can.adapter_serial
    The SocketCAN interface to prefer, and which CANable2 to accept on the USB
    fallback. Per-vehicle hardware identity, so it belongs in the profile rather
    than in canbus/verify_drivers.py where it used to live. adapter_serial ""
    accepts any matching adapter, which is what a bench with one wants.

"""
import json
import math
import os
import re
import textwrap

# Anchored to the REPO ROOT, not to this file. config.py lives in agv_core/
# now, so dirname(__file__) would be agv_core/ and every profile lookup would
# miss - with no error until a vehicle boots and finds no profile at all.
# profiles/ stays at the root deliberately: it is site data, not library code.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(_ROOT, "profiles")
DEFAULT_PROFILE = "agv-01"

# Which vehicle this process is. Deliberately NOT named AGV_ID: the sibling
# KIM2A checkout uses that name, both are worked on from the same shell, and an
# export meant for one vehicle silently retargeting the other is the kind of
# mistake that only shows up as strange behaviour on a length of tape.
PROFILE_ENV_VAR = "AGV_PROFILE"


class ConfigError(Exception):
    """Raised for a malformed or physically nonsensical profile."""


def profile_path(name=None):
    """Resolve a profile name to a path. name > $AGV_PROFILE > DEFAULT_PROFILE.

    There is no fallback to a profile that does not exist: a missing file is
    fatal and says which name it looked for, in the same spirit as the key
    checks below. A silent fallback would let a typo'd AGV_PROFILE boot the
    wrong vehicle's geometry, which is exactly the failure this loader exists
    to prevent.
    """
    name = name or os.environ.get(PROFILE_ENV_VAR) or DEFAULT_PROFILE
    return os.path.join(PROFILE_DIR, f"{name}.json")


# section -> json key -> (exported name, type). The exported names match the
# constants these replaced, so the diff at every call site is one word.
_SCHEMA = {
    # Restored 2026-09-21 for the LINE layer (dual-product plan, Increment 1).
    # These are the tape follower's constants and they are read by
    # amr_line.autopilot through amr_line.runtime, never from here directly -
    # the engine is handed a namespace so a layer can be built in a test, in
    # sim and on the vehicle from three different sources of the same names.
    # The u_turn_* keys are carried now though nothing reads them until
    # Increment 3: the decision was to restore the profile block verbatim
    # rather than let it arrive in pieces.
    "autopilot": {
        "invert_error":        ("INVERT_ERROR", bool),
        "branch_positive_is_left": ("BRANCH_POSITIVE_IS_LEFT", bool),
        "k_ratio":             ("K_RATIO", float),
        "kd":                  ("KD", float),
        "ki":                  ("KI", float),
        "tau_d_s":             ("TAU_D_S", float),
        "ti_deadband_mm":      ("TI_DEADBAND_MM", float),
        "i_clamp":             ("I_CLAMP", float),
        "sr_pos_frac":         ("SR_POS_FRAC", float),
        "sr_rate_frac":        ("SR_RATE_FRAC", float),
        "sr_cap":              ("SR_CAP", float),
        "sr_tau_s":            ("SR_TAU_S", float),
        "auto_rpm":            ("AUTO_RPM", float),
        "auto_u_turn_rpm":     ("AUTO_U_TURN_RPM", float),
        "u_turn_center_tol_mm": ("U_TURN_CENTER_TOL_MM", float),
        "u_turn_resume_delay_s": ("U_TURN_RESUME_DELAY_S", float),
        "u_turn_min_deg":      ("U_TURN_MIN_DEG", float),
        "u_turn_max_deg":      ("U_TURN_MAX_DEG", float),
        # The spin may stop on the tape only past this TRUE angle, integrated from the gyro
        # (2026-10-24: the encoder over-reads ~15 % in a pivot - 206-209 deg for a good
        # U-turn - and a stop at 151 deg by encoder left the AGV ~50 deg off the tape).
        # 0 = off (encoder gate only); a stale gyro falls back to the encoder gate.
        "u_turn_gyro_min_deg": ("U_TURN_GYRO_MIN_DEG", float),
        "u_turn_center_kp_rpm_per_mm": ("U_TURN_CENTER_KP_RPM_PER_MM", float),
        "u_turn_level_tolerance": ("U_TURN_LEVEL_TOLERANCE", int),
        # Kink pivot (2026-10-23, amr_line.job): the tape left the sensor past
        # kink_edge_mm off centre (a corner with no radius, grooved into the floor) ->
        # stop, pivot toward it until centred, at most kink_max_deg. 0 turns it off.
        "kink_edge_mm":        ("KINK_EDGE_MM", float),
        "kink_max_deg":        ("KINK_MAX_DEG", float),
        # where the pivot stops: the tape within +/-kink_stop_mm (not centred - 2026-10-24)
        "kink_stop_mm":        ("KINK_STOP_MM", float),
        # Tracked speeds (2026-10-08, tracked-speed-plan-1): auto_rpm is NORMAL, the
        # default and the corner speed; HIGH = auto_rpm x auto_high_ratio, granted only
        # inside an MLS marker zone (mission high_zone, amr_line.speed_zone; RFID only
        # stops, 2026-10-09). AUTO_HIGH_RPM is derived.
        # k_ratio/kd are the NORMAL (corner) gains, high_k_ratio/high_kd the HIGH
        # (straight) gains; the follower interpolates between them on its own speed.
        "auto_high_ratio":     ("AUTO_HIGH_RATIO", float),
        "high_k_ratio":        ("HIGH_K_RATIO", float),
        "high_kd":             ("HIGH_KD", float),
        "high_ramp_s":         ("HIGH_RAMP_S", float),
        "curve_guard_kappa":   ("CURVE_GUARD_KAPPA", float),
        "curve_guard_e_mm":    ("CURVE_GUARD_E_MM", float),
        # The RFID speed toggle tags and their lockout moved to the mission's tag
        # table (2026-10-08, agv_core.mission v2), and the toggle itself became the
        # mission's high zone (v2.1), cued by MLS markers since v2.2 (2026-10-09).
        # gain_blend_s went with the slow zone's gains.
        "ramp_accel_rpm_s":    ("RAMP_ACCEL_RPM_S", float),
        "ramp_jerk_rpm_s2":    ("RAMP_JERK_RPM_S2", float),
        "sensor_max_mm":       ("SENSOR_MAX_MM", float),
        "sensor_max_step_mm":  ("SENSOR_MAX_STEP_MM", float),
        "line_loss_grace_m":   ("LINE_LOSS_GRACE_M", float),
        "sensor_timeout_s":    ("SENSOR_TIMEOUT_S", float),
        "auto_resume_hold_s":  ("AUTO_RESUME_HOLD_S", float),
        "dt_nominal_s":        ("DT_NOMINAL_S", float),
        "inner_wheel_min_rpm": ("INNER_WHEEL_MIN_RPM", float),
        # New in the ROS port, not a gy-demo key. sensor_timeout_s is a
        # STALENESS gate and cannot see a stream that is fresh but slow: the
        # MLS SDO fallback measured 9.8 Hz against a 50 Hz PID. This is the
        # rate floor the follower refuses to run below.
        "line_min_track_hz":   ("LINE_MIN_TRACK_HZ", float),
    },
    "vehicle": {
        "track_m":            ("TRACK_M", float),
        "wheel_dia_m":        ("WHEEL_DIA_M", float),
        "gear_ratio":         ("GEAR_RATIO", float),
        "motor_max_rpm":      ("MOTOR_MAX_RPM", float),
        "sensor_lookahead_m": ("SENSOR_LOOKAHEAD_M", float),
        "invert_left":        ("INVERT_LEFT", bool),
        "invert_right":       ("INVERT_RIGHT", bool),
    },
    "drivers": {
        # "ramp" is a nested dict; handled separately in _read_ramp().
    },
    "rfid": {
        "enabled":            ("RFID_ENABLED", bool),
        "ip":                 ("RFID_IP", str),
        "port":               ("RFID_PORT", int),
        "interface":          ("RFID_INTERFACE", str),
        "tag_len":            ("RFID_TAG_LEN", int),
        "ignore_tags":        ("RFID_IGNORE_TAGS", list),
        "recv_timeout_s":     ("RFID_RECV_TIMEOUT_S", float),
        "silent_warn_s":      ("RFID_SILENT_WARN_S", float),  # no reader since 2026-10-25 (lean D82)
        "reconnect_period_s": ("RFID_RECONNECT_PERIOD_S", float),
        "tag_hold_s":         ("RFID_TAG_HOLD_S", float),  # no reader since 2026-10-25 (lean D82)
        "tag_clear_s":        ("RFID_TAG_CLEAR_S", float),
        "heartbeat_s":        ("RFID_HEARTBEAT_S", float),
        "heartbeat_timeout_s": ("RFID_HEARTBEAT_TIMEOUT_S", float),
        "expect_work_mode":   ("RFID_EXPECT_WORK_MODE", int),
        "expect_region":      ("RFID_EXPECT_REGION", int),
        "expect_power_dbm":   ("RFID_EXPECT_POWER_DBM", int),
    },
    "dio": {
        "enabled":            ("DIO_ENABLED", bool),
        "ip":                 ("DIO_IP", str),
        "port":               ("DIO_PORT", int),
        # The module answers to any unit id; this is documentation, and the
        # value the requests carry.
        "device_id":          ("DIO_DEVICE_ID", int),
        "scan_period_s":      ("DIO_SCAN_PERIOD_S", float),
        "timeout_s":          ("DIO_TIMEOUT_S", float),
        "reconnect_period_s": ("DIO_RECONNECT_PERIOD_S", float),
        "silent_warn_s":      ("DIO_SILENT_WARN_S", float),
        "di_base":            ("DIO_DI_BASE", int),
        "do_base":            ("DIO_DO_BASE", int),
        "num_di":             ("DIO_NUM_DI", int),
        "num_do":             ("DIO_NUM_DO", int),
        "di_flipped":         ("DIO_DI_FLIPPED", bool),
        # "di_names"/"do_names" are lists sized against num_di/num_do;
        # handled separately in _read_io_names().
    },
    "lidar": {
        # SICK nanoScan3. The live UDP stream is owned by the ROS driver
        # (amr_ws, sick_safetyscanners2); the controller no longer listens.
        # These keys feed the frame decoder agv_core/lidarframe.py (checked against
        # a recorded fixture in tests/test_lidar.py) and the planned launch wiring;
        # nothing binds the port but the ROS driver. READ-ONLY: nothing here opens
        # a CoLa 2 session or writes to the device.
        "enabled":               ("LIDAR_ENABLED", bool),
        "host_ip":               ("LIDAR_HOST_IP", str),
        "sensor_ip":             ("LIDAR_SENSOR_IP", str),
        "port":                  ("LIDAR_PORT", int),
        "reassembly_timeout_s":  ("LIDAR_REASSEMBLY_TIMEOUT_S", float),
        # Provisional cut-off-path mapping. The status block's layout is not in
        # this repo, so the bytes it reads are configuration rather than code
        # until a human has walked the rings and confirmed them.
        "zone_block":            ("LIDAR_ZONE_BLOCK", int),
        "zone_active_low":       ("LIDAR_ZONE_ACTIVE_LOW", bool),
        "zones_validated":       ("LIDAR_ZONES_VALIDATED", bool),
        # "zone_bytes" is a list of ints; handled separately in _read_zone_bytes().
    },
    "panel": {
        "enabled":        ("PANEL_ENABLED", bool),
        "di_reset":       ("PANEL_DI_RESET", int),
        "di_start":       ("PANEL_DI_START", int),
        "di_auto":        ("PANEL_DI_AUTO", int),
        "auto_when_on":   ("PANEL_AUTO_WHEN_ON", bool),
        "di_manual_arm":  ("PANEL_DI_MANUAL_ARM", int),
        "debounce_scans": ("PANEL_DEBOUNCE_SCANS", int),
        "coincidence_hold_s": ("PANEL_COINCIDENCE_HOLD_S", float),
    },
    "horn": {
        "enabled":    ("HORN_ENABLED", bool),
        "do_channel": ("HORN_DO_CHANNEL", int),
    },
    "pendant": {
        # Hard-wired jog pendant on the DIO island: four direction pushbuttons,
        # levels resolved in core/panel.pendant_intent() (an opposing pair
        # cancels); the mux turns them into a body twist.
        "enabled":   ("PENDANT_ENABLED", bool),
        "di_fwd":    ("PENDANT_DI_FWD", int),
        "di_rvs":    ("PENDANT_DI_RVS", int),
        "di_left":   ("PENDANT_DI_LEFT", int),
        "di_right":  ("PENDANT_DI_RIGHT", int),
    },
    "can": {
        "bitrate":        ("CAN_BITRATE", int),
        "channel":        ("CAN_CHANNEL", str),
        "adapter_serial": ("CAN_ADAPTER_SERIAL", str),
        "heartbeat_ms":   ("CAN_HEARTBEAT_MS", int),
        "left_node":      ("LEFT", int),
        "right_node":     ("RIGHT", int),
        "sensor_node":    ("SENSOR_NODE", int),
    },
    "monitor": {
        "enabled":            ("MONITOR_ENABLED", bool),
        "driver_temp_warn_c": ("MON_DRV_WARN_C", float),
        "driver_temp_trip_c": ("MON_DRV_TRIP_C", float),
        "motor_temp_warn_c":  ("MON_MTR_WARN_C", float),
        "motor_temp_trip_c":  ("MON_MTR_TRIP_C", float),
        "bus_v_warn_low":     ("MON_BUS_V_WARN_LOW", float),
        "bus_v_warn_high":    ("MON_BUS_V_WARN_HIGH", float),
    },
    "mls": {
        "variant":         ("MLS_VARIANT", int),
        "polarity_lock":   ("MLS_POLARITY_LOCK", bool),
        "teach_lock":      ("MLS_TEACH_LOCK", bool),
        "event_clear":     ("MLS_EVENT_CLEAR", int),
        # "marker_codes" is a list of ints; handled separately in _read_marker_codes().
    },
    "tape_loc": {
        "enabled":            ("TAPE_LOC_ENABLED", bool),
        "k_odo":              ("TAPE_LOC_K_ODO", float),
        "amcl_sigma_floor_m": ("TAPE_LOC_AMCL_SIGMA_FLOOR_M", float),
        "max_lateral_m":      ("TAPE_LOC_MAX_LATERAL_M", float),
        "innov_min_m":        ("TAPE_LOC_INNOV_MIN_M", float),
        "pose_max_age_s":     ("TAPE_LOC_POSE_MAX_AGE_S", float),
        "sigma_station_m":    ("TAPE_LOC_SIGMA_STATION_M", float),
        "sigma_junction_m":   ("TAPE_LOC_SIGMA_JUNCTION_M", float),
        "junction_lead_m":    ("TAPE_LOC_JUNCTION_LEAD_M", float),
        "lost_rejects":       ("TAPE_LOC_LOST_REJECTS", int),
        "sigma_lost_m":       ("TAPE_LOC_SIGMA_LOST_M", float),
        "healthy_window_m":   ("TAPE_LOC_HEALTHY_WINDOW_M", float),
        "lost_fault_s":       ("TAPE_LOC_LOST_FAULT_S", float),
        "amcl_params":        ("TAPE_LOC_AMCL_PARAMS", str),
        "site_mission":       ("TAPE_LOC_SITE_MISSION", str),
        "shadow_circuit":     ("TAPE_LOC_SHADOW_CIRCUIT", str),
        # The LINE layer's readiness monitor: an AMCL correction (map->odom jump) beyond this
        # drops READY. 0.15 m (the NAVIGATION default) tripped on every lap on the MRU trunk
        # (2026-10-24, one 15 cm catch-up along the corridor); NAVIGATION keeps its own value.
        "monitor_jump_m":     ("TAPE_LOC_MONITOR_JUMP_M", float),
        # Tracked plan 4: false = the position engine only shadows (Teach's guided-run orders drive);
        # true = the site mission is a job, and trips stop, branch and turn by position.
        "live":               ("TAPE_LOC_LIVE", bool),
    },
    "imu": {
        "enabled":        ("IMU_ENABLED", bool),
    },
    "blind_run": {
        "max_distance_m":    ("BLIND_MAX_DISTANCE_M", float),
        "max_rpm":           ("BLIND_MAX_RPM", float),
        "accel_rpm_s":       ("BLIND_ACCEL_RPM_S", float),
        "settle_s":          ("BLIND_SETTLE_S", float),
        "stop_tolerance_mm": ("BLIND_STOP_TOLERANCE_MM", float),
        "sync_kp":           ("BLIND_SYNC_KP", float),
        "overrun_margin":    ("BLIND_OVERRUN_MARGIN", float),
        "max_segments":      ("BLIND_MAX_SEGMENTS", int),
        "max_speed_mps":     ("BLIND_MAX_SPEED_MPS", float),
    },
    # "expect" is nested and nullable; _read_pp_expect reads it (see pp.* notes).
    "pp": {
        "enabled":       ("PP_ENABLED", bool),
        "vendor_ref":    ("PP_VENDOR_REF", str),
        "max_speed_mps": ("PP_MAX_SPEED_MPS", float),
    },
    "timing": {
        "loop_period_s":      ("LOOP_PERIOD_S", float),
        "driver_timeout_s":   ("DRIVER_TIMEOUT_S", float),
        "auto_start_delay_s": ("AUTO_START_DELAY_S", float),
        "premove_timeout_s":  ("PREMOVE_TIMEOUT_S", float),
    },
    # See the "freshness.*" note above. Gate limits (the mux), the consumers' own limits,
    # and the drive link's PC heartbeat / loss window / TPDO rate.
    "freshness": {
        "cmd_s":             ("FRESH_CMD_S", float),
        "lease_s":           ("FRESH_LEASE_S", float),
        "permit_s":          ("FRESH_PERMIT_S", float),
        "panel_s":           ("FRESH_PANEL_S", float),
        "drives_s":          ("FRESH_DRIVES_S", float),
        "field_s":           ("FRESH_FIELD_S", float),
        "line_panel_s":      ("FRESH_LINE_PANEL_S", float),
        "line_lease_s":      ("FRESH_LINE_LEASE_S", float),
        "line_drives_s":     ("FRESH_LINE_DRIVES_S", float),
        "executor_panel_s":  ("FRESH_EXEC_PANEL_S", float),
        "executor_drives_s": ("FRESH_EXEC_DRIVES_S", float),
        "pc_heartbeat_ms":   ("PC_HEARTBEAT_MS", int),
        "pc_loss_ms":        ("PC_LOSS_MS", int),
        "feedback_hz":       ("DRIVE_FEEDBACK_HZ", float),
    },
}

_TOP_LEVEL_SCALARS = {"profile_name": ("PROFILE_NAME", str), "tracked": ("TRACKED", bool)}
_NULLABLE_TOP_LEVEL = {"tracked"}


def _coerce(value, want, where):
    """JSON has one number type, so 2000 must be accepted for a float field -
    but a bool must never pass as a number, because in Python it silently would.
    """
    if want is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{where}: expected true/false, got {value!r}")
        return value
    if isinstance(value, bool):
        raise ConfigError(f"{where}: expected a number, got {value!r}")
    if want is int:
        if not isinstance(value, int):
            raise ConfigError(f"{where}: expected a whole number, got {value!r}")
        return value
    if want is float:
        if not isinstance(value, (int, float)):
            raise ConfigError(f"{where}: expected a number, got {value!r}")
        # An int too large for a float raises here; a float that already read
        # as inf (1e999 in the file) is refused below. Either way a positive-only
        # check would otherwise pass infinity - a watchdog that never expires.
        try:
            out = float(value)
        except OverflowError:
            out = math.inf
        if not math.isfinite(out):
            raise ConfigError(f"{where}: expected a finite number, "
                              f"got {value!r:.40}")
        return out
    if want is list:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{where}: expected a list of strings, got {value!r}")
        return list(value)
    if want is str:
        if not isinstance(value, str):
            raise ConfigError(f"{where}: expected a string, got {value!r}")
        return value
    raise ConfigError(f"{where}: unsupported schema type {want!r}")


def _read_io_names(raw, count, where):
    """dio.di_names / do_names -> exactly `count` strings.

    _SCHEMA's flat table can say "a list of strings" but not "as many as
    num_di", and that is the check worth having: a 16-lamp page fed 12 labels
    would silently mislabel channels 12-15 or blank them, which is worse than
    no names at all.
    """
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise ConfigError(f"{where}: expected a list of strings")
    if len(raw) != count:
        raise ConfigError(f"{where}: has {len(raw)} name(s) but there are "
                          f"{count} channel(s) - they must match")
    return [v.strip() for v in raw]


def _int_list(raw, where, what="integers"):
    """A JSON list of plain ints (bools refused), or ConfigError naming `where`."""
    if not isinstance(raw, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in raw):
        raise ConfigError(f"{where}: expected a list of {what}")
    return raw


def _read_do_list(raw, count, where):
    """dio.motion_on / dio.alarm_on -> sorted DO channel numbers, distinct, in 0..num_do-1.

    Operator, 2026-10-02:
      motion_on  DO00 (movement horn) and DO08: on while the motors turn, any mode.
      alarm_on   DO01 (alarm horn): on while an AUTO run is active and the protective
                 field is violated or warning field 1 or 2 is occupied.
      movement_horn  the motion_on channels that ARE the movement horn (DO00): off while
                 the alarm horn sounds, so a field switches the sound (2026-10-07).
    """
    _int_list(raw, where, "DO channel numbers")
    if len(set(raw)) != len(raw):
        raise ConfigError(f"{where}: a channel is listed twice")
    bad = [v for v in raw if not 0 <= v < count]
    if bad:
        raise ConfigError(f"{where}: channel(s) {bad} outside 0..{count - 1}")
    return sorted(raw)


def _read_zone_bytes(raw, where):
    """lidar.zone_bytes -> one byte offset per cut-off path, in path order.

    A list of ints, which _SCHEMA's flat table cannot express (its `list` means
    a list of strings, for the I/O names). Three entries, because the device's
    verification report defines paths 1-3 as stop, slow and warn - and the
    ORDER is the thing lidar_brief.md sec 2.5 insists must be confirmed rather
    than assumed, which is exactly why it lives in the profile.
    """
    _int_list(raw, where)
    if len(raw) != 3:
        raise ConfigError(f"{where}: expected 3 offsets (stop, slow, warn), "
                          f"got {len(raw)}")
    if any(v < 0 for v in raw):
        raise ConfigError(f"{where}: byte offsets must be >= 0, got {raw}")
    return list(raw)


def _read_marker_codes(raw, where):
    """mls.marker_codes -> the SICK standard-mode marker codes laid on the floor.

    Standard mode decodes 1-7 (manual 8021642 p. 52); which of them are usable
    depends on the sensor length and marker width (MLSE-0200 + 15 mm: 1-3)."""
    _int_list(raw, where)
    if not raw:
        raise ConfigError(f"{where}: expected at least one code")
    if len(set(raw)) != len(raw):
        raise ConfigError(f"{where}: duplicate code in {raw}")
    if any(not 1 <= v <= 7 for v in raw):
        raise ConfigError(f"{where}: standard-mode codes are 1..7, got {raw}")
    return sorted(raw)


def _read_ramp(raw):
    """drivers.ramp -> {"auto": {...}} of ints."""
    ramp = raw.get("ramp")
    if not isinstance(ramp, dict):
        raise ConfigError("drivers.ramp: missing or not an object")
    unknown = set(ramp) - {"auto"}
    if unknown:
        raise ConfigError(f"drivers.ramp: unknown mode(s) {sorted(unknown)}")
    out = {}
    for mode in ("auto",):
        block = ramp.get(mode)
        if not isinstance(block, dict):
            raise ConfigError(f"drivers.ramp.{mode}: missing or not an object")
        unknown = set(block) - {"accel", "decel"}
        if unknown:
            raise ConfigError(f"drivers.ramp.{mode}: unknown key(s) "
                              f"{sorted(unknown)}")
        missing = {"accel", "decel"} - set(block)
        if missing:
            raise ConfigError(f"drivers.ramp.{mode}: missing key(s) "
                              f"{sorted(missing)}")
        out[mode] = {k: _coerce(block[k], int, f"drivers.ramp.{mode}.{k}")
                     for k in ("accel", "decel")}
    return out


# pp.expect: the drive-side values verified before a pp move -> (index, name).
PP_EXPECT_OBJECTS = {
    "max_torque_permille":    0x6072,
    "following_error_counts": 0x6065,
    "position_window_counts": 0x6067,
    "halt_option":            0x605D,
    "fault_reaction":         0x605E,
    "quick_stop_decel":       0x6085,
}


def _read_pp_expect(raw):
    """pp.expect -> {name: int | None}. Every key present; null means "not
    configured yet", which keeps pp unavailable rather than failing the load."""
    block = raw.get("expect")
    if not isinstance(block, dict):
        raise ConfigError("pp.expect: missing or not an object")
    unknown = set(block) - set(PP_EXPECT_OBJECTS)
    if unknown:
        raise ConfigError(f"pp.expect: unknown key(s) {sorted(unknown)}")
    missing = set(PP_EXPECT_OBJECTS) - set(block)
    if missing:
        raise ConfigError(f"pp.expect: missing key(s) {sorted(missing)}")
    return {k: None if block[k] is None else _coerce(block[k], int, f"pp.expect.{k}")
            for k in PP_EXPECT_OBJECTS}






def _parse(doc):
    """Raw JSON document -> flat namespace of primitives. Strict both ways."""
    if not isinstance(doc, dict):
        raise ConfigError("profile must be a JSON object")

    expected_sections = set(_SCHEMA) | set(_TOP_LEVEL_SCALARS)
    unknown = set(doc) - expected_sections
    if unknown:
        raise ConfigError(f"unknown top-level key(s): {sorted(unknown)}")
    missing = expected_sections - set(doc)
    if missing:
        raise ConfigError(f"missing top-level key(s): {sorted(missing)}")

    ns = {}
    for key, (name, want) in _TOP_LEVEL_SCALARS.items():
        # tracked: null is a value, not a missing key - it means both products.
        ns[name] = None if key in _NULLABLE_TOP_LEVEL and doc[key] is None else _coerce(doc[key], want, key)

    for section, fields in _SCHEMA.items():
        block = doc[section]
        if not isinstance(block, dict):
            raise ConfigError(f"{section}: expected an object")
        allowed = set(fields)
        if section == "drivers":
            allowed.add("ramp")
        if section == "dio":
            allowed |= {"di_names", "do_names", "motion_on", "alarm_on", "movement_horn"}
        if section == "lidar":
            allowed |= {"zone_bytes"}
        if section == "mls":
            allowed.add("marker_codes")
        if section == "pp":
            allowed.add("expect")
        unknown = set(block) - allowed
        if unknown:
            raise ConfigError(f"{section}: unknown key(s) {sorted(unknown)}")
        missing = allowed - set(block)
        if missing:
            raise ConfigError(f"{section}: missing key(s) {sorted(missing)}")
        for key, (name, want) in fields.items():
            ns[name] = _coerce(block[key], want, f"{section}.{key}")

    ns["RAMP"] = _read_ramp(doc["drivers"])
    ns["PP_EXPECT"] = _read_pp_expect(doc["pp"])
    # Sanity-check the counts BEFORE the name lists are sized against them, or
    # "num_di": 0 gets reported as a problem with di_names, which sends the
    # reader to fix the wrong key.
    for key, name in (("num_di", "DIO_NUM_DI"), ("num_do", "DIO_NUM_DO")):
        if not 1 <= ns[name] <= 256:
            raise ConfigError(f"dio.{key}: expected 1..256, got {ns[name]}")
    ns["DIO_DI_NAMES"] = _read_io_names(
        doc["dio"]["di_names"], ns["DIO_NUM_DI"], "dio.di_names")
    ns["DIO_DO_NAMES"] = _read_io_names(
        doc["dio"]["do_names"], ns["DIO_NUM_DO"], "dio.do_names")
    ns["DIO_MOTION_ON"] = _read_do_list(
        doc["dio"]["motion_on"], ns["DIO_NUM_DO"], "dio.motion_on")
    ns["DIO_ALARM_ON"] = _read_do_list(
        doc["dio"]["alarm_on"], ns["DIO_NUM_DO"], "dio.alarm_on")
    ns["DIO_MOVEMENT_HORN"] = _read_do_list(
        doc["dio"]["movement_horn"], ns["DIO_NUM_DO"], "dio.movement_horn")
    ns["LIDAR_ZONE_BYTES"] = _read_zone_bytes(
        doc["lidar"]["zone_bytes"], "lidar.zone_bytes")
    ns["MLS_MARKER_CODES"] = _read_marker_codes(
        doc["mls"]["marker_codes"], "mls.marker_codes")
    return ns


def _derive(ns):
    """Everything computable from the primitives, so the profile cannot carry a
    value that contradicts the one it was derived from."""
    # Motor r/min -> wheel travel. One wheel turn covers pi*D and takes
    # GEAR_RATIO motor turns, so v = (N / GEAR_RATIO) * pi*D / 60.
    ns["MPS_PER_RPM"] = (math.pi * ns["WHEEL_DIA_M"]
                         / (ns["GEAR_RATIO"] * 60.0))          # 3.14159e-4
    ns["RPM_PER_MPS"] = 1.0 / ns["MPS_PER_RPM"]                # 3183.1
    # Yaw rate from a left/right difference: omega = (v_right - v_left) / TRACK.
    ns["RAD_S_PER_RPM_DIFF"] = ns["MPS_PER_RPM"] / ns["TRACK_M"]   # 6.46418e-4
    # Wheel rad/s per motor r/min (before any invert flag): 2*pi/60 through the gearhead.
    ns["WHEEL_RAD_S_PER_MOTOR_RPM"] = 2.0 * math.pi / 60.0 / ns["GEAR_RATIO"]  # 3.49066e-3
    ns["MAX_SPEED_MPS"] = ns["MOTOR_MAX_RPM"] * ns["MPS_PER_RPM"]  # 1.2566 m/s
    # HIGH follows NORMAL (the junction slow zone and the RFID toggle are retired).
    ns["AUTO_HIGH_RPM"] = ns["AUTO_RPM"] * ns["AUTO_HIGH_RATIO"]

    # 6083h caps both the forward ramp and the rate at which the wheel
    # DIFFERENCE can slew, so it is also the ceiling on yaw acceleration -
    # kinematics.max_yaw_accel() turns it into rad/s^2. Whatever produces
    # (v, omega) next has to respect that, and must DERIVE its limit from this
    # rather than carry a hardcoded one, or a later ramp change silently
    # commands a yaw rate the drives cannot produce.
    ns["ACCEL_RPM_S"] = ns["RAMP"]["auto"]["accel"]
    ns["DECEL_RPM_S"] = ns["RAMP"]["auto"]["decel"]

    # Threshold table for canmon.MonitorPoller.snapshot(). Two-sided on bus
    # voltage: low is battery sag (stopping distance already degraded), high is
    # regen the battery is refusing to take.
    ns["MONITOR_THRESHOLDS"] = {
        "drv_c": {"warn": ns["MON_DRV_WARN_C"], "trip": ns["MON_DRV_TRIP_C"]},
        "mtr_c": {"warn": ns["MON_MTR_WARN_C"], "trip": ns["MON_MTR_TRIP_C"]},
        "bus_v": {"warn_low": ns["MON_BUS_V_WARN_LOW"],
                  "warn": ns["MON_BUS_V_WARN_HIGH"]},
    }

    ns["NODES"] = {ns["LEFT"]: "left", ns["RIGHT"]: "right"}

    # How long a coil command stays valid without being renewed. The horn is
    # commanded from the CAN tick and written by the DIO thread, so the two run
    # at different rates and the command has to survive the gap between them -
    # but only the gap. If the tick stops renewing it, the coil must fall low on
    # its own rather than sound until somebody kills the process, which is the
    # one failure a horn can have that trains operators to ignore it.
    #
    # Five ticks or two scans, whichever is longer, so neither thread's normal
    # jitter can expire a command that is still being renewed.
    ns["HORN_HOLD_S"] = max(5.0 * ns["LOOP_PERIOD_S"],
                            2.0 * ns["DIO_SCAN_PERIOD_S"])

    # How old the last SUCCESSFUL DIO acquisition may be and still count as panel
    # input (selector, Start/Reset, pendant). silent_warn_s (2 s) is the diagnostic
    # "the module has gone quiet" age; a pendant FWD held in a 2 s old image is not a
    # hand on the pendant now (audit R01, 2026-10-02). Four scans, at least 0.2 s.
    ns["PANEL_SOURCE_MAX_AGE_S"] = max(4.0 * ns["DIO_SCAN_PERIOD_S"], 0.2)
    return ns


def _validate(ns):
    def check(cond, msg):
        if not cond:
            raise ConfigError(msg)

    g = ns.__getitem__

    # -- geometry ---------------------------------------------------------
    check(g("TRACK_M") > 0, "vehicle.track_m must be > 0")
    check(g("WHEEL_DIA_M") > 0, "vehicle.wheel_dia_m must be > 0")
    check(g("GEAR_RATIO") > 0, "vehicle.gear_ratio must be > 0")
    check(g("MOTOR_MAX_RPM") > 0, "vehicle.motor_max_rpm must be > 0")
    check(g("SENSOR_LOOKAHEAD_M") > 0, "vehicle.sensor_lookahead_m must be > 0")


    # -- drivers ----------------------------------------------------------
    for mode, block in g("RAMP").items():
        check(block["accel"] > 0 and block["decel"] > 0,
              f"drivers.ramp.{mode} accel and decel must be > 0")

    # -- line sensor (mls-marker-plan) -----------------------------------
    check(0 <= g("MLS_VARIANT") <= 7, f"mls.variant is 2006h:01, 0..7, got {g('MLS_VARIANT')}")
    check(g("MLS_EVENT_CLEAR") in (-1, 0, 1),
          f"mls.event_clear is the 2080h:01 reset value 0 or 1, or -1 = off; got {g('MLS_EVENT_CLEAR')}")

    # -- tape localization (tracked plan 3) -------------------------------
    for key, lo, hi in (("k_odo", 0.0, 0.1), ("amcl_sigma_floor_m", 0.0, 0.2), ("max_lateral_m", 0.0, 0.5),
                        ("innov_min_m", 0.0, 1.0), ("pose_max_age_s", 0.0, 2.0),
                        ("sigma_station_m", 0.0, 0.05), ("healthy_window_m", 0.0, 20.0),
                        ("lost_fault_s", 0.0, 300.0)):
        v = g(f"TAPE_LOC_{key.upper()}")
        check(lo < v <= hi, f"tape_loc.{key} must be in ({lo:g}, {hi:g}], got {v:g}"
              + (" - 2 sigma has to fit the operator's +-10 cm with the stop's own error"
                 if key == "sigma_station_m" else ""))
    check(g("TAPE_LOC_SIGMA_STATION_M") < g("TAPE_LOC_SIGMA_JUNCTION_M") <= 0.5,
          "tape_loc.sigma_junction_m must be above sigma_station_m and at most 0.5")
    check(g("TAPE_LOC_SIGMA_JUNCTION_M") < g("TAPE_LOC_SIGMA_LOST_M") <= 2.0,
          "tape_loc.sigma_lost_m must be above sigma_junction_m and at most 2.0")
    check(0.5 <= g("TAPE_LOC_JUNCTION_LEAD_M") <= 5.0, "tape_loc.junction_lead_m must be in [0.5, 5]")
    check(2 <= g("TAPE_LOC_LOST_REJECTS") <= 50, "tape_loc.lost_rejects must be in 2..50")
    check(0.05 <= g("TAPE_LOC_MONITOR_JUMP_M") <= 1.0, "tape_loc.monitor_jump_m must be in [0.05, 1] m")
    for key in ("SITE_MISSION", "SHADOW_CIRCUIT"):
        v = g(f"TAPE_LOC_{key}")
        check(bool(re.fullmatch(r"[A-Za-z0-9_-]+", v)),
              f"tape_loc.{key.lower()} must be a plain name, got {v!r}")
    check(g("TAPE_LOC_AMCL_PARAMS") in ("default", "lean"),
          f"tape_loc.amcl_params must be default or lean, got {g('TAPE_LOC_AMCL_PARAMS')!r}")
    check(not (g("TAPE_LOC_ENABLED") and g("TRACKED") is False),
          "tape_loc.enabled on a trackless profile (tracked: false): there is no LINE layer to run it in")
    check(not (g("TAPE_LOC_LIVE") and not g("TAPE_LOC_ENABLED")),
          "tape_loc.live needs tape_loc.enabled: the position engine drives from the tape locator")

    # -- bus and timing ---------------------------------------------------
    check(g("CAN_BITRATE") > 0, "can.bitrate must be > 0")
    check(bool(g("CAN_CHANNEL")), "can.channel must be a SocketCAN interface "
                                  "name such as \"can0\"")
    ids = [g("LEFT"), g("RIGHT"), g("SENSOR_NODE")]
    check(all(1 <= n <= 127 for n in ids),
          "CAN node IDs must be in 1..127")
    check(len(set(ids)) == 3,
          f"CAN node IDs must be distinct, got left={ids[0]} right={ids[1]} "
          f"sensor={ids[2]}")
    check(g("LOOP_PERIOD_S") > 0, "timing.loop_period_s must be > 0")
    check(g("DRIVER_TIMEOUT_S") > 0, "timing.driver_timeout_s must be > 0")

    # -- freshness (WP-A10) -------------------------------------------------
    for key, name, ceiling in (("cmd_s", "FRESH_CMD_S", 0.2), ("lease_s", "FRESH_LEASE_S", 0.3),
                               ("permit_s", "FRESH_PERMIT_S", 0.3)):
        check(0.0 < g(name) <= ceiling,
              f"freshness.{key} ({g(name)}) must be in (0, {ceiling}] s: a hard ceiling")
    for key, name in (("panel_s", "FRESH_PANEL_S"), ("drives_s", "FRESH_DRIVES_S"),
                      ("field_s", "FRESH_FIELD_S")):
        check(g(name) > 0.0, f"freshness.{key} must be > 0")
    for consumer, gate in (("line_panel_s", "panel_s"), ("line_lease_s", "lease_s"),
                           ("line_drives_s", "drives_s"), ("executor_panel_s", "panel_s"),
                           ("executor_drives_s", "drives_s")):
        c = g(_SCHEMA["freshness"][consumer][0])
        k = g(_SCHEMA["freshness"][gate][0])
        check(c >= k, f"freshness.{consumer} ({c}) must be at or above the gate's freshness.{gate} ({k})")
    check(g("PC_LOSS_MS") > 0,
          "freshness.pc_loss_ms must be > 0: with 0 the drives have no response to losing this PC")
    check(0 < g("PC_HEARTBEAT_MS") < g("PC_LOSS_MS") / 2.0,
          f"freshness.pc_heartbeat_ms ({g('PC_HEARTBEAT_MS')}) must be under half pc_loss_ms "
          f"({g('PC_LOSS_MS')}), or one late heartbeat trips the drives")
    check(g("DRIVE_FEEDBACK_HZ") > 0.0, "freshness.feedback_hz must be > 0")
    if g("DRIVE_FEEDBACK_HZ") > 0.0:
        check(g("DRIVER_TIMEOUT_S") >= 3.0 / g("DRIVE_FEEDBACK_HZ"),
              f"timing.driver_timeout_s ({g('DRIVER_TIMEOUT_S')} s) must cover at least three TPDO "
              f"periods at freshness.feedback_hz ({g('DRIVE_FEEDBACK_HZ')})")

    # -- drive monitoring --------------------------------------------------
    # Heartbeat is what makes a dead driver distinguishable from an idle one,
    # so it has to arrive comfortably inside the window that declares the
    # driver silent, or the health monitor trips on ordinary jitter.
    check(g("CAN_HEARTBEAT_MS") >= 0, "can.heartbeat_ms must be >= 0")
    check(g("CAN_HEARTBEAT_MS") == 0
          or g("CAN_HEARTBEAT_MS") / 1000.0 < g("DRIVER_TIMEOUT_S") / 2.0,
          f"can.heartbeat_ms ({g('CAN_HEARTBEAT_MS')}) must be under half "
          f"timing.driver_timeout_s ({g('DRIVER_TIMEOUT_S')} s), or a single "
          f"missed heartbeat reads as a dead driver")
    check(g("MON_DRV_WARN_C") < g("MON_DRV_TRIP_C"),
          "monitor.driver_temp_warn_c must be below driver_temp_trip_c")
    check(g("MON_MTR_WARN_C") < g("MON_MTR_TRIP_C"),
          "monitor.motor_temp_warn_c must be below motor_temp_trip_c")
    check(g("MON_BUS_V_WARN_LOW") < g("MON_BUS_V_WARN_HIGH"),
          f"monitor.bus_v_warn_low ({g('MON_BUS_V_WARN_LOW')}) must be below "
          f"bus_v_warn_high ({g('MON_BUS_V_WARN_HIGH')})")

    # -- dio --------------------------------------------------------------
    check(1 <= g("DIO_PORT") <= 65535, "dio.port must be in 1..65535")
    check(0 <= g("DIO_DEVICE_ID") <= 255, "dio.device_id must be in 0..255")
    # num_di/num_do ranges are checked in _parse(), before the name lists are
    # sized against them.
    check(g("DIO_DI_BASE") >= 0, "dio.di_base must be >= 0")
    check(g("DIO_DO_BASE") >= 0, "dio.do_base must be >= 0")
    check(g("DIO_SCAN_PERIOD_S") > 0, "dio.scan_period_s must be > 0")
    check(g("DIO_TIMEOUT_S") > 0, "dio.timeout_s must be > 0")
    check(g("DIO_RECONNECT_PERIOD_S") > 0, "dio.reconnect_period_s must be > 0")
    # A scan cannot outlast its own period, or the loop falls permanently
    # behind and every snapshot is older than it looks.
    check(g("DIO_TIMEOUT_S") < g("DIO_SCAN_PERIOD_S"),
          f"dio.timeout_s ({g('DIO_TIMEOUT_S')}) must be below scan_period_s "
          f"({g('DIO_SCAN_PERIOD_S')}) - two reads must fit inside one scan")
    # Otherwise a single late scan reads as a fault and the module flaps.
    check(g("DIO_SILENT_WARN_S") > g("DIO_SCAN_PERIOD_S"),
          f"dio.silent_warn_s ({g('DIO_SILENT_WARN_S')}) must exceed "
          f"scan_period_s ({g('DIO_SCAN_PERIOD_S')})")
    # The retry wait has to fit inside the health window, or a single transient
    # error is enough to declare the module dead - the reconnect sleep alone
    # would age the last good scan past silent_warn_s and stop auto.
    check(g("DIO_RECONNECT_PERIOD_S") < g("DIO_SILENT_WARN_S"),
          f"dio.reconnect_period_s ({g('DIO_RECONNECT_PERIOD_S')}) must be "
          f"below silent_warn_s ({g('DIO_SILENT_WARN_S')}) - otherwise one "
          f"retry always trips the health timeout")

    # -- lidar ------------------------------------------------------------
    check(1 <= g("LIDAR_PORT") <= 65535, "lidar.port must be in 1..65535")
    check(g("LIDAR_REASSEMBLY_TIMEOUT_S") > 0,
          "lidar.reassembly_timeout_s must be > 0")
    check(0 <= g("LIDAR_ZONE_BLOCK") < 7,
          f"lidar.zone_block ({g('LIDAR_ZONE_BLOCK')}) must be a block slot 0..6")
    check(g("LIDAR_HOST_IP") != g("LIDAR_SENSOR_IP"),
          "lidar.host_ip and lidar.sensor_ip must differ - host_ip is the "
          "address we bind, sensor_ip is the scanner we accept datagrams from")

    # -- panel ------------------------------------------------------------
    chans = {"di_reset": g("PANEL_DI_RESET"), "di_start": g("PANEL_DI_START"),
             "di_auto": g("PANEL_DI_AUTO"), "di_manual_arm": g("PANEL_DI_MANUAL_ARM")}
    for key, ch in chans.items():
        check(0 <= ch < g("DIO_NUM_DI"),
              f"panel.{key} ({ch}) must be a channel in 0..{g('DIO_NUM_DI') - 1}")
    # Two functions on one channel is a wiring or config error that would
    # otherwise present as phantom presses - a Reset edge every time Start is
    # pushed - which is a miserable thing to debug from the vehicle.
    check(len(set(chans.values())) == 4,
          f"panel channels must be distinct, got {chans}")
    if g("PENDANT_ENABLED"):
        jog = {g("PENDANT_DI_FWD"), g("PENDANT_DI_RVS"), g("PENDANT_DI_LEFT"), g("PENDANT_DI_RIGHT")}
        check(g("PANEL_DI_MANUAL_ARM") not in jog,
              f"panel.di_manual_arm ({g('PANEL_DI_MANUAL_ARM')}) is a pendant channel: "
              "every jog press would also power the drives")
    check(g("PANEL_DEBOUNCE_SCANS") >= 1, "panel.debounce_scans must be >= 1")
    # A selector change and a pendant press landing in the SAME scan is not a hand: on
    # 2026-09-17 the DIO image showed MANUAL+FWD for 1.02 s mid-route with nobody at the
    # box. Such a coincidence is held back this long before it is believed (0 disables).
    check(0.0 <= g("PANEL_COINCIDENCE_HOLD_S") <= 5.0,
          "panel.coincidence_hold_s must be in 0..5 s")
    # The panel is read out of the DI image; without the scan there is nothing
    # to read, and the buttons would be silently dead.
    check(not g("PANEL_ENABLED") or g("DIO_ENABLED"),
          "panel.enabled is true while dio.enabled is false - the panel is read "
          "from the DI image, so the buttons would never respond")

    # -- motion outputs ----------------------------------------------------
    check(not (g("HORN_ENABLED") and g("HORN_DO_CHANNEL") in g("DIO_MOTION_ON") + g("DIO_ALARM_ON")),
          f"dio.motion_on/alarm_on include the horn's channel {g('HORN_DO_CHANNEL')}: one coil, two owners")
    check(set(g("DIO_MOVEMENT_HORN")) <= set(g("DIO_MOTION_ON")),
          "dio.movement_horn must be among dio.motion_on (it is a motion output that yields to the alarm)")
    check(not set(g("DIO_MOTION_ON")) & set(g("DIO_ALARM_ON")),
          "dio.motion_on and dio.alarm_on share a channel: one coil, two owners")

    # -- horn -------------------------------------------------------------
    check(0 <= g("HORN_DO_CHANNEL") < g("DIO_NUM_DO"),
          f"horn.do_channel ({g('HORN_DO_CHANNEL')}) must be a channel in "
          f"0..{g('DIO_NUM_DO') - 1}")
    # Same reasoning as panel.enabled above: the coil is written by the DIO
    # scan, so without it the horn is silently dead rather than merely off.
    check(not g("HORN_ENABLED") or g("DIO_ENABLED"),
          "horn.enabled is true while dio.enabled is false - the coil is "
          "written by the DIO scan, so the horn would never sound")

    # -- pendant ----------------------------------------------------------
    pchans = {k: g(f"PENDANT_DI_{k.upper()}") for k in ("fwd", "rvs", "left", "right")}
    for key, ch in pchans.items():
        check(0 <= ch < g("DIO_NUM_DI"),
              f"pendant.di_{key} ({ch}) must be a channel in 0..{g('DIO_NUM_DI') - 1}")
    check(len(set(pchans.values())) == 4,
          f"pendant channels must be distinct, got {pchans}")
    # A pendant button on a panel channel would drive the vehicle while also
    # pressing Start/Reset or flipping the selector.
    shared = set(pchans.values()) & set(chans.values())
    check(not shared,
          f"pendant channels {sorted(shared)} collide with panel channels {chans}")
    check(not g("PENDANT_ENABLED") or g("DIO_ENABLED"),
          "pendant.enabled is true while dio.enabled is false - the pendant is "
          "read from the DI image, so its buttons would never respond")

    check(0 < g("RFID_TAG_CLEAR_S") <= 5, "rfid.tag_clear_s must be in (0, 5] seconds")

    # -- tracked AUTO speeds (2026-10-08): NORMAL = auto_rpm (0.50 m/s), HIGH = NORMAL x
    # auto_high_ratio (1.7 -> 0.85 m/s) inside an MLS marker zone only. Raising either is a
    # speed-cap change: README status table, and the operator's explicit say-so.
    check(0 < g("AUTO_RPM") <= g("MOTOR_MAX_RPM"),
          "autopilot: need 0 < auto_rpm <= vehicle.motor_max_rpm")
    check(1 < g("AUTO_HIGH_RATIO") <= 2,
          "autopilot.auto_high_ratio must be in (1, 2]: HIGH is that multiple of auto_rpm")
    check(g("AUTO_RPM") * g("AUTO_HIGH_RATIO") <= g("MOTOR_MAX_RPM"),
          "autopilot: auto_rpm x auto_high_ratio must not exceed vehicle.motor_max_rpm")
    check(g("HIGH_K_RATIO") > 0 and g("HIGH_KD") >= 0,
          "autopilot: need high_k_ratio > 0 and high_kd >= 0")
    check(0.5 <= g("HIGH_RAMP_S") <= 10, "autopilot.high_ramp_s must be in [0.5, 10] s")
    check(0 < g("CURVE_GUARD_KAPPA") <= 2,
          "autopilot.curve_guard_kappa must be in (0, 2] 1/m")
    check(0 < g("CURVE_GUARD_E_MM") < g("SENSOR_MAX_MM"),
          "autopilot.curve_guard_e_mm must be in (0, sensor_max_mm)")
    check(0 < g("U_TURN_MIN_DEG") < g("U_TURN_MAX_DEG") <= 270,
          "autopilot: need 0 < u_turn_min_deg < u_turn_max_deg <= 270")
    check(g("U_TURN_GYRO_MIN_DEG") == 0 or 120 <= g("U_TURN_GYRO_MIN_DEG") <= 180,
          "autopilot.u_turn_gyro_min_deg must be 0 (off) or in [120, 180] deg")
    check(0 < g("KINK_EDGE_MM") < g("SENSOR_MAX_MM"),
          "autopilot.kink_edge_mm must be in (0, sensor_max_mm)")
    check(g("KINK_MAX_DEG") == 0 or 20 <= g("KINK_MAX_DEG") <= 120,
          "autopilot.kink_max_deg must be 0 (off) or in [20, 120] deg")
    check(g("U_TURN_CENTER_TOL_MM") <= g("KINK_STOP_MM") < g("SENSOR_MAX_MM"),
          "autopilot.kink_stop_mm must be in [u_turn_center_tol_mm, sensor_max_mm)")

    # -- blind run --------------------------------------------------------
    check(0 < g("BLIND_MAX_DISTANCE_M") <= 50,
          "blind_run.max_distance_m must be in (0, 50] m")
    check(0 < g("BLIND_MAX_RPM") <= g("MOTOR_MAX_RPM"),
          "blind_run.max_rpm must be in (0, motor_max_rpm]")
    check(0 < g("BLIND_ACCEL_RPM_S") <= g("RAMP")["auto"]["accel"],
          "blind_run.accel_rpm_s must be > 0 and within the drive ramp "
          "(drivers.ramp.auto.accel), or the drive lags the plan")
    check(g("BLIND_SETTLE_S") >= 0, "blind_run.settle_s must be >= 0")
    check(0 < g("BLIND_STOP_TOLERANCE_MM") <= 50,
          "blind_run.stop_tolerance_mm must be in (0, 50] mm")
    check(g("BLIND_SYNC_KP") >= 0, "blind_run.sync_kp must be >= 0")
    check(0 <= g("BLIND_OVERRUN_MARGIN") <= 0.5,
          "blind_run.overrun_margin must be a fraction in [0, 0.5]")
    check(1 <= g("BLIND_MAX_SEGMENTS") <= 32,
          "blind_run.max_segments must be in 1..32")
    check(0 < g("BLIND_MAX_SPEED_MPS") <= 0.8,
          "blind_run.max_speed_mps must be in (0, 0.8] m/s")
    check(g("BLIND_MAX_SPEED_MPS") * g("RPM_PER_MPS") <= g("BLIND_MAX_RPM") + 1e-6,
          f"blind_run.max_speed_mps ({g('BLIND_MAX_SPEED_MPS')} m/s) needs more than "
          f"blind_run.max_rpm ({g('BLIND_MAX_RPM'):g} r/min)")

    # -- profile position (locked until someone records the decision) -------
    check(0 < g("PP_MAX_SPEED_MPS") <= g("BLIND_MAX_SPEED_MPS"),
          "pp.max_speed_mps must be in (0, blind_run.max_speed_mps]")
    expect = g("PP_EXPECT")
    for k, v in expect.items():
        check(v is None or v >= 0, f"pp.expect.{k} must be >= 0 or null")
    if g("PP_ENABLED"):
        unset = sorted(k for k, v in expect.items() if v is None)
        check(not unset, f"pp.enabled is true but pp.expect has null value(s) {unset}")
        check(g("PP_VENDOR_REF").strip() != "",
              "pp.enabled is true but pp.vendor_ref is empty - record who "
              "authorised pp on this 400 W geared motor, when, and on what basis")
    check(g("AUTO_START_DELAY_S") >= 0,
          "timing.auto_start_delay_s must be >= 0")
    check(g("AUTO_START_DELAY_S") <= 10.0,
          f"timing.auto_start_delay_s ({g('AUTO_START_DELAY_S')} s) is a long "
          f"time to stand still after a button press - an operator will press "
          f"it again")
    check(g("AUTO_START_DELAY_S") < g("PREMOVE_TIMEOUT_S") <= 30.0,
          f"timing.premove_timeout_s ({g('PREMOVE_TIMEOUT_S')} s) must exceed "
          f"auto_start_delay_s ({g('AUTO_START_DELAY_S')} s) and be at most 30 s")

    # -- rfid -------------------------------------------------------------
    check(1 <= g("RFID_PORT") <= 65535, "rfid.port must be in 1..65535")
    # The tag id is the LAST tag_len bytes of the EPC; an EPC is at most 12 bytes
    # here (96-bit), and our tags carry 4.
    check(1 <= g("RFID_TAG_LEN") <= 12, "rfid.tag_len must be in 1..12 bytes")
    for t in g("RFID_IGNORE_TAGS"):
        try:
            bytes.fromhex(t)
        except ValueError:
            check(False, f"rfid.ignore_tags: {t!r} is not hex")
        check(len(t) == 2 * g("RFID_TAG_LEN"),
              f"rfid.ignore_tags: {t!r} must be {2 * g('RFID_TAG_LEN')} hex "
              f"chars to match tag_len")
    check(g("RFID_RECV_TIMEOUT_S") > 0, "rfid.recv_timeout_s must be > 0")
    check(g("RFID_HEARTBEAT_S") >= 0, "rfid.heartbeat_s must be >= 0 (0 = off)")
    # The timeout has to cover at least one period, or a healthy reader answering
    # on time is dropped as dead.
    check(g("RFID_HEARTBEAT_TIMEOUT_S") > g("RFID_HEARTBEAT_S"),
          "rfid.heartbeat_timeout_s must exceed heartbeat_s")
    check(g("RFID_EXPECT_WORK_MODE") in (0, 1, 2),
          "rfid.expect_work_mode must be 0 (answer), 1 (active) or 2 (trigger)")
    check(0 <= g("RFID_EXPECT_REGION") <= 8, "rfid.expect_region must be in 0..8")
    check(0 <= g("RFID_EXPECT_POWER_DBM") <= 30, "rfid.expect_power_dbm must be in 0..30 dBm")
    check(g("RFID_SILENT_WARN_S") > g("RFID_RECV_TIMEOUT_S"),
          "rfid.silent_warn_s must exceed recv_timeout_s")
    check(g("RFID_RECONNECT_PERIOD_S") > 0,
          "rfid.reconnect_period_s must be > 0")
    check(g("RFID_TAG_HOLD_S") > 0, "rfid.tag_hold_s must be > 0")
    return ns


def _json_constant(name):
    """json.load's hook for the non-standard NaN / Infinity / -Infinity tokens.

    Python accepts them silently by default. They are passed through as the
    float they spell rather than refused here, because only _coerce knows which
    field it is reading: every value goes through it, and it refuses nonfinite
    numbers with the field named - "timing.driver_timeout_s: expected a finite
    number" sends the reader to the line, "Infinity is invalid" does not."""
    return float(name)


def _check_finite(ns):
    """Every published float, primitive or derived, must be finite. Finite
    inputs can still overflow in _derive (a huge wheel diameter), and a NaN
    compares False against every bound, so this runs before _validate."""
    for name, value in ns.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ConfigError(f"{name} is not finite ({value!r}) - check the "
                              "profile values it is derived from")
    return ns


def load(path=None):
    """Parse, derive, validate, then publish. Nothing is published on failure."""
    path = path or profile_path()
    try:
        with open(path) as fh:
            doc = json.load(fh, parse_constant=_json_constant)
    except FileNotFoundError as e:
        raise ConfigError(
            f"no vehicle profile at {path}. Set {PROFILE_ENV_VAR} to one of "
            f"{_available() or ['(none found)']}, or add the file.") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"{os.path.basename(path)} is not valid JSON: {e}") from e

    # The name inside the file has to agree with the file it came from. A
    # profile copied for a second vehicle and not renamed would otherwise
    # report the old identity in the event log and in every run CSV header -
    # silent, and only noticed when comparing runs weeks later.
    stem = os.path.splitext(os.path.basename(path))[0]
    ns = _parse(doc)
    if ns["PROFILE_NAME"] != stem:
        raise ConfigError(f"profile_name is {ns['PROFILE_NAME']!r} but the file "
                          f"is {stem}.json - rename one to match the other")

    ns = _validate(_check_finite(_derive(ns)))
    ns["PROFILE_PATH_LOADED"] = path
    globals().update(ns)
    return ns


def _available():
    """Profile names on disk, for the error message. Never raises."""
    try:
        return sorted(f[:-5] for f in os.listdir(PROFILE_DIR)
                      if f.endswith(".json"))
    except OSError:
        return []


# ---------------------------------------------------------------------------
# introspection, for the /params page
# ---------------------------------------------------------------------------
# The page is generated FROM _SCHEMA rather than from a list of its own. A
# hand-written parameters page is a second copy of the schema, and a second copy
# is one that silently stops matching - which on THIS page means a value the
# vehicle is running on that nobody can see. Add a key to a profile and it
# appears; there is nothing to remember.

# Units are read off the exported name's suffix for the same reason: the names
# already carry them, so there is nothing extra to keep in step. Longest first,
# because _MS and _MM would otherwise be eaten by _S and _M.
_UNIT_SUFFIX = (
    ("_RPM_S2", "r/min/s\u00b2"), ("_RPM_S", "r/min/s"), ("_RPM", "r/min"),
    ("_MM", "mm"), ("_MS", "ms"), ("_HZ", "Hz"),
    ("_S", "s"), ("_M", "m"), ("_C", "\u00b0C"),
)
# The ones a suffix cannot know: a bare voltage limit, a bitrate, and the
# derived conversions whose names END in something that reads as a unit but is
# not one (MPS_PER_RPM is metres per second per r/min, not r/min).
_UNIT_EXACT = {
    "CAN_BITRATE": "bit/s",
    "MON_BUS_V_WARN_LOW": "V", "MON_BUS_V_WARN_HIGH": "V",
    "MPS_PER_RPM": "m/s per r/min", "RPM_PER_MPS": "r/min per m/s",
    "RAD_S_PER_RPM_DIFF": "rad/s per r/min diff", "MAX_SPEED_MPS": "m/s",
    "WHEEL_RAD_S_PER_MOTOR_RPM": "wheel rad/s per motor r/min",
}

# Everything _derive() computes, with the relation that produced it - which is
# the whole reason these are shown apart from the profile: they cannot be
# edited, and a page that listed them alongside the tunables would invite
# somebody to try. See _derive() for the arithmetic itself.
_DERIVED = (
    ("MPS_PER_RPM", "\u03c0\u00b7wheel_dia_m / (gear_ratio \u00b7 60)"),
    ("RPM_PER_MPS", "1 / MPS_PER_RPM"),
    ("RAD_S_PER_RPM_DIFF", "MPS_PER_RPM / track_m"),
    ("WHEEL_RAD_S_PER_MOTOR_RPM", "2\u03c0 / (60 \u00b7 gear_ratio)"),
    ("MAX_SPEED_MPS", "motor_max_rpm \u00b7 MPS_PER_RPM"),
    ("AUTO_HIGH_RPM", "autopilot.auto_rpm \u00b7 auto_high_ratio - the tracked HIGH speed"),
    ("ACCEL_RPM_S", "drivers.ramp.auto.accel"),
    ("DECEL_RPM_S", "drivers.ramp.auto.decel"),
    ("HORN_HOLD_S", "max(5 \u00b7 loop_period_s, 2 \u00b7 dio.scan_period_s) - "
                    "how long a coil claim outlives its last renewal"),
)

# A tuning note heads a paragraph and starts at column 0 as section.key.
_NOTE_HEAD = re.compile(r"^[a-z_]+\.[a-z_0-9*]")


def _unit(const):
    if const in _UNIT_EXACT:
        return _UNIT_EXACT[const]
    for suffix, unit in _UNIT_SUFFIX:
        if const.endswith(suffix):
            return unit
    return ""


def _fmt(value):
    """A value as it should read on screen. Never returns an empty string - a
    blank cell reads as "not set" when the setting is genuinely an empty
    string or list, and those two mean different things."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.10g}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt(v) for v in value) if value else "(empty list)"
    return value if value else "(empty)"


_LOADED = object()


def product(tracked=_LOADED):
    """The profile's `tracked` as a product: True "tape", False "slam", null "both".
    Without an argument, the loaded profile's."""
    t = globals().get("TRACKED") if tracked is _LOADED else tracked
    return {True: "tape", False: "slam"}.get(t, "both")


def tuning_notes():
    """section.key -> the paragraph about it in this module's docstring.

    PARSED, not restated. The reasoning behind every setting that is not
    self-evident is already written down at the top of this file, and it is
    written there because JSON cannot carry comments. Copying it into a
    template would produce two versions of the same explanation, one of which
    would go stale - and the stale one would be the one on the screen.

    A heading is a column-0 `section.key`, optionally naming several keys
    separated by "/" and optionally `section.*` for a whole section. Anything
    that does not parse simply yields no note, so the page degrades to a plain
    table rather than failing.
    """
    doc = __doc__ or ""
    at = doc.find("TUNING NOTES")
    if at < 0:
        return {}

    out = {}
    heading = None
    body = []

    def flush():
        if not heading:
            return
        text = textwrap.dedent("\n".join(body)).strip()
        if not text:
            return
        section = heading[0].split(".")[0]
        for token in heading:
            out[token if "." in token else f"{section}.{token}"] = text

    for line in doc[at:].splitlines():
        if line and not line[0].isspace():
            if not _NOTE_HEAD.match(line):
                continue                      # prose between the notes
            flush()
            heading = [t.strip() for t in line.split("(")[0].split("/")]
            body = []
        elif heading is not None:
            body.append(line)
    flush()
    return out


# The drive ramps, shown FIRST as the "speed" section and nowhere else (one
# parameter in two places reads as two parameters). Display only: the rows carry
# their full dotted path, because this page's other audience is somebody about to
# edit the profile. (section, key) pairs, in the order they should read.
_SPEED_ROWS = [
    ("drivers", "ramp.auto.accel"),
    ("drivers", "ramp.auto.decel"),
]

# Section order on the page. Speed first, then the geometry it runs on;
# everything after is in schema order. Named here rather
# than by reordering _SCHEMA, because _SCHEMA's order is the profile's order and
# those are two different jobs.
_SECTION_ORDER = ["vehicle"]



def _row(section, key, const, value, notes, text=None, unit=None):
    """One displayed parameter. `key` is what to edit in the JSON, `const` is
    what the code calls it - both, because the two audiences for this page are
    somebody editing a profile and somebody reading a traceback."""
    # A note may be attached to the nested key it heads (drivers.ramp covers
    # ramp.auto.accel), so fall back to the first segment before giving up.
    note = (notes.get(f"{section}.{key}")
            or notes.get(f"{section}.{key.split('.')[0]}")
            or notes.get(f"{section}.*"))
    return {"key": key, "const": const,
            "value": _fmt(value) if text is None else text,
            "unit": _unit(const) if unit is None else unit, "note": note}


def describe():
    """The loaded profile as ordered sections of displayable rows.

    Read-only by construction: this returns text, and there is no counterpart
    that writes. A profile is changed by editing the JSON and restarting the
    service, which is what makes the value on the screen the value the bus
    thread is actually using.
    """
    g = globals()
    notes = tuning_notes()
    out = []

    def ramp_row(section, key):
        """A drivers.ramp.<mode>.<accel|decel> row. Nested, so _SCHEMA's flat
        table cannot express it and both call sites build it here."""
        _, mode, k = key.split(".")
        return _row(section, key, f'RAMP["{mode}"]["{k}"]',
                    g["RAMP"][mode][k], notes, unit="r/min/s")

    def build(section, key):
        if key.startswith("ramp."):
            return ramp_row(section, key)
        const, _want = _SCHEMA[section][key]
        return _row(section, key, const, g.get(const), notes)

    # Speed first. Gathered from three sections, so each row is labelled with
    # the path it actually lives at - see _SPEED_ROWS.
    speed = []
    for section, key in _SPEED_ROWS:
        row = build(section, key)
        row["key"] = f"{section}.{key}"
        speed.append(row)
    out.append({
        "name": "speed", "rows": speed,
        "note": "The drive ramps, 6083h/6084h (drivers.ramp.auto in the JSON), "
                "written to the drives at arm time for AUTO. The accel also sets "
                "the ceiling on yaw acceleration - see kinematics.max_yaw_accel()."})

    # Then the schema's own sections: the named ones in the order above, then
    # whatever is left in the order the profile writes it.
    ordered = _SECTION_ORDER + [s for s in _SCHEMA if s not in _SECTION_ORDER]
    for section in ordered:
        fields = _SCHEMA[section]
        rows = [_row(section, key, const, g.get(const), notes)
                for key, (const, _want) in fields.items()]

        # What _SCHEMA's flat table cannot express (the ramps are in "speed").
        if section == "dio":
            for key, const in (("di_names", "DIO_DI_NAMES"),
                               ("do_names", "DIO_DO_NAMES")):
                names = g[const]
                named = [f"{i:02d} {n}" for i, n in enumerate(names) if n]
                rows.append(_row(
                    section, key, const, names, notes,
                    text=(f"{len(named)} of {len(names)} named \u00b7 "
                          + " \u00b7 ".join(named)) if named
                         else f"none of {len(names)} named",
                    unit=""))
            on = g["DIO_MOTION_ON"]
            rows.append(_row(section, "motion_on", "DIO_MOTION_ON", on, notes,
                             text=(" \u00b7 ".join(f"DO{c:02d}" for c in on) + " on while the motors turn") if on else "none",
                             unit=""))
            al = g["DIO_ALARM_ON"]
            rows.append(_row(section, "alarm_on", "DIO_ALARM_ON", al, notes,
                             text=(" \u00b7 ".join(f"DO{c:02d}" for c in al) + " on in an AUTO run with a field occupied") if al else "none",
                             unit=""))
            mh = g["DIO_MOVEMENT_HORN"]
            rows.append(_row(section, "movement_horn", "DIO_MOVEMENT_HORN", mh, notes,
                             text=(" \u00b7 ".join(f"DO{c:02d}" for c in mh) + " off while the alarm horn sounds") if mh else "none",
                             unit=""))
        if section == "mls":
            rows.append(_row(section, "marker_codes", "MLS_MARKER_CODES",
                             g["MLS_MARKER_CODES"], notes,
                             text=", ".join(str(c) for c in g["MLS_MARKER_CODES"]),
                             unit="code"))
        if section == "lidar":
            rows.append(_row(section, "zone_bytes", "LIDAR_ZONE_BYTES",
                             g["LIDAR_ZONE_BYTES"], notes,
                             text="stop {}, slow {}, warn {}".format(
                                 *g["LIDAR_ZONE_BYTES"]),
                             unit="byte offset"))
        # A section whose every key was gathered into `speed` above has nothing
        # left to show - `manual` is exactly that - and a bare heading over
        # nothing reads as a section that failed to load.
        if rows:
            out.append({"name": section, "note": notes.get(f"{section}.*"),
                        "rows": rows})

    # `from` rather than a note: the relation is the point of the row, so it is
    # always on screen, and there is no JSON key to edit because there is no
    # JSON key at all.
    out.append({"name": "derived", "note": None, "rows": [
        {"key": const, "const": "", "from": why,
         "value": _fmt(g[const]),
         "unit": _unit(const), "note": None}
        for const, why in _DERIVED]})
    return out


load()
