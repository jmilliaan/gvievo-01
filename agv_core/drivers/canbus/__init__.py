"""CANopen layer: the SDO client, CiA 301/402 words, frame decoders, the write
deny-list and bench utilities.

`sdo` (SDO client, NMT, bus opening, the guarded bench write), `cia301`, `cia402`,
`guard`, `alarms` and `rpdo` are libraries - the bus owner (`amr_base.canopen`)
imports them. Nothing here imports a bench script.

`verify_bus`, `verify_drivers`, `bus_health`, `drive_forward`, `read_imu`,
`read_mls` and `lss` are bench tools, runnable against a live can0:

    python3 -m agv_core.drivers.canbus.verify_drivers

Run them with `-m` from the repo root, not as a bare file path. As plain
scripts only their own directory lands on sys.path, and the `agv_core.` imports
they now use would not resolve.
"""
