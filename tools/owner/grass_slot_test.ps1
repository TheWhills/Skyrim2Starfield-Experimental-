# Grass test (2026-11-24, docs/re/ground-cover-density.md route A): Skyrim's field grass through ONE LDefault slot.
# 1. terrain: in 20 x 20 quadrants (1 km) around Riverwood's forest flat (quadrant 58, 76), every layer that paints
#    LFieldGrass02 paints the placeholder LDefault006Base instead (same alphas), byte 6 cleared there;
# 2. reinstall the exterior;
# 3. grass mod: Nirn's ocean biome gets ONE entry {mask 0 (Base), our LFieldGrass02 slot, its Skyrim grass cover},
#    threshold 0.1, the working route's model options.
# Expected in game: the field looks as before (the biome draws our LFieldGrass02 for the placeholder) and grass grows
# ACROSS it at the texture's own strength, not only at its edges. Outside the square nothing changes on the ground.
# Starfield must be closed. -Restore puts the terrain back and reinstalls (rebuild the grass mod as usual afterwards).
#   powershell -ExecutionPolicy Bypass -File tools\owner\grass_slot_test.ps1
#   powershell -ExecutionPolicy Bypass -File tools\owner\grass_slot_test.ps1 -Restore
param(
    [string]$Staging = "C:\Modding\staging\skyrim_all",
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$Grass = "$env:LOCALAPPDATA\ModOrganizer\Starfield\mods\S2S Grass Native",
    [string]$Texconv = "C:\Modding\tools\texconv.exe",
    [int]$Row = 58,
    [int]$Col = 76,
    [int]$Size = 20,
    [double]$Threshold = 0.1,
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
if ($Restore) {
    Step "1. the terrain files from before the slot test"
    python -I scripts\terrain\btd_cover.py slot-restore --staging $Staging
} else {
    Step "1. terrain: LFieldGrass02 -> LDefault006Base in $Size x $Size quadrants around ($Row, $Col)"
    python -I scripts\terrain\btd_cover.py slot --staging $Staging --quad $Row $Col --size $Size --mask Base `
        --sf-esm "$SF\Data\Starfield.esm"
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
    Write-Host "`ndone: terrain as before the slot test. Rebuild S2S Grass Native with your usual command." -ForegroundColor Green
    exit 0
}
Step "3. grass mod: one Base slot = LFieldGrass02 + its cover"
python -I scripts\terrain\skyrim_grass_native.py --skyrim "$SKY\Skyrim.esm" --skyrim-data $SKY --starfield $SF `
    --terrain $Staging --texconv $Texconv --out $Grass `
    --only-ltex LFieldGrass02 --biome-masks 0 --threshold $Threshold `
    --vanilla-paths --coverage 100 --vanilla-material auto
if ($LASTEXITCODE -ne 0) { Fail "skyrim_grass_native" }
Write-Host "`ndone. S2S Grass Native on in MO2 (after SkyrimTerrainTamriel_Mars.esm), then coc SKY_TamrielRiverwoodSpawn." -ForegroundColor Green
Write-Host "Look at the flat forest floor that stayed bare (Skyrim 17448, -48815; quadrant 58, 76): grass across the field = route works;" -ForegroundColor Green
Write-Host "grass only at its edges again = the placeholder did not take; the ground looking different = slot texture." -ForegroundColor Green
