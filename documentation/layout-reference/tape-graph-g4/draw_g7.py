"""Draw graph g7, the complete AGV-01 tape graph, on the map, to scale, from the vehicle's files (2026-11-07).

Writes g7-overview.png into the current directory; run it from a scratch directory, look at the result,
copy the PNG here. Needs Pillow and the DejaVu fonts. Reads only.
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

MAPS = os.path.expanduser("~/amr_maps/rev-boiacca-map-01/")
TEACH = os.path.expanduser("~/.amr/teach/rev-boiacca-map-01-rev2/")
RES, OX, OY = 0.05, -96.52187077468524, -20.368095034827654  # map.yaml
K = 2
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans"
BOLD, SMALL = ImageFont.truetype(f"{FONT}-Bold.ttf", 24), ImageFont.truetype(f"{FONT}.ttf", 20)
HALO = {"stroke_width": 3, "stroke_fill": (255, 255, 255)}
SHARED, MRU, BTU, UNUSED = (40, 50, 70), (30, 90, 220), (215, 75, 15), (165, 170, 178)
JUNCTION, STOP, HOME, AREA = (0, 150, 60), (200, 0, 110), (255, 210, 0), (70, 170, 90)
BTU_LEGS = {"J-N:straight>J-S", "J-S:straight>X2", "X2:cross>J-LV", "J-LV:right>J-ML", "J-ML:merge>J-STEM"}
MRU_LEGS = {"J-N:right>X1", "X1:cross>J-ML", "J-ML:merge>U-MRU", "U-MRU:pivot>J-ML", "J-ML:left>J-STEM"}
NAMES = {"J-BMERGE": (-20, -34), "J-N": (12, 10), "J-S": (-28, 28), "X2": (-50, 8), "J-LV": (-60, 8), "X1": (-36, -44),
         "J-ML": (14, -8), "J-STEM": (-112, -12), "J-SMERGE": (10, -30), "J-SPLIT": (-14, -32), "U-MRU": (-30, 14)}
MACHINES = {"R2-1": "BTU24/16", "R2-2": "BTU23/15", "R2-3": "BTU22/14", "R2-4": "BTU21/13", "R2-5": "BTU20/12",
            "R2-6": "BTU19/11", "R2-7": "BTU18/10", "R2-8": "BTU17/9"}
SHOW = {"HOME-N2", "ATT", "MW-1", "MW-2", "MW-3", "MW-4", *MACHINES}


def main():
    x0, x1, y0, y1 = -86.0, 7.0, -8.0, 50.0
    graph = json.load(open(MAPS + "tapegraph/g7/graph.json"))
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
    colour = lambda lid: (BTU if lid in BTU_LEGS else MRU if lid in MRU_LEGS  # noqa: E731
                          else UNUSED if lid == "J-SPLIT:left>J-BMERGE" else SHARED)
    nodes = {}
    for leg in sorted(graph["legs"], key=lambda g: g["id"] in BTU_LEGS):
        d.line([p(*q) for q in leg["points"]], fill=colour(leg["id"]), width=4, joint="curve")
        if leg["from"] in NAMES:
            nodes.setdefault(leg["from"], leg["points"][0])
    for name, (x, y) in nodes.items():
        u, v = p(x, y)
        d.ellipse([u - 7, v - 7, u + 7, v + 7], fill=JUNCTION, outline=(0, 0, 0))
        du, dv = NAMES[name]
        d.text((u + du, v + dv), name, font=BOLD, fill=(0, 100, 40), **HALO)
    for st in graph["stations"]:
        if st["id"] not in SHOW:
            continue
        u, v = p(*st["pose"][:2])
        home = st["id"] == "HOME-N2"
        r = 10 if home else 7
        d.rectangle([u - r, v - r, u + r, v + r], fill=HOME if home else STOP, outline=(0, 0, 0))
        if st["id"] in MACHINES:
            d.text((u - 36, v - 58), st["id"], font=SMALL, fill=(140, 0, 80), **HALO)
            d.text((u - 50, v - 34), MACHINES[st["id"]], font=SMALL, fill=(90, 40, 60), **HALO)
        elif st["id"].startswith("MW"):
            d.text((u - 30, v + 12), st["id"], font=SMALL, fill=(140, 0, 80), **HALO)
        else:
            d.text((u - 36, v + 14), st["id"], font=BOLD, fill=(110, 70, 0), **HALO)
    d.text((14, 10), "g7: the complete AGV-01 tape graph, C-MRU and C-BTU. To scale, map frame", font=BOLD,
           fill=(20, 20, 20), **HALO)
    rows = [(SHARED, "both circuits"), (MRU, "C-MRU only"), (BTU, "C-BTU only, recorded 2026-11-07"),
            (UNUSED, "north bay, not on a route"), (JUNCTION, "junction"), (STOP, "stop"), (AREA, "high-speed area")]
    for i, (c, text) in enumerate(rows):
        y = im.size[1] - 27 * (len(rows) - i) - 8
        d.rectangle([14, y + 4, 46, y + 18], fill=c)
        d.text((54, y), text, font=SMALL, fill=(20, 20, 20), **HALO)
    u0, v0 = im.size[0] - 240, im.size[1] - 30
    d.line([(u0, v0), (u0 + 10 / RES * K, v0)], fill=(20, 20, 20), width=4)
    d.text((u0, v0 - 28), "10 m", font=SMALL, fill=(20, 20, 20), **HALO)
    im.save("g7-overview.png")
    print("g7-overview.png", im.size)


main()
