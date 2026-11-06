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
