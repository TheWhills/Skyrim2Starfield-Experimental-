# Exterior objects lit like Skyrim (2026-11-25): every converted object had one uniform "fairly rough" sheen, so the
# road shone in the sun beside the matte terrain. Converts the exterior's models again with each shape's own Skyrim
# specular (flag, glossiness, the normal map's alpha as mask), both the plain models (C:\Modding\work\sky_all) and the
# alternate-texture variants (C:\Modding\work\sky_alt), copies the changed files into the staged exterior (same file
# names: plugins, FormIDs, grass, LOD, water and the planet unchanged) and reinstalls it. Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\object_specular.ps1
param(
    [string]$Work = "C:\Modding\work\sky_all",
    [string]$AltWork = "C:\Modding\work\sky_alt",
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
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; try { notify "object_specular: FAILED - $t" } catch {}; exit 1 }
foreach ($p in @("$Work\convert_input.json", "$Staging\objects.json", "$SF\Tools\ContentResources.zip", $Texconv)) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
$works = @($Work) + @(if (Test-Path "$AltWork\convert_input.json") { $AltWork })
$i = 0
foreach ($w in $works) {
    $i++
    Step "$i. convert $w (resumable: rerun after a stop)"
    python -I scripts\terrain\make_skyrim_objects.py convert --work $w --skyrim-data $SKY --content-resources "$SF\Tools\ContentResources.zip" --texconv $Texconv --starfield-data "$SF\Data" --resume
    if ($LASTEXITCODE -ne 0) { Fail "convert $w" }
}
foreach ($w in $works) {
    foreach ($tree in @("textures", "materials", "meshes")) {
        Step "changed $tree of $w into the staged exterior"
        python -I scripts\terrain\refresh_models.py --work $w --staging $Staging --tree $tree
        if ($LASTEXITCODE -ne 0) { Fail "refresh $tree from $w" }
    }
}
if ($NoInstall) { Write-Host "staged in $Staging (not installed: -NoInstall)"; exit 0 }
if (Get-Process Starfield -ErrorAction SilentlyContinue) { Fail "Starfield is running: close it, then rerun (the conversions are kept)" }
Step "reinstall the exterior"
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
Write-Host "`nIn game: the road beside Riverwood in low sun, against the ground next to it." -ForegroundColor Green
try { notify "object_specular: done" } catch {}
