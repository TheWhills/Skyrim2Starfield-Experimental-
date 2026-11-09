# The installed exterior with Skyrim's own collision (native Starfield mesh bodies) instead of box collision
# (2026-11-08: Riverwood's invisible road hump was a box approximation). Converts the exterior's models again
# (C:\Modding\work\sky_all, resumable), copies the new meshes into the staged exterior (plugins, FormIDs, grass, LOD,
# water and the planet unchanged) and reinstalls it. Starfield must be closed. Long: every outdoor model is converted.
#   powershell -ExecutionPolicy Bypass -File tools\owner\exterior_collision.ps1
param(
    [string]$Work = "C:\Modding\work\sky_all",
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
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; try { notify "exterior_collision: FAILED - $t" } catch {}; exit 1 }
foreach ($p in @("$Work\convert_input.json", "$Staging\overlays_params.json", "$SF\Tools\ContentResources.zip")) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
if (-not (Test-Path $Texconv)) {
    $t = Get-ChildItem C:\Modding\tools -Recurse -Filter texconv*.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($t) { $Texconv = $t.FullName } else { Fail "texconv.exe not found (give -Texconv <path>)" }
}
Step "1. convert the exterior's models with native collision (resumable: rerun after a stop)"
python -I scripts\terrain\make_skyrim_objects.py convert --work $Work --skyrim-data $SKY --content-resources "$SF\Tools\ContentResources.zip" --texconv $Texconv --starfield-data "$SF\Data" --resume
if ($LASTEXITCODE -ne 0) { Fail "convert" }
Step "2. new meshes into the staged exterior"
python -I scripts\terrain\refresh_models.py --work $Work --staging $Staging
if ($LASTEXITCODE -ne 0) { Fail "refresh" }
if ($NoInstall) { Write-Host "staged in $Staging (not installed: -NoInstall)"; exit 0 }
Step "3. reinstall the exterior"
python -I scripts\deploy_skyrim_exterior.py uninstall --starfield $SF
if ($LASTEXITCODE -ne 0) { Fail "uninstall (a file changed since install? see above; remove it from Data by hand, then rerun with the convert already done)" }
python -I scripts\deploy_skyrim_exterior.py install --staging $Staging --starfield $SF
if ($LASTEXITCODE -ne 0) { Fail "install" }
Write-Host "`nIn game: coc SKY_TamrielRiverwoodSpawn and walk over the road where the hump was." -ForegroundColor Green
try { notify "exterior_collision: done" } catch {}
