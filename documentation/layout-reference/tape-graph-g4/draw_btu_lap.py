"""Draw a recorded C-BTU lap over graph g6 on the map, to scale, from the vehicle's files (2026-11-07).

Writes btu-lap-1.png into the current directory; run it from a scratch directory, look at the result,
copy the PNG here. Needs Pillow and the DejaVu fonts. Reads only.
"""
import glob
import json
import math
import os

from PIL import Image, ImageDraw, ImageFont

MAPS = os.path.expanduser("~/amr_maps/rev-boiacca-map-01/")
TEACH = os.path.expanduser("~/.amr/teach/rev-boiacca-map-01-rev2/")
RES, OX, OY = 0.05, -96.52187077468524, -20.368095034827654  # map.yaml
K = 2
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans"
BOLD, SMALL = ImageFont.truetype(f"{FONT}-Bold.ttf", 24), ImageFont.truetype(f"{FONT}.ttf", 20)
HALO = {"stroke_width": 3, "stroke_fill": (255, 255, 255)}
LAP, ROUTE, HOME, STOP, EST = (205, 70, 15), (150, 158, 170), (255, 210, 0), (200, 0, 110), (255, 255, 255)
JUNCTION, ODD, AREA = (0, 150, 60), (120, 40, 200), (70, 170, 90)
# Forks of the lap by map position, from its fork log; J-S and X2 by the order they come after J-N.
NAMES = [("J-BMERGE", 2.28, -1.38, 10, 8), ("J-N", -10.57, -1.45, 12, 8), ("J-S", -11.11, -1.47, -28, 28),
         ("X2", -11.81, -1.36, -50, 8), ("J-LV", -75.78, 3.13, -60, 8), ("J-ML", -10.55, 12.31, 12, -8),
         ("J-STEM", -11.65, 0.80, -72, -22), ("J-SMERGE", -10.49, -0.32, 10, -28), ("J-SPLIT", -5.48, -0.44, -14, -28)]
JOINTS = [(-20.56, -0.82), (-70.63, 2.74)]
ESTIMATED = {"R2-3": (-54.3, 16.5), "R2-2": (-62.2, 17.1), "R2-1": (-70.2, 17.6)}
MARKED = {"M19": "R2-4", "M20": "R2-5", "M21": "R2-6", "M22": "R2-7", "M23": "R2-8"}
LENGTHS = [("J-N to J-S 0.6 m, J-S to X2 0.8 m", (-40, -3.4)), ("X2 to J-LV: 64 m", (-52, 2.6)),
           ("J-LV to J-ML, along row 2: 83 m", (-58, 21.0))]


def main():
    x0, x1, y0, y1 = -86.0, 7.0, -8.0, 50.0
    graph = json.load(open(MAPS + "tapegraph/g6/graph.json"))
    rec = json.load(open(sorted(glob.glob(TEACH + "passes/C-BTU-*.json"))[0]))
    marks = json.load(open(TEACH + "marks.json"))
    areas = json.load(open(TEACH + "areas.json"))
    base = Image.open(MAPS + "rev2/map.pgm").convert("RGB")
    h = base.size[1]
    box = (int((x0 - OX) / RES), int(h - 1 - (y1 - OY) / RES), int((x1 - OX) / RES), int(h - 1 - (y0 - OY) / RES))
    im = base.crop(box).resize(((box[2] - box[0]) * K, (box[3] - box[1]) * K), Image.NEAREST)
    im = Image.blend(im, Image.new("RGB", im.size, (255, 255, 255)), 0.55)
    d = ImageDraw.Draw(im, "RGBA")

    def p(x, y):
        return ((x - OX) / RES - box[0]) * K, (h - 1 - (y - OY) / RES - box[1]) * K

    for area in areas.values():
        d.polygon([p(*q) for q in area["polygon"]], fill=(*AREA, 55), outline=(*AREA, 200))
    for leg in graph["legs"]:
        if leg["id"] != "J-SPLIT:left>J-BMERGE":
            d.line([p(*q) for q in leg["points"]], fill=ROUTE, width=4, joint="curve")
    pts = [p(s[1], s[2]) for s in rec["samples"]]
    d.line(pts, fill=LAP, width=4, joint="curve")

    def tag(text, u, v, du, dv, font=BOLD, fill=(20, 20, 20)):
        d.text((u + du, v + dv), text, font=font, fill=fill, **HALO)

    for name, x, y, du, dv in NAMES:
        u, v = p(x, y)
        d.ellipse([u - 7, v - 7, u + 7, v + 7], fill=JUNCTION, outline=(0, 0, 0))
        tag(name, u, v, du, dv, fill=(0, 100, 40))
    for x, y in JOINTS:
        u, v = p(x, y)
        d.ellipse([u - 6, v - 6, u + 6, v + 6], fill=ODD, outline=(0, 0, 0))
        tag("? joint", u, v, -24, 10, SMALL, ODD)
    for mid, sid in MARKED.items():
        u, v = p(*marks[mid]["pose"][:2])
        d.rectangle([u - 7, v - 7, u + 7, v + 7], fill=STOP, outline=(0, 0, 0))
        tag(f"{sid} ({mid})", u, v, -30, -30, SMALL, (140, 0, 80))
    for sid, (x, y) in ESTIMATED.items():
        u, v = p(x, y)
        d.rectangle([u - 7, v - 7, u + 7, v + 7], fill=EST, outline=STOP, width=3)
        tag(f"{sid} est.", u, v, -30, -30, SMALL, (140, 0, 80))
    for st in graph["stations"]:
        if st["id"] in ("HOME-N2", "ATT"):
            u, v = p(*st["pose"][:2])
            d.rectangle([u - 9, v - 9, u + 9, v + 9], fill=HOME if st["id"] == "HOME-N2" else STOP, outline=(0, 0, 0))
            tag(st["id"], u, v, -30, 12, BOLD, (110, 70, 0))
    for text, (x, y) in LENGTHS:
        tag(text, *p(x, y), 0, 0, SMALL)
    length = rec["samples"][-1][0] - rec["samples"][0][0]
    gap = math.dist(rec["samples"][0][1:], rec["samples"][-1][1:])
    d.text((14, 10), f"C-BTU lap {rec['started']}: {length:.0f} m, ends {gap * 100:.0f} cm from its start. To scale, map frame",
           font=BOLD, fill=(20, 20, 20), **HALO)
    rows = [("line", LAP, "the lap (recorded, not in the active graph)"), ("line", ROUTE, "g6: the taught C-MRU route"),
            ("dot", JUNCTION, "junction"), ("dot", ODD, "fork reading with no junction: looks like a tape joint"),
            ("box", STOP, "stop marked on the lap"), ("est", STOP, "stop estimated at the 8 m spacing, not marked"),
            ("area", AREA, "high-speed area")]
    for i, (kind, c, text) in enumerate(rows):
        y = im.size[1] - 27 * (len(rows) - i) - 8
        if kind == "line":
            d.line([(14, y + 9), (46, y + 9)], fill=c, width=5)
        elif kind == "dot":
            d.ellipse([24, y + 2, 38, y + 16], fill=c, outline=(0, 0, 0))
        elif kind == "area":
            d.rectangle([20, y + 2, 42, y + 16], fill=(*c, 80), outline=c)
        else:
            d.rectangle([24, y + 2, 38, y + 16], fill=(255, 255, 255) if kind == "est" else c, outline=c, width=2)
        d.text((54, y), text, font=SMALL, fill=(20, 20, 20), **HALO)
    # 10 m scale bar
    u0, v0 = im.size[0] - 240, im.size[1] - 30
    d.line([(u0, v0), (u0 + 10 / RES * K, v0)], fill=(20, 20, 20), width=4)
    d.text((u0, v0 - 24), "10 m", font=SMALL, fill=(20, 20, 20), **HALO)
    im.save("btu-lap-1.png")
    print("btu-lap-1.png", im.size)


main()
