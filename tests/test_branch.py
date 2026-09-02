"""Branch selection: the intent ladder, the commit seal-in, and track choice."""
from helpers import ROOT, check

import branch
from branch import LEFT, RIGHT, STRAIGHT


def tracks(*pairs):
    """(index, pos_mm) pairs -> the shape canworker._sensor_json() emits."""
    return [{"index": i, "pos_mm": p, "width": 10} for i, p in pairs]


# The sensor keeps the main track on LCP2 and puts the branch beside it
# (manual 8.4.1). These are the four #LCP cases from table 17.
PLAIN = tracks((2, 4))                          # #LCP 2
DIV_NEG = tracks((1, -38), (2, 3))              # #LCP 3, branch on the -ve side
DIV_POS = tracks((2, 3), (3, 41))               # #LCP 6, branch on the +ve side
CROSSING = tracks((1, -40), (2, 2), (3, 44))    # #LCP 7


def test_ladder_truth_table():
    """The two rungs, transcribed from the drawn design.

    Columns are the drawing's contacts. `prior` is the state image at the top
    of the scan, which is what a seal-in reads.
    """
    print("\nbranch: intent ladder")

    # (prior_left, prior_right, setL, clrL, setR, clrR) -> (left, right)
    TABLE = [
        # nothing latched, nothing asked
        ((False, False), (0, 0, 0, 0), (False, False)),
        # a single pulse sets, and the seal-in holds it after the pulse goes
        ((False, False), (1, 0, 0, 0), (True, False)),
        ((True, False), (0, 0, 0, 0), (True, False)),
        ((False, False), (0, 0, 1, 0), (False, True)),
        ((False, True), (0, 0, 0, 0), (False, True)),
        # the matching reset contact drops it
        ((True, False), (0, 1, 0, 0), (False, False)),
        ((False, True), (0, 0, 0, 1), (False, False)),
        # a reset for the other side leaves this one alone
        ((True, False), (0, 0, 0, 1), (True, False)),
        ((False, True), (0, 1, 0, 0), (False, True)),
        # interlock: a set for the opposite side cannot take over a live latch
        ((True, False), (0, 0, 1, 0), (True, False)),
        ((False, True), (1, 0, 0, 0), (False, True)),
        # A clear and an OPPOSITE set in the same scan is not symmetric, and
        # rung order is exactly why:
        #   clear-left + set-right : rung 1 reads the left that is still
        #     latched and refuses the set; rung 2 then clears left. Both end
        #     up off, and the one-shot set pulse is lost. Handover costs a
        #     second scan.
        #   clear-right + set-left : rung 1 clears right FIRST, so rung 2 sees
        #     the cleared value and the set lands. Handover in one scan.
        # Swapping the two rungs mirrors which direction is the fast one. Both
        # outcomes are safe - the slow case degrades to "both off" = straight -
        # and it takes two tags inside one 20 ms tick to reach either. Pinned
        # here so the asymmetry is a decision on record, not a surprise.
        ((True, False), (0, 1, 1, 0), (False, False)),
        ((False, True), (1, 0, 0, 1), (True, False)),
    ]
    for (pl, pr), (sl, cl, sr, cr), (want_l, want_r) in TABLE:
        lad = branch.Ladder()
        lad.left, lad.right = pl, pr
        lad.scan(set_left=bool(sl), clear_left=bool(cl),
                 set_right=bool(sr), clear_right=bool(cr))
        check(f"rung L={pl:d}R={pr:d} sL={sl} cL={cl} sR={sr} cR={cr}"
              f" -> L={want_l:d}R={want_r:d}",
              (lad.left, lad.right) == (want_l, want_r),
              f"got L={lad.left:d}R={lad.right:d}")

    # Rung order is semantics: rung 2 reads the `right` rung 1 just wrote.
    lad = branch.Ladder()
    lad.scan(set_left=True, set_right=True)
    check("a simultaneous set-left and set-right resolves right-wins",
          (lad.left, lad.right) == (False, True), f"{lad.left} {lad.right}")

    lad = branch.Ladder()
    lad.scan(set_right=True)
    check("intent() reports RIGHT", lad.intent() == RIGHT)
    lad.reset()
    check("reset() drops intent to STRAIGHT", lad.intent() == STRAIGHT)


def test_select_track():
    """Choosing an LCP needs no case analysis on #LCP, and degrades safely."""
    print("\nbranch: track selection")

    check("no tracks selects nothing", branch.select_track([], LEFT) is None)
    check("straight on a plain track takes LCP2",
          branch.select_track(PLAIN, STRAIGHT)["index"] == 2)
    check("left on a plain track still takes LCP2 - nothing to branch onto",
          branch.select_track(PLAIN, LEFT)["index"] == 2)

    # positive_is_left=True: LEFT is the highest position, RIGHT the lowest.
    check("left on a +ve-side diverter takes LCP3",
          branch.select_track(DIV_POS, LEFT)["index"] == 3)
    check("right on a -ve-side diverter takes LCP1",
          branch.select_track(DIV_NEG, RIGHT)["index"] == 1)
    check("straight through a +ve-side diverter holds LCP2",
          branch.select_track(DIV_POS, STRAIGHT)["index"] == 2)
    check("straight through a -ve-side diverter holds LCP2",
          branch.select_track(DIV_NEG, STRAIGHT)["index"] == 2)

    # The degradation that removes the need for a special case: asking for a
    # side that is not present yields the extreme in that direction, which IS
    # the main track.
    check("left at a -ve-side diverter degrades to LCP2, not the branch",
          branch.select_track(DIV_NEG, LEFT)["index"] == 2)
    check("right at a +ve-side diverter degrades to LCP2, not the branch",
          branch.select_track(DIV_POS, RIGHT)["index"] == 2)

    check("a crossing offers both extremes",
          (branch.select_track(CROSSING, LEFT)["index"],
           branch.select_track(CROSSING, RIGHT)["index"]) == (3, 1))

    # Handedness is one constant, and it must be confirmed on real tape.
    check("positive_is_left=False mirrors left and right",
          branch.select_track(DIV_POS, RIGHT, positive_is_left=False)["index"] == 3)
    check("positive_is_left=False leaves straight alone",
          branch.select_track(DIV_POS, STRAIGHT, positive_is_left=False)["index"] == 2)

    check("a track with no position is ignored",
          branch.select_track(tracks((1, None), (2, 5)), LEFT)["index"] == 2)


def test_engine_scans_tags():
    """The profile table compiles into the four contacts the rungs read."""
    print("\nbranch: engine")

    rows = [{"entry_tag": "000A", "exit_tag": "000B", "branch": LEFT},
            {"entry_tag": "0014", "exit_tag": "0015", "branch": RIGHT},
            # a second junction turning the same way drives the same coil
            {"entry_tag": "001E", "exit_tag": "001F", "branch": LEFT}]
    t = branch.compile_table(rows)
    check("entry tags for a side OR onto one contact",
          t["set_left"] == {"000A", "001E"}, sorted(t["set_left"]))
    check("exit tags likewise", t["clear_left"] == {"000B", "001F"})
    check("the other side is separate",
          (t["set_right"], t["clear_right"]) == ({"0014"}, {"0015"}))

    e = branch.BranchEngine(rows)
    check("no tag leaves intent straight", e.scan(None) == STRAIGHT)
    check("an entry tag latches its direction", e.scan("000A") == LEFT)
    check("and it holds with no further reads", e.scan(None) == LEFT)
    check("the tag that set it is recorded", e.set_by == "000A")
    check("the OTHER junction's exit tag does not clear it",
          e.scan("0015") == LEFT)
    check("its own exit tag does", e.scan("000B") == STRAIGHT)
    check("set_by clears with the latch", e.set_by is None)
    check("the second left junction drives the same coil",
          e.scan("001E") == LEFT)
    check("and its own exit tag clears it", e.scan("001F") == STRAIGHT)

    # An unknown tag is not an error - most tags on a route are stations, not
    # junctions - but a rung that never fires is exactly the silent failure the
    # strict config checks exist to prevent, so it is counted.
    e.scan("FFFF")
    check("an unmatched tag is counted, not fatal", e.unmatched == 1)
    check("and does not disturb the latch", e.ladder.intent() == STRAIGHT)

    e.scan("000A")
    e.reset()
    check("reset() drops intent and set_by",
          e.ladder.intent() == STRAIGHT and e.set_by is None)


def test_choose():
    """The crossing rule and the unhonoured flag."""
    print("\nbranch: choose")

    rows = [{"entry_tag": "000A", "exit_tag": "000B", "branch": LEFT}]
    e = branch.BranchEngine(rows)
    e.scan("000A")

    t, choice = e.choose(6, DIV_POS)
    check("ordered left at a +ve diverter, it takes LCP3",
          t["index"] == 3 and choice == LEFT)
    check("an honoured order is not flagged", e.unhonoured is False)

    t, choice = e.choose(3, DIV_NEG)
    check("ordered left at a -ve diverter, it carries straight on",
          t["index"] == 2 and choice == LEFT)
    check("and the order is flagged unhonoured", e.unhonoured is True)

    t, choice = e.choose(7, CROSSING)
    check("a crossing ignores intent and holds LCP2",
          choice == STRAIGHT and t["index"] == 2)
    check("a crossing is not an unhonoured order", e.unhonoured is False)
    check("and does not consume the latch", e.ladder.intent() == LEFT)

    t, choice = e.choose(2, PLAIN)
    check("plain tape is never an unhonoured order",
          t["index"] == 2 and e.unhonoured is False)
    t, choice = e.choose(0, [])
    check("no track returns nothing, and is not unhonoured",
          t is None and e.unhonoured is False)


def test_profile_table():
    """A junction table that cannot work must be refused BY NAME at boot: a
    dead rung produces no error, no log line and no motion of its own."""
    import copy
    import json
    import config
    print("\nbranch: profile validation")

    doc = json.load(open(str(ROOT / "profiles" / "agv-01.json")))

    def refused(name, rows, needle):
        d = copy.deepcopy(doc)
        d["branch_latch"] = rows
        try:
            config._parse(d)
            check(name, False, "NOT rejected")
        except config.ConfigError as e:
            check(name, needle in str(e), str(e)[:70])

    ok = {"entry_tag": "000A", "exit_tag": "000B", "branch": "left"}
    refused("an integer tag is refused - hex text is what tag_of() returns",
            [dict(ok, entry_tag=10)], "hex string")
    refused("a short tag is refused", [dict(ok, entry_tag="0A")], "hex characters")
    refused("a non-hex tag is refused", [dict(ok, entry_tag="00ZZ")], "hex characters")
    refused("an unknown direction is refused", [dict(ok, branch="up")], "branch")
    refused("entry_tag == exit_tag is refused",
            [dict(ok, exit_tag="000A")], "cannot both")
    refused("a tag used twice is refused",
            [ok, {"entry_tag": "000A", "exit_tag": "000C", "branch": "right"}],
            "two things")
    refused("a tag also in ignore_tags is refused",
            [dict(ok, entry_tag="3130")], "ignore_tags")
    refused("an unknown row key is refused", [dict(ok, x=1)], "unknown key")
    refused("a missing row key is refused",
            [{"entry_tag": "000A", "branch": "left"}], "missing key")

    d = copy.deepcopy(doc)
    d["branch_latch"] = []
    check("an empty table is valid - it ships that way until the real tags "
          "are known", config._parse(d)["BRANCH_LATCH"] == [])

    d["branch_latch"] = [{"entry_tag": "000a", "exit_tag": "000b",
                          "branch": "left"}]
    check("lower-case hex normalises, so it cannot become a second tag",
          config._parse(d)["BRANCH_LATCH"][0]["entry_tag"] == "000A")


def test_follower_uses_the_choice():
    """_read_error() must actually steer onto the chosen track."""
    import autopilot
    import config
    print("\nbranch: follower wiring")

    f = autopilot.LineFollower()
    sensor = {"tracks": DIV_POS, "nlcp": 6, "has_track": True}

    e_m, n, _ = f._read_error(sensor, STRAIGHT)
    check("straight follows LCP2 through a diverter",
          abs(e_m * 1000.0) == 3.0 and n == 2, f"{e_m}")

    f = autopilot.LineFollower()
    e_m, _, _ = f._read_error(sensor, LEFT)
    check("left follows LCP3", abs(e_m * 1000.0) == 41.0, f"{e_m}")

    f = autopilot.LineFollower()
    e_m, _, guard = f._read_error({"tracks": PLAIN, "nlcp": 2}, LEFT)
    check("on plain tape the order changes nothing",
          abs(e_m * 1000.0) == 4.0 and guard == "", f"{e_m}")

    check("the default argument keeps every existing caller working",
          f._read_error({"tracks": PLAIN, "nlcp": 2})[0] is not None)
    check("handedness is read from the profile, not hardcoded",
          isinstance(config.BRANCH_POSITIVE_IS_LEFT, bool))


def test_branch_events_are_edge_only():
    """_branch_scan() runs at 50 Hz. The ring buffer holds 200 entries, so a
    per-tick emit empties it of everything meaningful in about four seconds.

    The source scan in test_logging guards _run_autopilot by name; this proves
    the property for the branch path by counting, which is what actually
    matters and does not depend on which method the code happens to live in.
    """
    import canworker
    import events
    print("\nbranch: event discipline")

    src = (ROOT / "canworker.py").read_text()
    start = src.index("def _branch_scan")
    body = src[start:src.find("\n    def ", start + 1)]
    check("the branch emits live in _branch_scan, not _run_autopilot",
          "events." in body)

    class _Link:
        """An RfidLink stub: one tag, then the same snapshot forever - which is
        what the real link returns while a tag sits in the reader's field."""
        def __init__(self):
            self.n, self.tag = 0, None

        def read(self, tag=None):
            if tag is not None:
                self.n, self.tag = self.n + 1, tag

        def snapshot(self):
            return {"tags_seen": self.n, "last_tag": self.tag}

    ctl = canworker.Controller.__new__(canworker.Controller)
    ctl._rfid = _Link()
    ctl._branch_seen = 0
    ctl._branch = branch.BranchEngine(
        [{"entry_tag": "000A", "exit_tag": "000B", "branch": LEFT}])

    events.clear()
    ctl._rfid.read("000A")
    ctl._branch_scan({"nlcp": 2, "tracks": PLAIN})
    check("latching emits once", len(events.since(0)[1]) == 1)

    for _ in range(200):                       # 4 s of ticks, tag still in field
        ctl._branch_scan({"nlcp": 2, "tracks": PLAIN})
    check("a held tag does not re-emit for every tick",
          len(events.since(0)[1]) == 1, f"{len(events.since(0)[1])} events")
    check("and the latch is still set - a held tag must not re-trigger a "
          "CLEAR contact either", ctl._branch.ladder.intent() == LEFT)

    # An order that cannot be carried out is worth one line, not 50 a second.
    for _ in range(200):
        ctl._branch_scan({"nlcp": 3, "tracks": DIV_NEG})
    check("a sustained unhonoured order emits once",
          len(events.since(0)[1]) == 2, f"{len(events.since(0)[1])} events")

    events.clear()


TESTS = [
    test_ladder_truth_table,
    test_select_track,
    test_engine_scans_tags,
    test_choose,
    test_profile_table,
    test_follower_uses_the_choice,
    test_branch_events_are_edge_only,
]
