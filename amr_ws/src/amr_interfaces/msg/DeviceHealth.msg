# /amr/device_health (unified plan WP-H1, hardening plan H-P1-1 / section 3): one device's link,
# published by its owner at 2 Hz and on every edge. Reporting only: nothing reads it to decide
# about motion. Enforcement stays in the gate, drive_node, the job and the executor.
# The decisions are agv_core/health.py's; the name tables are amr_base/wire.py's
# (HEALTH_DEVICE_NAMES, HEALTH_STATE_NAMES). APPEND ONLY.
#
# Owners: drive_node (drive_left, drive_right, can_bus, mls_track, mls_gyro), panel_node (dio),
# trolley_node (rear_scanner), station_bridge (station_link). A device the profile does not fit
# is ABSENT, never LOST; a consumer that stops hearing a fitted device's owner shows it LOST.
uint8 DEVICE_DRIVE_LEFT=0
uint8 DEVICE_DRIVE_RIGHT=1
uint8 DEVICE_CAN_BUS=2
uint8 DEVICE_MLS_TRACK=3
uint8 DEVICE_MLS_GYRO=4
uint8 DEVICE_DIO=5
uint8 DEVICE_REAR_SCANNER=6
uint8 DEVICE_STATION_LINK=7
uint8 ABSENT=0          # not fitted, or not seen yet inside the owner's boot grace
uint8 OK=1              # fresh and plausible
uint8 DEGRADED=2        # fresh but reduced (SDO fallback, scans retried, TX errors)
uint8 STALE=3           # older than its stale limit
uint8 FROZEN=4          # arriving but implausible (a repeated scan)
uint8 LOST=5            # older than its lost limit, or the transport is down
uint8 RECONNECTING=6    # re-init in progress (probing, relinking, subscribing)
std_msgs/Header header
uint8 device
uint8 state
string code             # agv_core/alarms.py catalogue key; empty while OK or ABSENT
float32 age_s           # age of the device's newest data; -1 = none
float32 since_s         # how long in this state
uint32 gaps             # device-specific counters, see agv_core/health.py
uint32 rejects
uint32 reconnects
uint32 timeouts
string detail           # for the engineer; no consumer parses it
