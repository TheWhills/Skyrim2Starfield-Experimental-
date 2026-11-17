# Creatures: the Riverwood chicken first

Goal: Skyrim's creatures in Starfield on their own skeletons (no retarget), the approach tes4skyrim takes for
Oblivion / Morrowind creatures (docs/research/tes4skyrim.md). The chicken comes first: 33 bones, 20 clips, ambient.
Probe: `scripts/armor/creature_probe.py` (read-only).

## What the probes showed (owner's runs, 2026-11-17)
* Verified: Skyrim ChickenRace 000A919D: skeleton 'NPC Root [Root]' 33 bones + a 7-bone ragdoll skeleton, one
  behaviour (ChickenBehavior.hkx), 20 clips (list in docs/research/tes4skyrim.md).
* Verified: a Starfield creature RACE names ANAM skeleton .nif, NAM5 .rig, NAM6 root graph, DNAM default folder, then
  SGNM subgraph + SAPT folders. Graphs are shared by many skeletons (Creature_Root: 13 races; Critter_Root: 4).
* Verified: CritterRace 000176B6 (Critter_Root -> Critter_NonStrafing -> pathing / idle locomotion / idle turning,
  deaths, staggers, attacks, ranged attack, tunneling, look-at, flinches, jumping, knockdowns; Furniture) has 54 clips
  in Actors\Critter\Animations under PLAIN tags (no Relaxed_ / Ready_ prefixes, unlike QuadrupedA's 159). Its
  Critter_NonStrafing switches by prefix Idle / Attacking and by suffix on iSyncIdleWalkRun (Idle / Walk / Run).
* Verified: QuadrupedARace (Creature_Root -> Creature_NonStrafing, 22 subgraphs incl. graze, hide, bleed-out,
  dodges) has 159 clips, Relaxed_ / Ready_ prefixed idles and turns, Graze_ / Hide_ / BleedOut_ sets: the template for
  Riverwood's bigger animals later (cow, goat, horse, dog: unresolved which fits each).
* Verified (second run, nested nodes read): Critter_NonStrafing_IdleLocomotion plays WalkForward, JogForward,
  RunForward (and Walk / Jog / RunBackward; only WalkBackward ships); Creature_IdleTurning plays Idle and
  TurnInPlace_Left / Right 30 / 90 / 180; Critter_Root plays FurnitureDeath; NPC_Jumping the Jump* set. Idle_Flavor*,
  Idle_Feeding, Warn, Diversion, Ambush are named by no graph node: supported, they come through IDLE records
  (DynamicIdle / IdleFlavor events), so the chicken's flavour idles need IDLE forms too.
* Verified: CritterRace's rig has its own 30 bones (COM, C_spine1-2, C_Head1, C_hips1 / C_Hips2, six legs of 2-3
  bones, antennae of 3): no human bone names, so a creature rig is just its own bone table.
* The minimum clip set for the first test: Idle, WalkForward, JogForward, RunForward, TurnInPlace_Left / Right
  30 / 90 / 180 (graph-driven, no IDLE records needed).
* Correction: the first probe read only a graph's top-level nodes, so locomotion tags inside embedded state machines
  were missing; fixed (deep_tags_refs). The race's own folder is its real clip list either way.

## Chicken clip -> Critter tag (proposed; supported, not tested)
| Critter tag (state = loops) | Skyrim chicken clip |
|---|---|
| Idle (state) | MT_Idle |
| WalkForward (state) | WalkForward |
| RunForward (state), JogForward (state) | RunForward (Jog: the same clip; speed to tune) |
| TurnInPlace_Left90 / _Left180 | TurnLCannedL90 / TurnLCannedL180 |
| TurnInPlace_Right90 / _Right180 | the left turns mirrored (our converter has no mirror yet) |
| TurnInPlace_Left30 / _Right30 | unresolved: a cropped 90 or the 90 itself |
| RunDeparture_Left180 (state) | TurnCannedFleeL180 |
| Warn (state) | AggroWarning1 |
| Idle_Flavor01..04 | Idle_Fulbody1, Idle_Fulbody2, Idle_Fulbody3, Idle_Head1 |
| Idle_Feeding (state) | unresolved (a pecking clip: look at the Fulbody idles first) |
| GetUp_Front / GetUp_Back | GETUP (GETUPStance: unresolved) |
| furniture Idle / EnterFromStand / ExitToStand | Idle_Sitd1 / Idle_SitdownStart / Idle_Setgetup: sitting as a critter "furniture" (a rest spot), with Idle_SitdHeadturn / Idle_SitdPeck unplaced; or Idle_FlavorLoop01..04 (unresolved which) |
| Death_* | none: Skyrim's chicken dies by ragdoll (Starfield ragdoll on a new skeleton: unresolved) |
| Stagger*, MeleeAttack*, FireSingle, Tunnel*, Ambush, Diversion, WalkBackward, Jump* | none (a chicken doesn't do these; the graph only plays them when asked) |
Skyrim's TurnLoopingL has no Critter tag (Critter's idle turning graph plays the TurnInPlace set).

## Reuse found for step 1 (2026-11-17)
* sfnif.build_skinned_nif takes bone NAMES and per-bone binds, nothing human-specific (used by worn gear, hair and
  rigid weapons), and sfmesh writes per-vertex bone weights: the chicken's mesh can be written against its own
  33 bones. skyrimskin.skinned_shapes reads Skyrim's bones, binds and weights.
* Missing: a Starfield skeleton.nif for the chicken (a copy of the critter's shell, see Models), and a rig + clips
  written without retargeting (af_writer already writes any named bone list through CALUMI). The probe now prints a vanilla
  creature skeleton.nif's nodes and extra data (to copy what it carries) and checks the chicken's own models.

## Models (owner's run, 2026-11-17)
* Verified, Skyrim chicken.nif: one skinned BSTriShape 'chicken', 509 vertices, 650 triangles, 32 bones (all but
  the root), 0 unweighted vertices, at most 4 influences, weights from NiSkinData; one texture set + an alpha
  property (cut-out feathers, supported). Our skin reader takes it cleanly.
* Verified, Skyrim skeleton.nif: 35 NiNodes (Character01 > NPC Root [Root] > the 32 bones, MagicEffectsNode),
  BSBoneLOD, SkeletonID, and a ragdoll of 7 capsule rigid bodies with 6 ragdoll constraints.
* Verified, Starfield CritterRace skeleton.nif is a thin shell: 4 NiNodes (Critter_mrRigRoot, Root, COM,
  CharacterController), BSXFlags, two NiStringExtraData 'sgoKeep', two bhkNPCollisionObject -> bhkPhysicsSystem.
  Its 30 bones are only in the .rig (whose first bone is COM). Supported: Starfield builds a creature's bones from
  its .rig at load, so the chicken's skeleton.nif can be a copy of this shell, and its 33 bones go in the .rig.
  Unresolved: how the 4 nodes nest, and what the two physics systems are (ragdoll / controller capsule): the probe
  now prints the node tree and the bone names inside each physics blob.

* Verified (third run): the critter shell nests Critter_mrRigRoot (BSBound 'BBX', BSXFlags) > Root ('sgoKeep') >
  COM at (0, -0.113, 0.149) m ('sgoKeep'; collision: a hknpPhysicsSystem with one hknpSphereShape body), and
  Critter_mrRigRoot > CharacterController (collision: one hknpCapsuleShape body). Neither physics blob names a bone:
  no multi-bone ragdoll, so the shell can be copied to another creature as it is (creature.shell_skeleton renames the
  root and moves COM).

## The first test: the chicken in the critter's place (decided 2026-11-17)
A race of our own with its own animation folders meets the problem race_heads met (docs/npc/races.md: a copied race
with its own subgraph entries stood in the reference pose; the precomputed animation data is per race): it would need
the Creation Kit's animation-info generation or a SAM fragment first. So the skeleton question is asked without it:
the chicken's files replace the critter's own, at the critter's paths (skeleton.nif shell, skeleton.rig, the clips
under the critter's file names and descriptors, its body model), as loose files in a test mod. The index still
lists every file (same names), so any critter (placeatme) shows the chicken, or the failure is the skeleton itself.
Second test, after: the chicken as its own race (index via CK or SAM).
Core: src/fo4sf/creature.py (rig fold, clips, skinned mesh, shell; tests/test_creature.py); build:
scripts/npc/creature_build.py (loose files, no plugin; tests/test_creature_build.py incl. a fake-games run).
* Verified (fourth run): CritterRace's skin is Skin_Critter_Trilobite -> AA_Critter_Trilobite, MOD2
  Actors\Critter\Mesh\Critter_Trilobite\Critter_Trilobite.nif; trident, thorn and spaceroach critters have their own
  skins on the same race and rig; Traits_Critter_Trilobite 002C180F is the NPC to place.
* The test replaces the trilobite's model, so trilobites show the chicken; the other three lose their bones while the
  mod is on. Right turns keep the critter's clips (the chicken has left turns only; no mirror yet): during them the
  chicken stands in its rest pose. Unresolved: whether root motion is needed (clips play in place); the critter-sized
  sphere / capsule; the units differ by 0.01 % (mesh 1/70, rig 0.0142875: negligible).
In game, success: a chicken, its feathers textured, idling, walking and running without stretching or exploding.
Failure modes and what they mean: invisible (the mesh or its bones not found), a tangle of stretched triangles (rig
and bind disagree: creature_build.json bind_vs_rig), frozen in rest pose while moving (clips not found or not
matching the rig), a crash at load (the shell or rig rejected).

## What the test needs (in order)
1. The chicken mesh as a Starfield skinned mesh bound to its own bones, plus a Starfield skeleton.nif of those
   33 bones. Unresolved: our skinned-mesh path (gearfit / sfmesh) binds to Starfield's human skeleton; a
   keep-the-source-skeleton mode is new work.
2. A .rig from that skeleton.nif (hkx_to_af --own-rig exists; verified on doors that a custom .rig plays).
3. The clips converted without retargeting (hkx_to_af retargets onto the human today: a same-skeleton mode is new),
   each with an .afx under its Critter tag, in a new folder (Actors\S2SChicken\Animations).
4. The folder registered in the animation index: a new folder needs a clip-list entry (SAM page: an
   animations_<number>.txt for the graph's list), or the Creation Kit's animation-info generation. Tags already
   exist, so no new tags are needed. Verified earlier (2026-10-19): a loose clip the index doesn't list is not found.
5. A RACE copied from CritterRace with ANAM / NAM5 / DNAM / SAPT pointed at the chicken, an NPC_ using it, and one
   placed in Riverwood.
Success in game: the chicken stands, idles and walks with its own skeleton (no stretching), i.e. Starfield takes a
new creature skeleton on an existing graph.

## First in-game run (owner, 2026-11-17 14:02)
* Build: 36 files, all 15 clips, nothing missing. In game, `placeatme 2C180F`: the creature is heard but nothing is
  seen. Supported: the actor exists (its sounds play), its body is not drawn.
* Candidates: (1) loose .mesh files not loaded (loose animations load on this install, 2026-11-15, but our gear and
  hair always shipped in BA2s: loose geometries never tested); (2) the skin's bones not found (our bone names COM,
  Spine ... vs what the engine builds from the .rig); (3) a difference from the vanilla creature model's layout.
  Next: `creature_probe.py --model` prints the vanilla trilobite model and ours side by side.
* Verified (owner's creature_build.json): the chicken's bind pose matches the rig on every bone (0 mm, under 0.1 deg);
  all 15 clips written (26-201 frames).
* Verified (owner's model compare, 2026-11-17 14:08): the vanilla body Critter_Trilobite.nif carries its OWN bone
  nodes: 29 NiNodes (ExportScene, COM_Twin, C_spine1 ... ProjectileNode), 28 'sgoKeep' + one 'ParentBoneName'
  NiStringExtraData, BSSkin::Instance (skeleton root 0, 26 bones) and a SkinAttach whose 26 names are all EMPTY, plus
  a ragdoll (bhkRagdollSystem, 5 bhkNPCollisionObject); 4 LODs, tangents on every vertex. Ours was worn-gear style (one
  node, names only, bone refs -1): the cause of the invisible body (supported).
* Fix: creature.build_body_nif writes the vanilla layout: ExportScene > COM_Twin > the rig's bones at rest, each with
  'sgoKeep'; the skin instance points at those nodes; empty SkinAttach names; tangents from the Skyrim mesh. Not
  copied yet: ProjectileNode / ParentBoneName, the ragdoll, LODs 1-3.

