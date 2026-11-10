# Skyrim's walled cities as their own worldspaces next to the installed Tamriel (owner 2026-11-10: "separate, like
# Skyrim"). docs/terrain/skyrim-cities.md. Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\cities.ps1                       # all five
#   powershell -ExecutionPolicy Bypass -File tools\owner\cities.ps1 -Cities WhiterunWorld  # one first
# Per city: terrain overlay with Tamriel's own options (--like: height offset, ground, water, biome), no planet
# registration of its own (--no-mars); its objects exported / selected / converted (resumable) / staged (plugins
# through dotnet\TerrainOverlays) / checked. Then ONE registration plugin puts every city world on Tamriel's planet
# (register_worlds.py), and everything is copied into the MO2 mod folder "S2S Skyrim Cities" (loose files).
# In game: coc <the city's COC marker> (printed at the end; gates come later).
param(
    [string[]]$Cities = @("WhiterunWorld", "SolitudeWorld", "WindhelmWorld", "MarkarthWorld", "RiftenWorld"),
    [string]$Tamriel = "C:\Modding\staging\skyrim_all",
    [string]$Staging = "C:\Modding\staging",
    [string]$Work = "C:\Modding\work",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$Texconv = "C:\Modding\tools\texconv.exe",
    [string]$Mod = "$env:LOCALAPPDATA\ModOrganizer\Starfield\mods\S2S Skyrim Cities",
    [switch]$NoInstall
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; exit 1 }
foreach ($p in @("$Tamriel\build_command.txt", "$Tamriel\overlays_params.json", "$SKY\Skyrim.esm", "$SF\Data\Starfield.esm", "$SF\Tools\ContentResources.zip")) {
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
    Step "$c 1/5 terrain overlay (like $Tamriel)"
    python -I scripts\terrain\make_skyrim_overlay.py build --world-edid $c --frame local --like $Tamriel --no-mars --sf-data "$SF\Data" --out $terrain
    if ($LASTEXITCODE -ne 0) { Fail "$c terrain" }
    Step "$c 2/5 export + select"
    python -I scripts\terrain\make_skyrim_objects.py export --skyrim "$SKY\Skyrim.esm" --world-edid $c --work $w
    if ($LASTEXITCODE -ne 0) { Fail "$c export" }
    python -I scripts\terrain\make_skyrim_objects.py select --work $w --terrain $terrain
    if ($LASTEXITCODE -ne 0) { Fail "$c select" }
    Step "$c 3/5 convert (resumable)"
    python -I scripts\terrain\make_skyrim_objects.py convert --work $w --skyrim-data $SKY --content-resources "$SF\Tools\ContentResources.zip" --texconv $Texconv --starfield-data "$SF\Data" --resume
    if ($LASTEXITCODE -ne 0) { Fail "$c convert" }
    Step "$c 4/5 stage + plugins"
    python -I scripts\terrain\make_skyrim_objects.py stage --work $w --terrain $terrain --out $out --sf-esm "$SF\Data\Starfield.esm"
    if ($LASTEXITCODE -ne 0) { Fail "$c stage" }
    Step "$c 5/5 check"
    python -I scripts\terrain\make_skyrim_objects.py check --out $out
    $built += $out
}
Step "registration: every city world on Tamriel's planet"
$reg = Join-Path $Staging "sky_worlds_register"
$regArgs = @("--main", $Tamriel, "--out", $reg)
foreach ($b in $built) { $regArgs += @("--world", $b) }
python -I scripts\terrain\register_worlds.py @regArgs
if ($LASTEXITCODE -ne 0) { Fail "register_worlds" }
if ($NoInstall) { exit 0 }
Step "install into $Mod"
New-Item -ItemType Directory -Force -Path $Mod | Out-Null
foreach ($b in $built) {
    if (Test-Path "$b\Data") { robocopy "$b\Data" $Mod /E /NFL /NDL /NJH /NJS /NP | Out-Null }
    Get-ChildItem $b -Filter *.esm | Where-Object { $_.Name -notlike "*_Mars.esm" } | Copy-Item -Destination $Mod -Force
}
Copy-Item "$reg\SkyrimWorlds_Register.esm" -Destination $Mod -Force
Write-Host "`nMO2: refresh (F5), enable 'S2S Skyrim Cities' and its plugins (SkyrimWorlds_Register.esm last)." -ForegroundColor Green
foreach ($b in $built) {
    $p = Get-Content "$b\overlays_params.json" -Raw | ConvertFrom-Json
    foreach ($o in $p.overlays) { Write-Host "  in game: coc $($o.coc)" }
}
