# One-shot PC checklist for the Skyrim -> Starfield combat port (docs/armor/animation-port.md, lock-on-design.md).
# Read-only on both games. Writes two zips to the Desktop:
#   s2s_checklist_report.zip  - text reports (send this)
#   s2s_skyrim_anims.zip      - vanilla Skyrim animation files the port needs (send privately; game files)
#
#   cd <your clone of the repo>
#   git pull
#   powershell -ExecutionPolicy Bypass -File scripts\armor\pc_checklist.ps1
#
# Override any path: -Repo, -SF (Starfield install folder), -SKY (Skyrim SE Data folder), -Out.
param(
    [string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$SKY = "C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data",
    [string]$Out = (Join-Path (Join-Path $env:USERPROFILE "Desktop") "s2s_checklist")
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

Say "== 2. Starfield.esm: weapon animation keywords, HumanRace animation sets, melee aim assist"
python -I (Join-Path $Repo "scripts/armor/weapon_anim_survey.py") --esm (Join-Path $SF "Data\Starfield.esm") --out (Join-Path $Out "weapon_anims") 2>&1 | ForEach-Object { Say $_ }

Say "== 3. Starfield animation caches (animtextdata) for the melee sets"
python -I (Join-Path $Repo "scripts/armor/sf_animcache_survey.py") --starfield-data (Join-Path $SF "Data") --out (Join-Path $Out "animcache") 2>&1 | ForEach-Object { Say $_ }

Say "== 4. vanilla Skyrim: motion data, behaviours, two-handed / dual / shield clips"
$skyOut = Join-Path $Out "skyrim_anims"
python -I (Join-Path $Repo "scripts/armor/skyrim_anim_extract.py") --skyrim-data $SKY --out $skyOut 2>&1 | ForEach-Object { Say $_ }

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
