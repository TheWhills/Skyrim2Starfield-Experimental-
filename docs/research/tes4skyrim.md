# TES Auto-Convert (bryantmh/tes4skyrim): what it does, how, and what we can use

Owner (2026-11-17): "this converter is pulling in creatures, their models, and their animations from oblivion,
morrowind, and any mod made for them and is able to convert the animations into a skyrim usable format, something there
must be useful ... also do a deep dive in general". Read from the owner's download (tes4skyrim-master, VERSION 0.689,
~980 Python files, 155 docs), docs and code read only. Every claim below cites its file in that tree; "they report"
means it is their measurement, not ours. Their own code is MIT (README "Credits & License"); `external/pynifly_hkx/`
and `external/openmw/` are GPL-3.0, `hkxcmd.exe` and the mopp bridge embed proprietary Havok: methods only from those.
Supersedes the 2026-10-19 summary in docs/armor/animation-port.md "Creatures: lessons from TES4 AutoConvert".

## What it is
A full pipeline from Morrowind, Oblivion, Fallout 3 / New Vegas (and total conversions: Nehrim, Arktwend, mods for
them) to Skyrim SE: export (pure text dump of every record) -> extract -> meshes -> SpeedTrees -> creatures -> import
(all record transforms) -> sounds -> scripts (transpiled to Papyrus and compiled) -> pack (README "Pipeline phases").
Plus five SKSE plugins for what Skyrim lacks: jail / journal (TESRuntime), the creature animation cache
(CreatureRuntime), Fallout guns, Morrowind's dialogue and scripts (an OpenMW port), and a wider Havok world
(HavokWorldSize: Skyrim's physics only works within 64 cells of the world centre). Self-described pre-alpha.

## Creatures: how they do it (docs/commentary/asset_convert_creature.md)
* **Faithful port of every layer the source has, generation of the one it lacks.** Oblivion has no behaviour graphs:
  the engine picks clips by file name, the same convention for every creature. So the graph is generated per creature
  from one template, parameterized by that creature's clip inventory (section 1-2). They report 32/32 Oblivion.esm
  creatures, 64 Morroblivion projects, and FO3 / FNV folders through the same path.
* **The creature keeps its own skeleton: no retargeting at all** (Step 3). Bone names, weights and bind matrices in
  the body meshes stay valid, which "deletes the hardest humanoid-pipeline problem" from creatures. The rig root is
  renamed to `NPC Root [Root]`: the engine binds the graph by that name, otherwise the actor is invisible.
* **Animations: .kf -> Havok .hkx** (Step 4): decode Gamebryo B-spline tracks, sample at 30 fps, split root motion off
  the accum bone (into the boundanims sidecar; Skyrim clips are in place), compress with PyNifly's spline compressor,
  write packfile XML, compile with hkxcmd; ship 64-bit (32-bit packfiles load silently as an invisible actor). They
  measured hkxcmd's own KF converter as badly lossy (median 7.4 deg) and PyNifly's binary writer as crashing Havok.
* **Events: the dispatch channel matters.** Sounds and footsteps fire only from annotations inside the animation file,
  not from the animationdata text (silent creatures until moved); sound events must be `SoundPlay.<SNDR EditorID>`;
  the damage triple (weaponSwing / preHitFrame / HitFrame) lives in the graph's clip triggers; no event from two places.
* **Footsteps are a record chain plus a matching event**: ARMA SNDD -> FSTS -> FSTP (ANAM = the event name, verbatim)
  -> IPDS -> IPCT -> SNDR; an invented tag name is silent with a perfect chain.
* **Clip roles**: by name tables first, then by the clip's AnimGroup (the sequence name inside the .kf), which is the
  real binding (section 9: 48 creature folders were sliding with no MoveForward state until this).
* **Ground speed is baked into the clip** (section 8): every vanilla creature's movement speed equals its run clip's
  natural speed at playback 1.0, so they time-scale the walk / run clips, resample onto the 30 fps grid (a 60 fps
  file "exploded" the limbs), and derive MOVT, root motion and blend anchors from the baked file. Walk and run are
  separate states with hysteresis (vanilla sabrecat shape), not one blend.
* **Death and ragdoll** were the longest fight: the graph must raise `AddRagdollToWorld` itself; the `Ragdoll`
  release is a clip trigger; the skeleton.hkx needs a per-part resource tree; mapper order, joint limits containing
  the bind pose, mass units, keyframed vs powered bodies, clip-ordinal vs file-index bugs (sections 4, Step 0).
  Morrowind rigs have no physics at all, so ragdoll bodies are synthesized into both files.
* **The animation cache conflict, solved at runtime**: Skyrim has one global animationdatasinglefile; every mod that
  adds a creature rewrote it and the last one installed won. CreatureRuntime.dll composes vanilla + one fragment per
  plugin in memory when the engine reads the file (section "Runtime animation-cache composition").
* **Method**: enumerate the engine <-> graph interface from vanilla graphs first; a donor graph only as a test jig;
  bisect one layer at a time against vanilla assets; validators for every file (`tools/creature/ragdoll_validate.py`,
  `animcache_validate`, `animdata_index_check`).
* Side tool `skyb_retarget/` puts a different mesh (Skyblivion's) on a converted creature: fit the skeleton to the
  mesh's painted weights, retarget every clip with leg IK on the source foot paths, report foot slide per clip.

## Everything else that bears on our work
| Area | What they found | Where |
|---|---|---|
| Packages | Map each source package onto the Skyrim template that runs the same procedure (Eat, Sleep, Patrol, SitTarget, UseIdleMarker, FleeTo ...), never a generic Sandbox; never author procedure trees; dump each template's input signature and copy its UNAM list verbatim (the engine looks inputs up by UNAM byte; PKCU count drives the read). A validator checks every converted PACK against its template. | docs/commentary/tes5_import_package.md 1, 10; tools/esm/pack_validate.py |
| Script-gated packages | `GetVMScriptVariable` gates read a property of a script on a reference; vanilla's resource objects use `::ResourceState_var` (our Hod sawmill case). | tes5_import_package.md 7 |
| Conditions | Function indices are remapped per game (a Fallout CTDA is 28 bytes, other numbering); only FormID params are load-order remapped; cheapest OR group first; GetInCell names a prefix family. | docs/commentary/tes5_import_conditions.md |
| NPC idles | Converting Morrowind's own NPC idle clips was switched off (pelvis lifts, travelling idles); they now place vanilla furniture / idle markers on a linked ref and point SitTarget / UseIdleMarker at it. | docs/commentary/asset_convert_animation.md "Vanilla markers for NPC animation files" |
| Human graph | New humanoid states are spliced into vanilla 0_master and the character files (HKX2E round trip); two mods shipping patched copies still collide (unsolved). | asset_convert/havok/humanoid_graph.py |
| Animated objects | Script-driven sequences get a generated per-mesh graph (a Rest start state that plays nothing, transitions on every state, the 1-bone `x_SingleBone` rig); ambient ones point at vanilla's shared Autoplay graph; Open / Close door groups must not get a graph (crash). A mesh cannot be hot-reloaded: one build per launch. | asset_convert_animation.md "Animated-object behaviour graphs" |
| Live game bridge | An SKSE plugin with a named pipe: read / write memory, call functions, read a live actor's graph variables, trace its graph (active states, events in and out) at ~120 Hz. Built because most defects were "silent binding failures" offline tools cannot see. | game_bridge/README.md, tools/live/graph_trace.py, graph_vars.py, nif_live.py |
| Testing | Hidden launch, parallel game instances, console without keystrokes, repeatable cases, a clean-room test cell. | docs/commentary/headless_testing.md, ingame_testing.md |
| Engine facts | Read out of the unencrypted GOG exe with their disassembly tools (package loader, animation cache parser, sound path handling). | docs/commentary/ck_exe_disassembly.md, tools/disasm/ |
| Determinism | Output (NIFs, the ESM, FormIDs) made byte-deterministic; FormIDs are a save-game contract. | docs/commentary/performance.md |
| Audio | Effects stay PCM .wav (re-encoding to .xwm silenced ~2000 sounds); voice is .fuz. | asset_convert_creature.md Step 4 |

## What carries over to Skyrim -> Starfield, and what does not
* **Creatures: their core strategy fits us, with one advantage and one open question.** Advantage: Skyrim creatures
  already have behaviour graphs, so the "generate the missing layer" step becomes translate (our behavior_to_agx
  prototype, 2026-10-19: horse, dragon flight / hover) or generate in Starfield's text .agx, which is far easier to
  write than Havok packfiles. Clip roles come from Skyrim's graph itself, no name guessing. Open question, now the
  first one to answer: **can Starfield take a new creature skeleton** (a Skyrim wolf / chicken / dog rig as a Starfield
  rig with .af clips on it), the way Skyrim took Oblivion's? Their whole creature path rests on keeping the source
  skeleton. Unverified for Starfield.
* **Our CK animation-cache step is their animationdata problem.** We regenerate AnimTextData (AnimationFileData /
  AnimationOffsets / DynamicIdleData) through the Creation Kit by hand each time an animation set changes, into one
  shared folder. Their two answers: understand the format well enough to write it (they byte-validated animationdata
  against vanilla), or compose per-mod fragments at runtime in a DLL. Either would remove a manual step and the
  collision between mods.
* **Events and records must match verbatim**, and the channel matters: the same lesson as our forge hammer that only
  appeared with our own enter clips. For creatures in Starfield: sound and footstep events vs Starfield's sound records
  (Starfield uses Wwise events: different records, same rule).
* **Speed bake and the 30 fps grid** apply to any creature or locomotion clip we bring over.
* **Packages: confirm Starfield's templates the same way.** We map Skyrim Eat to Starfield Sandbox because our survey
  found no Starfield Eat template; their rule (the template that runs the same procedure, signature dumped, UNAM
  copied) is what our make_schedule already does for the templates that exist; their pack_validate is a model for a
  Starfield PACK validator.
* **Hod's sawmill**: the gate is the resource object's script state, as in their census; it needs the script.
* **A live bridge for Starfield would pay off at once.** Alvor's station choice, Hilde's chair loop, whether a
  furniture binds: all "silent" today, judged by watching. An SFSE plugin reading a live actor's current package,
  sandbox target, furniture state and graph variables would turn guesses into readings. (The owner has written SFSE
  plugins before.)
* **Physics range**: their HavokWorldSize note (Skyrim physics only within 64 cells of the centre) is a question for
  our Tamriel-sized planet overlay: does Starfield's physics have a range limit? Unverified; matters before a
  whole-world build.
* **Not useful as-is**: their Havok binary tooling (Skyrim hk_2010; Starfield uses .af / .agx), Oblivion-specific
  ragdoll fixes, navmesh generation from collision (we convert Skyrim's own navmeshes), OBScript transpiling (Skyrim's
  Papyrus is far closer to Starfield's).

## Suggested next steps from this
1. Answer the creature-skeleton question on one Riverwood animal (a chicken: few bones, few clips): Starfield rig from
   Skyrim's skeleton, a few clips through our .hkx -> .af path, a scaffold graph (a vanilla Starfield creature's) as the
   test jig, then a translated Skyrim graph.
   Probe (2026-11-17, read-only): `scripts/armor/creature_probe.py` prints Skyrim's ChickenRace (path subrecords,
   NPC count, behaviour project -> character -> rig bones, behaviours, clip list) and every Starfield RACE's path
   subrecords (skeleton / rig / root graph / folder, unresolved which signature is which until the run) with
   NPC counts; `--sf-race` opens a race's rig strings and root graph.
   Owner's run, 2026-11-17:
   * Verified, Skyrim ChickenRace 000A919D (3 NPC_): ChickenProject.hkx -> Characters\ChickenCharater.hkx
     (Bethesda's spelling) -> rig Character Assets\skeleton.hkx with two skeletons, 'NPC Root [Root]' 33 bones
     (pelvis, spine, ribcage, 3 neck, head + comb + 2 wattles, 2 legs of thigh / calf ('LeftCafe') / ankle and 4 toes
     of 2 bones each) and a 7-bone ragdoll 'Ragdoll_Pelvis01'; one behaviour ChickenBehavior.hkx (58,960 bytes);
     20 clips: MT_Idle, WalkForward, RunForward, TurnLoopingL, 4 canned turns (TurnLCannedL90/180, TurnCannedFlee
     L90/180), 3 Idle_Fulbody, Idle_Head1, sit down / sitting (Idle_SitdownStart, Idle_Sitd1, Idle_SitdHeadturn,
     Idle_SitdPeck, Idle_Setgetup), GETUP, GETUPStance, AggroWarning1.
   * Verified, Starfield's creature race layout (31 RACE): ANAM skeleton .nif, NAM5 .rig, NAM6 root graph .agx, DNAM
     default animation folder; then SGNM (a subgraph) each followed by its SAPT animation folders (one or more, most
     specific first, as on HumanRace). The block repeats for the female when a race has one.
   * Verified, graphs are shared across skeletons: Creature_Root.agx (+ Creature_NonStrafing / _Strafing / _Flying)
     drives BipedA, FlyerA, HexapodA, HopperA, MantaA, MantidA, MiniBotA, OctopedeA, QuadrupedA/B/C, SwimmerA and
     Terrormorph, each with its own skeleton.nif, .rig and Animations folder; Critter_Root.agx
     (+ Critter_NonStrafing) drives Critter, FloaterA, LarvaA and ParasiteA. Supported (to test in game): a new
     skeleton with its own .rig and folder runs on an existing graph, so the chicken needs no new graph at first,
     only clips whose .afx tags are the ones the graph plays.
   * The chicken's template: CritterRace 000176B6 (11 NPC_; Critter_Root + Critter_NonStrafing, Furniture).
     Next run: `--sf-race CritterRace` lists the tags its graphs play and the .afx its folders supply, i.e. the
     list the 20 Skyrim clips have to be mapped onto.
2. Read our AnimTextData files the way they read animationdata (grammar, hashes), to generate them without the CK.
3. A small SFSE live-readback plugin: current package, sandbox target, furniture, graph variables of a ref.
4. Check Starfield's physics range on the planet before scaling up.
