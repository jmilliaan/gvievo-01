# Motion permission lease from the coordinator (route executor), 10 Hz (spec §2.1).
# The mux accepts a command only if its source matches and this message was
# received less than 0.3 s ago. No permit, or an expired one, means zero output.
uint8 NONE=0
uint8 TELEOP=1      # manual jog, only while the panel selector is MANUAL
uint8 FOLLOW=2      # controller_server output on /cmd_vel during a straight
uint8 ROTATE=3      # behavior_server output on /cmd_vel_rotate during a turn

std_msgs/Header header
string run_id
uint8 source
bool enabled
string reason
