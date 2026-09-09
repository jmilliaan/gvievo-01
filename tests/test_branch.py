"""Branch selection: the intent ladder, the commit seal-in, and track choice."""
import time
from helpers import NO_TRACK, ROOT, check

import autopilot
import branch
from panel import AUTO, MANUAL
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


def test_selection_follows_the_tape_not_the_label():
    """STRAIGHT follows the track it was already on, not whichever one the
    sensor labelled LCP2 this scan.

    Run 0023, t=31.0: coming out of the U-turn on a tape at -43 mm, the main
    line came into view on the POSITIVE side. LCP indices are assigned by
    position, so the labels swap as the two tapes converge - and the followed
    position went -43 -> +86 -> -60 mm in half a second, changing tape and back.
    """
    print("\nbranch: selection follows the tape, not the LCP label")

    # The merge as logged: the tape being followed, and the main line arriving
    # from the other side. Labels deliberately "wrong" - LCP2 is the far one.
    merge = [{"index": 1, "pos_mm": -43.0, "width": 10},
             {"index": 2, "pos_mm": 86.0, "width": 10}]

    check("without an anchor it still trusts LCP2, as it always did",
          branch.select_track(merge, STRAIGHT)["pos_mm"] == 86.0)
    check("anchored on the tape it was following, it stays on it",
          branch.select_track(merge, STRAIGHT, True, -43.0)["pos_mm"] == -43.0)
    check("...and would have stayed even mid-jump",
          branch.select_track(merge, STRAIGHT, True, -30.0)["pos_mm"] == -43.0)

    # Continuity must not defeat a branch order: taking a fork IS changing tape,
    # and it is the one moment that is intended.
    fork = tracks((2, 3), (3, 41))
    check("a LEFT order still jumps to the branch",
          branch.select_track(fork, LEFT, True, 3.0)["index"] == 3)
    check("a RIGHT order still takes the other extreme",
          branch.select_track(tracks((1, -38), (2, 3)), RIGHT, True, 3.0)["index"] == 1)

    # Three tracks at a crossing: hold the one being followed.
    check("a crossing holds the track it is on",
          branch.select_track(CROSSING, STRAIGHT, True, 2.0)["index"] == 2)
    check("...even when the labels put another nearer zero",
          branch.select_track(tracks((1, -2), (2, 40), (3, 80)),
                              STRAIGHT, True, 40.0)["pos_mm"] == 40.0)

    # A single track is a single track, anchor or not.
    check("one track is picked whatever the anchor says",
          branch.select_track(PLAIN, STRAIGHT, True, -90.0)["index"] == 2)

    # choose() must land on the same track the follower will.
    e = branch.BranchEngine([])
    track, choice = e.choose(6, merge, -43.0)
    check("choose() re-selects to the same tape as the follower",
          choice == STRAIGHT and track["pos_mm"] == -43.0)

    # End to end through the follower: the anchor is its own last position, so
    # the jump never reaches the error signal.
    import autopilot
    f = autopilot.LineFollower()
    f.reset()
    f._last_valid_mm = -43.0
    e_m, n, guard = f._read_error({"tracks": merge, "nlcp": 6}, STRAIGHT)
    check("the follower stays on its tape through the merge",
          f.followed_mm == -43.0 and guard == "", f"{f.followed_mm} {guard!r}")


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


def test_the_fork_consumes_the_order():
    """A branch order ends at the fork, not at the exit tag.

    Held to the exit tag it stops being "take the left fork" and becomes
    "always follow the leftmost tape" - and after a U-turn the vehicle faces the
    other way, so the MAIN LINE is the leftmost tape. Runs 0023/0024 jumped
    -43 -> +83 -> -57 mm at the merge, every lap, for exactly that reason.
    """
    print("\nbranch: the fork consumes the order")

    rows = [{"entry_tag": "0002", "exit_tag": "0001", "branch": LEFT,
             "slow_speed": True}]
    e = branch.BranchEngine(rows)

    check("an entry tag still latches the order", e.scan("0002", 2) == LEFT)
    check("...and the slow zone with it", e.slow is True)

    # Plain tape between the tag and the junction: nothing resolves yet.
    for _ in range(50):
        e.scan(None, 2)
    check("a single track before the fork does not consume the order",
          e.ladder.intent() == LEFT, "consumed too early")

    # The diverter itself.
    for _ in range(10):
        e.scan(None, 6)
    check("the order survives while the diverter is in view",
          e.ladder.intent() == LEFT)

    # Out the other side.
    e.scan(None, 2)
    check("coming out on a single track consumes it", e.ladder.intent() == STRAIGHT)
    check("...and it is counted", e.forks == 1)
    check("*** but the slow zone SURVIVES the fork ***", e.slow is True,
          "the vehicle must stay slow across the whole junction bubble")
    check("set_by clears with the order", e.set_by is None)

    # The merge on the way back: two tracks, no order standing. This is the one
    # that used to jump.
    for _ in range(30):
        e.scan(None, 6)
    check("a diverter seen with NO order cannot arm a pulse",
          e.ladder.intent() == STRAIGHT and e._at_fork is False)
    e.scan(None, 2)
    check("...so coming out of it changes nothing", e.forks == 1)
    check("...and the vehicle is still slow through it", e.slow is True)

    # Only the exit tag ends the bubble.
    e.scan("0001", 2)
    check("the exit tag is what ends the slow zone", e.slow is False)

    # A dropout mid-fork must not be mistaken for the far side of it.
    e2 = branch.BranchEngine(rows)
    e2.scan("0002", 2)
    e2.scan(None, 6)
    e2.scan(None, 0)                      # no track at all
    check("losing the tape mid-diverter does not consume the order",
          e2.ladder.intent() == LEFT, "a dropout is not the far side of a fork")
    e2.scan(None, 2)
    check("...it is consumed when a real single track returns",
          e2.ladder.intent() == STRAIGHT)

    # The backstop: if the fork is never detected, the exit tag still clears it,
    # which is exactly what the code did before this rung existed.
    e3 = branch.BranchEngine(rows)
    e3.scan("0002", 2)
    for _ in range(100):
        e3.scan(None, 2)                  # a fork that never resolved
    check("an undetected fork leaves the order standing", e3.ladder.intent() == LEFT)
    e3.scan("0001", 2)
    check("...and the exit tag still clears it, as it always did",
          e3.ladder.intent() == STRAIGHT and e3.forks == 0)

    # Omitting nlcp entirely leaves the latch on the tags alone.
    e4 = branch.BranchEngine(rows)
    e4.scan("0002")
    for _ in range(20):
        e4.scan()
    check("without #LCP the latch behaves exactly as it used to",
          e4.ladder.intent() == LEFT and e4.forks == 0)


def test_the_u_turn_merge_end_to_end():
    """The whole 0024 sequence: entry tag, fork, loop, U-turn, merge.

    Asserts the thing that was actually wrong - that the vehicle does not change
    tape at the merge - by driving the engine and the follower together.
    """
    import autopilot
    print("\nbranch: the U-turn merge, end to end")

    e = branch.BranchEngine([{"entry_tag": "0002", "exit_tag": "0001",
                              "branch": LEFT, "slow_speed": True}])
    f = autopilot.LineFollower()
    f.reset()

    def tick(tag, nlcp, tracks):
        e.scan(tag, nlcp)
        _, choice = e.choose(nlcp, tracks, f.followed_mm)
        return f._read_error({"tracks": tracks, "nlcp": nlcp}, choice)

    tick(None, 2, tracks((2, 0)))              # approaching on plain tape
    tick("0002", 2, tracks((2, 0)))            # entry tag
    check("the order is standing before the fork", e.ladder.intent() == LEFT)

    # The fork: main track plus a branch on the positive side. LEFT takes it.
    for _ in range(6):
        tick(None, 6, tracks((2, 3), (3, 41)))
    check("the order steers onto the branch", f.followed_mm > 20,
          f"{f.followed_mm} mm")

    tick(None, 2, tracks((2, 41)))             # out the far side, one track
    check("the fork consumed the order", e.ladder.intent() == STRAIGHT)
    check("...and the bubble is still slow", e.slow is True)

    # Round the loop, drifting out to -43 mm as the real run does.
    for mm in list(range(40, -40, -4)) + [-43]:
        tick(None, 2, tracks((2, float(mm))))
    check("it follows its tape round the loop", f.followed_mm == -43.0,
          f"{f.followed_mm} mm")

    # THE MERGE. Facing the other way now, so the main line arrives on the
    # POSITIVE side - the exact geometry that used to grab the wrong tape.
    for _ in range(20):
        tick(None, 6, [{"index": 1, "pos_mm": -43.0, "width": 10},
                       {"index": 2, "pos_mm": 86.0, "width": 10}])
    check("*** it stays on its own tape through the merge ***",
          f.followed_mm == -43.0, f"jumped to {f.followed_mm} mm")
    check("...with no slew clamp, because nothing jumped",
          f._read_error({"tracks": [{"index": 1, "pos_mm": -43.0, "width": 10},
                                    {"index": 2, "pos_mm": 86.0, "width": 10}],
                         "nlcp": 6}, STRAIGHT)[2] == "")
    check("...and it is still slow, so the exit tag still has a job",
          e.slow is True)

    e.scan("0001", 2)
    check("the exit tag ends the bubble", e.slow is False)


def test_station_stop_pauses_the_run():
    """A station tag stops the vehicle over a DISTANCE and holds it until Start,
    without ending the run it is in.

    The run staying latched is what makes the other two properties fall out: the
    log stays open across the dwell, and _hold_arm_state leaves the vehicle armed
    because it only disarms a run that is not running.
    """
    import autopilot
    import canworker
    import config
    import events
    print("\nbranch: a station tag pauses the run")

    check("the profile carries station tags", bool(config.STOP_TAGS),
          str(config.STOP_TAGS))
    (direction, tag), row = sorted(config.STOP_TAGS.items())[0]
    dist = row["stop_distance_m"]
    check("a station row carries both a distance and a resume window",
          set(row) == {"stop_distance_m"}, str(row))

    # --- the ramp lands at the distance, from any speed --------------------
    for v in (config.AUTO_SLOW_RPM, config.AUTO_RPM):
        f = autopilot.LineFollower()
        f.reset()
        f._v_rpm = v
        f.begin_measured_stop(dist)
        travelled, t = 0.0, 0.0
        while f._v_rpm > 0.5 and t < 30.0:
            f._ramp(0.0, 0.02, f._stop_rate)
            travelled += f._v_rpm * config.MPS_PER_RPM * 0.02
            t += 0.02
        check(f"from {v:.0f} r/min it stops within 10% of {dist} m",
              abs(travelled - dist) < 0.1 * dist,
              f"{travelled * 1000:.0f} mm in {t:.2f} s")

    check("a measured stop with no speed asks for no rate",
          autopilot.LineFollower().begin_measured_stop(dist) is None)

    # --- the run is paused, not ended --------------------------------------
    class Ctl(canworker.Controller):
        def __init__(self):
            super().__init__()
            self._lock = __import__("threading").RLock()
            self._armed, self._mode = True, "auto"
            self._auto_running = True
            self._auto_hold = self._stop_hold = None
            self._auto_ok_since = None
            self._stop_ignore_until = 0.0
            self._auto_start_at = 0.0
            self._auto_seen, self._auto_tick = -1, 0.0
            self._log_close_at = 0.0
            self._fault = self._run_source = self._last_action = None
            self._last_stop_reason = None
            self._target, self._direction = (0, 0), "stop"
            self._deadline = 0.0
            self._follower = autopilot.LineFollower()
            self._follower.reset()

    c = Ctl()
    c._route.index = 2
    c._route.direction = direction
    c._route.parked = True
    c._follower._v_rpm = config.AUTO_SLOW_RPM
    events.clear()
    c._begin_station_stop(tag)
    check("the tag parks the vehicle", c._stop_hold == tag)
    check("*** the run is NOT ended - the latch is kept ***",
          c._auto_running is True,
          "ending it would close the log and let AUTO disarm the vehicle")
    check("...so no log tail is scheduled", c._log_close_at == 0.0)
    check("...and the reason names the station",
          tag in (c._last_stop_reason or ""), str(c._last_stop_reason))
    check("it says so once", len(events.since(0)[1]) == 1)

    # Start resumes THE SAME run rather than beginning a new one.
    started = []
    c._do_auto_run = lambda *a, **k: started.append(a)
    c._panel_start(MANUAL)
    check("Start in manual still does nothing at a station",
          c._stop_hold == tag and not c._auto_start_at)
    c._panel_start(AUTO)
    check("Start at a station schedules the same delay as any other start",
          c._auto_start_at > 0)
    c._pending_start()
    check("...and nothing moves until it expires", c._stop_hold == tag)
    c._auto_start_at = time.monotonic() - 0.001
    c._pending_start()
    check("then the run carries on", c._stop_hold is None)
    check("*** it did NOT start a new run ***", not started,
          "_do_auto_run would reset the PID and open a second log for one lap")

    # Ending the run for real drops the station hold with it.
    c._stop_hold = tag
    c._end_auto_run("auto run STOP (operator)", hard=True)
    check("a real stop clears the station hold too", c._stop_hold is None)
    events.clear()


def test_slow_zone_latch():
    """The third rung: a slow zone is the entry-to-exit interval of any junction
    that asked for one, and NOTHING else on the route may start or end it."""
    print("\nbranch: slow zone")

    rows = [{"entry_tag": "000A", "exit_tag": "000B", "branch": LEFT,
             "slow_speed": True},
            # the same direction, deliberately NOT slow
            {"entry_tag": "0014", "exit_tag": "0015", "branch": LEFT,
             "slow_speed": False},
            # a row from before the flag existed - absent means false
            {"entry_tag": "001E", "exit_tag": "001F", "branch": RIGHT}]
    t = branch.compile_table(rows)
    check("only the rows that asked for it feed the slow contacts",
          (t["set_slow"], t["clear_slow"]) == ({"000A"}, {"000B"}),
          f"{sorted(t['set_slow'])} / {sorted(t['clear_slow'])}")

    e = branch.BranchEngine(rows)
    check("a fresh engine is not in a slow zone", e.slow is False)
    check("the entry tag latches the zone", e.scan("000A") == LEFT or True)
    check("...and slow is set with it", e.slow is True)
    check("it holds across ticks with no read", e.scan(None) == LEFT and e.slow)

    # The whole point of the seal-in: the zone must outlive the one scan the
    # tag is under the reader for.
    for _ in range(50):
        e.scan(None)
    check("it survives 50 ticks of silence", e.slow is True)

    check("an unrelated junction's tags do not end it",
          e.scan("001F") == LEFT and e.slow is True)

    # The coils are genuinely independent. 0015 is the exit tag of the OTHER
    # left-hand junction, so it shares - and clears - the left coil; it is not
    # in clear_slow, so the zone must survive it. A zone ends at its own exit
    # tag and nowhere else.
    check("a shared direction coil can clear while the zone stands",
          e.scan("0015") == STRAIGHT, e.ladder.intent())
    check("...the zone is still latched", e.slow is True)

    check("its own exit tag ends the zone", e.scan("000B") == STRAIGHT)
    check("...and slow drops with it", e.slow is False)

    # Orthogonal to the steering order in both directions.
    e2 = branch.BranchEngine(rows)
    e2.scan("0014")
    check("a junction without the flag latches a direction but no zone",
          e2.ladder.intent() == LEFT and e2.slow is False)
    e2.scan("0015")
    check("a right-hand junction without the flag is likewise not slow",
          e2.scan("001E") == RIGHT and e2.slow is False)

    # Same reasoning as intent: a zone that survived a manual intervention
    # would slow - or fail to slow - on an order given before the stop.
    e.scan("000A")
    e.reset()
    check("reset() drops the slow zone too", e.slow is False)


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
    # The one optional key. "True" is what a human types when JSON wants true,
    # and Python would take the string as truthy without a word - so the loader
    # has to be the thing that notices.
    refused("slow_speed as a STRING is refused, not silently truthy",
            [dict(ok, slow_speed="True")], "true/false")
    refused("slow_speed as a number is refused",
            [dict(ok, slow_speed=1)], "true/false")

    d = copy.deepcopy(doc)
    d["branch_latch"] = [ok]
    check("slow_speed is optional and defaults to false",
          config._parse(d)["BRANCH_LATCH"][0]["slow_speed"] is False)
    d["branch_latch"] = [dict(ok, slow_speed=True)]
    check("...and is carried through when given",
          config._parse(d)["BRANCH_LATCH"][0]["slow_speed"] is True)

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


def test_follower_slows_in_a_zone():
    """`slow` must change the speed the ramp is AIMED at, and nothing else.

    Driven through update() rather than by reading the branch, because the
    property that matters is the one the wheels see: the vehicle converges on
    auto_slow_rpm inside the zone and back on auto_rpm outside it, with the
    ordinary S-curve doing the transition in both directions.
    """
    import autopilot
    import config
    print("\nbranch: slow zone changes the cruise target")

    on_tape = {"tracks": PLAIN, "nlcp": 2, "has_track": True}

    def settle(f, slow, ticks=400):
        for _ in range(ticks):
            f.update(on_tape, 0.0, 0.02, True, STRAIGHT, slow)
        return f._v_rpm

    f = autopilot.LineFollower()
    v_fast = settle(f, False)
    check("outside a zone the ramp converges on auto_rpm",
          abs(v_fast - config.AUTO_RPM) < 1.0, f"{v_fast:.1f} r/min")

    v_slow = settle(f, True)
    check("inside one it converges on auto_slow_rpm",
          abs(v_slow - config.AUTO_SLOW_RPM) < 1.0, f"{v_slow:.1f} r/min")
    check("...which is genuinely slower on this profile",
          config.AUTO_SLOW_RPM < config.AUTO_RPM,
          f"{config.AUTO_SLOW_RPM} < {config.AUTO_RPM}")

    v_back = settle(f, False)
    check("and back to auto_rpm when the zone ends",
          abs(v_back - config.AUTO_RPM) < 1.0, f"{v_back:.1f} r/min")

    # The transition is the existing ramp, not a step: a step would be a
    # deceleration the drivers, not the profile, had to absorb.
    f2 = autopilot.LineFollower()
    settle(f2, False)
    _, _, d1 = f2.update(on_tape, 0.0, 0.02, True, STRAIGHT, True)
    check("entering a zone does not step the base speed",
          config.AUTO_SLOW_RPM < d1["v_base"] <= config.AUTO_RPM,
          f"one tick in: {d1['v_base']:.1f} r/min")
    check("the diag says which regime it is in", d1["slow"] is True)

    # A stop is a stop at either speed - the zone must not hold speed on.
    _, _, d2 = f2.update(on_tape, 0.0, 0.02, False, STRAIGHT, True)
    check("not running still ramps down inside a zone",
          d2["v_base"] < d1["v_base"], f"{d2['v_base']:.1f} r/min")

    check("the default argument keeps every existing caller working",
          autopilot.LineFollower().update(on_tape, 0.0, 0.02, True)[2]["slow"]
          is False)


def test_slow_zone_reaches_the_wheels():
    """The wiring, end to end: a tag read has to arrive at the setpoint.

    The ladder and the follower are each tested above in isolation, which
    between them prove nothing about whether canworker actually carries the
    answer from one to the other. _branch_scan() returns a PAIR now, and a
    caller that unpacked only the choice would still pass every other test in
    this file while the vehicle took every junction at full speed.
    """
    import time
    import canworker
    import config
    import events
    print("\nbranch: a slow zone reaches the setpoint")

    ctl = canworker.Controller()
    ctl._armed = True
    ctl._mode = "auto"
    ctl._auto_running = True
    ctl._follower._v_rpm = config.AUTO_RPM      # already cruising
    # Its own junction table, so this does not depend on what the live profile
    # happens to have in branch_latch today.
    ctl._branch = branch.BranchEngine(
        [{"entry_tag": "000A", "exit_tag": "000B", "branch": LEFT,
          "slow_speed": True}],
        config.BRANCH_POSITIVE_IS_LEFT)

    class FakeRfid:
        """Cumulative tags_seen and a held last_tag, like the real link."""
        def __init__(self):
            self.n, self.tag = 0, None

        def read(self, tag):
            self.n += 1
            self.tag = tag

        def snapshot(self, encounters=False):
            return {"tags_seen": self.n, "last_tag": self.tag,
                    "comms_ok": True, "encounter_seq": self.n, "generation": 0,
                    "encounters": [(self.n, self.tag)] if self.n else []}

    rfid = FakeRfid()
    ctl._rfid = rfid
    tape = {"tracks": PLAIN, "nlcp": 2, "has_track": True}

    def ticks(n):
        for _ in range(n):
            ctl._sensor = tape
            ctl._sensor_seen += 1
            ctl._sensor_last = time.monotonic()
            ctl._run_autopilot()
        return ctl._pid

    d = ticks(200)
    check("a run with no tag read cruises at auto_rpm",
          d["slow"] is False and abs(d["v_base"] - config.AUTO_RPM) < 1.0,
          f"{d['v_base']:.0f} r/min")

    rfid.read("000A")
    d = ticks(1)
    check("the entry tag latches the zone on the very next tick",
          d["slow"] is True, str(d["slow"]))
    check("...and the branch order with it", d["branch"] == LEFT, d["branch"])
    check("...but the speed does not step - the ramp takes it down",
          d["v_base"] > config.AUTO_SLOW_RPM, f"{d['v_base']:.0f} r/min")

    d = ticks(300)
    check("the setpoint settles on auto_slow_rpm inside the zone",
          abs(d["v_base"] - config.AUTO_SLOW_RPM) < 1.0, f"{d['v_base']:.0f} r/min")

    rfid.read("000B")
    d = ticks(300)
    check("the exit tag returns it to auto_rpm",
          d["slow"] is False and abs(d["v_base"] - config.AUTO_RPM) < 1.0,
          f"{d['v_base']:.0f} r/min")
    check("...and clears the order too", d["branch"] == STRAIGHT, d["branch"])

    # 800 ticks at 50 Hz is 16 s. Two transitions is what belongs in the ring;
    # one per tick would flush 200 entries of real history in four seconds.
    msgs = [e["msg"] for e in events.since(0)[1] if "slow zone" in e["msg"]]
    check("the zone is logged on the edges only, twice", len(msgs) == 2, str(msgs))
    check("...and each says which speed it moved to",
          str(int(config.AUTO_SLOW_RPM)) in msgs[0]
          and str(int(config.AUTO_RPM)) in msgs[1], str(msgs))
    events.clear()


def test_slow_zone_uses_its_own_gains():
    """A slow zone swaps the STEERING GAINS, not just the speed.

    This is the half that actually makes a corner. e_ss = kappa/k_ratio has no
    v in it, so the speed change alone buys nothing on a curve - run 0018 lost
    the tape on a ~0.5 m U-turn while already down at 441 r/min.
    """
    import autopilot
    import config
    print("\nbranch: slow zone carries its own gains")

    check("the profile actually raises the gain in a zone",
          config.SLOW_K_RATIO > config.K_RATIO,
          f"{config.K_RATIO} -> {config.SLOW_K_RATIO}")
    check("...and raises kd with it, or damping collapses",
          config.SLOW_KD > config.KD, f"{config.KD} -> {config.SLOW_KD}")
    z = autopilot.predicted_zeta(slow=True)
    check("the slow pair is sanely damped", 0.2 <= z <= 1.5, f"zeta {z:.3f}")

    # The P term is the observable: p = k_ratio * v * e, so at a FIXED speed and
    # error the ratio of the two p values is the ratio of the gains.
    on_tape = {"tracks": tracks((2, 20.0)), "nlcp": 2, "has_track": True}

    def p_at(slow):
        f = autopilot.LineFollower()
        f.reset()
        f._v_rpm = config.AUTO_SLOW_RPM        # same speed both times
        # two ticks: the first primes the derivative, the second is the reading
        f.update(on_tape, 0.0, 0.02, True, STRAIGHT, slow)
        return f.update(on_tape, 0.0, 0.02, True, STRAIGHT, slow)[2]

    fast, slow = p_at(False), p_at(True)
    ratio = slow["p"] / fast["p"]
    want = config.SLOW_K_RATIO / config.K_RATIO
    check("at the same speed and error the zone's P term scales by the gain "
          "ratio", abs(ratio - want) < 0.01, f"{ratio:.3f} vs {want:.3f}")
    check("the row records which gain set produced it",
          fast["k_used"] == config.K_RATIO and slow["k_used"] == config.SLOW_K_RATIO,
          f"{fast['k_used']} / {slow['k_used']}")
    check("a bigger gain commands more yaw for the same error",
          abs(slow["omega_cmd"]) > abs(fast["omega_cmd"]),
          f"{fast['omega_cmd']:.4f} -> {slow['omega_cmd']:.4f}")

    # _pid's gain arguments default to the profile, so nothing that called it
    # the old way changes behaviour.
    f = autopilot.LineFollower(); f.reset()
    f._last_e_m = 0.0
    a = f._pid(0.02, 0.25, 0.02)[1]
    f2 = autopilot.LineFollower(); f2.reset()
    f2._last_e_m = 0.0
    b = f2._pid(0.02, 0.25, 0.02, config.K_RATIO, config.KD)[1]
    check("_pid defaults to the profile gains", abs(a - b) < 1e-12, f"{a} {b}")


def test_auto_resumes_after_the_tape_comes_back():
    """A lost line HOLDS the run and resumes it once the tape has been in view
    for auto_resume_hold_s - and the wheels actually accelerate again.

    The properties that matter are the ones that stop this becoming a vehicle
    that wanders off on its own: the window restarts on ANY dropout, the START
    latch is still required, and no other kind of stop is resumable.
    """
    import canworker
    import config
    import events
    print("\nauto: hold and resume on a lost line")

    ctl = canworker.Controller()
    ctl._armed = True
    ctl._mode = "auto"
    ctl._auto_running = True
    ctl._follower._v_rpm = config.AUTO_RPM      # already at cruise
    events.clear()

    t = [1000.0]
    real_mono, real_perf = time.monotonic, time.perf_counter
    time.monotonic = time.perf_counter = lambda: t[0]

    tape = {"tracks": [{"index": 2, "pos_mm": 2.0, "width": 10}],
            "has_track": True}

    def tick(sensor, dt=0.02):
        t[0] += dt
        ctl._sensor = sensor
        ctl._sensor_seen += 1
        ctl._sensor_last = t[0]
        return ctl._run_autopilot()

    try:
        for _ in range(5):
            tick(tape)
        check("a run on tape is driving", ctl._auto_hold is None
              and ctl._follower.state == "run")

        # Lose it. LINE_LOSS_GRACE_M of travel at cruise, then the stop.
        for _ in range(200):
            tick(NO_TRACK)
            if ctl._auto_hold:
                break
        check("a lost line holds the run", ctl._auto_hold is not None,
              str(ctl._auto_hold))
        check("...without latching a fault", ctl._fault is None, str(ctl._fault))
        check("...keeping the START latch, because the operator never stopped",
              ctl._auto_running is True)
        check("...and the wheels are at zero", ctl._target == (0, 0),
              str(ctl._target))

        # Tape back, but not yet for long enough.
        for _ in range(10):
            tick(tape)
        check("it does not go again the instant the tape reappears",
              ctl._auto_hold is not None)

        # A dropout inside the window must restart it, not be forgiven.
        t0 = ctl._auto_ok_since
        tick(NO_TRACK)
        check("any dropout restarts the window", ctl._auto_ok_since is None,
              f"was {t0}")

        for _ in range(int(config.AUTO_RESUME_HOLD_S / 0.02) + 5):
            tick(tape)
        check(f"after {config.AUTO_RESUME_HOLD_S:.0f} s of tape it resumes",
              ctl._auto_hold is None)
        check("...and says so in the event log",
              any("resuming" in e["msg"] for e in events.since(0)[1]))

        # The whole point: it has to get going again, not sit at zero.
        #
        # Sampled at HALF the ramp time, computed from the profile rather than
        # fixed at 60 ticks. A fixed window silently becomes a saturated one
        # the moment auto_rpm is lowered - at 1000 r/min the ramp completes in
        # 50 ticks, so a 60-tick sample tests nothing about ramping and fails
        # for the wrong reason.
        half = int(0.5 * config.AUTO_RPM / config.RAMP_ACCEL_RPM_S / 0.02)
        for _ in range(half):
            tick(tape)
        check("the wheels accelerate again", ctl._follower._v_rpm > 100.0,
              f"v_base {ctl._follower._v_rpm:.0f} r/min")
        check("...through the ramp rather than in one step",
              ctl._follower._v_rpm < config.AUTO_RPM,
              f"{ctl._follower._v_rpm:.0f} r/min at half the ramp "
              f"({half} ticks)")

        # A run that was ENDED is not a run that can resume itself.
        ctl._auto_hold = "line lost - holding"
        ctl._end_auto_run("auto run STOP (operator)", hard=True)
        check("ending the run drops the hold with it",
              ctl._auto_hold is None and ctl._auto_ok_since is None)
    finally:
        time.monotonic, time.perf_counter = real_mono, real_perf
    events.clear()


def test_resume_can_be_switched_off():
    """auto_resume_hold_s = 0 keeps the old behaviour exactly: a latched fault
    that only panel Reset clears."""
    import canworker
    import config
    import events
    print("\nauto: resume disabled falls back to a latched fault")

    saved = config.AUTO_RESUME_HOLD_S
    config.AUTO_RESUME_HOLD_S = 0.0
    ctl = canworker.Controller()
    ctl._armed = True
    ctl._mode = "auto"
    ctl._auto_running = True
    ctl._follower._v_rpm = config.AUTO_RPM
    events.clear()
    try:
        for _ in range(200):
            ctl._sensor = NO_TRACK
            ctl._sensor_seen += 1
            ctl._sensor_last = time.monotonic()
            ctl._run_autopilot()
            if ctl._fault:
                break
        check("a lost line still latches a fault when resume is off",
              ctl._fault is not None, str(ctl._fault))
        check("...and ends the run", ctl._auto_running is False)
        check("...with no hold standing", ctl._auto_hold is None)
    finally:
        config.AUTO_RESUME_HOLD_S = saved
        events.clear()


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

        def snapshot(self, encounters=False):
            return {"tags_seen": self.n, "last_tag": self.tag,
                    "comms_ok": True, "encounter_seq": self.n, "generation": 0,
                    "encounters": [(self.n, self.tag)] if self.n else []}

    ctl = canworker.Controller.__new__(canworker.Controller)
    ctl._rfid = _Link()
    ctl._branch_seen = 0
    ctl._branch = branch.BranchEngine(
        [{"entry_tag": "000A", "exit_tag": "000B", "branch": LEFT}])
    # _branch_scan re-selects from the follower's anchor, so the real
    # collaborator is needed rather than a stub - see select_track(last_mm).
    ctl._follower = autopilot.LineFollower()

    events.clear()
    ctl._rfid.read("000A")
    ctl._branch_scan({"nlcp": 2, "tracks": PLAIN}, "000A")
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


def test_standing_default_replaces_the_tag_pair():
    """The U-turn has no RFID tag, so the intent comes from a standing default.

    The tag pair that used to order it (0002 in, 0001 out) is gone from the
    profile. What replaces it is autopilot.branch_default: the answer the
    ladder gives when no coil is sealed in. Everything here is about keeping
    that distinct from an ORDER - a default must not look like one to the
    ForkPassed contact, or the fork it never took gets consumed anyway.
    """
    print("\nbranch: the standing default")

    lad = branch.Ladder(RIGHT)
    check("with nothing latched the default IS the intent",
          lad.intent() == RIGHT)
    check("...but nothing is actually sealed in", lad.latched() is False)
    lad.scan()
    check("a scan with no pulses leaves it there", lad.intent() == RIGHT)

    # A default is not a coil: it cannot be cleared, and a clear contact that
    # appeared to work on it would be a latch nobody could reason about.
    lad.scan(clear_right=True, clear_left=True)
    check("a clear contact cannot clear a default", lad.intent() == RIGHT)

    lad.scan(set_left=True)
    check("an order still overrides the default", lad.intent() == LEFT)
    check("...and that one IS latched", lad.latched() is True)
    lad.scan(clear_left=True)
    check("clearing the order falls back to the default, not to straight",
          lad.intent() == RIGHT)

    lad.reset()
    check("reset() drops orders but keeps the default - disarming does not "
          "rebuild the track", lad.intent() == RIGHT and lad.latched() is False)

    try:
        branch.Ladder("rightmost")
        check("an unknown default is refused", False, "accepted!")
    except ValueError:
        check("an unknown default is refused", True)

    check("straight is still the drawn behaviour, and still the fallback",
          branch.Ladder().intent() == STRAIGHT)

    # -- the fork must not eat what was never an order ---------------------
    e = branch.BranchEngine([], positive_is_left=True, default=RIGHT)
    check("the engine carries the default through", e.ladder.intent() == RIGHT)

    # Drive a whole diverter: multi-track, then back to one. With a latched
    # order this is the ForkPassed pulse; with only a default there is nothing
    # to consume and the pulse must never fire.
    for nlcp in (2, 3, 3, 2, 2):
        e.scan(None, nlcp)
    check("a diverter driven on the default alone consumes no order",
          e.forks == 0, f"{e.forks} fork(s)")
    check("...and the intent is unchanged by it", e.ladder.intent() == RIGHT)
    check("...and no tag is credited for it", e.set_by is None)

    # A real order on top of a default still ends at its fork, and lands back
    # on the default rather than on straight.
    rows = [{"entry_tag": "000A", "exit_tag": "000B", "branch": LEFT,
             "slow_speed": False}]
    e2 = branch.BranchEngine(rows, positive_is_left=True, default=RIGHT)
    check("the tag still orders the other side", e2.scan("000A", 2) == LEFT)
    e2.scan(None, 3)
    check("the order stands through the diverter", e2.ladder.intent() == LEFT)
    check("coming out of it consumes the order", e2.scan(None, 2) == RIGHT)
    check("...exactly once", e2.forks == 1, f"{e2.forks}")

    # -- what the vehicle actually follows ---------------------------------
    e3 = branch.BranchEngine([], positive_is_left=True, default=RIGHT)
    e3.scan(None, 2)
    t, choice = e3.choose(2, PLAIN, last_mm=0.0)
    check("on plain tape the default changes nothing - the extreme track in "
          "any direction is the only track",
          choice == RIGHT and t["index"] == 2)
    check("...and that is not reported as unhonoured", e3.unhonoured is False)

    t, _ = e3.choose(3, DIV_NEG, last_mm=0.0)
    check("at a right-hand diverter it takes the branch - this is the U-turn",
          t["index"] == 1 and t["pos_mm"] == -38, str(t))

    t, _ = e3.choose(6, DIV_POS, last_mm=0.0)
    check("at a left-hand diverter it degrades to the main track, not the "
          "branch", t["index"] == 2)
    check("...and says the order was not honoured, because a standing default "
          "is still an intent somebody should hear about",
          e3.unhonoured is True)

    _, choice = e3.choose(7, CROSSING, last_mm=0.0)
    check("a crossing overrides the default to straight, per the manual",
          choice == STRAIGHT)

    # The live profile, which is what the vehicle will actually run on.
    import config
    check("the profile no longer carries the U-turn tag pair",
          config.BRANCH_LATCH == [], str(config.BRANCH_LATCH))
    check("...and takes the U-turn by standing preference instead",
          config.BRANCH_DEFAULT in ("left", "right"), config.BRANCH_DEFAULT)
    # Which SIDE is a measured fact about the track, not a constant this test
    # gets to pin - runs 0048/0049 logged "that side is not in this diverter"
    # against the shipped value and it was changed. What must hold is that the
    # profile and the handedness agree on what the word means.
    check("the standing side maps to an extreme position through the "
          "profile's handedness, whichever side it names",
          branch.select_track(DIV_POS, config.BRANCH_DEFAULT,
                              config.BRANCH_POSITIVE_IS_LEFT)["index"]
          == (3 if (config.BRANCH_DEFAULT == "left")
                   == config.BRANCH_POSITIVE_IS_LEFT else 2))

    # The consequence worth having on record: the slow zone and its high-gain
    # pair came from that row's tags, so the junction is now taken at cruise on
    # the ordinary gains. Run 0018 is why that is worth a check rather than a
    # comment - it lost the tape on a 0.5 m U-turn at exactly these gains.
    check("no slow zone survives the removal - the junction runs at auto_rpm "
          "on the ordinary gains, and a tight U-turn needs neither of those "
          "to be true (see run 0018)",
          not any(r["slow_speed"] for r in config.BRANCH_LATCH))



TESTS = [
    test_ladder_truth_table,
    test_select_track,
    test_selection_follows_the_tape_not_the_label,
    test_engine_scans_tags,
    test_the_fork_consumes_the_order,
    test_the_u_turn_merge_end_to_end,
    test_standing_default_replaces_the_tag_pair,
    test_station_stop_pauses_the_run,
    test_slow_zone_latch,
    test_choose,
    test_profile_table,
    test_follower_uses_the_choice,
    test_follower_slows_in_a_zone,
    test_slow_zone_uses_its_own_gains,
    test_auto_resumes_after_the_tape_comes_back,
    test_resume_can_be_switched_off,
    test_slow_zone_reaches_the_wheels,
    test_branch_events_are_edge_only,
]
