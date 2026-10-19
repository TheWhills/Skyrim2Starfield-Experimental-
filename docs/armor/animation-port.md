# Porting Skyrim's animations to Starfield: the plan (2026-10-19)

Owner's goal: **all** of Skyrim's animations in Starfield, including what Starfield has no system for (spell casting,
bows, blocking, horse riding, ...), a way to convert **modded** animations (combat packs, OAR / DAR replacers), and
eventually a **patcher like Nemesis / Pandora** for Starfield. This page is the plan; labels as elsewhere
(verified / supported hypothesis / unresolved). See also README.md (what exists on this branch) and af-format-status.md.

## Decision: convert at build time, onto Starfield's own system
* Skyrim's Havok 2010 `.hkx` clips and behavior graphs are **not** run in Starfield. Starfield has its own animation
  system: clips `.af`, clip descriptors `.afx` (XML: tag, is_state, filename), graphs `.agx` (graphs reference base
  graphs with event / tag selectors and variables), skeletons `.rig` (verified for doors: docs/spikes/WP-doors-research.md).
  Teaching the engine to read Havok 2010 would mean replacing its animation runtime from an SFSE plugin.
* Skyrim's skeleton is **not** put on Starfield humans: no bone name is shared (Skyrim `NPC L UpperArm [LUar]`,
  Starfield `L_Biceps`; BodySlide 6.0's reference skeletons: Skyrim SE 514 nodes incl. the XPMSE-style extras,
  Starfield human 116 nodes; verified 2026-10-19), so every Starfield clip, behaviour and outfit would break.
* So: **humans keep Starfield's rig**; Skyrim clips are decoded, **retargeted** onto it and written as `.af` (through
  CALUMI.Animation, already used for doors). **Creatures keep a Skyrim-derived rig** (`.rig` written from the Skyrim
  Havok skeleton) with their clips converted 1:1, no retargeting.

## The pipeline (one converter, many sources)
```
 Skyrim .hkx (vanilla BSAs, mods: SSE 64-bit, LE 32-bit)
   -> decode  (packfile reader + spline / interleaved track decompression; annotations = events; root motion)
   -> neutral clip  (bone name, local rotation / translation / scale per frame, events, root motion, fps)
   -> retarget  (humans only: Skyrim->Starfield bone map, rest-pose correction, limb length, root motion rescale)
   -> write .af + .afx  (CALUMI.Animation via ctypes, run time, LGPL: never vendored)
   -> wire it in  (a vanilla tag the human graph already uses, an IDLE record, a furniture, or a graph patch)
```
Every stage gets a synthetic-fixture test and an in-game oracle (below). The neutral clip is the hand-off point:
glTF export of it also feeds Native Animation Framework SF (Nexus 7360, plays .gltf / .glb on a skeleton node list)
as a fallback player for idles and scenes.

## What goes where

| Skyrim animation set | Starfield has a system for it? | Route |
|---|---|---|
| Locomotion, sneak, jump, sit / sleep / lean, dialogue gestures | yes (native human set) | native Starfield clips by default; Skyrim's as **replacers** (same tags) when wanted |
| Furniture idles (smithing, tanning, cooking, chopping wood, bard, alchemy) | partly (Starfield furniture + idle markers) | Skyrim clip on a Starfield furniture / idle-marker graph with our own `.afx`; NAF fallback |
| One-handed melee | yes (melee weapons) | replacers on the melee tags; Skyrim power attacks / chains may need graph states (patch) |
| Two-handed melee, dual wield, shield block / bash | unresolved (survey) | graph patch + weapon / keyword wiring; possibly SFSE |
| Bows, crossbows | no bow system | supported idea: a weapon whose fire is gated by a charge (draw) state; needs graph states; unresolved |
| Spell casting (ready, charge, release, concentration, dual cast, ward) | Starborn powers exist (one gesture) | supported idea: spells as hand "weapons" (projectile / beam fire, concentration = continuous fire) with casting clips; full Skyrim magic (equip per hand) likely needs SFSE |
| Shouts | powers | map to Starborn powers (one cast clip each) |
| Horse riding (mount, dismount, ride, mounted combat) | no mounts | engine-level. Two candidates: (a) SFSE mount system; (b) supported idea: the horse as a **vehicle** (Starfield's REV-8 rover system) with horse model + clips driven by speed. Survey the vehicle graphs first |
| Swimming | unresolved (survey) | |
| Killmoves / paired | Starfield has takedowns? unresolved | paired clips need both actors' graphs; late |
| Creatures (wolf, bear, horse, dragon, giant, mammoth, draugr, spiders ...) | no matching rigs | Skyrim rig -> `.rig`, clips 1:1 -> `.af`, graph: borrow the closest Starfield creature graph (quadruped / biped) and map clip tags; dragons (flight) are the hardest |
| Werewolf / vampire lord | no | creature rig + player race swap; late |
| Face / lip-sync | `.ffxanim` | separate track (FaceFX); not in this plan |

## Modded animations
* **Clip packs and replacers** (most combat / idle mods): just `.hkx` clips at vanilla paths -> the same converter.
  LE 32-bit `.hkx` must be read too (many mods ship it).
* **OAR / DAR conditional replacers** (folder + `config.json` / `_conditions.txt`): convert the clips; the conditions
  need a Starfield-side **conditional replacer** (SFSE plugin, OAR-like) that picks a clip set per actor by
  condition. Our importer translates the conditions we can evaluate in Starfield (race, keywords, equipped type,
  random, actor value ...); others are reported.
* **Behaviour mods** (MCO / ADXP, SCAR, BFCO, Precision-dependent sets): their Nemesis / Pandora patches edit Skyrim's
  behaviour XML node by node. A generic translation is not possible (different graph). Plan: support the
  **frameworks** (an MCO-style attack-chain graph patch written once for Starfield) and convert the **clip packs**
  that target them; each framework is its own milestone.

## The patcher ("Pandora for Starfield")
A tool that takes a vanilla Starfield `.agx` plus N patches and writes the merged graph, plus the `.afx` / clip folder
entries, once per install (like Nemesis / Pandora's "Update / Launch"). Prerequisite: the `.agx` format (text or
binary, how states / transitions / selectors / variables are stored) and how the game finds graphs and clips
(records' ANAM / BNAM / CNAM, AnimTextData tables). Order:
1. clip **replacement** by tag (no graph edits; may already be enough for many packs if the human graph selects clips by
   `.afx` tag, supported hypothesis from the door graphs)
2. graph **additions** (new states / events / variables) from our own patch format, with conflict detection
3. merge of many patches, deterministic, uninstallable
4. importers for the supported Skyrim frameworks

## Phases and oracles (in-game evidence each)
* **A. Survey** (`scripts/armor/sf_anim_survey.py`): what Starfield's graphs, descriptors, rigs and native behaviours
  are; keyword hits for casting / melee / bow / mount / vehicle / swim / killmove. Plus the existing
  `hkx_survey.py` and `af_roundtrip_survey.py` runs. Oracle: report read.
* **B. One clip end to end**: Skyrim `mt_idle.hkx` decoded, retargeted, written as `.af`, replacing one vanilla human
  idle (loose file, same path). Oracle: a Starfield NPC idles like a Skyrim one, no stretching / twisting.
* **C. Bone map + retarget quality**: walk, run, 1h attack; root motion distance matches. Oracle: no foot sliding.
* **D. First new behaviour**: casting (most asked for), via the cheapest route the survey supports.
* **E. Patcher v1** (tag replacers + one graph addition).
* **F. Creatures**: wolf first (quadruped, simple), then horse (needed for riding), then the rest.
* **G. Riding**, **H. modded packs / OAR importer**, **I. framework importers**.

## Inputs on hand (2026-10-19, owner uploads)
* BodySlide & Outfit Studio 6.0.0 (Nexus 18449, GPL): `res\skeleton_{male,female}_{sse,sk,sf}.nif`, `.hkx` skeletons;
  bone-map source; read from the owner's install, never committed.
* SF Extended Skeleton 1.3 (Nexus 16905): +39 human bones incl. `C_Tail_01..08`, `C_Tail_Root`, ears (`L_Ear1/2`):
  the tail chain Khajiit / Argonian need (a dependency for players).
* XPMSE (Skyrim): extra Skyrim bones (weapons, tails); BodySlide's SSE skeleton already carries them.
* sfport (Nexus 18458, FO4 -> Starfield outfit porter, Python): same armor problem from FO4; method (driver bones,
  torso landmark fit, per-limb rotate + stretch, body fit, skin pieces, morphs) is the reference for the armor step.
  **No license file: learn from it, do not copy its code here.**

## Progress
**2026-10-19 (owner away; real files from PyNifly's GPL test set, used outside the repo, never committed):**
* `skyrimhkx.describe` read 17 real files (SE 64-bit and LE 32-bit: human clips, troll attack, human / troll / skeever
  skeletons) with no implausible values: the member offsets in the module, marked unverified, are **verified**
  (`Layout`, now 32- and 64-bit). Two XML-format `.hkx` files are not read (binary only).
* `hkxspline.decode` (new, written here) decodes every spline-compressed clip: translations agree with PyNifly's
  decoder within 1e-4; rotations within 0.002 (0.007 at one block boundary). Against the uncompressed reference pose
  in skeleton.hkx ours is closer (median 0.00045 vs 0.0013; a quarter of resting bones exact): PyNifly's threecomp40
  offset is about 2 quantization steps off (worth reporting upstream). All 1,044 track-blocks seen use threecomp40;
  threecomp48 / polar32 / threecomp24 / straight16 untested (48 implemented, the others raise).
* Block boundaries follow Havok's lookup (block = time / block duration): frame 255 comes from block 1.
* `skeletonmap` (new): 66 one-to-one bones, Skyrim Spine1 split over C_Spine1 + C_Spine2, 25 derived Starfield
  bones, WEAPON / WeaponLeft / hand IK solved in world space, 19 rest-only nodes, 30 Skyrim bones unmapped with reasons
  (skirt chains, sheath / magic nodes, root-motion helpers). bone_map_report.py on BodySlide's reference skeletons:
  no missing names either side; rest joints median 0.074 m apart, max 0.20 m (clavicle: defined differently, so the
  retargeter carries rotation deltas against each skeleton's own rest pose, never positions).
* Next: the retargeter (neutral clip on Skyrim rest -> Starfield local rotations), then writing `.af` (CALUMI; a Linux
  build of it is half done in scratch, which would let the whole hkx -> af chain be tested here).
