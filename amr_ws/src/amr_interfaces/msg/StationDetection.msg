# RFID tag encounters from rfid_node on /amr/rfid (2026-10-02; replaces the spec's
# QrDetection, reconciliation D-4). An RFID read means "somewhere in the antenna's
# read zone": identity, not pose.
#
# Two kinds of message on ONE topic, so their order is the publisher's order:
#   heartbeat=false  one per DISTINCT pass of a tag (agv_core.drivers.rfid encounter
#                    stream): rfid_tag + encounter_seq. A consumer processes each
#                    exactly once; a gap in encounter_seq is a buffer overrun.
#   heartbeat=true   2 Hz link status: comms_ok, the latest encounter_seq, generation.
# A change of generation is a reconnect: anything read across it is not continuous.
std_msgs/Header header
string rfid_tag          # 4 hex chars, same convention as the mission's tag tables
string station_id        # unused (no stations.yaml); kept for wire compatibility
bool known
# Appended 2026-10-02. APPEND ONLY.
bool heartbeat
uint64 encounter_seq
uint32 generation
bool comms_ok
float32 rx_age_s         # since any byte from the reader; -1 = never
float32 tag_age_s        # since the last tag read; -1 = never
