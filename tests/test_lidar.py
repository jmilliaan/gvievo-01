"""The nanoScan3 reader: reassembly, decode, and the rule that keeps it honest.

Everything here runs against tests/fixtures/nanoscan3_telegram.bin - five real
datagrams captured off the wire from the scanner at 192.168.3.10. No socket, no
scanner, no privileges.

The fixture is the point. A decoder built from a document and never checked
against a device is how you end up confidently plotting 1651 points at a
resolution the scanner is not using.
"""
import re
import socket
import struct
import threading
import time

from helpers import ROOT, check

import config
import health
import lidar
import lidarframe as lf

FIXTURE = ROOT / "tests" / "fixtures" / "nanoscan3_telegram.bin"

# What the fixture is known to contain, measured when it was captured.
TELEGRAM_LEN = 6812
BEAMS = 1652
BLOCKS = [(80, 16), (100, 24), (128, 6608), None, None, (6748, 64), None]
SPEC = (0, [6, 12, 13], False, False)


def code(path):
    """Source with docstrings and comments removed.

    Every source scan below needs this: these modules explain at length what
    they deliberately do NOT do - open port 2122, use the vendor library - and a
    naive substring search would fail on the prose forbidding the thing.
    """
    src = (ROOT / path).read_text()
    src = re.sub(r'"""(?:.|\n)*?"""', '""', src)
    src = re.sub(r"'''(?:.|\n)*?'''", "''", src)
    return "\n".join(line.split("#")[0] for line in src.splitlines())


def method(src, name):
    """One def's body, ending at the next def rather than at a byte count."""
    start = src.index(f"def {name}(")
    rest = src[start:]
    nxt = re.search(r"\n    (?:def |@)", rest[1:])
    return rest[:nxt.start() + 1] if nxt else rest


def datagrams():
    """The captured datagrams, in arrival order."""
    raw = FIXTURE.read_bytes()
    out, i = [], 0
    while i < len(raw):
        n = struct.unpack_from("<I", raw, i)[0]
        i += 4
        out.append(raw[i:i + n])
        i += n
    return out


def telegram():
    asm = lf.Reassembler(1.0)
    for d in datagrams():
        got = asm.push(d, 1.0)
        if got:
            return got[1]
    raise AssertionError("fixture does not reassemble")


def test_header_and_reassembly():
    """Five datagrams, one scan - in whatever order UDP feels like."""
    print("\nthe telegram reassembles")
    dgs = datagrams()
    check("the fixture is five datagrams", len(dgs) == 5, str(len(dgs)))

    h = lf.parse_datagram(dgs[0])
    check("the marker is recognised", h is not None)
    check("total_length is the telegram length", h["total_length"] == TELEGRAM_LEN,
          str(h["total_length"]))
    check("the header is 24 bytes", lf.HEADER_LEN == 24, str(lf.HEADER_LEN))

    # A bound port is not a promise about who sends to it.
    check("a foreign datagram is rejected, not decoded",
          lf.parse_datagram(b"XXXX" + bytes(40)) is None)
    check("a truncated datagram returns None rather than raising",
          lf.parse_datagram(b"MS3 ") is None)

    # UDP reorders. Arrival order must not be load-bearing.
    for order, label in ((list(reversed(dgs)), "reversed"),
                         ([dgs[2], dgs[0], dgs[4], dgs[1], dgs[3]], "shuffled")):
        asm = lf.Reassembler(1.0)
        got = None
        for d in order:
            got = asm.push(d, 1.0) or got
        check(f"{label} fragments still reassemble",
              got is not None and len(got[1]) == TELEGRAM_LEN,
              "no telegram" if got is None else str(len(got[1])))

    # A lost fragment must expire. Keeping it would let it pair with a
    # same-offset fragment from a LATER scan and emit one picture built out of
    # two different instants - which no consumer could possibly detect.
    asm = lf.Reassembler(0.05)
    for d in dgs[:4]:
        got = asm.push(d, 1.0)
    check("an incomplete telegram emits nothing", got is None)
    # A fragment of a DIFFERENT telegram, 1 s later. Re-sending a fragment of
    # the same one is not the case under test: that is a slow telegram, and
    # expiring it would be wrong.
    later = bytearray(dgs[0])
    struct.pack_into("<I", later, 12, 999999)      # a new identification
    asm.push(bytes(later), 2.0)
    check("the partial telegram was dropped, not kept", asm.dropped == 1,
          str(asm.dropped))
    check("a slow telegram is not dropped for being slow",
          lf.Reassembler(0.05).push(dgs[0], 1.0) is None)

    # Being handed a duplicate fragment must not produce an over-long telegram.
    asm = lf.Reassembler(1.0)
    got = None
    for d in dgs + [dgs[0]]:
        got = asm.push(d, 1.0) or got
    check("a duplicated fragment does not lengthen the telegram",
          got is not None and len(got[1]) == TELEGRAM_LEN)


def test_block_table_is_the_only_map():
    """Offsets come from the telegram's own directory, never from a constant."""
    print("\nthe block table is the map")
    tel = telegram()
    table = lf.block_table(tel)

    check("the table has seven slots", len(table) == 7, str(len(table)))
    check("the observed blocks are found", table == BLOCKS, str(table))

    # (0, 0) on the wire means "switched off". Read literally it is a
    # zero-length block AT offset 0, and a decoder that believes that will
    # cheerfully hand back a slice of the telegram header instead.
    check("an absent block is None, not offset 0",
          table[lf.BLK_INTRUSION] is None and table[lf.BLK_APPLICATION] is None)
    check("block() returns None for an absent block",
          lf.block(tel, table, lf.BLK_INTRUSION) is None)

    # The blocks tile the telegram exactly - which is what proves the base
    # offset is right rather than merely plausible.
    last = table[lf.BLK_LOCAL_IO]
    check("the last block ends exactly at the telegram end",
          last[0] + last[1] == len(tel), f"{last[0] + last[1]} vs {len(tel)}")

    # A block extending past the telegram is a decode error, not a short read.
    bad = bytearray(tel)
    struct.pack_into("<HH", bad, 32 + 4 * lf.BLK_STATUS, 60000, 4000)
    check("a block running past the end is refused",
          lf.block_table(bytes(bad))[lf.BLK_STATUS] is None)


def test_beam_count_comes_from_the_wire():
    """sec 2.4's trap: the datasheet says 1651, the scanner sends 1652."""
    print("\nthe beam count comes from the block size")
    tel = telegram()
    table = lf.block_table(tel)

    check("the fixture carries 1652 points", lf.beam_count(table) == BEAMS,
          str(lf.beam_count(table)))
    check("that is the block size divided by the point size",
          lf.beam_count(table) == BLOCKS[lf.BLK_MEASUREMENT][1] // lf.POINT_LEN)

    # The datasheet's 1651 is the count of VALID beams, and hardcoding it would
    # silently drop the last point of every scan. Assert it is nowhere near the
    # decode path.
    check("1651 is not hardcoded in lidarframe",
          "1651" not in code("core/lidarframe.py"))
    check("...nor in the reader", "1651" not in code("drivers/lidar.py"))

    m = lf.measurement(tel, table)
    check("every point decodes", len(m["dist_mm"]) == BEAMS, str(len(m["dist_mm"])))
    valid = lf.valid_mask(m["status"], m["dist_mm"])
    check("most points are valid with an echo", 1400 < sum(valid) < BEAMS,
          str(sum(valid)))
    # Bit 0 is validity: the fixture's one point without it reads zero distance.
    zero = [i for i, d in enumerate(m["dist_mm"]) if d == 0]
    check("a zero-distance point is not marked valid",
          all(not (m["status"][i] & lf.STATUS_VALID) for i in zero), str(zero))
    check("no-echo returns are excluded from the mask",
          all(not v for v, d in zip(valid, m["dist_mm"]) if d >= lf.NO_ECHO_MM))

    # Decimation must sample, not resample onto a different geometry: the
    # browser reconstructs bearings as start + i*res*step.
    dec = lf.measurement(tel, table, step=4)
    check("decimation keeps every 4th point",
          dec["dist_mm"] == m["dist_mm"][::4] and dec["step"] == 4)


def test_geometry_is_read_not_assumed():
    """sec 2.4: take the angular range from the telegram, never hardcode it."""
    print("\nthe angular geometry is read from the telegram")
    tel = telegram()
    table = lf.block_table(tel)
    d = lf.derived_values(tel, table)

    check("the start angle decodes", d is not None and
          abs(d["start_angle_deg"] + 47.5) < 1e-6, str(d and d["start_angle_deg"]))
    check("the resolution decodes",
          abs(d["resolution_deg"] - 0.166666) < 1e-4, str(d["resolution_deg"]))
    span = BEAMS * d["resolution_deg"]
    # The manual warns the device may output a slightly LARGER range than
    # configured. 275.33 against a configured 275 is exactly that, and a decoder
    # that clamped to the configured value would misplace every point.
    check("the span is the configured 275 deg or a little more",
          275.0 <= span < 276.0, f"{span:.2f} deg")
    check("unnamed header words are kept raw rather than guessed",
          set(d["raw"]) == {"f0", "f3", "f4", "f5"}, str(sorted(d["raw"])))


def test_zones_are_never_silently_clear():
    """sec 2.5 and sec 4, which are the two ways this page could kill someone."""
    print("\ncut-off paths are never silently clear")
    tel = telegram()
    table = lf.block_table(tel)

    z = lf.zones(tel, table, SPEC)
    check("the profile's flag is reported, not inferred", z["validated"] is False)
    check("three paths are reported", len(z["paths"]) == 3, str(z["paths"]))
    check("the raw bytes travel with them for the walk-through", "raw" in z)

    # An offset outside the block must read as unknown. Returning False would be
    # the literal worst case: a mapping error rendering as "path clear".
    z2 = lf.zones(tel, table, (0, [6, 12, 999], False, True))
    check("an out-of-range offset reads as unknown, not clear",
          z2["paths"][2] is None, str(z2["paths"]))

    # An absent status block likewise.
    z3 = lf.zones(tel, table, (lf.BLK_INTRUSION, [0, 1, 2], False, True))
    check("an absent status block is not readable", z3["readable"] is False)
    check("...and yields no path claims", z3["paths"] == [])


def _link(enabled=True):
    """A LidarLink with no socket, driven by hand."""
    return lidar.LidarLink(sock_factory=lambda: None)


def test_link_publishes_and_goes_stale():
    """Silence is the fault here, unlike the RFID reader."""
    print("\nthe link reports staleness rather than hiding it")
    tel = telegram()
    ln = _link()

    snap = ln.snapshot()
    check("before any telegram, comms is not ok", snap["comms_ok"] is False)
    check("...and that counts as stale", snap["stale"] is True)
    check("...and the zones say so too", snap["zones"]["stale"] is True)

    ln._on_telegram(1000, tel)
    snap = ln.snapshot()
    check("a telegram makes the link ok", snap["comms_ok"] is True)
    check("...and not stale", snap["stale"] is False)
    check("the beam count is published", snap["beams"] == BEAMS, str(snap.get("beams")))
    check("the summary carries no point array", "points" not in snap
          and "measurement" not in snap)
    # The bus thread reads this at tick rate through PullSource; the 80 bytes of
    # undecoded diagnostic blocks belong on the 5 Hz cloud poll instead.
    check("the summary carries no raw diagnostic blocks", "raw" not in snap)

    # Age it past the window by hand rather than sleeping.
    ln._last_ok = time.monotonic() - (config.LIDAR_SILENT_WARN_S + 0.05)
    snap = ln.snapshot()
    check("an old telegram goes stale", snap["comms_ok"] is False
          and snap["stale"] is True)
    check("the zone snapshot is stale too", snap["zones"]["stale"] is True)
    # The zones the LAST telegram reported are still in there. That is fine -
    # and it is exactly why `stale` has to travel with them, because a consumer
    # reading paths alone would see a perfectly ordinary set of flags.
    check("stale zones still carry their last paths, flagged",
          snap["zones"]["paths"] == lf.zones(tel, lf.block_table(tel), SPEC)["paths"])


def test_sequence_gaps_are_counted():
    """sec 3.5: dropped datagrams are otherwise completely invisible."""
    print("\ntelegram counter gaps are counted")
    tel = telegram()
    ln = _link()

    for ident in (10, 11, 12):
        ln._on_telegram(ident, tel)
    check("consecutive telegrams report no gap", ln.snapshot()["gaps"] == 0,
          str(ln.snapshot()["gaps"]))

    ln._on_telegram(17, tel)            # 13..16 lost
    check("a jump of 5 counts four lost telegrams",
          ln.snapshot()["gaps"] == 4, str(ln.snapshot()["gaps"]))

    # The counter is a u32. Wrapping is not a loss of four billion telegrams.
    ln2 = _link()
    ln2._on_telegram(0xFFFFFFFF, tel)
    ln2._on_telegram(0, tel)
    check("wraparound reports no gap", ln2.snapshot()["gaps"] == 0,
          str(ln2.snapshot()["gaps"]))

    # Nor is a counter that goes backwards a gap of nearly 2^32.
    ln3 = _link()
    ln3._on_telegram(500, tel)
    ln3._on_telegram(400, tel)
    check("a backwards counter is not a huge gap", ln3.snapshot()["gaps"] == 0,
          str(ln3.snapshot()["gaps"]))


def test_cloud_is_separate_and_survives_a_bad_telegram():
    print("\nthe cloud is decoded on demand")
    tel = telegram()
    ln = _link()

    empty = ln.cloud()
    check("with no telegram the cloud is stale and empty",
          empty["points"] is None and empty["stale"] is True)

    ln._on_telegram(1, tel)
    c = ln.cloud(step=4)
    check("the cloud decimates", len(c["points"]) == (BEAMS + 3) // 4,
          str(len(c["points"])))
    check("it carries the geometry the browser needs",
          abs(c["start_angle_deg"] + 47.5) < 1e-6 and c["step"] == 4)
    check("it carries the no-echo value rather than the page assuming one",
          c["no_echo_mm"] == lf.NO_ECHO_MM)
    check("it carries the zones", c["zones"]["validated"] is False)

    # A page must never 500 because a telegram was malformed.
    ln._last_tel = b"MS3 " + bytes(8)
    bad = ln.cloud()
    check("a malformed telegram yields no points instead of an exception",
          bad["points"] is None)


def test_link_survives_a_hostile_socket():
    """The thread must outlive anything the network does to it."""
    print("\nthe reader thread survives bad input")
    dgs = datagrams()

    class FakeSock:
        def __init__(self):
            self.queue = ([(b"\x00" * 8, ("192.168.3.10", 6060))]      # garbage
                          + [(b"hello", ("10.0.0.1", 6060))]           # foreign IP
                          + [(d, ("192.168.3.10", 6060)) for d in dgs])
        def recvfrom(self, _n):
            if self.queue:
                return self.queue.pop(0)
            raise socket.timeout()
        def close(self):
            pass

    sock = FakeSock()
    ln = lidar.LidarLink(sock_factory=lambda: sock)
    t = threading.Thread(target=ln._run, daemon=True)
    t.start()
    for _ in range(100):
        if ln.snapshot()["telegrams"]:
            break
        time.sleep(0.01)
    snap = ln.snapshot()
    ln.stop()
    t.join(timeout=2.0)

    check("the telegram was received despite the junk before it",
          snap["telegrams"] == 1, str(snap["telegrams"]))
    check("the datagram from the wrong host was not decoded",
          snap["comms_ok"] is True)
    check("the thread stopped cleanly", not t.is_alive())


def test_lidar_cannot_stop_the_vehicle():
    """Non-critical, on purpose. The stop is the OSSD into the FX3."""
    print("\na dead lidar is a display fault and nothing more")
    mon = health.HealthMonitor()
    ln = _link()
    src = mon.add(health.PullSource("lidar", ln.snapshot),
                  config.LIDAR_SILENT_WARN_S)
    check("the lidar source is not critical", src.critical is False)

    # Seen once, then gone - the only state health.py counts as lost.
    ln._on_telegram(1, telegram())
    mon.evaluate()
    ln._last_ok = time.monotonic() - 10.0
    r = mon.evaluate()
    check("a dead lidar is reported lost", r["sources"]["lidar"]["ok"] is False)
    check("...but raises no system error", r["system_error"] is False)
    check("...it lands in the sensor tier, which stops auto but not manual",
          r["sensor_error"] is True
          and r["sensor_detail"] == ln.snapshot()["detail"], r["sensor_detail"])

    # canworker must not have registered it as critical either.
    src = code("canworker.py")
    i = src.index('PullSource("lidar"')
    check("canworker registers it without critical=True",
          "critical" not in src[i:i + 200])

    # And nothing that produces motion may consult it.
    for fn in ("_do_arm", "_do_auto_run", "drive"):
        check(f"{fn}() does not consult the lidar",
              "_lidar" not in method(src, fn))


def test_reader_never_writes_to_the_scanner():
    """Rule 2 of the brief, as a source scan.

    The failure this guards against is somebody adding the vendor library, or a
    "just set the UDP target" call, months from now: it would work, and it would
    quietly invalidate the scanner's safety verification.
    """
    print("\nnothing can write to the scanner")
    for name in ("drivers/lidar.py", "drivers/lidar_scan.py", "core/lidarframe.py"):
        src = code(name)
        for bad in ("sendto", "sendall", "SOCK_STREAM", "2122",
                    "sick_safetyscanners"):
            check(f"{name} does not use {bad}", bad not in src)


def test_an_unplugged_scanner_is_a_warning_not_a_stop():
    """The vehicle must drive with the lidar Ethernet unplugged.

    Two things get checked here, because they fail differently. The BEHAVIOUR:
    a socket that cannot even bind - which is what an unplugged NIC gives you,
    errno 99 - must leave the reader thread alive, retrying, and must raise no
    critical fault, or a data-only link would be gating a vehicle whose real
    stop is the OSSD pair into the FX3. The WORDS: an operator seeing three red
    lamps needs to be told it is a cable and that the AGV still runs, not shown
    a raw errno.
    """
    print("\nan unplugged scanner warns, and nothing else")

    class DeadNic:
        """bind() on an address the machine does not have."""
        def __init__(self):
            self.tries = 0
        def __call__(self):
            self.tries += 1
            raise OSError(99, "Cannot assign requested address")

    factory = DeadNic()
    ln = lidar.LidarLink(sock_factory=factory)
    t = threading.Thread(target=ln._run, daemon=True)
    t.start()
    time.sleep(0.05)
    snap = ln.snapshot()

    check("the reader thread survives a socket it cannot open", t.is_alive())
    check("...and keeps retrying", factory.tries >= 1, str(factory.tries))
    check("the link reports itself down", snap["connected"] is False)
    check("never_seen says the scanner has not answered at all",
          snap["never_seen"] is True)
    check("...and rx_age_s is None rather than a number",
          snap["rx_age_s"] is None)

    # The safety rule is NOT relaxed by knowing why the data is absent.
    check("the zones still read stale, so no lamp reads clear",
          snap["stale"] is True and snap["zones"]["stale"] is True)

    # The whole point: this must not reach the critical tier.
    mon = health.HealthMonitor()
    mon.add(health.PullSource("lidar", ln.snapshot), config.LIDAR_SILENT_WARN_S)
    r = mon.evaluate()
    check("an unplugged scanner raises no system error",
          r["system_error"] is False)
    ln.stop()
    t.join(timeout=2.0)

    # A scanner that RAN and then died is a different fault and keeps its
    # error level - never_seen must not swallow it.
    ln2 = _link()
    ln2._on_telegram(1, telegram())
    ln2._last_ok = time.monotonic() - 10.0
    dead = ln2.snapshot()
    check("a stream that ran and then stopped is not 'never seen'",
          dead["never_seen"] is False)
    check("...and is still stale", dead["stale"] is True)

    # The words in front of the operator.
    al = (ROOT / "app" / "static" / "alarms.js").read_text()
    check("the alarms page warns rather than errors when never connected",
          "if (l.never_seen) rows.push(['warn'" in al)
    check("...and says it is the Ethernet link", "not connected" in al)
    check("...while a stream that died stays an error",
          "else if (l.stale) rows.push(['error'" in al)
    # Matched against the expression, not the file: the comment above it in
    # alarms.js names the old code to explain what was wrong with it.
    check("the raw errno no longer renders as 'Sensor lost'",
          "name !== 'lidar'" in al
          and "'Sensor lost', hw.sensor_detail" not in al
          and "heldBack.join" in al)

    page = (ROOT / "app" / "templates" / "lidar.html").read_text()
    check("the lidar page carries a not-connected banner",
          'id="l-nolink"' in page)
    check("...hidden until the state poll says otherwise", "hidden>" in page)
    check("...and states the vehicle runs without it",
          "runs normally without it" in page)
    js = (ROOT / "app" / "static" / "lidar.js").read_text()
    check("the banner is driven by never_seen",
          "l.enabled && l.never_seen" in js)


TESTS = [
    test_header_and_reassembly,
    test_block_table_is_the_only_map,
    test_beam_count_comes_from_the_wire,
    test_geometry_is_read_not_assumed,
    test_zones_are_never_silently_clear,
    test_link_publishes_and_goes_stale,
    test_sequence_gaps_are_counted,
    test_cloud_is_separate_and_survives_a_bad_telegram,
    test_link_survives_a_hostile_socket,
    test_lidar_cannot_stop_the_vehicle,
    test_an_unplugged_scanner_is_a_warning_not_a_stop,
    test_reader_never_writes_to_the_scanner,
]
