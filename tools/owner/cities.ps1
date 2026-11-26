# Skyrim's walled cities as their own worldspaces next to the installed Tamriel, reached through their gates
# (owner 2026-11-10: "separate, like Skyrim"; 2026-11-25: Whiterun first). docs/terrain/skyrim-cities.md.
# Starfield must be closed (checked before the install).
#   powershell -ExecutionPolicy Bypass -File tools\owner\cities.ps1                        # Whiterun (default)
#   powershell -ExecutionPolicy Bypass -File tools\owner\cities.ps1 -Cities WhiterunWorld,SolitudeWorld
#   powershell -ExecutionPolicy Bypass -File tools\owner\cities.ps1 -Uninstall             # take the cities out again
# Per city:
#   1. terrain: an overlay with the installed Tamriel's options (--like its build command: height offset, water, biome),
#      no planet plugin of its own (--no-mars), its ground CUT from the installed Tamriel's terrain file (--terrain-from:
#      Tamriel's heights, textures, blend and grass slots exactly as installed; Tamriel's plugin draws the textures);
#   2. objects: export / select / convert (resumable; current conversions: Skyrim specular, alternate textures as their
#      own models, native collision) / stage (city plugin through dotnet\TerrainOverlays) / check;
#   3. baked snow on the city's snowy statics (scripts\terrain\snow_bake.py; nothing to do for Whiterun).
# Then ONE plugin (SkyrimWorlds_Register.esm) puts every city world on Tamriel's planet and adds the gates: a load door
# at each Skyrim gate, both ways (register_worlds.py --skyrim). scripts\deploy_skyrim_city.py installs it all into
# Starfield\Data (city archive without the files Tamriel's archives already hold), hides the gate statics in place and
# records everything for uninstall. MO2: tick the new plugins after SkyrimTerrainTamriel_Mars.esm, the register plugin last.
param(
    [string[]]$Cities = @("WhiterunWorld"),
    [string]$Tamriel = "C:\Modding\staging\skyrim_all",           # the installed exterior (terrain cut from it)
    [string]$TamrielBuild = "C:\Modding\staging\skyrim_tamriel",   # its terrain build (build_command.txt for --like)
    [string]$Staging = "C:\Modding\staging",
    [string]$Work = "C:\Modding\work",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$Texconv = "C:\Modding\tools\texconv.exe",
    # water type of the cities' water (make_skyrim_objects.py stage --water-type): "probe" = three types side by side in
    # Whiterun (pool WaterOceanClear, Gildergreen ring WaterClearSterile, the rest WaterOceanDark), or one WATR hex
    [string]$WaterType = "probe",
    [switch]$NoInstall,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; exit 1 }
function NoGame { if (Get-Process Starfield -ErrorAction SilentlyContinue) { Fail "Starfield is running: close it first" } }
if ($Uninstall) {
    NoGame
    python -I scripts\deploy_skyrim_city.py uninstall --starfield $SF
    if ($LASTEXITCODE -ne 0) { Fail "uninstall" }
    exit 0
}
# where each city's coc marker goes (Skyrim cell; "" = the overlay's centre)
$Arrival = @{ "WhiterunWorld" = "5,-2" }
foreach ($p in @("$TamrielBuild\build_command.txt", "$Tamriel\overlays_params.json", "$Tamriel\formids.json", "$SKY\Skyrim.esm",
                 "$SF\Data\Starfield.esm", "$SF\Tools\ContentResources.zip")) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
if (-not (Test-Path $Texconv)) {
    $t = Get-ChildItem C:\Modding\tools -Recurse -Filter texconv*.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($t) { $Texconv = $t.FullName } else { Fail "texconv.exe not found (give -Texconv <path>)" }
}
$built = @()
foreach ($c in $Cities) {
    $low = $c.ToLower()
    $terrain = Join-Path $Staging "sky_${low}_terrain"
    $out = Join-Path $Staging "sky_$low"
    $w = Join-Path $Work "city_$low"
    Step "$c 1/6 terrain cut from the installed Tamriel"
    $ta = @("build", "--skyrim", "$SKY\Skyrim.esm", "--world-edid", $c, "--frame", "local", "--like", $TamrielBuild, "--no-mars",
            "--terrain-from", $Tamriel, "--sf-data", "$SF\Data", "--out", $terrain)
    if ($Arrival.ContainsKey($c)) { $ta += @("--arrival", $Arrival[$c]) }
    python -I scripts\terrain\make_skyrim_overlay.py @ta
    if ($LASTEXITCODE -ne 0) { Fail "$c terrain" }
    Step "$c 2/6 export + select"
    python -I scripts\terrain\make_skyrim_objects.py export --skyrim "$SKY\Skyrim.esm" --world-edid $c --work $w
    if ($LASTEXITCODE -ne 0) { Fail "$c export" }
    python -I scripts\terrain\make_skyrim_objects.py select --work $w --terrain $terrain
    if ($LASTEXITCODE -ne 0) { Fail "$c select" }
    Step "$c 3/6 convert (resumable)"
    python -I scripts\terrain\make_skyrim_objects.py convert --work $w --skyrim-data $SKY --content-resources "$SF\Tools\ContentResources.zip" --texconv $Texconv --starfield-data "$SF\Data" --resume
    if ($LASTEXITCODE -ne 0) { Fail "$c convert" }
    Step "$c 4/6 stage + plugin"
    python -I scripts\terrain\make_skyrim_objects.py stage --work $w --terrain $terrain --out $out --sf-esm "$SF\Data\Starfield.esm" --water-type $WaterType
    if ($LASTEXITCODE -ne 0) { Fail "$c stage" }
    Step "$c 5/6 check (a city on terraces fails 'object origins sit on the terrain': expected)"
    python -I scripts\terrain\make_skyrim_objects.py check --out $out | Select-String -Pattern "^\s+(ok|FAIL)"
    Step "$c 6/6 baked snow"
    python -I scripts\terrain\snow_bake.py --work $w --staging $out --out (Join-Path $Work "city_${low}_snow") --skyrim-data $SKY --content-resources "$SF\Tools\ContentResources.zip" --texconv $Texconv --starfield-data "$SF\Data"
    if ($LASTEXITCODE -ne 0) { Fail "$c snow_bake" }
    $built += $out
}
Step "registration + gates: every city world on Tamriel's planet, a load door at each gate both ways"
$reg = Join-Path $Staging "sky_worlds_register"
$regArgs = @("--main", $Tamriel, "--out", $reg, "--skyrim", "$SKY\Skyrim.esm")
foreach ($b in $built) { $regArgs += @("--world", $b) }
python -I scripts\terrain\register_worlds.py @regArgs
if ($LASTEXITCODE -ne 0) { Fail "register_worlds" }
if ($NoInstall) { exit 0 }
Step "install into $SF\Data"
NoGame
if (Test-Path "$SF\Data\SkyrimCities.deploy.json") {
    python -I scripts\deploy_skyrim_city.py uninstall --starfield $SF
    if ($LASTEXITCODE -ne 0) { Fail "uninstall of the previous cities" }
}
$ia = @("install", "--register", $reg, "--exterior", $Tamriel, "--starfield", $SF)
foreach ($b in $built) { $ia += @("--city", $b) }
python -I scripts\deploy_skyrim_city.py @ia
if ($LASTEXITCODE -ne 0) { Fail "install" }
