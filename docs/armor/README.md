# Armor, skeletons and animation: what exists on branch `skyrim/armor`

Status: **offline tools on synthetic data; nothing run on real game files or in game yet.** Labels as elsewhere.

| Piece | File | Status |
|---|---|---|
| Armor inventory (ARMO / ARMA: slots, armor type, worn / 1st-person / world models, races, weight slider) | `src/fo4sf/skyrimarmor.py` | layouts from xEdit wbDefinitionsTES5 (weight slider "Enabled" = DNAM bit 0x02); synthetic tests |
| Skinned (worn) Skyrim SE mesh reader: bones, bind transforms, per-vertex weights, body-part partitions | `src/fo4sf/skyrimskin.py` | layouts from niftools nif.xml; partition-palette bone indices **supported hypothesis**; synthetic tests |
| First-run report: armor step (inventory + parse of up to 400 worn meshes, bone names used, body parts, >80-bone shapes) | `scripts/skyrim_first_run.py` | the real-data check of both readers |
| Skyrim .hkx describe + track decoding (skeletons, animations, bindings, annotation events; spline tracks -> per-frame transforms), SE 64-bit and LE 32-bit | `src/fo4sf/skyrimhkx.py`, `src/fo4sf/hkxspline.py` | **verified** 2026-10-19 on 17 real files (PyNifly's test set: SE + LE humans, troll, skeever); threecomp40 rotations; threecomp48 unverified |
| Skyrim -> Starfield bone table (map / split / derived / world-solved / rest / unmapped, with reasons) | `src/fo4sf/skeletonmap.py`, `scripts/armor/bone_map_report.py` | covers both real skeletons completely; rest joints median 7.4 cm apart |
| Iron weapon test pack: Skyrim weapon models into Starfield's WEAPON frame, a minimal plugin writer, one-run PC script | `src/fo4sf/skyrimweapon.py`, `src/fo4sf/sfplugin.py`, `scripts/armor/weapon_test_pack.py` | synthetic end-to-end test; animation-port.md "Iron weapon test pack" |
| .hkx survey over the owner's BSAs | `scripts/armor/hkx_survey.py` | reports implausible values per file = wrong offsets |
| Skeleton / body / animation sample fetch (one zip to upload) | `scripts/armor/fetch_skeletons.py` | synthetic + smoke test on a real Starfield-format archive |
| .af round-trip survey through CALUMI | `scripts/armor/af_roundtrip_survey.py` | fake-backend tests; see af-format-status.md |
| Reference: a working community outfit | robes-of-oblivion-reference.md | verified from its files |
| Outfit Studio MCP probe (the armor conversion's engine: tools, argument schemas, reference templates, archive bodies; optional body load + render) | `scripts/armor/os_probe.py` | fake-server tests; decisions.md 2026-11-05 |
| Outfit Studio armor driver: a Skyrim NPC's default outfit (DOFT -> OTFT -> LVLI -> ARMO -> ARMA worn .nif) onto Starfield's body via MCP (import_from_game, scale / pose / unpose, fit_to_body keeping the old body's gap, copy_bone_weights, validate, render, export) | `scripts/armor/os_convert.py`, `scripts/armor/os_skeleton.py` | synthetic plugin + fake-server tests; route from Outfit Studio's guides (decisions.md 2026-11-06) |
| Outfit Studio -> real Starfield files: pulls the fitted gear over MCP (geometry, per-bone weights), calibrates Outfit Studio's units on the body against the game's naked .mesh, writes BSGeometry + .mesh (the hair writer) and S2SArmorTest.esm (ARMO / ARMA from Clothes_Nightwear_01 + an outfit) | `scripts/armor/os_export.py` | synthetic + fake-server tests; decisions.md 2026-11-06 |
| `scripts/armor/armor_check.py` | Diagnoses a converted armor: body bones whose bind disagrees with the skeleton or that move no body vertex, gear vertices on them, gear vertices far outside the body. |
| `scripts/armor/nif_dump.py` | Dumps the blocks of a vanilla armor NIF and of ours side by side (skin instance, bone data, bone names). |
| `scripts/npc/beard_match.py` | Matches each Skyrim beard to the closest-shaped Starfield beard (beard_match.json, for face_fit --beard-map). |
| `scripts/armor/gear_fit.py` | Fits a Skyrim NPC's outfit onto Starfield's body by skeleton and body shape (`fo4sf.gearfit`), no Outfit Studio; writes the armor mod: one NIF, addon and morph record (MRPH) per shape, so each piece follows the body sliders. |
| Starfield animation-system survey (graphs, descriptors, rigs, native behaviours) | `scripts/armor/sf_anim_survey.py` | synthetic test; plan: animation-port.md |
| HDT-SMP / FSMP physics configs: features, chains, mesh links, extra bones | `scripts/armor/smp_survey.py` | synthetic test; findings: animation-port.md "SMP config survey" |
| Starfield Havok cloth (BSClothExtraData, .hkx, BA2): bone-driving rigs, constraints, colliders | `scripts/armor/sf_cloth_survey.py` | synthetic test; findings: animation-port.md "Starfield cloth decoded" |
| Havok tagfile writer; SMP hair -> Starfield cloth (bone chains, links, local range, capsules); KS wig test pack | `src/fo4sf/hktagwrite.py`, `src/fo4sf/smpcloth.py`, `src/fo4sf/skyrimhair.py`, `scripts/armor/hair_pack.py` | synthetic tests; writer byte-identical on the OC cloth files; animation-port.md "SMP hair -> Starfield cloth" |

## Runs to do on the PC (each writes a report to paste back)
1. `python -I scripts\skyrim_first_run.py ...` (terrain, objects, now also armor).
2. `python -I scripts\armor\fetch_skeletons.py --skyrim-data ... --starfield-data ... --out C:\Modding\work\skeletons` -> upload the zip.
3. `python -I scripts\armor\hkx_survey.py --skyrim-data ... --out C:\Modding\work\hkx` -> report.txt.
4. `python -I scripts\armor\af_roundtrip_survey.py --dll <CALUMI.Animation.dll> --starfield-data ... --out C:\Modding\work\af_survey --limit 200`, then without --limit.
5. Outfit Studio v6.1.0 running with `--mcp` (Starfield target game, empty project): `python -I scripts\armor\os_probe.py --out C:\Modding\work\os_probe --load-body auto` -> zip the folder.

## Next, once the reports are in
Skeleton map (Skyrim bone -> Starfield bone(s), rest-pose offsets, length ratios) from the fetched skeletons; then the
armor fitting path (re-pose + body correction field, or body-surface weight transfer), then .hkx track decoding.

## Clothing as items, both sexes (owner 2026-11-09; built, untested in game)
Owner: today Ysolda's outfit is "Ysolda's outfit" for whoever wears it; eventually each Skyrim clothing piece is one
converted item, with the right ids, worn by every NPC who should wear it, male or female, each seeing its own version.
How both games do it (xEdit wbDefinitionsTES5 / wbDefinitionsSF1, verified field layout): an ARMO lists ARMA addons;
an ARMA holds a MALE and a FEMALE model (MOD2 / MOD3; first person MOD4 / MOD5) and the engine picks by the wearer's
sex. Starfield adds a body-slider morph per sex (NAM4 male world, NAM6 female world; NAM5 / NAM7 first person). Our
writer (os_export) now puts the same fitted model in MOD2 and MOD3 and the same MRPH in NAM4 and NAM6.
Plan:
1. Convert by record, not by NPC: per Skyrim ARMO one Starfield ARMO, per Skyrim ARMA its addon(s) with the Skyrim
   MALE model fitted to Starfield's male body in MOD2 + its morph in NAM4, the FEMALE model fitted to the female body in
   MOD3 + NAM6 (Skyrim ARMAs with one model for both: fitted twice). Fit bodies: the fixed per-sex ones (face_fit
   BODY_NPC) until outfits follow every body through the weight morphs.
2. Skyrim OTFT -> Starfield OTFT of the converted ARMOs (leveled lists later); a converted NPC's DOFT -> its Skyrim
   outfit's converted OTFT, so every NPC sharing an outfit wears the same items.
3. Stable ids: a mapping file (Skyrim form key -> our FormID) kept across rebuilds, so plugins referencing the items
   (NPCs, FO4Port.esm) do not move (face_fit's ids moving each run is the cautionary case).
4. Parts per biped slot (gear_fit.distinct_slots) decided once per ARMA for both sexes; when the male and female NIFs
   do not split the same way, addons per sex (one model filled) - whether an ARMA with only MOD2 shows nothing on a
   female is to check in game.
Test when built: Ysolda's dress item on a female and a male test NPC, each in their own fitted version.

Built (2026-11-09, `scripts/armor/item_convert.py`, synthetic tests in tests/test_item_convert.py; not run on game
data yet, owner queue step 9):
- `gear_fit.py --stage --sex male|female --armor <ARMO>` fits one item for one sex (the race's addon, NordRace by
  default; the male model when the addon has no female one) and writes only the part NIFs, morphs and textures
  (meshes\S2S\Items\<ARMO>_M|F\) and the parts list (gear_fit_<name>.json); no plugin.
- item_convert.py runs that for both sexes of every item (--armor, --outfit, or --npc for its default outfit), pairs
  the parts (skin piece with skin piece, then same shape name, then same slots; slots then made distinct over the
  pairs) and writes S2SClothes.esm with os_export.item_records: per pair one ARMA (MOD2 + NAM4 male, MOD3 + NAM6
  female, a MRPH per sex), per item an ARMO with Skyrim's name (S2S_<ARMO EditorID>), per outfit an OTFT
  (S2S_<OTFT EditorID>, one u32 per item in INAM; the per-NPC outfits held one), and with --test-npcs a male and a
  female NPC (copies of face_fit's body NPCs) wearing it. A part one sex lacks gets an ARMA with that sex's fields
  only (unresolved: what the other sex shows).
- Ids: S2SClothes_ids.json keeps every FormID by EditorID (never reused) and which records each Skyrim item / outfit
  wrote; rerunning an item replaces only its records, other items stay (--replace-all drops them).
- `face_fit.py --items-plugin S2SClothes.esm`: a test NPC wears the converted OTFT its Skyrim default outfit became
  (before --outfits-plugin's per-NPC outfit), so NPCs sharing a Skyrim outfit share the items.
- Open: skin pieces of two items in one outfit both sit on the skin template's slot (13), so only one may show;
  leveled outfit entries resolve as gear_fit does (first entry giving armor, all with Use All).

### Clothing as items, first run (owner, 2026-11-09; verified in game)
item_convert on Ysolda: FarmClothesOutfit04 -> ClothesFarmClothes04 (S2S_Skin slot 13 + dress slots 3 / 5) and
ClothesFarmBoots04 (slot 7), male and female meshes per part, one OTFT. The male and female test NPCs each wear their
own sex's version; the player's dress in character creation follows the weight sliders (muscular / heavy). Seen: a
lighter band at the female test NPC's upper chest (skin piece against the neck; open), the dress's side slits as in
Skyrim's mesh. Next: face_fit --items-plugin so every NPC with this Skyrim outfit (Ysolda, Delphine) shares it.

### Skin pieces on boots and gloves (2026-11-09; in game unverified)
Owner: Orgnar in the converted barkeeper clothes showed skin through his shirt with the barkeeper shoes on, not
without them. Two causes in the code (verified by reading it; the owner's item_convert.json not seen): every skin
piece used the vanilla skin addon's slot 13, so the shoes' skin piece (Skyrim's shoe mesh has a bit of skin) claimed
the shirt's skin slot; and the armpit band (gear_fit.armpits) was added to every skin piece, shoes included, and
showed through the shirt. Now a skin piece on an item that does not cover the body (slot 3) takes the item's own
slots (os_export.item_records), and only body gear gets the armpit band (gear_fit.armpit_skin).

