# CiA-402 state of both drives, drive node -> diagnostics/mission (spec §2.1 /drives/status, 10 Hz).
std_msgs/Header header
uint16 left_statusword
uint16 right_statusword
uint16 left_error_code
uint16 right_error_code
string left_state
string right_state
bool operational
# Drive power (2026-10-08). link_state: disarmed | standby | armed | fault. Standby = CANopen
# up and feedback flowing, power stage off. power_reason: why power is or is not wanted
# (amr_base/arm_policy), for the operator.
string link_state
bool power_wanted
string power_reason
# Drive fault (unified plan WP-B4, 2026-11-16). fault_code: the agv_core/alarms.py catalogue code
# of a latched link FAULT, chosen by amr_base.canopen.decide() (DRIVE_SILENT, DRIVE_FAULT,
# CAN_TX_FAILED), or DRIVE_FAULT while not linked because preflight found a drive in fault;
# "" = none. fault_detail: side-labelled ("left: ...; right: ..."), with each drive's alarm
# history as preflight read it (603Fh last alarm, survives a power cycle; 1003h error list).
string fault_code
string fault_detail
# Motion lamp (unified plan WP-C7, cpu-load plan C#15, 2026-11-16): either motor turning faster than
# the feedback noise floor (amr_base.panel_io.wheels_turning on the same feedback as /wheel_states).
# panel_node's dio.motion_on outputs follow it instead of the 41 Hz /wheel_states.
bool turning
# Bus (main supply) voltage per drive (unified plan WP-P7, H-P2-6, 2026-11-16): drive_node's monitor
# reading of 40A4h (agv_core.canmon, about once a sweep), V. NaN = not read (monitor off, no answer yet).
# amr_line refuses a NEW run at or below monitor.bus_v_trip_low (canmon.supply_refusal). APPEND ONLY.
float32 left_bus_v
float32 right_bus_v
