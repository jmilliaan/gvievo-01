"""Generate the IB-01 interconnect board schematic (ib01.kicad_sch) for KiCad 10.

Source of the content: ../pcb-study-001.md (scope A + B + C + E, owner decisions P1-P7,
fuse values in section 8) and ../../01-schematic/io-mapping.md (what lands where).

Connections are made with net labels on every pin, no wires. Symbols are copied from the
stock KiCad libraries so the file opens without project libraries.

Run:  python3.11 gen_schematic.py        (or D:\\kicad\\bin\\python.exe)
This script is the master until the schematic is edited by hand in KiCad. After that,
edit the .kicad_sch and stop using the script.
"""
import os
import re
import uuid

KICAD_SYM = r'D:\kicad\share\kicad\symbols'
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = 'ib01'
OUT = os.path.join(HERE, PROJECT + '.kicad_sch')
NS = uuid.UUID('3f6d1c2e-6a51-4b7e-9a0f-1b01b01b01b0')
ROOT_UUID = str(uuid.uuid5(NS, 'root'))


def uid(key):
    return str(uuid.uuid5(NS, key))


# --------------------------------------------------------------------------- s-expressions
class Q(str):
    """A quoted string atom; holds the escaped text exactly as in the file."""


def esc(s):
    return Q(s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n'))


TOK = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def parse(text):
    stack, cur = [], []
    for m in TOK.finditer(text):
        lp, rp, qs, at = m.groups()
        if lp:
            stack.append(cur)
            cur = []
        elif rp:
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif qs is not None:
            cur.append(Q(qs))
        elif at is not None:
            cur.append(at)
    return cur[0]


def ser(x, ind=0):
    if not isinstance(x, list):
        return '"%s"' % x if isinstance(x, Q) else str(x)
    if all(not isinstance(e, list) for e in x):
        return '(' + ' '.join(ser(e) for e in x) + ')'
    pad = '\t' * (ind + 1)
    head = []
    i = 0
    while i < len(x) and not isinstance(x[i], list):
        head.append(ser(x[i]))
        i += 1
    lines = ['(' + ' '.join(head)]
    for e in x[i:]:
        lines.append(pad + ser(e, ind + 1))
    lines.append('\t' * ind + ')')
    return '\n'.join(lines)


def find(node, head):
    return [e for e in node if isinstance(e, list) and e and e[0] == head]


# --------------------------------------------------------------------------- library symbols
_libs = {}


def lib_symbol(lib_id):
    lib, name = lib_id.split(':')
    if lib not in _libs:
        with open(os.path.join(KICAD_SYM, lib + '.kicad_sym'), encoding='utf-8') as f:
            _libs[lib] = parse(f.read())
    for s in find(_libs[lib], 'symbol'):
        if s[1] == name:
            if find(s, 'extends'):
                raise SystemExit('%s is a derived symbol; flattening not implemented' % lib_id)
            return s
    raise SystemExit('symbol not found: ' + lib_id)


def pins_of(sym):
    """{number: (x, y, angle)} in library coordinates (y up)."""
    out = {}

    def walk(n):
        for e in n:
            if isinstance(e, list) and e:
                if e[0] == 'pin':
                    at = find(e, 'at')[0]
                    num = find(e, 'number')[0][1]
                    out[str(num)] = (float(at[1]), float(at[2]), int(float(at[3])))
                else:
                    walk(e)
    walk(sym)
    return out


# --------------------------------------------------------------------------- schematic items
items = []        # placed symbols, labels, texts, rectangles
used_libs = {}    # lib_id -> lib symbol tree
refs = set()


def r(v):
    return float('%.2f' % v)


def snap(v, g=1.27):
    return round(v / g) * g


def font(size=1.27, bold=False):
    f = ['font', ['size', size, size]]
    if bold:
        f.append(['bold', 'yes'])
    return f


def text(x, y, s, size=1.27, bold=False):
    items.append(['text', esc(s), ['exclude_from_sim', 'no'], ['at', r(x), r(y), 0],
                  ['effects', font(size, bold), ['justify', 'left', 'bottom']],
                  ['uuid', Q(uid('text%s%s%s' % (x, y, s)))]])


def rect(x1, y1, x2, y2, key):
    items.append(['rectangle', ['start', r(x1), r(y1)], ['end', r(x2), r(y2)],
                  ['stroke', ['width', 0.3], ['type', 'dash']], ['fill', ['type', 'none']],
                  ['uuid', Q(uid('rect' + key))]])


def label(x, y, net, out_angle):
    just = {0: ['justify', 'left', 'bottom'], 90: ['justify', 'left', 'bottom'],
            180: ['justify', 'right', 'bottom'], 270: ['justify', 'right', 'bottom']}[out_angle]
    items.append(['label', esc(net), ['at', r(x), r(y), out_angle],
                  ['effects', font(), just], ['uuid', Q(uid('lbl%s%s%s' % (x, y, net)))]])


def place(lib_id, ref, value, x, y, nets, footprint='', mpn='', descr='', ref_at=None,
          val_at=None, pin_notes=None, lcsc='', loose=''):
    """Place a symbol at (x, y), unrotated, and put a net label on each pin."""
    if ref in refs:
        raise SystemExit('duplicate reference ' + ref)
    x, y = snap(x), snap(y)   # symbol origin on the 1.27 mm grid, so every pin is too
    refs.add(ref)
    sym = lib_symbol(lib_id)
    used_libs[lib_id] = sym
    pins = pins_of(sym)
    if set(nets) != set(pins):
        raise SystemExit('%s: pins %s, nets given for %s' % (ref, sorted(pins), sorted(nets)))
    ra = ref_at or (x, y - 2.54)
    va = val_at or (x, y + 2.54)

    def prop(name, val, at, hide=False, just=None):
        p = ['property', Q(name), esc(val), ['at', r(at[0]), r(at[1]), 0]]
        if hide:
            p.append(['hide', 'yes'])
        eff = ['effects', font()]
        if just:
            eff.append(['justify', just])
        p.append(eff)
        return p

    props = [prop('Reference', ref, ra, just='left'), prop('Value', value, va, just='left'),
             prop('Footprint', footprint, (x, y), hide=True),
             prop('Datasheet', '', (x, y), hide=True),
             prop('Description', descr, (x, y), hide=True)]
    if mpn:
        props.append(prop('MPN', mpn, (x, y), hide=True))
    if lcsc:
        props.append(prop('LCSC', lcsc, (x, y), hide=True))          # part fitted on the board
    if loose:
        props.append(prop('Loose part', loose, (x, y), hide=True))   # mating plug or fuse, ordered separately
    node = ['symbol', ['lib_id', Q(lib_id)], ['at', r(x), r(y), 0], ['unit', 1],
            ['exclude_from_sim', 'no'], ['in_bom', 'yes'], ['on_board', 'yes'], ['dnp', 'no'],
            ['uuid', Q(uid('sym' + ref))]] + props
    for num in sorted(pins, key=lambda n: int(n) if n.isdigit() else 0):
        node.append(['pin', Q(num), ['uuid', Q(uid('pin%s.%s' % (ref, num)))]])
    node.append(['instances', ['project', Q(PROJECT), ['path', Q('/' + ROOT_UUID),
                                                       ['reference', Q(ref)], ['unit', 1]]]])
    items.append(node)
    for num, (px, py, pa) in pins.items():
        if nets[num]:
            label(x + px, y - py, nets[num], (pa + 180) % 360)
        else:   # unused pin of a larger part: no-connect flag
            items.append(['no_connect', ['at', r(x + px), r(y - py)], ['uuid', Q(uid('nc%s.%s' % (ref, num)))]])
        if pin_notes and num in pin_notes:
            text(x + 3.0, y - py + 0.6, pin_notes[num])
    return pins


# --------------------------------------------------------------------------- footprints / parts
# Parts from LCSC (2026-11-16) so JLCPCB can assemble the whole board. Project footprints: gen_footprints.py.
FP_P762 = 'ib01:KF2EDGVM-7.62-{n}P'
FP_P508 = 'ib01:2EDGVM-5.08-{nn}P'
FP_P350 = 'ib01:KF2EDGVM-3.5-{n}P'
FP_FUSE = 'ib01:XF-508P-B-B'
FP_LED = 'LED_SMD:LED_0805_2012Metric'
FP_R0805 = 'Resistor_SMD:R_0805_2012Metric'
FP_R1206 = 'Resistor_SMD:R_1206_3216Metric'
FP_HOLE = 'MountingHole:MountingHole_4.3mm_M4_Pad_Via'
FP_HOLE_NPTH = 'MountingHole:MountingHole_4.3mm_M4'
FP_JP = 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical'

# family (by pitch: 7.62 / 5.08 / 3.5 mm): footprint, value, header MPN, plug MPN, {poles: header LCSC}, {poles: plug LCSC}
FAMILY = {
    'P762': (FP_P762, 'KF2EDGVM-7.62-{n}P', 'Kefa KF2EDGVM-7.62-{n}P (15 A / 630 V IEC)', 'Kefa KF2EDGKM-7.62-{n}P',
              {2: 'C441450'}, {2: 'C441150'}),
    'P508': (FP_P508, '2EDGVM-5.08-{nn}P', 'Degson 2EDGVM-5.08-{nn}P-14-100A(H) (20 A / 320 V IEC)', 'Degson 2EDGKM-5.08-{nn}P-14-00A(H)',
             {2: 'C699489'}, {2: 'C699500'}),
    'P350': (FP_P350, 'KF2EDGVM-3.5-{n}P', 'Kefa KF2EDGVM-3.5-{n}P (8 A UL / 7 A IEC)', 'Kefa KF2EDGKM-3.5-{n}P',
           {2: 'C441407', 4: 'C441409', 5: 'C441410', 6: 'C441411', 7: 'C441412', 9: 'C441414', 12: 'C441405'},
           {2: 'C441107', 4: 'C441109', 5: 'C441110', 6: 'C441111', 7: 'C441112', 9: 'C441114', 12: 'C441105'}),
}
FUSE_LCSC = {'0997002.WXN': 'C3661386', '0997003.WXN': 'C3661685', '0997005.WXN': 'C2680609', '099707.5WXN': 'C2680610'}
R_LCSC = {'10k': 'C17414', '4k7': 'C17673', '22k': 'C25830', '120': 'C17909'}
LED_LCSC = 'C2297'


def connector(ref, fam, x, y, title, pins):
    """pins: list of (net, note). Draws the heading, the symbol, labels and pin notes."""
    n = len(pins)
    fp, val, mpn, plug, hl, pl = FAMILY[fam]
    lib_id = 'Connector_Generic:Conn_01x%02d' % n
    nets = {str(i + 1): p[0] for i, p in enumerate(pins)}
    notes = {str(i + 1): p[1] for i, p in enumerate(pins) if p[1]}
    # y is where pin 1 sits; the symbol origin moves down by the height above pin 1
    ys = y + max(p[1] for p in pins_of(lib_symbol(lib_id)).values())
    top = y - 5.08
    text(x - 22.86, top - 6.0, title, size=1.6, bold=True)
    place(lib_id, ref, val.format(n=n, nn='%02d' % n), x, ys, nets,
          footprint=fp.format(n=n, nn='%02d' % n), mpn=mpn.format(n=n, nn='%02d' % n), descr=title,
          lcsc=hl[n], loose='%s (LCSC %s), cable side' % (plug.format(n=n, nn='%02d' % n), pl[n]),
          ref_at=(x - 22.86, top - 3.2), val_at=(x - 10.0, top - 3.2), pin_notes=notes)


FUSES = []


def fuse_cell(n, x, y, amps, net_in, ret, load, rled, mpn_code):
    """Fuse Fn, then indicator Rn + Dn from the fused net to the return.

    LED lit = the branch has power behind its fuse. Dark = fuse blown or no supply."""
    out = '%s-F%d' % (net_in, n)
    led = 'LED-F%d' % n
    place('Device:Fuse', 'F%d' % n, '%s A' % amps, x, y, {'1': net_in, '2': out},
          footprint=FP_FUSE, mpn='XFCN XF-508P-B-B MINI fuse holder, 500 V', lcsc='C19727305',
          loose='Littelfuse %s MINI 58 V (LCSC %s), fit by hand' % (mpn_code, FUSE_LCSC[mpn_code]),
          descr='Branch fuse: ' + load.replace('\n', ' '), ref_at=(x + 2.0, y - 1.0), val_at=(x + 2.0, y + 1.6))
    rfp = FP_R1206 if rled.startswith('22') else FP_R0805
    place('Device:R', 'R%d' % n, rled, x + 11.43, y, {'1': out, '2': led},
          footprint=rfp, lcsc=R_LCSC[rled], descr='LED resistor F%d' % n, ref_at=(x + 13.4, y - 1.0), val_at=(x + 13.4, y + 1.6))
    place('Device:LED', 'D%d' % n, 'green', x + 11.43, y + 15.24, {'1': ret, '2': led},
          footprint=FP_LED, lcsc=LED_LCSC, descr='Indicator F%d: on = branch powered' % n,
          ref_at=(x + 4.0, y + 19.6), val_at=(x + 10.0, y + 19.6))
    text(x - 5.0, y + 25.0, 'F%d  %s A\n%s' % (n, amps, load), size=1.27)
    FUSES.append((n, amps, net_in, out, load))


# =========================================================================== content
text(15, 18, 'IB-01 INTERCONNECT BOARD  -  AGV I-PRIME  -  replaces the terminal blocks (functions A, B, C, E)', 3.0, True)
text(15, 24, 'Generated from documentation/electrical/02-pcb/pcb-study-001.md and 01-schematic/io-mapping.md, 2026-11-16. '
     'Fuse values are estimates (study section 8). Draft 2: circuit unchanged from draft 1; board layout corrected (study section 7).', 1.5)

# ---------------------------------------------------------------- zone E: 48 V (top left)
rect(10, 30, 290, 150, 'zoneE')
text(13, 35, 'ZONE E  -  48 V (floating, 1N48 isolated from 1N24 / 1N12). Keep clear of the 24 V / 12 V zone.', 2.0, True)
text(13, 39.5, 'Motor feeders pass through unfused (13 A breakers -FC1 / -FC2 in front). Converter inputs and the 48 V spare (J8) fused here (gap R6). '
     'PE goes to the chassis bar, not through this board.', 1.4)
y0 = 55
connector('J1', 'P762', 40, y0, 'J1  48 V IN, LEFT FEEDER (from -FC1)', [('2P48', '2P48 from -FC1 (2.5 mm2)'), ('1N48', '1N48')])
connector('J2', 'P762', 40, y0 + 25, 'J2  48 V IN, RIGHT FEEDER (from -FC2)', [('3P48', '3P48 from -FC2 (2.5 mm2)'), ('1N48', '1N48')])
connector('J3', 'P762', 40, y0 + 50, 'J3  48 V IN, CONVERTERS (from -QA1)', [('1P48', '1P48 after -QA1 (1.5 mm2)'), ('1N48', '1N48')])
connector('J4', 'P762', 120, y0, 'J4  DRIVER L POWER (-TA1, LC03D06A)', [('2P48', '+48 V to -TA1'), ('1N48', '0 V to -TA1')])
connector('J5', 'P762', 120, y0 + 25, 'J5  DRIVER R POWER (-TA2, LC03D06A)', [('3P48', '+48 V to -TA2'), ('1N48', '0 V to -TA2')])
connector('J6', 'P762', 120, y0 + 50, 'J6  -TA3 INPUT (24 V converter)', [('1P48-F12', '+Vin -TA3 SD-100C-24'), ('1N48', '-Vin -TA3')])
connector('J7', 'P762', 120, y0 + 75, 'J7  -TA4 INPUT (12 V converter)', [('1P48-F13', '+Vin -TA4 SD-100C-12'), ('1N48', '-Vin -TA4')])
fuse_cell(12, 200, 60, '5', '1P48', '1N48', '-TA3 input', '22k', '0997005.WXN')
fuse_cell(13, 245, 60, '5', '1P48', '1N48', '-TA4 input', '22k', '0997005.WXN')
connector('J8', 'P762', 40, y0 + 75, 'J8  48 V SPARE OUTPUT', [('1P48-F19', '+48 V spare (F19)'), ('1N48', '0 V')])
fuse_cell(19, 222, 100, '5', '1P48', '1N48', '48 V spare', '22k', '0997005.WXN')

# ---------------------------------------------------------------- zone A: 24 V / 12 V distribution (top right)
rect(300, 30, 584, 150, 'zoneA')
text(303, 35, 'ZONE A  -  24 V AND 12 V DISTRIBUTION. One fuse + LED per load (P1, P3); fans share F7 (P6); spares F14-F18.', 2.0, True)
text(303, 39.5, '1N24 and 1N12 are joined at the converters, not on this board. -FC3 / -FC4 stay in front of the inputs.', 1.4)
connector('J10', 'P508', 325, 55, 'J10  24 V IN (-FC3, -TA3)', [('1P24', '1P24 from -FC3'), ('1N24', '1N24 from -TA3 V-')])
connector('J11', 'P508', 325, 80, 'J11  12 V IN (-FC4, -TA4)', [('1P12', '1P12 from -FC4'), ('1N12', '1N12 from -TA4 V-')])
f24 = [(1, '2', '-BG1 scanner', '0997002.WXN'), (2, '3', '-KE1/-KE2 safety ctrl\n+ safety feeds', '0997003.WXN'),
       (3, '2', '-KE4 I/O module\n+ pendant, commons', '0997002.WXN'), (4, '2', '-PJ1 horn', '0997002.WXN'),
       (5, '2', '-PH1 display', '0997002.WXN'), (6, '2', '-BG3 line sensor', '0997002.WXN'),
       (7, '2', '-GQ1..3 fans', '0997002.WXN'), (8, '2', '-TA1 network supply', '0997002.WXN'),
       (9, '2', '-TA2 network supply', '0997002.WXN')]
for i, (n, a, load, code) in enumerate(f24):
    fuse_cell(n, 360 + 25.4 * (i % 5), 55 + 45 * (i // 5), a, '1P24', '1N24', load, '10k', code)
fuse_cell(10, 360 + 25.4 * 4, 100, '7.5', '1P12', '1N12', '-KE3 IPC', '4k7', '099707.5WXN')
fuse_cell(11, 360 + 25.4 * 5, 100, '3', '1P12', '1N12', '-BG4 RFID', '4k7', '0997003.WXN')
for i, n in enumerate((14, 15, 16)):
    fuse_cell(n, 360 + 25.4 * (5 + i), 55, '2', '1P24', '1N24', '24 V spare %d' % (i + 1), '10k', '0997002.WXN')
for i, n in enumerate((17, 18)):
    fuse_cell(n, 360 + 25.4 * (6 + i), 100, '3', '1P12', '1N12', '12 V spare %d' % (i + 1), '4k7', '0997003.WXN')

# ---------------------------------------------------------------- load connectors (middle band)
rect(10, 160, 584, 262, 'loads')
text(13, 165, 'LOAD CONNECTORS  -  24 V AND 12 V (zone A). Pin notes give the far end.', 2.0, True)
xs = [35, 105, 175, 245, 315, 385, 455, 525]
yl = 182
connector('J12', 'P350', xs[0], yl, 'J12  -BG1 SCANNER SUPPLY', [('1P24-F1', 'M12 pin 1 +24 V (brown)'), ('1N24', 'M12 pin 3 0 V (blue)')])
connector('J13', 'P350', xs[1], yl, 'J13  SAFETY CONTROLLER (box)', [('1P24-F2', '-KE1 A1'), ('1N24', '-KE1 A2'), ('1P24-F2', '-KE2 A1'),
                                                                ('1N24', '-KE2 A2'), ('DI09', '-KE2 Q3 ESTOP OK (not safety)')])
connector('J14', 'P350', xs[2], yl, 'J14  PANEL SAFETY FEEDS', [('1P24-F2', '-SJ4 pole 1 feed (to I7)'), ('1P24-F2', '-SJ3 pole 1 feed (to I8)')])
connector('J17', 'P350', xs[3], yl, 'J17  -PJ1 HORN', [('1P24-F4', '+24 V'), ('1N24', '0 V'), ('1N24', 'COM'), ('DO0', 'sound 1 (movement)'),
                                                   ('DO1', 'sound 2 (alarm)')])
connector('J18', 'P350', xs[4], yl, 'J18  -PH1 DISPLAY', [('1P24-F5', '+24 V'), ('1N24', '0 V')])
connector('J19', 'P350', xs[5], yl, 'J19  -BG3 LINE SENSOR', [('1P24-F6', 'M12 1 L+ (brown)'), ('CAN_H', 'M12 2 CAN-H (white)'),
                                                         ('1N24', 'M12 3 GND (blue)'), ('CAN_L', 'M12 4 CAN-L (black)')])
connector('J20', 'P350', xs[6], yl, 'J20  -GQ1..3 FANS', [('1P24-F7', '-GQ1 +'), ('1N24', '-GQ1 -'), ('1P24-F7', '-GQ2 +'),
                                                      ('1N24', '-GQ2 -'), ('1P24-F7', '-GQ3 +'), ('1N24', '-GQ3 -')])
connector('J27', 'P508', xs[7], yl, 'J27  -KE3 IPC (12 V)', [('1P12-F10', '+12 V (1.0 mm2 min)'), ('1N12', '0 V')])
connector('J28', 'P350', xs[7], yl + 22, 'J28  -BG4 RFID (12 V)', [('1P12-F11', '+12 V'), ('1N12', '0 V')])
y2 = 222
for i, (ref, n) in enumerate((('J31', 14), ('J32', 15), ('J33', 16))):
    connector(ref, 'P350', xs[3 + i], y2, '%s  24 V SPARE %d' % (ref, i + 1), [('1P24-F%d' % n, '+24 V (F%d)' % n), ('1N24', '0 V')])
connector('J34', 'P350', xs[6], y2, 'J34  12 V SPARE 1', [('1P12-F17', '+12 V (F17)'), ('1N12', '0 V')])
connector('J35', 'P350', xs[7], y2 + 8, 'J35  12 V SPARE 2', [('1P12-F18', '+12 V (F18)'), ('1N12', '0 V')])
for ref, x, side, tag, fz in (('J15', xs[0], 'L', '-TA1', 'F8'), ('J16', xs[1], 'R', '-TA2', 'F9')):
    connector(ref, 'P350', x, y2, '%s  DRIVER %s CONTROL (%s 28-pin)' % (ref, side, tag), [
        ('CAN_H', 'pin 6 CAN_H'), ('CAN_L', 'pin 5 CAN_L'), ('CAN_GND', 'pin 7 CAN_GND'), ('CHASSIS', 'CAN cable screen'),
        ('1P24-%s' % fz, 'pin 20 NET-VIN'), ('1N24', 'pin 21 NET-GND'), ('1P24-F2', 'pin 28 EDM+ supply'),
        ('1N24', 'pin 12 HWTO1- return'), ('1N24', 'pin 27 HWTO2- return')])
text(xs[2] - 22.86, y2 - 4, 'Safety signals stay OFF this board (P1):\nHWTO1+ / HWTO2+ (-KE2 Q1 / Q2), EDM- (I3 / I4),\n'
     'E-stop X1/X2/I1/I2, OSSD I5/I6, I7, I8.\nThey keep their terminals until function D.\n'
     'EDM+ and HWTO- here are supplies, not signals.', 1.27)

# ---------------------------------------------------------------- zone C: control I/O, zone B: CAN (bottom)
rect(10, 270, 400, 395, 'zoneC')
text(13, 275, 'ZONE C  -  CONTROL I/O  (-KE4 CK-TP5162, NPN outputs; DI COM0 = 1P24, COM1 = 1N24)', 2.0, True)
yc = 292
connector('J21', 'P350', 35, yc, 'J21  -KE4 SUPPLY', [('1P24-F3', '24V'), ('1N24', '0V')])
connector('J22', 'P350', 105, yc, 'J22  -KE4 DI ROW (module pin)', [
    ('DI00', '1 DI0'), ('DI01', '2 DI1'), ('DI02', '3 DI2'), ('DI03', '4 DI3'), ('DI04', '5 DI4'), ('DI05', '6 DI5'),
    ('DI06', '7 DI6'), ('1P24-F3', '9 DI_COM0'), ('DI08', '11 DI8'), ('DI09', '12 DI9'), ('1N24', '19 DI_COM1'),
    ('', 'spare (12-pole part: the 11-pole plug is not stocked)')])
connector('J23', 'P350', 175, yc, 'J23  -KE4 DO ROW (module pin)', [('DO0', '1 DO0'), ('DO1', '2 DO1'), ('1P24-F3', '9 +'), ('1N24', '10 -')])
connector('J24', 'P350', 245, yc, 'J24  PANEL BUTTONS (non-safety)', [
    ('DI00', '-SJ2 START'), ('1N24', '-SJ2 return'), ('DI01', '-SJ3 RESET pole 2'), ('1N24', '-SJ3 return'),
    ('DI02', '-SJ4 MANUAL pole 2'), ('1N24', '-SJ4 return')])
connector('J25', 'P350', 315, yc, 'J25  PENDANT (Delta 8 x 0.5)', [
    ('1N24', 'common'), ('DI03', '-SJ6 FORWARD'), ('DI04', '-SJ7 REVERSE'), ('DI05', '-SJ8 LEFT'), ('DI06', '-SJ9 RIGHT'),
    ('1P24-F3', '-SJ5 MANUAL ARM feed'), ('DI08', '-SJ5 MANUAL ARM')])

rect(410, 270, 584, 395, 'zoneB')
text(413, 275, 'ZONE B  -  CAN BACKBONE (125 kbit/s)', 2.0, True)
text(413, 279.5, 'Order on the board: J29 USB-CAN (120 R inside) ... J15, J16, J19, J30 ... JP1 + R30 at the far end.\n'
     'Screens to CHASSIS at the board (mounting holes to the back plate).', 1.27)
connector('J29', 'P350', 440, 298, 'J29  -TF1 USB-CAN (CANable)', [('CAN_H', 'CANH'), ('CAN_L', 'CANL'), ('CAN_GND', 'GND'), ('CHASSIS', 'screen')])
connector('J30', 'P350', 515, 298, 'J30  -GB1 BATTERY BMS CAN', [('CAN_H', 'CAN H'), ('CAN_L', 'CAN L'), ('CAN_GND', 'CAN GND'), ('CHASSIS', 'screen')])
place('Connector_Generic:Conn_01x02', 'JP1', 'TERM', 440, 325, {'1': 'CAN_H', '2': 'CAN_TERM'}, footprint=FP_JP,
      mpn='2.54 mm 1x2 header', lcsc='C32713268', loose='jumper shunt closed top (LCSC C100114), fit by hand', descr='CAN far-end terminator on/off (fitted = on)', ref_at=(445, 322), val_at=(445, 330))
place('Device:R', 'R30', '120', 470, 330, {'1': 'CAN_TERM', '2': 'CAN_L'}, footprint=FP_R1206, lcsc=R_LCSC['120'],
      descr='CAN far-end terminator', ref_at=(472, 329), val_at=(472, 332))
text(413, 340, 'JP1 fitted = far end terminated (default).', 1.27)
for i in range(6):
    if i in (0, 3):   # H1, H4 sit in the 48 V zone: plain hole, no copper (no track may cross the 48 V keep-out)
        place('Mechanical:MountingHole', 'H%d' % (i + 1), 'M4', 425 + i * 22, 352, {}, footprint=FP_HOLE_NPTH,
              descr='Standoff to the back plate, unplated (48 V zone)', ref_at=(428 + i * 22, 348), val_at=(428 + i * 22, 351))
    else:
        place('Mechanical:MountingHole_Pad', 'H%d' % (i + 1), 'M4', 425 + i * 22, 352, {'1': 'CHASSIS'}, footprint=FP_HOLE,
              descr='Standoff to the back plate (chassis)', ref_at=(428 + i * 22, 348), val_at=(428 + i * 22, 351))
text(413, 364, 'H2, H3, H5, H6: M4 standoffs = CHASSIS. H1, H4 (48 V zone): unplated. Board max 150 x 250 mm (owner).', 1.27)

# ---------------------------------------------------------------- notes
text(15, 402, 'NOTES  1) Fuses: Littelfuse MINI 58 V (0997xxx.WXN), 1000 A @ 58 V DC; -QA1 is the backup above that (P7). '
     'One fuse type on the whole board.  2) LED on = branch powered; dark = fuse blown or no supply.  '
     '3) Currents and fuse values are estimates: confirm by clamp-meter round (study section 8).', 1.27)
text(15, 406, '4) The 24 V converter is SD-100C-24 (owner 2026-11-16); documents still say SD-150C-24.  '
     '5) Parts from LCSC for full JLCPCB assembly: Kefa KF2EDGVM 7.62 (48 V), Degson 2EDGVM 5.08 (inputs, IPC), Kefa KF2EDGVM 3.5 (signals, small loads), flanged; fuse holder XFCN XF-508P-B-B. Plugs and fuses are loose parts (field Loose part).', 1.27)


# =========================================================================== write
def write():
    lib_symbols = ['lib_symbols']
    for lib_id, sym in used_libs.items():
        s = list(sym)
        s[1] = Q(lib_id)
        lib_symbols.append(s)
    doc = ['kicad_sch', ['version', 20250610], ['generator', Q('eeschema')], ['generator_version', Q('10.0')],
           ['uuid', Q(ROOT_UUID)], ['paper', Q('A2')],
           ['title_block', ['title', Q('IB-01 interconnect board')], ['date', Q('2026-11-16')], ['rev', Q('draft 2')],
            ['company', Q('PT INTI GANDA PERDANA')], ['comment', 1, Q('AGV I-PRIME, replaces the terminal blocks (A, B, C, E)')],
            ['comment', 2, Q('Source: 02-pcb/pcb-study-001.md; generated by gen_schematic.py')]],
           lib_symbols] + items + [['sheet_instances', ['path', Q('/'), ['page', Q('1')]]], ['embedded_fonts', 'no']]
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(ser(doc) + '\n')
    print('wrote', OUT, '-', len(refs), 'symbols')


write()
