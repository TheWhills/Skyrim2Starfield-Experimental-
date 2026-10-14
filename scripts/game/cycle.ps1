# Full test cycle: close Starfield, redeploy staging, launch, load the last save, clear dialogs, coc into a cell, screenshot.
# usage: cycle.ps1 -Staging <staging dir> -Starfield <game dir> -Cell FO4Port_Vault111Cryo -Shot <out.png>
param([Parameter(Mandatory)][string]$Staging, [Parameter(Mandatory)][string]$Starfield, [string]$Cell = 'FO4Port_Vault111Cryo', [string]$Shot = (Join-Path $env:TEMP 'fo4sf_cycle.png'))
$repo = Split-Path (Split-Path $PSScriptRoot); $sf = $Starfield
$i = (Join-Path $PSScriptRoot 'input.ps1'); $env:LEGACY = '1'
$p = Get-Process Starfield -ErrorAction SilentlyContinue
$pidFile = Join-Path $PSScriptRoot 'cycle_pid.txt'           # local only: the PID of the game this script launched
$own = if (Test-Path $pidFile) { [int](Get-Content $pidFile) } else { 0 }
if ($p -and $p.Id -ne $own) { "Starfield is running but was not started by cycle.ps1 (the user's own session): not closing it"; exit 3 }
if ($p) { $p.CloseMainWindow() | Out-Null; Start-Sleep 8; $p.Refresh(); if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -Confirm:$false }; Start-Sleep 4 }
python -I "$repo\scripts\deploy_starfield.py" uninstall --starfield $sf | Out-Null
python -I "$repo\scripts\deploy_starfield.py" install --staging $Staging --starfield $sf | Select-Object -Last 1
Start-Process 'steam://rungameid/1716740'
$deadline = (Get-Date).AddSeconds(150); while ((Get-Date) -lt $deadline) { $q = Get-Process Starfield -ErrorAction SilentlyContinue; if ($q) { $q.Id | Set-Content $pidFile; break }; Start-Sleep 3 }
Start-Sleep 30
$seq = 'click:768,432|wait:6000|key:up|wait:700|key:enter|wait:2500|hold:e,300|wait:2500|hold:e,300|wait:45000|' +
       'key:grave|wait:1500|type:fov 90|wait:300|key:enter|wait:2500|key:grave|wait:1200|hold:e,300|wait:1500|' +
       "key:grave|wait:1500|key:back|key:back|key:back|type:coc $Cell|wait:400|key:enter|wait:40000"
powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq $seq | Out-Null
if ($LASTEXITCODE -ne 0) { "input guard stopped the sequence (someone else has focus)"; exit 2 }
powershell -NoProfile -ExecutionPolicy Bypass -File $PSScriptRoot\shot.ps1 -Out $Shot | Out-Null
"cycle done -> $Shot"
