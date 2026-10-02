# The Manual page's button panel, web -> panel_node (20 Hz, held not latched).
# Levels, exactly as the physical contacts would read: panel_node debounces them
# and makes the edges. Older than 0.5 s = not there (web buttons: no panel image).
std_msgs/Header header
bool start            # momentary, held for one pulse per click
bool reset            # momentary, held for one pulse per click
bool mode_auto        # selector: true = AUTO, false = MANUAL
bool estop            # E-stop pressed (latching, until released on the page)
