# Snow on rocks (2026-11-25): Starfield's global snow layer on the exterior cells where Skyrim's objects carry snow
# directional materials (scripts\terrain\snow_layer.py), then reinstalls the exterior. Starfield must be closed.
# -Off removes the layer from every cell again.
#   powershell -ExecutionPolicy Bypass -File tools\owner\snow_layer.ps1 [-Off]
param(
    [switch]$Off,
    [string]$Work = "C:\Modding\work\sky_all",
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [switch]$NoInstall
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; exit 1 }
if (-not $NoInstall -and (Get-Process Starfield -ErrorAction SilentlyContinue)) { Fail "Starfield is running: close it first" }
$a = @("--work", $Work, "--staging", $Staging, "--skyrim-data", $SKY, "--sf-esm", "$SF\Data\Starfield.esm")
if ($Off) { $a += "--off" }
python -I scripts\terrain\snow_layer.py @a
if ($LASTEXITCODE -ne 0) { Fail "snow_layer" }
if ($NoInstall) { exit 0 }
if (Test-Path "$SF\Data\SkyrimExterior.deploy.json") {
    python -I scripts\deploy_skyrim_exterior.py uninstall --starfield $SF --staging $Staging
    if ($LASTEXITCODE -ne 0) { Fail "uninstall" }
}
python -I scripts\deploy_skyrim_exterior.py install --staging $Staging --starfield $SF
if ($LASTEXITCODE -ne 0) { Fail "install" }
if (Test-Path "$SF\Data\FO4Port.esm") {      # hide the statics FO4Port.esm replaces again (as riverwood_doors.ps1)
    $extPlugin = (Get-Content "$Staging\formids.json" -Raw | ConvertFrom-Json).plugin
    python -I scripts\terrain\apply_ref_overrides.py --from "$SF\Data\FO4Port.esm" --into "$SF\Data\$extPlugin"
    if ($LASTEXITCODE -ne 0) { Fail "apply_ref_overrides" }
}
Write-Host "`nIn game: rocks ~80 m north of SKY_TamrielRiverwoodSpawn, Hollyfrost Farm; Riverwood itself stays bare." -ForegroundColor Green
