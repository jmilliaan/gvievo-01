# /amr/rear/trolley (station call plan 4.4). What the rear lidar says about the hitch, and the rear
# protective field. Reported, never a permission: trolley detection is not personnel protection.
uint8 UNKNOWN=0
uint8 ABSENT=1
uint8 PRESENT=2
uint8 FIELD_UNKNOWN=0
uint8 FIELD_CLEAR=1
uint8 FIELD_VIOLATED=2
uint8 CASE_UNKNOWN=0
uint8 CASE_NO_TROLLEY=1
uint8 CASE_OTHER=2
std_msgs/Header header
uint8 state
uint8 rear_field       # FIELD_CLEAR only with the rear case gate met (plan 3.3)
uint8 rear_case        # CASE_UNKNOWN if the driver does not report it
uint16 roi_points      # beams inside the zone, last scan
string detail          # why UNKNOWN, for the screen
