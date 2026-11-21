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
    [int]$NavRadius = 2,
    [switch]$Resurvey,         # redo the vanilla navmesh survey (it is kept between runs)
    # Skyrim NPCs to place with their AI packages. Default (2026-11-15, owner: "why you keep losing progress"): every
    # Riverwood adult face_fit fits, so a command without -Actors no longer drops them; -NoActors for none.
    # 2026-11-20 (owner: children placed with their schedules): Dorthe and Frodnar, face_fit's child test NPCs.
    [string[]]$Actors = @("Orgnar", "Delphine", "Embry", "Faendal", "Alvor", "Sigrid", "Hod", "Gerdur", "Sven", "Hilde",
                          "CamillaValerius", "LucanValerius", "Dorthe", "Frodnar"),
    [switch]$NoActors,
    [switch]$Furniture,        # chairs / benches / beds / lean counters / idle markers as Starfield furniture NPCs use
    [ValidateSet("floor", "skyrim")][string]$MarkerZ = "floor",   # furniture marker height (docs/npc/furniture.md)
    [string[]]$FurnShift = @(),   # move a furniture kind's markers, e.g. -FurnShift "bartender=0,0.2,0"
    [string[]]$FurnTurn = @(),    # turn a furniture kind's markers (degrees), e.g. -FurnTurn "bed=90" (default bed -90)
    [switch]$NoCrafting,       # with -Furniture: leave crafting stations (cooking pots, alchemy, smithing) as statics
    [string[]]$SkipKind = @(), # with -Furniture: leave these furniture kinds as statics, e.g. -SkipKind forge (A/B)
    # a Starfield Sit package into one Skyrim furniture reference, ahead of the NPC's own (make_schedule --sit-at), e.g.
    # -SitAt "Alvor=0D6987:8:720" (his forge, 8:00 for 12 h)
    [string[]]$SitAt = @(),
    [switch]$PlainStations,
    [string[]]$StationKeyword = @(),  # with -PlainStations: keywords the stations still get, e.g. FurnitureSpecial    # with -Furniture (A/B): work stations without FurnitureSpecial / IgnoreCollision, template's entry sides
    # 2026-11-21 (owner: wine, bread, cabbages, potions pickable): Skyrim's placed food / drink / potions / ingredients
    # and clutter (MiscItem: plates, tankards, baskets; 2026-11-21) as Starfield items with a vanilla item's physics body (make_items.py; docs/interior/items.md "Placed items")
    [switch]$Items,
    [switch]$NoOutdoorFurniture,  # with -Furniture: leave the outdoor benches / chairs / forge around -NavAround as they are
    [string]$Faces = "$env:LOCALAPPDATA\ModOrganizer\Starfield\mods\S2S Face Test\faces.json",
    # with -Furniture: chairs / benches carry this plugin's Skyrim-animation keyword (stance_plugin.py; the clips:
    # furniture_anim_pack.py); "" or a missing file = Starfield's animations
    [string]$AnimPlugin = "$env:LOCALAPPDATA\ModOrganizer\Starfield\mods\S2S Stances\S2SStances.esm",
    # candle / hearth flames: cards with Skyrim's textures or Starfield's fire flipbooks; "particles": hearths as
    # Starfield's own particle fire (a plugin change: a full build, not -AssetsOnly)
    # default since 2026-11-16 (owner's comparisons): hearths burn Starfield's FireMed02, candles keep Skyrim's cards;
    # "layered": Skyrim's hearth flame meshes and cards burning with Starfield's LayeredFireV2 material, no particle fire
    # default "layered" since 2026-11-16 11:06 (owner accepted the orange LayeredFireV2 hearth and Skyrim's candles)
    [ValidateSet("skyrim", "starfield", "particles", "layered")][string]$FlameStyle = "layered",
    # with -FlameStyle particles: the Starfield fire placed in hearths, "BASE[:SCALE]" (default FireMed02 1CEDAB, 0.8)
    [string]$ParticleFire = "",
    # candle flames: Skyrim's textures, or Starfield's own candle flame (its mesh + material) fitted to Skyrim's teardrop (models only:
    # -AssetsOnly is enough to switch)
    # 2026-11-21 (owner: "the candles just look very low quality"): "soft" = our own smooth flame flipbook with a halo
    [ValidateSet("skyrim", "starfield", "soft")][string]$CandleStyle = "soft",
    # soft candles' brightness, stops over the scene's exposure (2026-11-21: 5 "awfully white", now 3; lower = dimmer).
    # Flame-only: -AssetsOnly
    [double]$CandleExposure = 3,
    # Skyrim's ambient as each room's environment light: radiance per linear unit (2026-11-21: 38, a first guess;
    # higher = brighter shadows / corners). Written by step 1: a full build
    [double]$AmbientScale = 38,
    # 2026-11-21: exposure like Skyrim's, adapting to what you look at (auto, a copy of LGT_NoLut with Starfield's auto
    # exposure between EV100 ExposureMin and ExposureMax), or fixed (EV 5, each room's lights scaled instead). Step 1
    [ValidateSet("auto", "fixed")][string]$Exposure = "auto",
    # dark views sit at ExposureMin (2026-11-21: at 1 every inn view 2 - 3.7 stops over Skyrim; higher = darker)
    [double]$ExposureMin = 4,
    [double]$ExposureMax = 8,
    # the compensation curve's default (2026-11-21: -3 and 0 looked the same; ExposureMin is the knob)
    [double]$ExposureCompensation = 0,
    # 2026-11-15 (owner: "are we running more steps than needed for the test again"): models / materials / textures
    # only. Re-converts what changed (flame changes: the candles and hearths) and repacks the archives; skips the
    # interior export, navmesh, NPCs, furniture and the plugin build. Needs one full build before it (the plugin is
    # reused). Not for changes to records (doors, NPCs, furniture, lights).
    [switch]$AssetsOnly,
    # turning parts (2026-11-18, the mill water wheel): copies of a vanilla turning static at the exterior's wheels, from
    # the exterior's own converted models (scripts\terrain\spin_parts.py; reconvert first: exterior_collision.ps1)
    [string]$ExteriorWork = "C:\Modding\work\sky_all",
    [switch]$NoSpin,
    # 2026-11-21 (owner: "does it need to do all of this every time we test"): the window shows each step's summary; the
    # full output always goes to <Work>\logs\riverwood_doors_last.log (send that file when asked). -FullLog prints it all
    [switch]$FullLog
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
# output: every line into the log file; the window gets the lines tools\owner\log_noise.txt does not match (per-NPC
# package lines, per-item / per-furniture records, notes ...), long lines cut; each step's time, and a table at the end
$env:PYTHONUNBUFFERED = "1"          # lines as they come, not in chunks at the end (stdout is a pipe now)
$env:PYTHONIOENCODING = "utf-8"
$LogDir = Join-Path $Work "logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Log = Join-Path $LogDir "riverwood_doors_last.log"
Set-Content -LiteralPath $Log -Encoding UTF8 -Value ("riverwood_doors " + (Get-Date -Format s) + ": " + $MyInvocation.Line)
$Noise = @(Get-Content (Join-Path $PSScriptRoot "log_noise.txt") | Where-Object { $_ -and -not $_.StartsWith("#") })
$script:StepName = $null
$script:StepClock = $null
$script:StepTimes = @()
function Log($line) { Add-Content -LiteralPath $Log -Encoding UTF8 -Value $line }
function Quiet($line) { foreach ($rx in $Noise) { if ($line -match $rx) { return $true } }; return $false }
function Run {
    # a native command (python / dotnet), its output (stderr too) logged and filtered; $LASTEXITCODE as it left it
    $exe, $rest = $args
    $ErrorActionPreference = "Continue"           # stderr lines are not errors here (PowerShell 5 would stop on them)
    & $exe @rest 2>&1 | ForEach-Object {
        $line = "$_"
        Log $line
        if ($FullLog -or -not (Quiet $line)) {
            if ($line.Length -gt 240) { $line = $line.Substring(0, 240) + " ... (whole line in the log)" }
            Write-Host $line
        }
    }
}
function EndStep {
    if ($script:StepName) {
        $sec = $script:StepClock.Elapsed.TotalSeconds
        $script:StepTimes += , @($script:StepName, $sec)
        Write-Host ("   ({0:N0} s)" -f $sec) -ForegroundColor DarkGray
        Log ("   ({0:N0} s)" -f $sec)
    }
    $script:StepName = $null
}
function Step($t) {
    EndStep
    $script:StepName = $t
    $script:StepClock = [Diagnostics.Stopwatch]::StartNew()
    Write-Host "`n== $t" -ForegroundColor Cyan
    Log "`n== $t"
}
function Timings {
    EndStep
    Write-Host "`nstep times:" -ForegroundColor DarkGray
    foreach ($st in $script:StepTimes) {
        $row = "  {0,6:N0} s  {1}" -f $st[1], $st[0]
        Write-Host $row -ForegroundColor DarkGray
        Log $row
    }
    Write-Host "full output: $Log" -ForegroundColor DarkGray
}
function Fail($t) {
    Write-Host "FAILED: $t" -ForegroundColor Red
    Log "FAILED: $t"
    Timings
    try { notify "riverwood_doors: FAILED - $t" } catch {}
    exit 1
}
foreach ($p in @("$Exterior\formids.json", "$Exterior\overlays_params.json", "$SKY\Skyrim.esm", "$SF\Data\Starfield.esm", "$SF\Tools\ContentResources.zip")) {
    if (-not (Test-Path $p)) { Fail "missing $p" }
}
if (-not (Test-Path $Texconv)) {
    $t = Get-ChildItem C:\Modding\tools -Recurse -Filter texconv*.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($t) { $Texconv = $t.FullName } else { Fail "texconv.exe not found (give -Texconv <path>)" }
}
$clock = [Diagnostics.Stopwatch]::StartNew()

if ($AssetsOnly -and ($ParticleFire -or $FlameStyle -eq "particles")) {
    Write-Host "note: the hearth fires are plugin records; a different -FlameStyle / -ParticleFire takes a full build" -ForegroundColor Yellow
}
if ($AssetsOnly) {
    $staging = Join-Path $Work "convert"
    if (-not (Test-Path (Join-Path $staging "FO4Port.esm")) -or -not (Test-Path (Join-Path $Work "convert_input.json"))) {
        Fail "-AssetsOnly needs one full build first (no FO4Port.esm / convert_input.json in $Work)"
    }
    Step "2. convert the models (resumable; only changed ones are redone)"
    Run python -I scripts\terrain\make_skyrim_objects.py convert --work $Work --skyrim-data $SKY --content-resources "$SF\Tools\ContentResources.zip" --texconv $Texconv --starfield-data "$SF\Data" --resume --flame-style $FlameStyle --candle-style $CandleStyle --candle-exposure $CandleExposure.ToString([cultureinfo]::InvariantCulture)
    if ($LASTEXITCODE -ne 0) { Fail "convert" }
    if ($NoInstall) { Timings; Write-Host "converted in $staging (not installed: -NoInstall)"; exit 0 }
    Step "4. install (archives repacked, plugin unchanged)"
    if (Test-Path "$SF\Data\FO4Port.deploy.json") { Run python -I scripts\deploy_starfield.py uninstall --starfield $SF }
    Run python -I scripts\deploy_starfield.py install --staging $staging --starfield $SF
    if ($LASTEXITCODE -ne 0) { Fail "install" }
    Timings
    Write-Host ("`nassets-only build: {0:N0} s" -f $clock.Elapsed.TotalSeconds) -ForegroundColor Green
    try { notify "riverwood_doors: assets rebuilt and installed" } catch {}
    exit 0
}

Step "1. interior batch with doors to the exterior"
# a search of all of C:\Modding (about 12 s, owner 2026-11-21): here, so -AssetsOnly does not pay for it
$nav = Get-ChildItem C:\Modding -Recurse -Filter navmesh_defaults.json -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$args1 = @("batch", "--skyrim", "$SKY\Skyrim.esm", "--work", $Work, "--exterior")
if ($Find) { $args1 += @("--find", $Find) } else { $args1 += @("--cells", $Cells) }
if ($nav) { $args1 += @("--navmesh-defaults", $nav.FullName) }
$args1 += @("--ambient-scale", $AmbientScale.ToString([cultureinfo]::InvariantCulture))
$args1 += @("--exposure", $Exposure, "--starfield-esm", "$SF\Data\Starfield.esm",
            "--exposure-min", $ExposureMin.ToString([cultureinfo]::InvariantCulture),
            "--exposure-max", $ExposureMax.ToString([cultureinfo]::InvariantCulture),
            "--exposure-compensation", $ExposureCompensation.ToString([cultureinfo]::InvariantCulture))
# outdoor furniture (2026-11-13): benches, chairs, the forge, smelter, tanning rack around -NavAround become usable
# furniture in the exterior (their models converted with the interiors)
if ($Furniture -and -not $NoOutdoorFurniture) { $args1 += @("--exterior-furniture", $NavAround, "--exterior-radius", $NavRadius) }
Run python -I scripts\interior\make_skyrim_interior.py @args1
if ($LASTEXITCODE -ne 0) { Fail "batch" }

Step "2. convert the inn's models (resumable)"
$conv = @("convert", "--work", $Work, "--skyrim-data", $SKY, "--content-resources", "$SF\Tools\ContentResources.zip", "--texconv", $Texconv, "--starfield-data", "$SF\Data", "--resume", "--flame-style", $FlameStyle, "--candle-style", $CandleStyle, "--candle-exposure", $CandleExposure.ToString([cultureinfo]::InvariantCulture))
if ($ParticleFire) { $conv += @("--particle-fire", $ParticleFire) }   # an empty argument would be dropped by PowerShell 5
Run python -I scripts\terrain\make_skyrim_objects.py @conv
if ($LASTEXITCODE -ne 0) { Fail "convert" }
Run python -I scripts\interior\make_skyrim_interior.py check --work $Work

$navWork = Join-Path $Work "navmesh"
if ($Navmesh) {
    Step "2b. exterior navmesh around $NavAround"
    $navDef = Join-Path $navWork "survey\navmesh_defaults_exterior.json"
    if ($Resurvey -or -not (Test-Path $navDef)) {
        $sv = @("--esm", "$SF\Data\Starfield.esm", "--out", (Join-Path $navWork "survey"), "--exterior", "--max", "400")
        if (Test-Path "$SF\Data\ShatteredSpace.esm") { $sv += @("--navi-esm", "$SF\Data\ShatteredSpace.esm") }
        Run python -I scripts\interior\navmesh_survey.py @sv
        if ($LASTEXITCODE -ne 0) { Fail "navmesh survey" }
    }
    Run python -I scripts\terrain\make_skyrim_navmesh.py export --skyrim "$SKY\Skyrim.esm" --exterior $Exterior --out $navWork --around $NavAround --radius $NavRadius --navmesh-defaults $navDef
    if ($LASTEXITCODE -ne 0) { Fail "navmesh export" }
}

if ($NoActors) { $Actors = @() }
if ($Actors.Count -gt 0) {
    Step "2c. NPCs with their schedules: $($Actors -join ', ')"
    $sa = @("--skyrim", "$SKY\Skyrim.esm", "--starfield", "$SF\Data\Starfield.esm", "--work", $Work)
    # with -File, "-Actors A,B,C" arrives as one string: split it
    foreach ($n in ($Actors -join ",").Split(",")) { if ($n.Trim()) { $sa += @("--npc", $n.Trim()) } }
    # with -Furniture the sandboxes have chairs / the bar / beds to use: keep Skyrim's own Allow Wandering (Orgnar: off,
    # so he stays at the bar) instead of forcing it on
    if ($Furniture) { $sa += @("--keep-furniture-only") }
    # outdoor package spots (2026-11-12): packages near a reference in the converted exterior are kept (FO4Port.esm
    # puts a marker there in the exterior's persistent cell), so the NPCs walk out of their houses and around town
    $sa += @("--exterior", $Exterior)
    if (Test-Path $Faces) { $sa += @("--faces", $Faces) } else { Write-Host "no faces.json at $Faces" -ForegroundColor Yellow }
    foreach ($st in $SitAt) { if ($st.Trim()) { $sa += @("--sit-at", $st.Trim()) } }
    Run python -I scripts\npc\make_schedule.py @sa
    if ($LASTEXITCODE -ne 0) { Fail "make_schedule" }
}

if ($Furniture) {
    Step "2d. furniture NPCs can use"
    $fa = @("--skyrim", "$SKY\Skyrim.esm", "--skyrim-data", $SKY, "--work", $Work, "--marker-z", $MarkerZ)
    # several kinds: separate with ";" ("bartender=0,0.2,0;lean_counter=0,0.1,0")
    foreach ($sh in ($FurnShift -join ";").Split(";")) { if ($sh.Trim()) { $fa += @("--shift", $sh.Trim()) } }
    foreach ($tu in ($FurnTurn -join ";").Split(";")) { if ($tu.Trim()) { $fa += @("--turn", $tu.Trim()) } }
    if ($NoCrafting) { $fa += @("--no-crafting") }
    foreach ($sk in $SkipKind) { if ($sk.Trim()) { $fa += @("--skip-kind", $sk.Trim()) } }
    if ($PlainStations) { $fa += @("--plain-stations") }
    foreach ($kw in $StationKeyword) { if ($kw.Trim()) { $fa += @("--station-keyword", $kw.Trim()) } }
    if ($AnimPlugin -and (Test-Path $AnimPlugin)) { $fa += @("--anim-plugin", $AnimPlugin) }
    Run python -I scripts\interior\make_furniture.py @fa
    if ($LASTEXITCODE -ne 0) { Fail "make_furniture" }
}

if ($Items) {
    Step "2e. food, drink, potions and clutter as items"
    Run python -I scripts\interior\make_items.py --skyrim "$SKY\Skyrim.esm" --skyrim-data $SKY --starfield $SF --work $Work
    if ($LASTEXITCODE -ne 0) { Fail "make_items" }
}

Step "3. FO4Port.esm with the doors linked both ways"
$staging = Join-Path $Work "convert"
Remove-Item Env:SPIN_PARTS -ErrorAction SilentlyContinue
if (-not $NoSpin -and (Test-Path "$ExteriorWork\convert\manifest.json") -and (Test-Path "$Exterior\objects.json")) {
    Run python -I scripts\terrain\spin_parts.py --exterior $Exterior --work $ExteriorWork --out $staging
    if ($LASTEXITCODE -ne 0) { Fail "spin_parts" }
    $env:SPIN_PARTS = Join-Path $staging "spin_parts.json"
}
$env:STARFIELD_DATA = "$SF\Data"
$env:EXTERIOR_DIR = $Exterior
$env:EXTERIOR_DOORS = Join-Path $Work "exterior_doors.json"
if ($Navmesh) { $env:EXTERIOR_NAVMESH = Join-Path $navWork "exterior_navmesh.json" }
if ($Actors.Count -gt 0) { $env:ACTORS = Join-Path $Work "actors.json" }
if ($Furniture) { $env:FURNITURE = Join-Path $Work "furniture.json" }
if ($Items) { $env:ITEMS = Join-Path $Work "items.json" }
Run dotnet run --project dotnet\PluginSpike -- $staging (Join-Path $staging "manifest.json") ("@" + (Join-Path $Work "cells.txt"))
$rc = $LASTEXITCODE
Remove-Item Env:EXTERIOR_DIR, Env:EXTERIOR_DOORS, Env:EXTERIOR_NAVMESH, Env:ACTORS, Env:FURNITURE, Env:ITEMS, Env:SPIN_PARTS -ErrorAction SilentlyContinue
if ($rc -ne 0) { Fail "PluginSpike (paste its output: compile errors name the Mutagen property)" }

if ($Navmesh) {
    Step "3b. compare the navmesh in FO4Port.esm with Skyrim's"
    Run python -I scripts\terrain\make_skyrim_navmesh.py compare --skyrim "$SKY\Skyrim.esm" --work $navWork --plugin (Join-Path $staging "FO4Port.esm")
    if ($LASTEXITCODE -ne 0) { Fail "navmesh compare" }
    Write-Host "open $navWork\compare.html in a browser" -ForegroundColor Green
}
if ($NoInstall) { Timings; Write-Host "built in $staging (not installed: -NoInstall)"; exit 0 }
Step "4. install (replaces the Oct 23 FO4Port test)"
if (Test-Path "$SF\Data\FO4Port.deploy.json") { Run python -I scripts\deploy_starfield.py uninstall --starfield $SF }
Run python -I scripts\deploy_starfield.py install --staging $staging --starfield $SF
if ($LASTEXITCODE -ne 0) { Fail "install" }
# 2026-11-14: the game ignores FO4Port.esm's overrides of the exterior's statics (in game, fresh coc: still there), so
# the hidden ones are written into the exterior plugin itself, in place (docs/npc/furniture.md)
Step "5. hide the replaced exterior statics in the exterior plugin"
$extPlugin = (Get-Content "$Exterior\formids.json" -Raw | ConvertFrom-Json).plugin
# only the installed copy: the build reads the staged one for the statics' places (load doors go where the static stood)
Run python -I scripts\terrain\apply_ref_overrides.py --from "$SF\Data\FO4Port.esm" --into "$SF\Data\$extPlugin"
if ($LASTEXITCODE -ne 0) { Fail "apply_ref_overrides" }
Timings
Write-Host ("`nfull build: {0:N0} s" -f $clock.Elapsed.TotalSeconds) -ForegroundColor Green
Write-Host "`nIn game: coc SKY_TamrielRiverwoodSpawn, walk to the Sleeping Giant Inn's door and use it; inside, use the front door back out." -ForegroundColor Green
try { notify "riverwood_doors: built and installed" } catch {}
