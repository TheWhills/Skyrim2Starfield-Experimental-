# Move the player to a converted cell with `coc` and VERIFY the arrival before anything else runs.
# usage: coc.ps1 -Cell Vault111Cryo -CellJson <staging>\Vault111Cryo.json [-Wait 30000]
# Exit 0: the player stands within 5 m of the cell's COC marker. Exit 1: not there (load failed or the jump didn't
# happen): route tests must not run, they would teleport to this cell's coordinates inside another cell and fall.
# Exit 2/3/4: the console could not be opened safely (console_open.ps1 codes); nothing was typed.
param([Parameter(Mandatory)][string]$Cell, [Parameter(Mandatory)][string]$CellJson, [int]$Wait = 30000)
$env:LEGACY = '1'
$i = Join-Path $PSScriptRoot 'input.ps1'
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'console_open.ps1') | Out-Null
if ($LASTEXITCODE -ne 0) { "console not opened safely (code $LASTEXITCODE)"; exit $LASTEXITCODE }
powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq "type:coc FO4Port_$Cell|key:enter|wait:400|key:grave|wait:$Wait" | Out-Null
$marker = (Get-Content $CellJson -Raw | ConvertFrom-Json).refs | Where-Object { $_.base_editor_id -eq 'COCMarkerHeading' } | Select-Object -First 1
if (-not $marker) { "no COC marker in ${CellJson}: arrival not verifiable"; exit 1 }
$mx = $marker.pos[0] / 70; $my = $marker.pos[1] / 70
# up to 3 reads: OCR sometimes shifts a column ("0.00 29.26 60.11" for "29.26 60.11 ...") and a single read then
# looked like a failed jump (Vault 81 and the library were skipped although the player had arrived)
$d = 1e9
for ($n = 0; $n -lt 3 -and $d -gt 5; $n++) {
  $p = powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'readpos.ps1')
  if ("$p" -like 'fail console*') { "console not opened safely: $p"; exit 2 }
  $v = "$p".Trim().Split(' ', [StringSplitOptions]::RemoveEmptyEntries)
  try { $d = [Math]::Sqrt([Math]::Pow([double]$v[0] - $mx, 2) + [Math]::Pow([double]$v[1] - $my, 2)) } catch { $d = 1e9 }
}
if ($d -gt 5) { "not at FO4Port_$Cell (last read $p, marker {0:N2} {1:N2})" -f $mx, $my; exit 1 }
"at FO4Port_$Cell (read $p, {0:N1} m from the COC marker)" -f $d
exit 0
