# Print every iec-page-NN.html in a folder to A3 PDF with Edge headless, then merge them in page order.
# Usage (from 01-schematic-iec): ..\kit\print-set.ps1 -Dir . -Out circuit-diagrams.pdf   (needs python3.11 with pypdf)
param([string]$Dir = '.', [string]$Out = 'circuit-diagrams.pdf')
$Dir = (Resolve-Path $Dir).Path
if (-not [IO.Path]::IsPathRooted($Out)) { $Out = Join-Path $Dir $Out }
$tmp = Join-Path $env:TEMP 'iec-pdf'
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $tmp | Out-Null
$browser = @(
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
foreach ($p in Get-ChildItem (Join-Path $Dir 'iec-page-*.html') | Sort-Object Name) {
  $pdf = Join-Path $tmp ($p.BaseName + '.pdf')
  & $browser --headless=new --disable-gpu --no-pdf-header-footer --virtual-time-budget=8000 `
    --print-to-pdf="$pdf" "$(([Uri]$p.FullName).AbsoluteUri)" 2>$null
  $t = 0; while (-not (Test-Path $pdf) -and $t -lt 20) { Start-Sleep -Milliseconds 500; $t++ }
  if (-not (Test-Path $pdf)) { Write-Warning "no pdf: $($p.Name)" }
}
python3.11 -c @"
import sys, glob, pypdf
w = pypdf.PdfWriter()
for f in sorted(glob.glob(sys.argv[1] + '/iec-page-*.pdf')):
    r = pypdf.PdfReader(f)
    if len(r.pages) != 1: print('pages', len(r.pages), f)
    for pg in r.pages: w.add_page(pg)
w.add_metadata({'/Title': 'Circuit diagram (draft for preliminary review)'})
w.write(sys.argv[2]); print('pages total', len(w.pages))
"@ $tmp $Out
