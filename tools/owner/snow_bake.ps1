# Snow on rocks, baked into the objects (2026-11-25): Skyrim's snowy statics get variants whose vertex colours carry a
# snow mask, with vanilla Starfield's two-layer snow material (scripts\terrain\snow_bake.py), added to the staged
# exterior in place; then reinstalls it. Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\snow_bake.ps1 [-Model "Landscape\Rocks\RockL02.nif"]
param(
    [string]$Model = "",
    [string]$Work = "C:\Modding\work\sky_all",
    [string]$Out = "C:\Modding\work\sky_snow",
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
$a = @("--work", $Work, "--staging", $Staging, "--out", $Out, "--skyrim-data", $SKY, "--content-resources",
       "$SF\Tools\ContentResources.zip", "--texconv", $Texconv, "--starfield-data", "$SF\Data")
if ($Model) { $a += @("--model", $Model) }
python -I scripts\terrain\snow_bake.py @a
if ($LASTEXITCODE -ne 0) { Fail "snow_bake" }
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
Write-Host "`nIn game: snowy boulders ~80 m north of SKY_TamrielRiverwoodSpawn (RockL02Snow)." -ForegroundColor Green
