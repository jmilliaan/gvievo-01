"""Make the JLCPCB order files for IB-01 (full assembly, parts from LCSC).

    D:\\kicad\\bin\\python.exe make_fab.py

Inputs: ib01.kicad_pcb (routed), ib01.net (kicad-cli sch export netlist), for the LCSC fields.
Writes fab/:
  ib01-gerber.zip          Gerbers + drill files (PCB order)
  ib01-bom-jlc.csv         every part JLCPCB fits: Comment, Designator, Footprint, LCSC Part #
  ib01-cpl-jlc.csv         placement of those parts: Designator, Mid X, Mid Y, Layer, Rotation
  ib01-loose-parts.csv     what is NOT soldered on the board (cable plugs, fuses, jumper shunt): order from LCSC
Through-hole parts are placed at the centre of their pins. JLCPCB's "Confirm Parts Placement" step
is where rotation and LED polarity are checked.
"""
import csv
import os
import re
import subprocess
import zipfile
from collections import OrderedDict, defaultdict

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
FAB = os.path.join(HERE, 'fab')
GER = os.path.join(FAB, 'gerber')
PCB = os.path.join(HERE, 'ib01.kicad_pcb')
NET = os.path.join(HERE, 'ib01.net')
CLI = r'D:\kicad\bin\kicad-cli.exe'
os.makedirs(GER, exist_ok=True)


def run(*args):
    r = subprocess.run([CLI, *args], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit('kicad-cli failed: %s\n%s' % (' '.join(args), r.stdout + r.stderr))


# ---------------------------------------------------------------- Gerbers + drill
run('pcb', 'export', 'gerbers', '--layers', 'F.Cu,B.Cu,F.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts',
    '-o', GER + os.sep, PCB)
run('pcb', 'export', 'drill', '--format', 'excellon', '--excellon-separate-th', '--excellon-units', 'mm',
    '-o', GER + os.sep, PCB)
zpath = os.path.join(FAB, 'ib01-gerber.zip')
with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(os.listdir(GER)):
        z.write(os.path.join(GER, f), f)
print('wrote', zpath, '-', len(os.listdir(GER)), 'files')

# ---------------------------------------------------------------- fields from the netlist
net = open(NET, encoding='utf-8').read()
fields = {}
for blk in re.split(r'\(comp\s', net[net.index('(components'):net.index('(libparts')])[1:]:
    ref = re.search(r'\(ref "([^"]+)"', blk).group(1)
    fields[ref] = dict(re.findall(r'\(name "([^"]+)"\) "([^"]*)"', blk))

# ---------------------------------------------------------------- BOM + CPL (all fitted parts)
board = pcbnew.LoadBoard(PCB)
bom = OrderedDict()
cpl = []
missing = []
for fp in sorted(board.GetFootprints(), key=lambda f: (re.sub(r'\d', '', f.GetReference()),
                                                       int(re.sub(r'\D', '', f.GetReference()) or 0))):
    ref = fp.GetReference()
    if ref.startswith('H'):
        continue                                    # mounting holes: no part
    lcsc = fields.get(ref, {}).get('LCSC', '')
    if not lcsc:
        missing.append(ref)
    fpname = str(fp.GetFPID().GetLibItemName())
    comment = 'MINI fuse holder' if ref.startswith('F') else fp.GetValue()   # fuse value is on the loose fuse
    bom.setdefault((comment, fpname, lcsc), []).append(ref)
    if fp.GetAttributes() & pcbnew.FP_THROUGH_HOLE:
        xs = [p.GetPosition().x for p in fp.Pads()]
        ys = [p.GetPosition().y for p in fp.Pads()]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    else:
        cx, cy = fp.GetPosition().x, fp.GetPosition().y
    cpl.append([ref, '%.3fmm' % pcbnew.ToMM(cx), '%.3fmm' % -pcbnew.ToMM(cy), 'Top',
                '%g' % (fp.GetOrientationDegrees() % 360)])
if missing:
    raise SystemExit('no LCSC number for: ' + ', '.join(missing))

with open(os.path.join(FAB, 'ib01-bom-jlc.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['Comment', 'Designator', 'Footprint', 'LCSC Part #'])
    for (val, fpname, lcsc), refs in bom.items():
        w.writerow([val, ','.join(refs), fpname, lcsc])
with open(os.path.join(FAB, 'ib01-cpl-jlc.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation'])
    w.writerows(cpl)
print('wrote JLC BOM (%d lines) and CPL (%d parts)' % (len(bom), len(cpl)))

# ---------------------------------------------------------------- loose parts (per board)
loose = defaultdict(list)
for ref, fl in fields.items():
    if fl.get('Loose part'):
        loose[fl['Loose part']].append(ref)
with open(os.path.join(FAB, 'ib01-loose-parts.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['Part (LCSC)', 'Qty per board', 'For'])
    for part, refs in sorted(loose.items()):
        refs.sort(key=lambda s: (re.sub(r'\d', '', s), int(re.sub(r'\D', '', s) or 0)))
        w.writerow([part, len(refs), ','.join(refs)])
    w.writerow(['M4 standoff + screw (local hardware)', 6, 'H1-H6'])
print('wrote loose-parts list (%d lines)' % (len(loose) + 1))
