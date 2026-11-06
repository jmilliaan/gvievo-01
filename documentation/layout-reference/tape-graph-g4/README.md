# Tape graph g4 on rev-boiacca-map-01 rev1 (2026-11-06)

Home moved to HOME-N2 in the right bay. Rendered on the survey map, in the map frame AMCL localises in.
Plan: `manuals/tracked-plan-4-position-engine.md`, sections 11.3 and 11.5.

| Image | Shows |
|---|---|
| `g4-home.png` | the HOME complex: the drawn right bay, HOME-N2, J-SMERGE and the real J-SPLIT |
| `g4-overview.png` | the whole C-MRU circuit |

`draw_g4.py` redraws both from the vehicle's graph (reads only); run it from a scratch directory.

| Item | Map frame, m | Source |
|---|---|---|
| J-SMERGE | (-10.59, -0.31) | MLS: tracks close up. Was labelled J-SPLIT until 2026-11-06 |
| J-SPLIT | (-5.55, -0.39) | MLS: tracks open. The real split, 5.1 m on |
| Right bay, `J-SPLIT:right>J-BMERGE` | (-5.55, -0.39) to (2.36, -1.41) | **Drawn**: operator's sketch, checked against 48 logged AMCL poses (median 3 cm, worst 10 cm) |
| HOME-N2 | (0.004, -1.225), 5.734 m along the bay | **Drawn** in g5 on the perpendicular from HOME-N, not taught. g4 had (0.04, -1.23), 5.770 m; the images still show that |
| Every other leg | | The 10-24 pass, as g1 |

g5 is g4 with only HOME-N2 moved. Tape spacing between the bays is 1.32 m on the floor; the map frame reads
about 1.2 m. The drawn bay stays where AMCL reads the AGV on that tape: a live scan at N2 fits the map best
within 5 cm of it, and clearly worse 20 cm further out.

A recorded lap from HOME-N2 should replace the drawn leg. The hand-derived drawings (`../c-mru-route`,
`../homepos-area-projection`) show the bay about 3.3 m long; the map says about 8 m, so trust this folder
for distances. Not resolved: which is right about the shape between J-STEM and J-SPLIT.
