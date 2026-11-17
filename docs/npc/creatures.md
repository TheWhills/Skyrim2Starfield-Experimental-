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
* Missing: a Starfield skeleton.nif writer (a NiNode tree of the bones at rest). The probe now prints a vanilla
  creature skeleton.nif's nodes and extra data (to copy what it carries) and checks the chicken's own models.

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
