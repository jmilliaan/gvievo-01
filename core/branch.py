"""Branch selection at a diverter: which of the sensor's tracks to follow.

The order comes from RFID station tags, held in a PLC seal-in latch:

    Branch_right = (SetRight OR Branch_right) AND NOT ClearRight AND NOT Branch_left
    Branch_left  = (SetLeft  OR Branch_left ) AND NOT ClearLeft  AND NOT Branch_right

Seal-in, explicit reset, mutual interlock. Transcribed rung for rung from the
drawn design, and deliberately kept that shape: the code is meant to be diffed
against the drawing, not merely to compute the same answer.

The seal-in is the whole point. A tag read is a ONE-SCAN pulse - the tag is
past the reader a tick later - so without the seal-in the order would evaporate
before the junction arrived. And because the latch is cleared only by an exit
tag placed after the junction, no input can change while a diverter is actually
in view, which is why this needs no second "commit" latch to hold the choice
steady mid-junction.

Track layout, from the MLS manual (section 8.4.1, table 17):

    "If only one line center point is found, it is output as LCP2. If a further
     line center point is found, it is output as LCP1 or LCP3, depending on its
     direction."  and  "LCP1 < LCP2 < LCP3 always applies."

  #LCP 2  LCP2         plain track
  #LCP 3  LCP1 + LCP2  diverter toward the negative side
  #LCP 6  LCP2 + LCP3  diverter toward the positive side
  #LCP 7  all three    90 deg crossing / double diverter

So the main track keeps LCP2 and the branch appears beside it. Selecting the
extreme position in the wanted direction therefore needs no case analysis on
#LCP, and degrades correctly on its own: ask for a side that is not there and
the extreme in that direction IS LCP2, the straight-through track. That is the
safe answer, and it falls out rather than being special-cased.

Deliberately imports neither config nor any clock - the caller supplies
handedness and the compiled tag table. Same rule plotrun.py follows: a module
that cannot read the vehicle profile cannot grow a hidden dependency on one
vehicle.
"""

STRAIGHT, LEFT, RIGHT = "straight", "left", "right"
DIRECTIONS = (LEFT, RIGHT)

# A 90 deg crossing is not a diverter. The manual's own advice is to navigate
# intersections by markers rather than by #LCP, so intent is ignored there and
# the vehicle holds the main track straight through.
CROSSING_NLCP = 7


class Ladder:
    """The intent latch. One scan per control tick, inputs frozen by the caller."""

    def __init__(self):
        self.left = False
        self.right = False

    def reset(self):
        """Disarm clears intent. A latch that survived a manual intervention
        would take a junction on an order given before whatever made the
        operator stop the vehicle."""
        self.left = False
        self.right = False

    def scan(self, set_left=False, clear_left=False,
             set_right=False, clear_right=False):
        """Solve both rungs in drawn order. Returns the resulting intent.

        Rung order is semantics, not layout. The second rung reads the `right`
        the first rung just wrote - that is PLC coil semantics, and it is what
        resolves a set-left and a set-right landing in the SAME scan: right
        wins. Swap the two lines and left wins instead. The case is rare enough
        never to show up in testing and to then bite once, at a junction where
        two tags sit close together, so it is asserted in the tests rather than
        left to whichever order someone types next.
        """
        self.right = (set_right or self.right) and not clear_right and not self.left
        self.left = (set_left or self.left) and not clear_left and not self.right
        return self.intent()

    def intent(self):
        if self.right:
            return RIGHT
        if self.left:
            return LEFT
        return STRAIGHT


def compile_table(rows):
    """Profile branch_latch rows -> the four pulse sets the rungs read.

    Several junctions may drive the same direction, so each contact is the OR
    of every tag wired to it - the generalisation of the drawn ladder from one
    junction per coil to many.
    """
    table = {"set_left": set(), "clear_left": set(),
             "set_right": set(), "clear_right": set()}
    for row in rows or ():
        side = row["branch"]
        table[f"set_{side}"].add(row["entry_tag"])
        table[f"clear_{side}"].add(row["exit_tag"])
    return table


class BranchEngine:
    """Ladder plus the compiled tag table. Scanned once per control tick."""

    def __init__(self, rows=(), positive_is_left=True):
        self.ladder = Ladder()
        self.table = compile_table(rows)
        self.positive_is_left = bool(positive_is_left)
        self.set_by = None          # the tag that set the live latch
        self.unmatched = 0          # tags read that no rung wires up
        self.unhonoured = False     # ordered a side that was not there

    def reset(self):
        self.ladder.reset()
        self.set_by = None
        self.unhonoured = False

    def scan(self, tag=None):
        """One scan against one tag id (or None for a tick with no read).

        Returns the intent. The caller must pass a genuine one-shot: a tag held
        live for several ticks would re-trigger its rung every tick, which for a
        set contact is harmless and for a clear contact would pin the latch off.
        """
        was = self.ladder.intent()
        if tag is not None and not any(tag in s for s in self.table.values()):
            self.unmatched += 1
        intent = self.ladder.scan(
            set_left=tag in self.table["set_left"],
            clear_left=tag in self.table["clear_left"],
            set_right=tag in self.table["set_right"],
            clear_right=tag in self.table["clear_right"])
        if intent != was:
            self.set_by = tag if intent != STRAIGHT else None
        return intent

    def choose(self, nlcp, tracks):
        """Pick the track to follow. Returns (track_or_None, choice).

        Sets .unhonoured when a real diverter was in view and the ordered side
        was not one of the tracks in it - the vehicle carries straight on, which
        is safe, but the order was not carried out and someone should hear so.
        """
        choice = STRAIGHT if nlcp == CROSSING_NLCP else self.ladder.intent()
        track = select_track(tracks, choice, self.positive_is_left)
        self.unhonoured = bool(
            choice in DIRECTIONS and track is not None
            and track.get("index") == 2 and nlcp not in (None, 0, 2,
                                                         CROSSING_NLCP))
        return track, choice


def select_track(tracks, choice, positive_is_left=True):
    """Pick a track. tracks: [{"index", "pos_mm"}, ...]. Returns the dict or None.

    STRAIGHT takes LCP2 when present, because the sensor keeps the main track
    there. LEFT/RIGHT take the extreme position on the wanted side, which needs
    no knowledge of #LCP and degrades to LCP2 when that side is absent.
    """
    usable = [t for t in tracks or [] if t.get("pos_mm") is not None]
    if not usable:
        return None
    if choice == STRAIGHT:
        main = [t for t in usable if t.get("index") == 2]
        return main[0] if main else min(usable, key=lambda t: abs(t["pos_mm"]))
    want_positive = (choice == LEFT) == bool(positive_is_left)
    return (max if want_positive else min)(usable, key=lambda t: t["pos_mm"])
