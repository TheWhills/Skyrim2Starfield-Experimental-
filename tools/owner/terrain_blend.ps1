# Ground textures that fade into each other instead of meeting in straight lines (2026-11-21, owner: "spots in the
# terrain that are supposed to fade or have a snow texture or blend kind of just got off like squares into each other").
# Rebuilds the installed exterior's terrain into a separate folder with the new blend (landtex "noise"), copies only the
# texture layers into the installed exterior's terrain files (heights, plugins, objects, grass, LOD, water, planet
# unchanged) and reinstalls it. Starfield must be closed. The rebuild covers all of Tamriel, so it takes a while.
#   powershell -ExecutionPolicy Bypass -File tools\owner\terrain_blend.ps1
#   -Blend solid gives the old straight borders back; -Warp <m> sets how far borders may wander (default 3.5)
param(
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$Fresh = "C:\Modding\staging\skyrim_all_blend",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [ValidateSet("noise", "solid", "dither")][string]$Blend = "noise",
    [double]$Warp = 3.5,
    [switch]$SkipRebuild,       # the fresh build is already there (e.g. after a failed install): splice and install only
    [switch]$NoInstall
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; try { notify "terrain_blend: FAILED - $t" } catch {}; exit 1 }
$t0 = Get-Date
if (-not (Test-Path "$Staging\build_command.txt")) { Fail "missing $Staging\build_command.txt" }
if (-not $SkipRebuild) {
    Step "1. the terrain again with the new blend, into $Fresh (all of Tamriel: slow)"
    python -I scripts\terrain\refresh_btd.py rebuild --staging $Staging --fresh $Fresh --blend $Blend --warp $Warp.ToString([cultureinfo]::InvariantCulture)
    if ($LASTEXITCODE -ne 0) { Fail "rebuild" }
}
Step "2. its texture layers into the installed exterior's terrain (heights kept)"
python -I scripts\terrain\refresh_btd.py splice --staging $Staging --fresh $Fresh
if ($LASTEXITCODE -ne 0) { Fail "splice" }
if ($NoInstall) { Write-Host "staged in $Staging (not installed: -NoInstall)"; exit 0 }
Step "3. reinstall the exterior"
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
