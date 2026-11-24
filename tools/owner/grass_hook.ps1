# Skyrim's grass on EVERY converted Skyrim ground texture (2026-11-24, route B of docs/re/ground-cover-density.md).
# Needs the S2SGrass SFSE plugin (native/combat/sfse/grass), which this script builds if needed and puts into the
# grass mod. Replaces the 7-slot build of grass_tamriel.ps1:
# 1. terrain: back to the textures as converted (undoes grass_tamriel.ps1's slot placeholders, if any);
# 2. reinstall the exterior;
# 3. grass mod: every grassy Skyrim texture's own grasses and cover (underwater kelp / coral left out: no water),
#    no biome override, plus SFSE\Plugins\S2SGrass.ini (texture -> cover) and S2SGrass.dll.
# Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\grass_hook.ps1
#   powershell -ExecutionPolicy Bypass -File tools\owner\grass_hook.ps1 -GrassOnly    (terrain already done)
# Log after a game start: Documents\My Games\Starfield\SFSE\Logs\S2SGrass.log
param(
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$Grass = "$env:LOCALAPPDATA\ModOrganizer\Starfield\mods\S2S Grass Native",
    [string]$Texconv = "C:\Modding\tools\texconv.exe",
    [double]$DensityScale = 1.0,
    [double]$Threshold = 0.1,
    [switch]$GrassOnly
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; exit 1 }
foreach ($p in @("$Staging\overlays_params.json", "$SF\Data\Starfield.esm", "$SKY\Skyrim.esm")) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
Step "0. the S2SGrass SFSE plugin"
$dll = "native\combat\sfse\build\windows\x64\releasedbg\S2SGrass.dll"
Push-Location native\combat\sfse
xmake build S2SGrass
$ok = $LASTEXITCODE -eq 0
Pop-Location
if (-not $ok -or -not (Test-Path $dll)) { Fail "xmake build S2SGrass (native\combat\sfse\README.md: Build)" }
if (-not $GrassOnly) {
    Step "1. terrain: the textures as converted"
    if (Test-Path "$Staging\btd_before_slots") {
        python -I scripts\terrain\btd_cover.py slots-restore --staging $Staging
        if ($LASTEXITCODE -ne 0) { Fail "btd_cover slots-restore" }
    } else {
        Write-Host "  no slot placeholders to undo"
    }
    # 2026-11-24: the byte-6 grass test (terrain_byte6.ps1, 2026-11-22/23) left LDefault003FlatIn in byte 6 of every
    # land quadrant; as a sixth layer it took the base layer's share (90 % of Skyrim's LRocks01NoRocks ground drew
    # Nirn's FlatInner ground). The converter writes byte 6 = 0, so clearing it is always right here.
    python -I scripts\terrain\btd_byte6.py restore --staging $Staging
    if ($LASTEXITCODE -ne 0) { Fail "btd_byte6 restore" }
    Step "2. reinstall the exterior"
    if (Test-Path "$SF\Data\SkyrimExterior.deploy.json") {
        python -I scripts\deploy_skyrim_exterior.py uninstall --starfield $SF --staging $Staging
        if ($LASTEXITCODE -ne 0) { Fail "uninstall" }
    }
    python -I scripts\deploy_skyrim_exterior.py install --staging $Staging --starfield $SF
    if ($LASTEXITCODE -ne 0) { Fail "install" }
    if (Test-Path "$SF\Data\FO4Port.esm") {
        $extPlugin = (Get-Content "$Staging\formids.json" -Raw | ConvertFrom-Json).plugin
        python -I scripts\terrain\apply_ref_overrides.py --from "$SF\Data\FO4Port.esm" --into "$SF\Data\$extPlugin"
        if ($LASTEXITCODE -ne 0) { Fail "apply_ref_overrides" }
    }
}
Step "3. grass mod: every grassy texture its own Skyrim grass"
python -I scripts\terrain\skyrim_grass_native.py --skyrim "$SKY\Skyrim.esm" --skyrim-data $SKY --starfield $SF `
    --terrain $Staging --texconv $Texconv --out $Grass `
    --palette-hook --threshold $Threshold --density-scale $DensityScale `
    --flat-paths --coverage 100 --no-water-clamp --no-back-faces
if ($LASTEXITCODE -ne 0) { Fail "skyrim_grass_native" }
New-Item -ItemType Directory -Force "$Grass\SFSE\Plugins" | Out-Null
Copy-Item $dll "$Grass\SFSE\Plugins\S2SGrass.dll" -Force
Write-Host "  S2SGrass.dll -> $Grass\SFSE\Plugins" -ForegroundColor Green
Write-Host "`ndone. S2S Grass Native on in MO2 (after SkyrimTerrainTamriel_Mars.esm), start through SFSE, then" -ForegroundColor Green
Write-Host "coc SKY_TamrielRiverwoodSpawn. Send Documents\My Games\Starfield\SFSE\Logs\S2SGrass.log with the screenshots." -ForegroundColor Green
