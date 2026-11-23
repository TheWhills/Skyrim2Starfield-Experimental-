# Grass test (2026-11-23): uniform biome-mask density maps for the installed Skyrim terrain, then reinstall.
# Ground cover on our terrain grows only in small spots near banks and edges; vanilla terrain blocks ship density
# maps (textures\terrain\<block>_<mask>.dds) and ours have none. Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_density.ps1            (every pixel 255)
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_density.ps1 -Remove
param(
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [int]$Value = 255,
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; exit 1 }
foreach ($p in @("$Staging\overlays_params.json", "$SF\Data\Starfield.esm")) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
if ($Remove) {
    Step "1. remove the density maps"
    python -I scripts\terrain\density_maps.py remove --staging $Staging
} else {
    Step "1. uniform density maps (value $Value)"
    python -I scripts\terrain\density_maps.py uniform --staging $Staging --value $Value
}
if ($LASTEXITCODE -ne 0) { Fail "density_maps" }
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
Write-Host "`ndone. coc SKY_TamrielRiverwoodSpawn and look at the flat forest floor." -ForegroundColor Green
