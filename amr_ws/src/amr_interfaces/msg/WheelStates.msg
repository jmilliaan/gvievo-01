# Wheel feedback, drive node -> diff_drive_odom (spec §2.1 /wheel_states, 100 Hz).
# Position from 6064h, velocity from 606Ch, read from the drives themselves (D-2).
std_msgs/Header header
float64 left_pos_rad
float64 right_pos_rad
float64 left_vel_rad_s
float64 right_vel_rad_s
bool left_valid
bool right_valid
