# Grass test (2026-11-22): write quadrant byte 6 of the installed Skyrim terrain like vanilla terrain does (a per-mask
# LDefault texture), then reinstall. Vanilla fills byte 6 in almost every quadrant; ours wrote 0, and no ground cover
# grew on our terrain. Starfield must be closed. -Restore puts byte 6 back to 0 and reinstalls.
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_byte6.ps1 -Mask FlatOut
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_byte6.ps1 -Restore
param(
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$Mask = "FlatOut",
    [switch]$Restore
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
    Step "1. byte 6 back to 0"
    python -I scripts\terrain\btd_byte6.py restore --staging $Staging
} else {
    Step "1. byte 6 = the LDefault texture matching '$Mask'"
    python -I scripts\terrain\btd_byte6.py set --staging $Staging --sf-esm "$SF\Data\Starfield.esm" --mask $Mask
}
if ($LASTEXITCODE -ne 0) { Fail "btd_byte6" }
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
Write-Host "`ndone. With S2S Grass Native (--control) on, land on Nirn / coc SKY_TamrielRiverwoodSpawn and look for grass." -ForegroundColor Green
