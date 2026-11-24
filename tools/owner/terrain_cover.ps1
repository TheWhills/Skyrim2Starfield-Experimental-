# Grass test (2026-11-23): re-encode the installed Skyrim terrain so ground cover reads the same textures the renderer
# draws (ground cover reads the layer bytes from the other end: btd_cover.py), then reinstall. Starfield must be
# closed. -Restore puts the previous terrain files back and reinstalls.
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_cover.ps1
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_cover.ps1 -Restore
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_cover.ps1 -Pad 40   (diagnostic: unique padding)
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_cover.ps1 -UniformRow 58 -UniformCol 76
#       (diagnostic: 3 x 3 quadrants = one texture in every layer at full strength; -UniformRestore undoes it)
param(
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$Grass = "$env:LOCALAPPDATA\ModOrganizer\Starfield\mods\S2S Grass Native",
    [switch]$Restore,
    [int]$Pad = 0,
    [int]$UniformRow = -1,
    [int]$UniformCol = -1,
    [int]$Alpha = 7,
    [switch]$UniformRestore
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; exit 1 }
foreach ($p in @("$Staging\overlays_params.json", "$SF\Data\Starfield.esm")) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
if ($Restore) {
    Step "1. the terrain files from before the re-encoding"
    python -I scripts\terrain\btd_cover.py restore --staging $Staging
} elseif ($UniformRestore) {
    Step "1. the terrain files from before the uniform patch"
    python -I scripts\terrain\btd_cover.py uniform-restore --staging $Staging
} elseif ($UniformRow -ge 0) {
    Step "1. diagnostic: 3 x 3 quadrants around ($UniformRow, $UniformCol) = field grass in every layer, alpha $Alpha"
    python -I scripts\terrain\btd_cover.py uniform --staging $Staging --quad $UniformRow $UniformCol --alpha $Alpha
} elseif ($Pad -gt 0) {
    Step "1. diagnostic: $Pad unique vanilla textures inserted before the mask entry"
    python -I scripts\terrain\btd_cover.py pad --staging $Staging --sf-esm "$SF\Data\Starfield.esm" --count $Pad
} else {
    Step "1. re-encode for ground cover"
    python -I scripts\terrain\btd_cover.py set --staging $Staging --grass $Grass
}
if ($LASTEXITCODE -ne 0) { Fail "btd_cover" }
Step "2. reinstall the exterior"
if (Test-Path "$SF\Data\SkyrimExterior.deploy.json") {
    python -I scripts\deploy_skyrim_exterior.py uninstall --starfield $SF --staging $Staging
    if ($LASTEXITCODE -ne 0) { Fail "uninstall" }
}
python -I scripts\deploy_skyrim_exterior.py install --staging $Staging --starfield $SF
if ($LASTEXITCODE -ne 0) { Fail "install" }
if (Test-Path "$SF\Data\FO4Port.esm") {
    $extPlugin = (Get-Content "$Staging\formids.json" -Raw | ConvertFrom-Json).plugin
    python -I scripts\terrain\apply_ref_overrides.py --from "$SF\Data\FO4Port.esm" --into "$SF\Data\$extPlugin"
    if ($LASTEXITCODE -ne 0) { Fail "apply_ref_overrides" }
}
Write-Host "`ndone. coc SKY_TamrielRiverwoodSpawn: grass should now grow where its texture is drawn." -ForegroundColor Green
