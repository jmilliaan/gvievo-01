"""The QoS profiles every node uses, defined once.

A publisher and a subscriber that disagree on reliability or durability never
connect, and LeanNode suppresses the incompatible-QoS log, so a copy that drifts
fails silently. test_qos.py pins each profile.

  SENSOR_DATA   streams where only the newest sample matters (scan, wheels, imu,
                line track, the _ui copies): depth 5, best effort, volatile
  RELIABLE_1    commands and state that a late joiner need not see: depth 1,
                reliable, volatile
  LATCHED       state a late joiner must get at once (mode, lease, panel, run
                state): depth 1, reliable, transient local
  EVENT_STREAM  every message counts and none may be dropped behind a newer one
                (RFID encounters, MLS markers, operator events): depth 50,
                reliable, volatile
"""

from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy

SENSOR_DATA = QoSProfile(
    depth=5, reliability=QoSReliabilityPolicy.BEST_EFFORT, durability=QoSDurabilityPolicy.VOLATILE
)
RELIABLE_1 = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.VOLATILE
)
LATCHED = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.TRANSIENT_LOCAL
)
EVENT_STREAM = QoSProfile(
    depth=50, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.VOLATILE
)
