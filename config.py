"""The vehicle profile. Every tunable parameter in the system lives here.

Reads agv-profile.json and publishes it as flat module-level constants, so call
sites read `config.K_RATIO` rather than digging through nested dicts. Everything
else imports this; this imports nothing but the standard library, which is what
keeps the dependency graph acyclic.

Three rules the loader enforces, in order of how much trouble they save:

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

load() is written as an atomic swap - parse and validate into a fresh namespace,
publish only on success - so nothing observes a half-applied profile. Only
called once today; a reload endpoint would be a caller, not a rewrite.


TUNING NOTES
============
JSON cannot carry comments, so the reasoning behind the settings that are not
self-evident lives here. Read this before editing agv-profile.json.

autopilot.dry_run
    *** Set false only after the sign has been confirmed by a dry run. ***
    Runs the whole loop and writes the CSV, but canworker never arms the drivers
    and sends 0 to 60FFh, so nothing can move. Check the sign by sliding a magnet
    under a STATIONARY AGV - not by pushing the AGV, which is not possible: the
    CiA 402 "Operation enabled" state excites the motor (opman_can:1391) and the
    velocity loop then holds zero, and a non-excited brake motor has the brake
    clamped instead (opman_fun:2021). Only the FREE input frees the shaft.
    A wrong sign steers the AGV off the line and accelerates away from it.

autopilot.invert_error
    True if a positive reported track position means the line is to the LEFT.
    Not derivable from the manual - established on the machine by dry run on
    2026-08-31 (logs/auto_20260831_092454.csv and _092528.csv):
        tape to the RIGHT of the sensor -> reported -53 mm
        tape to the LEFT  of the sensor -> reported +20 mm
    so positive does mean LEFT, and the raw reading has to be negated.

autopilot.k_ratio / kd / ki
    Steering gains. k_ratio is in 1/m^2 (Kp = k_ratio*v has units rad/s per m).
    Commission at the KIM2A-proven point first as a model check, then move up:
        k_ratio 11.3, kd 0.94 -> zeta 0.30, ~12.6 mm overshoot, ~7 s settle
        k_ratio 25.0, kd 5.0  -> zeta 0.61, ~2.6 mm overshoot, ~1.2 s settle
    ki starts at 0; add it only to null a standing offset.

autopilot.tau_d_s
    Derivative low-pass. The sensor quantises to 1 mm, so a raw derivative sees
    100 mm/s steps on every bit flip. KIM2A pairs a light kd with a 13 ms filter;
    the 25/5 point above needs the heavier 50 ms.

autopilot.ti_deadband_mm / i_clamp
    Conditional integration (KIM2A section 2.1): integrate only while the error
    is SMALL, freeze outside. This is anti-windup, not a conventional deadband -
    large excursions must contribute nothing. Do not invert this.

autopilot.sr_pos_frac / sr_rate_frac
    Speed reduction - draft section 5 error_cons. Responds to error magnitude AND
    rate, so it slows on approach to a curve rather than after deviating.

    These are FRACTIONS OF BASE SPEED per mm (and per mm/s), not absolute r/min.
    They used to be absolute, and that was a bug: when cruise went 800 -> 2000 the
    authority silently fell from 15% of base to 6% because nobody rescaled them.
    Anything that must stay proportional to speed has to be *expressed* relative
    to speed, or it will be missed at the next speed change. 0.0075 per mm means
    a 20 mm error always sheds 15% of whatever the base currently is.

autopilot.sr_cap / sr_tau_s
    Ceiling on the reduction, as a fraction of base, and the lag on the reduction
    itself. sr_tau_s is a TIME, not a per-tick coefficient: KIM2A uses a fixed
    alpha of 0.15, which quietly makes the filter faster or slower with the tick
    rate; since dt here is measured and only clamped to a band, a time constant
    is the honest form. 0.12 s == alpha 0.15 at 50 Hz.

autopilot.line_loss_grace_m
    How far the AGV may travel on the last good correction across a tape gap
    before it gives up and stops. A DISTANCE for the same reason the sr_ terms
    are fractions: as seconds it was 0.30, which meant 75 mm of blind travel at
    800 r/min but 188 mm at 2000. Distance is the quantity that actually matters,
    and it rescales itself - it even adapts within a run as the ramp changes
    speed. config derives LINE_LOSS_GRACE_MAX_S from this as a standstill
    backstop, since a stationary AGV accrues no distance.

autopilot.ramp_accel_rpm_s / ramp_jerk_rpm_s2
    The software motion profile, and it must stay meaningfully BELOW the driver's
    6083h (drivers.ramp.auto.accel) or the driver becomes the limiter and the
    S-curve shape is lost. _validate() enforces the ordering.

autopilot.sensor_max_mm / sensor_max_step_mm
    Sensor guards (KIM2A section 7.8). A single glitch frame would otherwise jerk
    the steering hard through the derivative term. Beyond max_mm the frame is
    DISCARDED; a jump bigger than max_step_mm is CLAMPED toward the last accepted.

autopilot.dt_nominal_s
    dt is measured, then clamped to [0.2x, 5x] this, so a scheduling hiccup or a
    resume-after-stop gap cannot blow up the I and D terms.

autopilot.inner_wheel_min_rpm
    Lowest r/min either wheel may be commanded. 0 means the inner wheel may stop
    but never reverses; the differential is limited to respect it rather than the
    wheel being clipped, which would alter the turn ratio. Set negative to permit
    pivoting. KIM2A gets this for free (negative rpm -> 0 V); our 60FFh is signed.

vehicle.invert_left / invert_right
    Both drivers take a POSITIVE 60FFh to travel forward on this AGV. If you swap
    a motor, re-flash a driver or remount a wheel, re-verify on blocks and set
    these rather than editing motion.py's table - the table stays in vehicle terms.

drivers.ramp
    6083h/6084h per mode, written at arm time. The two modes want opposite things
    from the driver:
      manual : a hand-jogged pad. The driver does all the shaping, so it is set
               gentle. Decel stays faster than accel because releasing the button
               is the safety-relevant direction.
      auto   : the software S-curve shapes the motion (autopilot.ramp_accel_rpm_s),
               so the driver is set as transparent as is safe and mostly just
               follows. A STOP deliberately falls through to this decel rate.
    CAUTION: with a 400 W motor on a gearhead the Function Edition warns the motor
    can be damaged by a hard decel while demand and actual velocity differ a lot
    (opman_fun:2951). On that combination drop the auto decel to match its accel
    and set drive_forward.PVCM_NORMAL = 0 to use motion extension instead.
    CAUTION (auto): 6083h also caps how fast the wheel DIFFERENCE can slew, which
    is the real ceiling on steering gain - see the note atop autopilot.py. Raising
    k_ratio without raising this diverges; raising this without re-checking
    traction is a different kind of mistake.

drivers.target_deadband_rpm
    The PID rewrites the setpoint nearly every tick, and each write is a blocking
    SDO round-trip (~1.8 ms x 2 nodes). Only resend when the command has actually
    moved; 5 r/min out of 800 is 0.6% and well inside the driver's own resolution.
    A target of exactly (0, 0) is never deadbanded away.

timing.manual_watchdog_s / auto_watchdog_s
    A held button re-POSTs every ~100 ms. Miss three in a row and the setpoint is
    zeroed - covers a closed tab, a dropped Wi-Fi link and a wedged browser. Auto
    is fed by the telemetry poll rather than a held button, so it gets a looser
    deadline; it still stops if the page goes away.

timing.loop_period_s / telemetry_period_s / field_period_s
    50 Hz control loop; 5 Hz statusword + rpm + error register (6 fast reads);
    2 Hz sensor field level. The telemetry rate is also what sets how coarsely the
    ACTUAL wheel speeds appear in the run plot - the commanded traces are logged
    at the full loop rate, the measured ones only as fast as they are polled.

plot.err_range_mm / rpm_max
    Fixed axis limits for the per-run PNG, so two runs can be compared by eye
    rather than each being scaled to its own data. Traces HARD CLIP at the frame.
    They are profile values rather than code constants deliberately: KIM2A
    hardcoded theirs for one vehicle and the second vehicle's traces compressed
    into an unreadable band, and we would hit the same trap inverted - at the
    sensor's full +/-100 mm a straight-line run of +/-8 mm draws as a flat line.

    err_range_mm 100 matches the MLS range, so a saturated sensor clips flat at
    the frame and every run is directly comparable. That is the right window for
    curve work, where steady-state error is kappa/k_ratio - 59 mm on a 1.5 m
    radius at k_ratio 11.3. The cost is that a clean straight-line run of a few
    mm draws as an almost flat line; drop to ~30 if you are chasing millimetre
    detail on straights and do not need the curve headroom.
    rpm_max wants roughly auto_rpm x 1.25 so the ramp has headroom to read true.

rfid.*  (Chafon CF821, UHF EPC Gen2, TCP 2022)
    enabled ships FALSE. The link layer is commissioned and reboot-safe
    (manuals/rfid-setup), but the wire protocol is NOT yet confirmed on this
    reader, so the driver must not be trusted to produce real tags until it is.

    inventory_cmd / epc_offset / handshake_hex are the UNVERIFIED parts, exposed
    here precisely so they can be corrected from a packet capture without a code
    change. The framing itself (A0 | Len | Addr | Cmd | Data | Checksum, two's
    complement checksum) is the documented Chafon family layout.

    poll_period_s = 0 means DO NOT POLL - the reader is in active mode and
    streams on its own. Any positive value is command mode. The CF821 datasheet
    lists "active mode / command mode / trigger mode", and which one this unit is
    in has not been read yet; both are supported without a code change.

    poll_period_s also sets positional accuracy, not just liveness: at 0.5 m/s a
    100 ms poll means a tag's position is known to about 50 mm.

    comms_timeout_s must exceed both poll_period_s and reply_timeout_s, or the
    normal silence of an empty antenna field reads as a comms fault. _validate()
    enforces that.

rfid.*  (Chafon CF821, UHF EPC Gen2, TCP 2022)
    enabled ships FALSE. The link layer is commissioned and reboot-safe
    (manuals/rfid-setup), but the wire protocol is NOT yet confirmed on this
    reader, so the driver must not be trusted to produce real tags until it is.

    inventory_cmd / epc_offset / handshake_hex are the UNVERIFIED parts, exposed
    here precisely so they can be corrected from a packet capture without a code
    change. The framing itself (A0 | Len | Addr | Cmd | Data | Checksum, two's
    complement checksum) is the documented Chafon family layout.

    poll_period_s = 0 means DO NOT POLL - the reader is in active mode and
    streams on its own. Any positive value is command mode. The CF821 datasheet
    lists "active mode / command mode / trigger mode", and which one this unit is
    in has not been read yet; both are supported without a code change.

    poll_period_s also sets positional accuracy, not just liveness: at 0.5 m/s a
    100 ms poll means a tag's position is known to about 50 mm.

    comms_timeout_s must exceed both poll_period_s and reply_timeout_s, or the
    normal silence of an empty antenna field reads as a comms fault. _validate()
    enforces that.


timing.log_tail_s
    How long to keep logging after a stop. The deceleration is the part worth
    seeing afterwards, and it happens entirely inside the drivers.
"""
import json
import math
import os

PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "agv-profile.json")


class ConfigError(Exception):
    """Raised for a malformed or physically nonsensical profile."""


# section -> json key -> (exported name, type). The exported names match the
# constants these replaced, so the diff at every call site is one word.
_SCHEMA = {
    "vehicle": {
        "track_m":            ("TRACK_M", float),
        "wheel_dia_m":        ("WHEEL_DIA_M", float),
        "gear_ratio":         ("GEAR_RATIO", float),
        "motor_max_rpm":      ("MOTOR_MAX_RPM", float),
        "sensor_lookahead_m": ("SENSOR_LOOKAHEAD_M", float),
        "invert_left":        ("INVERT_LEFT", bool),
        "invert_right":       ("INVERT_RIGHT", bool),
    },
    "autopilot": {
        "dry_run":             ("DRY_RUN", bool),
        "invert_error":        ("INVERT_ERROR", bool),
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
        "ramp_accel_rpm_s":    ("RAMP_ACCEL_RPM_S", float),
        "ramp_jerk_rpm_s2":    ("RAMP_JERK_RPM_S2", float),
        "sensor_max_mm":       ("SENSOR_MAX_MM", float),
        "sensor_max_step_mm":  ("SENSOR_MAX_STEP_MM", float),
        "line_loss_grace_m":   ("LINE_LOSS_GRACE_M", float),
        "sensor_timeout_s":    ("SENSOR_TIMEOUT_S", float),
        "dt_nominal_s":        ("DT_NOMINAL_S", float),
        "inner_wheel_min_rpm": ("INNER_WHEEL_MIN_RPM", float),
    },
    "manual": {
        "full_rpm":   ("MANUAL_FULL_RPM", int),
        "half_ratio": ("MANUAL_HALF_RATIO", float),
    },
    "plot": {
        "err_range_mm": ("PLOT_ERR_RANGE_MM", float),
        "rpm_max":      ("PLOT_RPM_MAX", float),
    },
    "drivers": {
        "target_deadband_rpm": ("TARGET_DEADBAND_RPM", int),
        # "ramp" is a nested dict; handled separately in _read_ramp().
    },
    "rfid": {
        "enabled":            ("RFID_ENABLED", bool),
        "ip":                 ("RFID_IP", str),
        "port":               ("RFID_PORT", int),
        "interface":          ("RFID_INTERFACE", str),
        "init_hex":           ("RFID_INIT_HEX", str),
        "frame_len":          ("RFID_FRAME_LEN", int),
        "tag_offset":         ("RFID_TAG_OFFSET", int),
        "tag_len":            ("RFID_TAG_LEN", int),
        "ignore_tags":        ("RFID_IGNORE_TAGS", list),
        "recv_timeout_s":     ("RFID_RECV_TIMEOUT_S", float),
        "banner_wait_s":      ("RFID_BANNER_WAIT_S", float),
        "silent_warn_s":      ("RFID_SILENT_WARN_S", float),
        "reconnect_period_s": ("RFID_RECONNECT_PERIOD_S", float),
        "tag_hold_s":         ("RFID_TAG_HOLD_S", float),
    },
    "can": {
        "bitrate":     ("CAN_BITRATE", int),
        "left_node":   ("LEFT", int),
        "right_node":  ("RIGHT", int),
        "sensor_node": ("SENSOR_NODE", int),
    },
    "timing": {
        "loop_period_s":      ("LOOP_PERIOD_S", float),
        "telemetry_period_s": ("TELEMETRY_PERIOD_S", float),
        "field_period_s":     ("FIELD_PERIOD_S", float),
        "manual_watchdog_s":  ("MANUAL_WATCHDOG_S", float),
        "auto_watchdog_s":    ("AUTO_WATCHDOG_S", float),
        "log_tail_s":         ("LOG_TAIL_S", float),
    },
}

_TOP_LEVEL_SCALARS = {"profile_name": ("PROFILE_NAME", str)}


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
        return float(value)
    if want is list:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{where}: expected a list of strings, got {value!r}")
        return list(value)
    if want is str:
        if not isinstance(value, str):
            raise ConfigError(f"{where}: expected a string, got {value!r}")
        return value
    raise ConfigError(f"{where}: unsupported schema type {want!r}")


def _read_ramp(raw):
    """drivers.ramp -> {"manual": {...}, "auto": {...}} of ints."""
    ramp = raw.get("ramp")
    if not isinstance(ramp, dict):
        raise ConfigError("drivers.ramp: missing or not an object")
    unknown = set(ramp) - {"manual", "auto"}
    if unknown:
        raise ConfigError(f"drivers.ramp: unknown mode(s) {sorted(unknown)}")
    out = {}
    for mode in ("manual", "auto"):
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
        ns[name] = _coerce(doc[key], want, key)

    for section, fields in _SCHEMA.items():
        block = doc[section]
        if not isinstance(block, dict):
            raise ConfigError(f"{section}: expected an object")
        allowed = set(fields)
        if section == "drivers":
            allowed.add("ramp")
        unknown = set(block) - allowed
        if unknown:
            raise ConfigError(f"{section}: unknown key(s) {sorted(unknown)}")
        missing = allowed - set(block)
        if missing:
            raise ConfigError(f"{section}: missing key(s) {sorted(missing)}")
        for key, (name, want) in fields.items():
            ns[name] = _coerce(block[key], want, f"{section}.{key}")

    ns["RAMP"] = _read_ramp(doc["drivers"])
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
    ns["MAX_SPEED_MPS"] = ns["MOTOR_MAX_RPM"] * ns["MPS_PER_RPM"]  # 1.2566 m/s

    # Inner wheel of a curve, and both wheels of a spin.
    ns["MANUAL_HALF_RPM"] = round(ns["MANUAL_FULL_RPM"] * ns["MANUAL_HALF_RATIO"])

    # A scheduling hiccup or a resume-after-stop gap must not blow up I and D,
    # so the measured dt is clamped to this band.
    ns["DT_MIN_S"] = 0.2 * ns["DT_NOMINAL_S"]
    ns["DT_MAX_S"] = 5.0 * ns["DT_NOMINAL_S"]

    # Line loss is budgeted as a DISTANCE, but a stationary AGV that cannot see
    # tape accrues no distance and would coast forever, so the budget needs a
    # time ceiling too. Five times the nominal grace at cruise: generous enough
    # never to fire during normal travel, finite enough to bound the standstill
    # case. Derived, so it is not one more thing to forget when speed changes.
    ns["LINE_LOSS_GRACE_MAX_S"] = (
        5.0 * ns["LINE_LOSS_GRACE_M"]
        / max(ns["AUTO_RPM"] * ns["MPS_PER_RPM"], 1e-6))

    # The autopilot is tuned against the AUTO ramp specifically: 6083h caps both
    # the forward ramp and the rate at which the wheel DIFFERENCE can slew,
    # which is the binding constraint on steering gain.
    ns["ACCEL_RPM_S"] = ns["RAMP"]["auto"]["accel"]
    ns["DECEL_RPM_S"] = ns["RAMP"]["auto"]["decel"]

    ns["NODES"] = {ns["LEFT"]: "left", ns["RIGHT"]: "right"}
    ns["TPDO1_COB"] = 0x180 + ns["SENSOR_NODE"]
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

    # -- control law ------------------------------------------------------
    check(g("K_RATIO") > 0, "K_RATIO must be > 0")
    check(g("KD") >= 0 and g("KI") >= 0, "KD and KI must be >= 0")
    check(g("TAU_D_S") >= 0, "TAU_D_S must be >= 0")
    check(g("TI_DEADBAND_MM") > 0, "TI_DEADBAND_MM must be > 0")
    check(g("I_CLAMP") > 0, "I_CLAMP must be > 0")
    check(0.0 < g("SR_CAP") < 1.0, "SR_CAP must be a fraction in (0, 1)")
    check(g("SR_TAU_S") >= 0, "SR_TAU_S must be >= 0")
    check(g("SR_POS_FRAC") >= 0 and g("SR_RATE_FRAC") >= 0,
          "SR fractions must be >= 0")
    check(0 < g("AUTO_RPM") <= g("MOTOR_MAX_RPM"),
          f"AUTO_RPM must be in (0, {g('MOTOR_MAX_RPM')}]")
    check(g("RAMP_ACCEL_RPM_S") > 0 and g("RAMP_JERK_RPM_S2") > 0,
          "ramp accel and jerk must be > 0")
    check(g("SENSOR_MAX_MM") > 0 and g("SENSOR_MAX_STEP_MM") > 0,
          "sensor guards must be > 0")
    check(g("LINE_LOSS_GRACE_M") >= 0, "LINE_LOSS_GRACE_M must be >= 0")
    check(g("LINE_LOSS_GRACE_M") <= 0.5,
          f"line_loss_grace_m ({g('LINE_LOSS_GRACE_M')} m) is more than half a "
          f"metre of blind travel - that is a long way to drive on a stale "
          f"correction")
    check(g("PLOT_ERR_RANGE_MM") > 0 and g("PLOT_RPM_MAX") > 0,
          "plot ranges must be > 0")
    check(g("SENSOR_TIMEOUT_S") > 0, "SENSOR_TIMEOUT_S must be > 0")
    check(g("DT_NOMINAL_S") > 0 and g("DT_MIN_S") > 0
          and g("DT_MAX_S") > g("DT_MIN_S"), "dt band is inconsistent")
    check(g("INNER_WHEEL_MIN_RPM") < g("AUTO_RPM"),
          "INNER_WHEEL_MIN_RPM must leave room to steer at AUTO_RPM")

    # -- manual jog -------------------------------------------------------
    check(0 < g("MANUAL_FULL_RPM") <= g("MOTOR_MAX_RPM"),
          f"manual.full_rpm must be in (0, {g('MOTOR_MAX_RPM')}]")
    check(0.0 < g("MANUAL_HALF_RATIO") <= 1.0,
          "manual.half_ratio must be a fraction in (0, 1]")

    # -- drivers ----------------------------------------------------------
    for mode, block in g("RAMP").items():
        check(block["accel"] > 0 and block["decel"] > 0,
              f"drivers.ramp.{mode} accel and decel must be > 0")
    check(g("TARGET_DEADBAND_RPM") >= 0, "target_deadband_rpm must be >= 0")

    # The software S-curve only shapes the motion if it is the slower of the
    # two; at or above 6083h the driver becomes the limiter and the jerk-limited
    # profile is lost. This pairing is the one check neither module could make
    # alone before, which is exactly why it belongs here.
    check(g("RAMP_ACCEL_RPM_S") < g("ACCEL_RPM_S"),
          f"autopilot.ramp_accel_rpm_s ({g('RAMP_ACCEL_RPM_S')}) must stay "
          f"below drivers.ramp.auto.accel ({g('ACCEL_RPM_S')}), or the driver "
          f"becomes the limiter and the software profile has no effect")

    # -- bus and timing ---------------------------------------------------
    check(g("CAN_BITRATE") > 0, "can.bitrate must be > 0")
    ids = [g("LEFT"), g("RIGHT"), g("SENSOR_NODE")]
    check(all(1 <= n <= 127 for n in ids),
          "CAN node IDs must be in 1..127")
    check(len(set(ids)) == 3,
          f"CAN node IDs must be distinct, got left={ids[0]} right={ids[1]} "
          f"sensor={ids[2]}")
    check(g("LOOP_PERIOD_S") > 0, "timing.loop_period_s must be > 0")
    check(g("TELEMETRY_PERIOD_S") >= g("LOOP_PERIOD_S"),
          "timing.telemetry_period_s must be >= loop_period_s")
    check(g("FIELD_PERIOD_S") >= g("LOOP_PERIOD_S"),
          "timing.field_period_s must be >= loop_period_s")
    check(g("MANUAL_WATCHDOG_S") > 0 and g("AUTO_WATCHDOG_S") > 0,
          "watchdog deadlines must be > 0")
    check(g("LOG_TAIL_S") >= 0, "timing.log_tail_s must be >= 0")

    # -- rfid -------------------------------------------------------------
    check(1 <= g("RFID_PORT") <= 65535, "rfid.port must be in 1..65535")
    check(g("RFID_FRAME_LEN") > 0, "rfid.frame_len must be > 0")
    check(g("RFID_TAG_LEN") > 0, "rfid.tag_len must be > 0")
    check(g("RFID_TAG_OFFSET") >= 0, "rfid.tag_offset must be >= 0")
    # The tag has to lie inside the frame, or every read silently yields nothing.
    check(g("RFID_TAG_OFFSET") + g("RFID_TAG_LEN") <= g("RFID_FRAME_LEN"),
          f"rfid.tag_offset + tag_len ({g('RFID_TAG_OFFSET')}+{g('RFID_TAG_LEN')}) "
          f"must fit inside frame_len ({g('RFID_FRAME_LEN')})")
    try:
        init = bytes.fromhex(g("RFID_INIT_HEX") or "")
    except ValueError:
        init = None
        check(False, "rfid.init_hex must be valid hex, or empty")
    # Without the init command this reader never transmits. Empty is legal (a
    # unit already left streaming) but is almost always a mistake.
    check(init is None or len(init) > 0 or not g("RFID_ENABLED"),
          "rfid.init_hex is empty while rfid.enabled is true - the reader will "
          "stay silent until it is sent the start command")
    for t in g("RFID_IGNORE_TAGS"):
        try:
            bytes.fromhex(t)
        except ValueError:
            check(False, f"rfid.ignore_tags: {t!r} is not hex")
        check(len(t) == 2 * g("RFID_TAG_LEN"),
              f"rfid.ignore_tags: {t!r} must be {2 * g('RFID_TAG_LEN')} hex "
              f"chars to match tag_len")
    check(g("RFID_RECV_TIMEOUT_S") > 0, "rfid.recv_timeout_s must be > 0")
    check(g("RFID_BANNER_WAIT_S") > 0, "rfid.banner_wait_s must be > 0")
    check(g("RFID_SILENT_WARN_S") > g("RFID_RECV_TIMEOUT_S"),
          "rfid.silent_warn_s must exceed recv_timeout_s")
    check(g("RFID_RECONNECT_PERIOD_S") > 0,
          "rfid.reconnect_period_s must be > 0")
    check(g("RFID_TAG_HOLD_S") > 0, "rfid.tag_hold_s must be > 0")
    return ns


def load(path=None):
    """Parse, derive, validate, then publish. Nothing is published on failure."""
    path = path or PROFILE_PATH
    try:
        with open(path) as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"no vehicle profile at {path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"{os.path.basename(path)} is not valid JSON: {e}")

    ns = _validate(_derive(_parse(doc)))
    ns["PROFILE_PATH_LOADED"] = path
    globals().update(ns)
    return ns


load()
