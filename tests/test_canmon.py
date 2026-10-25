"""CAN monitoring: alarm decode, the write deny-list, the SDO poller."""
import struct

from helpers import ROOT, _why, check

from agv_core import config


def test_can_monitoring():
    """Alarm decode, the write deny-list, and the round-robin poller.

    All pure tables and bookkeeping, so all testable without a bus. The wiring
    that puts them on the bus is checked in the two tests below.
    """
    from agv_core import canmon
    from agv_core.drivers.canbus import alarms, guard
    print("\nCAN monitoring: alarms, deny-list, poller")

    # -- EMCY decode -------------------------------------------------------
    a = alarms.decode_emcy(bytes([0x53, 0xFF, 0x81, 0, 0, 0, 0, 0]))
    check("the top-priority HWTO alarm decodes",
          a["name"] == "HWTO input circuit error" and a["level"] == "error"
          and a["tier"] == alarms.MUST, a["name"])
    check("the error register is decoded from byte 2",
          a["register_bits"] == ["generic", "manufacturer"],
          str(a["register_bits"]))
    # 0000h is the drive saying everything cleared, not a fault.
    clr = alarms.decode_emcy(bytes(8))
    check("0000h is a clear, not an alarm",
          clr["cleared"] and clr["level"] == "info")
    unk = alarms.decode_emcy(bytes([0x99, 0x99, 0, 0, 0, 0, 0, 0]))
    check("an unlisted code still reports as an error",
          not unk["cleared"] and unk["level"] == "error"
          and "9999" in unk["hex"], unk["name"])
    check("a short frame decodes rather than raising",
          alarms.decode_emcy(b"\x22\xff")["code"] == 0xFF22)
    check("decode_emcy never raises on random bytes",
          all(alarms.decode_emcy(bytes([i, i, i])) for i in range(0, 256, 17)))
    missing = [c for c in (0xFF53, 0xFF68, 0xFF50, 0xFF55, 0xFF22, 0xFF25,
                           0xFF21, 0xFF26, 0x8120, 0x8130, 0x8140, 0xFF31,
                           0xFF45, 0xFF41, 0xFFF0)
               if c not in alarms.EMCY_CODES]
    check("every MUST alarm from the plan is in the table", not missing,
          f"{len(alarms.EMCY_CODES)} codes"
          + (f", missing {[hex(c) for c in missing]}" if missing else ""))

    check("NMT state decodes from the heartbeat byte",
          alarms.decode_nmt(0x05) == "Operational"
          and alarms.decode_nmt(0x7F) == "Pre-operational")

    # -- the write deny-list (monitoring plan section 8) --------------------
    check("the setpoint is writable", guard.is_allowed(0x60FF, 800))
    check("the controlword is writable", guard.is_allowed(0x6040, 0x000F))
    check("the heartbeat interval is writable", guard.is_allowed(0x1017, 200))
    # 403Eh bit 6 is FREE: it releases the holding brake on BOTH drive wheels.
    check("403Eh (FREE / brake release) is refused",
          not guard.is_allowed(0x403E, 0x40))
    check("40D0h (clear ETO / automatic restart) is refused",
          not guard.is_allowed(0x40D0, 1))
    check("40C0h (alarm reset) is refused", not guard.is_allowed(0x40C0, 1))
    check("1011h (restore defaults) is refused", not guard.is_allowed(0x1011, 1))
    check("1010h (store parameters) is refused", not guard.is_allowed(0x1010, 1))
    check("the whole 4xxxh parameter block is refused",
          not any(guard.is_allowed(i) for i in (0x4000, 0x40C6, 0x4123, 0x4FFF)))
    # 6040h is allowed, but bit 7 of it is fault reset by another name.
    check("controlword bit 7 (fault reset) is refused",
          not guard.is_allowed(0x6040, 0x0080))
    check("a refusal explains itself", "FREE" in _why(guard, 0x403E),
          _why(guard, 0x403E)[:60])
    check("an unlisted index is refused by default",
          not guard.is_allowed(0x1000, 1))

    # -- PDO configuration -------------------------------------------------
    # An RPDO mapping is a WRITE PATH: map a forbidden object into one and a
    # plain CAN frame does what a direct SDO write is refused. So the mapping
    # ranges are admitted by rule, and the deny-list is applied recursively to
    # the object each entry names.
    MAP_60FF = (0x60FF << 16) | 0x0020        # target velocity, 32 bits
    MAP_6040 = (0x6040 << 16) | 0x0010        # controlword, 16 bits
    MAP_403E = (0x403E << 16) | 0x0010        # FREE / brake release
    check("an RPDO may map the setpoint",
          guard.is_allowed(0x1600, MAP_60FF, sub=1))
    check("an RPDO may map the controlword",
          guard.is_allowed(0x1600, MAP_6040, sub=1))
    check("*** an RPDO may NOT map 403Eh behind the deny-list ***",
          not guard.is_allowed(0x1600, MAP_403E, sub=1))
    check("the smuggled object is named in the refusal",
          "403E" in _why(guard, 0x1600, MAP_403E, sub=1),
          _why(guard, 0x1600, MAP_403E, sub=1)[:70])
    check("no 4xxxh parameter can be mapped into an RPDO",
          not any(guard.is_allowed(0x1600, (i << 16) | 0x0010, sub=1)
                  for i in (0x4000, 0x40C0, 0x40D0, 0x40C6, 0x4FFF)))
    check("sub 0 is the entry count, not an object reference",
          guard.is_allowed(0x1600, 2, sub=0))
    check("an empty mapping slot maps nothing and is permitted",
          guard.is_allowed(0x1600, 0, sub=3))
    check("an RPDO mapping without a subindex is refused, not guessed",
          not guard.is_allowed(0x1600, MAP_60FF))
    # A TPDO is a READ path - the device transmits. Refusing these would forbid
    # reading a temperature by PDO while permitting it by SDO.
    check("a TPDO may map any object, including a forbidden one",
          guard.is_allowed(0x1A00, MAP_403E, sub=1)
          and guard.is_allowed(0x1A03, (0x2034 << 16) | 0x0010, sub=1))
    check("PDO communication parameters are writable",
          all(guard.is_allowed(i, 0x40000180, sub=1)
              for i in (0x1400, 0x1800, 0x1803, 0x1806)))
    check("the PDO ranges stop where CiA 301 says they do",
          not any(guard.is_allowed(i) for i in (0x13FF, 0x1C00)))

    # The line sensor's own list (mls-marker-plan, 2026-10-09): exactly these, and no
    # store, factory reset, offset calibration, zero teach or inversion.
    check("the MLS write list is exactly variant, markers, polarity, teach lock, event reset "
          "and the four IMU TPDO COB-IDs",
          set(guard.SENSOR_ALLOWED) == {(0x2006, 1), (0x2028, 1), (0x2028, 2), (0x2028, 3),
                                        (0x202D, 5), (0x2029, 0), (0x2080, 1),
                                        (0x1803, 1), (0x1804, 1), (0x1805, 1), (0x1806, 1)})
    check("the MLS list refuses the IMU TPDO mappings and every other IMU TPDO sub-index",
          not any(guard.is_sensor_allowed(i, s) for i in (0x1803, 0x1806, 0x1A03, 0x1A06)
                  for s in (0, 2, 3, 5)))
    check("the MLS list refuses store, defaults, offset calibration, zero teach, inversion",
          not any(guard.is_sensor_allowed(i, s) for i, s in
                  ((0x1010, 1), (0x1011, 1), (0x202A, 0), (0x202B, 0), (0x202C, 0),
                   (0x2027, 0), (0x2025, 0), (0x2026, 0), (0x202D, 1), (0x2006, 2),
                   (0x2070, 6), (0x2070, 7), (0x2080, 2))))
    # The IMU TPDO COB-IDs are PDO comm params, which the drive list admits by rule
    # anyway; every manufacturer object on the MLS list stays off the drive list.
    check("the MLS list makes no drive object writable, and the drive list none of its 2xxxh objects",
          not any(guard.is_sensor_allowed(i, 0) for i in guard.ALLOWED)
          and not any(guard.is_allowed(i) for i, _ in guard.SENSOR_ALLOWED if 0x2000 <= i <= 0x2FFF))
    check("FREE (403Eh) stays refused on both lists",
          not guard.is_allowed(0x403E, 0) and not guard.is_sensor_allowed(0x403E, 0)
          and not guard.is_sensor_allowed(0x403E, 1))

    # Every bench write goes through sdo.guarded_sdo_write. A raw sdo_write( call in
    # canbus/ is allowed only inside that helper, and rpdo.configure's injected
    # writer (its steps pass guard.check_steps before the first frame).
    import io
    import tokenize
    raw = []
    for path in sorted((ROOT / "agv_core/drivers/canbus").glob("*.py")):
        toks = [t for t in tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
                if t.type in (tokenize.NAME, tokenize.OP)]
        for prev, tok, nxt in zip(toks, toks[1:], toks[2:], strict=False):
            if tok.string == "sdo_write" and nxt.string == "(" and prev.string != "def":
                raw.append(f"{path.name}:{tok.start[0]}")
    allowed_raw = {"sdo.py", "rpdo.py"}
    check("no raw sdo_write( outside sdo.guarded_sdo_write (and rpdo's injected writer)",
          {r.split(":")[0] for r in raw} <= allowed_raw and len(raw) == 2, ", ".join(raw))

    from agv_core.drivers.canbus import sdo

    class _NoBus:
        sent = []

        def recv(self, timeout=None):
            return None

        def send(self, m):
            self.sent.append(m)

    nb = _NoBus()
    ok_free, why_free = sdo.guarded_sdo_write(nb, 1, 0x403E, 0, 1 << 6, 2)
    ok_imu, _ = sdo.guarded_sdo_write(nb, 10, 0x1A06, 1, 0, 4, sensor=True)
    check("the bench guard refuses FREE and an IMU mapping write before a frame is sent",
          not ok_free and not ok_imu and "403E" in why_free and nb.sent == [], why_free[:80])

    # Every write by the bus owner (amr_base.canopen since U11 retired canworker)
    # must go through the guard, not around it. _raw_write is the shutdown path,
    # where raising would leave the motors energised: 6040h/60FFh only, and the
    # call count is pinned so a new bypass cannot slip in unnoticed.
    co = (ROOT / "amr_ws/src/amr_base/amr_base/canopen.py").read_text(encoding="utf-8")
    check("DriveLink.write() calls the guard", "guard.check(index, value, sub)" in co)
    # The one runtime MLS write (2080h:01, mls-diagnostics-plan E2) has its own method,
    # on the line-sensor list, never the drives'.
    check("DriveLink.write_sensor() calls the line-sensor guard", "guard.check_sensor(index, sub)" in co)
    direct = [ln.strip() for ln in co.splitlines()
              if "_raw_write(" in ln and "def " not in ln
              and not ln.strip().startswith(("#", "*", '"'))]
    check("raw writes are only the disarm path",
          len(direct) == 2, f"{len(direct)}: " + "; ".join(direct)[:110])
    check("no raw write targets a forbidden index",
          not any(f"0x{i:04X}" in "".join(direct) for i in guard.FORBIDDEN))

    # -- round-robin poller -------------------------------------------------
    pol = canmon.MonitorPoller([1, 2])
    seen = [pol.next_object()[1] for _ in range(len(canmon.OBJECTS))]
    check("a sweep visits every object exactly once",
          sorted(seen) == sorted(o[1] for o in canmon.OBJECTS),
          f"{len(seen)} objects")
    check("the cursor wraps and counts sweeps", pol.sweeps == 1)

    # Types come from the MANUAL, not the plan - the plan guessed 40A4h as
    # INT32 when it is INT16, and a 16-bit signed value read as 32-bit is
    # plausible-looking garbage rather than an error.
    check("40A4h is decoded as INT16 per the manual",
          canmon.OBJECT_BY_KEY["bus_v"][3] == "i16")
    check("409Bh is decoded as INT32 per the manual",
          canmon.OBJECT_BY_KEY["cur_a"][3] == "i32")
    check("a negative current decodes as regeneration",
          canmon._decode("i32", struct.pack("<i", -2500)) == -2500)
    check("an i16 sign bit is honoured",
          canmon._decode("i16", struct.pack("<h", -55)) == -55)
    check("a short payload decodes rather than raising",
          canmon._decode("i32", b"\x01") == 1)
    check("a None payload yields None", canmon._decode("i16", None) is None)
    check("decode_int gives an unsigned read its object's width and sign",
          canmon.decode_int("i16", 0xFFC9) == -55 and canmon.decode_int("i32", 0xFFFFF63C) == -2500
          and canmon.decode_int("u8", 0x1FF) == 0xFF and canmon.decode_int("i16", None) is None)

    # step(): the diagnostic slot is bounded (one SDO per call, U7) and a timeout
    # is stored as None, never a plausible number.
    stepper = canmon.MonitorPoller({1: "left", 2: "right"}, objects=canmon.OBJECTS[:2])
    calls = []

    def read(nid, idx):
        calls.append((nid, idx))
        return None if nid == 2 else 0x01F4  # right drive times out; 500 raw -> 50.0 V

    out = [stepper.step(read) for _ in range(4)]
    check("step reads one object per call, alternating nodes, the object fixed for a node sweep",
          [c[0] for c in calls] == [1, 2, 1, 2]
          and calls[0][1] == calls[1][1] == canmon.OBJECTS[0][0] and calls[2][1] == canmon.OBJECTS[1][0],
          str(calls))
    snap = stepper.snapshot({})["nodes"]
    check("a timeout is stored as None and counted apart from the reads",
          out[0][2] == 500 and out[1][2] is None and snap["1"]["bus_v"]["value"] == 50.0
          and snap["2"]["bus_v"]["value"] is None and (stepper.reads, stepper.timeouts) == (4, 2))

    pol.store(1, "bus_v", 482)
    pol.store(1, "drv_c", 723)
    pol.store(1, "mtr_c", 400)
    pol.store(2, "bus_v", 375)
    snap = pol.snapshot(config.MONITOR_THRESHOLDS)
    check("a raw reading is scaled to its unit",
          snap["nodes"]["1"]["bus_v"]["value"] == 48.2,
          str(snap["nodes"]["1"]["bus_v"]["value"]))
    check("a temperature over its warn threshold is flagged",
          snap["nodes"]["1"]["drv_c"]["state"] == "warn")
    check("a temperature under its warn threshold is not",
          snap["nodes"]["1"]["mtr_c"]["state"] == "ok")
    # Two-sided: low bus voltage is battery sag, and stopping distance was
    # already degraded before anything alarmed.
    check("bus voltage is flagged at the LOW end too",
          snap["nodes"]["2"]["bus_v"]["state"] == "warn",
          str(snap["nodes"]["2"]["bus_v"]["value"]))
    pol.store(1, "info", None)
    check("an unanswered read stores as blank, not zero",
          pol.snapshot()["nodes"]["1"]["info"]["value"] is None)


def test_cia_tables_and_preflight():
    """The CiA 301/402 words the bus owner and the bench share, and the one
    preflight verdict both print (lean plan D41/D43)."""
    from agv_core.drivers.canbus import cia301, cia402, drive_forward, rpdo
    print("\nCiA 301/402: shared words, one enable sequence, one preflight")

    check("CiA 402 words: Operation enabled 000Fh, state mask 6Fh/27h, pp 1, pv 3",
          cia402.CW_OPERATION_ENABLED == 0x000F == cia402.CW_ENABLE == rpdo.CW_OPERATION_ENABLED
          and (cia402.OPERATION_ENABLED_MASK, cia402.OPERATION_ENABLED) == (0x6F, 0x27)
          and (cia402.MODE_PP, cia402.MODE_PV) == (1, 3)
          and cia402.is_operation_enabled(0x0627) and not cia402.is_operation_enabled(0x0621)
          and not cia402.is_operation_enabled(None))
    check("CiA 301 words: COB disabled bit 31, async 255, NMT start 01h / pre-op 80h",
          cia301.COB_DISABLED == 1 << 31 == rpdo.COB_DISABLED and cia301.TRANSMISSION_ASYNC == 255
          and (cia301.NMT_START, cia301.NMT_PREOPERATIONAL) == (0x01, 0x80))
    check("the bench and the bus owner share one enable sequence: 06h, 07h, 0Fh",
          drive_forward.ENABLE_SEQUENCE is cia402.ENABLE_SEQUENCE
          and [cw for cw, _ in cia402.ENABLE_SEQUENCE] == [0x06, 0x07, 0x0F])

    healthy = {0x1001: 0, 0x6041: 0x0221}

    def run(sdo=(True, b"", "ok", 1.0), regs=None, nodes=None):
        r = healthy if regs is None else regs
        return cia402.preflight_report(lambda n, i, s: sdo, lambda n, i: r.get(i),
                                       nodes or {1: "left"})

    ok, lines = run()
    check("a healthy drive passes preflight", ok and "Ready to switch on" in lines[0], lines[0])
    ok, lines = run(sdo=(None, None, "timeout", None))
    check("a silent drive fails preflight as not responding", not ok and "not responding" in lines[0])
    ok, lines = run(sdo=(True, b"", "2 REPLIES - ID COLLISION?", 1.0))
    check("two answers on one Node-ID fail preflight", not ok and "COLLISION" in lines[0])
    ok, lines = run(regs={0x1001: 0x81, 0x6041: 0x0208})
    check("a fault fails preflight, naming the error register and FAULT state",
          not ok and "reports a fault" in " ".join(lines) and "FAULT state" in lines[-1])
    ok, lines = run(regs={0x1001: 0, 0x6041: 0x0021})
    check("a clear Remote bit fails preflight", not ok and "Remote bit clear" in lines[-1])
    ok, lines = run(regs={0x1001: None, 0x6041: 0x0221})
    check("unreadable diagnostics fail preflight instead of raising",
          not ok and "diagnostics unreadable" in lines[0])


TESTS = [
    test_can_monitoring,
    test_cia_tables_and_preflight,
]
