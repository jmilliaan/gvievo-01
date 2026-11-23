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
# Manual Arm. gvievo-ce (kyb unit): there is no arm input; true whenever the panel image is
# valid, so MANUAL is always armed unless an emergency. False when invalid.
bool manual_arm
# Start and Reset as debounced LEVELS (2026-11-11). APPEND ONLY. Held = true. Motion still enters on
# the edges above alone; these only let the line layer see Start + Reset held together for 1 s
# under MANUAL, its At home (amr_line.home_combo). False while invalid.
bool start_held
bool reset_held
# Emergency (emergency-suite plan Part B, 2026-11-16; contract as kyb-trackless). APPEND ONLY.
# estop_ok: the E-stop signal NOT active. DI09 (panel.di_estop, Flexi Soft Q3), HIGH = E-stop
# pressed (panel.estop_active_high, owner 2026-11-16), filtered by the adapter (active over
# panel.estop_confirm_scans); held as it was while the image is invalid or stale - a DIO gap is
# never an E-stop. Informational: STO is the Flexi Soft's, in hardware. emergency: amr_base/emergency.py.
uint8 EMG_NORMAL=0         # clear. Reaching it grants no motion: Start (AUTO) or the lease (MANUAL)
uint8 EMG_ACTIVE=1         # E-stop signal active: release the E-stop, press Reset
uint8 EMG_RESET_NEEDED=2   # signal clear again but not reset yet: press Reset
uint8 EMG_RESETTING=3      # Reset pressed with the signal clear; waiting for the drives to leave STO
uint8 EMG_RESET_FAILED=4   # the Reset did not take within panel.estop_reset_timeout_s
bool estop_ok
uint8 emergency
