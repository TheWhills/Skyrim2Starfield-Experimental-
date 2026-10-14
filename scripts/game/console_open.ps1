# Open the Starfield console only from plain gameplay, and confirm it opened, before anything gets typed.
# Exit 0: console open. Exit 3: a menu or the console was already up (nothing pressed). Exit 4: the key was pressed but the
# console did not appear (nothing typed). Exit 2: input guard (something else has focus).
# Why: a blind toggle that the game dropped left the console closed, and "player.getpos" went to the game ("p" = Skills).
param([string]$Work = (Join-Path $env:TEMP 'fo4sf_ocr'))
New-Item -ItemType Directory -Force $Work | Out-Null
$env:LEGACY = '1'
$i = Join-Path $PSScriptRoot 'input.ps1'; $shot = Join-Path $PSScriptRoot 'shot.ps1'
$py = $(if ($env:FO4SF_PYTHON) { $env:FO4SF_PYTHON } else { 'python' })
$img = Join-Path $Work 'hud_check.png'
function Hud { powershell -NoProfile -ExecutionPolicy Bypass -File $shot -Out $img | Out-Null; (& $py (Join-Path $PSScriptRoot 'hud_visible.py') $img) -eq 'yes' }
$ok = $false
for ($t = 0; $t -lt 4; $t++) {
  if (Hud) { $ok = $true; break }
  # Starfield's idle camera (third person, HUD hidden) starts after a while without input: a 1-pixel mouse nudge
  # ends it. Harmless in menus too (no key is sent).
  if ($t -eq 1) { powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq 'move:1,0|wait:300|move:-1,0|wait:1500' | Out-Null }
  Start-Sleep -Milliseconds 700
}
if (-not $ok) { "hud not visible: menu or console already open"; exit 3 }
powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq 'key:grave|wait:900' | Out-Null
if ($LASTEXITCODE -ne 0) { "input guard"; exit 2 }
if (Hud) { "console did not open"; exit 4 }
exit 0
