# Run the #check layout report (iec-sheet.js) of every iec-page-NN.html, or of the page numbers given.
# Usage (from 01-schematic-iec): ..\kit\check-set.ps1 -Dir . [-Only 40,41]   'OK' = nothing overlaps.
param([string]$Dir = '.', [string[]]$Only)
$browser = @(
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$pages = Get-ChildItem (Join-Path $Dir 'iec-page-*.html') | Sort-Object Name
if ($Only) { $pages = $pages | Where-Object { $Only -contains $_.BaseName.Substring(9) } }
foreach ($p in $pages) {
  $dom = & $browser --headless=new --disable-gpu --window-size=1587,1123 --virtual-time-budget=8000 `
    --dump-dom "$(([Uri]$p.FullName).AbsoluteUri)#check" 2>$null | Out-String
  $m = [regex]::Match($dom, '<pre id="check">([\s\S]*?)</pre>')
  $txt = if ($m.Success) { [Net.WebUtility]::HtmlDecode($m.Groups[1].Value) } else { 'NO REPORT' }
  "== $($p.BaseName.Substring(9))"
  $txt
}
