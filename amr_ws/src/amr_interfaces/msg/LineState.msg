# Line-follow layer state (dual-product plan, Increment 1), published by
# line_follow_node on /amr/line_state on change and at 1 Hz.
#
# *** The first four state values are load-bearing. *** readiness.py holds
# _line_active_locked as `line_state in (1, 2, 3)`, which feeds
# mode_fsm.Conditions.line_active and therefore the admit() rule that refuses
# to leave LINE while the follower is armed or running. ARMED/RUNNING/HOLD must
# be exactly 1..3: renumber them and leaving LINE mode is either wrongly
# refused, or wrongly ALLOWED while the vehicle is still moving. Append only.
uint8 IDLE=0            # layer up, not armed; safe to swap the layer out
uint8 ARMED=1           # armed and waiting for a physical Start edge
uint8 RUNNING=2         # following tape
uint8 HOLD=3            # stopped, progress retained; see hold_cause
uint8 DONE=4            # run finished or stopped itself; Reset clears
uint8 FAULT=5           # sensor/drive/authority fault; acknowledgement does not resume

std_msgs/Header header
uint32 generation           # layer generation that produced this; consumers drop other generations
uint8 state

# Why the follower is not driving. HOLD only: field | estop | drives | track |
# rate | authority | pending. Shares the vocabulary of RunState.hold_cause so
# both products explain a stop the same way.
string hold_cause
bool auto_resume            # HOLD and this hold clears by itself once the cause does

# What the engine is doing, straight out of the follower's diagnostic row.
string engine_state         # idle | halted | sensor_lost | coast | line_lost | run | stopping
bool has_track
float64 error_mm            # lateral error the PID acted on; 0 with no track
float64 v_mps               # commanded body speed
float64 omega_rad_s         # commanded yaw rate
float64 followed_m          # distance travelled this run

# Sensor health, the two numbers R1 says to record on the vehicle. track_hz is
# a RATE gate, not a staleness gate: the SDO fallback measured 9.8 Hz against a
# 50 Hz PID, and every staleness check ever written passes that.
float32 track_hz
float32 sample_age_s
string track_source         # "tpdo" (control-rate) | "sdo" (polled, monitor only)

string message              # last result / block reason, for the operator
