# Which ground texture does the game really draw? (2026-11-22, the owner's pale grey-blue band where Skyrim paints
# LRocks01NoRocks.) Paints our converted textures of the named Skyrim ground textures a solid colour and reinstalls the
# exterior; -Restore puts the real textures back and reinstalls. Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_colour_test.ps1
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_colour_test.ps1 -Restore
param(
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$Colours = "LRocks01NoRocks=magenta,LRocks01=cyan,LReachMossyRocks01=yellow",
    [switch]$Restore,
    [switch]$Label          # every converted ground texture shows its own name instead of a colour
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; exit 1 }
if ($Restore) {
    Step "1. the real ground textures back"
    python -I scripts\terrain\ground_colour_test.py restore --staging $Staging
} elseif ($Label) {
    Step "1. every ground texture labelled with its name"
    python -I scripts\terrain\ground_colour_test.py label --staging $Staging
} else {
    Step "1. paint $Colours"
    python -I scripts\terrain\ground_colour_test.py paint --staging $Staging --colours $Colours
}
if ($LASTEXITCODE -ne 0) { Fail "step 1" }
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
if ($Restore) { Write-Host "`nreal textures back in game." -ForegroundColor Green }
else { Write-Host "`nIn game: the grey band (player.setpos x -1955.40, y 749.15). Undo: -Restore" -ForegroundColor Green }
