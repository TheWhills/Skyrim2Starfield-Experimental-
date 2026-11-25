# Sharper ground (2026-11-25): the ground textures at Skyrim's own size (2.44 m per repeat, was 4.88:
# scripts\terrain\ground_tiling.py) and height maps from each texture's normal map (scripts\terrain\ground_heights.py),
# in the staged exterior; then reinstalls it. Starfield must be closed.
# -NormalStrength: the ground normal maps' bump strength (scripts\terrain\ground_normals.py; 1 = as converted; the
# terrain shades bumps darker than objects do).
#   powershell -ExecutionPolicy Bypass -File tools\owner\ground_heights.ps1 [-NormalStrength 0.5]
param(
    [double]$NormalStrength = -1,
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$Texconv = "C:\Modding\tools\texconv.exe",
    [switch]$NoInstall
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; exit 1 }
if (-not $NoInstall -and (Get-Process Starfield -ErrorAction SilentlyContinue)) { Fail "Starfield is running: close it first" }
if ($NormalStrength -ge 0) {
    python -I scripts\terrain\ground_normals.py --staging $Staging --texconv $Texconv --strength $NormalStrength.ToString([cultureinfo]::InvariantCulture)
    if ($LASTEXITCODE -ne 0) { Fail "ground_normals" }
}
python -I scripts\terrain\ground_heights.py --skyrim "$SKY\Skyrim.esm" --staging $Staging --texconv $Texconv
if ($LASTEXITCODE -ne 0) { Fail "ground_heights" }
python -I scripts\terrain\ground_tiling.py --staging $Staging
if ($LASTEXITCODE -ne 0) { Fail "ground_tiling" }
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
Write-Host "`nIn game: the ground beside the road, close up." -ForegroundColor Green
