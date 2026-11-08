# Owner's setup: folders, mod folders, working commands

The owner's own machine (Windows, PowerShell, Mod Organizer 2). Agents: read this before giving the owner a command,
and update it in the same commit whenever a folder or a working command changes. Paths use `$HOME` and
`$env:LOCALAPPDATA` so no user name is stored (scripts/guard.py rejects them).

## Paste first in every new PowerShell window

```powershell
cd "$HOME\Skyrim2Starfield-Experimental-"
git pull
$sky="C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data"
$sf="D:\SteamLibrary\steamapps\common\Starfield"
$mods="$env:LOCALAPPDATA\ModOrganizer\Starfield\mods"
$armor="$mods\S2S Armor Test"
$face="$mods\S2S Face Test"
$hairs="$mods\S2S Skyrim Hairs\S2SSkyrimHairs.esm"
$ms="$mods\More-Sliders Complete"
$cs="$ms\meshes\actors\human\characterassets"
```

Starfield must be closed while a script writes into the mods folders.

## What is where

| What | Where |
| --- | --- |
| Repository (branch `skyrim/armor`) | `$HOME\Skyrim2Starfield-Experimental-` |
| Skyrim SE Data | `C:\Games\Steam\steamapps\common\Skyrim Special Edition\Data` (`$sky`) |
| Starfield install | `D:\SteamLibrary\steamapps\common\Starfield` (`$sf`) |
| MO2 mods folder | `$env:LOCALAPPDATA\ModOrganizer\Starfield\mods` (`$mods`) |
| Converted outfits: S2SArmorTest.esm, meshes, morphs, `gear_fit.json` | `$mods\S2S Armor Test` (`$armor`) |
| Test NPCs: S2SFaceTest.esm, `faces.json` (NPC ids), face textures | `$mods\S2S Face Test` (`$face`) |
| Converted hair / beards: S2SSkyrimHairs.esm | `$mods\S2S Skyrim Hairs` (`$hairs`) |
| Voice test (a second S2SFaceTest.esm under Sound\Voice) | `$mods\S2S Voice Swap Test` |
| More Sliders (face-bone mod) | `$mods\More-Sliders Complete` (`$ms`, `$cs`) |
| Beard matches (beard_match.json) | `C:\Modding\work\beards` |
| Outfit debug meshes (fit_debug.zip per NPC) | `C:\Modding\work\debug_<npc>` (ralof, ysolda, nazeem, saadia) |
| Voice lines (skyrim_voice.py --out: lines.json + .wem / .ffxanim) | `C:\Modding\work\voice` |
| Voice files as installed (face_fit copies them) | `$face\Sound\Voice\S2SFaceTest.esm\S2S_<voice type>_<NPC>` |

## Working commands

Converted outfit for a test NPC (one per NPC; `--add` keeps the other outfits in the plugin):

```powershell
python -I scripts\armor\gear_fit.py --skyrim-data $sky --starfield $sf --npc Saadia --name Saadia_outfit --out $armor --add --debug-dir C:\Modding\work\debug_saadia
```

Same for `Ralof`, `Ysolda`, `Nazeem` (`--name <NPC>_outfit`, `--debug-dir C:\Modding\work\debug_<npc>`). Options in
use: `--debug-steps` (the outfit after each fit step, in the zip), `--conform` (new fit method, A/B), `--curved`,
`--strap-gap <m>` (0 = off), `--round-bust` (female only; looked worse, off).

A Skyrim armor set instead of an NPC's outfit (the NPC only gives race and sex; add it in game with
`player.additem`, the id is printed at the end):

```powershell
python -I scripts\armor\gear_fit.py --skyrim-data $sky --starfield $sf --npc Ralof --armor ArmorIronCuirass --armor ArmorIronGauntlets --armor ArmorIronBoots --name IronArmor --full "Iron Armor (S2S)" --out $armor --add --debug-dir C:\Modding\work\debug_iron
```

Test NPCs with their faces, converted hair, Starfield beards and their outfits:

```powershell
python -I scripts\npc\face_fit.py --skyrim-data $sky --starfield $sf --out $face --npc Ralof --npc Ysolda --npc Nazeem --npc Saadia --test-plugin --hairs-plugin $hairs --outfits-plugin "$armor\S2SArmorTest.esm" --beard-map C:\Modding\work\beards\beard_match.json --voice-lines C:\Modding\work\voice
```

 The NPCs' ids for `player.placeatme` are in
`$face\faces.json`.

Beard matches (rerun only when the matcher changes):

```powershell
python -I scripts\npc\beard_match.py --skyrim-data $sky --starfield $sf --out C:\Modding\work\beards
```
