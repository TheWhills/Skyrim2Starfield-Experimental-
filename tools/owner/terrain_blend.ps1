# Ground textures that fade into each other instead of meeting in straight lines (2026-11-21, owner: "spots in the
# terrain that are supposed to fade or have a snow texture or blend kind of just got off like squares into each other").
# Recomputes the texture layers of the installed exterior's terrain files from Skyrim.esm with the new blend (landtex
# "noise"), using the staging's own texture choices, after a spot check that the old way reproduces what is installed.
# Heights, plugins, objects, grass, LOD, water and the planet stay as they are. Then reinstalls. Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_blend.ps1
#   -Blend solid gives the old straight borders back; -Warp <m> sets how far borders may wander (default 3.5)
#   The terrain files as first built are kept in <Staging>\btd_before_blend.
param(
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [ValidateSet("noise", "solid", "dither")][string]$Blend = "noise",
    [double]$Warp = 3.5,
    [switch]$NoInstall
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; try { notify "terrain_blend: FAILED - $t" } catch {}; exit 1 }
$t0 = Get-Date
foreach ($p in @("$Staging\overlays_params.json", "$SKY\Skyrim.esm", "$SF\Data\Starfield.esm")) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
Step "1. the terrain's texture layers again with the $Blend blend (heights kept)"
python -I scripts\terrain\refresh_btd.py recompute --staging $Staging --skyrim "$SKY\Skyrim.esm" --sf-data "$SF\Data" --blend $Blend --warp $Warp.ToString([cultureinfo]::InvariantCulture)
if ($LASTEXITCODE -ne 0) { Fail "recompute (nothing installed; see the spot check above)" }
if ($NoInstall) { Write-Host "staged in $Staging (not installed: -NoInstall)"; exit 0 }
Step "2. reinstall the exterior"
if (Test-Path "$SF\Data\SkyrimExterior.deploy.json") {
    python -I scripts\deploy_skyrim_exterior.py uninstall --starfield $SF --staging $Staging
    if ($LASTEXITCODE -ne 0) { Fail "uninstall (a file changed since install? see above)" }
}
python -I scripts\deploy_skyrim_exterior.py install --staging $Staging --starfield $SF
if ($LASTEXITCODE -ne 0) { Fail "install" }
# the fresh exterior plugin is unpatched: hide the statics FO4Port.esm replaces again (as riverwood_doors.ps1 step 5)
if (Test-Path "$SF\Data\FO4Port.esm") {
    $extPlugin = (Get-Content "$Staging\formids.json" -Raw | ConvertFrom-Json).plugin
    python -I scripts\terrain\apply_ref_overrides.py --from "$SF\Data\FO4Port.esm" --into "$SF\Data\$extPlugin"
    if ($LASTEXITCODE -ne 0) { Fail "apply_ref_overrides" }
}
$mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
Write-Host "`ndone in $mins min. In game: coc SKY_TamrielRiverwoodSpawn and look where the forest floor meets the dirt." -ForegroundColor Green
try { notify "terrain_blend: done ($mins min)" } catch {}
