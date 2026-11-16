"""Autoroute IB-01 with Freerouting, keeping the copper pours.

    D:\\kicad\\bin\\python.exe route.py export     -> ib01.dsn  (for Freerouting)
    java -jar D:\\kicad\\freerouting\\freerouting-2.5.0.jar -de ib01.dsn -do ib01.ses -mp 40 --gui.enabled=false
    D:\\kicad\\bin\\python.exe route.py import     <- ib01.ses, refills the pours, saves ib01.kicad_pcb

2P48, 3P48 and 1N48 are connected by their pours (exported as planes, so the router leaves them).
1N24 and 1N12 are routed as tracks; their bottom pours are filled around the tracks afterwards. Track widths come from the net classes in ib01.kicad_pro.
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, 'ib01.kicad_pcb')
DSN = os.path.join(HERE, 'ib01.dsn')
SES = os.path.join(HERE, 'ib01.ses')

board = pcbnew.LoadBoard(PCB)
if sys.argv[1:] == ['export']:
    if not pcbnew.ExportSpecctraDSN(board, DSN):
        raise SystemExit('DSN export failed')
    # 1N24 and 1N12 are routed as tracks: drop their planes from the router's view, so a bottom
    # track can never cut a pin off the plane. Their pours are still filled on the board afterwards.
    txt = open(DSN, encoding='utf-8').read()
    for net in ('/1N24', '/1N12'):
        i = txt.find('(plane ' + net + ' ')
        if i < 0:
            raise SystemExit('plane not found: ' + net)
        depth, j = 0, i
        while True:
            depth += {'(': 1, ')': -1}.get(txt[j], 0)
            j += 1
            if depth == 0:
                break
        txt = txt[:i] + txt[j:]
    open(DSN, 'w', encoding='utf-8').write(txt)
    print('wrote', DSN)
elif sys.argv[1:] == ['import']:
    if not pcbnew.ImportSpecctraSES(board, SES):
        raise SystemExit('SES import failed')
    # Freerouting sometimes necks a track down below the board minimum at a pad; widen those stubs.
    for t in board.GetTracks():
        if t.GetClass() != 'PCB_VIA' and t.GetWidth() < pcbnew.FromMM(0.2):
            t.SetWidth(pcbnew.FromMM(0.2))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    print('routed board saved:', PCB, '-', len(board.GetTracks()), 'tracks and vias')
else:
    raise SystemExit(__doc__)
