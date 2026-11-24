# Skyrim's grass on the whole staged Tamriel (2026-11-24, route A of docs/re/ground-cover-density.md).
# 1. terrain: the 7 grassiest Skyrim land textures (fo4sf.grassslots.DEFAULT_SLOT_MAP: LFieldGrass02, LPineForest02,
#    LRocks01, LGrassSnow01, LFieldGrass01, LTundra01, LFallForestGrass01NoFern) painted as Starfield's 7 slot
#    placeholders everywhere, same alphas; byte 6 cleared everywhere (no more pale-sand leftovers);
# 2. reinstall the exterior;
# 3. grass mod: each texture's Skyrim grasses (own models at new paths directly in landscape\grass\, Skyrim's own
#    textures on the game's grass shader, clamped, no terrain tint, no water clamps, no mirrored back faces), and
#    Nirn's ocean biome's first LNAM / ANAM of each mask = {that texture, its cover}.
# The other grassy Skyrim textures keep their look but grow nothing (7 slots per world without an SFSE plugin).
# Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\grass_tamriel.ps1
#   powershell -ExecutionPolicy Bypass -File tools\owner\grass_tamriel.ps1 -GrassOnly     (terrain already done)
#   powershell -ExecutionPolicy Bypass -File tools\owner\grass_tamriel.ps1 -Restore       (terrain as before)
param(
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$Grass = "$env:LOCALAPPDATA\ModOrganizer\Starfield\mods\S2S Grass Native",
    [string]$Texconv = "C:\Modding\tools\texconv.exe",
    [string]$Map = "",
    [double]$DensityScale = 1.0,
    [double]$Threshold = 0.1,
    [switch]$GrassOnly,
    [switch]$Restore
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; exit 1 }
foreach ($p in @("$Staging\overlays_params.json", "$SF\Data\Starfield.esm", "$SKY\Skyrim.esm")) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
$mapArgs = @()
if ($Map) { $mapArgs = @("--map", $Map) }
if (-not $GrassOnly) {
    if ($Restore) {
        Step "1. the terrain files from before the slots"
        python -I scripts\terrain\btd_cover.py slots-restore --staging $Staging
    } else {
        Step "1. terrain: the 7 grassy Skyrim textures as slot placeholders, byte 6 cleared"
        python -I scripts\terrain\btd_cover.py slots --staging $Staging @mapArgs
    }
    if ($LASTEXITCODE -ne 0) { Fail "btd_cover" }
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
    if ($Restore) {
        Write-Host "`ndone: terrain as before. Rebuild S2S Grass Native with your usual command." -ForegroundColor Green
        exit 0
    }
}
$slotMap = "default"
if ($Map) { $slotMap = $Map }
Step "3. grass mod: the 7 textures' Skyrim grasses"
python -I scripts\terrain\skyrim_grass_native.py --skyrim "$SKY\Skyrim.esm" --skyrim-data $SKY --starfield $SF `
    --terrain $Staging --texconv $Texconv --out $Grass `
    --slot-map $slotMap --threshold $Threshold --density-scale $DensityScale `
    --flat-paths --coverage 100 --no-water-clamp --no-back-faces
if ($LASTEXITCODE -ne 0) { Fail "skyrim_grass_native" }
Write-Host "`ndone. S2S Grass Native on in MO2 (after SkyrimTerrainTamriel_Mars.esm), then coc SKY_TamrielRiverwoodSpawn." -ForegroundColor Green
Write-Host "Look around Riverwood and beyond: forest floor (pine forest grass), fields, rocky ground, snow and tundra." -ForegroundColor Green
