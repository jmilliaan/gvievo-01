"""Draw graph g4 (HOME-N2, right bay) on the rev1 survey map, from the vehicle's files (2026-11-06).

Writes g4-home.png and g4-overview.png into the current directory; run it from a scratch directory,
look at the result, copy the PNGs here. Needs Pillow and the DejaVu fonts. Reads only.
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

MAPS = os.path.expanduser("~/amr_maps/rev-boiacca-map-01/")
RES, OX, OY = 0.05, -96.52187077468524, -20.368095034827654   # rev1 map.yaml
BLUE, ORANGE, GREEN, CYAN, GREY = (30, 90, 220), (235, 120, 20), (0, 150, 60), (0, 170, 230), (165, 170, 178)
OUT = {"J-BMERGE:merge>J-N", "J-N:right>X1", "X1:cross>J-ML", "J-ML:merge>U-MRU"}
BACK = {"U-MRU:pivot>J-ML", "J-ML:left>J-STEM", "J-STEM:merge>J-SMERGE", "J-SMERGE:merge>J-SPLIT"}
DRAWN, UNUSED = "J-SPLIT:right>J-BMERGE", "J-SPLIT:left>J-BMERGE"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans"
BOLD, SMALL = ImageFont.truetype(f"{FONT}-Bold.ttf", 20), ImageFont.truetype(f"{FONT}.ttf", 16)
HALO = {"stroke_width": 3, "stroke_fill": (255, 255, 255)}
NODE_NAMES = {"J-BMERGE": (16, -12), "J-N": (-10, 16), "X1": (-40, -12), "J-ML": (16, -10), "J-STEM": (-92, 8),
              "J-SMERGE": (-60, -38), "J-SPLIT": (-30, -40)}


def main():
    graph = json.load(open(MAPS + "tapegraph/g4/graph.json"))
    base = Image.open(MAPS + "rev1/map.pgm").convert("RGB")
    legs = {leg["id"]: leg for leg in graph["legs"]}
    nodes = {}
    for leg in legs.values():
        if leg["from"] in NODE_NAMES and leg["id"] != UNUSED:
            nodes[leg["from"]] = leg["points"][0]
    h = base.size[1]

    def draw(name, x0, x1, y0, y1, k, stations, title):
        box = (int((x0 - OX) / RES), int(h - 1 - (y1 - OY) / RES), int((x1 - OX) / RES), int(h - 1 - (y0 - OY) / RES))
        im = base.crop(box).resize(((box[2] - box[0]) * k, (box[3] - box[1]) * k), Image.NEAREST)
        im = Image.blend(im, Image.new("RGB", im.size, (255, 255, 255)), 0.45)
        d = ImageDraw.Draw(im)

        def p(x, y):
            return ((x - OX) / RES - box[0]) * k, (h - 1 - (y - OY) / RES - box[1]) * k

        for lid, leg in legs.items():
            c = BLUE if lid in OUT else ORANGE if lid in BACK else CYAN if lid == DRAWN else GREY
            d.line([p(*q) for q in leg["points"]], fill=c, width=7 if lid == DRAWN else 5, joint="curve")
        for n, (x, y) in nodes.items():
            u, v = p(x, y)
            d.ellipse([u - 9, v - 9, u + 9, v + 9], fill=GREEN, outline=(0, 0, 0))
            du, dv = NODE_NAMES[n]
            d.text((u + du, v + dv), n, font=BOLD, fill=(0, 110, 45), **HALO)
        for st in graph["stations"]:
            if st["id"] not in stations:
                continue
            u, v = p(*st["pose"][:2])
            home = st["id"] == "HOME-N2"
            r = 12 if home else 8
            d.rectangle([u - r, v - r, u + r, v + r], fill=(255, 210, 0) if home else (200, 0, 110), outline=(0, 0, 0))
            d.text((u - 30, v + r + 3), st["id"] + (" (drawn)" if home else ""), font=BOLD if home else SMALL,
                   fill=(110, 70, 0) if home else (140, 0, 80), **HALO)
        d.text((14, 10), title, font=BOLD, fill=(20, 20, 20), **HALO)
        rows = [(BLUE, "outbound"), (ORANGE, "inbound (from the 10-24 pass)"),
                (CYAN, "J-SPLIT right to J-BMERGE: DRAWN from the sketch and logged poses"),
                (GREY, "left bay: tape stays, not on the route")]
        for i, (c, text) in enumerate(rows):
            y = im.size[1] - 22 * (len(rows) - i) - 8
            d.line([(14, y + 9), (50, y + 9)], fill=c, width=6)
            d.text((58, y), text, font=SMALL, fill=(20, 20, 20), **HALO)
        im.save(name)
        print(name, im.size)

    draw("g4-home.png", -14.5, 6.5, -5.5, 3.5, 6, {"HOME-N2", "ATT"}, "g4: HOME complex, home in the right bay")
    draw("g4-overview.png", -58, 8, -7, 49, 3, {"HOME-N2", "ATT", "MW-1", "MW-2", "MW-3", "MW-4"},
         "g4 on rev-boiacca-map-01 rev1: C-MRU")


main()
