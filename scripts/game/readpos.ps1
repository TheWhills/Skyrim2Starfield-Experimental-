# Ask the game for the player's position and read it back via OCR.
# Prints "x y z" in game metres, or "fail" if any value could not be read.
# Requires Starfield focused with the console CLOSED; leaves it closed.
param([string]$Work = (Join-Path $env:TEMP 'fo4sf_ocr'))
New-Item -ItemType Directory -Force $Work | Out-Null
$env:LEGACY = '1'
$i = (Join-Path $PSScriptRoot 'input.ps1')
$py = $(if ($env:FO4SF_PYTHON) { $env:FO4SF_PYTHON } else { 'python' })
powershell -NoProfile -ExecutionPolicy Bypass -File $PSScriptRoot\console_open.ps1 -Work $Work | Out-Null
if ($LASTEXITCODE -ne 0) { "fail console $LASTEXITCODE"; exit 3 }   # never type unless the console is confirmed open
powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq 'type:player.getpos x|key:enter|wait:350|type:player.getpos y|key:enter|wait:350|type:player.getpos z|key:enter|wait:700' | Out-Null
if ($LASTEXITCODE -ne 0) { "fail guard"; exit 2 }
$cap = Join-Path $Work 'readpos_cap.png'; $prep = Join-Path $Work 'readpos_prep.png'
powershell -NoProfile -ExecutionPolicy Bypass -File $PSScriptRoot\shot_region.ps1 -Out $cap | Out-Null
powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq 'key:grave|wait:600' | Out-Null
$txt = Join-Path $Work 'readpos_ocr.txt'
foreach ($th in 135, 140, 130, 145) {                    # console text is ~150 on a dimmed ~85 background
  & $py $PSScriptRoot\ocr_prep.py $cap $prep $th 12
  (powershell -NoProfile -ExecutionPolicy Bypass -File $PSScriptRoot\ocr.ps1 -Image $prep -Scale 1) | Set-Content $txt -Encoding utf8
  $r = & $py $PSScriptRoot\parse_getpos.py $txt
  if ($r -ne 'fail') { $r; exit 0 }
}
"fail"