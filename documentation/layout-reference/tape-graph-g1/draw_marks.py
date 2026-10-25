"""Redraw the marks-*.png images of this folder from the vehicle's files (2026-10-25).

Reads the rev1 survey map, graph g1, the junction anchors and the marks (with their roles) and
writes the four images into the current directory. Run it from a scratch directory, look at the
result, then copy the PNGs here. Needs Pillow and the DejaVu fonts.
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

MAPS = os.path.expanduser("~/amr_maps/rev-boiacca-map-01/")
TEACH = os.path.expanduser("~/.amr/teach/rev-boiacca-map-01-rev1/")
RES, OX, OY = 0.05, -96.52187077468524, -20.368095034827654   # rev1 map.yaml
OUTBOUND = {"J-BMERGE:merge>J-N", "J-N:right>X1", "X1:cross>J-ML", "J-ML:merge>U-MRU"}
BLUE, ORANGE, GREEN = (30, 90, 220), (235, 120, 20), (0, 150, 60)
COLOUR = {"out": (200, 0, 110), "in": (130, 40, 200), "uturn": (220, 30, 30), "ref": (120, 120, 120)}
LEGEND = [("out", "outbound stop (ATT, MW: release empty)"), ("in", "inbound stop (ME: attach full)"),
          ("uturn", "mid-line U-turn point (UT)"), ("ref", "reference mark, no role")]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans"
BOLD, SMALL = ImageFont.truetype(f"{FONT}-Bold.ttf", 20), ImageFont.truetype(f"{FONT}.ttf", 15)
HALO = {"stroke_width": 3, "stroke_fill": (255, 255, 255)}


def kind(mark):
    role = mark.get("role", "")
    if role.startswith("UT-"):
        return "uturn"
    if role.startswith("ME-"):
        return "in"
    return "out" if role else "ref"


def symbol(d, u, v, k, r=10):
    c = COLOUR[k]
    if k == "uturn":
        d.ellipse([u - r, v - r, u + r, v + r], fill=c, outline=(0, 0, 0))
    elif k == "ref":
        d.rectangle([u - r + 2, v - r + 2, u + r - 2, v + r - 2], fill=c, outline=(0, 0, 0))
    else:
        d.polygon([(u, v - r - 1), (u + r, v), (u, v + r + 1), (u - r, v)], fill=c, outline=(0, 0, 0))


class Canvas:
    def __init__(self, base, x0, x1, y0, y1, k):
        self.h = base.size[1]
        a, b = self._px(x0, y1), self._px(x1, y0)
        self.box = (int(a[0]), int(a[1]), int(b[0]), int(b[1]))
        self.k = k
        size = ((self.box[2] - self.box[0]) * k, (self.box[3] - self.box[1]) * k)
        im = base.crop(self.box).resize(size, Image.NEAREST)
        self.im = Image.blend(im, Image.new("RGB", im.size, (255, 255, 255)), 0.4)
        self.d = ImageDraw.Draw(self.im)

    def _px(self, x, y):
        return (x - OX) / RES, self.h - 1 - (y - OY) / RES

    def p(self, x, y):
        u, v = self._px(x, y)
        return (u - self.box[0]) * self.k, (v - self.box[1]) * self.k

    def inside(self, x, y):
        u, v = self.p(x, y)
        return 0 <= u < self.im.size[0] and 0 <= v < self.im.size[1]


def legend(c, corner):
    d = c.d
    lx, ly = 16, 16 if corner == "tl" else c.im.size[1] - 200
    d.rectangle([lx - 8, ly - 8, lx + 390, ly + 178], fill=(255, 255, 255), outline=(0, 0, 0))
    for i, (col, text) in enumerate(((BLUE, "g1 legs, outbound"), (ORANGE, "g1 legs, inbound"))):
        d.line([(lx, ly + 10 + 24 * i), (lx + 36, ly + 10 + 24 * i)], fill=col, width=4)
        d.text((lx + 46, ly + 2 + 24 * i), text, fill=(0, 0, 0), font=SMALL)
    d.ellipse([lx + 12, ly + 50, lx + 24, ly + 62], fill=GREEN)
    d.text((lx + 46, ly + 50), "junction", fill=(0, 0, 0), font=SMALL)
    for i, (k, text) in enumerate(LEGEND):
        y = ly + 72 + 22 * i
        symbol(d, lx + 18, y + 8, k, r=8)
        d.text((lx + 46, y), text, fill=(0, 0, 0), font=SMALL)
    metres = max(m for m in (1, 2, 5, 10) if m / RES * c.k <= 300)
    bar = metres / RES * c.k
    d.line([(lx, ly + 170), (lx + bar, ly + 170)], fill=(0, 0, 0), width=3)
    d.text((lx + bar + 6, ly + 162), f"{metres} m", fill=(0, 0, 0), font=SMALL)


def render(data, view, name, place, labels=True, corner="tl", key=True):
    graph, anchors, marks = data["graph"], data["anchors"], data["marks"]
    c = Canvas(data["base"], *view)
    d = c.d
    for leg in graph["legs"]:
        d.line([c.p(*q) for q in leg["points"]], fill=BLUE if leg["id"] in OUTBOUND else ORANGE, width=4)
    end = next(g for g in graph["legs"] if g["id"] == "J-ML:merge>U-MRU")["points"][-1]
    u, v = c.p(*end)
    d.ellipse([u - 9, v - 9, u + 9, v + 9], outline=COLOUR["uturn"], width=3)
    if c.inside(*end):
        d.text((u + 12, v - 30), "U-MRU (tape end)", fill=(190, 0, 0), font=SMALL, **HALO)
    for n, (x, y) in anchors.items():
        u, v = c.p(x, y)
        d.ellipse([u - 7, v - 7, u + 7, v + 7], fill=GREEN, outline=(0, 0, 0))
        d.text((u - 10, v + 9), n, fill=(0, 110, 40), font=SMALL, **HALO)
    for mid, m in marks.items():
        k = kind(m)
        u, v = c.p(*m["pose"][:2])
        symbol(d, u, v, k)
        if labels or k == "ref":
            dx, dy = place(k)
            text = f"{mid} {m['role']}" if m.get("role") else mid
            colour = tuple(int(0.8 * ch) for ch in COLOUR[k])
            d.text((u + dx, v + dy), text, fill=colour, font=BOLD, **HALO)
    if key:
        legend(c, corner)
    c.im.save(name)
    print(name, c.im.size)


def main():
    base = Image.open(MAPS + "rev1/map.pgm").convert("RGB")
    with open(MAPS + "tapegraph/g1/graph.json") as fh:
        graph = json.load(fh)
    with open(TEACH + "marks.json") as fh:
        marks = json.load(fh)
    with open(TEACH + "anchors.json") as fh:
        anchors = json.load(fh)
    data = {"base": base, "graph": graph, "marks": marks, "anchors": anchors}
    xs = [q[0] for g in graph["legs"] for q in g["points"]]
    ys = [q[1] for g in graph["legs"] for q in g["points"]]
    beside = {"out": (-30, -40), "uturn": (-30, -66), "in": (-30, 16), "ref": (12, -26)}
    render(data, (min(xs) - 3, max(xs) + 3, min(ys) - 3, max(ys) + 3, 2), "marks-overview.png",
           lambda k: (12, -26), labels=False, corner="bl")
    render(data, (-14, 6, -5, 13, 6), "marks-home-junctions.png", lambda k: (14, -34), corner="bl")
    render(data, (-58, -5, 36, 48, 3), "marks-mru-line.png", beside.get, corner="bl")
    render(data, (-56, -20, 41.5, 47, 5), "marks-mru-machines.png", beside.get, key=False)


if __name__ == "__main__":
    main()
