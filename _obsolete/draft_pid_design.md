# AGV Motion Control Architecture — Handoff Brief

**Audience:** control software agent running on the AGV onboard IPC, with access to motor drivers, sensors, and the control loop.
**Scope:** velocity command generation, acceleration profiling, and line-following PID for a differential-drive tow tractor.

---

## 1. System

| Item | Specification |
|---|---|
| Configuration | Differential drive, two driven wheels, tow-tractor type |
| Motors | BLV-series brushless DC gearmotor, 400 W, 1.27 Nm rated, one per side |
| Gearbox | 30:1 |
| Drive wheel diameter | 180 mm |
| Driver configuration | MEXE02 |
| Navigation | Line following; line sensor provides cross-track error |
| Control host | Onboard Ubuntu IPC, Python control loop |
| Operating surface | Painted concrete, oil contamination expected |

---

## 2. Control Law

```
v_left  = v_default + pid_output - error_cons
v_right = v_default - pid_output - error_cons
```

| Term | Role | Mode |
|---|---|---|
| `v_default` | Base forward speed, shaped by a software acceleration/deceleration profile | Common |
| `pid_output` | Heading correction derived from line-sensor cross-track error | Differential |
| `error_cons` | Forward speed reduction proportional to error | Common |

Each term addresses a separate control objective. They are not interchangeable and none is redundant.

---

## 3. Acceleration Handling

### 3.1 Where the profile lives

Acceleration and deceleration are generated **in software**, by ramping `v_default`.

The BLV driver acceleration and deceleration time parameters are set to **minimum** in MEXE02. The drivers therefore track the commanded speed as directly as possible, and the actual motion profile is determined by the software ramp rather than by driver-internal smoothing.

### 3.2 Profile shape

Use an **S-curve (jerk-limited)** profile. Do not use trapezoidal.

- A trapezoidal profile produces a torque discontinuity at each corner of the ramp. That transient can break drive-wheel traction even when the steady-state torque demand is comfortably within available grip.
- Jerk limiting also reduces snatch in the towed trolley train and suppresses cart oscillation.

### 3.3 Acceleration limits are a physical constraint

The drivetrain can command torque transients that exceed available wheel traction. The acceleration limit must be set below the measured breakaway threshold, with margin for degraded floor conditions.

| Rule | Detail |
|---|---|
| Set the limit from measurement | Derive it from the tested breakaway threshold, not from desired cycle time |
| Allow margin for contamination | Oil on painted concrete substantially reduces the available friction coefficient relative to clean floor |
| Re-verify before raising | Do not increase the acceleration limit to improve throughput without re-testing traction on the worst-case surface |
| Account for towed load | Acceleration capability differs substantially between an unladen AGV and one towing a loaded train |

For the towed-load case, either set the limit conservatively for the worst case, or schedule the limit against a load estimate derived from motor current.

---

## 4. PID

### 4.1 Separation of concerns

PID governs **tracking quality**. It does not govern the acceleration profile. These are independent:

| Layer | Decides |
|---|---|
| Profile generator | *What* speed is demanded, and how fast the demand changes |
| PID | *How closely* the machine follows that demand |

**Do not detune PID as a means of limiting acceleration.** Doing so makes acceleration an uncontrolled emergent property of loop dynamics — it varies with load, becomes non-repeatable across runs, and degrades disturbance rejection at the same time.

The correct combination is a **rate-limited setpoint with a tightly tuned loop**: enforce acceleration limits in the profile, and tune PID as tightly as stability allows underneath it.

### 4.2 Implementation requirements

| Item | Requirement |
|---|---|
| Integral windup | Clamp the integral term, or freeze integration while either wheel command is saturated. This is the most common failure mode in this architecture |
| Derivative noise | The line sensor output is quantised. Filter the derivative term, or use derivative-on-measurement instead of derivative-on-error |
| Loop timing | Use a fixed-rate loop, or compute the integral and derivative terms from measured `dt`. Python loop jitter will otherwise scale both terms incorrectly |
| Saturation | Compute both wheel commands first, then scale both together if either exceeds limits. Clipping one wheel independently alters the effective turn ratio |
| Reverse travel | The sign of the PID correction inverts when driving backwards. Handle this explicitly |
| Output rate | `pid_output` is summed onto `v_default` and is **not** rate-limited by the profile generator. Because driver acceleration is set to minimum, a large step in PID output produces a fast torque step at the wheel |

On the last point: if motor current spikes toward the breakaway threshold during aggressive corrections under load, either rate-limit the PID output or reduce the derivative gain.

### 4.3 Gain scheduling

The relationship between wheel-speed differential and resulting turn rate depends on forward speed. Gains tuned at one speed will be sluggish or oscillatory at another.

| Approach | When to use |
|---|---|
| Single gain set | Acceptable if the operating speed range is narrow |
| Scale gains inversely with `v_default` | Simple and usually sufficient |
| Express correction as a ratio of `v_default` rather than an absolute increment | Scales naturally; often the cleanest solution |

Relevant if the AGV runs meaningfully different speeds for aisle travel versus station approach.

---

## 5. error_cons

`error_cons` reduces forward speed as a function of cross-track error. **It is not redundant with a well-tuned PID and should not be omitted.**

### 5.1 Why it is required

| Reason | Explanation |
|---|---|
| PID cannot slow the vehicle | PID output is symmetric — it raises one wheel and lowers the other, leaving net forward speed unchanged. It steers but does not decelerate. On a tight curve or large deviation, reduced forward speed is a distinct objective needing its own term |
| Saturation headroom | When `v_default` is near maximum and PID demands a large correction, the outer wheel command clips at the driver limit. Turn response becomes nonlinear precisely when the largest correction is needed. Reducing base speed restores control authority |

### 5.2 Refinements

- Act on both error magnitude **and** error rate, so speed reduction begins on approach to a curve rather than after deviation has already developed.
- Apply a lower bound on the resulting speed, so a transient sensor fault cannot drive the command to zero and stall the vehicle mid-path.

---

## 6. Forward Compatibility

This control law is specific to line following, where the sensor supplies cross-track error directly. It does not carry over to SLAM-based navigation, which requires a pose controller producing a (linear velocity, angular velocity) pair, converted to wheel speeds through the differential-drive kinematic model.

**Keep the wheel-speed conversion isolated in its own function**, so the upper control layer can be replaced without modifying the motor interface.

---

## 7. Summary of Non-Negotiables

1. Acceleration is shaped by ramping `v_default` in software; driver accel/decel parameters stay at minimum.
2. The profile is S-curve, not trapezoidal.
3. The acceleration limit is set from measured traction, with margin for a contaminated floor.
4. PID is tuned for tracking, never detuned to limit acceleration.
5. Integral windup protection and joint (not independent) wheel-command saturation are mandatory.
6. `error_cons` stays in the control law.
