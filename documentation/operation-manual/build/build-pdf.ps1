# Build operation-manual.pdf (A4) from operation-manual-doc.md: pandoc → HTML (manual.css, manual.lua) → Edge print.
# Usage: documentation\operation-manual\build\build-pdf.ps1
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$md = Join-Path $root 'operation-manual-doc.md'
$html = Join-Path $root 'operation-manual.build.html'
$pdf = Join-Path $root 'operation-manual.pdf'
$pandoc = @((Get-Command pandoc -ErrorAction SilentlyContinue).Source, "$env:LOCALAPPDATA\Pandoc\pandoc.exe") |
  Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$browser = @(
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

# Images are linked relative to the manual folder, so the HTML is written there and deleted afterwards.
& $pandoc $md --from gfm+implicit_figures --to html5 --standalone --embed-resources `
  --metadata title='AGV I-PRIME Operation Manual' --metadata pagetitle='AGV I-PRIME Operation Manual' `
  --variable 'header-includes=<style>header#title-block-header{display:none}</style>' `
  --css (Join-Path $here 'manual.css') --lua-filter (Join-Path $here 'manual.lua') `
  --resource-path $root --output $html
if ($LASTEXITCODE) { throw 'pandoc failed' }
Remove-Item $pdf -ErrorAction SilentlyContinue
& $browser --headless=new --disable-gpu --no-pdf-header-footer --virtual-time-budget=8000 `
  --print-to-pdf="$pdf" "$(([Uri]$html).AbsoluteUri)" 2>$null
$t = 0; while (-not (Test-Path $pdf) -and $t -lt 40) { Start-Sleep -Milliseconds 500; $t++ }
Remove-Item $html
if (Test-Path $pdf) { $pdf } else { throw 'no pdf' }
