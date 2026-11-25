# Skyrim's alternate textures on the installed exterior (2026-11-25): the snowy roads (RoadChunkM01Snow ...) and the rock
# piles, drifts, mountain trims and cliffs Skyrim retextures to match the ground (snow, tundra, reach grass, beach) were
# drawn with the plain textures. Plans the mesh + texture variants (scripts\terrain\alt_textures_patch.py), converts
# them in their own work folder (resumable), adds them to the staged exterior in place (FormIDs, grass, LOD, water and
# the planet unchanged) and reinstalls it. Over 4 GiB the textures go into the Mars plugin's own archive.
# Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\alt_textures.ps1
param(
    [string]$ExteriorWork = "C:\Modding\work\sky_all",
    [string]$Work = "C:\Modding\work\sky_alt",
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$Texconv = "C:\Modding\tools\texconv.exe",
    [switch]$NoInstall
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; try { notify "alt_textures: FAILED - $t" } catch {}; exit 1 }
foreach ($p in @("$ExteriorWork\export.json", "$Staging\objects.json", "$SF\Tools\ContentResources.zip", $Texconv)) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
if (-not $NoInstall -and (Get-Process Starfield -ErrorAction SilentlyContinue)) { Fail "Starfield is running: close it first" }
Step "1. which placed references have alternate textures"
python -I scripts\terrain\alt_textures_patch.py plan --work $ExteriorWork --staging $Staging --skyrim-data $SKY --out $Work
if ($LASTEXITCODE -ne 0) { Fail "plan" }
Step "2. convert the mesh + texture variants (resumable)"
python -I scripts\terrain\make_skyrim_objects.py convert --work $Work --skyrim-data $SKY --content-resources "$SF\Tools\ContentResources.zip" --texconv $Texconv --starfield-data "$SF\Data" --resume
if ($LASTEXITCODE -ne 0) { Fail "convert" }
Step "3. add them to the staged exterior"
python -I scripts\terrain\alt_textures_patch.py apply --work $Work --staging $Staging
if ($LASTEXITCODE -ne 0) { Fail "apply" }
if ($NoInstall) { Write-Host "staged in $Staging (not installed: -NoInstall)"; exit 0 }
Step "4. reinstall the exterior"
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
Write-Host "`nIn game: coc SKY_TamrielRiverwoodSpawn, then the road at Hollyfrost Farm and snowy rock piles." -ForegroundColor Green
try { notify "alt_textures: done" } catch {}
