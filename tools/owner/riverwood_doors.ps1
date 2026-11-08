# Riverwood <-> Sleeping Giant Inn: load doors between the installed exterior (C:\Modding\staging\skyrim_all, on the
# planet) and the converted inn (docs/interior/skyrim-interiors.md "Doors between the exterior and the interiors").
# No exterior rebuild: FO4Port.esm overrides the exterior's door. Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\riverwood_doors.ps1
# -Navmesh: also Skyrim's exterior navmesh around Riverwood (-NavAround, -NavRadius Skyrim cells each side) in the
# same FO4Port.esm, then make_skyrim_navmesh.py compare (<Work>\navmesh\compare.html). docs/terrain/exterior-navmesh.md
# Every build now also registers its navmeshes (interiors too) in a NAVI override and gives load doors XNDP;
# $env:NAVI="off" before running leaves the NAVI out.
param(
    [string]$Cells = "RiverwoodSleepingGiantInn",
    [string]$Find = "",          # a regex of interior EditorIDs instead of -Cells, e.g. "^Riverwood"
    [string]$Exterior = "C:\Modding\staging\skyrim_all",
    [string]$Work = "C:\Modding\work\s2s\riverwood_doors",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$Texconv = "C:\Modding\tools\texconv.exe",
    [switch]$NoInstall,
    [switch]$Navmesh,
    [string]$NavAround = "Riverwood",
    [int]$NavRadius = 2
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; try { notify "riverwood_doors: FAILED - $t" } catch {}; exit 1 }
foreach ($p in @("$Exterior\formids.json", "$Exterior\overlays_params.json", "$SKY\Skyrim.esm", "$SF\Data\Starfield.esm", "$SF\Tools\ContentResources.zip")) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
if (-not (Test-Path $Texconv)) {
    $t = Get-ChildItem C:\Modding\tools -Recurse -Filter texconv*.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($t) { $Texconv = $t.FullName } else { Fail "texconv.exe not found (give -Texconv <path>)" }
}
$nav = Get-ChildItem C:\Modding -Recurse -Filter navmesh_defaults.json -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1

Step "1. interior batch with doors to the exterior"
$args1 = @("batch", "--skyrim", "$SKY\Skyrim.esm", "--work", $Work, "--exterior")
if ($Find) { $args1 += @("--find", $Find) } else { $args1 += @("--cells", $Cells) }
if ($nav) { $args1 += @("--navmesh-defaults", $nav.FullName) }
python -I scripts\interior\make_skyrim_interior.py @args1
if ($LASTEXITCODE -ne 0) { Fail "batch" }

Step "2. convert the inn's models (resumable)"
python -I scripts\terrain\make_skyrim_objects.py convert --work $Work --skyrim-data $SKY --content-resources "$SF\Tools\ContentResources.zip" --texconv $Texconv --starfield-data "$SF\Data" --resume
if ($LASTEXITCODE -ne 0) { Fail "convert" }
python -I scripts\interior\make_skyrim_interior.py check --work $Work

$navWork = Join-Path $Work "navmesh"
if ($Navmesh) {
    Step "2b. exterior navmesh around $NavAround"
    $navDef = Join-Path $navWork "survey\navmesh_defaults_exterior.json"
    if (-not (Test-Path $navDef)) {
        $sv = @("--esm", "$SF\Data\Starfield.esm", "--out", (Join-Path $navWork "survey"), "--exterior", "--max", "400")
        if (Test-Path "$SF\Data\ShatteredSpace.esm") { $sv += @("--navi-esm", "$SF\Data\ShatteredSpace.esm") }
        python -I scripts\interior\navmesh_survey.py @sv
        if ($LASTEXITCODE -ne 0) { Fail "navmesh survey" }
    }
    python -I scripts\terrain\make_skyrim_navmesh.py export --skyrim "$SKY\Skyrim.esm" --exterior $Exterior --out $navWork --around $NavAround --radius $NavRadius --navmesh-defaults $navDef
    if ($LASTEXITCODE -ne 0) { Fail "navmesh export" }
}

Step "3. FO4Port.esm with the doors linked both ways"
$staging = Join-Path $Work "convert"
$env:STARFIELD_DATA = "$SF\Data"
$env:EXTERIOR_DIR = $Exterior
$env:EXTERIOR_DOORS = Join-Path $Work "exterior_doors.json"
if ($Navmesh) { $env:EXTERIOR_NAVMESH = Join-Path $navWork "exterior_navmesh.json" }
dotnet run --project dotnet\PluginSpike -- $staging (Join-Path $staging "manifest.json") ("@" + (Join-Path $Work "cells.txt"))
$rc = $LASTEXITCODE
Remove-Item Env:EXTERIOR_DIR, Env:EXTERIOR_DOORS, Env:EXTERIOR_NAVMESH -ErrorAction SilentlyContinue
if ($rc -ne 0) { Fail "PluginSpike (paste its output: compile errors name the Mutagen property)" }

if ($Navmesh) {
    Step "3b. compare the navmesh in FO4Port.esm with Skyrim's"
    python -I scripts\terrain\make_skyrim_navmesh.py compare --skyrim "$SKY\Skyrim.esm" --work $navWork --plugin (Join-Path $staging "FO4Port.esm")
    if ($LASTEXITCODE -ne 0) { Fail "navmesh compare" }
    Write-Host "open $navWork\compare.html in a browser" -ForegroundColor Green
}
if ($NoInstall) { Write-Host "built in $staging (not installed: -NoInstall)"; exit 0 }
Step "4. install (replaces the Oct 23 FO4Port test)"
if (Test-Path "$SF\Data\FO4Port.deploy.json") { python -I scripts\deploy_starfield.py uninstall --starfield $SF }
python -I scripts\deploy_starfield.py install --staging $staging --starfield $SF
if ($LASTEXITCODE -ne 0) { Fail "install" }
Write-Host "`nIn game: coc SKY_TamrielRiverwoodSpawn, walk to the Sleeping Giant Inn's door and use it; inside, use the front door back out." -ForegroundColor Green
try { notify "riverwood_doors: built and installed" } catch {}
