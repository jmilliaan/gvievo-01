"""Device drivers for everything that is not on the CAN bus.

Ethernet devices: the digital I/O island (`dio`, Modbus TCP). The legacy
`modbus_io` and `lidar_scan` modules went with the legacy controller (U11,
2026-09-21): the nanoScan3 is `sick_safetyscanners2` on the ROS side.

CAN-bus devices live one level down, in `agv_core.drivers.canbus`.
"""
