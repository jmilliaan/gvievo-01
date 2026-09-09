"""The vehicle profile. Every tunable parameter in the system lives here.

Reads profiles/<name>.json and publishes it as flat module-level constants, so
call sites read `config.K_RATIO` rather than digging through nested dicts.
Everything else imports this; this imports nothing but the standard library,
which is what keeps the dependency graph acyclic.

WHICH VEHICLE
=============
The profile is chosen by the AGV_PROFILE environment variable, falling back to
DEFAULT_PROFILE:

    python3 app.py                      # profiles/agv-01.json
    AGV_PROFILE=agv-02 python3 app.py   # profiles/agv-02.json

and in the systemd unit, Environment=AGV_PROFILE=agv-01. There is no CLI flag
and no fallback to a profile that does not exist - a missing file is fatal and
lists the names that ARE present.

Four rules the loader enforces, in order of how much trouble they save:

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

load() is written as an atomic swap - parse and validate into a fresh namespace,
publish only on success - so nothing observes a half-applied profile. Only
called once today; a reload endpoint would be a caller, not a rewrite.


TUNING NOTES
============
JSON cannot carry comments, so the reasoning behind the settings that are not
self-evident lives here. Read this before editing a profile.

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
    2026-08-31:
        tape to the RIGHT of the sensor -> reported -53 mm
        tape to the LEFT  of the sensor -> reported +20 mm
    so positive does mean LEFT, and the raw reading has to be negated.

    Those two readings ARE the evidence - the run CSVs they came from are no
    longer kept. If a sensor is remounted, re-measure the same way (dry run,
    magnet under a STATIONARY AGV) rather than trusting this line.

autopilot.k_ratio / kd / ki
    Steering gains. k_ratio is in 1/m^2 (Kp = k_ratio*v has units rad/s per m).
    Commission at the KIM2A-proven point first as a model check, then move up:
        k_ratio 11.3, kd 0.94 -> zeta 0.30, ~12.6 mm overshoot, ~7 s settle
        k_ratio 25.0, kd 5.0  -> zeta 0.61, ~2.6 mm overshoot, ~1.2 s settle
    ki starts at 0; add it only to null a standing offset.

autopilot.slow_k_ratio / slow_kd
    The steering gains used while a SLOW ZONE is latched, in place of k_ratio and
    kd. This is the pair that decides how tight a corner the vehicle can hold.

    *** Slowing down does not help a corner. Raising k_ratio does. ***
    Cross-track error on a curve settles at

        e_ss = kappa / k_ratio          (kappa = 1/radius)

    and speed does not appear in it - it cancels, because Kp = k_ratio*v while
    holding a curve needs omega = v*kappa. That is the same cancellation that
    makes damping speed-independent, and it means halving the speed leaves the
    steady-state cornering error exactly where it was.

    Run 0018 is the evidence. It lost the tape on the ~0.5 m U-turn while already
    slowed to 441 r/min, with sat_scale at 1.00 throughout - so it never ran out
    of wheel authority, it simply could not point tightly enough. At k_ratio 11.3
    a 0.5 m radius needs 177 mm of standing error to hold, and the sensor stops
    at 100 mm, so the tape was always going to leave the window.

    What each gain buys, simulated against the real 6083h slew limit at 800 r/min:

        k_ratio / kd    R=1.0 m   R=0.7 m   R=0.5 m
          11.3 / 0.94     54 mm     71 mm    OFF THE SENSOR
          25   / 5.0      30 mm     39 mm     49 mm
          40   / 6.0      21 mm     28 mm     36 mm
          50   / 8.0      17 mm     23 mm     30 mm

    A slow zone is the right home for a high gain, and not only because that is
    where the corners are: the binding limit on k_ratio is how fast 6083h slews
    the wheel DIFFERENCE (2.59 rad/s^2 at 2000 r/min/s), and a lower speed needs
    proportionally less yaw rate for the same curvature. The headroom is largest
    exactly where it is wanted.

    kd has to rise with k_ratio or damping collapses - zeta is
    (kd + Ls*k)/(2*sqrt(k*(1 + Ls*kd))), which _validate() holds inside a sane
    band. Commission by working UP: 25/5.0 first, and only go further if the
    tightest corner on the route still runs wide.

    The changeover is a step, not a ramp. It lands at the entry tag, on the
    straight before the diverter, where the error is small - so the step in Kp*e
    is a few hundredths of a rad/s and is not worth ramping out.

autopilot.gain_blend_s
    Time constant for moving between the ordinary gains and the slow-zone pair.
    0 switches them instantly.

    The zone boundary is a tag, and a tag lands wherever it was stuck down - not
    necessarily where the vehicle has finished converging. Run 0020 read its exit
    tag while still 44 mm off the line, and k_ratio fell 25 -> 11.3 in one tick:
    steering authority more than halved at the moment the vehicle also began
    accelerating 800 -> 1200 r/min. The speed change was already shaped by
    ramp_accel_rpm_s; this gives the gain change the same courtesy.

    Short. It is smoothing a step, not filtering a signal - too long and the
    vehicle carries the wrong gains into the corner the zone exists for.

autopilot.tau_d_s
    Derivative low-pass. The sensor quantises to 1 mm, so a raw derivative sees
    100 mm/s steps on every bit flip. KIM2A pairs a light kd with a 13 ms filter;
    the 25/5 point above needs the heavier 50 ms.

autopilot.ti_deadband_mm / i_clamp
    Conditional integration: integrate only while the error
    is SMALL, freeze outside. This is anti-windup, not a conventional deadband -
    large excursions must contribute nothing. Do not invert this.

autopilot.sr_pos_frac / sr_rate_frac
    Speed reduction (error_cons). Responds to error magnitude AND
    rate, so it slows on approach to a curve rather than after deviating.

    These are FRACTIONS OF BASE SPEED per mm (and per mm/s), not absolute r/min.
    They used to be absolute, and that was a bug: when cruise went 800 -> 2000 the
    authority silently fell from 15% of base to 6% because nobody rescaled them.
    Anything that must stay proportional to speed has to be *expressed* relative
    to speed, or it will be missed at the next speed change. 0.0075 per mm means
    a 20 mm error always sheds 15% of whatever the base currently is.

autopilot.branch_default
    Which track to follow when NO branch order is latched. "straight", "left"
    or "right".

    *** This is how the U-turn is taken now. *** It used to be a branch_latch
    row - tag 0002 in, 0001 out, ordering LEFT - but the track has no RFID tag
    at that junction any more, so there is no pulse to seal in. The vehicle
    takes the extreme tape on the named side wherever a diverter appears, and
    the U-turn is selected by the junction's geometry instead of by being told
    about it beforehand.

    *** The side was measured, not guessed. *** It shipped as "right" and runs
    0048/0049 refused it: "branch right ordered, but that side is not in this
    diverter - carrying straight on", twice, with the sensor reporting two
    tracks and the follower still on LCP2. RIGHT takes the LOWEST position, so
    landing on LCP2 means the second tape was above it - the positive side,
    which with branch_positive_is_left true is LEFT. Hence "left". If the
    vehicle ever carries straight on through that junction again, this is the
    first line to re-read, and that same warning is the evidence.

    *** It is a standing rule, and the ForkPassed contact cannot end it. ***
    That contact exists to stop a latched order outliving its fork, after run
    0023/0024 - and a default outlives every fork by definition, because there
    is no pulse that could consume it. It is only consulted where there is a
    choice: on plain tape the extreme track in any direction is the only track,
    and a #LCP 7 crossing overrides it to straight. The exposure is a MERGE,
    where two tapes converge in the sensor window and the continuity rule that
    keeps STRAIGHT on the tape it was already following does not apply. Whether
    that is safe is a property of the LAYOUT: every merge on the track has to
    be right-handed, or the vehicle will change tape at the ones that are not.

    *** Setting this does not slow the junction down. *** The slow zone and the
    high-gain pair it carries come from a branch_latch row's tags, and a
    junction with no tags has neither. See auto_slow_rpm and slow_k_ratio: run
    0018 lost the tape on a 0.5 m U-turn at k_ratio 11.3, so if the new
    junction turns that tightly it needs either those gains everywhere or a tag
    pair to switch them in. "straight" restores the previous behaviour exactly.

autopilot.auto_slow_rpm
    Cruise speed while a SLOW ZONE is latched - the stretch between the entry and
    exit tags of any branch_latch row carrying slow_speed true. Off the zone the
    vehicle runs at auto_rpm; the transition either way goes through the ordinary
    software ramp, so it is shaped by ramp_accel_rpm_s and ramp_jerk_rpm_s2 like
    any other change of target and needs no separate profile.

    The zone is the whole entry-to-exit interval rather than the diverter itself,
    which is what gives the ramp room to act: the entry tag sits before the
    junction precisely so the branch order arrives in time, and the slowdown
    wants exactly the same lead. At 1200 -> 800 r/min with ramp_accel_rpm_s 1000
    that is 0.4 s, about 150 mm of travel.

    Must be in (0, auto_rpm]; _validate() enforces it, because a "slow" speed
    above cruise would speed the vehicle UP at a junction. Two derived values key
    off the SLOWER of the two - the line-loss time ceiling and the
    inner_wheel_min_rpm headroom check - since normal travel through a slow zone
    is the case they have to tolerate.

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

autopilot.auto_resume_hold_s
    How long the tape must be CONTINUOUSLY in view before an auto run that
    stopped itself on a lost line resumes on its own. 0 disables the resume
    entirely, and the run then behaves as it always did: a latched fault that
    only panel Reset clears.

    The stop is unchanged and still immediate - this only governs going again
    afterwards. A gap in the tape stops the vehicle within line_loss_grace_m of
    travel; if the tape comes back and STAYS back for this long, the run picks
    up where it left off and accelerates through the ordinary software ramp.
    Any dropout inside the window restarts the window, so an intermittent read
    can never accumulate its way to a resume.

    2 s is deliberately far longer than the 100 ms sensor_timeout_s that
    declares the loss: the question being answered is not "is there a frame"
    but "is this vehicle genuinely back on the tape", and a marginal sensor
    sitting at the edge of the tape will flicker for longer than a few frames.

    *** This is an automatic restart of MOTION, so it is worth being clear
    about what it is not. *** It cannot restart anything the safety chain
    stopped: an FX3 demand removes torque at the drives, and no value here
    brings that back. A lost tape is a navigation failure, not a protective
    stop. Every other involuntary stop - watchdog, silent driver, panel Reset,
    selector - still latches a fault and still needs a human.

autopilot.ramp_accel_rpm_s / ramp_jerk_rpm_s2
    The software motion profile, and it must stay meaningfully BELOW the driver's
    6083h (drivers.ramp.auto.accel) or the driver becomes the limiter and the
    S-curve shape is lost. _validate() enforces the ordering.

autopilot.sensor_max_mm / sensor_max_step_mm
    Sensor guards. A single glitch frame would otherwise jerk
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

manual.half_ratio / spin_ratio
    Two fractions of full_rpm, for two different manoeuvres.

    half_ratio is the INNER WHEEL of a curve. The outer wheel stays at
    full_rpm, so the ratio between them is what sets the turn radius: the
    vehicle still travels forward and the fraction only decides how sharply.

    spin_ratio is BOTH WHEELS of a spin, equal and opposite. It sets no radius
    at all - the vehicle turns on its axis and goes nowhere - so what this
    fraction actually chooses is how fast it rotates.

    *** They were one number and that was the bug. *** Sharing half_ratio tied
    the turn radius of a curve to the yaw rate of a spin, and those want
    opposite things: a curve wants a big difference between the wheels to turn
    tightly, while a spin wants a SMALL common speed, because a spin is the
    manoeuvre done in a confined space with somebody standing close enough to
    have chosen it over driving round. Raising full_rpm for open-floor travel
    sped up the spin in exactly the place that wanted it slowest.

    The spin also loads the drivetrain differently. Both wheels are fighting
    the floor sideways for the whole manoeuvre rather than rolling, so it is
    the one jog that is scrubbing the tyres the entire time it is held.

    _validate() refuses a spin_ratio that rounds to 0 r/min against full_rpm:
    that is a spin button which commands nothing, and a dead control reads as
    broken hardware rather than as a profile that asked for it.

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
    A held button re-POSTs every ~100 ms. Miss six in a row and the setpoint is
    zeroed - covers a closed tab, a dropped Wi-Fi link and a wedged browser. Auto
    is fed by the telemetry poll rather than a held button, so it gets a looser
    deadline; it still stops if the page goes away.

    0.6 s rather than the original 0.4: three missed POSTs is tight over Wi-Fi,
    and the trips it produced were the link hiccuping rather than the operator
    letting go. It does not change how fast the vehicle stops when they DO let
    go - the browser sends /api/stop on release and that is immediate; this
    deadline only covers the case where nothing arrives at all.

    *** The two modes do different things when it expires. *** Both zero the
    setpoint. Manual stops there and logs a warning: recovery is to hold the
    button again, which is a deliberate act with a hand on the control, so
    there is nothing for an acknowledgment to add. Auto latches a fault, because
    an auto run is latched motion that would otherwise resume on its own.

branch_latch.*
    The junction table. An entry tag latches a steering order, the fork consumes
    it, and the exit tag ends the slow zone that ran alongside it - three coils
    off one tag pair, see core/branch.py.

    Branch tags are unique within this table and cannot also be station or
    high-speed tags. Direction-qualified reuse belongs to those other tables.

stop_until_start_button.*
    Direction-qualified station rules: tag, direction and stop_distance_m.
    The route stage identifies the physical station when tag values repeat.
    Arrival pauses the same run/log; Start resumes after auto_start_delay_s.
    Distance-based deceleration is computed from the software ramp speed, not
    measured odometry. Steering and drive dynamics affect actual stop distance.
    ignore_t was removed: tag encounters now suppress repeats until clearance.

route
    Ordered physical stations. The first row is the startup position (point 2,
    outbound). Each row supplies id, tag, arrival direction and permission for
    high speed on its outgoing leg. Departure adopts the NEXT station's arrival
    direction. Route state survives Reset, disarm and manual mode in memory;
    a process restart initializes the first station again.

high_speed_mode.*
    Direction-qualified entry_tag / exit_tag set and reset the high-speed latch.
    The same physical tag pair may be reversed for the opposite direction and
    reused on several segments. Station, branch and speed tag types cannot
    overlap. Stations, holds, disarm and RFID link loss clear high speed.

autopilot.auto_rpm_high / speed_switch_accel_decel_s
    auto_rpm_high must exceed auto_rpm and fit motor_max_rpm. The speed-switch
    rate is their difference divided by speed_switch_accel_decel_s: 1000 to
    2000 over 2 s requests 500 rpm/s. Existing jerk limiting remains active, so
    completion can take slightly longer. Startup and station stops keep their
    own ramps; slow-zone speed and gains override high-speed mode.

rfid.tag_clear_s
    A same-valued tag becomes a new encounter after this interval without a
    read. This is separate from tag_hold_s, which only keeps the HMI readable.
    0.5 s is provisional: verify it against actual read gaps and station spacing.
    Reconnection re-baselines the reader rather than inventing a station visit.

panel.manual_auto_arm
    MANUAL is an ARMED STATE. With this set, the selector sitting in MANUAL is
    itself the arm command: the drives energise without anyone pressing Reset,
    and re-energise on their own if something de-energised them.

    The point is the operator's hands. Reset had become a button pressed
    reflexively before every jog, and a control pressed by reflex is a control
    that has stopped being a decision.

    *** Arming is not motion. *** An armed manual vehicle is excited and holding
    zero; every millimetre of travel still needs a jog button HELD, re-POSTed
    every ~100 ms, with manual_watchdog_s to stop it the moment they are
    released. What this changes is that the vehicle is live whenever the
    selector says MANUAL - including at power-up with the selector already
    there, which is a level, not an edge, and so is not covered by the panel's
    anti-tie-down rule.

    It cannot arm through the safety chain. An FX3 demand leaves the drives in
    ETO and the arm attempt simply fails; it is retried on a slow backoff rather
    than latched, so the vehicle comes back on its own once the chain is
    restored and acknowledged. No latched fault is cleared this way - a fault
    still blocks arming until somebody presses Reset.

horn.*
    The only output this software energises. DO goes high whenever motion is
    COMMANDED - manual jog or auto run, no distinction, because the hazard is
    the same 150 kg either way and a horn that means two different things means
    neither.

    *** It follows the setpoint, not the wheels. *** The coil is raised from the
    commanded target, so it sounds at the instant motion is asked for rather
    than once the vehicle is already rolling - which is the whole point of a
    warning device. It also means the horn goes quiet while the drives are
    still decelerating, and that is the right way round: the warning ends when
    the vehicle stops being commanded to move, and what remains is a coast that
    is already ending.

    *** Not a safety function. *** The stop is the OSSD chain into the FX3, in
    hardware. This is an audible warning and nothing gates on it: a horn that
    failed to sound must not be able to prevent a jog, or a broken lamp becomes
    a stranded vehicle.

    Renewal, not level. The command carries HORN_HOLD_S and the CAN tick renews
    it every 20 ms; a tick that stops renewing drops the coil at the DIO scan
    rather than leaving it energised. See the derived value.

timing.auto_start_delay_s
    The pause between AUTO arming and the wheels being commanded, after Start is
    pressed. The drives energise, the brake releases and the sensor comes up
    during it, so the vehicle is fully awake before the first setpoint rather
    than during it - and it gives whoever pressed the button a beat to step back.

    Start does the arming now, so the whole press-to-motion time is the arm
    sequence (~0.8 s of SDO) plus this. Cancelled by a selector move, by Reset,
    or by losing the panel image inside the window.

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

timing.driver_timeout_s
    How long a driver may go without answering a telemetry read before it is
    declared silent and the vehicle is stopped. This is HARDWARE health and has
    nothing to do with the browser watchdogs above - those cover an absent
    operator, this covers an absent driver.

    Must sit above telemetry_period_s or the ordinary gap between two polls
    reads as a dead driver; _validate() enforces that. 0.6 s is three normal
    polls, which is deliberately generous: the 5 Hz telemetry poll shares the
    bus with setpoint writes, so an occasional late read is expected. Tighten it
    only after watching the event log across several runs.

can.heartbeat_ms
    Producer heartbeat time (1017h), written to each drive at bus-up. The
    driver default is 0 = OFF, and with it off a drive that has stopped
    responding looks identical to one that is simply idle - which is exactly
    the hole health.py was working around by inferring liveness from whether an
    SDO happened to answer. 200 ms is the plan's recommendation.

    Must be under half timing.driver_timeout_s or one missed heartbeat reads as
    a dead driver; _validate() enforces that. 0 leaves the drive's own setting
    alone.

monitor.*
    Drive health monitoring - see manuals/can-monitoring-plan.txt.

    *** DIAGNOSTIC ONLY. Nothing here may decide whether it is safe to move. ***
    The safety chain is lidar/encoders -> FX3 -> HWTO1/HWTO2 -> STO, in
    hardware. CAN is the channel beside it that records what happened and warns
    before a trip.

    The analogue objects are polled ONE PER NODE per poll, round-robin, and
    poll_period_s paces it. At tick rate that would be two SDO round-trips out
    of every 20 ms budget - about 4 ms of tick and a fifth of a 125 kbps bus -
    for values that move on a thermal timescale. At 0.1 s it is ~0.8 ms of
    average tick and ~4% of the bus, sweeping the whole table in about a
    second. The plan asks for 1-5 Hz on Tier 3; this sits just under it and
    leaves the control loop alone, which matters more.

    Temperature warns are the plan's: driver trips at 85 C so warn at 70, motor
    trips at 95 so warn at 80. Bus voltage is two-sided - low is battery sag
    with stopping distance already degraded, high is regen the battery is
    refusing to take, and the high warn wants to sit well below the drive's
    own 63 V overvoltage trip.

can.channel / can.adapter_serial
    The SocketCAN interface to prefer, and which CANable2 to accept on the USB
    fallback. Per-vehicle hardware identity, so it belongs in the profile rather
    than in canbus/verify_drivers.py where it used to live. adapter_serial ""
    accepts any matching adapter, which is what a bench with one wants.

timing.log_tail_s
    How long to keep logging after a stop. The deceleration is the part worth
    seeing afterwards, and it happens entirely inside the drivers.
"""
import json
import math
import os
import re
import textwrap

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "profiles")
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
        "branch_positive_is_left": ("BRANCH_POSITIVE_IS_LEFT", bool),
        # The intent with no latch set - "straight", "left" or "right". A
        # junction with no RFID tag has nothing to seal in, so this is how it
        # gets an answer. See the tuning note.
        "branch_default":      ("BRANCH_DEFAULT", str),
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
        "auto_rpm_high":       ("AUTO_RPM_HIGH", float),
        "speed_switch_accel_decel_s": ("SPEED_SWITCH_S", float),
        "auto_slow_rpm":       ("AUTO_SLOW_RPM", float),
        "slow_k_ratio":        ("SLOW_K_RATIO", float),
        "slow_kd":             ("SLOW_KD", float),
        "gain_blend_s":        ("GAIN_BLEND_S", float),
        "ramp_accel_rpm_s":    ("RAMP_ACCEL_RPM_S", float),
        "ramp_jerk_rpm_s2":    ("RAMP_JERK_RPM_S2", float),
        "sensor_max_mm":       ("SENSOR_MAX_MM", float),
        "sensor_max_step_mm":  ("SENSOR_MAX_STEP_MM", float),
        "line_loss_grace_m":   ("LINE_LOSS_GRACE_M", float),
        "sensor_timeout_s":    ("SENSOR_TIMEOUT_S", float),
        "auto_resume_hold_s":  ("AUTO_RESUME_HOLD_S", float),
        "dt_nominal_s":        ("DT_NOMINAL_S", float),
        "inner_wheel_min_rpm": ("INNER_WHEEL_MIN_RPM", float),
    },
    "manual": {
        "full_rpm":   ("MANUAL_FULL_RPM", int),
        "half_ratio": ("MANUAL_HALF_RATIO", float),
        # The spin pair gets its own fraction. See the tuning note: a spin is a
        # different manoeuvre from a curve, not a slower version of one.
        "spin_ratio": ("MANUAL_SPIN_RATIO", float),
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
        "tag_clear_s":        ("RFID_TAG_CLEAR_S", float),
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
        # SICK nanoScan3, streaming UDP to this host. READ-ONLY: we bind a
        # socket and listen. Nothing here opens a CoLa 2 session or writes to
        # the device - see drivers/lidar.py.
        "enabled":               ("LIDAR_ENABLED", bool),
        "host_ip":               ("LIDAR_HOST_IP", str),
        "sensor_ip":             ("LIDAR_SENSOR_IP", str),
        "port":                  ("LIDAR_PORT", int),
        "silent_warn_s":         ("LIDAR_SILENT_WARN_S", float),
        "reassembly_timeout_s":  ("LIDAR_REASSEMBLY_TIMEOUT_S", float),
        "reconnect_period_s":    ("LIDAR_RECONNECT_PERIOD_S", float),
        "decimate":              ("LIDAR_DECIMATE", int),
        # Identity and configuration checksum, compared at runtime so a swapped
        # scanner or an altered configuration is visible. Empty disables the
        # comparison rather than failing it.
        "expected_identity":     ("LIDAR_EXPECTED_IDENTITY", str),
        "expected_checksum":     ("LIDAR_EXPECTED_CHECKSUM", str),
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
        "manual_auto_arm": ("PANEL_MANUAL_AUTO_ARM", bool),
        "debounce_scans": ("PANEL_DEBOUNCE_SCANS", int),
    },
    # The panel's mirror image: that section READS the DI image, this one
    # WRITES a coil. Kept apart from "dio" for the same reason "panel" is - dio
    # owns the socket and the scan, and these say what a channel MEANS.
    "horn": {
        "enabled":    ("HORN_ENABLED", bool),
        "do_channel": ("HORN_DO_CHANNEL", int),
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
        "poll_period_s":      ("MONITOR_PERIOD_S", float),
        "driver_temp_warn_c": ("MON_DRV_WARN_C", float),
        "driver_temp_trip_c": ("MON_DRV_TRIP_C", float),
        "motor_temp_warn_c":  ("MON_MTR_WARN_C", float),
        "motor_temp_trip_c":  ("MON_MTR_TRIP_C", float),
        "bus_v_warn_low":     ("MON_BUS_V_WARN_LOW", float),
        "bus_v_warn_high":    ("MON_BUS_V_WARN_HIGH", float),
    },
    "timing": {
        "loop_period_s":      ("LOOP_PERIOD_S", float),
        "telemetry_period_s": ("TELEMETRY_PERIOD_S", float),
        "field_period_s":     ("FIELD_PERIOD_S", float),
        "manual_watchdog_s":  ("MANUAL_WATCHDOG_S", float),
        "auto_watchdog_s":    ("AUTO_WATCHDOG_S", float),
        "driver_timeout_s":   ("DRIVER_TIMEOUT_S", float),
        "log_tail_s":         ("LOG_TAIL_S", float),
        "auto_start_delay_s": ("AUTO_START_DELAY_S", float),
    },
}

_TOP_LEVEL_SCALARS = {"profile_name": ("PROFILE_NAME", str)}

# The nanoScan3's scan cycle, from its datasheet: 30 ms, i.e. 33 Hz. A device
# constant, not a tunable - it is here so the lidar timing checks below have
# something to measure the profile against, and it is the ONE nanoScan3 number
# taken from paper rather than from the telegram. Everything about the scan
# ITSELF - beam count, start angle, angular resolution - is read off the wire,
# because sec 2.4 of lidar_brief.md says the device may not do what the
# datasheet says.
LIDAR_SCAN_CYCLE_S = 0.030


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


def _read_zone_bytes(raw, where):
    """lidar.zone_bytes -> one byte offset per cut-off path, in path order.

    A list of ints, which _SCHEMA's flat table cannot express (its `list` means
    a list of strings, for the I/O names). Three entries, because the device's
    verification report defines paths 1-3 as stop, slow and warn - and the
    ORDER is the thing lidar_brief.md sec 2.5 insists must be confirmed rather
    than assumed, which is exactly why it lives in the profile.
    """
    if not isinstance(raw, list) or not all(isinstance(v, int)
                                            and not isinstance(v, bool)
                                            for v in raw):
        raise ConfigError(f"{where}: expected a list of integers")
    if len(raw) != 3:
        raise ConfigError(f"{where}: expected 3 offsets (stop, slow, warn), "
                          f"got {len(raw)}")
    if any(v < 0 for v in raw):
        raise ConfigError(f"{where}: byte offsets must be >= 0, got {raw}")
    return list(raw)


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


def _read_branch_latch(rows, tag_len, ignore_tags):
    """branch_latch -> validated rows, or [] when there are no junctions yet.

    An entry tag sets a direction and an exit tag clears it (branch.Ladder).
    Every check here exists to stop a rung being silently DEAD, which is the
    only failure mode this table has: a tag that never matches produces no
    error, no log line and no motion - the AGV simply drives past the junction.

    slow_speed is OPTIONAL and defaults to false, because most junctions do not
    need it and a table of diverters written before the flag existed must keep
    loading. It is the one key here that changes how fast the vehicle arrives at
    the diverter, so it is still type-checked like everything else: the string
    "True" is refused, not silently accepted as truthy.
    """
    if not isinstance(rows, list):
        raise ConfigError("branch_latch: expected a list")
    want = {"entry_tag", "exit_tag", "branch"}
    optional = {"slow_speed"}
    width = tag_len * 2
    seen = {}
    out = []
    for i, row in enumerate(rows):
        where = f"branch_latch[{i}]"
        if not isinstance(row, dict):
            raise ConfigError(f"{where}: expected an object")
        unknown = set(row) - want - optional
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}")
        missing = want - set(row)
        if missing:
            raise ConfigError(f"{where}: missing key(s) {sorted(missing)}")

        slow = _coerce(row.get("slow_speed", False), bool,
                       f"{where}.slow_speed")

        side = _coerce(row["branch"], str, f"{where}.branch")
        if side not in ("left", "right"):
            raise ConfigError(f"{where}.branch: expected 'left' or 'right', "
                              f"got {side!r}")

        tags = {}
        for key in ("entry_tag", "exit_tag"):
            raw = row[key]
            # The reader hands tags over as hex text (rfid.tag_of), so a JSON
            # number here can never match one - and would fail silently.
            if not isinstance(raw, str):
                raise ConfigError(
                    f"{where}.{key}: expected a {width}-character hex string "
                    f"like \"000A\", got {raw!r}. Tag ids come from "
                    f"rfid.tag_of() as hex text, so a number never matches.")
            tag = raw.upper()
            if len(tag) != width or any(c not in "0123456789ABCDEF" for c in tag):
                raise ConfigError(f"{where}.{key}: expected {width} hex "
                                  f"characters, got {raw!r}")
            if tag in ignore_tags:
                raise ConfigError(f"{where}.{key}: {tag} is also in "
                                  f"rfid.ignore_tags, so it is discarded before "
                                  f"the ladder can see it")
            tags[key] = tag

        if tags["entry_tag"] == tags["exit_tag"]:
            raise ConfigError(f"{where}: entry_tag and exit_tag are both "
                              f"{tags['entry_tag']} - the same read cannot both "
                              f"set and clear the latch")
        for key, tag in tags.items():
            if tag in seen:
                raise ConfigError(f"{where}.{key}: tag {tag} is already used by "
                                  f"{seen[tag]} - one tag cannot mean two things")
            seen[tag] = f"{where}.{key}"
        out.append({"entry_tag": tags["entry_tag"],
                    "exit_tag": tags["exit_tag"], "branch": side,
                    "slow_speed": slow})
    return out


def _rule_rows(rows, keys, where):
    if not isinstance(rows, list):
        raise ConfigError(f"{where}: expected a list")
    for i, row in enumerate(rows):
        loc = f"{where}[{i}]"
        if not isinstance(row, dict) or set(row) != set(keys):
            raise ConfigError(f"{loc}: expected exactly {sorted(keys)}")
        yield row, loc


def _tag(raw, width, where, forbidden):
    if not isinstance(raw, str) or len(raw) != width or any(
            c not in "0123456789ABCDEF" for c in raw.upper()):
        raise ConfigError(f"{where}: expected {width} hex characters")
    tag = raw.upper()
    if tag in forbidden:
        raise ConfigError(f"{where}: tag {tag} is ignored or assigned to another rule type")
    return tag


def _travel_direction(raw, where):
    if raw not in ("outbound", "inbound"):
        raise ConfigError(f"{where}.direction must be outbound or inbound")
    return raw


def _read_stop_tags(rows, tag_len, ignore_tags, branch_tags):
    """Direction-qualified stop parameters; physical stations live in route."""
    out = {}
    for row, loc in _rule_rows(rows, ("tag", "direction", "stop_distance_m"),
                               "stop_until_start_button"):
        direction = _travel_direction(row["direction"], loc)
        tag = _tag(row["tag"], tag_len * 2, loc, ignore_tags | branch_tags)
        dist = _coerce(row["stop_distance_m"], float, loc + ".stop_distance_m")
        if not 0 < dist <= 5:
            raise ConfigError(f"{loc}.stop_distance_m must be in (0, 5] m")
        key = (direction, tag)
        if key in out:
            raise ConfigError(f"{loc}: duplicate direction/tag stop rule")
        out[key] = {"stop_distance_m": dist}
    return out


def _read_route(rows, speed_rows, stops, tag_len, ignored, branch_tags):
    stations, ids = [], set()
    for row, loc in _rule_rows(rows, ("id", "tag", "direction", "high_speed_to_next"),
                               "route"):
        ident = _coerce(row["id"], str, loc + ".id")
        if not ident.strip() or ident in ids:
            raise ConfigError(f"{loc}.id must be nonempty and unique")
        ids.add(ident)
        direction = _travel_direction(row["direction"], loc)
        tag = _tag(row["tag"], tag_len * 2, loc, ignored | branch_tags)
        if (direction, tag) not in stops:
            raise ConfigError(f"{loc}: no matching direction/tag stop rule")
        high = _coerce(row["high_speed_to_next"], bool, loc + ".high_speed_to_next")
        stations.append(dict(id=ident, tag=tag, direction=direction,
                             high_speed_to_next=high))
    if len(stations) < 2:
        raise ConfigError("route must contain at least two stations; first is initial position")
    if stations[0]["direction"] != "outbound":
        raise ConfigError("route first station must be outbound")
    speed, contacts = [], set()
    stop_tags = {tag for direction, tag in stops}
    for row, loc in _rule_rows(speed_rows, ("entry_tag", "exit_tag", "direction"),
                               "high_speed_mode"):
        direction = _travel_direction(row["direction"], loc)
        tags = [_tag(row[k], tag_len * 2, loc + "." + k,
                     ignored | branch_tags | stop_tags)
                for k in ("entry_tag", "exit_tag")]
        for tag in tags:
            if (direction, tag) in contacts:
                raise ConfigError(f"{loc}: duplicate/ambiguous high-speed contact in {direction}")
            contacts.add((direction, tag))
        speed.append(dict(entry_tag=tags[0], exit_tag=tags[1], direction=direction))
    for i, station in enumerate(stations):
        departure = stations[(i + 1) % len(stations)]["direction"]
        if station["high_speed_to_next"] and not any(
                r["direction"] == departure for r in speed):
            raise ConfigError(f"route[{i}]: high-speed leg has no {departure} speed rule")
    return stations, speed


def _parse(doc):
    """Raw JSON document -> flat namespace of primitives. Strict both ways."""
    if not isinstance(doc, dict):
        raise ConfigError("profile must be a JSON object")

    expected_sections = (set(_SCHEMA) | set(_TOP_LEVEL_SCALARS)
                         | {"branch_latch", "stop_until_start_button",
                            "route", "high_speed_mode"})
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
        if section == "dio":
            allowed |= {"di_names", "do_names"}
        if section == "lidar":
            allowed |= {"zone_bytes"}
        unknown = set(block) - allowed
        if unknown:
            raise ConfigError(f"{section}: unknown key(s) {sorted(unknown)}")
        missing = allowed - set(block)
        if missing:
            raise ConfigError(f"{section}: missing key(s) {sorted(missing)}")
        for key, (name, want) in fields.items():
            ns[name] = _coerce(block[key], want, f"{section}.{key}")

    ns["RAMP"] = _read_ramp(doc["drivers"])
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
    ns["LIDAR_ZONE_BYTES"] = _read_zone_bytes(
        doc["lidar"]["zone_bytes"], "lidar.zone_bytes")
    ns["BRANCH_LATCH"] = _read_branch_latch(
        doc["branch_latch"], ns["RFID_TAG_LEN"], set(ns["RFID_IGNORE_TAGS"]))
    _branch_tags = {r[k] for r in ns["BRANCH_LATCH"]
                    for k in ("entry_tag", "exit_tag")}
    ns["STOP_TAGS"] = _read_stop_tags(
        doc["stop_until_start_button"], ns["RFID_TAG_LEN"],
        set(ns["RFID_IGNORE_TAGS"]), _branch_tags)
    ns["ROUTE"], ns["HIGH_SPEED_MODE"] = _read_route(
        doc["route"], doc["high_speed_mode"], ns["STOP_TAGS"],
        ns["RFID_TAG_LEN"], set(ns["RFID_IGNORE_TAGS"]), _branch_tags)
    return ns


def _derive(ns):
    """Everything computable from the primitives, so the profile cannot carry a
    value that contradicts the one it was derived from."""
    # Motor r/min -> wheel travel. One wheel turn covers pi*D and takes
    # GEAR_RATIO motor turns, so v = (N / GEAR_RATIO) * pi*D / 60.
    ns["MPS_PER_RPM"] = (math.pi * ns["WHEEL_DIA_M"]
                         / (ns["GEAR_RATIO"] * 60.0))          # 3.14159e-4
    ns["RPM_PER_MPS"] = 1.0 / ns["MPS_PER_RPM"]                # 3183.1
    if ns["SPEED_SWITCH_S"] <= 0:
        raise ConfigError("speed_switch_accel_decel_s must be > 0")
    ns["SPEED_SWITCH_RPM_S"] = (
        ns["AUTO_RPM_HIGH"] - ns["AUTO_RPM"]) / ns["SPEED_SWITCH_S"]
    # Yaw rate from a left/right difference: omega = (v_right - v_left) / TRACK.
    ns["RAD_S_PER_RPM_DIFF"] = ns["MPS_PER_RPM"] / ns["TRACK_M"]   # 6.46418e-4
    ns["MAX_SPEED_MPS"] = ns["MOTOR_MAX_RPM"] * ns["MPS_PER_RPM"]  # 1.2566 m/s

    # Inner wheel of a curve...
    ns["MANUAL_HALF_RPM"] = round(ns["MANUAL_FULL_RPM"] * ns["MANUAL_HALF_RATIO"])
    # ...and both wheels of a spin, which is no longer the same number.
    ns["MANUAL_SPIN_RPM"] = round(ns["MANUAL_FULL_RPM"] * ns["MANUAL_SPIN_RATIO"])

    # A scheduling hiccup or a resume-after-stop gap must not blow up I and D,
    # so the measured dt is clamped to this band.
    ns["DT_MIN_S"] = 0.2 * ns["DT_NOMINAL_S"]
    ns["DT_MAX_S"] = 5.0 * ns["DT_NOMINAL_S"]

    # Line loss is budgeted as a DISTANCE, but a stationary AGV that cannot see
    # tape accrues no distance and would coast forever, so the budget needs a
    # time ceiling too. Five times the nominal grace at cruise: generous enough
    # never to fire during normal travel, finite enough to bound the standstill
    # case. Derived, so it is not one more thing to forget when speed changes.
    #
    # Taken at the SLOWEST speed the autopilot commands, not at cruise: the
    # ceiling must never fire during normal travel, and normal travel through a
    # slow zone covers the same distance in more time. At the present 800 r/min
    # the 75 mm budget takes 0.30 s against a ~1.5 s ceiling, so this does not
    # bite today - but it should hold by construction, not by luck.
    ns["LINE_LOSS_GRACE_MAX_S"] = (
        5.0 * ns["LINE_LOSS_GRACE_M"]
        / max(min(ns["AUTO_RPM"], ns["AUTO_SLOW_RPM"]) * ns["MPS_PER_RPM"],
              1e-6))

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

    # The autopilot is tuned against the AUTO ramp specifically: 6083h caps both
    # the forward ramp and the rate at which the wheel DIFFERENCE can slew,
    # which is the binding constraint on steering gain.
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

    # -- branch selection --------------------------------------------------
    # Spelled out rather than taken from branch.py: config imports nothing from
    # the layers it configures, so a typo here has to be caught here.
    check(g("BRANCH_DEFAULT") in ("straight", "left", "right"),
          f"autopilot.branch_default ({g('BRANCH_DEFAULT')!r}) must be "
          f"'straight', 'left' or 'right'")

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
    check(g("AUTO_RPM") < g("AUTO_RPM_HIGH") <= g("MOTOR_MAX_RPM"),
          "auto_rpm_high must exceed auto_rpm and not exceed motor_max_rpm")
    check(0 < g("SPEED_SWITCH_RPM_S") <= g("RAMP_ACCEL_RPM_S"),
          "speed_switch_accel_decel_s requests a rate above ramp_accel_rpm_s")
    check(0 < g("RFID_TAG_CLEAR_S") <= 5,
          "rfid.tag_clear_s must be in (0, 5] seconds")
    check(g("SLOW_K_RATIO") > 0, "slow_k_ratio must be > 0")
    check(g("SLOW_KD") >= 0, "slow_kd must be >= 0")
    check(g("GAIN_BLEND_S") >= 0, "gain_blend_s must be >= 0")
    # A gain pair that cannot damp itself is the one way this feature bites
    # back: too little kd for the k_ratio and the vehicle weaves through every
    # junction it was meant to corner better.
    _z = (g("SLOW_KD") + g("SENSOR_LOOKAHEAD_M") * g("SLOW_K_RATIO")) / (
        2.0 * math.sqrt(g("SLOW_K_RATIO")
                        * (1.0 + g("SENSOR_LOOKAHEAD_M") * g("SLOW_KD"))))
    check(0.2 <= _z <= 1.5,
          f"slow_k_ratio {g('SLOW_K_RATIO')} with slow_kd {g('SLOW_KD')} gives "
          f"predicted zeta {_z:.2f}, outside 0.2..1.5 - raise slow_kd with "
          f"slow_k_ratio or the vehicle weaves through every junction")
    check(0 < g("AUTO_SLOW_RPM") <= g("AUTO_RPM"),
          f"auto_slow_rpm ({g('AUTO_SLOW_RPM')}) must be in (0, auto_rpm "
          f"({g('AUTO_RPM')})] - a slow speed above cruise is a typo, and the "
          f"vehicle would speed UP at a junction")
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
    check(g("AUTO_RESUME_HOLD_S") >= 0,
          "auto_resume_hold_s must be >= 0 (0 disables the resume)")
    check(not (0 < g("AUTO_RESUME_HOLD_S") < g("SENSOR_TIMEOUT_S")),
          f"auto_resume_hold_s ({g('AUTO_RESUME_HOLD_S')}) is below "
          f"sensor_timeout_s ({g('SENSOR_TIMEOUT_S')}) - it would resume "
          f"before the sensor has been believed once")
    check(g("DT_NOMINAL_S") > 0 and g("DT_MIN_S") > 0
          and g("DT_MAX_S") > g("DT_MIN_S"), "dt band is inconsistent")
    # Against the SLOWER of the two: the floor has to leave steering headroom at
    # the speed the vehicle actually takes a junction at, which is the one place
    # it is asked to steer hardest.
    check(g("INNER_WHEEL_MIN_RPM") < min(g("AUTO_RPM"), g("AUTO_SLOW_RPM")),
          "INNER_WHEEL_MIN_RPM must leave room to steer at AUTO_SLOW_RPM")

    # -- manual jog -------------------------------------------------------
    check(0 < g("MANUAL_FULL_RPM") <= g("MOTOR_MAX_RPM"),
          f"manual.full_rpm must be in (0, {g('MOTOR_MAX_RPM')}]")
    check(0.0 < g("MANUAL_HALF_RATIO") <= 1.0,
          "manual.half_ratio must be a fraction in (0, 1]")
    check(0.0 < g("MANUAL_SPIN_RATIO") <= 1.0,
          "manual.spin_ratio must be a fraction in (0, 1]")
    # Rounding a small fraction of a small full_rpm can reach 0, and a spin
    # button that commands zero is a button that does nothing - which reads as
    # a broken control rather than as a profile that asked for it.
    check(g("MANUAL_SPIN_RPM") > 0,
          f"manual.spin_ratio ({g('MANUAL_SPIN_RATIO')}) x full_rpm "
          f"({g('MANUAL_FULL_RPM')}) rounds to 0 r/min - the spin buttons "
          f"would be dead")

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
    check(bool(g("CAN_CHANNEL")), "can.channel must be a SocketCAN interface "
                                  "name such as \"can0\"")
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
    # A driver is declared silent when its telemetry stops answering. The
    # deadline has to sit ABOVE the poll period or the normal gap between two
    # polls reads as a fault - the same pairing check as loop/telemetry above,
    # and one neither module could make alone.
    check(g("DRIVER_TIMEOUT_S") > g("TELEMETRY_PERIOD_S"),
          f"timing.driver_timeout_s ({g('DRIVER_TIMEOUT_S')}) must exceed "
          f"telemetry_period_s ({g('TELEMETRY_PERIOD_S')}), or the gap between "
          f"two normal polls is reported as a dead driver")
    check(g("LOG_TAIL_S") >= 0, "timing.log_tail_s must be >= 0")
    check(g("AUTO_START_DELAY_S") >= 0,
          "timing.auto_start_delay_s must be >= 0")
    check(g("AUTO_START_DELAY_S") <= 10.0,
          f"timing.auto_start_delay_s ({g('AUTO_START_DELAY_S')} s) is a long "
          f"time to stand still after a button press - an operator will press "
          f"it again")

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
    # One object per node per poll. At the 20 ms tick this would be two SDO
    # round-trips EVERY tick - about 4 ms of a 20 ms budget and a fifth of the
    # bus - for values that move on a thermal timescale. Pacing it to 0.1 s
    # sweeps the whole table in about a second, which is inside the 1-5 Hz the
    # monitoring plan asks for and leaves the control loop alone.
    check(g("MONITOR_PERIOD_S") >= g("LOOP_PERIOD_S"),
          f"monitor.poll_period_s ({g('MONITOR_PERIOD_S')}) must be >= "
          f"loop_period_s ({g('LOOP_PERIOD_S')})")
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
    # A scan is two reads and, when a coil is being corrected, a write. Only
    # the first operation to go quiet costs the whole timeout - the rest never
    # run, because a failure raises out of the scan - so this bounds the scan
    # even though three timeouts would not fit inside one period.
    check(g("DIO_TIMEOUT_S") < g("DIO_SCAN_PERIOD_S"),
          f"dio.timeout_s ({g('DIO_TIMEOUT_S')}) must be below scan_period_s "
          f"({g('DIO_SCAN_PERIOD_S')}) - one stalled operation must not "
          f"outlast the scan that issued it")
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
    check(g("LIDAR_SILENT_WARN_S") > 0, "lidar.silent_warn_s must be > 0")
    check(g("LIDAR_REASSEMBLY_TIMEOUT_S") > 0,
          "lidar.reassembly_timeout_s must be > 0")
    check(g("LIDAR_RECONNECT_PERIOD_S") > 0,
          "lidar.reconnect_period_s must be > 0")
    check(g("LIDAR_DECIMATE") >= 1, "lidar.decimate must be >= 1")
    # The scanner streams every 30 ms. A window under that declares the link
    # dead between two consecutive good telegrams, and the page flaps at 34 Hz.
    check(g("LIDAR_SILENT_WARN_S") > LIDAR_SCAN_CYCLE_S,
          f"lidar.silent_warn_s ({g('LIDAR_SILENT_WARN_S')}) must exceed the "
          f"{LIDAR_SCAN_CYCLE_S * 1000:.0f} ms scan cycle")
    # A telegram is five datagrams arriving inside one cycle. Holding fragments
    # for longer than a cycle risks pairing a fragment with a same-offset
    # fragment from the NEXT scan and emitting a stitched-together picture.
    check(g("LIDAR_REASSEMBLY_TIMEOUT_S") < g("LIDAR_SILENT_WARN_S"),
          f"lidar.reassembly_timeout_s ({g('LIDAR_REASSEMBLY_TIMEOUT_S')}) must "
          f"be below silent_warn_s ({g('LIDAR_SILENT_WARN_S')})")
    check(0 <= g("LIDAR_ZONE_BLOCK") < 7,
          f"lidar.zone_block ({g('LIDAR_ZONE_BLOCK')}) must be a block slot 0..6")
    check(g("LIDAR_HOST_IP") != g("LIDAR_SENSOR_IP"),
          "lidar.host_ip and lidar.sensor_ip must differ - host_ip is the "
          "address we bind, sensor_ip is the scanner we accept datagrams from")

    # -- panel ------------------------------------------------------------
    chans = {"di_reset": g("PANEL_DI_RESET"), "di_start": g("PANEL_DI_START"),
             "di_auto": g("PANEL_DI_AUTO")}
    for key, ch in chans.items():
        check(0 <= ch < g("DIO_NUM_DI"),
              f"panel.{key} ({ch}) must be a channel in 0..{g('DIO_NUM_DI') - 1}")
    # Two functions on one channel is a wiring or config error that would
    # otherwise present as phantom presses - a Reset edge every time Start is
    # pushed - which is a miserable thing to debug from the vehicle.
    check(len(set(chans.values())) == 3,
          f"panel channels must be distinct, got {chans}")
    check(g("PANEL_DEBOUNCE_SCANS") >= 1, "panel.debounce_scans must be >= 1")
    # The panel is read out of the DI image; without the scan there is nothing
    # to read, and the buttons would be silently dead.
    check(not g("PANEL_ENABLED") or g("DIO_ENABLED"),
          "panel.enabled is true while dio.enabled is false - the panel is read "
          "from the DI image, so the buttons would never respond")

    # -- horn -------------------------------------------------------------
    check(0 <= g("HORN_DO_CHANNEL") < g("DIO_NUM_DO"),
          f"horn.do_channel ({g('HORN_DO_CHANNEL')}) must be a channel in "
          f"0..{g('DIO_NUM_DO') - 1}")
    # Same reasoning as panel.enabled above: the coil is written by the DIO
    # scan, so without it the horn is silently dead rather than merely off.
    check(not g("HORN_ENABLED") or g("DIO_ENABLED"),
          "horn.enabled is true while dio.enabled is false - the coil is "
          "written by the DIO scan, so the horn would never sound")

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
    path = path or profile_path()
    try:
        with open(path) as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise ConfigError(
            f"no vehicle profile at {path}. Set {PROFILE_ENV_VAR} to one of "
            f"{_available() or ['(none found)']}, or add the file.")
    except json.JSONDecodeError as e:
        raise ConfigError(f"{os.path.basename(path)} is not valid JSON: {e}")

    # The name inside the file has to agree with the file it came from. A
    # profile copied for a second vehicle and not renamed would otherwise
    # report the old identity in the event log and in every run CSV header -
    # silent, and only noticed when comparing runs weeks later.
    stem = os.path.splitext(os.path.basename(path))[0]
    ns = _parse(doc)
    if ns["PROFILE_NAME"] != stem:
        raise ConfigError(f"profile_name is {ns['PROFILE_NAME']!r} but the file "
                          f"is {stem}.json - rename one to match the other")

    ns = _validate(_derive(ns))
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
    "CAN_BITRATE": "bit/s", "PLOT_RPM_MAX": "r/min",
    "MON_BUS_V_WARN_LOW": "V", "MON_BUS_V_WARN_HIGH": "V",
    "K_RATIO": "1/m\u00b2",
    "MPS_PER_RPM": "m/s per r/min", "RPM_PER_MPS": "r/min per m/s",
    "RAD_S_PER_RPM_DIFF": "rad/s per r/min diff", "MAX_SPEED_MPS": "m/s",
}

# Everything _derive() computes, with the relation that produced it - which is
# the whole reason these are shown apart from the profile: they cannot be
# edited, and a page that listed them alongside the tunables would invite
# somebody to try. See _derive() for the arithmetic itself.
_DERIVED = (
    ("MPS_PER_RPM", "\u03c0\u00b7wheel_dia_m / (gear_ratio \u00b7 60)"),
    ("RPM_PER_MPS", "1 / MPS_PER_RPM"),
    ("RAD_S_PER_RPM_DIFF", "MPS_PER_RPM / track_m"),
    ("MAX_SPEED_MPS", "motor_max_rpm \u00b7 MPS_PER_RPM"),
    ("MANUAL_HALF_RPM", "manual.full_rpm \u00b7 manual.half_ratio"),
    ("MANUAL_SPIN_RPM", "manual.full_rpm \u00b7 manual.spin_ratio"),
    ("DT_MIN_S", "0.2 \u00b7 dt_nominal_s"),
    ("DT_MAX_S", "5 \u00b7 dt_nominal_s"),
    ("LINE_LOSS_GRACE_MAX_S",
     "5 \u00b7 line_loss_grace_m / cruise speed - the standstill backstop"),
    ("ACCEL_RPM_S", "drivers.ramp.auto.accel"),
    ("DECEL_RPM_S", "drivers.ramp.auto.decel"),
    ("HORN_HOLD_S", "max(5 \u00b7 loop_period_s, 2 \u00b7 dio.scan_period_s) - "
     "how long a coil command survives unrenewed"),
    ("TPDO1_COB", "0x180 + can.sensor_node"),
    ("LIDAR_SCAN_CYCLE_S",
     "nanoScan3 datasheet - a device constant, not a tunable"),
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
    string, which for rfid.init_hex is the difference between a reader that
    streams and one that never says anything."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.10g}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt(v) for v in value) if value else "(empty list)"
    return value if value else "(empty)"


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


# How fast the vehicle goes, gathered from the three sections that happen to
# hold it, and shown FIRST. Speed is the thing looked up most often and the
# thing most often changed, and it was previously spread across `manual`,
# `autopilot` and `drivers` - three scrolls apart on the page for one question.
#
# Display only. The JSON keeps its existing shape, so these rows carry their
# full dotted path rather than a bare key: this page's other audience is
# somebody about to edit the profile, and "auto_slow_rpm" alone would not say
# which section to put it in.
#
# (section, key) pairs, in the order they should read.
_SPEED_ROWS = [
    ("manual", "full_rpm"),
    ("manual", "half_ratio"),
    ("manual", "spin_ratio"),
    ("autopilot", "auto_rpm"),
    ("autopilot", "auto_rpm_high"),
    ("autopilot", "speed_switch_accel_decel_s"),
    ("autopilot", "auto_slow_rpm"),
    ("drivers", "ramp.manual.accel"),
    ("drivers", "ramp.manual.decel"),
    ("drivers", "ramp.auto.accel"),
    ("drivers", "ramp.auto.decel"),
]

# Everything in _SPEED_ROWS is suppressed where it would otherwise appear, so no
# value is ever printed twice - a page showing one parameter in two places is a
# page where the two can be read as two parameters.
#
# branch_default moves for the same reason and to the same effect: the question
# it answers is "what will the vehicle do at a junction", and that is the RFID
# rules block. Left in autopilot as well it would be the one parameter on the
# page appearing twice, which is exactly what this set exists to prevent.
_MOVED = set(_SPEED_ROWS) | {("autopilot", "branch_default")}

# Section order on the page. Speed first, then the control law, then the
# geometry it runs on; everything after is in schema order. Named here rather
# than by reordering _SCHEMA, because _SCHEMA's order is the profile's order and
# those are two different jobs.
_SECTION_ORDER = ["autopilot", "vehicle"]

# How many kinds of thing an RFID tag is allowed to mean. Two are implemented;
# the rest are named on the page rather than left out, so the budget is visible
# and adding the third is an obvious edit rather than an archaeology exercise.
RFID_RULE_SLOTS = 8


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
        "note": "How fast the vehicle goes, in one place. These keys live in "
                "the manual, autopilot and drivers sections of the JSON - each "
                "row is labelled with the path to edit. auto_slow_rpm applies "
                "only between the entry and exit tags of a junction that asked "
                "for it; high_speed_mode selects auto_rpm_high on permitted route legs."})

    # Every kind of thing a station tag can mean, in slot order, with what is
    # actually loaded under each. Grouped by FUNCTION rather than listed as one
    # flat table because the question this answers is "what will the vehicle do
    # when it reads a tag", and that is decided by which rule owns it.
    #
    # The undefined slots are shown rather than omitted: a page that lists two
    # rules looks complete, and the next person needs to see there is room for
    # six more before they invent a ninth mechanism somewhere else.
    rules = []

    def rule(slot, name, const, loaded, note=None):
        rules.append({
            "key": f"{slot} \u00b7 {name}", "const": const,
            "value": (f"{loaded} rule{'' if loaded == 1 else 's'} loaded"
                      if loaded else "none loaded"),
            "unit": "", "note": note})

    ladder = g["BRANCH_LATCH"]
    rule(1, "branch latch", "BRANCH_LATCH", len(ladder),
         notes.get("branch_latch.*"))
    for r in ladder:
        rules.append({
            "key": f"\u2514 {r['entry_tag']} \u2192 {r['exit_tag']}", "const": "",
            "value": f"branch {r['branch']}"
                     + (" \u00b7 slow zone" if r["slow_speed"] else ""),
            "unit": "", "note": None})
    # The standing default belongs HERE, not only in the autopilot section.
    # This block answers "what will the vehicle do at a junction", and with an
    # empty ladder it would otherwise read "none loaded" - which says the
    # vehicle carries straight on, the one thing it no longer does.
    if g["BRANCH_DEFAULT"] != "straight":
        side = "rightmost" if g["BRANCH_DEFAULT"] == "right" else "leftmost"
        rules.append({
            "key": "\u2514 autopilot.branch_default", "const": "BRANCH_DEFAULT",
            "value": f"take the {side} tape", "unit": "",
            "note": notes.get("autopilot.branch_default")})

    stops = g["STOP_TAGS"]
    rule(2, "stop until start button", "STOP_TAGS", len(stops),
         notes.get("stop_until_start_button.*"))
    for (direction, tag), row in sorted(stops.items()):
        rules.append({"key": f"\u2514 {direction} {tag}", "const": "",
                      "value": f"stop over {row['stop_distance_m']:.2f} m, hold for Start",
                      "unit": "", "note": "Repeated reads suppressed until tag clears."})
    rule(3, "high speed", "HIGH_SPEED_MODE", len(g["HIGH_SPEED_MODE"]))
    for row in g["HIGH_SPEED_MODE"]:
        rules.append({"key": f"\u2514 {row['direction']} {row['entry_tag']} -> {row['exit_tag']}",
                      "const": "", "value": "set / reset high speed", "unit": "", "note": None})
    for n in range(4, RFID_RULE_SLOTS + 1):
        rules.append({"key": f"{n} \u00b7 undefined rule {n - 3}", "const": "",
                      "value": "free slot", "unit": "", "note": None})
    tags = ({t for r in ladder for t in (r["entry_tag"], r["exit_tag"])}
            | {tag for direction, tag in stops}
            | {t for r in g["HIGH_SPEED_MODE"] for t in (r["entry_tag"], r["exit_tag"])})
    out.append({"name": "rfid rules", "rows": rules,
                "note": f"{len(tags)} tag id(s) in use. Rules are direction-qualified; "
                        "physical stations are identified by the ordered route."})
    out.append({"name": "route", "note": "First station is the startup position; state survives manual/Reset.",
                "rows": [{"key": r["id"], "const": "", "unit": "", "note": None,
                          "value": f"{r['direction']} {r['tag']}; "
                                   f"high speed to next: {r['high_speed_to_next']}"}
                         for r in g["ROUTE"]]})

    # Then the schema's own sections: the named ones in the order above, then
    # whatever is left in the order the profile writes it.
    ordered = _SECTION_ORDER + [s for s in _SCHEMA if s not in _SECTION_ORDER]
    for section in ordered:
        fields = _SCHEMA[section]
        rows = [_row(section, key, const, g.get(const), notes)
                for key, (const, _want) in fields.items()
                if (section, key) not in _MOVED]

        # The three things _SCHEMA's flat table cannot express, in the same
        # order the profile writes them.
        if section == "drivers":
            for mode in ("manual", "auto"):
                for k in ("accel", "decel"):
                    key = f"ramp.{mode}.{k}"
                    if (section, key) not in _MOVED:
                        rows.append(ramp_row(section, key))
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
        # TPDO1_COB is a CAN identifier and is unreadable in decimal.
        {"key": const, "const": "", "from": why,
         "value": f"0x{g[const]:03X}" if const == "TPDO1_COB"
                  else _fmt(g[const]),
         "unit": _unit(const), "note": None}
        for const, why in _DERIVED]})
    return out


load()
