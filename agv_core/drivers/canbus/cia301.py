"""CiA 301 constants shared by the bus owner and the bench tools. Pure: no bus, no python-can."""

SDO_REQUEST_BASE = 0x600        # client -> server, + node id
SDO_REPLY_BASE = 0x580          # server -> client, + node id
EMCY_COB_BASE = 0x080
HEARTBEAT_COB_BASE = 0x700

# NMT commands (COB-ID 000h, byte 0), and the heartbeat state byte a node reports.
NMT_START = 0x01
NMT_STOP = 0x02
NMT_PREOPERATIONAL = 0x80
NMT_STATE_OPERATIONAL = 0x05

# Bit 31 of a PDO COB-ID entry means "this PDO does not exist". A PDO is reconfigured
# by disabling it, rewriting it, and enabling it again; enabling an addressed one is
# clearing this bit, not writing a new COB-ID.
COB_DISABLED = 1 << 31
COB_MASK = 0x7FF

# Default PDO slots: TPDO n is COB 0x180/0x280/... + node, comm 1800h + (n-1), map 1A00h + (n-1).
TPDO1_COB_BASE, TPDO2_COB_BASE = 0x180, 0x280
TPDO1_COMM, TPDO1_MAP = 0x1800, 0x1A00
TPDO2_COMM, TPDO2_MAP = 0x1801, 0x1A01

# Transmission type 255: asynchronous, event-driven (no SYNC producer on this bus).
TRANSMISSION_ASYNC = 255
