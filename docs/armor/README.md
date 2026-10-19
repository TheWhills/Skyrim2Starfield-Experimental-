# Armor, skeletons and animation: what exists on branch `skyrim/armor`

Status: **offline tools on synthetic data; nothing run on real game files or in game yet.** Labels as elsewhere.

| Piece | File | Status |
|---|---|---|
| Armor inventory (ARMO / ARMA: slots, armor type, worn / 1st-person / world models, races, weight slider) | `src/fo4sf/skyrimarmor.py` | layouts from xEdit wbDefinitionsTES5 (weight slider "Enabled" = DNAM bit 0x02); synthetic tests |
| Skinned (worn) Skyrim SE mesh reader: bones, bind transforms, per-vertex weights, body-part partitions | `src/fo4sf/skyrimskin.py` | layouts from niftools nif.xml; partition-palette bone indices **supported hypothesis**; synthetic tests |
| First-run report: armor step (inventory + parse of up to 400 worn meshes, bone names used, body parts, >80-bone shapes) | `scripts/skyrim_first_run.py` | the real-data check of both readers |
| Skyrim .hkx describe + track decoding (skeletons, animations, bindings, annotation events; spline tracks -> per-frame transforms), SE 64-bit and LE 32-bit | `src/fo4sf/skyrimhkx.py`, `src/fo4sf/hkxspline.py` | **verified** 2026-10-19 on 17 real files (PyNifly's test set: SE + LE humans, troll, skeever); threecomp40 rotations; threecomp48 unverified |
| Skyrim -> Starfield bone table (map / split / derived / world-solved / rest / unmapped, with reasons) | `src/fo4sf/skeletonmap.py`, `scripts/armor/bone_map_report.py` | covers both real skeletons completely; rest joints median 7.4 cm apart |
| .hkx survey over the owner's BSAs | `scripts/armor/hkx_survey.py` | reports implausible values per file = wrong offsets |
| Skeleton / body / animation sample fetch (one zip to upload) | `scripts/armor/fetch_skeletons.py` | synthetic + smoke test on a real Starfield-format archive |
| .af round-trip survey through CALUMI | `scripts/armor/af_roundtrip_survey.py` | fake-backend tests; see af-format-status.md |
| Reference: a working community outfit | robes-of-oblivion-reference.md | verified from its files |
| Starfield animation-system survey (graphs, descriptors, rigs, native behaviours) | `scripts/armor/sf_anim_survey.py` | synthetic test; plan: animation-port.md |
| HDT-SMP / FSMP physics configs: features, chains, mesh links, extra bones | `scripts/armor/smp_survey.py` | synthetic test; findings: animation-port.md "SMP config survey" |
| Starfield Havok cloth (BSClothExtraData, .hkx, BA2): bone-driving rigs, constraints, colliders | `scripts/armor/sf_cloth_survey.py` | synthetic test; findings: animation-port.md "Starfield cloth decoded" |

## Runs to do on the PC (each writes a report to paste back)
1. `python -I scripts\skyrim_first_run.py ...` (terrain, objects, now also armor).
2. `python -I scripts\armor\fetch_skeletons.py --skyrim-data ... --starfield-data ... --out C:\Modding\work\skeletons` -> upload the zip.
3. `python -I scripts\armor\hkx_survey.py --skyrim-data ... --out C:\Modding\work\hkx` -> report.txt.
4. `python -I scripts\armor\af_roundtrip_survey.py --dll <CALUMI.Animation.dll> --starfield-data ... --out C:\Modding\work\af_survey --limit 200`, then without --limit.

## Next, once the reports are in
Skeleton map (Skyrim bone -> Starfield bone(s), rest-pose offsets, length ratios) from the fetched skeletons; then the
armor fitting path (re-pose + body correction field, or body-surface weight transfer), then .hkx track decoding.
