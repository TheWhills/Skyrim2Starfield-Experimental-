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

Phone notifications: tools\owner\notify-profile.ps1 is loaded by the PowerShell profile (set up once, see
below), so every `python <script>.py ...` run sends "<script> <name>: done / FAILED" to the ntfy topic
skyrim-conversion-tj-92841, and `notify "..."` sends any message. The cloud session cannot reach ntfy.sh itself.

Once per PC:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
if (-not (Test-Path $PROFILE)) { New-Item -ItemType File -Force $PROFILE | Out-Null }
Add-Content $PROFILE '. "$HOME\Skyrim2Starfield-Experimental-\tools\owner\notify-profile.ps1"'
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
| Race heads test: S2SRaceTest.esm, head morph.dat, `race_heads.json` (NPC ids) | `$mods\S2S Race Test` |
| Converted hair / beards: S2SSkyrimHairs.esm | `$mods\S2S Skyrim Hairs` (`$hairs`) |
| Voice test (a second S2SFaceTest.esm under Sound\Voice) | `$mods\S2S Voice Swap Test` |
| More Sliders (face-bone mod) | `$mods\More-Sliders Complete` (`$ms`, `$cs`) |
| Beard matches (beard_match.json) | `C:\Modding\work\beards` |
| Outfit debug meshes (fit_debug.zip per NPC) | `C:\Modding\work\debug_<npc>` (ralof, ysolda, nazeem, saadia) |
| Exterior objects work folder (export / convert for skyrim_all, Oct 16) | `C:\Modding\work\sky_all` |
| Installed exterior (Tamriel on the planet; matches the game's SkyrimTerrainTamriel.esm, height offset 385 m) | `C:\Modding\staging\skyrim_all` |
| Other exterior builds (older) | `C:\Modding\staging\skyrim_objects`, `C:\Modding\staging\skyrim_tamriel` |
| Interior batches (checklist step 11, Oct 23) | `C:\Modding\work\s2s\interiors`, `C:\Modding\work\s2s\checklist` |
| Riverwood <-> inn door build | `C:\Modding\work\s2s\riverwood_doors` |
| Exterior navmesh (export, survey, compare.html) | `C:\Modding\work\s2s\riverwood_doors\navmesh` |
| Voice lines (skyrim_voice.py --out: lines.json + .wem / .ffxanim) | `C:\Modding\work\voice` |
| Voice files as installed (face_fit copies them) | `$face\Sound\Voice\S2SFaceTest.esm\S2S_<voice type>_<NPC>` |

## Queue for the next session (written 2026-11-09, in this order)

Each step says what to send back. A: read-only, Starfield may stay open; B: builds, Starfield closed; C: in game.

1. `git pull`
2. Done 2026-11-09: race probe (good), beast probe (fixed), readiness, magic and fire surveys (docs/npc/races.md,
   "Owner's run of the probes").
3. Done 2026-11-09: mouth probe (teeth placed, jawOpen found; docs/npc/races.md).
4. B: Embry's outfit, then the faces of all seven test NPCs (the head transfer changed, so every face changes):
   ```powershell
   python -I scripts\armor\gear_fit.py --skyrim-data $sky --starfield $sf --npc Embry --name Embry_outfit --out $armor --add --debug-dir C:\Modding\work\debug_embry
   python -I scripts\npc\face_fit.py --skyrim-data $sky --starfield $sf --out $face --npc Ralof --npc Ysolda --npc Nazeem --npc Saadia --npc Orgnar --npc Delphine --npc Embry --test-plugin --hairs-plugin $hairs --outfits-plugin "$armor\S2SArmorTest.esm" --beard-map C:\Modding\work\beards\beard_match.json --voice-lines C:\Modding\work\voice
   ```
   Send faces.json (and gear_fit.json if Embry's run complains).
5. B: the Riverwood build with the scheduled NPCs (always after a face_fit run: its ids move):
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\owner\riverwood_doors.ps1 -Find "^Riverwood" -Navmesh -Actors Orgnar,Delphine,Embry -Furniture
   ```
6. C: in game: Embry's shirt shows, Delphine's dress does not clip at the shoulders, the faces (compare with Skyrim),
   Orgnar still at the bar. New in this build: cooking pots, the alchemy lab and the enchanter are Starfield
   crafting furniture: does anyone cook at a pot, and what does E on a pot / the alchemy lab open? (If it breaks
   something, rebuild with `-NoCrafting`.) Screenshots.
6b. Done 2026-11-09: Delphine's shoulders fixed (armpit skin limited to the underside, none under tight sleeves).
   The iron armour was converted with the old armpit: refit it when it is next tested and check its armpit when aiming.
6c. Done 2026-11-09: crafting stations. Alchemy lab, enchanter and cooking pot each open a Starfield menu (Starfield's
   recipes; Skyrim's own recipes are a later step).
7. Done 2026-11-09: race heads in game. Altmer / Bosmer / Dunmer / Orc shapes on Starfield's head, pointed ears both
   sides (stronger-side symmetry), normal skin. Open: the Orc mouth hangs open (teeth / mouth do not follow).

7b. B + C: the Orc race. Done: S2S_OrcRace exists and its NPCs animate (2026-11-09). Now the player side: the race
   lists two Orc face presets, and an optional player patch (S2SOrcPlayer.esm) makes the player an Orc, as the Exo
   Race mod does (setrace on the player did not take). Starfield closed:
   ```powershell
   git pull origin skyrim/armor
   python -I scripts\npc\race_heads.py --skyrim-data $sky --starfield $sf --out "$mods\S2S Race Test" --new-races Orc --player-race Orc
   ```
   S2SOrcPlayer.esm lands in the S2S Race Test mod folder: tick it in MO2's plugin list after S2SRaceTest.esm (off
   = human player as before). In game: a NEW game (character creation as an Orc: presets, the Orc blend in each
   region), then a test save: `player.getisrace xx00080F` and `showlooksmenu player 1`. Screenshots.
   2026-11-10: the patch works on an existing save (getisrace 1.00), but showlooksmenu crashes when hovering facial
   hair. Open: is it our race or the looks menu itself - the same save with S2SOrcPlayer.esm off (human player),
   other categories (hair, eyebrows) as the Orc, and what a vanilla beard head part names
   (`npc_record_diff.py --type HDPT --find beard --show beard`). The dump: every beard names its valid races as
   FLST HeadPartsHumanRace (0024A024), without our race. Fixed: race_heads adds the new races to that list; rerun
   the command above, then the looks menu again.
   Owner: no crash any more, but not Orc-looking and several Face controls locked. Now the Orc shape is baked into
   the race's own head (default --race-shape baked); rerun the command above (same command), then the looks menu.
   Its output lists the baked head files; the mod folder gains meshes\s2s\races\orc and geometries\.
   Owner: Orc head shows; face rows garbled ("U", "Z"), shape pads and eye shape locked, eyebrows clip, mouth open.
   Fixed the row names (localized labels) and the presets (they had been added as face dials); same command again.
   Then: the face parts (eyes, lashes, brows, beards, teeth, jewelry) baked per race and sex too (same command; the
   output prints how many parts and how long; --no-bake-parts to skip).
   All ten races at once (each its own race, baked head + parts, Skyrim height); --player-race picks which one you
   play (Orc, Altmer, Bosmer, Dunmer, Nord, ...):
   ```powershell
   python -I scripts\npc\race_heads.py --skyrim-data $sky --starfield $sf --out "$mods\S2S Race Test" --new-races all --player-race Orc
   ```
   The Orc race now also gets Skyrim's orc mouth (teeth + tusks) as its teeth; the run uses texconv and
   <Starfield>\Tools\ContentResources.zip for its texture (--texconv / --content-resources if elsewhere). Check in
   game: tusks show, sit in the mouth, and drop with the jaw when talking.
   Dialogue that fits the story (2026-11-10: lines whose Skyrim conditions do not hold at the start of a new game -
   Delphine's dragon mounds, Embry's romance lines - are left out; docs/npc/voice-pipeline.md). Rerun the voice
   step (lines already converted are reused, so only new ones go through Wwise / lips), then face_fit (step 4's
   command) and the Riverwood build (step 5):
   ```powershell
   python -I scripts\npc\skyrim_voice.py --skyrim-data $sky --out C:\Modding\work\voice --npc Ralof --npc Ysolda --npc Nazeem --npc Saadia --npc Orgnar --npc Delphine --npc Embry --ffmpeg <ffmpeg.exe> --starfield $sf --wwise --lips
   ```
   Looks probe (read-only; send look_probe.md): skin tones and eye colours, and how the aliens mod adds its green skin
   (its .esm path from MO2; leave --plugin out if unsure):
   ```powershell
   python -I scripts\npc\look_probe.py --starfield $sf --out C:\Modding\work\races --plugin "<aliens mod>.esm"
   ```

7d. B + C: Riverwood's NPCs on their own races (Faendal a Bosmer, the rest Nords, the Valerius siblings
   Imperials). After the race build with all races (step 7b's command with `--new-races all`), face_fit with
   `--races-plugin` (EditorIDs it cannot find are printed: tell me and I fix the list), then the Riverwood build:
   ```powershell
   python -I scripts\npc\face_fit.py --skyrim-data $sky --starfield $sf --out $face --npc Ralof --npc Ysolda --npc Nazeem --npc Saadia --npc Orgnar --npc Delphine --npc Embry --npc Faendal --npc Alvor --npc Sigrid --npc Hod --npc Gerdur --npc Sven --npc Hilde --npc CamillaValerius --npc LucanValerius --test-plugin --hairs-plugin $hairs --outfits-plugin "$armor\S2SArmorTest.esm" --beard-map C:\Modding\work\beards\beard_match.json --voice-lines C:\Modding\work\voice --races-plugin "$mods\S2S Race Test\S2SRaceTest.esm"
   ```
   In game: placeatme Faendal's test NPC (faces.json): Bosmer head and ears, his own face on top; a Nord looks like
   before. S2SRaceTest.esm must load before S2SFaceTest.esm.
7c. B + C: the walled cities as their own spaces next to Tamriel (docs/terrain/skyrim-cities.md). Whiterun first
   (one city converts its models once; later runs resume):
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\owner\cities.ps1 -Cities WhiterunWorld
   ```
   Enable "S2S Skyrim Cities" in MO2 (SkyrimWorlds_Register.esm last), then in game `coc` the printed marker. Does
   Whiterun stand on its ground, and does Tamriel still load as before? Then all five (no -Cities). Gates later.
8. B + C: SAM one-tag test (docs/armor/animation-port.md, "SAM"). Needs SAM (Nexus 18674) and Address Library for
   SFSE Plugins enabled in MO2, the game started with sfse_loader.exe:
   ```powershell
   python -I scripts\armor\sam_test_pack.py --starfield-data "$sf\Data" --out "$mods\S2S SAM Test"
   ```
   Enable "S2S SAM Test" last (it ships MeleeAttacks.agx: disable our stance / combo packs for the test, or keep it
   below them), draw a one-handed melee weapon, attack once. The overhead power swing = SAM made our new tag play;
   a snap or nothing = it did not. Send a short clip or what you saw, and SFSE\Plugins\SfAnimIndexLoader.log (MO2:
   in the SAM mod folder or Overwrite).
9. Done 2026-11-09: clothing as items. Ysolda's FarmClothesOutfit04 (dress, boots) in S2S Clothes, male and female
   versions; both test NPCs wear it, and the player's dress follows the body sliders in character creation.
9b. Done 2026-11-09: Delphine (and Ysolda) wear the shared S2S_FarmClothesOutfit04 in the Riverwood build (in game:
   showinventory lists S2S_ClothesFarmClothes04 / S2S_ClothesFarmBoots04 worn from that outfit; shoulders clean).
9c. Done 2026-11-09: the other test NPCs' outfits as items (Ralof, Nazeem, Saadia + Orgnar, Embry), Riverwood rebuilt.
   Orgnar: skin through his shirt while wearing the barkeeper shoes, fine without them (owner).
9d. Done 2026-11-09: ClothesBarKeeperShoes and ClothesFineBoots02 rebuilt alone (--armor); Orgnar, Saadia, Nazeem
   right in game. All seven test NPCs wear shared item outfits.

10. B + C: weapon types with their own movesets (docs/armor/animation-port.md, "weapon types"). Install the two
   zips I sent (SkyrimMelee_LoreRim_greatsword_type.zip, SkyrimMelee_LoreRim_waraxe_type.zip) as MO2 mods, keep the
   sword stance pack v15 enabled, then (use your stance and iron weapon mod folders if they are named differently):
   ```powershell
   python -I scripts\armor\stance_plugin.py --starfield $sf --out "$mods\S2S Stances"
   python -I scripts\armor\weapon_test_pack.py --skyrim-data $sky --starfield $sf --texconv C:\Modding\tools\texconv.exe --out "$mods\S2S Iron Weapons" --stances-plugin "$mods\S2S Stances\S2SStances.esm"
   ```
   Then the Creation Kit cache run (docs/armor/animation-port.md, "The Creation Kit cache run"). In game: additem the
   iron greatsword, war axe and sword (`help "(Skyrim)" 4`). Greatsword = LoreRim's greatsword swings with both hands on
   the handle; war axe = its axe swings; sword unchanged; the stance keys change each. If greatsword and axe still swing
   like the sword, send weapon_test_pack.json and stance_plugin.json (in those mod folders).

11. B + C: race proportions test (docs/npc/races.md, "Race proportions"). Extract Racial Body Morphs - Extreme into
   its own folder (e.g. C:\Modding\work\rbm), then (`--calumi`: the CALUMI.Animation.dll hkx_to_af uses; optional):
   ```powershell
   python -I scripts\npc\skeleton_probe.py --starfield-data "$sf\Data" --race-mod C:\Modding\work\rbm --out C:\Modding\work\skeleton_probe --calumi <CALUMI.Animation.dll> --test-pack Orc --pack-out "$mods\S2S Skeleton Test"
   ```
   Enable "S2S Skeleton Test" (it replaces the human skeleton, so EVERY human, you too, gets Orc male / female
   proportions: upper body about 10 % bigger, wider shoulders, smaller head, shorter forearms). Look at yourself and
   NPCs standing, walking, running and swinging a weapon, clothes and armour on; then disable it and compare. Send
   skeleton_probe.md and screenshots of both. Normal-looking with it on = Starfield ignores the helpers (SFSE route);
   broken or crash = disable it and tell me.

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

Race survey (read-only; every Skyrim race against Starfield's character system; docs/npc/races.md):

```powershell
python -I scripts\npc\race_survey.py --skyrim-data $sky --starfield $sf --out C:\Modding\work\races
```

Race probe (read-only: Starfield's head morphs and regions, HumanRace-by-name counts, Skyrim race morphs moved onto
Starfield's head; opens as C:\Modding\work\races\race_view.html):

```powershell
python -I scripts\npc\race_probe.py --skyrim-data $sky --starfield $sf --out C:\Modding\work\races --skip refs
```

Race heads test (Skyrim race shapes as head morph keys, NPCs to spawn; then enable "S2S Race Test" and
S2SRaceTest.esm in MO2, spawn with the console lines it prints, xx = the plugin's load order index):

```powershell
python -I scripts\npc\race_heads.py --skyrim-data $sky --starfield $sf --out "$mods\S2S Race Test"
```

Default races HighElfRace, OrcRace, WoodElfRace, DarkElfRace (at most 4: one morph.dat holds 128 keys); `--races`
to pick others. If the race NPCs look like the control NPC (plain face), rerun with `--race-head` (HumanRace then uses
our head part and lists our keys; vanilla faces stay as they are since our morph.dat keeps every vanilla key).

Mouth probe (read-only: Skyrim's human / orc mouths placed on Starfield's head, jaw part marked, weights copied
from Starfield's teeth; opens as C:\Modding\work\races\mouth_view.html):

```powershell
python -I scripts\npc\mouth_probe.py --skyrim-data $sky --starfield $sf --out C:\Modding\work\races
```

Beast probe (read-only: Khajiit / Argonian heads warped onto the human one and given Starfield's face-bone weights,
their sliders, tail and skeleton bones, Starfield's morph records; opens as C:\Modding\work\races\beast_view.html):

```powershell
python -I scripts\npc\beast_probe.py --skyrim-data $sky --starfield $sf --out C:\Modding\work\races
```

`--skip refs` leaves out the HumanRace counts (unchanged since the first run). The transfer is the surface one
(fo4sf/headcorr.py, about 20 s per sex); `--transfer nearest` gives the old average to compare. face_fit uses the same
transfer (also `--transfer nearest` there).

Beard matches (rerun only when the matcher changes):

```powershell
python -I scripts\npc\beard_match.py --skyrim-data $sky --starfield $sf --out C:\Modding\work\beards
```

Riverwood <-> Sleeping Giant Inn load doors (interior batch with --exterior, convert, FO4Port.esm overriding the
installed exterior's door, install; Starfield closed):

```powershell
powershell -ExecutionPolicy Bypass -File tools\owner\riverwood_doors.ps1
```

All of Riverwood's interiors (every interior cell whose EditorID starts with Riverwood):

```powershell
powershell -ExecutionPolicy Bypass -File tools\owner\riverwood_doors.ps1 -Find "^Riverwood"
```

Riverwood's interiors plus Skyrim's exterior navmesh around Riverwood (5 x 5 Skyrim cells; `-NavRadius` to change),
with the comparison (`C:\Modding\work\s2s\riverwood_doors\navmesh\compare.html`):

```powershell
powershell -ExecutionPolicy Bypass -File tools\owner\riverwood_doors.ps1 -Find "^Riverwood" -Navmesh
```

Where Skyrim sits on the planet (sun path; show, then move: latitude, longitude in radians; Starfield closed):

```powershell
python -I scripts\terrain\set_planet_latlon.py --staging C:\Modding\staging\skyrim_all
python -I scripts\terrain\set_planet_latlon.py --staging C:\Modding\staging\skyrim_all --latlon 0.3 0 --starfield $sf
```

Which converted exterior object is this (console FormID of a clicked object, or everything near a spot from
`player.getpos x` / `y`):

```powershell
python -I scripts\terrain\which_ref.py --staging C:\Modding\staging\skyrim_all --ref <FormID>
python -I scripts\terrain\which_ref.py --staging C:\Modding\staging\skyrim_all --near <x> <y> --radius 6 --spawn-at 225.70 -627.74
```

The game reports positions in the planet's merged grid, not the exterior's own frame: `--spawn-at` is
`player.getpos x` / `y` right after `coc SKY_TamrielRiverwoodSpawn` (225.70, -627.74 on 2026-11-08; z 184.15 there
while the exterior's own height is about 382 m). terrain_view.py takes the same `--spawn-at`.

Terrain around a spot (the game's BTD heights vs Skyrim's ground, bumps, objects, water; 2-D map and 3-D view):

```powershell
python -I scripts\terrain\terrain_view.py --terrain C:\Modding\staging\skyrim_all --skyrim "$sky\Skyrim.esm" --pos <x> <y> --radius 40 --out C:\Modding\work\terrain_view.html
```

How Skyrim's collision for a model compares with the visible mesh and with our box collision (3-D + top-down excess):

```powershell
python -I scripts\terrain\collision_view.py --skyrim-data $sky --model meshes\Landscape\Roads\RoadStraightLongRamp01.nif --out C:\Modding\work\collision_view.html
```

The installed exterior with Skyrim's own collision instead of boxes (reconverts every outdoor model, then swaps the
meshes in the staging and reinstalls; long; Starfield closed):

```powershell
powershell -ExecutionPolicy Bypass -File tools\owner\exterior_collision.ps1
```

NPC schedules, step 1 (read-only survey of an NPC's AI packages and Starfield's package templates):

```powershell
python -I scripts\npc\package_survey.py --skyrim "$sky\Skyrim.esm" --npc Orgnar --starfield "$sf\Data\Starfield.esm" --out C:\Modding\work\packages
```

NPCs placed in their converted interior with their Skyrim AI packages (step 2 of docs/npc/schedules.md; Starfield closed):

```powershell
powershell -ExecutionPolicy Bypass -File tools\owner\riverwood_doors.ps1 -Find "^Riverwood" -Navmesh -Actors Orgnar
```

In game, NPC selected in the console: `getiscurrentpackage <id>` (1 = running; ids are printed by the build, FO4Port's
load slot is 05, e.g. `getiscurrentpackage 05000E64`). `getcurrentaiprocedure` is not a reliable check (vanilla NPCs show -1).

Furniture survey (read-only; Skyrim's chairs / beds / lean spots in the batch and Starfield's furniture; docs/npc/furniture.md):

```powershell
python -I scripts\interior\furniture_survey.py --skyrim "$sky\Skyrim.esm" --skyrim-data "$sky" --starfield "$sf\Data\Starfield.esm" --work C:\Modding\work\s2s\riverwood_doors --out C:\Modding\work\furniture
```

Furniture NPCs can use (chairs, benches, beds, lean counters, sweeping spots) in the same build (Starfield closed):

```powershell
powershell -ExecutionPolicy Bypass -File tools\owner\riverwood_doors.ps1 -Find "^Riverwood" -Navmesh -Actors Orgnar,Delphine,Embry -Furniture
```
Scheduled NPCs with their own face, hair, outfit and voice: fit them first (outfit, voice lines, face-test NPC; the
face_fit run must list every NPC wanted, old and new, since it rewrites S2SFaceTest.esm), then the build above. The
build overrides each NPC's face-test record (FO4Port.esm masters S2SFaceTest.esm: in MO2's plugin list FO4Port.esm must
sit below it). Rebuild FO4Port.esm after every face_fit run (face_fit's ids move). `$env:ACTOR_LOOK="generic"` = the
old generic copies.

`-MarkerZ skyrim` puts the markers at Skyrim's seat height instead of the floor. `-FurnShift "bartender=0,0.2,0"` moves a kind's markers
(metres, +y = facing); furniture_standoff.py measures how far (vanilla placements vs Skyrim's):

```powershell
python -I scripts\interior\furniture_standoff.py --esm "$sf\Data\Starfield.esm" --base NPCBartender_Standing --base NPCLeaningBartopFront --out C:\Modding\work\furniture\standoff_sf.json
python -I scripts\interior\furniture_standoff.py --esm "$sky\Skyrim.esm" --base CounterBarLeanMarker --base CounterLeanMarker --units 70 --out C:\Modding\work\furniture\standoff_sky.json
```
