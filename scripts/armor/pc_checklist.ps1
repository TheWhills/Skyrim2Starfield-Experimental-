# One-shot PC checklist for the Skyrim -> Starfield combat port (docs/armor/animation-port.md, lock-on-design.md).
# Read-only on both games. Writes two zips to the Desktop:
#   s2s_checklist_report.zip  - text reports (send this)
#   s2s_skyrim_anims.zip      - vanilla Skyrim animation files the port needs (send privately; game files)
#
#   cd <your clone of the repo>
#   git pull
#   powershell -ExecutionPolicy Bypass -File scripts\armor\pc_checklist.ps1
#
# Override any path: -Repo, -SF (Starfield install folder), -SKY (Skyrim SE Data folder), -Out, -Texconv.
# Also builds the iron weapon test mod (step 6) into the Desktop folder "S2S Iron Weapons" when texconv is found, and
# the combat plugin (step 7) into the Desktop folder "S2S Combat Plugin" when xmake and Visual Studio's tools are found.
param(
    [string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$Out = (Join-Path (Join-Path $env:USERPROFILE "Desktop") "s2s_checklist"),
    [string]$Texconv = "C:\Modding\tools\xedit\Edit Scripts\texconv.exe"
)
$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$log = Join-Path $Out "checklist.log"
function Say($t) { Write-Host $t; Add-Content -Path $log -Value $t }
"" | Set-Content $log
Set-Location $Repo

Say "== 0. environment"
Say ("python: " + (python --version 2>&1))
Say ("repo commit: " + (git log -1 --format="%h %s" 2>&1))
foreach ($f in @("Starfield.exe", "sfse_loader.exe", "CreationKit.exe")) {
    $p = Join-Path $SF $f
    if (Test-Path $p) { Say ("{0}: {1}" -f $f, (Get-Item $p).VersionInfo.FileVersion) } else { Say "${f}: not found" }
}
$al = Get-ChildItem -Path (Join-Path $SF "Data\SFSE\Plugins") -Filter "versionlib*" -ErrorAction SilentlyContinue
Say ("Address Library files: " + (($al | ForEach-Object Name) -join ", "))

Say "== 1. Creation Kit command-line switches (looking for GenerateAnimInfo)"
$ck = Join-Path $SF "CreationKit.exe"
if (Test-Path $ck) {
    $b = [IO.File]::ReadAllBytes($ck)
    $found = foreach ($enc in [Text.Encoding]::ASCII, [Text.Encoding]::Unicode) {
        [regex]::Matches($enc.GetString($b), '-?Generate[A-Za-z]+') | ForEach-Object Value
    }
    $found = $found | Sort-Object -Unique
    Say ("switches: " + ($found -join ", "))
    $ctx = foreach ($enc in [Text.Encoding]::ASCII, [Text.Encoding]::Unicode) {
        [regex]::Matches($enc.GetString($b), '[ -~]{0,80}GenerateAnim[ -~]{0,120}') | ForEach-Object Value
    }
    $ctx | Sort-Object -Unique | Set-Content (Join-Path $Out "ck_generateanim_context.txt")
} else {
    Say "CreationKit.exe not found (free Steam tool: 'Starfield: Creation Kit')"
}

Say "== 1b. Starfield.exe: Papyrus functions the combat plugin calls (native/combat/sfse/README.md)"
$exe = Join-Path $SF "Starfield.exe"
if (Test-Path $exe) {
    $text = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($exe))
    foreach ($fn in @("SetAnimationVariableBool", "SetAnimationVariableInt", "SetAnimationVariableFloat",
                      "GetAnimationVariableFloat", "SendAnimationEvent", "AddKeyword", "RemoveKeyword", "SetGhost")) {
        Say ("{0}: {1}" -f $fn, $(if ($text.Contains($fn)) { "present" } else { "NOT FOUND" }))
    }
    $text = $null
} else {
    Say "Starfield.exe not found"
}

Say "== 2. Starfield.esm: weapon animation keywords, HumanRace animation sets, melee aim assist"
python -I (Join-Path $Repo "scripts/armor/weapon_anim_survey.py") --esm (Join-Path $SF "Data\Starfield.esm") --out (Join-Path $Out "weapon_anims") 2>&1 | ForEach-Object { Say $_ }

Say "== 3. Starfield animation caches (animtextdata) for the melee sets"
python -I (Join-Path $Repo "scripts/armor/sf_animcache_survey.py") --starfield-data (Join-Path $SF "Data") --out (Join-Path $Out "animcache") 2>&1 | ForEach-Object { Say $_ }

Say "== 4. vanilla Skyrim: motion data, behaviours, two-handed / dual / shield clips"
$skyOut = Join-Path $Out "skyrim_anims"
python -I (Join-Path $Repo "scripts/armor/skyrim_anim_extract.py") --skyrim-data $SKY --out $skyOut 2>&1 | ForEach-Object { Say $_ }

Say "== 6. iron weapon test mod (one Skyrim weapon of each type)"
if (-not (Test-Path $Texconv)) {
    $found = Get-ChildItem -Path "C:\Modding" -Filter "texconv*.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $Texconv = $found.FullName }
}
if (Test-Path $Texconv) {
    $wpn = Join-Path (Join-Path $env:USERPROFILE "Desktop") "S2S Iron Weapons"
    python -I (Join-Path $Repo "scripts/armor/weapon_test_pack.py") --skyrim-data $SKY --starfield $SF --texconv $Texconv --out $wpn 2>&1 | ForEach-Object { Say $_ }
    Copy-Item (Join-Path $wpn "weapon_test_pack.json") $Out -ErrorAction SilentlyContinue
} else {
    Say "texconv.exe not found (give -Texconv <path>): weapon test mod skipped"
}

Say "== 7. combat plugin (SFSE) build"
$xmake = Get-Command xmake -ErrorAction SilentlyContinue
$plug = Join-Path $Repo "native\combat\sfse"
if ($xmake -and (Test-Path (Join-Path $plug "xmake.lua"))) {
    git -C $Repo submodule update --init --recursive 2>&1 | ForEach-Object { Say $_ }
    Push-Location $plug
    $blog = Join-Path $Out "plugin_build.log"
    & xmake f -m releasedbg -y *> $blog
    & xmake -y *>> $blog
    $ok = $LASTEXITCODE -eq 0
    Pop-Location
    Say ("plugin build: " + $(if ($ok) { "ok" } else { "FAILED (plugin_build.log is in the report)" }))
    $dll = Get-ChildItem -Path (Join-Path $plug "build") -Filter "S2SCombat.dll" -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($dll) {
        $mod = Join-Path (Join-Path (Join-Path (Join-Path $env:USERPROFILE "Desktop") "S2S Combat Plugin") "SFSE") "Plugins"
        New-Item -ItemType Directory -Force -Path $mod | Out-Null
        Copy-Item $dll.FullName $mod
        Copy-Item (Join-Path $plug "S2SCombat.ini") $mod
        Say "plugin mod folder: $mod (add to MO2 as a mod; first-run notes in native\combat\sfse\README.md)"
    }
} else {
    Say "xmake not found (winget install xmake; needs Visual Studio 2022 Build Tools): plugin build skipped"
}

Say "== 5. zips"
$desk = Join-Path $env:USERPROFILE "Desktop"
$rep = Join-Path $desk "s2s_checklist_report.zip"
$sky = Join-Path $desk "s2s_skyrim_anims.zip"
Remove-Item $rep, $sky -ErrorAction SilentlyContinue
$items = Get-ChildItem $Out | Where-Object { $_.Name -ne "skyrim_anims" } | ForEach-Object FullName
Compress-Archive -Path $items -DestinationPath $rep
if (Test-Path $skyOut) { Compress-Archive -Path (Join-Path $skyOut "*") -DestinationPath $sky }
Say ("report: $rep (" + [math]::Round((Get-Item $rep).Length / 1MB, 1) + " MB)")
if (Test-Path $sky) { Say ("skyrim anims: $sky (" + [math]::Round((Get-Item $sky).Length / 1MB, 1) + " MB)") }
Say "done"
