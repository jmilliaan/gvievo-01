# Operator panel image, debounced (core/panel.PanelScan semantics): the DIO adapter
# (T12) or fake_panel_node in sim. Stale (> 0.2 s) means no motion permission.
std_msgs/Header header
bool valid            # a trusted, debounced image exists
bool mode_auto        # selector: true = AUTO, false = MANUAL  ("auto" is a C++ keyword)
bool start_edge       # rising edge of Start on THIS message
bool reset_edge       # rising edge of Reset on THIS message
uint32 seq            # increments per scan, so edges are never missed by a slow consumer
# Jog pendant (core/panel.pendant_intent): direction levels, an opposing pair
# cancelled. Levels, not edges: held = keep moving.
bool pendant_fwd
bool pendant_rvs
bool pendant_left
bool pendant_right
# Pendant enable / arm (panel.di_manual_arm, DI09 on MCQ4-4), debounced level. In either
# mode the drives are powered only while this is true (amr_base/arm_policy). False when invalid.
bool manual_arm
# Emergency (emergency-suite plan, 2026-10-30). estop_ok: DI08 (panel.di_estop_ok, Flexi Soft
# Q3), HIGH = no emergency; False while the image is invalid or stale (fail-safe). The PC's
# picture only: STO is the Flexi Soft's, in hardware. emergency: amr_base/emergency.py.
uint8 EMG_NORMAL=0         # clear; a run that was stopped by it has been aborted
uint8 EMG_ACTIVE=1         # DI08 LOW (or panel invalid/stale): release the E-stop, press Reset
uint8 EMG_RESET_NEEDED=2   # DI08 HIGH again but not reset yet: press Reset
uint8 EMG_RESETTING=3      # Reset pressed with DI08 HIGH; waiting for the drives to leave STO
uint8 EMG_RESET_FAILED=4   # the Reset did not take within panel.estop_reset_timeout_s
bool estop_ok
uint8 emergency
