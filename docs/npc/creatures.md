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
* Second in-game run (owner, 14:18): still heard, not seen, with our own bone nodes in the body.
* Verified (model compare 2): the vanilla body's COM_Twin sits at the model's ORIGIN (0, 0, 0) and carries
  NiStringExtraData ParentBoneName = COM (not sgoKeep); its children (C_spine1 at 0, C_hips1 at 0, ...) are in COM's
  frame; BSXFlags 0x1004A; the skin's 26 bone refs do not include COM_Twin. Ours had COM_Twin at the COM's height in
  the actor's space, sgoKeep on it, BSXFlags 0x10000. Supported: the body is hung off the skeleton's COM bone by
  ParentBoneName, so a body without it is never attached (not drawn).
* Fix 2: the body is written in COM's space (creature.to_com_space: vertices, normals, tangents, bind worlds),
  COM_Twin at the origin with ParentBoneName = COM, BSXFlags 0x1004A. `--vanilla-material` gives the chicken the
  trilobite's material to rule the converted (loose) material out.
* **Verified in game (owner, 2026-11-17 14:27, screenshots): the chickens are drawn**, textured with their own
  converted material, at a chicken's size, on Starfield's critter graph. Starfield takes a creature skeleton of our
  own: a rig from Skyrim's skeleton plus a body carrying its own bone nodes in COM's space (fix 2 was the one).
  The owner: "their movement is awfully strange".
* Known gaps that would show as strange movement: (1) no root motion: our clips play in place, while Starfield keeps
  root motion in the .af header and a Root track (humans, 2026-10-19) and the critter rig has no Root bone
  (unresolved where a creature's lives); (2) right turns are the critter's clips (no chicken bones: rest pose);
  (3) jog = run clip; (4) the critter's speeds vs the chicken's stride; (5) Skyrim plays right turns as mirrored
  left ones (supported by its "[mirror" generators). Next: `creature_probe.py --motion` prints the chicken's motion
  data and the vanilla critter clips' headers / COM tracks.
* Owner, 14:29 (screenshots): the chickens move, but "not quite upright, they almost pedal their legs forward": the
  body sits tilted back with the legs out in front. Supported cause: the shell's COM node kept the critter's rotation
  (critter bones run along x; creature.shell_skeleton set only COM's position), while the rig and the body assume the
  chicken's COM rest rotation; the engine placing COM by the shell node turns the whole chicken by the difference.
  Fix 3: the shell's COM gets the chicken's COM rest rotation (com_rest_q in creature_build.json); the probe's node
  tree prints node rotations, to compare with the critter's COM.
* Owner, 14:38 (after fix 3, screenshot): still tilted back, legs pedalling in front. Fix 3 did land (shell compare:
  our COM q (-0.469, 0, 0, 0.883), i.e. -56 deg about x = the chicken's Pelvis rest), so the shell rotation was not
  the cause.
* Verified (owner's motion probe): the vanilla critter's shell COM is unrotated and its clips hold COM level
  (yaw ~0, height 0.144-0.157 m in idle / walk / jog / run / turns); its moving clips have a Root track (walk, jog,
  run, turns, flee) and carry their motion in the header (walk +0.504 m over 40 frames, jog +0.600, run +0.650,
  TurnInPlace_Left90 +90 deg, Right90 -90 deg, RunDeparture_Left180 -0.783 m and +180 deg); idles have no Root.
  Skyrim's chicken (animationdatasinglefile, ChickenProject): walk 0.496 m in 1.0 s, run 3.600 m in 1.0 s, canned
  turns +90 / +180 deg in place, flee turns also move (L90: x -1.274 m; L180: y -0.890 m); idles none. Its behaviour
  plays the right turns and two idles as mirrored left ones (8 "[mirror]" generators). Same sign convention as
  Starfield's headers (left = +yaw).
* Fix 4 (supported, to test): COM levelled like the critter's (creature_rig level_com: the Pelvis rest rotation moved
  out of COM into its children, world pose unchanged; the shell COM and the body's COM space follow), a Root bone
  above COM in the rig, and every moving clip gets Skyrim's root motion as its Root track and header
  (creature_build: root_motion_m_deg in creature_build.json). Hypothesis for the tilt: the engine does not compose
  COM's clip keys with a rotated COM rest the way af_writer assumes (rest-relative keys, verified on human bones
  whose root carries no such rotation); with COM at identity both readings agree.
* Owner, 17:35 (screenshots beside Skyrim's chicken): fix 4 works, they "move right"; but the body looks "almost
  missing a piece or underbelly": a hard edge down the breast, hollow between the legs. Not a rig problem (the pose
  and stride match Skyrim's). Candidates: (1) faces Skyrim draws double-sided (SLSF2_Double_Sided) culled in
  Starfield: the creature mesh path never added back faces, unlike statics (skyrimconvert.with_back_faces);
  (2) the alpha cutout removing more than Skyrim's test does. Fix 5: back faces added when Skyrim's shader is
  double-sided (--double-sided auto|on|off), the shader / alpha flags recorded in creature_build.json
  ("skyrim_shader"), and --opaque to rule the cutout out.
* Owner, 17:43 / 17:46: the json shows Skyrim's chicken shader is NOT double-sided (alpha test at 128, no blend), and
  --opaque changed nothing: neither the culling nor the cutout. Cause found (verified by a test that fails on the
  old code): since fix 4 COM rests level, but the body's COM bind was still the Skyrim Pelvis bind (pitched -56 deg),
  so at rest every vertex weighted to COM (belly, lower breast) was swung 56 deg up into the body. Fix 6: every bind
  from the rig's rest pose in COM's space (creature.rest_worlds); the mesh's own binds agree with the rig on all other
  bones within 0.1 deg. tests/test_creature.py checks that each bone's rest world cancels its bind.
* **Verified in game (owner, 2026-11-17 17:51, screenshot): the whole chicken shows** (full breast and belly) and it
  moves right: upright, walking and running with Skyrim's root motion. The first Skyrim creature works in
  Starfield on its own skeleton, in the critter's place. Open: right turns (mirror; meanwhile the critter's clips,
  rest pose), its own race (animation index via CK or SAM) so critters stay critters, Skyrim's ragdoll death, the
  flavour idles' IDLE records, the sitting set, then Riverwood's other animals.
* Owner, 17:52: a little way off the chicken's legs stop and it slides; close up the legs animate again. Supported
  cause: distance animation LOD (Skyrim's chicken skeleton has BSBoneLOD; the critter shell has none, so Starfield's
  bone LOD likely lives in the .rig): our rig, written through CALUMI (rotation, translation, name, parent only),
  leaves any per-bone LOD / flag field at its default, so at distance only the root moves. Next: creature_probe.py
  --rig lays a vanilla rig and ours open field by field (96-byte records) to find it. Less likely: the body has one
  mesh LOD where the trilobite has four.
* Owner's rig dump (vanilla critter, vanilla human, ours), 17:55. Verified (same offsets in all three files): bone
  k's record has, after three -1 fields, a 32-bit index at byte 152 + 96 k and a small level at 156 + 96 k. Vanilla:
  Root -1 / 0; critter COM, spine and legs level 2, back-leg tips 1, antenna tips 0; human 4 down to 0 (camera
  bones); records sorted by level; the index a permutation of the bone numbers within level groups (meaning
  unresolved). Ours (CALUMI): -1 / 0 on every bone. Supported: the level is the bone's animation LOD, so at a distance
  only Root moved and the chicken slid with still legs. Fix 7: creature_build patches the rig after CALUMI (creature.
  set_rig_lod: Root -1 / 0, every other bone index = its own number, level 2; --rig-lod N; the record layout is
  checked first). To verify in game: legs keep walking at a distance.
* Owner, 18:08 / 18:12: with the rig levels set (creature_build.json: lod_level 2, no note) the legs still stop a few
  feet off: the rig field is not (alone) the cause. Clip compare (vanilla critter WalkForward.af vs ours): the same
  header layout and root motion; vanilla keys 31 tracks over 40 frames, ours 33 over 31; per-bone track lists in
  both; nothing that reads as per-LOD clip data (unresolved, not decoded further). The body models do differ: the
  vanilla trilobite fills LOD0-3 (each skinned, 26 bones), ours only LOD0. Supported: a small creature switches to
  LOD1 within a few feet (screen size), and an empty slot is drawn unskinned at rest, riding the moving actor.
  Fix 8: the body fills all four LOD slots with its mesh (--body-lods, default 4). Real lower-detail meshes later.
* Owner, 18:18: with LOD0-3 filled the legs still stop ~5 ft off. Next hypothesis (supported, not verified): a clip
  takes the rig's per-bone levels when CALUMI writes it against the rig, and fix 7 patched the rig only AFTER all 15
  clips were written (against the unpatched rig, every bone level 0). The vanilla walk clip has bone lists near its
  start that ours lays out differently (clip compare, 18:12). Fix 9: creature_build makes the rig first (with the
  first clip), patches its levels, then writes every clip against the patched rig.
* Owner, 18:23: fix 9 (rig patched before the clips) did not help. 18:25, the control: the VANILLA trilobite (mod off)
  keeps walking with its legs from afar. Verified: the freeze comes from our files, not from critter-sized creatures.
  Fixes 7-9 (rig levels, LOD0-3 slots, rig before clips) each left it unchanged; the rig fields' meaning is
  unresolved. Next: CALUMI / sf_animation_io's own code (owner's copy) for the rig and clip fields, and whether only
  the legs or the whole bird freezes (per-bone vs whole-body).

* Owner, 18:33: the WHOLE chicken freezes and slides, not just the legs, so the per-bone levels (fixes 7-9) were
  never the cause. Read (not run) the owner's sf_animation_io-master: its ExportRig adds the rig package and then
  maps bones into it (SFBGSRigPackage_AddBoneNameToMapC; key 0 = Root, 9 = COM, ...), and its docs say "at least,
  the Root bone should be mapped as Root"; rigs also carry a precision (DEFAULT / FIRST_PERSON / SHIP). Ours added
  an empty package: no Root / COM mapping, zero precision (the zeroed header values in the rig compare, supported).
  Fix 10 (supported, not verified): af_writer.copy_rig_package gives our rig the vanilla critter rig's bone-map keys
  for the bones both name (Root, COM), its mannequin flag and its precision, as rig_prefix already did for the human
  rig. The per-bone level patch (fix 7) is now off by default (--rig-lod 0); --no-rig-package builds the old rig.
* Owner, 18:48: fix 10 built (creature_build.json: package_keys Root 0, COM 9) and the whole chicken still freezes
  afar. Ruled out offline: the body's bounding sphere (0 radius, FLT_MAX box) is the same in the vanilla trilobite
  (model_compare). CALUMI's README lists "full .af/.rig decoding" as planned, so it may not write something the game
  uses at a distance. Next, a bisect on the VANILLA trilobite with nothing of the chicken's
  (scripts/npc/critter_roundtrip.py): `--what clips` (the critter's own clips read and rewritten by CALUMI against
  the vanilla rig) and `--what rig` (the vanilla rig copied by CALUMI). Whichever one makes the vanilla trilobite
  freeze afar is the part CALUMI writes wrong; if neither does, the cause is in our rig's bones or the shell.
* Owner, 19:00: clip test keeps animating afar; rig test (the vanilla rig copied by CALUMI, clips vanilla) freezes
  and slides like the chicken. Verified: the freeze comes from the rig CALUMI writes, not from its clips nor from
  anything of the chicken's. CALUMI's copy keeps names, parents, rest pose, bone-map keys, mannequin flag and
  precision (rig_prefix), so the lost data is elsewhere in the rig. Next: a byte diff of the vanilla rig against
  CALUMI's copy (critter_roundtrip --what rig now saves both), then write the chicken rig with what is missing.
* 19:04, byte diff of the vanilla critter rig against CALUMI's copy (same 3717 bytes; owner's files, not in Git).
  Verified layout: header, then 96-byte bone records from byte 128 (record k at 128 + 96k): +0 name offset, +8
  parent, +12/+16/+20 -1 (both), +48 local rotation (x, y, z, w), +80 local translation (both, equal to float
  rounding). What CALUMI does not write:
  - +24 mirror partner index (R_FrontLegA1 7 <-> L_FrontLegA1 5; centre bones themselves). CALUMI -1.
  - +28 level: Root 5, COM 4, C_spine1/2 3, the body 2, leg tips and antenna2 1, antenna3 0. CALUMI 0. (Fix 7
    wrote Root 0 and every other bone 2 here, and k at +24.)
  - +40 float: Root/COM 1, spines 2, legs 5, head 10, antenna1 20, back-leg C 30, antenna2 45, the tips 60.
    CALUMI 0. Meaning unresolved (grows toward the extremities: a size or distance per bone?).
  - +64 a second rotation per bone: equal to +48 for COM; otherwise vanilla's and CALUMI's differ, and neither is
    the parent-composed rest rotation in the conventions tried (unresolved).
  - header: bytes 24-47 hold one 8-byte value three times in vanilla (30 90 c8 21 f5 fd ff ff), CALUMI zeros;
    byte 65 is 01 in vanilla, where CALUMI writes "CALUMIDVRSJOJO".
  Restoring all three groups from vanilla gives the vanilla file but for 24 rounding bytes. Bisect sent to the
  owner: A header only, B +24/+28/+40 only, C +64 only (one mod each on the vanilla trilobite).
* Owner, 19:11: of the three, only B (+24 mirror, +28 level, +40 weight restored from vanilla) keeps the vanilla
  trilobite animating afar; A (header) and C (+64 rotation) do not. Verified: the distance freeze is those per-bone
  fields. Why fix 7 failed (supported): it wrote Root level 0 (vanilla Root 5) and no mirror / weight.
  Fix 11: creature.rig_fields gives every bone vanilla's pattern and creature_build writes it into the chicken's rig
  (creature.set_rig_fields; replaces set_rig_lod / --rig-lod). Mirror: the left/right partner by name. Level: Root
  5, COM 4, trunk 3, else min(2, deepest - depth below COM); this reproduces all 31 vanilla critter levels. Weight:
  1 / 2 / 5 / 30 / 60 by role and level (vanilla's own values are hand-set; meaning unresolved). Chicken: body and
  legs 2, head 1, comb and wattles 0 (like the trilobite's antenna tips: may stop far off).
* Owner, 19:20: with fix 11 the head animates afar, the legs still do not. The vanilla rigs list their bones sorted
  by level, highest first (critter 5, 4, 3, 3, 2 x 19, 1 x 6, 0 x 2); ours listed the chicken's legs (2) after its
  head (1) and comb / wattles (0). Supported hypothesis: far off the game animates only the leading run of bones
  down to some level, so a level-0 bone ends the run and every bone after it stays still. Fix 12:
  creature.sorted_by_level reorders the chicken's rig (stable, parents stay first) before anything is written; the
  body's skin, binds and clips follow the rig by name.
* Owner, 19:25: fix 12 works: the chicken keeps walking with its legs at a distance. Verified in game: a rig written
  by CALUMI needs (1) each record's mirror / level / weight (creature.rig_fields, set_rig_fields) and (2) its bones
  sorted by level, highest first (sorted_by_level). Fixes 7-10 (old level patch, LOD0-3 body slots, rig before clips,
  rig package) stay in but were not the cause. Applies to every creature rig we build with CALUMI.
* Owner, 19:28: right turns move the legs oddly (they were still the trilobite's clips). Fix 13: the critter's
  turninplace_right30 / 90 / 180 and rundeparture_right180 get the chicken's left-turn clips mirrored across the
  actor's YZ plane (creature.mirror_clip: each bone takes its rig_fields partner's model-space pose reflected, with
  the partners' rest-frame difference kept; Root's turn and sideways drift flip), as Skyrim's "[mirror]" generators
  play them. creature_build.json marks them "mirrored". Offline checks only.
* Owner, 19:28: next, the chicken as its own race and its death ragdoll. Built (offline checks only):
  `creature_build --own-race` writes the same files under actors\s2s\chicken (each critter path moved, same relative
  path: creature_race.redirect) plus S2SCreatures.esm: copies of CritterRace, Skin_Critter_Trilobite, its addon
  AA_Critter_Trilobite and Traits_Critter_Trilobite (S2S_ChickenRace / _Skin / _SkinAA / S2S_Chicken, objects
  0x800-0x803) with the race's ANAM / NAM5 / DNAM / SAPT and the addon's model paths redirected, graphs (NAM6, SGNM)
  kept, every 4-byte field naming one of the four vanilla FormIDs pointed at its copy, FULL as text, DESC and SRAC
  dropped. The race keeps its own subgraph entries, so it needs its own animation data: the Creation Kit's
  GenerateAnimInfo run over S2SCreatures.esm (OWNER-SETUP 7j); without it a copied race stood in the reference pose
  (race_heads, 2026-11-09). Every critter descriptor the chicken has no clip for gets its idle (clips_idle_filled),
  so no tag the critter graph asks for is missing from our folder.
  Unresolved: whether the CK's run over S2SCreatures.esm alone keeps the stance sets (the test disables the stance
  index); whether our race needs the CK's GeneratedSubgraphData table (the listing tells).
* Owner, 19:52: verified in game: S2S_Chicken (1A000803 in the owner's load order) spawns and walks as its own race
  after the CK run over S2SCreatures.esm (S2S Creature AnimInfo: AnimationFileData + AnimationOffsets only; the CK's
  GeneratedSubgraphData tables, ours included, were header-only stubs and were left out). The chicken's folder is
  listed in one set file of the generated index. `help S2S_Chicken 4` lists the race, skin and addon but not the NPC.
  (The trilobite still showed the chicken because the critter-replacing test mod was still enabled.)
* Owner, 19:56: killed, the chicken freezes standing (no ragdoll in its body). Read the vanilla trilobite body
  (owner's file, not in Git), verified: one bhkRagdollSystem block (u32 size + Havok tagfile, root hknpRagdollData)
  and five bhkNPCollisionObject (target node i32, flags u16 0x80, system block i32, body index u32) on COM_Twin (0),
  C_hips1 (1), C_spine1 (2), C_Hips2 (3), C_spine2 (4). hknpRagdollData: 5 materials, 5 motionProperties, 5
  bodyCinfos (COM a sphere, the others capsules, C_spine2 a compound of two capsules; all at the bone's own frame:
  position 0, orientation identity, motionType 2, mass 2 each), 4 constraintCinfos (hkpRagdollConstraintData: pivot
  frames A / B, twist / cone / plane limits, position motors off, friction), an unnamed 5-bone hkaSkeleton (parents
  -1, 0, 0, 1, 2) and boneToBodyMap 0-4. hktagwrite round trip (root type hknpRagdollData): every value read back
  equal; the byte order of items differs from Havok's own (the writer is breadth-first per element), so a game check
  first: the trilobite with its ragdoll rewritten (S2S Ragdoll Writer Test). Skyrim's chicken ragdoll lives in its
  skeleton.nif (7 bhkRigidBody + bhkCapsuleShape on bhkBlendCollisionObject, 6 bhkRagdollConstraint);
  creature_probe --extract-skyrim copies it out.
* Owner, 20:09-20:10: writer test 1 (the trilobite's ragdoll rewritten): killed, it stayed standing and animated or
  flipped over and spun. Verified offline: the vanilla ragdoll puts every array item on 16 bytes and every object on
  8; ours had hkFloat3 hull vertices and the compound shape's instances (SIMD transforms, read in place) on 4.
  hktagwrite.Writer now takes least alignments (array 16 / object 8 for ragdolls; the cloth default unchanged).
  Writer test 2 (same edit, vanilla alignment) sent; result pending.
* Fix 14 (built, offline checks only): the chicken's ragdoll. creature_ragdoll reads Skyrim's (skeleton.nif:
  7 capsule bodies on Pelvis, Neck0-2, HEAD, Right / LeftAnkle, 6 ragdoll constraints, child = A, parent = B, masses
  10 / 5, cone 0.377, planes +-0.26 (ankles +-0.17), twist +-0.70 (ankles +-0.17), friction 10), moves every point
  and axis into the rig bone's frame (identity for all but COM, which takes the pelvis' 56 deg pitch), and writes an
  hknpRagdollData on the vanilla trilobite's (ids, filter, motion properties, motors, friction atoms from its root and
  first capsule body / first constraint), plus a bhkRagdollSystem and one bhkNPCollisionObject per body in the
  chicken's body NIF (COM's on COM_Twin). Checked on the owner's files: every joint's pivot is the same model-space
  point from both bodies and both twist axes agree at rest; the Skyrim nodes sit on the rig bones (0 mm).
  creature_build.json "ragdoll" lists the bodies; --no-ragdoll builds without.
