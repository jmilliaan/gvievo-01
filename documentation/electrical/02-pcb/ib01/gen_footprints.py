"""Footprints for the LCSC parts of IB-01, drawn from the manufacturers' drawings (2026-11-16).

    python3.11 gen_footprints.py      -> ib01.pretty/*.kicad_mod

Parts (datasheets on lcsc.com/datasheet/<C-number>.pdf):
  Kefa KF2EDGVM-3.5-nP     header 3.5 mm, vertical, flanged   (C441407 ... ; drawing Rev A 2021-03-15)
      hole 1.40 +0.10/0, pin 0.8 sq; body length n*3.5 + 10.4 (ears included), depth 7.0,
      pin row 3.0 mm from one long face (which face is not stated: courtyard covers both ways)
  Degson 2EDGVM-5.08-02P   header 5.08 mm, vertical, flanged  (C699489)
      hole 1.70, pin 1.0 sq; body 20.32 x 8.2, pin row 3.75 from one long face
  Kefa KF2EDGVM-7.62-2P    header 7.62 mm, vertical, flanged  (C441450)
      hole 1.60 +0.10/0, pin 1.0 sq; body 25.4 x 8.7, pin row 3.8 from one long face
  XFCN XF-508P-B-B         MINI blade fuse holder, 500 V      (C19727305)
      4 pins on a 9.80 x 3.40 rectangle, holes 1.6 min, pins 1.6 x 0.4; body 16.0 x 6.7, centred on the pins
      drawn with 1.8 mm holes: the pin is 1.65 mm across its diagonal, 1.7 left no margin for the hole tolerance
The flange screws thread into the header body: no extra PCB holes.
Pad 1 is square. Footprint origin = pad 1.
"""
import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, 'ib01.pretty')
NS = uuid.UUID('7b0c2e1a-0c1d-4f7e-8a51-1b01f00710b0')
os.makedirs(LIB, exist_ok=True)


def f(v):
    return ('%.4f' % v).rstrip('0').rstrip('.')


def footprint(name, descr, pads, body, crtyd, value_y, ref_y, extra_silk=()):
    """pads: list of (number, x, y, drill, size, square). body/crtyd: (x1, y1, x2, y2)."""
    u = lambda k: str(uuid.uuid5(NS, name + k))
    out = ['(footprint "%s"' % name, '\t(version 20241229)', '\t(generator "gen_footprints.py")',
           '\t(layer "F.Cu")', '\t(descr "%s")' % descr, '\t(attr through_hole)',
           '\t(property "Reference" "REF**" (at 0 %s 0) (layer "F.SilkS") (uuid "%s") (effects (font (size 1 1) (thickness 0.15))))' % (f(ref_y), u('ref')),
           '\t(property "Value" "%s" (at 0 %s 0) (layer "F.Fab") (uuid "%s") (effects (font (size 1 1) (thickness 0.15))))' % (name, f(value_y), u('val'))]

    def rect(layer, r, w, key):
        x1, y1, x2, y2 = r
        out.append('\t(fp_rect (start %s %s) (end %s %s) (stroke (width %s) (type solid)) (fill no) (layer "%s") (uuid "%s"))'
                   % (f(x1), f(y1), f(x2), f(y2), f(w), layer, u(key)))
    rect('F.Fab', body, 0.1, 'fab')
    sx1, sy1, sx2, sy2 = body
    rect('F.SilkS', (sx1 - 0.11, sy1 - 0.11, sx2 + 0.11, sy2 + 0.11), 0.12, 'silk')
    rect('F.CrtYd', crtyd, 0.05, 'crtyd')
    for i, (x1, y1, x2, y2) in enumerate(extra_silk):
        out.append('\t(fp_line (start %s %s) (end %s %s) (stroke (width 0.12) (type solid)) (layer "F.SilkS") (uuid "%s"))'
                   % (f(x1), f(y1), f(x2), f(y2), u('xs%d' % i)))
    for i, (num, x, y, drill, size, square) in enumerate(pads):
        out.append('\t(pad "%s" thru_hole %s (at %s %s) (size %s %s) (drill %s) (layers "*.Cu" "*.Mask") (uuid "%s"))'
                   % (num, 'rect' if square else 'circle', f(x), f(y), f(size), f(size), f(drill), u('pad%d' % i)))
    out.append(')')
    with open(os.path.join(LIB, name + '.kicad_mod'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(out) + '\n')
    return name


def header(name, descr, n, pitch, drill, pad, body_len, row_from_face, depth):
    """Vertical pluggable header: pins on y = 0, body centred on the pin span along x."""
    span = (n - 1) * pitch
    x1 = span / 2 - body_len / 2
    x2 = span / 2 + body_len / 2
    y1, y2 = -row_from_face, depth - row_from_face           # body as drawn (one face 'row_from_face' from the pins)
    far = max(row_from_face, depth - row_from_face)
    crt = (x1 - 0.25, -far - 0.25, x2 + 0.25, far + 0.25)     # courtyard symmetric: the face is not stated
    pads = [(str(i + 1), i * pitch, 0, drill, pad, i == 0) for i in range(n)]
    # pin-1 mark: short silk line below pad 1, outside the body
    mark = [(-0.8, y2 + 0.5, 0.8, y2 + 0.5)]
    return footprint(name, descr, pads, (x1, y1, x2, y2), crt, far + 1.6, -far - 1.6, mark)


made = []
for n in (2, 4, 5, 6, 7, 9, 12):
    made.append(header('KF2EDGVM-3.5-%dP' % n, 'Kefa KF2EDGVM-3.5-%dP, 3.5 mm vertical pluggable header, screw flange' % n,
                       n, 3.5, 1.45, 2.3, n * 3.5 + 10.4, 3.0, 7.0))
made.append(header('2EDGVM-5.08-02P', 'Degson 2EDGVM-5.08-02P-14-100A(H), 5.08 mm vertical pluggable header, screw flange',
                   2, 5.08, 1.75, 3.0, 20.32, 3.75, 8.2))
made.append(header('KF2EDGVM-7.62-2P', 'Kefa KF2EDGVM-7.62-2P, 7.62 mm vertical pluggable header, screw flange',
                   2, 7.62, 1.7, 3.2, 25.4, 3.8, 8.7))
# Fuse holder: pins (0,0) (0,3.4) = contact 1, (9.8,0) (9.8,3.4) = contact 2; body centred on the pin rectangle
fx1, fy1 = 4.9 - 8.0, 1.7 - 3.35
made.append(footprint('XF-508P-B-B', 'XFCN XF-508P-B-B MINI blade fuse holder, 500 V, PCB',
                      [('1', 0, 0, 1.8, 2.8, True), ('1', 0, 3.4, 1.8, 2.8, True),
                       ('2', 9.8, 0, 1.8, 2.8, False), ('2', 9.8, 3.4, 1.8, 2.8, False)],
                      (fx1, fy1, fx1 + 16.0, fy1 + 6.7), (fx1 - 0.25, fy1 - 0.25, fx1 + 16.25, fy1 + 6.95),
                      fy1 + 6.7 + 1.6, fy1 - 1.6))
print('wrote', len(made), 'footprints to', LIB)

tbl = os.path.join(HERE, 'fp-lib-table')
with open(tbl, 'w', encoding='utf-8', newline='\n') as fh:
    fh.write('(fp_lib_table\n\t(version 7)\n\t(lib (name "ib01")(type "KiCad")(uri "${KIPRJMOD}/ib01.pretty")'
             '(options "")(descr "IB-01 parts from LCSC (generated by gen_footprints.py)"))\n)\n')
print('wrote', tbl)
