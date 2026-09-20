"""Device drivers for everything that is not on the CAN bus.

Ethernet and GPIO devices: the Modbus I/O island (`modbus_io`), the digital
I/O façade over it (`dio`), the Chafon RFID reader (`rfid`) and the nanoScan3
scan decoder (`lidar_scan`, decode only — the live UDP socket belongs to
`sick_safetyscanners2` on the ROS side).

CAN-bus devices live one level down, in `agv_core.drivers.canbus`.
"""
