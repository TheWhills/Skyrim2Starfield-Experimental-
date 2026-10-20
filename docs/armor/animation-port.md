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

**2026-10-19, Skyrim behaviour inventory** (`scripts/armor/behavior_inventory.py` on the 276 vanilla behaviour /
character / skeleton files Pandora ships as templates, GPL repo, read outside this repo). Pandora's copies carry 8
extra leading bytes per object (pointers land on the object start, fields sit 8 bytes later), so they are not the
game's own layout: the inventory reads strings through pointer fixups, independent of offsets. Per creature folder
(graphs, state machines, states, clip generators, synchronized (paired) clips, blends, distinct animation files):
```
creature                 graphs   SMs states  clips  sync blends  anims
ambient                       2    22     76     65     0      3     41
atronachflame                 1    24     57     45     0      8     49
atronachfrost                 1    18     49     59     0     19     39
atronachstorm                 1    16     44     38     0     11     29
bear                          4    27     77     74     5     16     46
canine                        9    81    252    222     6     49    126
character                    35  1963   5269   4975   435   1014   2178
chaurus                       1    18     66     66     0      9     57
cow                           6    29     84     80     0     24     46
deer                          4    25     70     59     0     19     33
dlc01                         2    37    110    120     8     16    109
dlc02                        12   203    549    617    18    127    382
dragon                        1    66    218    214     9     29    189
dragonpriest                  1    36    109    117     0     18    120
draugr                        1    79    232    414     6    120    226
dwarvenspherecenturion        1    36     81    132     0     40     94
dwarvenspider                 1    12     46     44     0     10     37
dwarvensteamcenturion         1    24     68     80     4     16     52
falmer                        1    67    191    190     6     57    136
frostbitespider               1    14     52     53     4      6     49
giant                         1    42     98    124     5     33     75
goat                          4    27     80     62     0     15     43
hagraven                      1    21     61     96     4     24     88
horker                        4    32     88     75     0     13     47
horse                         1    20     66     65     4     11     73
icewraith                     1    11     31     24     0      2     20
mammoth                       4    26     72     59     0     11     51
mudcrab                       1    19     55     56     0      9     46
sabrecat                      4    36    112     91     6     17     71
skeever                       4    24     64     50     0     10     41
slaughterfish                 1    13     31     27     0      7     34
spriggan                      1    21     65     92     4     22    121
troll                         1    24     90    116     5     22     81
vampirelord                   1    44    125    116     3     56    104
werewolfbeast                 1    67    147    200     5     53    146
wisp                          1    22     61     47     0      5     42
witchlight                    1     6     15     11     0      1     10
```
Human ("character"): 35 graphs, 5,269 states, 4,975 clips over 2,178 animation files, 435 paired clips (killmoves,
mount / dismount). Horse: 66 states, 73 animations, events HorseEnter / HorseExit / HorseLocomotion / HorseDismount;
mounting is a paired clip with the rider (sharedkillmoves/human&horse/paired_mount.hkx). These are the sizes of the
behaviour each Starfield creature graph must cover.

**2026-10-19, retargeter** (`src/fo4sf/retarget.py`): world-space rotation deltas from each Skyrim bone (relative to its
rest) applied to the mapped Starfield bone's rest; Starfield bone lengths kept; COM movement scaled by the leg-length
ratio (Starfield 0.827 m / Skyrim 0.898 m = 0.921). Conventions verified first: Skyrim .hkx reference-pose FK equals
the Skyrim .nif skeleton joints (median 3e-5 units), and .nif rotation matrices used as stored equal the .hkx
quaternions (max 5e-5). On the 7 real SE clips: every mapped limb segment turns exactly as in Skyrim (angle change
0.0 deg); lowest foot point over the clip, Skyrim vs Starfield: sneak idle -0.009 / -0.025 m, sneak attack intro
-0.003 / -0.036 m, others within 0.013 m (scaling the COM by hip height instead sank feet up to 0.11 m). Starfield's
rest toe sits 0.019 m above the ground (Skyrim 0.001 m). Open: a foot-planting (IK) pass; root motion; WEAPON
placement unverified until a weapon clip plays in game.

**2026-10-19, first .af files from Skyrim clips** (`src/fo4sf/af_writer.py`, `scripts/armor/hkx_to_af.py`):
decode -> retarget -> write .af / .afx / events.json through CALUMI -> read back through CALUMI. CALUMI now also builds
on Linux (`scripts/armor/build_calumi_linux.sh`: clones commit b0f3b5c outside the repo and applies portability edits;
no CALUMI code enters the repo), so the chain runs and is checked here. All 7 real SE clips: written (7 to 60 KB,
115 Starfield bones; the skeleton's one unnamed leaf under Camera is dropped, CALUMI rejects unnamed bones) and read
back within 0.0005 rotation / 0.25 mm translation, except one IK helper key in idlebook_onepage (0.012).
Findings:
* **verified**: a port pitfall, not CALUMI's: GCC resolves bare `abs(float)` to C's `int abs`, which made the encoder
  never drop x / y / z, so rotations over 90 degrees came back clamped near 90 (probe: 120 / 150 / 179 deg about X
  read back as 87 / 89 / 95). With `using std::abs` every probe angle round-trips within 2e-5 (5e-4 on a diagonal axis).
* **verified (encoder behaviour)**: CALUMI drops a quaternion component only if it exceeds 1/sqrt 2, else it drops w;
  when w is near 0 and two components are both about 0.70, rebuilding w loses precision (0.012, about 1.4 deg, the
  idlebook outlier). The format marks which component is missing, so an encoder that drops the largest one would avoid
  it: worth reporting upstream.
* **verified**: rotations are stored as given (not relative to the rig's bind pose): a bone with a 150 deg rest
  animated at 140-170 deg showed the same clamping before the fix.
* For the in-game test, `hkx_to_af.py` saves against the game's own human skeleton.rig (found in Starfield -
  Animations.ba2) so bone indexing matches vanilla clips. Unverified until it plays: how the human graph finds a
  replacement clip (path / .afx tag), root motion, and the WEAPON placement.
* First in-game test path (no graph work): `hkx_to_af.py --osf "Skyrim Port"` writes an OSF Animation content pack
  (clips + a `clipLibrary` catalog, OSF docs/GETTING_STARTED.md), played from OSF's in-game browser on the player or an
  NPC. OSF decodes .af through CALUMI itself, so this tests our clips on a real Starfield actor.

## Weapons: how will a converted bow play its animations? (2026-10-19, open)
Not known yet. What is known:
* Alternate Recoil Animations (Nexus 16838) changed weapon animations by editing "about 400 subgraph data records" in
  xEdit and notes that "weapons using custom animation sets" need patching: Starfield has subgraph data records and
  per-weapon animation sets (**supported**, from the mod page).
* Fallout 4, the same engine line, picks weapon animations through a race's subgraph data: actor keywords + weapon
  keywords (Anims* on the WEAP) -> the folders the behaviour graph plays clips from. New weapon types there needed a new
  keyword + subgraph entries + clips, no graph edits (**supported hypothesis** for Starfield).
* Plan for a bow, in three layers: (1) selection: a WEAP with a bow animation keyword and subgraph data pointing at a
  folder of converted Skyrim bow clips, saved under the tags (`.afx`) of the Starfield weapon type it borrows; (2)
  states: first version maps Skyrim draw -> Starfield aim / ready, release -> fire, nock -> reload (no graph edits);
  true hold-to-draw with draw-time damage needs new graph states (the patcher) or SFSE; (3) gameplay: AMMO / PROJ
  records for arrows (gravity-arc projectile, pickup), WEAP stats.
* `scripts/armor/weapon_anim_survey.py` finds the subgraph records by content (record type not assumed), the
  animation keywords on weapons, full weapon records and HumanRace's animation fields; with sf_anim_survey.py (the
  .afx tags in each weapon folder) that settles layer (1).

### 2026-10-19: owner's surveys of the installed game (sf_anim_survey, weapon_anim_survey, hkx_survey)
**Starfield (verified from the owner's report + 38 vanilla graphs, 60 descriptors, 4 rigs it zipped):**
* 39,398 animation-system files: 19,358 .af, 19,303 .afx, 390 .rig, 347 .agx (all 347 text graphs readable).
* .agx format settled: a state machine's default state is `<default_state>True</default_state>`, the first line of its
  `<node>`, unindented (75 machines; not always node 0); Start Selection Method Default / Sync (iSync* variable) /
  Variable; conditions use `=`, `!=`, `!greaterthan!`, `!greaterthan!=`, `!lessthan!`, `!lessthan!=`, `!ampersand!`,
  `|` and parentheses; vanilla nodes without flags have no `<flags>`; flags seen: Animation Driven, Allow Rotation,
  Turn Animation, Is Attack Not Ready, Equip Not OK, Is Busy, Disable Foot IK, Block POV Switch. agx_write now writes
  all of this. Node types in the 38: ANIMATION 163, GRAPH_REF 100, SWITCH 85, ASSIGN_VARIABLE 71, STATE_MACHINE 60,
  BLEND_TREE 48, MERGE 37, BLEND 25, ANIMATION_IMPACT_SELECTOR 25 (directional hit / death picks), then SET_ORIENT,
  DYNAMIC_ANIMATION, PHYSICS_CONTACT_LISTENER, BONE_CONSTRAINT, PAIRED_ANIMATION, TWO_BONE_IK, FOOT_IK, RAGDOLL_GET_UP...
* Human_Root.agx is a blend tree (deaths, paired kills, foot IK, ActorStateController, a SWAP_GRAPH node); NPC_Melee /
  Player_Melee / NPC_Gun / Player_Gun are the weapon graphs the race's subgraph data swaps in (supported: the swap
  node + SGNM).
* Melee: NPC_MeleeAttacks is one machine: events MeleeAttack01..05, MeleeAttackPower01 / 02, MeleeAttackSprintStart ->
  clips tagged the same (MeleeAttackSprint for the sprint one); MeleeActions: BlockStart / BlockStop (tag
  MeleeBlock_Out), Equip / Unequip, ThrowGrenade / ThrowMine, and casting: **CastSelfStart / CastTargetStart -> tags
  CastSelf / CastTarget** (also in GunActions, 1stPerson_MeleeActions, creature graphs): Starfield already has a
  self / target cast slot. Tags are altered by switches: Prefix Relaxed / Ready / Sneak / Alert (iSyncRelaxReadySneak),
  Gravity / ZeroGravity (iSyncGravity), Swimming; Suffix Idle / Walk / Run (iSyncIdleWalkRun).
* Subgraph data (HumanRace, 158 entries): one-handed melee = target keyword **AnimOneHanded -> NPC_Melee.agx, folders
  Actors\Human\Animations\Melee > melee\common > common**; unarmed per archetype (macho, angry, female...); AnimSword
  is on 2 weapons, WeaponTypeMelee1H on 11. No bow / draw clips anywhere (0 hits).
* Vanilla human rig (meshes\actors\human\characterassets\skeleton.rig): 97 bones, 82 animated, Root first; same rest
  pose as the skeleton NIF for every body bone; Weapon sits under C_Chest; C_Waist exists only in the rig.
  hkx_to_af now saves clips in that rig's order and hierarchy (retarget.rehome); two Skyrim clips converted against it
  read back within 6e-4 (rotation) / 0.24 mm.
**Skyrim:** hkx_survey decoded all 1,593 clips in its first 2,000 files (threecomp40 only; 1 XML file skipped); annotation
events: SoundPlay, FootLeft / FootRight, preHitFrame, weaponSwing, HitFrame, arrowAttach / arrowRelease,
MLh_ / MRh_SpellFire_Event, weaponDraw / weaponSheathe ...
**Consequence:** a Skyrim one-handed weapon needs no new graph: convert its clips under Starfield's tags (attack ->
MeleeAttack01..05, power attack -> MeleeAttackPower01 / 02, sprint attack -> MeleeAttackSprint, block -> the
MeleeBlock tags, equip / unequip, Ready_ / Sneak_ variants), put them in our own folder, and give the WEAP a keyword
with a HumanRace subgraph entry naming NPC_Melee / Player_Melee and our folder first (the Alternate Recoil method).
Spells map onto CastSelf / CastTarget the same way. New graphs (the translator) are only for what Starfield lacks:
bow draw / hold / release, horses, two-handed and dual wield sets if their timing differs.

### 2026-10-19: first sword-attack replacement pack (built, not yet seen in game)
Skyrim 1hm_attackright / left / power / sneak attacks -> the player's sword set (melee\onehanded\player\sword:
MeleeAttack_A/B/C, MeleeAttackPower_A, Sneak_*) and the NPC sword set (melee\onehanded\sword: MeleeAttack01-04,
MeleeAttackPower01/02). Each keeps its vanilla .afx (combo window AttackStateNextAttack, HitFrame, PreHitFrame,
WeaponSwing, camera shake, foley, bDontAllow* / bCanComboAttack / bFreeMovement windows), scaled from the vanilla clip's
exact length (read from its .af) to Skyrim's (40 vs 51-79 frames). The Skyrim attack .hkx files carry no annotation
events: Skyrim keeps HitFrame & co. in its behaviour graphs' clip triggers, so the hit timing here is proportional
(supported hypothesis that it lands near the swing; reading the triggers from 1hm_behavior.hkx is the precise fix).
No root motion yet (vanilla attacks step forward via the header translation). Descriptors are now written without
self-closing empty elements, as shipped.

### 2026-10-19: owner, --free-movement: standing combos start moving, but slowly (inch, walk, jog, run) or not at all
* Graphs read (owner extract): BoneWeights picks UpperBody / Spine / ZeroG masks; Player_Melee's Copy Bone Weights
  takes them only through its "Walking, Turning" and "Jumping" inputs (control variable BoneWeightsAction, set by
  no graph: the game); Biped_IdleLocomotion is momentum-driven (Momentum Move Stop / Switchback nodes; StandToWalk /
  StandToRun entered on CurrentSpeed vs Speed thresholds). Supported hypothesis: a swing started standing is layered
  full body (legs and root from the swing), so locomotion barely accelerates until the walking mask takes over -
  the ramp the owner sees. Vanilla flags Equip / Unequip "Force Copy Bone Weights" (mask even when standing).
* combo_loop.py --upper-body (experiment) sets that flag on the layered combo: legs always from locomotion (instant
  movement), at the cost of Skyrim's step-in on standing swings. Test pack pending; the faithful alternative is a
  per-swing choice (full body when the stick is idle at the swing's start, masked when it is not).

### 2026-10-19: owner, layered combo: moving swings move and steer; standing swings stay standing until the end
* Verified in game (owner): attacking while moving keeps the player moving and lets him change direction during the
  swing; attacking from a standstill plays the whole Skyrim swing (legs included) but holds him in place for the
  combo. Skyrim lets you start moving during any swing. Supported hypothesis: the late vanilla bFreeMovement window
  is what holds a standing swing now that it is layered. combo_loop.py --free-movement (needs --actions-graph,
  experiment) opens it over all of A / B / C; test pack pending.

### 2026-10-19: owner: with bFreeMovement open the player still stops until the swing ends -> layered combo
* Result of the --move-while-attacking experiment (owner, in game): no movement during a full-body swing, whatever
  bFreeMovement says. The experiment switch is removed.
* The owner's SW SFBM mod (Nexus 16022) does let you move: read for the mechanism only (nothing copied), its
  MeleeActions.agx plays MeleeAttack_A / B / C (and Power_A) inside MeleeActions, the graph Player_Melee layers over
  locomotion, and its MeleeAttacks enters the full-body combo only on MeleeAttackStartInAir.
* Graph semantics (supported by every vanilla link): a link whose 1-based source is the target itself is an
  any-state transition - vanilla enters each MeleeActions action that way and returns to IdleTimer with event-less
  links (clip end); MeleeAttacks enters its combo the same way.
* combo_loop.py --actions-graph builds that from the vanilla files: a copy of the (looping) MeleeAttackCombo machine
  becomes action 12 of MeleeActions (any state -> it on MeleeAttackStart, -> IdleTimer at its end), and the vanilla
  full-body combo's entry event is renamed to MeleeAttackStartFullBody (never sent). Expected: legs from Starfield's
  locomotion while moving, the whole Skyrim swing when standing (Copy Bone Weights decides; to be seen in game).
  Power and sprint attacks stay full body; Skyrim's directional power attacks are next.
* Fixed on the way: agx_edit.set_event / set_condition matched links inside an embedded machine too (iter over the
  whole subtree); they now touch only the state's own incoming links.

### 2026-10-19: owner: endless combo works; next, moving / directional attacks as in Skyrim
* Starfield (verified, Player_Melee.agx root blend tree): locomotion (Biped_IdleLocomotion) is the base; MeleeActions
  (block, cast, equip) are LAYERED over it through Copy Bone Weights (BoneWeights graph); MeleeAttacks is reached by
  a Switch "Idle" / "Attacking" (Attacking on the attack events, back to Idle on AttackEnd / ActionInterrupt /
  BlockStart / JumpStart), i.e. attacks are FULL BODY, locomotion off. MeleeAttacks leaves a combo / power / sprint
  attack for "None" on Speed > 1.0 and bFreeMovement, and bFreeMovement is only open late in each clip.
* Skyrim (verified, 1hm_behavior.hkx): each attack is a blend by Direction (BSCyclicBlendTransitionGenerator) of
  forward / right / backward / left blends by SpeedDamped of standing / walk / run clips (1HM_AttackRight,
  1HM_WalkFwdAttackRight, 1HM_RunFwdAttackRight, ... right and left swings each); power attacks pick
  1HM_AttackPowerFwd / Left / Right / Bwd (and ForwardSprint) by direction. All those clips are in the owner's
  extract (sky1h).
* Open question for the game: does the player move during a swing if bFreeMovement is open? combo_loop.py
  --move-while-attacking (experiment) opens it over all of A / B / C and makes the combo -> None-on-moving
  transition impossible. If the player then moves (gliding on the standing clip), the plan is a per-swing blend by
  direction and speed of Skyrim's walk / run attack clips; if not, directional attacks need root motion from the
  clips instead.

### 2026-10-19: vanilla MeleeAttacks.agx (owner extract): endless combo; the leg is Skyrim's own recovery
* Graph links (verified on 42 vanilla graphs): a <link>'s <node> is the source's 1-BASED index among its siblings
  (all 362 state-machine transitions resolve to a real source with a free output slot that way; 0-based fails on a
  third). agx_write wrote 0-based and is fixed (every link in graphs written before pointed one node too low). One
  link per <input>, socket <id>s unique per node. fo4sf.agx_edit edits a shipped graph in place, byte-identical
  elsewhere (ElementTree round trip verified on MeleeAttacks.agx / Player_Melee.agx).
* Combo (verified): MeleeAttackCombo is None -> A, A -> B on MeleeAttackStart, B -> C on MeleeAttackFinisherStart, and
  nothing out of C. Descriptors: A and B open bCanComboAttack, B also bAllowFinisher (frames 15-48), C has no combo
  window and bDontAllowAttack over 50 of its 51-60 frames. scripts/armor/combo_loop.py adds C -> B and B -> C on
  MeleeAttackStart, gives our C (Skyrim's right swing, like A) A's timing and drops bAllowFinisher from B: right,
  left, right, left ... for as long as attack is pressed; Starfield's finisher is dropped (Skyrim has none). The
  graph is shared by every melee weapon type; unarmed keeps its finisher (its descriptors are untouched).
* Skyrim's own timing (verified, 1hm_behavior.hkx clip triggers, hkbClipTrigger = localTime f32 @0, event id @8,
  relativeToEnd u8 @24, 32 bytes): 1HM_AttackRight preHitFrame 0.233 s, weaponSwing 0.333, HitFrame 0.367,
  AttackWinStart 0.867 - AttackWinEnd 1.267 (the combo window), attackStop at the end; the third-person clip starts
  at startTime = attackIntroLength (0.333 default). Not used yet (our hit stays on the blade peak, frames 13-14).
* Leg (verified on the data): the hips turn back 75 deg over frames 22-31 while the left foot stays planted 50 cm
  out, then the foot travels home in the last 8 frames lifted only 5 cm - identical in the Skyrim file. In Skyrim a
  follow-up attack (AttackWin 0.87-1.27 s) cuts that recovery; with the endless combo it shows only after the last
  swing. Changing it would mean editing Skyrim's motion (owner's call).

### 2026-10-19: owner: grip right in combat; left leg slides back with a jolt; only three hits, then it stops
* Root motion: not wanted - the goal is Skyrim's combat, and Skyrim's standing attacks stay in place (owner).
* Leg (verified on the data): every attack starts and ends exactly on the ready idle's foot positions, but Skyrim's
  1hm_attackright itself ends mid-step - its left foot moves 11 cm in the last frame (1hm_attackleft 1 cm) - so the
  foot slides home and stops dead when the clip ends. hkx_to_af --ease-out 8 re-times the last 8 frames of attack
  replacements (vanilla descriptor has a HitFrame) so the clip settles: last-frame step 10 cm -> 2.4 cm, same poses.
* Combo: the player's attacks live in MeleeAttacks.agx (vanilla: 6 nodes, an embedded "MeleeAttackCombo" state
  machine, events MeleeAttackStart / MeleeAttackPowerStart / MeleeAttackSprintStart / ActionInterrupt). Supported
  hypothesis: the combo machine chains A -> B -> C on MeleeAttackStart with no transition out of C, so a fourth press
  does nothing until C ends; Skyrim alternates right / left for as long as attack is pressed. Plan: a replacement graph
  with C -> B added (B is Skyrim's left swing, C its right), needs the vanilla file (owner extract pending).

### 2026-10-19: owner: pop largely fixed; weapon right when drawn, "all weird" once in combat / attacking
* Verified on vanilla clips: every one-handed combat clip (attacks, ready / block idles, equip / unequip, jumps, casts)
  animates R_AnimObject3 (under R_Wrist) exactly on the Weapon bone (within 1 mm / 0.4 deg); relaxed and furniture
  clips do not. We left it out (NOT_ANIMATED), so it sat on the wrist bone. In combat the game holds the weapon on
  R_AnimObject3 (verified in game by the owner: with the track, the sword sits correctly while attacking). hkx_to_af --weapon-in-hand now gives it a track equal to the Weapon bone
  (skeletonmap.WEAPON_FOLLOWERS, retarget.copy_world). Our attack now animates the same bones as vanilla's except Root
  (root motion, still open). WeaponLeft is inconsistent in vanilla (on L_Wrist in some combat clips, in a left grip in
  others) and was left alone.

### 2026-10-19: owner: still pops mid swing, never in TFC (sword now in the fist) -> DirectAt and COM held
* The camera-shake timing was not it. Verified on vanilla clips (ready idle, attacks, chair idle): COM and DirectAt keep
  their rest rotation in character space on every frame (within 0.7 deg); the turn lives in C_Hips / C_Spine. Ours
  turned DirectAt with the chest, up to 100 deg in the sword attack. DirectAt is the Source Bone of NPC_Melee's
  "Dual Direct At" node (aim / look vectors, heading delta, Lag Degrees 20, Disable Heading Min/Max with 10 deg
  hysteresis), which turns chest and head toward the camera's aim: fed a DirectAt swinging 100 deg it fights the swing
  and switches on and off across the heading limits - and TFC gives it no aim (supported hypothesis for the pop).
* retarget.hold_rest_rotation re-expresses the clip so skeletonmap.HOLD_REST_ROTATION (COM, DirectAt) stay at rest
  rotation with the pose unchanged (positions and other rotations identical); C_Waist, never animated, follows.

### 2026-10-19: owner: pop still there, about halfway through the swing, never in TFC; sword still not lined up
* Sword (verified on our output): setting the Weapon bone to Skyrim's orientation turned it a constant 22 deg (30 in the
  block idle) away from the vanilla grip, about its own origin, so the hilt sat beside the fist. Now the weapon always
  sits in the vanilla grip and, with hkx_to_af --weapon-in-hand, the right hand is turned instead so the held blade
  points and faces as Skyrim's does (hand within 0.1 deg of the grip on every frame).
* Pop (supported hypothesis): the clip data cannot depend on the camera, but the hit events can. Our HitFrame /
  CameraShake were vanilla's frames scaled by length, and landed at frame 10 of the sword attack, exactly when the
  Skyrim wind-up pauses (weapon 0.2 m/s) - 4 frames before the real swing (tip peak at frame 13-14). A camera shake
  at the dead point reads as the body hitching, and TFC has no camera shake. Verified on 41 vanilla one-handed
  attacks: HitFrame = the frame of fastest blade-tip travel (within 1 frame in 39, 2-3 in two), PreHitFrame 5 frames
  before. retarget.blade_peak finds that frame in our clip and retime_descriptor now scales piecewise through
  (vanilla HitFrame -> ours), so PreHitFrame, WeaponSwing, CameraShake, swing sounds and windows keep their distance
  to the hit. The source does have a fast whole-body snap at frames 12-14 (COM turns 37 deg in one frame, in the
  decoded Skyrim data too); that is Skyrim's own motion, not a conversion error.

### 2026-10-19: owner: body "pops" during the first swing (not in TFC), sword not where Skyrim has it
* Blade axes (supported): Starfield melee weapons run along the Weapon bone's +Z (the vanilla sword MeleeAttack_A hit
  frame swings +Z forward-left), Skyrim's along +Y (1hm_idle holds +Y forward-up). With the grip, our blade already
  pointed within 8 deg of Skyrim's but was turned ~20 deg about itself; the Weapon bone now takes Skyrim's orientation
  (skeletonmap.WEAPON_AXES: x_sf = -z_sk, y_sf = -x_sk, z_sf = y_sk), the hilt staying at the vanilla grip point.
* The pop: supported hypothesis that it is the jump between Starfield's own ready stance / block idle and the Skyrim
  attack's first and last poses (both played on the same weapon), maybe plus the attack's Allow Rotation turning the
  body to the camera (which TFC would not do). The pack now also replaces the one-handed Ready_Idle (1hm_idle),
  MeleeBlock_Idle (1hm_blockidle), Equip and Unequip (1hm_equip / 1hm_unequip; Skyrim weaponDraw / weaponSheathe
  annotations mapped to WeaponDraw / WeaponSheathe) for player and NPC, so attacks start and end from Skyrim's stance.

### 2026-10-19: attacks in game look stiff, sword not in the fist (owner) -> limbs aligned, vanilla grip
**Owner, in game:** attacks play with a normal camera, but the arms look rigid and the weapon does not line up with
the hand. Measured causes: (1) the two rest poses' limbs differ (upper arms 16 deg, clavicles 37, finger joints 11-46,
hand roll 13.5), and world-delta retargeting carried those offsets into every frame: Skyrim's arm moved, but from a
pose 16 deg off, fingers curled wrong round the hilt; (2) the Weapon bone was placed from Skyrim's WEAPON offset, 16 deg
and 1.7 cm away from where vanilla Starfield holds it. Fixes: retarget.rest_alignment swings each driven Starfield
bone's rest onto the Skyrim bone's rest direction (hands also rolled by the knuckle line; finger tips inherit); arms,
forearms, hands and fingers now point within 0.02 deg of Skyrim's through 1hm_attackright (knuckle line 3 deg, from
proportions). skeletonmap.GRIP puts Weapon in R_Wrist's frame at the offset every vanilla one-handed clip uses
(verified identical in the sword and generic MeleeAttack_A), and the hand IK targets on the hands.

### 2026-10-19: sword pack in game: attacks play, camera tipped over (owner) -> camera bones left out
**Verified in game:** with the sword pack, attacking in third person played our clip but threw the camera into a tilted
view at floor level. Cause (verified from the vanilla clips): vanilla human clips never carry tracks for the camera
bones (Camera, Camera Control, Camera Control FP, CamTargetParent, CameraTarget), the prop slots (AnimObject*,
L_/R_AnimObject*), Eye_Target, L_Arm / R_Arm or C_Waist; Root only for root motion (vanilla attacks move it a few mm per
frame). Our clips wrote all 82, and the NIF's Camera orientation differs from the rig's, so the camera got a rotated
track. skeletonmap.NOT_ANIMATED lists them; hkx_to_af writes no track for them (62 tracks, vanilla attack 64 incl.
Root). Packs rebuilt: every one-handed set (sword, generic, knife; player and NPC; 47 clips) and every chair-family
idle (chair, chair_executive, chairleanback, 13 animflavor idles, female chair; seat-aligned).

### 2026-10-19: first Skyrim clip playing in Starfield (owner, in game)
**Verified in game:** Skyrim's chair_idlearmscrossedvar1, converted by hkx_to_af against the vanilla human rig (rest-
relative keys, 82 animated bones), played on the player through OSF Animation (scene "Skyrim: chair idlearmscrossedvar
1", screenshot): a correct seated pose on thin air: arms crossed over the chest, knees bent at seat height, feet flat
on the ground, head tilted down as in Skyrim; no twisted limbs. So decode -> retarget -> rest-relative .af works
end to end. OSF notes: its released build hides clipLibrary-only packs (unless Show author details), so packs also list
one looping scene per clip, without `unlisted`.

### 2026-10-19: vanilla .af clips compared with ours (owner extracted chair Idle, sword attacks, rigs)
* **verified: .af keys are relative to the rig's rest pose.** Decoded with CALUMI and composed as local = rest * key
  (rotation), rest + key (translation), the vanilla chair Idle is a seated human (hips 0.67 m, ankles 0.12 m, head 1.24
  m, knees forward) and the sword MeleeAttack_A a standing one (hips 0.96 m); read as absolute locals the hips land
  below the floor, and key * rest bends the knees backwards. CALUMI stores and returns keys as given, so our writer
  converted nothing: every clip written before this (incl. the first OSF test pack) carried absolute locals and would
  play rest-on-rest in game. af_writer.write now stores rest-relative keys (rest_relative); read_back composes them back
  (absolute=True). Our Skyrim chair idle, decoded the game's way, sits at hips 0.662 m vs vanilla 0.671 m, ankles
  0.113 vs 0.126 m, head 1.231 vs 1.243 m: the retarget lands on Starfield's seat height.
* **verified:** vanilla clips declare only the rig's 82 Default-type bones in their header (0x2A: u16 version 5, bone
  count, frame count, index-atlas count); the 15 Twist bones (listed last in the rig) are procedural. CALUMI sizes the
  table from the whole rig it saves against (97), so hkx_to_af now saves against a copy holding the 82 animated bones
  (af_writer.rig_prefix: names, parents, rest, rig-package keys, mannequin flag and translation precision copied) and
  writes no twist tracks. Read-back against the full game rig: 6e-4 rotation, 0.25 mm translation.
* The header also carries a translation: 1.85 m forward on the player's MeleeAttack_A, zero on the chair Idle: the
  clip's root motion (supported hypothesis; root motion is still an open item for us).
* Male and female human rigs list the same 97 bones; rest positions differ by up to 2 cm: female clips are converted
  against the female rig and BodySlide's female skeleton.
* Furniture: `--align-com` moves a replacement clip horizontally so its mean COM sits on the vanilla clip's (the
  Skyrim chair idle sat 9 / 13 cm further forward than the male / female vanilla idles).

### 2026-10-19: what SW SFBM Vanilla Blocking Fix (Nexus 16022, owner upload) shows (verified from its files)
* **`.agx` graphs are plain XML text** (Bethesda graph-editor export): nodes typed NT_ANIMATION_NODE (TagName, State
  Variable, Speed Multiplier = WeaponSpeedMult, crop frames, mirror), NT_SWITCH_NODE (variable, Tag Alteration
  Prefix / Suffix), NT_BLEND_NODE, NT_GRAPH_REF (another graph by name), state machines / blend trees, bone constraints,
  a stagger meter; links carry Event, Condition (text expressions such as `bDontAllowBlock=0`,
  `Speed !greaterthan! 1.0 !ampersand! bFreeMovement !greaterthan! 0`), blend time, transition type. The mod ships edited
  copies of four vanilla graphs (Player_Melee, MeleeActions, MeleeAttacks, HitReactions) as loose files: graph edits
  are loose-file overrides, and a patcher is an XML merge. Reader: `src/fo4sf/agx.py`.
* Player_Melee is assembled from 14 referenced graphs (MeleeActions, MeleeAttacks, Jumping, Ladder, Mantling, GravDash,
  Stagger, Biped_IdleLocomotion, ...); variants are switches with tag alterations: Gravity / ZeroGravity, Relaxed /
  Ready / Sneak (prefix), swimming (iSyncSwimState: Starfield has a swim state), hit direction (suffix).
* Variants keep the base tag in their `.afx` and carry the prefix in the file name: Sneak_MeleeAttack_A.af and
  ZeroG_MeleeAttack_A.af sit beside MeleeAttack_A.af, all tagged MeleeAttack_A.
* Folders per weapon: melee\onehanded\player\{,knife\,sword\,sword\twohandblock\}; the mod overrides the same tags at
  several levels (supported: most specific folder first, from the equipped weapon's subgraph data).
* MeleeActions already has **CastSelf / CastTarget** animation nodes (events CastSelfStart / CastTargetStart),
  ThrowGrenade / ThrowMine, Equip / Unequip, and **melee blocking** (BlockStart / BlockStop -> MeleeBlock_Into / _Idle
  (is_state 1, the loop) / _Out / _HitReaction): hooks for Skyrim casting and blocking exist in vanilla.
* `.afx` events per frame use Skyrim's names: PreHitFrame, WeaponSwing, HitFrame, FootLeft, FootRight (plus
  AttackStateNextAttack, AttackEnd, AssignVariable with payloads, CameraShake), and variable windows (bDontAllowBlock,
  bDontAllowAttack, bFreeMovement, bCanComboAttack, bAllowFinisher, bNoLeftHandIK ...). af_writer now writes the
  mapped Skyrim annotations into the .afx (others stay in <clip>.events.json); rampout = blend-out frames.

## Creatures: lessons from TES4 AutoConvert (2026-10-19)
Read from its design notes (github.com/bryantmh/tes4skyrim, docs/commentary/asset_convert_creature.md,
docs/plans/horse_rideability.md, docs/reference/creature_race_equivalence.md; read only, no code taken). Its creature
port (Oblivion / Morrowind / FNV -> Skyrim) is live end to end. What carries over:
* **Gap table per layer first**: record, skeleton, body mesh, animation, animation selection, movement / combat data.
  Theirs found one layer with no source (Oblivion has no behaviour graphs: selection is hard-coded by file name).
  Ours differs: both Skyrim and Starfield have graphs, so the question is translate vs. generate vs. borrow.
* **Enumerate the engine <-> graph interface from vanilla graphs before writing any**: events the engine sends
  (their list for Skyrim: moveStart / moveStop, turnLeft, weaponDraw, attackStart_<Name>, staggerStart, deathStart,
  ...), variables it drives (Speed, Direction, TurnDelta, iCombatStance, bAnimationDriven, ...), events the graph must
  emit (preHitFrame, HitFrame, SoundPlay, FootFront / FootBack, attackStop). Records must match the graph (their RACE
  attack events ATKE = graph events; generated on both sides so they agree by construction).
  Done here: sf_anim_survey.py now summarises every text .agx (events, variables, tags, graph refs, tag alterations).
* **Generate from a template, don't hand-pick donors, for anything that must work for any mod**: they rejected donor
  graphs because each hard-codes its species' clip set and needs per-creature hand mapping; they generate one graph
  per creature from a template keyed on the clip inventory, and keep donors only as **development scaffolding** (put
  the converted creature on a vanilla graph to test skeleton / mesh / clips in game before the generator exists).
* **Clip claiming tables**: map each source clip to a role (forward, run, attack, stagger, death, swim, block,
  equip ...) by name, with a fallback on the clip's internal name; a missing role leaves the actor sliding.
* **Movement speed lives in records** (their MOVT speeds are baked from each clip's root motion); root motion and
  per-clip events are sidecar data the generator writes.
* **Per-layer A/B bisection**: point a converted race at vanilla assets to tell record faults from graph faults.
* Death / ragdoll physics and the spell-casting handshake were each large separate efforts; horse riding is a plan
  there (unimplemented): a "Ridden" state added to the horse graph plus the rider-side vanilla assets.
For us, by creature class:
* quadrupeds and bipeds (wolf, bear, horse, troll, draugr ...): template generation in Starfield's .agx, keyed on
  Skyrim's clip inventory (behavior_inventory.py) and the Starfield interface (the survey); scaffold first on the
  closest Starfield creature graph.
* Skyrim's own graphs can also be **translated** (hkbStateMachine / hkbClipGenerator / hkbBlenderGenerator /
  transitions with events -> .agx state machines / animation nodes / blend nodes / links with events), which keeps
  modded behaviours too, but Bethesda modifiers without a Starfield node (BSTweener, BSLimbIK, ...) need substitutes.
* dragons: flight needs engine support for flying actors (Skyrim's engine has a fly movement type and flight AI);
  whether Starfield has any flying creature and movement type is unverified and is the first thing to check.

**2026-10-19, foot planting** (`retarget.plant_feet`, on by default in hkx_to_af.py, `--no-foot-plant` to skip): a
two-bone IK per leg puts each Starfield ankle as far above its rest height as Skyrim's ankle is above its own (scaled
by the leg-length ratio); ankle x / y, knee bend plane and foot world rotation are kept. On the 7 real clips the foot
contact gap went from up to -0.052 m (sneak attack intro) to at most -0.006 m; ankles reach their targets within
0.0004 m; leg segments now differ from Skyrim's directions by 2-5.5 deg (the re-bent knees), arms unchanged.
Owner note: Starfield has many flying creatures (bird-like aliens), none as complex as dragons; a flier's graph and
movement type are the candidate scaffold for dragon flight.

**2026-10-19, Skyrim behaviour graphs read, first translation to .agx** (offline, Pandora's vanilla templates):
* `src/fo4sf/skyrimbehavior.py` reads hkbBehaviorGraph files: state machines, states, transitions (event, target,
  condition expression, effect), clips (animation path, speed, crop), blends, variable bindings (member -> variable,
  e.g. BSSpeedSamplerModifier goalSpeed = Speed), events / variables. Field offsets worked out from the data (pointer
  fixups say which field points at what); self-checks: on all 114 vanilla behaviour files, 3,212 state machines /
  8,836 states / 7,470 transitions / 8,865 clips, **0 failures** (every transition targets a state of its own machine,
  every event id in range, every clip an .hkx). Pandora's copies carry 8 extra bytes per object (detected per file).
  `scripts/armor/behavior_dump.py` writes a readable tree + JSON per graph.
* The .agx state-machine form (from the SFBM graphs): a state machine is a <graph> whose nodes are its states
  (NT_ANIMATION_NODE with TagName, TagName None = empty state, NT_STATE_MACHINE_EMBEDDED with a nested <graph>); a
  transition is a <link> on the target's input naming the source node and one of its output slots, with Event,
  Condition, Blend Time, Priority, Transition Type; the graph's sheet sets the start selection (Default / Variable).
  Node flags are state behaviours (Animation Driven, Blocking, Block POV Switch, Is Attack Not Ready, ...).
  How the default state is marked is not visible in the shipped files (unverified; the writer puts it first).
* `src/fo4sf/agx_write.py` writes that form; `src/fo4sf/behavior_to_agx.py` translates a Skyrim state machine:
  states / nested machines / clips / transitions / conditions (Skyrim `<`, `>`, `&&`, `||` -> `!lessthan!`,
  `!greaterthan!`, `!ampersand!`, `|`; `!lessthan!` by analogy) / blend times (hkbBlendingTransitionEffect duration
  @80; 0.2 s default); wildcard transitions become links from every other state. Prototype runs: horse DefaultBehavior
  (20 states, 24 transitions, 8 machines, all carried; 3 blend states left empty), horse root (mount / dismount /
  swim / ragdoll states, 34 transitions), dragon BHR_Flight and BHR_Hover (all states and transitions; the cruise
  flap / glide / feather and hover turns sit inside blends). Not translated yet: blends and their variables,
  modifiers (look-at, foot IK, ragdoll, timers, expressions), clip triggers, nested-state transitions.
* Dragon graph shape (behavior_dump): master -> ground / take-off / flight (cruise: feather, flap, glide) / hover /
  nine landing kinds (default, vertical, injured, hasty, crash, perches), shouts layered on a neck machine; engine
  events TakeOff, HoverStart, FlyStop*, FlightCruising ...; variables Pitch, Speed, TargetSpeed, TurnDelta, ...

**2026-10-19, blends translated; CALUMI Motion** (offline):
* CALUMI.Motion (github.com/Calaverah/CALUMI.Motion, LGPL, Nexus 16181: a visual .agx editor; read for format
  knowledge only) lists 60 Starfield graph node types. Skyrim classes with a Starfield counterpart: blender ->
  NT_BLEND_NODE, cyclic / locomotion blends -> NT_LOCOMOTION_BLEND, manual selector -> NT_SWITCH_NODE, synchronized
  (paired) clips -> NT_PAIRED_ANIMATION, look-at -> NT_DIRECT_AT / NT_DUAL_DIRECT_AT, foot IK -> NT_FOOT_IK /
  NT_MULTI_FOOT_IK, ragdoll drive / get-up -> NT_RAGDOLL_DRIVE / NT_RAGDOLL_GET_UP, timer -> NT_TIMER_EVENT,
  every-N-events -> NT_EVERY_N_EVENTS_MODIFIER, state tagging -> NT_ASSIGN_ISTATE; also NT_CURVED_PATH_BLENDER,
  NT_TWO_BONE_IK, NT_RANDOM_ANIMATION_NODE, NT_EVALUATE_CONDITION_VARIABLE (supported: names; semantics unverified).
* Blend format (shipped files + CALUMI.Motion): NT_BLEND_NODE has <divisions> and one <blendInput> per input
  (`<point><Range>r</Range><Weight>w</Weight></point>` rows; empty in the shipped graphs), named inputs fed by data
  links (no property sheet), output "Out"; rows Name, Variable Name, Variable Type (Standard 0 / Parametric 1 /
  Layer 2), Sync Variable, Input Lock Time, Range Min / Max, Wrap To Range, Max Blend Time, Normalize Weights, Only
  Highest Weight Active. NT_SWITCH_NODE: Variable Type (Event 0 / Variable 1 / Event and Variable 2), Tag Alteration
  (Do Nothing 0 / Prefix 1 / Suffix 2). A blend tree (NT_BLEND_TREE_EMBEDDED, or a whole graph like Player_Melee) is a
  data-flow graph whose node 0 is its output (the only node nothing consumes, in all three shipped trees). Graphs carry
  a second sheet listing their states' names (supported: the names a start / sync variable selects by).
* Translator: Skyrim blenders -> blend trees (variable = the one bound to blendParameter, one triangle curve per
  child = the blender's linear interpolation), selectors -> switches on the bound variable, behaviour references ->
  NT_GRAPH_REF, anything used from more than one place -> its own graph file + NT_GRAPH_REF (no in-file instancing;
  copying blew the dragon up to 742 machines). Results: dragon -> 61 graphs, 1.5 MB, 218 states / 66 machines (= the
  source), 217 clip states, 29 blends, 6 switches, 77 shared-part refs, 2 pose-matching states left empty, 118
  modifiers not translated; horse -> 13 graphs; wolf -> a reference to QuadrupedBehavior (16 graphs, which itself
  references NonCombatIdle and ForwardLocomotion). CLI: scripts/armor/behavior_to_agx.py.
* Still not translated: modifiers (look-at, foot IK, ragdoll, timers, expressions, event-driven), pose matching,
  cyclic blend transitions, clip triggers. Unverified in game: everything about how the engine loads these.

### 2026-10-19: Alternate Recoil Animations (Nexus 16838) and CP's Menagerie (Nexus 7783), owner uploads (verified from their files)
* **How a weapon gets its animations (layer 1 of the bow plan): RACE subgraph data.** The mod's plugin carries a full
  HumanRace (ARA_HumanRace) with 400 entries: SAKD actor keywords, STKD target (weapon) keywords, SGNM graph
  (1stPerson_Gun.agx, 1stPerson_Gun_ZeroG_Wrapping.agx), SAPT animation folders MOST SPECIFIC FIRST (the mod's
  `_AlternateRecoilAnimations\Rifle\Medium\Rank0`, then gun\gripcompact\grendel, gun\gripcompact, gun\common, common),
  SRAF 01 00 01 00 (every entry). STKD comes before SGNM in some entries, after the SAPT list in others; SRAF ends each
  entry. The race also names, per sex, skeleton (ANAM), rig (NAM5), root graph (NAM6 Human_Root.agx) and default
  folder (DNAM actors\human\animations\common). Reader / writer: `src/fo4sf/subgraph.py`; weapon_anim_survey.py now
  lists every HumanRace entry with keyword names. A bow = a WEAP keyword + an entry with it in STKD, a graph, and its
  own folder first in SAPT.
* Weapon clip folders: _1stperson\animations\gun\<grip type>\<weapon>\ (gripextendedlow\dreambeam, grippistol\
  solstice ...); clips override vanilla files at the same path; .afx where the tag needs one (FireAutoPush).
* **Animation caches (AnimTextData), the Starfield counterpart of Skyrim's animationdata**: the Terran Armada archive
  ships 2,760 files in meshes\animtextdata\{animationfiledata, animationoffsets, animationstancedata,
  dynamicidledata}\<64-bit number>.txt (909 sets; the same number in each family) plus
  animationoffsets\persistantsubgraphinfoandoffsetdata.txt (a list of the set files). AnimationFileData: "3", "1",
  the number, a count, then the resolved clip (and graph) paths; AnimationOffsets "V5": per graph, tag -> clip path,
  binary root-motion keys and foot events (FootLeft / FootRight); AnimationStanceData: bone transforms
  (AnimationTransformedBoneArray); DynamicIdleData "Version 1": idle clip list. Adding folders / clips means these
  caches change (the mod regenerated 909 sets, creatures included). The number is unidentified: paired sets
  (1stPerson_Gun vs its ZeroG wrapping) differ by exactly 1,429,745,511 every time (suggests a sum of per-part
  hashes); FNV-1 / FNV-1a / CRC-64 (three polynomials) sums over graph + folders, raw or lower case: no match.
  Unresolved: how to generate them ourselves (the Creation Kit presumably regenerates them).
* CP's Menagerie: no race or animation records; ARMA skins (new .nif) on vanilla creature races (ashta-style
  skeletons), applied to vanilla NPC_ records: a new creature body on an existing creature skeleton and graph works.
  That is the scaffold route for the first Skyrim creature test.
* CALUMI.Motion (Windows build, owner upload): to open translated .agx files on the PC as a validity check.

## Physics for hair / capes / clothes (FSMP-style), planning note (2026-10-19)
Owner question: keep Skyrim HDT-SMP / FSMP physics for ported hair and armour; Starfield's own physics looks less
fluid. What exists (Nexus pages, not verified in files): Starfield has native Havok cloth in NIFs
(BSClothExtraData); Nexus 14491 is a Blender add-on exporting it through the official art tools (FBXImporter /
MeshConverter forks), used by physics hair ports (Nexus 14496 "Hairs and wigs with physics", 18427 BDO hairs);
authors call it experimental and setups hard. No SMP-like SFSE plugin was found.
Routes:
* A. translate SMP XML (bones, constraints, collision shapes, per-vertex shapes) into native BSClothExtraData:
  no runtime plugin, engine-supported, but needs the Havok cloth authoring path (art tools) and may stay less fluid.
* B. an SFSE physics plugin reading the SMP XML at run time (own solver or a permissively licensed library), writing
  bone transforms every frame: closest to FSMP, but C++ hooks into Starfield's skeleton update, built blind here and
  compiled by the owner; reimplement from the XML format and observed behaviour, not from FSMP / HDT-SMP code.
* C. first step either way: bone-chain physics (springs on hair / cape / skirt bone chains) covers most of the
  "flowy" look and is the smallest piece; per-vertex / per-triangle shapes come later.
Prerequisites in this plan: armour / hair meshes keep their extra physics bones when converted (skinned to bones the
mesh carries, not only skeletonmap's human bones), and a survey of real SMP XML configs (how many use bone chains
only vs per-vertex shapes) decides A vs B.

### SMP config survey (2026-10-19, `scripts/armor/smp_survey.py`, `src/fo4sf/smpconfig.py`)
Run on owner uploads KS Hairdos SMP (Nexus SSE 31300) and Cloaks of Skyrim Retextured HDT-SMP; format notes from
the files and from FSMP 4.1.1's schema `FSMPV/hdtSMP64.xsd` (MIT, DaymareOn). No FSMP code read (GPL).
* **verified (files):** a worn NIF names its config in an NiStringExtraData "HDT Skinned Mesh Physics Object" (value
  = Data-relative path, sometimes with a `Data\` prefix). 100 configs, 675 NIF -> config links, none missing.
* **verified:** 99 of 100 configs are bone chains: kinematic anchor bones the mesh carries (`Zoella Flyaways L 1`,
  `CB 01 1`) parented to one skeleton bone (hair: NPC Head -> Starfield C_Head, 503 links; cloaks: NPC Spine2 ->
  C_Chest, 1158), then 2-7 simulated bones each (max 38 per config, 689 total), linked only by
  `generic-constraint` (6-DOF spring: small angular limits, e.g. +-0.1..0.5 rad; angular stiffness 0 in 55 configs,
  1-500 in the rest). No loops / nets, no stiffspring or conetwist, no motors, no bone primitive shapes, no
  patterns. 2 configs have a simulated bone outside any constraint.
* **verified:** collision is mesh-based: per-vertex-shape on the hair mesh itself (94 configs) against
  per-triangle-shape "Virtual*" meshes (VirtualHead, VirtualBody, VirtualGround ...; 99 configs). In most hair NIFs
  those Virtual* meshes are absent (VirtualHead named but missing in 459 links); KS ships them in a separate
  VirtualCollision NIF / config, and body mods supply their own (supported hypothesis: SMP matches shapes across
  meshes on one skeleton by tag).
* Numbers may use comma decimals ("0,1"); the schema says the runtime accepts both.
* unresolved: whether an unnamed `*-default` redefinition replaces or merges into the previous one (the reader
  replaces); how a bone with no constraint behaves.

Consequence for the routes: SMP content here is exactly "C" (bone chains hanging off one skeleton bone) plus
coarse body collision. Starfield's cloth is particle based, and the add-on page (Nexus 14491) says "Cloth Bones
naturally drive part of the mesh that is weighted to them", i.e. Havok cloth particles can drive bones. So route A
becomes a direct mapping (supported hypothesis until a Starfield cloth NIF is decoded):
| SMP | Havok cloth in BSClothExtraData |
|---|---|
| kinematic anchor bone (mass 0) | fixed particle skinned to the animated bone |
| simulated bone (mass > 0) | simulated particle, mass; bone transform read back from particles |
| generic-constraint bodyA-bodyB | stand (distance) link; angular limits / stiffness -> bend link or local-range constraint toward the animated pose |
| bone linear / angular damping | particle damping |
| per-triangle Virtual* body shapes | capsules / spheres on body bones (head, spine, arms, legs) |
| per-vertex hair shape | particle radius |
Route B (SFSE solver) stays the fallback if cloth bones cannot be produced outside the art tools or feel too stiff.
Next: decode a Starfield NIF with BSClothExtraData with `fo4sf.hktagfile` (the payload should be a Havok tagfile;
unverified) to list the hcl* classes, particles and constraints it holds; the converted mesh must keep its chain
bones (`extra_bones` in the survey) under the mapped host bone.

### Starfield cloth decoded (2026-10-19, `src/fo4sf/sfcloth.py`, `scripts/armor/sf_cloth_survey.py`)
Owner uploads: OC Hairs (Nexus 14496), OC Agent outfit (14478), Eris Hairstyles (16118, inside its BA2). 59 cloth
setups, all decoded with the new generic value reader in `fo4sf.hktagfile` (`Tagfile.root()`).
* **verified:** BSClothExtraData = u32 size + Havok tagfile (TAG0, SDK 20190200); a loose .hkx beside the OC NIFs is
  the same bytes. Root objects: hclClothData + hkaSkeleton.
* **verified: every one of the 59 is bone-driving cloth** (hair, a dress and a jacket alike), the same operator
  chain: skin the hidden sim mesh to the host / chain bones (hclObjectSpaceSkinPNOperator or
  hclBoneSpaceSkinPNOperator) -> hclMoveParticlesOperator (pinned particles follow their skinned vertices) ->
  hclSimulateOperator -> hclSimpleMeshBoneDeformOperator (each driven bone follows one sim triangle;
  boneOffset = 64 x bone index, triangleOffset = 6 x triangle index). The visible mesh is plain skinning.
* **verified:** the NIF holds no nodes for the extra bones: SkinAttach names them (bone refs -1) and the cloth's
  hkaSkeleton is the human skeleton with the extra bones inserted under their host (OC ponytail: 36 bones under
  C_Head, chains up to 17 deep; Eris: Hair_<strand>_<n> under C_Head; dress: 114 under C_Hips; jacket: 135 under
  C_Chest). Supported hypothesis: the engine creates the extra bones from the cloth skeleton.
* **verified:** Eris reuses one cloth rig for several styles (one identical payload in 20 NIFs = 5 hairstyles x
  m/f x facebones): the visible mesh changes, the rig does not.
* Constraint sets seen: StandardLink (59), StretchLink (59), BendStiffness (56), LocalRange (44), BonePlanes (24),
  Volume (5). Colliders: convex geometry (head / torso, 55), capsules (biceps, thighs, calves, 46), spheres (8),
  plane (1), each on a skeleton bone. Units metres, gravity -9.81 z, damping 0.8-0.96 per second.

What an SMP hair / cloak conversion has to produce (plan; route A confirmed as the engine's own mechanism):
1. Visible mesh skinned (SkinAttach names) to the host bone + the chain bones; chain bones renamed if needed.
2. BSClothExtraData: hkaSkeleton = Starfield human skeleton + the SMP chain bones under the mapped host
   (`chain_anchors` in smp_survey: NPC Head -> C_Head, NPC Spine2 -> C_Chest), and hclClothData with the operator
   chain above. SMP -> Havok cloth: kinematic anchor -> pinned particles; each simulated bone -> a sim triangle
   that drives it; generic-constraint links -> StandardLink / StretchLink; angular limits -> LocalRange or
   BonePlanes (distance from the animated pose); angular stiffness -> BendStiffness; Virtual* body meshes ->
   convex head / torso and limb capsules.
Two ways in, cheapest first:
* rig reuse: weight the converted hair onto an existing Starfield cloth rig (as Eris does) and copy that rig's
  BSClothExtraData unchanged at conversion time from the user's own files. No cloth writer; a quick in-game test.
* per-chain cloth: generate the sim ribbon and constraint sets from the SMP config and write the tagfile, using a
  cloth NIF's TYPE section as the template at run time (as meshcollision does for collision).
**Vanilla (owner run 2026-10-19, `--filter hair,clothes,outfit`): 394 cloth setups, 0 errors, all bone-driving**
(404 hclSimpleMeshBoneDeformOperator). Vanilla hairs carry their own rigs (bob: 12 bones under C_Head, 29
particles; choppy_bob: 72 bones; coily_mohawk: 2; the child ponytail: 5 in one chain), and so do suits, capes
(Varuun administrator cape: 138 bones on C_Chest / L_Clavicle), banners, scarves and helmets. Classes beyond the mods:
hclCopyVerticesOperator (241), hclCompressibleLinkConstraintSetMx (52), hclVolumeConstraint (6),
hclTaperedCapsuleShape colliders (108). So vanilla hairs are rig-reuse candidates and writer templates.
Vanilla hair rigs (female variants, 20): tousled_bob 76 bones / depth 7, choppy_bob and short_loc 72 / 7, messy_bob 49,
back_buzz 46, receding_wizard 44, messy_mullet 39, shaggy 36, straight_bob 28, viking_braids 28, unkempt 27,
hollywood_curls 22, cropped_bang 19, bob 12, whitney_curls 12, child ponytail_hairmesh 5 (one chain, 12 particles: the
smallest writer template), hairspray_bob 4, spiked 3, coily_mohawk 2, top_bun 2. The long, layered rigs use BonePlanes +
LocalRange (pose-keeping, like SMP's angular limits) besides links and bend stiffness.
