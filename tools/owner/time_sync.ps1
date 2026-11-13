# Keeps Nirn's sun on the NPC schedules' clock (2026-11-13): compiles scripts\terrain\papyrus\S2S_LocalTimeSync.psc
# with the Creation Kit's Papyrus compiler and writes S2STimeSync.esm (scripts\terrain\time_sync.py) into an MO2 mod
# folder. Then enable "S2S Time Sync" and S2STimeSync.esm in MO2. Starfield must be closed.
#   powershell -ExecutionPolicy Bypass -File tools\owner\time_sync.ps1
param(
    [string]$SF = "D:\SteamLibrary\steamapps\common\Starfield",
    [string]$Mod = "$env:LOCALAPPDATA\ModOrganizer\Starfield\mods\S2S Time Sync",
    [string]$Work = "C:\Modding\work\s2s\time_sync",
    [string]$Compiler = ""          # PapyrusCompiler.exe, when it is not under <Starfield>\Tools
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Repo
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "FAILED: $t" -ForegroundColor Red; exit 1 }
if (-not (Test-Path "$SF\Data\Starfield.esm")) { Fail "missing $SF\Data\Starfield.esm" }
New-Item -ItemType Directory -Force -Path $Work, "$Mod\Scripts" | Out-Null

Step "Papyrus compiler"
if (-not $Compiler) {
    $c = Get-ChildItem "$SF\Tools" -Recurse -Filter PapyrusCompiler.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $c) { Fail "PapyrusCompiler.exe not under $SF\Tools (install the Starfield Creation Kit from Steam, or give -Compiler <path>)" }
    $Compiler = $c.FullName
}
Write-Host $Compiler
$flags = Get-ChildItem (Split-Path $Compiler), "$SF\Data\Scripts\Source" -Recurse -Filter *.flg -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $flags) { Fail "no Papyrus flags file (*.flg) next to the compiler or in $SF\Data\Scripts\Source" }
Write-Host "flags: $($flags.FullName)"

Step "Base script sources (ScriptObject.psc, Game.psc ...)"
$base = Get-ChildItem "$SF\Data\Scripts\Source", "$SF\Tools" -Recurse -Filter ScriptObject.psc -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $base) {
    # the Creation Kit ships them zipped: find the zip holding ScriptObject.psc and unpack it once into $Work\base
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zips = Get-ChildItem "$SF\Data\Scripts", "$SF\Tools", "$SF\Data" -Filter *.zip -ErrorAction SilentlyContinue
    foreach ($z in $zips) {
        $zf = [System.IO.Compression.ZipFile]::OpenRead($z.FullName)
        $hit = $zf.Entries | Where-Object { $_.Name -ieq "ScriptObject.psc" } | Select-Object -First 1
        $zf.Dispose()
        if ($hit) {
            Write-Host "unpacking $($z.FullName)"
            Expand-Archive -Path $z.FullName -DestinationPath "$Work\base" -Force
            $base = Get-ChildItem "$Work\base" -Recurse -Filter ScriptObject.psc | Select-Object -First 1
            break
        }
    }
}
if (-not $base) { Fail "ScriptObject.psc not found (Creation Kit script sources); tell Claude where the CK put its scripts" }
$imports = Split-Path $base.FullName
Write-Host "imports: $imports"

Step "Compile S2S_LocalTimeSync"
# the compiler takes the script by NAME, found through -i (a full path gave "filename does not match script name")
$src = "$Repo\scripts\terrain\papyrus"
Push-Location $src
& $Compiler "S2S_LocalTimeSync" "-f=$($flags.FullName)" "-i=$src;$imports" "-o=$Mod\Scripts" -optimize -release -final
Pop-Location
if ($LASTEXITCODE -ne 0 -or -not (Test-Path "$Mod\Scripts\S2S_LocalTimeSync.pex")) { Fail "Papyrus compile (paste its output)" }

Step "S2STimeSync.esm"
python -I scripts\terrain\time_sync.py --starfield $SF --out $Mod
if ($LASTEXITCODE -ne 0) { Fail "time_sync.py" }

Write-Host "`nDone: $Mod (S2STimeSync.esm + Scripts\S2S_LocalTimeSync.pex). Enable the mod and the plugin in MO2." -ForegroundColor Green
Write-Host "In game on Nirn: the status screen's LOCAL TIME should match UT within a minute or two after loading." -ForegroundColor Green
