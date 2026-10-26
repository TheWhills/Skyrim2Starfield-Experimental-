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

### 2026-10-19: owner, --no-pivot: worse - no moving off from a standing combo, and a forward run keeps going after release
* Result (owner, in game): with the pivot flags and the bAlignWithAimAssistTarget / DisableAllowRotation windows gone,
  a standing combo never starts moving, and attacking while running forward keeps the player running after the stick
  is released. So those controls take part in Starfield's movement control during a swing; --no-pivot is a dead end
  (kept only as a recorded experiment, not for packs).
* Where it stands: plain layered combo (v9): moving swings move and steer, standing swings are Skyrim's whole swing
  and hold the player until the combo ends - consistent and predictable. --free-movement: standing combos can start
  moving, but with a slow ramp. --free-movement --upper-body: instant start, but only straight and with lucky timing;
  standing swings lose the leg work. Moving off in the middle of a standing swing is decided by the game's movement
  code, not by anything in the graphs read so far.
* Owner, --free-movement --upper-body: the same latch - while attacks continue, the player keeps moving in the last
  pushed direction after the stick is released (a new direction re-latches), instead of swinging in place. Both
  experiments are out; v9 (plain layered combo) is the candidate baseline, pending the same release check on it.
* Owner: v9 latches too - keep attacking and you keep moving in the last pushed direction (a new direction
  re-latches, from walking pace). So the layered approach itself does it. Read 2026-10-19: vanilla combo states send
  AttackStart on enter and AttackStop on exit; the SFBM mod's layered A / B / C send neither, and vanilla's own
  layered MeleeAttackInAir_A sends only AttackStart. Supported hypothesis: AttackStart switches the game's movement
  into its attacking mode, which holds the last input. combo_loop.py --no-attack-events (experiment) removes both
  from the layered copy; test pack pending. Risk: anything else the game hangs on AttackStart (hit setup, stamina).
* Owner: --no-attack-events latches the same. The SFBM mod's descriptors (read) differ more: AttackEnd at frame 0 of
  every layered swing (vanilla's end-of-attack event: Player_Melee's Switch returns to Idle on it, MeleeAttacks'
  None sends it on enter), attacks locked by bDontAllowAttack (0-25) instead of a bCanComboAttack window, no Allow
  Rotation flag, no aim / rotation windows, bNoHeadTrack throughout. Supported hypothesis: ending the game's attack
  state at once is what frees the movement input. combo_loop.py --attack-end-at-start (experiment) adds AttackEnd at
  frame 0 and holds bDontAllowAttack to each swing's AttackStateNextAttack frame; test pack pending.
* Owner, --attack-end-at-start: the latch now ends after a few swings, but combat still feels locked: the combo
  stays in whatever mode it started in (moving or standing). Parked here: what holds movement during a swing is the
  game's code (attack state, movement input), and graph / descriptor edits only nudge it. Next options: settle on a
  build and move on, or a native (SFSE) look at the player's attack-movement code.

### 2026-10-19: owner, --upper-body: moving off mid-combo is instant, but only sometimes and only straight ahead
* Biped_IdleLocomotion (read): the Locomotion machine leaves its idle "None" for StandToWalk / StandToRun start
  clips on CurrentSpeed / Speed thresholds and for Biped_Locomotion at CurrentSpeed >= 0.1; the start clips turn the
  body with the move (Set Orient "Turn Animation Modify Translation", active on bPlayerMoveStartActive). The idle /
  locomotion switch itself is iSyncIdleLocomotion, set by the game.
* Supported hypothesis: the swing's facing controls fight that turn - "Should Pivot to Camera" on the combo and on A,
  bAlignWithAimAssistTarget early and DisableAllowRotation late in each swing - so only a straight start (no turn)
  gets through, and only outside those windows. combo_loop.py --no-pivot (experiment) clears the flags on the
  layered copy and drops the two windows. Cost if it helps: swings no longer snap toward the camera / aim target.

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

### 2026-10-19: BFCO windows and routing (steps 2 and 3)
* BFCO markers (read on its 1hm / 2hm / h2h base movesets): BFCO_NextIsAttackN / NextIsPowerAttackN at 0 s route the
  next press (1hm-sword-base: 1 -> 2 -> 3 -> 4 -> 5 -> 2, endless), BFCO_NextWinStart / NextPowerWinStart open the next
  attack, BFCO_DIY_EndLoop (or MCO_WinClose) closes it, BFCO_DIY_recovery (also "Rcovery"; MCO_Recovery) is where
  moving cancels; MCO-era clips carry MCO_WinOpen / Close and MCO_PowerWinOpen / Close alongside.
* fo4sf.bfco maps them onto the vanilla descriptor (template: the player's MeleeAttack_A): bDontAllowAttack until the
  first hit, bCanComboAttack from it to the window close (presses queue as in vanilla, where bCanComboAttack opens
  long before AttackStateNextAttack), AttackStateNextAttack at the BFCO window, bDontAllowPowerAttack until the power
  window, bFreeMovement and DisableAllowRotation from recovery to the end (supported hypothesis until tested).
* hkx_to_af --replace CLIP::VANILLA_AFX::NAME writes a clip under its own file name and tag (BFCO_Attack4 ...);
  --bfco applies the windows. scripts/armor/bfco_combo.py retags the vanilla combo machine's A / B / C as
  BFCO_Attack1-3, adds attacks 4..N as copies of B (enter / exit events and settings kept) and wires the BFCO routing
  on MeleeAttackStart. That custom tags are found in the weapon's folder is a supported hypothesis (descriptors are
  how clips are discovered); the test pack will tell. The graph is shared by every melee type, so weapon types
  without BFCO_AttackN clips lose their combo for now.
* Owner, in game: power attacks play, a regular attack does nothing - so the BFCO_Attack1 state finds no clip
  (supported hypothesis: the game does not discover clips under a tag / path it does not already know, e.g. it lists
  animations from its archives rather than the loose folder). Diagnostic pack (work/build_bfco3.sh, bfco_combo.py
  --tag K=NAME): attacks 1-3 on the vanilla MeleeAttack_A / B / C files, 4 as a new file under the known tag
  MeleeAttack_D (used in the knife / unarmed folders), 5 as a new file under BFCO_Attack5. The number of distinct
  swings before the chain stalls tells which naming works.
* Owner, diagnostic pack: every press replays attack 1. Cause (supported): our bCanComboAttack stayed open to the
  clip's end, and the queued attack fires where the window ENDS (vanilla sword A: window 6-22, AttackStateNextAttack
  22) - after the clip, i.e. as a fresh attack 1. fo4sf.bfco now ends the window at BFCO's NextWinStart and opens
  it at max(0.2 s, NextWinStart - 0.6 s) (vanilla opens at frame 6). Diagnostic pack rebuilt; the tag question is
  still open.
* Owner, rebuilt diagnostic: the combo works but stops after 3 swings, so attack 4 (a NEW loose file
  player\sword\MeleeAttack_D.af / .afx under the known tag MeleeAttack_D) is not found. Verified on the vanilla
  descriptors: the sneak / zero-g variants keep the base tag inside (sneak_meleeattack_b.afx: <tag>MeleeAttack_B</tag>),
  so the graph's tag-prefix switches (RelaxReadySneakSwitch "Sneak", Gravity "ZeroG") must find clips by FILE NAME
  (prefix + tag), and the files it can find appear to be the ones the archives list (supported hypothesis: loose files
  only override existing paths). Diagnostic 2 (work/build_bfco4.sh; hkx_to_af --replace ...::tag:NAME keeps the
  vanilla path and changes only the tag): attack 4 on the existing Sneak_MeleeAttack_B path, graph and file both
  saying Sneak_MeleeAttack_B; attack 5 on the existing Sneak_MeleeAttack_C path retagged BFCO_Attack5 - plays only
  if lookups use the <tag> inside the descriptor.
* Owner: still 3 swings, then back to idle. Found on review: both diagnostics used the vanilla MeleeAttack_B
  descriptor as attack 2's template, which keeps bAllowFinisher (15-48): a press there sends
  MeleeAttackFinisherStart (B -> C), and after the finisher the game starts no further combo attack - the same stop
  combo_loop.py avoided by dropping bAllowFinisher (v8 looped endlessly). So "3 swings" said nothing about the files.
  fo4sf.bfco.apply now drops bAllowFinisher. Diagnostic 3 (work/build_bfco4.sh): attack 4 on the existing
  Sneak_MeleeAttack_B path (file and tag), attack 5 a NEW file MeleeAttack_D.
* Owner, diagnostic 3: the 4th press sends the player back to idle - the transition fires, but the state finds no
  clip (or the copied state does not run). Both a literal existing file name (Sneak_MeleeAttack_B) and a new file
  under MeleeAttack_D fail. Open: is it the clip lookup (only tags the game already resolves, e.g. through its own
  prefix switches) or the copied states? Diagnostic 4 (work/build_bfco5.sh): copies 4 and 5 play the vanilla tags
  MeleeAttack_A / MeleeAttack_B (known to work) - if the 4th swing is attack 1's motion, copies work and the lookup is
  the limit. Copies now also get file-wide unique user_ids.
* Owner, diagnostic 4: every press attacks, no reset; some swings repeat (as routed). So copied states WORK, and the
  limit is the clip lookup.
* Verified on the vanilla descriptors: a clip is keyed by (<prefix>, <tag>), not by its file name -
  sneak_meleeattack_b.afx says <tag>MeleeAttack_B</tag> <prefix>Sneak</prefix> (zero-g: <prefix>ZeroG</prefix>;
  furniture flavours: Analyze, Bored, ...). That explains diagnostic 3: its file was keyed (Sneak,
  Sneak_MeleeAttack_B), which nothing asks for. A NEW file (BFCO_Attack1, the very first state) was not found.
  Diagnostic 5 (work/build_bfco6.sh): existing sneak paths re-keyed with the prefix removed - attack 4 as
  (-, MeleeAttack_D), attack 5 as (-, BFCO_Attack5). If 5 swings play, any tag works on a reused path.
* Owner, diagnostic 5: attacks 1-4 play, the 5th returns to idle. Verified: an EXISTING path re-keyed under a tag
  the game already uses (MeleeAttack_D, a knife / unarmed tag) plays; the same under a new string (BFCO_Attack5)
  does not. So no plugin is needed for normal movesets: extra attacks go on existing descriptor paths (the player's
  sneak / zero-g attack variants) under known tags (vanilla: MeleeAttack_D / _E, MeleeAttack01-04,
  MeleeAttackPower01 / 02 - only _D verified in game). Cost: the sneak / zero-g attack variants of that folder now
  fall back to the moveset's clips. fo4sf.animslots allocates the slots; scripts/armor/bfco_pack.py builds a whole
  pack from a BFCO moveset folder (attacks 1-3 on MeleeAttack_A-C, 4.. on re-keyed hosts, power / sprint, combo
  graph). Truly open-ended packs (more attacks than spare hosts, new tags) would need an SFSE plugin.
* MCO / DAR movesets (owner's Nordic Combat Animations for Player, Nexus SE 72966, read for the format): DAR condition
  folders (_CustomConditions/<n>/_conditions.txt: IsEquippedRightType etc.; 40100 = one-handed sword alone) holding
  mco_attack1..N / mco_powerattack1..N with MCO_WinOpen / Close, MCO_PowerWinOpen / Close, MCO_Recovery and
  animmotion, no routing markers: MCO chains them in order. fo4sf.bfco reads mco_ names and chains in order when no
  clip routes (BFCO_NextIsAttackN). Test pack: 40100's six attacks (6th under MeleeAttack01, not yet verified in
  game) and mco_powerattack1.
* Owner, in game: the Nordic pack works (all six attacks), but looks less smooth than in Skyrim. Measured: its
  clips carry a handful of animmotion keys (mco_attack1: 6 over 1.83 s), and linear interpolation made the root
  speed jump from one frame to the next (0 -> 2.4 -> 5.9 -> 0 m/s), and stop dead at a last key that is not the clip's
  end. fo4sf.rootmotion now interpolates with a monotone cubic (PCHIP: through every key, no overshoot, holds stay
  holds, continuous speed) and eases into a hold after the last key; two keys spanning the clip stay a straight line.
  Largest frame-to-frame speed change in the pack's attacks now 0.6-4 m/s (was up to 5.9).
* Owner suspects the 30 fps conversion. Facts: the Nordic clips are 30 fps at the source (no resampling happened;
  BFCO's base clips are ~59.4 fps and were resampled). The .af format has no frame-rate field (CALUMI's reader and
  writer: header = magic, root rotation / translation, flags, version, bone and frame counts) and our 30 fps clips
  play at the right speed in game, so the engine runs .af clips at 30 keys per second. A remaining difference that
  is real but not ours to change: Skyrim evaluates its spline-compressed tracks as smooth curves at render rate,
  Starfield (supported hypothesis) interpolates between 30 Hz keys. Unresolved whether that is what the owner sees.

### 2026-10-19: root motion (step 1 of the BFCO plan)
* Starfield (verified on the owner's 966 vanilla .af): root motion is the Root bone's own track (vanilla sword
  MeleeAttack_A: Root translation 0 -> (0, 1.847, 0) m over 41 keys; turning clips key Root rotation too), and the
  header repeats its end: rotation f32 w, x, y, z at byte 8 = last Root rotation, translation f32 x, y, z at byte 24 =
  last Root translation (582 / 582 clips with a header translation, 156 / 156 with a header rotation). Clips without
  motion leave Root out and the header at identity.
* Skyrim packs (verified on BFCO's clips): `animmotion X Y Z` = displacement from the clip's start in game units at
  that time (dense per-frame keys or sparse linear ones), `animrotation A` = accumulated yaw in degrees (all 0 in
  BFCO's clips: sign **unresolved**, taken as counter-clockwise from above). Their NPC Root track is static. Many pack
  clips are 60 fps (BFCO_Attack1: 105 frames / 1.75 s); the converter played frames 1:1 before, i.e. at half speed.
* fo4sf.rootmotion reads the annotations, builds the Root track (metres, leg-length scale like the COM) and patches
  the header; retarget.resample brings clips to 30 fps first; hkx_to_af writes Root (and drops it from the omitted
  bones) only for clips that move, and keeps animmotion / animrotation out of the descriptors (--no-root-motion off).
  Skyrim's own vanilla clips keep their motion in animationdatasinglefile instead (not read yet).
* Test pack (work/build_bfco.sh): BFCO's 1hm-sword-base Attack1 / 2 / 4, PowerAttackA (5.2 m dash) and SprintAttack
  (4.4 m) on the player's MeleeAttack_A / B / C, MeleeAttackPower_A and MeleeAttackSprint, vanilla graphs (full body,
  three-hit combo); read back: header and Root keys laid out like vanilla's.
* Verified in game (owner): every swing carries the player forward, the power attack dashes about 5 m, the sprint
  attack lunges, hits land, no clipping through walls.

### 2026-10-19: target is BFCO (Attack Behavior Framework, Nexus SE 117052) - commit-based combat, full body
* Owner: the goal is to port BFCO (most modded Skyrim combat builds on it) or something its animation packs work with.
* BFCO, read for format only (nothing copied): the SKSE plugins (BFCO.dll, BFCO_Functions.dll) and Nemesis patches
  read input and route attacks; four behaviour variables (BDI json: BFCO_ComboLocked, BFCO_LastAttack,
  BFCO_NextNormal, BFCO_NextPower); attacks are full body and animation driven (bAnimationDriven in its patches).
* Verified on the 202 clips it ships (our decoder): everything an attack needs is in the clip's own annotations -
  root motion as `animmotion x y z` (11,502) and `animrotation` (10,791) keys, combo windows BFCO_NextWinStart /
  BFCO_NextPowerWinStart (MCO_WinOpen / Close, MCO_PowerWinOpen / Close in MCO-era packs), routing
  BFCO_NextIsAttackN / BFCO_NextIsPowerAttackN, recovery (movement cancel) BFCO_DIY_recovery / MCO_Recovery, loop end
  BFCO_DIY_EndLoop, plus HitFrame / weaponSwing / preHitFrame, Precision collision and camera-shake annotations.
* Consequence (decision): BFCO-style combat does not walk while swinging - movement comes from the clip's root motion
  and the player cancels into locomotion once recovery opens. That maps onto Starfield's FULL-BODY attack path
  (MeleeAttacks): bCanComboAttack = next-attack window, the None-on-moving transition (Speed > 1 and bFreeMovement) =
  recovery cancel, Allow Rotation / DisableAllowRotation = rotation windows, Root track + header translation = root
  motion (vanilla attacks use both). The layered walk-while-swinging work above is a vanilla-Skyrim nicety that BFCO
  does not use; it stays an option (--actions-graph), not the base. Movement locking is not a blocker for BFCO.
* Plan: (1) root motion from animmotion / animrotation (and Skyrim's animationdatasinglefile motion data for vanilla
  clips) into the Root track and .af header; (2) annotation -> descriptor mapping (windows -> bCanComboAttack /
  power window / bFreeMovement / rotation windows, routing -> graph); (3) a generated MeleeAttacks combo machine with
  N attacks, power, sprint and jump attacks from a pack's clip set; (4) per-weapon-type folders in place of OAR
  conditions; (5) later, an SFSE plugin for what Starfield's own input code cannot do (held / charged attacks,
  input buffering, BFCO_ComboLocked-style state).

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

## New weapon types (two-handed, dagger / axe / mace) and dual wield: plan (2026-10-20)
Owner: most Skyrim weapon types (greatsword, battleaxe, warhammer...) do not exist in Starfield, and dual wield has
to be worked out.
* **Starfield has one-handed melee only** (verified on the owner's files: animation folders melee\onehanded\{knife,
  sword, player\...} and melee\unarmed; HumanRace subgraph: AnimOneHanded -> NPC_Melee / Player_Melee). Nothing in the
  melee graphs is weapon-specific beyond clip tags, so a greatsword can run on Player_Melee with its own clips
  (supported hypothesis).
* **Why new files and tags were not found (supported hypothesis):** the AnimTextData caches
  (animationfiledata / animationoffsets: per graph + folder set, tag -> resolved clip path), see the Alternate Recoil
  notes above. Fallout 4's Creation Kit regenerates them from the command line:
  `CreationKit.exe -GenerateAnimInfo:<ESM> <Data> <Output> [--speed] [--stance]` (falloutck.uesp.net/wiki/Subgraphs).
  **Unresolved: whether Starfield's Creation Kit has the same switch** (first PC check). If it does: one keyword per
  Skyrim weapon type, a HumanRace subgraph entry each (subgraph.py), its own folder, regenerated caches; the 7-11 attack
  slot limit goes away too (new tags).
* Skyrim types -> Nordic Combat Animations folders (DAR conditions read 2026-10-20): 1H sword 40100, dagger 40200,
  war axe 40300, mace 40400, greatsword 40500, battleaxe / warhammer 40600 (Skyrim type 6 covers both); dual: same
  type pairs 40150 / 40250 / 40350 / 40450, mixed 40090. The packs carry attacks and power attacks only: two-handed
  stance clips (idle, walk / run, block, equip, sprint) come from vanilla Skyrim.
* **Measured 2026-10-20** (Nordic 40500 and 40150 converted with the current pipeline, scratch only):
  - greatsword: the left wrist drifts 3-6 cm (std, per axis) in the weapon's frame over a swing: the support hand
    slides on the grip (Starfield arm proportions). Fix planned: solve the left arm so the hand keeps its Skyrim
    offset from the weapon.
  - dual: WeaponLeft stays at its rest offset from L_Wrist (8.5 cm every frame); nothing turns the left hand to match
    Skyrim's Shield (left weapon) node the way weapon_in_hand does for the right. Fix planned: the right-hand handling
    mirrored (WeaponLeft from Shield, L_AnimObject3 as the left follower: hypothesis by symmetry with R_AnimObject3).
* **Dual wield routes:** Starfield has no left-hand weapon slot. A (no plugin): the WEAP is the right blade, the left
  blade is an apparel piece skinned 100 % to WeaponLeft (the bone is in the vanilla rig, verified), equipped with the
  weapon; attack = Skyrim's dual combo, power attack = dual power attack, aim stays block. B (SFSE): a real left-hand
  melee slot with its own stats and input. A first.

## Block hits: Maxsu Block Overhaul / Dynamic Block Hit -> Starfield (2026-10-20, owner uploads, read for format only)
* **Skyrim side (verified from the files):** Maxsu Block Overhaul (V0.24a, Nemesis patch + maxsuBlockHit_behavior)
  hooks 1hm_behavior event 47 `blockHitStart` (vanilla: a small additive twitch) and sends it to its own block-hit
  state that plays Maxsu_WeaponBlockHit / Maxsu_ShieldBlockHit on the upper body, plus a guard-break state on
  `Maxsu_GuardBreakStart` (weapon / shield, 4 variants each); clip events Maxsu_BlockHitWinOpen / WinClose. Dynamic
  Block Hit swaps those clips through Open Animation Replacer: 122 folders, 121 distinct clips, by weapon type (Sword
  = 1H, 2hw, Dual Wield, Shield, Javelin, Pike / Spear / Quarterstaff, Unarmed Claw) x hit kind (NA normal attack, PA
  power attack, ST "Groggy" when health or stamina < 30 %) x Random 1-6; its plugin marks power-attack hits with a
  perk entry that applies a spell (MGEF _SD_BlockHit_PA, the PA folders' condition).
* **Starfield side (verified on the vanilla graphs):** MeleeActions already has the hook: `BlockHitStart` ->
  state MeleeBlock_HitReaction (tag MeleeBlock_HitReaction, flags Animation Driven + Blocking) inside the block
  machine (MeleeBlock_Into / Idle / HitReaction); one clip, no variants. Stagger clips exist per size and direction
  (StaggerBackward{Small,Medium,Large}[_Left/_Right], StaggerForward*, StaggerLeft / Right, ZeroG_*); the player graph
  has cHitReactionDir / cHitReactionBodyPart.
* So: the recoil itself is a clip swap (no graph edit); variants = a small machine in place of the one state
  (rotating on each BlockHitStart; random selection not seen in Starfield graphs); per weapon type = the weapon
  folders; power-attack / groggy kinds need a variable the graph can read (Papyrus SetAnimationVariable* from OnHit:
  supported hypothesis, and a script would likely be one hit late; SFSE otherwise); guard break = Starfield's own
  stagger clips replaced (supported hypothesis: a blocked power attack staggers).
* Test pack built (scratch): DBH "Sword NA Base" recoil as MeleeBlock_HitReaction (31 frames, pushes back 1.13 m).

## Dodges: TK Dodge (RE, For RE, 1st-person 8-way, RE Addon) -> Starfield (2026-10-20, owner uploads, format only)
* **Skyrim side (verified from the files):** an SKSE plugin (TK_Dodge_RE.dll) reads the dodge key, picks the direction
  from movement input (4 ways; standing still -> `defaultDodgeEvent`, TKDodgeBack), checks / spends stamina and sends
  the graph event TKDodgeForward / Back / Left / Right; a Nemesis patch adds the dodge states to 1hm_behavior and
  magicbehavior (both views) with variables bIsDodging, bInIframe, bIframeActive, iStep / iStepSelector and clip
  events TKDR_DodgeStart / End, TKDR_IframeDuration / IframeEnd; the plugin makes the player ignore hits while
  i-frames run (iFrameDuration 0.3 s) and can cancel attacks into a dodge. The 1st-person 8-way pack picks diagonals
  with OAR on Keytrace.esp's key-held magic effects; the RE Addon adds an MCM and stamina-cost actor values.
* **Root motion of these (and of vanilla Skyrim clips) is not in the .hkx**: it is in animationdatasinglefile
  motion blocks (TKDodgeForward -> id 1656: 0.867 s, 409 units = 5.4 m on our scale; Back 300 u, Left / Right
  252 u). `rootmotion.parse_motion_data` + `hkx_to_af --motion CLIP=FILE:ID` read them (vanilla Skyrim attacks
  converted so far had none applied: their power-attack lunges live there too).
* **Starfield side (verified on the vanilla files):** no player dodge state or clip in the 233 graphs / 970 descriptors
  here. The nearest built-in evasive move is the slide: SlideStart -> SlideFromSprint (Biped_IdleLocomotion), with a
  melee player clip (melee\onehanded\player\SlideFromSprint, 51 frames, bIsSliding 0-25). Descriptor flags / variables
  include nothing that grants invulnerability (disableCollision exists, on jump traversal: collision, not damage).
* So: the clips and their motion convert (done); triggering needs input -> a graph event, which vanilla Papyrus cannot
  do (no key events): SFSE plugin (the same one as the input buffer / charged attacks), which would also own the
  i-frames. Without a plugin only existing triggers can be borrowed (the slide: forward only, from a sprint).
* retime_descriptor now scales <rampout> (blend-out frames) down with a shorter clip and clamps it to the last frame
  (the 29-frame slide blend-out on a 27-frame dodge would have blended the whole clip).
* Test pack built (scratch): StepDodgeForward with its motion as the melee player SlideFromSprint (27 frames, 5.4 m).

## Combat SFSE plugin: scope and references (2026-10-20, planning)
* **Payload Interpreter annotations in the movesets (verified, strings of the owner's copies):** Nordic Combat
  Animations' clips carry `PIE.@SGVI|MCO_nextattack|N` (99), `PIE.@SGVI|MCO_nextpowerattack|N` (102),
  `PIE.@SGVF|MCO_AttackSpeed|0.9-0.95` (97), `PIE.@CAMSHAKE|...` (84+), `@SGVI|MCO_nextdodge` (2); BFCO: 2
  `@SGVF|BFCO_AttackSpeed`. So Nordic's routing is explicit (bfco.chain assumed in-order for MCO sets) and every attack
  has a speed multiplier the converter ignores so far (unresolved: part of "less smooth"?). Syntax (Payload
  Interpreter, MIT, github.com/D7ry/PayloadInterpreter): `event.@INSTR|arg|arg`, PIE = a do-nothing host event.
* Vanilla Starfield descriptors already carry `AssignVariable` events with `X=1` payloads (44 seen): a native way to
  set graph variables from a clip (supported hypothesis: may cover @SGVI / @SGVF without a plugin).
* IFrame Generator RE (source github.com/max-su-2019/MaxsuIFrame): its Nexus permissions forbid conversion to other
  games: design reference only, no port.
* Plugin library: CommonLibSF moved to libxse/commonlibsf (the Starfield-Reverse-Engineering repo archived
  2025-09-16): GPL-3.0-or-later with a modding exception and a GPL linking exception; XMake / CMake, MSVC or clang-cl,
  C++23. Starfield SFSE references that drive animation: OSF Animation (github.com/ozooma10/osf-animation), NAF
  (github.com/Deweh/NativeAnimationFrameworkSF), SAF (Nexus 16124).

## LoreRim MCO Animations and SpellSword Moveset: what the movesets use (2026-10-20, owner uploads, format only)
Survey (scratch tool: every clip's annotations via skyrimhkx.describe):
* **LoreRim - MCO Animations:** 4,009 clips in 242 DAR / OAR folders, about 85 movesets (sword, dagger, war axe, mace,
  greatsword, battleaxe, warhammer, katana 1H / 2H, rapier, spear, pike, halberd, quarterstaff, scythe, claw, fists,
  with shield / dual-wield variants; most in Novice / Apprentice / Adept / Expert versions: these are **stances**, not
  skill tiers (corrected below: HasPerk on the Stances mod's perks, 75 folders)). DAR
  conditions: IsEquippedRightHasKeyword 323, IsEquippedLeftType 232, IsEquippedRightType 191, IsActorBase 130,
  HasMagicEffect 84, HasPerk 75, IsInFaction 31 ... Clips: 3,628 with animmotion, 375 at 60 fps; files
  BFCO_ / mco_ attackN (up to 10), powerattackN, powerattackloop / outro (charged), sprintattack, sprintpowerattack,
  idles / locomotion / block / bash for some styles.
  Annotations: MCO windows (WinOpen / Close, PowerWinOpen / Close, Recovery; MCO_TransitionOpen / Close 24;
  MCO_ChargedAttack 44); Payload Interpreter SGVI 6,265 (MCO_nextattack / nextpowerattack), SGVF 1,053 + the typo
  SVGF 1,269 (MCO_AttackSpeed 0.7-1.5), CAMSHAKE 507, CAST 10 (DD_FighterBuffs.esp), custom `$` instructions whose
  definitions are not in the pack ($ChargeN, $Parry_start / stop, $katanaN_Iframe, $ES_Paralysis / Strikefly /
  HeavyParalysis / Repulse / Unbalance, $Dust, $SmashDownFog ...); Precision hitboxes (Collision_Add / Remove
  .Node(WEAPON|SHIELD|bone)|ID|Scale|DamageMult, Collision_AttackStart / End: ~2,000); SCAR NPC AI
  (SCAR_ComboStart 899, SCAR_ActionData{json: idle, distance, angle, chance, type} ~1,600); MeleeTrace_*; TDM_AttackStart.
* **Routing is a graph, normal and power interleaved** (each clip: next normal N, next power M); e.g. LoreRim
  Sword Shield Novice: attack 6 -> 3, attack 7 / 8 -> 8 (a repeat), power 7 / 10 -> attack 1.
* **SpellSword Moveset:** 89 clips in 8 OAR folders, sword right + spell or staff left (locomotion, idles, spell
  pre-charge poses, equip); almost no clip annotations: state switching is event -> spell -> magic effect -> OAR
  condition (Dynamic Animation Casting toml, Behavior Data Injector events EquipIdle / IdleEnd / IdleNon). Starfield
  counterpart: the melee graph's CastSelf / CastTarget slot (left-hand casting with a melee weapon, see above).
* **Converter changes (this entry):** bfco.markers reads MCO_nextattack / nextpowerattack and MCO_AttackSpeed from
  the payloads (SVGF ignored); hkx_to_af --bfco bakes the attack speed into the clip (retarget.play_speed); packs slot
  only attacks the chain reaches (bfco.reachable). Nordic 1H rebuilt: attack 6 (never played by Nordic) dropped, attack
  5 at 0.9 speed (62 frames instead of 56).

## Stances and directional attacks: dTry's Key Utils + Stances - Dynamic Weapon Movesets (2026-10-20, owner uploads)
* **Key Utils (SKSE, DtryKeyUtil.dll + Keytrace.esp, verified from its configs):** maps a key (DX scan code), a user
  event or a held movement direction to a spell; movement trace keeps Keytrace's ForwardMGEF 0x801 / Left 0x802 /
  Backward 0x803 / Right 0x804 on the player while that direction is held (optionally only under True Directional
  Movement's target lock).
* **Stances (Papyrus + Key Utils config):** arrow keys (200 up = high, 203 left = mid, 208 down = low, 205 right =
  neutral; T + direction as an all-in-one key) cast a switch spell whose effect script adds one stance perk
  (stances_highstance_perk 0x42518, mid 0x42519, low 0x4251A; neutral = none), removes the others, plays a draw sound,
  casts an icon effect, and sends blockStart / blockStop so the animation replacer re-picks clips.
* **LoreRim uses both (verified on its conditions):** tier names are stances: Novice = neutral (no perk, 21 folders),
  Apprentice = low (22), Adept = mid (23), Expert = high (20). Keytrace effects pick directional power attacks
  (e.g. backward held + power attack -> a dedicated BFCO_PowerAttack1 for sword / dagger, with or without shield,
  when TDM's directional mode is off or its target lock is on).
* **Starfield mapping (supported hypotheses, to test):** a stance = an actor keyword whose HumanRace subgraph entry
  lists that stance's folder first (Starfield already picks unarmed sets by actor keyword: same tags, no graph edit,
  no extra slots; needs the new-folder route, and whether the swap re-applies while the weapon is drawn is
  unresolved: Stances itself has to poke the graph). Directional attacks: Biped_IdleLocomotion has a `Direction`
  graph variable (with Speed), so a condition in MeleeAttacks could pick the backward power attack natively; it is
  the movement direction, not the key, so a standing start may read 0 speed. Keys -> stance: the plugin's input
  layer (key -> action table, as Key Utils), since Papyrus cannot read keys.

## Lock-on (True Directional Movement style), owner wants it eventually (2026-10-20, planning)
* TDM (Nexus 51614, source github.com/ersh1/TrueDirectionalMovement, no licence stated on the page: design reference
  only): directional movement (the body turns to the movement direction), target lock (face the target, camera yaw /
  pitch with an offset, switch by mouse / scroll / stick, auto-next on death, a "relaxed" free-camera mode, several
  target points per actor), head tracking, a TrueHUD reticle, projectile aim help (predictive / homing).
* Starfield hooks to try first (supported hypotheses): vanilla melee descriptors set `bAlignWithAimAssistTarget`
  (50 clips), so attacks already turn to the aim-assist target: a lock could feed that target instead of new
  rotation code; weapon-drawn third person already strafes facing the camera, so the lock is mostly camera control
  toward the target (OSF Animation drives the camera from SFSE: possible). Reticle: an effect / art object on the
  target first (as Stances shows its icon), HUD work later. Expose the lock as a graph variable / keyword so the
  movesets' TDM conditions (LoreRim: 19 folders) port.
* Order: after the plugin core (input table, payload commands, i-frames, dodge).

## 2026-10-20: left hand for dual wield and two-handed weapons (converter)
* **Two-handed grip (`hkx_to_af --two-hand-grip`, retarget.two_bone_ik):** the left wrist is put where Skyrim has the
  left hand in the weapon's frame (Skyrim Weapon frame -> Starfield WEAPON frame through WEAPON_AXES), every frame, by
  two-bone IK on L_Biceps / L_Forearm with the elbow kept in its bend plane and the hand's world rotation kept.
  Nordic greatsword (40500), verified on the written clips: the left wrist was 9-10 cm off on average (up to 14 cm)
  and drifted 2.8 / 5.7 / 4.1 cm (std per axis) on the handle; now 1.0 / 0.9 / 1.9 cm, the same as Skyrim's own
  (0.9 / 1.9 / 1.0 cm), IK error 0.
* **Dual wield (`--left-weapon`, with `--weapon-in-hand`):** Skyrim hangs the left weapon rigidly off the Shield node
  (verified: fixed in the left hand on every frame). WeaponLeft is held at the mirror image of the right grip
  (skeletonmap.LEFT_GRIP, retarget.mirror_grip; exact at rest) and the left hand is turned so the left blade points
  along Skyrim's (Shield +Y). Nordic dual sword (40150): left blade within 0.7-1.1 deg of Skyrim's on every frame
  (10.6 deg off before); the left hand turns 25.5 deg from Skyrim's, as the right does (21.6). LEFT_WEAPON_AXES keeps
  the blade's roll as the mirrored right weapon's, because following Shield's own roll would twist the wrist ~150 deg.
  The left blade itself is still to make: an apparel mesh skinned to WeaponLeft (dual-wield plan above).

## 2026-10-20: power-attack routing (MCO / BFCO) in the combo graph
* `bfco.routes`: the whole routing over normal and power attacks (normal -> next normal / next power, power -> next
  normal / next power), restricted to what is reachable from attack 1 and power attack 1 (both chains together).
* `bfco_pack`: normal attacks first, then power attacks: the first on vanilla meleeattackpower_a (MeleeAttackPower_A,
  also the standing power attack), the others on the spare hosts left, as many as every planned folder can hold (one
  planning run over all folders: separate runs gave the shared graph different budgets); the rest fall back to the
  first. Nordic 1H: power attacks 1-3 slotted (MeleeAttackPower_A, MeleeAttack01, MeleeAttack02), 4-5 fall back
  (player/sword has 4 spare hosts, 2 used by attacks 4-5).
* `bfco_combo.build(power=...)`: each slotted power attack is a state inside MeleeAttackCombo (copy of attack 2's
  state); normal k -> its next power attack and power -> power on MeleeAttackPowerStart, power -> next normal on
  MeleeAttackStart; top level MeleeAttackPower_A -> MeleeAttackCombo on MeleeAttackStart.
* **Unresolved, to test in game:** whether the game sends MeleeAttackPowerStart while a combo attack plays (vanilla
  descriptors carry bDontAllowPowerAttack windows, which suggests it does; vanilla has no transition from the combo
  to a power attack).

## 2026-10-20: iron weapon test pack (one Skyrim weapon of each type)
Owner request: real Skyrim weapons to test the movesets with. `scripts/armor/weapon_test_pack.py` (also step 6 of
pc_checklist.ps1 when texconv is found) builds an MO2 mod on the PC:
* the iron set (dagger, sword, war axe, mace, greatsword, battleaxe, warhammer; `skyrimweapon.IRON_SET`), model path
  and stats read from Skyrim.esm (fallback: the vanilla paths);
* models converted by the Skyrim object converter (`SkyrimConverter(shape_hook=skyrimweapon.weapon_shapes)`):
  geometry rotated by WEAPON_AXES^-1 (Skyrim +Y blade -> Starfield +Z) and shifted so Skyrim's hand point on the
  weapon (skeleton rest: (7.16, 0, -2.43) units in the Weapon frame) lands on Starfield's wrist point of the vanilla
  grip; scabbard shapes (under a node named Scb) left out (supported hypothesis on the name). Verified on a synthetic
  sword: blade along +Z, hand point onto the wrist point exactly, scabbard dropped;
* `S2SWeapons.esm` (`fo4sf.sfplugin`, a minimal master writer: HEDR version and form version copied from the
  installed Starfield.esm): one copy of a vanilla one-handed melee WEAP per weapon (keyword AnimSword first, then
  WeaponTypeMelee1H), new EditorID, text name "<name> (Skyrim)", MODL = the converted model, DESC dropped; everything
  else (stats, sounds, keywords) is the template's for now;
* `S2SWeapons - Main.ba2` / `- Textures.ba2` with Archive2 when the Creation Kit is installed, else loose files.
**Unresolved, to see in game:** whether Starfield melee weapons take their visible model from WEAP MODL (the report
lists the template's subrecords and model to check); the grip in game; dual wield's left blade (needs a Starfield
skinned-mesh writer: not in this pack).

## 2026-10-20: skinned NIF writer and the dual-wield left blade
* `sfnif.build_skinned_nif` / `parse_skin`: worn NIFs with the block layout of the community outfit that works in game
  (robes-of-oblivion-reference.md): BSGeometry with skin -> BSSkin::Instance (root 0, its BoneData, one empty bone ref
  per bone, no scales), SkinAttach "SkinBMP" (bone names), BSSkin::BoneData (68 bytes per bone), BSXFlags 0x10000,
  zero sphere + FLT_MAX box; meshes external with (bone, u16 weight) pairs. The reader agrees with the robe files.
* **Bind convention (verified on the robe):** its binds are inverse(bone rest world) composed with the geometry node's
  transform (rotation = s x W^T with the robe's odd 1.2243 node scale, translation = W^T (t_node - T_bone)): the
  engine draws a vertex at bone_world * bind * vertex and ignores the node transform. So a rigid part can use an
  identity bind with bone-local vertices, independent of the skeleton's rest pose: done for the left blade.
* `skyrimconvert.convert_nif(skin_bone=...)`: rigid one-bone worn models (4 weights per vertex, (0, 65535) first).
* `skyrimweapon.left_weapon_frame`: Skyrim draws left weapons in its Shield frame; the model goes into WeaponLeft's
  frame (LEFT_WEAPON_AXES, LEFT_GRIP; Skyrim's left hand at (-7.56, 0, 0.16) units in the Shield frame from the
  skeleton): hand point onto the Starfield wrist point and blade along +Z, as the right weapon (tested).
* `weapon_test_pack.py --left-blade sword` (default): the iron sword again as `longsword_left.nif` skinned to
  WeaponLeft, worn through ARMO / ARMA copies of vanilla `Clothes_Nightwear_01` (the outfit the robe mod copied;
  worn and first-person models -> the left blade). Test shortcut: it occupies the outfit's slot.
  **Unresolved:** a slot that does not replace the outfit; whether the first-person skeleton has WeaponLeft; the left
  blade stays where the WeaponLeft bone is when sheathed (no sheath position yet).

## Combat plugin: game side, first draft (2026-10-20, away from the PC)
* `native/combat/include/s2s/controller.h`: the plugin's decision logic as a game-independent controller, tested here
  (MCO input buffer with the window rules, TK Dodge direction / i-frames / dodge end from TKDR events or the i-frames,
  Payload Interpreter variable commands, Key Utils / Stances bindings as one exclusive keyword group, INI parsing,
  Starfield key codes -> Key Utils codes). `AttackEnd` (the name our converter gives Skyrim's attackStop) now ends the
  attack phase.
* `native/combat/sfse`: SFSE glue (input receiver hook, player animation-event sink, NotifyAnimationGraph, Papyrus for
  variables / keywords / ghost), sample `S2SCombat.ini`, build and first-run notes. **Unverified** until the PC: it
  builds with MSVC, the hooks fire, the animation-event layout, the Papyrus names (pc_checklist step 1b lists them).
* Converted clips do not carry the MCO / PIE / TKDR annotations yet (they stay in `<clip>.events.json`); writing them
  into the .afx (and whether the graph passes unknown event names to the sink) is the graph-side prep item.

## Automatic root motion from animationdatasinglefile (2026-10-20)
* `src/fo4sf/animdata.py` reads the whole file by its structure (verified by walking TK Dodge For RE's full copy:
  429 projects, 171,765 lines, ends exactly at the last line; 10 object projects are listed twice): per project the
  behaviour files, the clip blocks (clip generator name, motion id, speed, crop, events) and the motion blocks. Nemesis /
  Pandora fragment folders (`animationdatasinglefile\<Project>~n\`) are read too, patch markup applied (`MOD_CODE ...
  OPEN` / `ORIGINAL` / `CLOSE`; patched blocks keep stale key counts, so keys are taken by shape).
* Motion follows the clip generator, so a clip file gets it through the generators that play it: behaviour
  hkbClipGenerator name -> animation file (`--motion-behaviors DIR`), else the generator's name taken as the file name.
  Verified on TK's 1hm_behavior: TKDodgeForward plays `SneakRun_ForwardRoll.hkx` (5.85 m), not TK's StepDodgeForward
  (OAR-style replacement files keep needing the explicit `--motion`); vanilla 1hm attacks: normal swings carry no motion,
  power attacks do (fwd 6.9 m, left / right ~2 m, sprint power 8.9 m on a 70 units / m reading); converted end to end, 1hm_attackpowerfwd gets a 6.4 m root offset in its .af, 1hm_attackright none. Generators of one
  file can disagree (vanilla DodgeRight vs TKDodgeRight both play DodgeRight.hkx): the most common id wins, the rest is
  listed in `motion_data.json`.
* `hkx_to_af --motion-data <animationdatasinglefile.txt or fragment folder> [--motion-project DefaultMale]
  [--motion-behaviors <behaviors folder>]` applies it to clips that have no animmotion annotations of their own
  (explicit `--motion` still wins; BFCO-style annotated clips are left alone). The PC checklist's step 4 already extracts
  the vanilla file and behaviours this needs.

## LoreRim neutral-stance packs; routing read where the window opens (2026-10-20)
* 11 test packs from LoreRim MCO Animations (scratch, delivered as SkyrimMelee_LoreRim_weapon_types.zip): the folders
  without a Stances perk condition for sword (9011000), sword + shield (9011200), dagger (9021000), war axe (9031000),
  mace (9041000), greatsword (9051000), battleaxe / warhammer (9061000), dual sword / dagger / war axe / mace (9011100,
  9021100, 9031100, 9041100); `--bfco` (attack speeds baked in), `--two-hand-grip` / `--left-weapon` as the Nordic
  packs. 4-7 attacks per chain, 1-4 power attacks slotted; all clips convert (read-back rotation error <= 0.0066).
  LoreRim ships each attack twice (BFCO_AttackN and mco_attackN, byte-identical: checked on two pairs).
* **Fix (bfco.markers):** routing is the value in effect when the window opens. LoreRim dual sword sets
  `MCO_nextattack 2` at 0.6 s, opens the window at 0.67 s and resets it to 1 at 1.33 s (a late press restarts the
  combo); the last value used to win, so the pack looped attack 1. Now 1 -> 2 -> 3 -> 4 -> 1; the later value is
  reported as `late_reset`. Only 2 of LoreRim's folders (6 of 782 attacks) and none of Nordic's are affected.
* **Plugin events in clips (graph-side prep):** `hkx_to_af --plugin-events [HOST]` writes the annotations the combat
  plugin reads (MCO / BFCO windows, `PIE.@...` / `.$...` commands, TKDR_, TDM_, Collision_) into the .afx events,
  as Skyrim splits them (event "PIE", payload "@SGVI|...") or all under one HOST event (the plugin's
  `sPluginEventHost`). Whether the graph passes event names it does not know to the plugin is **unresolved**: the
  first plugin run's `anim event:` log answers it, and HOST is the fallback (e.g. a vanilla event such as
  `AssignVariable`, which vanilla clips already carry with payloads).

## Dodge states in the melee graph (2026-10-20, graph-side prep)
* `scripts/armor/dodge_graph.py` adds one state per dodge direction to the top machine of MeleeActions.agx, built
  like the vanilla actions there: a copy of MeleeBlock_Out (a plain clip state), entered from any state on
  TKDodge<Direction> (the plugin's event), `Send Event On End = TKDR_DodgeEnd` (the plugin's dodge end), leaving
  to IdleTimer without an event; 4-way or `--eight-way`; clip tags per direction (`--tag Back=...`). Tested on a
  synthetic graph; applied to the vanilla graph (states 12-15, vanilla links unchanged).
* Test pack (scratch, SkyrimDodge_plugin_test.zip): the graph + TK Dodge's four step dodges as new clips in
  melee/onehanded/player (StepDodge*, motion from TK's motion blocks 1656-1659: 5.4 / 3.9 / 3.3 / 3.3 m). With the
  plugin it answers three open questions at once: new event names in a graph, new clip tags without the cache
  rebuild, and whether the graph's end-of-clip events reach the plugin. **Unresolved** besides: dodging out of an
  attack (MeleeAttacks is a separate graph; its states may hold the actions layer).
* Not done yet: block-hit variants (one MeleeBlock_HitReaction clip in vanilla; variants need the plugin's hit-type
  variable and a selector state).

## Stances, LoreRim style (2026-10-20, built away from the PC)
* **S2SStances.esm** (`scripts/armor/stance_plugin.py`, PC checklist step 8, needs Starfield.esm): three actor
  keywords S2S_StanceHigh / Mid / Low (new records) and a HumanRace override where every third-person melee
  animation entry gets, per stance, a copy with the stance keyword added to its actor keywords and the stance folder
  (`actors\human\animations\melee\s2s_stances\<stance>`) first in its folders; copies placed before the originals.
  Fields over 64 KiB are written as XXXX (sfplugin), so the big race record round-trips. Tested on a synthetic
  Starfield.esm.
* **Keys** (S2SCombat.ini, now on by default): Up = high (LoreRim Expert), Left = mid (Adept), Down = low
  (Apprentice), Right = neutral (Novice, no keyword). Each press removes every other stance keyword (Papyrus-added
  keywords persist in saves, so the plugin's memory alone could be stale). `sStanceRefreshEvents` (e.g.
  `BlockStart, BlockStop`, what Skyrim's Stances sends) is sent after a change if the set only switches on re-draw.
* **Stance packs** (`scripts/armor/stance_pack.py`): one combo graph serves every stance, so the slots form a ring of
  N attacks (the longest chain that fits); each stance fills it with its own chain from attack 1 (a shorter chain
  repeats; where the ring closes differently from the chain it is reported as "wrap"). Neutral goes to the vanilla
  folders as a normal pack, the others into their stance folders under the same files / tags.
  Built: LoreRim sword (9011000 / 9012000 / 9013000 / 9014000): ring of 6; high plays 1-6 exactly, neutral / low
  1 2 3 4 5 2 (their chain continues 3, the ring goes to 1), mid 1-5 then 1. Delivered as
  SkyrimMelee_LoreRim_sword_stances.zip (scratch).
* **Unresolved, answered by the test:** whether a keyword-matched entry wins over the plain one, whether the new
  folder is found without the Creation Kit cache rebuild, and whether the set switches while the weapon is drawn.

### 2026-10-23: stances in game: keywords work, clips not picked; stance folders now mirror the weapon subpath
* Verified (owner's log): every arrow key adds / removes the right stance keyword and HasKeyword confirms it on the
  player; the Creation Kit's `-GenerateAnimInfo:S2SStances.esm <Data> <Out>` works on 1.16 and wrote 724 cache files,
  21 of them new sets naming the stance folders (7 clips each). Swings still identical in every stance, also after a
  save / reload (so not only a graph refresh question).
* Tried and wrong: clips moved to s2s_stances\<stance>\onehanded\player\sword; the regenerated caches then named no
  stance clip at all (the CK lists only files directly in a listed folder; it does not add weapon subfolders).
* Found (verified, owner's archives): Starfield.esm names no melee\onehanded folder; the player's weapon sets are the
  "Weapon" rows of the generated table meshes\animtextdata\generatedsubgraphdata\humanrace.txt (1,607 rows: 1,016
  Weapon, 555 Furniture, 36 MT), e.g. AnimArchetypePlayer + AnimOneHanded, AnimSword -> Player_Melee.agx,
  melee\onehanded\player\sword > ...\player > ...\sword > onehanded > melee\common > common; 16 player third-person
  one-handed rows (sword / knife / two-hand block, female, zero-g). The first stance plugin copied the esm's generic
  melee entries, which these rows always beat.
* Now: `stance_plugin.py` reads that table from the archives and adds, per stance, an esm entry for each of the 16 rows
  with the stance keyword added to its actor keywords, its weapon keywords and graph, the stance folder first, SRAF role
  Weapon / third person (48 entries); clips back flat in s2s_stances\<stance>. Supported: an esm entry with these
  keywords competes with the table rows and wins on the extra keyword; the CK builds its cache sets as it did for the
  first entries.
* The CK output also holds cut-down GeneratedSubgraphData (creature tables with only a header) and a
  PersistantSubgraphInfoAndOffsetData.txt listing only the regenerated sets: kept out of the loose-file mod for now
  so they do not shadow the vanilla ones (unresolved whether the game needs our index file to find the new sets).
* **Verified (owner, 2026-10-23): stances change the sword attacks in game.** Working setup: S2SStances.esm with
  the 48 entries cloned from the generated table's player one-handed Weapon rows, clips flat in
  s2s_stances\<stance>, CK `-GenerateAnimInfo:S2SStances.esm` run through MO2, its AnimationFileData +
  AnimationOffsets as loose files (GeneratedSubgraphData and PersistantSubgraphInfoAndOffsetData.txt left out). The CK
  output then had 48 sets naming the stance clips with the vanilla sword folders (the vanilla MeleeAttack_A etc.
  replaced by the stance ones). Limitation: a stance change shows only after a save / reload, so the subgraph is picked
  when the graph is built; next: find what re-picks it in play (re-equip, redraw) and do that from the plugin.
* **Verified (owner, 2026-10-23): stance changes apply in play, no reload.** The combat plugin re-equips the weapon
  0.25 s after the last stance key: Papyrus Actor.GetEquippedWeapon(0) for the weapon (FormID = low 32 bits of its VM
  handle), then ActorEquipManager::UnequipObject / EquipObject on the base form (as the console's unequipitem /
  equipitem), the equip on UnequipComplete or after 0.5 s. Papyrus UnequipItem / EquipItem returned but did nothing;
  a redraw does not re-pick the set. Limitation: the base form is re-equipped without its instance data (weapon mods
  on a modded vanilla weapon may be lost; the converted Skyrim weapons have none).
* **Power attacks follow the combo (2026-10-23, built, in-game check pending).** Owner: only one power attack played;
  BFCO / MCO pick the power attack by the normal attack before it (LoreRim sword high: after 1 power 2, after 2
  power 3 ...; low: 1->2, 2->4, 3->3, 4->4, 5->5). `stance_pack.py` now gives ring slots 1-5 their own power state
  (hosts left after the 6 normal slots: sneak / zero-g power and zero-g attack descriptors, power ones first, tags
  MeleeAttack02-04, MeleeAttackPower01 / 02), each stance filling it from its routing; after power slot j a normal
  press goes to ring slot j + 1, a power press to power slot j + 1. Slot 6 and the standing power attack keep the
  vanilla MeleeAttackPower_A (each stance's power 1). Delivered as SkyrimMelee_LoreRim_sword_stances_v2.zip (scratch);
  stance folders now hold 12 clips each, so the CK cache must be rebuilt.
* **Why every mid-combo power attack was the same (owner, 2026-10-23):** the plugin's MeleeAttackPowerStart was
  "taken by the graph", yet each stance played one power attack: vanilla MeleeAttacks.agx has a TOP-LEVEL
  transition MeleeAttackCombo -> MeleeAttackPower_A on MeleeAttackPowerStart (1-based links 5 / 4 / 1 = idle, combo,
  sprint), which catches the press before the combo machine's own states. Now every ring slot has an inner power
  transition (slots without a host -> an inner state on the vanilla MeleeAttackPower_A tag) and that outer
  transition's event is renamed to S2S_ComboPowerInside (never sent); the standing power attack is unchanged.
  BFCO does the same job differently: its power state machine's startStateId is bound to MCO_nextpowerattack, which
  each normal clip sets (read for the approach only). Pack v3 (scratch).

## 2026-10-26: dual wield, first build (owner: looks + plugin damage, LoreRim dual movesets)
* **Moveset:** a fifth stance, Dual (`stance_plugin.STANCES_DUAL`, keyword S2S_StanceDual, last so High / Mid / Low
  keep their form IDs; clips in `s2s_stances\dual`). `stance_pack.py --stance Dual=<LoreRim 9011100>` with
  `--left-weapon --weapon-in-hand --bfco`: same ring of 6 and power slots as the sword stances (v15's graph serves it);
  dual chain 1-4 (slots 1 2 3 4 1 2), every dual power attack is LoreRim's one. LoreRim also has dual Low / Mid / High
  (9012100 / 9013100 / 9014100): later.
* **Switching:** the left blade's ARMO (weapon_test_pack) carries a new keyword S2S_LeftBlade; S2SCombat asks Papyrus
  Actor.WornHasKeyword every 0.5 s (supported name) and, while worn, sets the stance group to S2S_StanceDual (with the
  stance re-equip); off returns to the stance before. Stance keys while dual pick the stance for later.
* **Two hits:** LoreRim dual clips carry two HitFrames per attack (one after weaponSwing, one after weaponLeftSwing).
  The descriptor writer used to keep only the vanilla descriptor's one; it now adds the extra HitFrame / WeaponSwing
  (weaponLeftSwing -> WeaponSwing). Unresolved: whether Starfield's melee hits again on the second HitFrame; S2SCombat
  logs "player hit <target> at <t>" so a run shows one or two hits per swing (if one: plugin damage, phase 2).
