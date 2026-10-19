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
