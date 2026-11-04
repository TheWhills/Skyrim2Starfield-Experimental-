# Decisions (local AI team)

Format: date, decision, why, alternatives considered.

## 2026-10-12 Terrain test travel: every teleport at most 2 cells per axis, terrain waypoints instead of hops (Claude, proposed)
Plans for the terrain runner keep every teleport within 200 m along each axis (at most 2 Starfield cells whatever the
overlay's merge offset): legs longer than 185 m get open terrain waypoints that are judged like the probes, and
`hop_m` 200 stays as a safety net. Why: in the overlay runs so far, teleports of at most 2 cells per axis landed 144 of
145 times and those of 3 or more relocated the player ("Boundary Reached") or hung 11 of 28 times
(`scripts/terrain/teleport_audit.py`, **supported**); distance alone does not separate them. Waypoints rather than
hops, because the runner's step timeout (150 + 90 s per point) does not count hops. Alternatives: `hop_m` 200 alone
(core64c's entry 1 would run past its timeout), splitting entries (at best 79 s of margin), per-axis hops in the
runner (a runner change, not on the integration branch). Evidence: docs/terrain/core64c.md "Teleport rule".

## 2026-10-12 Whole-core objects: one archive below 4 GiB with capped textures, not a region split (Claude, proposed)
core64c selects 649,596 convertible Fallout4.esm exterior references of the 64-cell core and places the 648,358 whose
models convert (1,238 belong to the 118 models that do not) in core64's plugin, and ships every
converted file in one stored `<plugin> - Main.ba2`, with converted textures capped per kind by dropping top mip levels
(color 1024, normal 512, rough 256, opacity 512 px; `convert_batch.py --max-texture`, off by default). Why: every large
vanilla archive stops just below 4 GiB (whether the engine reads past it is unresolved); full resolution needs about
8.5 GiB; the runner's installer packs one archive; the 11,769 models share 2,632 materials over the whole map, so a
split into 15 regions of 1.6 km would need 28.8 GiB and its four central regions would still exceed 4 GiB each; C:
has too little room for a full-resolution build plus its temporary archive. Alternatives: cap 512 everywhere (1.66
GiB, blurrier albedo), one plugin's Main + Textures archive plus a carrier plugin at full resolution (needs a
per-plugin installer and an in-game check), region plugins (above). Evidence: docs/terrain/core64c.md.

## 2026-10-11 Commonwealth terrain: one large overlay, a grid of overlays as fallback (Claude, proposed)
Plan the whole-map terrain as one overlay worldspace holding the playable Commonwealth plus 1 to 2.5 km around it
(64 to 90 Starfield cells, Absolute alignment), registered on a hidden host planet at a measured lat/long; fall back
to a grid of 14-cell overlays generated edge to edge if large overlays fail in game. Why: one landing is 100 cells
(game terrain width, 5-cell buffer), so the full 114-cell LAND grid never fits; a single overlay has no seams, while
every overlay seam has a 1-cell merge ring of unknown behaviour; both are built by the same generator
(`scripts/terrain/make_cw_overlays.py`). Alternatives: a custom planet surface made of our blocks (exact far terrain,
but four unknown height / blend rules and a planet to build), static mesh tiles (exact, but new collision, material
and LOD pipelines). Gates: an uncompressed rerun of exp2b (exp2b3) must read our BTD heights (exp2b's packed BTD
read flat at its minimum; cause unresolved, packing is one hypothesis), then exp3 (2 x 2 grid: seams, where the tiles
sit, measured from heights since our anchors do not merge), then a 64-cell core overlay. Evidence:
docs/terrain/commonwealth-scale.md.

## 2026-10-11 FO4 terrain heights: own Python reader following fo4land, Mutagen as the cross-check (Claude)
`src/fo4sf/fo4land.py` reads LAND/VHGT with the algorithm of fo76utils `fo4land` (MIT); `dotnet/Fo4Land` decodes the
same cells through Mutagen as a second, independent parse. Why: fo4land needs scons + a C++ compiler, which this
machine lacks and the rules forbid installing; its output is 16-bit normalised (0.81-unit step for the Commonwealth)
and drops the shared 33rd edge vertex we need for seam checks; Python fits the converter and unittest stack.
Alternatives: build fo4land (blocked), Mutagen only (C# outside the Python pipeline), extend Codex's Fo4Export
(not ours). Evidence: docs/terrain/source-patch.md.

## 2026-10-09 Enforce local concurrency with a proxy, not with prompts
OpenCode has no cross-agent concurrency limit for a provider. A small stdlib-Python proxy (:1235) in front of
LM Studio (:1234) admits at most 1 inference request at a time after a resource check, queues the rest, and logs
every decision to SQLite. Agents get per-agent model aliases so usage is attributed without OpenCode changes.
Alternatives: LM Studio's own parallel-request setting (no resource checks, no attribution); an OpenCode plugin
(more coupling to an evolving plugin API).

## 2026-10-09 Thresholds adjusted for a resident model and for game tests
The owner's starting thresholds (70 / 85 / 95 VRAM / 90 RAM) apply as given to RAM. For VRAM, a loaded model
permanently holds most of the 12 GB, so with a model resident the restrict level starts at 92% (block stays 95%).
While Starfield runs, local inference is blocked (`game_blocks_inference`): measured 2026-10-09 with the game in
Parsons: VRAM 83%, GPU 99%, RAM 85%, which leaves no room for a model and would distort game tests. All values
are in tools/ai-team/config.json and are starting points to adjust from observed behaviour.

## 2026-10-09 One model, aliases per agent
One loaded model is shared by all local agents (12 GB VRAM cannot hold two). The alias decides only attribution.

## 2026-10-09 Lead does not edit code
The Lead's `edit` permission is limited to docs/ai/**; implementation happens in the implementation agent's own
worktree. `subagent_depth: 1` and `task: deny` on the specialists prevent delegation chains.

## 2026-10-09 Local model: Qwen3-14B Q4_K_M
Chosen by Claude and Codex on #32 (owner asked the agents to decide; Grok not yet answered). Fits the 12 GB card
fully with a 16K context; the 30B-A3B coder model is tested only if 14B fails the tool-calling eval, and only with the
game closed (it needs CPU offload). File: lmstudio-community/Qwen3-14B-GGUF, Qwen3-14B-Q4_K_M.gguf, 9,001,753,376
bytes, SHA-256 712c0791...c58555 (matches Hugging Face). Downloaded with curl because `lms get` stalled at 0 bytes.

## 2026-10-09 Lead may wake idle remote agents (owner request)
The owner asked the local Lead to start Codex and Grok itself. `tools/ai-team/wake_agent.py` forks the agent's most
recent session (full history, new session id) and runs one headless turn with the Lead's brief (`codex exec fork`,
`grok -c --fork-session -p`). Forking avoids writing into a session file an open window may hold; nothing is typed into
any window. Deterministic guards: refuses if the agent was active in the last 10 min (two writers in one repo) or
was woken in the last 30 min (their usage comes from the owner's plans); every attempt is logged (wakes.jsonl).
Alternatives: keystrokes into the agents' terminals (focus stealing, wrong-window risk); GitHub comments only (agents
don't poll while idle).

## 2026-10-20 Combat SFSE plugin: game-independent core in C++ under native/combat
The combat features Skyrim modding gets from SKSE plugins (Payload Interpreter commands, MCO / BFCO input buffer
and charged attacks, TK Dodge, i-frames, TDM lock-on, Key Utils / Stances key table) need an SFSE plugin in
Starfield. Its logic lives in `native/combat` as plain C++20 with no game types (MIT, like the repo), tested on any
platform (tests/test_native_combat.py builds and runs it); the SFSE glue (input hooks, animation-graph event sink,
camera, damage) will link it with CommonLibSF (libxse; GPL-3.0-or-later with a modding exception and a GPL linking
exception) and is built on the owner's PC with Visual Studio's tools: Microsoft's downloads are blocked from the
cloud workspace, so no Windows cross-build here (checked 2026-10-20). Behaviour is written from the mods' data formats
and documented behaviour only; no code from TDM (GPL), IFrame Generator (no-port permission) or other mods is used.
Alternatives: Papyrus (cannot read keys, runs late), one plugin per feature (more hooks fighting each other).

## 2026-10-20 Combat SFSE plugin, game side: thin glue over a tested controller
`native/combat/sfse` (xmake, CommonLibSF as a git submodule pinned to the commit the draft was checked against) only
translates: input events and the player's animation-graph events go into `s2s::combat::Controller` (core, tested
anywhere), its commands come back out and run on the main thread through SFSE's task interface. Choices:
* Hooks patch the vtables read from the live objects (UI's input receiver; the player's
  BSTEventSink<BSAnimationGraphEvent> at +0x50) at kPostDataLoad, instead of Address Library vtable indices (the
  VTABLE id arrays are not in declaration order; the live object has the right one by construction).
* Graph variables are set through Papyrus (`ObjectReference.SetAnimationVariable*`, dispatched by the VM, a frame or
  two late): CommonLibSF maps no setter and the Fallout 4 lineage has non-virtual ones whose Starfield addresses are
  unknown. Replace with the native setter once found. Keywords (stances) and the interim i-frames (`Actor.SetGhost`)
  use Papyrus for the same reason.
* Unverified details (event layout, press / release convention, stick axis, per-frame tick) are logged on the first
  run rather than guessed silently (sfse/README.md lists what each log line answers).
* `scripts/guard.py` skips paths registered in .gitmodules: submodule files are not part of this repo's history
  (CommonLibSF's generated ID headers exceed the size limit).
Alternatives: Address Library vtable indices (index order unknown); a Papyrus-only plugin (cannot read keys).

## 2026-10-21 NPC faces: fit Starfield face dials to Skyrim's baked FaceGen heads
Converted NPCs get Starfield face dial values solved by bounded least squares so the Starfield head (skinned to its
face bones) matches each NPC's baked Skyrim FaceGen head, carried across through a one-off alignment of the two base
heads (docs/npc/README.md). No per-NPC hand work, no new meshes per NPC, faces stay editable in Starfield's chargen.
Vanilla slider files by default; a face-bone mod's (More Sliders) as an option, since it would make every converted
NPC depend on that mod. Alternatives: translating Skyrim's 19 NAM9 morph values directly (they describe offsets from a
race head Starfield does not have, and miss the race head and preset shapes baked into FaceGen); shipping each NPC's
Skyrim head mesh (thousands of meshes, no chargen, Starfield's head shaders and morphs lost).

## 2026-10-21: interiors are built in batches into one plugin, with a source map
Skyrim interiors are converted many at a time (`make_skyrim_interior.py batch`) into one PluginSpike run: one model
conversion, stable FormIDs as before, load doors linked only when both ends are in the batch, navmesh links kept inside
the batch. PluginSpike writes `source_map.json` (Skyrim form key -> new FormKey) as the single lookup for later steps
(NPCs, furniture, packages, locations) instead of each step re-deriving the formids.json keys. Load doors get their own
DOOR base per model (no animation graph) rather than reusing the static, because XTEL needs a door base.

## 2026-10-22: Skyrim collision becomes native Starfield compressed meshes
Skyrim models no longer get box approximations of their collision by default: the decoded Skyrim triangles are encoded
as Havok compressed meshes (`cmsencode`, format measured on FO4 files) and written by the FO4 path's writer, one body per
Skyrim body with its collision layer. Reason: boxes cannot represent ramps (voxel ledges up to ~0.47 m blocked Alva's
cellar stairs in the analysis), activation rays hit collision so approximations move door prompts, and the FO4 path
proved native collision in game. Boxes remain as `--box-collision` and as the per-model fallback.

## 2026-10-23: stair-helper ramps over Skyrim step collision
Starfield's character controller does not climb Skyrim's step collision smoothly (owner: "runs into each step").
Instead of editing the steps, native collision adds a separate ramp body through the step nosings on the stair-helper
layer (31), as Bethesda does in their own content: actors walk a slope, items and projectiles still meet the steps.
Found geometrically (flat narrow parallel treads, consistent rise / run, 3+ steps); models that already have stair
helpers keep only theirs. Layer 31 verified in game (owner, 2026-10-23); the layer stays an option.

## 2026-10-23 — Combo power attack: keep the key from the game's controls (PlayerControls::Manager)
- Owner: after the correct combo power attack the game still played its standing power attack (MeleeAttackPower_A).
  Zeroing the V ButtonEvent in UI's PerformInputProcessing did not stop it (verified, owner's run): UI is not where the
  gameplay controls read attacks.
- Now the plugin also hooks PlayerControls::Manager's BSInputEventReceiver::PerformInputProcessing (slot 1). The 9
  vtables come from CommonLibSF's Address Library IDs (RE::VTABLE::PlayerControls__Manager); which one is the
  BSInputEventReceiver base is read from MSVC RTTI at run time (core `rtti_base_vtable`, synthetic test), so a wrong
  guess logs a warning and patches nothing.
- The power key press while an attack runs (`Controller::hides_power_press`), its repeats and its release are unlinked
  from that receiver's event list for the call and linked back after: the shared events are no longer mutated (the UI
  zeroing is removed), UI and other receivers still see them.
- Status: supported (Fallout 4's PlayerControls is a BSInputEventReceiver), unresolved until the owner's run. Log lines:
  "player controls: input receiver hooked ..." and "power attack key kept from the game's controls".

## 2026-10-23 — Combo power attacks use a plugin-only graph event (S2S_ComboPower)
- Owner's run with the PlayerControls hook: the hook went in ("PlayerControls::Manager vtable 6 of 9") and the V
  press was kept from the game's controls on every mid-combo press (verified, log), yet the standing power attack
  still started when the combo power attack's clip ended: an AttackStart with no key press and no plugin command,
  1.4-1.7 s after the combo power started, with no AttackEnd in between.
- The only graph path to that clip is top-level None -> MeleeAttackPower_A on MeleeAttackPowerStart, so the game
  sends that event when the combo ends. Supported hypothesis: the game queues it because the plugin's own
  MeleeAttackPowerStart reached the graph (not because of the key).
- Change: the stance packs' combo -> power transitions now listen to S2S_ComboPower (bfco_combo power["event"],
  stance_pack.power_routing), and the plugin sends sComboPowerEvent (default S2S_ComboPower) for mid-combo power
  attacks. The game's own MeleeAttackPowerStart (standing V) is unchanged. Older packs: sComboPowerEvent =
  MeleeAttackPowerStart.
- Owner, same day: worse (the power attack came late and several looped in a row). Reverted to MeleeAttackPowerStart
  in the packs and the plugin default; the event stays configurable (sComboPowerEvent, power["event"]).

## 2026-10-23 — Cancel the game's queued standing power attack (bCancelQueuedPower)
- Owner's log of the S2S_ComboPower run: every "S2S_ComboPower" was "not taken by the graph" (supported: Starfield
  graphs only take event names they know), so mid-combo V did nothing; yet the game still started standing power
  attacks later, one after another (AttackStart with no attack press and nothing sent by the plugin), with V kept
  from PlayerControls::Manager. So the game learns of the V press some other way and queues one standing power attack
  per refused press; the graph event was not the trigger (the earlier hypothesis is withdrawn).
- Change: the plugin counts mid-combo V presses; an AttackStart within fQueuedPowerWindow (3 s) of the last such press
  or cancel, not preceded by a plugin send (0.15 s) and with no attack press around it (checked 50 ms later: the
  press logs a few ms after its AttackStart), gets sQueuedPowerCancelEvent (ActionInterrupt). The stance packs add
  top-level MeleeAttackPower_A -> idle and MeleeAttackCombo -> idle on ActionInterrupt (an event the graph already
  knows: idle -> idle). A standing V press clears the count. Status: unresolved until the owner's run; expect a few
  frames of the queued attack before it blends out.
- Owner, same day (stance pack v5): verified - the extra standing power attack after a combo no longer plays.

## 2026-10-23 — Hosted power attacks lacked root motion: zero-g host flags
- Owner: in a power -> power chain the third / fourth power attack sometimes does not step forward. Their clips do
  carry root motion (report: 0.9-2.0 m); their hosts are the zero-g descriptors (ZeroG_MeleeAttackPower_A / _A / _B /
  _C -> tags MeleeAttack03 / 04 / MeleeAttackPower01 / 02), flagged "Motion Driven" (only zero-g descriptors carry
  it) or nothing, while every working attack (standing A / B / C, sneak hosts) is flagged "Allow Rotation".
- Change: hkx_to_af's "tag:" retag (every reused host) applies af_writer.ground_flags: "Motion Driven" off, "Allow
  Rotation" on, other flags kept. Verified in game (owner, pack v6): every power attack in a chain steps forward.
- Owner's log (pack v6, 15:41): every mid-combo V "taken by the graph"; 3 queued standing power attacks cancelled,
  each "ActionInterrupt -> taken by the graph" (verified). Stance re-equip still logs "unequip ...: refused" from
  ActorEquipManager::UnequipObject while the stance applies and the equip reports done (return value meaning
  unresolved, behaviour verified). The first-click attack-start burst of the S2S_ComboPower run did not recur (one
  AttackStart / AttackEnd 0.000 pair only).

## 2026-10-23 — Full-body dodges on known event names (stance pack v7)
- TKDodgeBack was "not taken by the graph" (no dodge states installed; and new event names are refused anyway).
- Vanilla graphs read for routing: Player_Melee's Switch over MeleeAttacks goes to "Attacking" on
  MeleeAttackPowerStart / MeleeAttackSprintStart and back to "Idle" on AttackEnd / ActionInterrupt / BlockStart /
  JumpStart (a Blend Node lists the same two events); MeleeEventControllers discards MeleeAttackPowerStart while
  bDontAllowPowerAttack (likely why the game re-sends queued power attacks). MeleeActions is layered over locomotion,
  so a dodge there would lose the legs while moving.
- Change: dodge_graph --attacks-graph puts one dodge state per direction at the top of MeleeAttacks (copies of the
  standing power attack, no weapon-speed multiplier), entered from idle / combo / attacks / dodges on NPC melee attack
  events (MeleeAttack01 forward, 02 back, 03 left, 04 right: known names the game never sends to the player), back
  to idle on clip end (AttackEnd ends the plugin's dodge too); Player_Melee's two attack lists learn those events.
  dodge_pack.py converts TK Dodge RE's step dodges (root motion 5.4 / 3.9 / 3.3 / 3.3 m) as new clips S2S_Dodge* in
  onehanded\player (needs the CK GenerateAnimInfo run; the CK reads tags from the graph). Plugin: sDodgeEvents
  (defaults to those events), dodge sends count as plugin sends for the queued-power cancel.
- Status: unresolved until the owner's run. Open: whether NPC event names are known for the player's graph.
- Owner's run (v7): the Creation Kit's AnimationFileData listed no S2S_Dodge*.af although v7 was the only enabled melee
  pack and the run was fresh (verified, owner's checks). The same caches do list the new s2s_stances folders' files.
  Supported: the CK lists loose files only for folders the archives do not already hold. Also verified on a cache of
  the owner's: AnimationOffsets only lists the vanilla graph's tags (no MeleeAttack_D / 03 / Power01...), yet those
  hosted tags play in game, so a new tag needs its file listed, not an offsets entry.
- Change (pack v8): the dodge clips take existing vanilla paths in onehanded\player (Sneak_ThrowGrenade / ThrowMine /
  CastSelf / CastTarget, retagged S2S_Dodge*), already in the caches; no CK rerun needed for them.
- Owner's run (v8, sneak throw / cast hosts): every dodge event "taken by the graph" (verified: the NPC attack event
  names work for the player), but each dodge state ended 0.1 s later with AttackEnd 0.000 and the player glitched:
  the clip was not found (supported: sneak-prefixed vanilla files in onehanded\player are not in the stance entries'
  AnimationFileData, while the moved sneak hosts in the s2s_stances folders are).
- Change (v9): S2SStances.esm gets a shared folder actors\...\melee\s2s_stances\common, listed after each stance folder
  and first in one neutral copy of every player weapon row (no stance keyword, after the stance entries, before the
  vanilla ones; ordering against the vanilla rows unverified). The dodges are new clips there. Needs the esm rebuilt
  and the CK GenerateAnimInfo run. Status: unresolved until the owner's run.
- Owner's run (v9, esm rebuilt, fresh CK run with 236 AnimationFileData files): still no S2S_Dodge in AnimationFileData.
  Supported: the CK does not scan folders; it probes each folder for clip names it knows (the graph's tags and their
  Sneak_ / ZeroG_ variants; an earlier cache lists s2s_stances\mid\MeleeAttack_A.af and sneak_meleeattack_a.af in
  the vanilla names' case, never a name of ours), which also explains every earlier "new file not found".
- Change (v10): the dodge clips in s2s_stances\common are named Sneak_MeleeAttack_A / _B / _C / Sneak_MeleeAttackPower_A
  (descriptor tags S2S_Dodge*). Sneak variants, not plain graph tags, so AnimationOffsets (tag -> first folder holding
  that file name) cannot point the standing attacks at a dodge in the neutral entries. No esm change from v9.
- Owner's run (v10): s2s_stances\common is in AnimationFileData (verified), every dodge event taken, but each dodge
  state still ended after 0.1 s (AttackEnd 0.000), in the stance the save had and in Mid. Supported: clips are found
  by file name, first listed folder wins, and every stance folder already holds Sneak_MeleeAttack_* hosts of its own.
- v11 (diagnostic): Forward / Back / Left use the zero-g stagger names (only in onehanded\player, after the shared
  folder); Right keeps Sneak_MeleeAttackPower_A. Expected if right: W / S / A dodge in every stance, D only in neutral.
  If all four still end at 0.1 s, the dodge states themselves (graph) are at fault, not the clip lookup.
- Owner's run (v11): every dodge (W / A / S / D, neutral and a stance) still ended at 0.1 s; and the neutral combo power
  attacks went wrong. Two causes found in the log: (1) the queued-power cancel took a real combo power attack whose
  AttackStart came 0.15 s after the plugin's send (window was 0.15 s): window now 0.5 s (kOwnSendWindow, synthetic
  test); (2) v11's Sneak_MeleeAttackPower_A in the shared folder (first in the neutral entries) shadows the neutral
  power host of the same name: names must be unique across the folder list (dodge_pack.names, three zero-g names).
- The dodge failing with unshadowed names too points away from the clip names. v12 (diagnostic): Forward plays the
  pool tag MeleeAttack_D, Back the standing power MeleeAttackPower_A (both play in combos), Left / Right the converted
  dodges. If Forward / Back also end at 0.1 s, the dodge states (graph) are at fault.
- Owner's run (v12): standing Alt (Back, playing MeleeAttackPower_A in the dodge state) plays the power attack in full
  (verified): the dodge states, their events and the Player_Melee switch work; what fails is finding our clips.
- Owner shared Dodge Framework SFSE (Nexus 16111, read for approach only): it moves the player from code (dodge speed,
  duration, end speed) and plays existing idles by console (player.playidle Human_Root_Gravity_Off / On) - no new
  animation files. A fallback if converted clips cannot be found.
- Hypothesis now: clip tags, like events, must be names the game already knows (every working hosted tag is a vanilla
  name: MeleeAttack_D / _E / 01-04 / Power01-02; every failing one ours: S2S_Dodge*). v13: Left's converted clip is
  tagged MeleeAttack05 (vanilla NPC tag, unused by the packs), Right keeps S2S_DodgeRight as the control.
- Owner's run (v13): Alt+A (converted left dodge, tag MeleeAttack05) played a dodge-like move; Alt+D (tag
  S2S_DodgeRight) snapped back; standing Alt and Alt+W played the power attack (diagnostic tags). Verified: clip tags,
  like graph events, must be names the game already has.
- v14: all four dodges on vanilla human tags the player's melee graph never plays (TAGS: MeleeAttack05, FireSingle,
  FireAuto, FireAutoPush - NPC melee / player gun tags from the CK's AnimationOffsets), files under four zero-g-only
  names in s2s_stances\common (NAMES; a stance FileData lists each once, in a vanilla folder after the shared one).
- Owner's run (v14): all four dodges play (verified). The left one (tag FireAuto) repeated until something else took
  over (no AttackEnd): the game loops that tag. v15: Left on MeleeAttackBash (player / NPC gun bash tag).
- Owner, v15: all four dodges work (verified).

## 2026-10-23 — Lock-on: find the actor array in ProcessLists at run time
- CommonLibSF's ProcessLists::highActorHandles (+0x58) was always empty on 1.16 (owner's runs); its handle resolution
  (BSPointerHandleManagerInterface::GetSmartPointer, ID 35638) is mapped.
- Change: core scan_handle_arrays / read_handle_array (synthetic test) read every 8-byte offset of the object as a
  BSTArray in either layout and keep the plausible ones whose handles resolve to actors; Lock.cpp uses the array with
  the most actors (re-scan at most every 2 s while none), logs the arrays found ("lock-on: actor arrays in
  ProcessLists: ..."), then the player's-cell fallback as before. Caps Lock (58) added as a keyboard lock key.
- Unverified: whether the steering (writing the player's angle) turns the player and camera. Status: owner's run.
- Owner's run: four handle arrays found in ProcessLists - +070 (1238 handles: every actor; resolving them froze the game
  ~3 s per press) and +060 / +080 / +090 (21-26, verified actors) - but "no target among 1238". Change: only arrays of
  at most 512 handles are used, together and de-duplicated; the no-target line now lists the nearest four (distance,
  alive, screen position) to settle the distance units (fMaxDistance 28 taken as metres) and the screen test. Caps
  Lock dropped as lock key (it is Starfield's walk / run toggle, owner); a commented keyboard example instead.
- Owner's run: targets found and locked (NPCs at 3-26 m: distances read as metres look right, verified roughly by the
  owner's play), but frame time went to 5-36 ms while locked: every frame gathered all ~76 actors. Change: a full
  gather only on the lock / switch key (it records each actor's handle); while locked only the target's handle is
  resolved each frame. A "following" line every 2 s logs distance and yaw / pitch error, to check the steering (owner:
  the camera locks onto "something").
- Owner: the player turns toward the target but the camera does not follow - Starfield's third-person camera keeps its
  own rotation (supported; CommonLibSF maps PlayerCamera's states array but not ThirdPersonState's fields). Change:
  bSteerPlayer (default 0) so the player no longer spins; a camera probe logs, every 0.5 s while locked (8 times), the
  camera root's world rotation and the third-person state's angle-like floats that changed (state checked against
  ThirdPersonState's vtable), to find the yaw / pitch field to steer. Unresolved until the owner's run.
- Owner's camera-probe run: verified ThirdPersonState vtable and "current"; ThirdPersonState +0x170..+0x17C is a unit
  quaternion (w, x, y, z) = Rz(-yaw) * Rx(-pitch) of the camera's world rotation: its yaw matches the camera root's
  forward row (world.rotate row 1, 3x4 floats) to ~0.1 deg in two samples 43 deg apart, while the player's heading
  stayed behind (the camera turns on its own). Core camera_angles / camera_quat (tests from the logged values).
- Change: while locked the plugin steers that quaternion toward the target (yaw rate 8, pitch rate 2, mouse adds on
  top); picking (crosshair, score) uses the camera's view; bSteerCamera = 1, bSteerPlayer = 0, probe off by default.
- Owner's run (camera steering): FPS dropped and the camera did not stay on the target (yaw error 2-41 deg). Frame
  time ~1.1 ms while locked: memory checks (VirtualQuery) on every frame. Change: ThirdPersonState checked at most once
  a second, the per-frame target resolved without a memory check (handles only resolve to live objects). Diagnostic:
  "camera write check" (what was written last frame vs what the camera holds now; 10 per lock) and the camera probe
  back on for 8 samples, over 0x400 bytes without the angle-size filter, to tell "the write is overwritten each frame"
  (then the real source is elsewhere) from "the write holds".
- 2026-10-23 lock-on holds (verified partly: owner's run after the yaw-float write locked onto the NPC looked at, but
  loosely: mouse moves pulled the view off and it slid back, and the crosshair sat beside the NPC). Changes:
  bHardLock (default 1) sets the view to the target's angles every frame instead of easing at fYawRate/fPitchRate;
  bBlockLook (default 1) hides mouse moves and the right stick from PlayerControls while locked (supported, not
  verified: the controls' look handler is what turns the camera); bAimFromCamera (default 1) aims from the camera
  root's world position (+0xB0) instead of the player's eye, since the crosshair is on the camera's ray. The target is
  re-validated every 0.25 s, its position read each frame.
- 2026-10-25 lock-on pitch: owner's screenshots show the yaw held on the target but the view's height stayed where it
  was at lock time. The camera's own yaw floats are written, but no pitch float was found in ThirdPersonState; the
  lock now also writes the player's pitch (angle.x) whenever it steers the camera (supported, not verified: Skyrim's
  third-person camera takes its pitch from the player). The write check logs the player's pitch to confirm.
- 2026-10-25 lock-on pitch, second try (owner's log): the player's angle.x read back 0 every frame while the camera's
  pitch climbed to its 79 deg limit, so in third person it is a per-frame look input the camera adds and the game
  zeroes (supported). The lock now writes a capped share (fPitchGain 0.5) of the remaining up / down error there each
  frame; the quaternion keeps the current pitch. ThirdPersonState / PlayerCamera memory checks run only when those
  objects change (timing showed 14-24 ms frames while locked).
- 2026-10-25 lock-on verified on the owner's run: the view holds the NPC's centre on both axes (pitch through the
  player's look input). Owner asked for TDM's smooth start and no lock on corpses: a new target now eases in at
  fAcquireRate (10 / s) until within 2 deg or fAcquireTime (0.6 s), then the hard hold takes over. Death already
  released the lock (core: !alive, checked every 0.25 s via Actor::IsDead's kDead bit, not verified on 1.16); the
  release now logs "target died" and lock / release lines are no longer capped by iLogTargets.
- 2026-10-25 lock-on ease-in stall and corpses (owner's log): the camera's yaw floats sit ~0.55 deg off the view's yaw,
  so writing the absolute angle pulled the view back 0.55 deg a frame; from the left the ease-in stalled ~3 deg short
  until the 0.6 s limit snapped it ("half, pause, other half"). The floats are now moved by the wanted step instead.
  Actor::IsDead (kDead bit) stayed false on a killed NPC (the lock held and re-locked the corpse): a target also counts
  as dead at Health <= 0 (ActorValueOwner::GetActorValue, supported; its health is logged on lock and as it changes).
- 2026-10-25 lock-on: death release verified (owner: dead NPCs no longer locked; Health <= 0). Up / down ease-in still
  looked abrupt or absent, so the ease-in is now a timed smoothstep curve (fAcquireTime 0.4 s, fAcquireRate removed)
  from the view at lock time to the target, the same on both axes (TDM-like); pitch follows the curve through the look
  input at fPitchGain. A frame-by-frame trace of the first three ease-ins shows view / curve / target / input.
- 2026-10-25 lock-on ease-in verified (owner: "working great"; trace: the view follows the 0.4 s curve within 0.4 deg
  on both axes, no overshoot, lands on the target and holds). Remaining cost: one ~17 ms frame on the lock key (the
  full actor gather), ~7 us per frame while locked.
- 2026-10-25 blocking (owner: vanilla block works; wants timed block / parry and block-hit reactions). Hit events: the
  TESHitEvent source has no GetEventSource ID on 1.16, but its class vtable is mapped, so the game image's writable
  pages are searched once for objects with that vtable (find_vtable_objects; supported, logged) and the existing hit
  sink is registered through BSTEventSource::RegisterSink (mapped). Parry (core, tested): a blocked hit within
  fParryWindow (0.25 s) of the block going up (iWantBlock rising, polled per tick), once per press, gives back the
  health lost (next ticks, within 0.3 s, up to the most health held over the window) and sends the attacker the first
  of sParryEvents its graph takes (StaggerStart: Player_Melee's Stagger Meter listens to it; recoilStart /
  recoilLargeStart are Skyrim's names; which one works is unverified, the log says). Block-hit recoil: the DBH clip
  pack now also covers onehanded/player/ (the player's own folder holds a vanilla MeleeBlock_HitReaction).
- 2026-10-25 block, owner's first run: the hit source was found by vtable (+5977F40, 45 MB in 9 ms) and events arrive,
  but target / cause at CommonLibSF's +F0 / +F8 read null: the 1.16 layout differs. The sink now looks for actors in
  each event (8-byte pointers whose RTTI class is Actor / PlayerCharacter, in order: first = target, next = attacker;
  and 4-byte handles), logging the first six events slot by slot to fix the layout. Block / hit / stagger animation
  events are logged past the general cap (is_combat_reaction_event) to see what a blocked hit does (owner: the guard
  drops instead of recoiling). Owner: the block raise is slow (vanilla: 0.3 s blend + 26-frame MeleeBlock_Into) where
  Skyrim's is near-instant; block_pack.py ships MeleeActions with BlockStart blends 0.1 s / BlockStop 0.15 s, and
  hkx_to_af.py --fit makes MeleeBlock_Into Skyrim's block pose in 0.15 s (MeleeBlock_Out its ready idle in 0.2 s).
  The parry window counts from the block press (iWantBlock), not from the raise animation.
- 2026-10-25 TESHitEvent 1.16 layout verified (owner's log, both directions): hit data aggressor handle +0x40, target
  handle +0x48 (CommonLibSF +0x40 / +0x44); the event's target / cause pointers are null. The sink reads those handles
  (combat::hit_handles); the slot dump stays as a fallback when they do not resolve. Parries never fired before this
  (no hit on the player was recognised). Owner: hit while blocking -> "I stop blocking": the log shows the block-hit
  state did play (StartAnimationDriven + its BlockUp sound right after each hit), so the Dynamic Block Hit recoil (arm
  knocked out, 1.1 m push) reads as a broken guard. SkyrimBlock_fast_v2 uses Skyrim's own 1hm_blockhit (a flinch that
  stays in guard, no push) as MeleeBlock_HitReaction instead.
- 2026-10-25 block, third run: hits on the player now arrive (attacker and attack event read: MeleeAttack01-04,
  MeleeAttackPower02), but every one logged "blocking 0": iWantBlock is the graph's AI switch ("Transition for AI
  needing to Block without event"), not the player's block. Blocking is now the block key (SecondaryAttack / right
  mouse, for the first 0.4 s: the guard coming up) or bIsBlocking (the State Variable of MeleeActions' block states) or
  iWantBlock; changes are logged. The timed-block window starts on the key press. Owner's definition: a timed block
  negates all damage (it does: the health is given back) - "parry" renamed timed block in the log and INI
  (fTimedBlockWindow, fParryWindow still read); it also shows sTimedBlockMessage (Debug.Notification, supported) until
  a spark effect exists (Simple Block Sparks' Skyrim particle NIFs do not carry over; a vanilla Starfield impact
  effect is the likely route). Held-block hits give back fBlockReduction (0.6) of the damage.
- 2026-10-25 crash on the first blocked hit (owner's log ends right after "iS2SBlockHitType = 1 dispatched"; blocking
  was recognised for the first time: key, then bIsBlocking, both verified moving). Two first-time calls follow such a
  hit: SetAnimationVariableInt for a variable the graph does not have (Papyrus) and the held-block give-back through
  ActorValueOwner::ModActorValue (native vfunc, slots unverified on 1.16). Both removed from the path: the give-back
  (and stamina damage) now go through Papyrus ObjectReference.RestoreValue / DamageValue, and sBlockHitVariable is
  empty in the shipped INI until variants exist.
- 2026-10-25 timed block verified (owner's log: four timed blocks 0.17-0.24 s after the press, 21 of 21 health given
  back each time, the attacker's graph took StaggerStart - the "recoil" the owner saw; held-block hits gave back 13 of
  21). The damage still lands for a frame before the give-back (no mapped damage hook). Guard drop verified in the log:
  bIsBlocking turns off ~0.3 s after every blocked hit (timed or not) with the key still held - the 1.16 game or graph
  leaves the block states after the hit reaction. While the key stays down, the plugin now sends BlockStart again
  (sBlockReraiseEvent, every 0.3 s at most, for 1.5 s after the hit; supported: BlockStart is the graph's entry event).
- 2026-10-25 timed-block sparks (owner: hard to tell when a timed block lands; asked for a Simple Block Sparks-like
  effect). Simple Block Sparks' Skyrim particle NIFs do not carry over, so the plugin plays one of Starfield's own impact
  effects: Papyrus ObjectReference.PlayImpactEffect(ImpactDataSet, node "Weapon", pick direction toward the attacker,
  3 m) - supported, not verified (FO4's signature). Which ImpactDataSet: sTimedBlockEffect, or the best spark-named set
  found once per session by looking up form IDs 1..0x3FFFFF (TESForm::LookupByID, GetFormEditorID; both logged with
  the time taken, bListEffectForms = 0 skips it). Also Game.ShakeCamera(None, 0.4, 0.15) and the notification.
- 2026-10-25 owner: on a timed block the attacker recoils, but Skyrim's timed block "zeros out damage and creates an
  effect". Vanilla Skyrim has no timed block; it comes from mods - Valhalla Combat (dTry, Nexus 64741: timed block
  ~0.3 s after raising the guard negates melee damage and deals stun damage; perfect block ~0.15 s also restores stamina
  and staggers / recoils the attacker; spark effects credited). Split the same way: fPerfectBlockWindow 0.12 s - only a
  perfect block sends sParryEvents; every timed block negates and shows the feedback. The owner's log: timed blocks lost
  no health at all (nothing to give back). Spark search: 275 impact data sets, none with "spark" in the EditorID; the
  scorer now also takes "metal", and all impact-set names are logged to pick one by hand.
- 2026-10-26 sparks: the game keeps no EditorIDs for impact data sets at run time (owner's log: 275 sets, every
  GetFormEditorID empty), so they cannot be picked by name. sTimedBlockEffect now takes a form ID, and a preview pair of
  keys ([ / ], iEffectPrevKey / iEffectNextKey) plays each set onto the floor with its form ID on screen, to find the
  sparks by eye. The owner's run also verified timed and perfect blocks: 26 of 26 health back each time, StaggerStart
  only on the perfect ones (0.09-0.10 s).
- 2026-10-26 owner's run: 14 timed blocks (9 perfect, incl. power attacks), all damage given back, but the player
  died on a perfect timed block of a power attack at 70 health: the damage lands before the give-back. While blocking
  the player is now in Papyrus' deferred kill state (Actor.StartDeferredKill / EndDeferredKill, FO4 names; supported),
  ended 0.5 s after the guard is down and any give-back is done. The owner's effect pick 0x000550C3 is a placed
  reference (form type 0x4A REFR), not an impact set: its base object is placed at the weapon node
  (ObjectReference.PlaceAtNode) and disabled / deleted 1.5 s later; the log names the base object's form type.
- 2026-10-26 timed-block sparks: the owner's pick 0x000550C3 was a beer can reference (the placement path works: a can
  appeared at the weapon on each timed block; the 1.5 s cleanup did not remove them, unresolved). Owner's SF1Edit list
  of Starfield.esm's impact data sets: 0x00258056 WPNMeleeBlockBladeSmallImpactSet is vanilla's blade-block impact;
  now the shipped default (alternatives noted in the INI).
- 2026-10-26 timed-block effect 0x00258056 dispatched on every timed block, nothing visible (owner). The Papyrus
  result of PlayImpactEffect is now logged and, when false (pick ray hit nothing / node not found), the next aim is
  tried: toward the attacker from the node, down toward the attacker, straight down from the root.
- 2026-10-26 0x00258056 (WPNMeleeBlockBladeSmallImpactSet): PlayImpactEffect returned false for every aim, even
  straight down onto the floor (owner's log) - likely no entries for those materials. sTimedBlockEffect is now a list;
  each set is tried with each aim until one returns true (logged). Default: PHYWeaponMetalBlade1Hand, WPNMeleeImpact
  BladeMedium, PHYMetalGenericMedium, then the block set.
- 2026-10-26 0x000A7C3D played (down toward the attacker / straight down; never toward the attacker's body) but the
  owner saw nothing - a dropped-blade physics impact. Default list now starts with projectile impact sets, which show
  sparks on metal: FXProjectileBullet (0x0000D02C), ArcWelder (0x000BA2E3), BulletWhiteHot (0x001E3EA5).
- 2026-10-26 timed-block sparks at the impact point: Simple Block Sparks' mesh is a 593-byte pointer to Skyrim's own
  addon node 52 (FXMetalSparkImpact01), spawned by its DLL at the contact point (a BSTempEffectParticle-style call).
  Skyrim particle meshes do not run in Starfield, and Starfield's temp-effect spawn is not mapped in CommonLibSF:
  parked until the owner finds a Starfield spark Art Object / Visual Effect / Addon Node (unresolved).
- 2026-10-26 weapon clash (owner's request: port Cinematic Clash). Its source is GPL-3.0: read for behaviour only, no
  code taken; s2s/clash.h is written from its INI and observed behaviour. Starfield has no weapon-on-weapon collision
  (the Skyrim mod's trigger, via Precision / Maxsu Weapon Parry), so a clash starts on a perfect block instead of the
  attacker's parry stagger (bOnPerfectBlock). First cut: meter + mash (difficulty presses / s), outcome staggers
  (staggerMagnitude + StaggerStart / recoil events, Skyrim's names; Starfield's unresolved), the opponent placed in
  front and restrained (Papyrus MoveTo / SetAngle / Actor.SetRestrained, FO4 signatures: supported), the lock-on held
  on them, movement / block / attack kept from the game's controls, the player ghosted, ground sparks every 0.25 s,
  messages instead of the on-screen meter. Not yet: HUD meter, camera presets, sounds, blade-distance solve / tilt,
  skill influence, rumble, OAR-style conditions.
- 2026-10-26 first clash run (owner's log): clashes start (perfect block and forced), opponent placed / restrained,
  guard taken, lock-on held; every clash lost in ~1.4 s with no attack press logged, the camera only looked at the
  opponent, the gap looked a little far. Now: fGraceTime 1 s before the opponent pushes, fClashDistance 0.7, the lock
  view turned fCameraYaw 35 / fCameraPitch 5 deg off the opponent for a side-on shot (eased in), attack also by user
  event PrimaryAttack, every key during a clash logged with the meter. FPS: the plugin's own time stayed ~10 us per
  frame and no effect object was placed in that session; the drop is likely objects left in the save by the earlier
  placement tests (the 1.5 s cleanup never removed them): the placed reference is now also found through the VM
  object's handle, and placements are logged (supported, not verified).
- 2026-10-26 owner's clash screenshots: the camera ended up straight overhead. Aiming the lock's pitch from the camera
  at an opponent 0.7 away runs away (the orbit camera rises as it tilts down, so the target sinks further below it;
  the normal lock at several metres converges). During a clash the pitch is now held at fCameraPitch (8 deg down) and
  only the yaw is aimed, from the player's eye, turned fCameraYaw off the opponent. FPS: fixed on the owner's side.
- 2026-10-26 owner's clash screenshots with the fixed tilt: the camera is right (behind, side-on), both guards up, but
  the two stand side by side, the player facing the camera's way (35 deg off the opponent), blades not crossing. While
  a clash runs both headings (data.angle.z) are now written each frame to face each other (bFaceEachOther).
- 2026-10-26 owner: facing each other now works; an effect plays at the player's feet (the clash sparks: impact sets
  only play on the floor) and the opponent sometimes recoils before raising the guard. Clash sparks are off by default
  (fSparkInterval 0) until an in-air effect is found; during the grace time the opponent gets the interrupt + guard
  every 0.2 s (its own hit reaction can start after the clash's first guard event).
- 2026-10-26 owner's clash log: mashing works (6-9 presses, wins), but every 0.2 s the interrupt + BlockStart was
  taken again by both graphs (block-up sound each time): the block re-entered over and over - the opponent looking
  mid-attack / recoiling, the player's feet shuffling. The guard is now a Guard command: the game side sends the
  interrupt and the block only when that actor's bIsBlocking is off. The grace (0.6 s) now holds the meter for both
  sides (presses during it were winning clashes in under a second).
- 2026-10-26 owner asked what differs from Cinematic Clash (source read for behaviour; GPL, nothing copied). Added its
  three techniques that answer the open issues, written independently: (1) a graph event filter - Actor's and
  PlayerCharacter's IAnimationGraphManagerHolder::NotifyAnimationGraphImpl (slot 1, vtables found through RTTI) drop
  the two fighters' attack / reaction / block-drop / walk / turn events (sBlockedEvents) while a clash runs, the
  plugin's own sends pass (thread-local flag); (2) the locomotion floats (Speed, SpeedSampled, Direction, TurnDelta -
  Skyrim's names; only those the Starfield graph has, logged at clash begin) set to 0 on both every frame (Papyrus,
  queued); (3) facing: both turned for fSettleTime 0.5 s, then only the player's heading is held, corrected past 0.5
  deg. Supported, not verified: that Starfield's AI / hit reactions go through that function.
- 2026-10-26 owner's log with the filter build: both vtables hooked; Speed / Direction / TurnDelta exist on both graphs
  (SpeedSampled does not); no event was kept by the filter (unresolved: whether the game's own attacks / reactions go
  through NotifyAnimationGraphImpl - the filter now logs every event it sees for the two); footsteps (FootLeft /
  FootRight, walk foley) all through each clash; Alt mid-clash ran the plugin's dodge and walked out (aborted at 6 m).
  During a clash no key reaches the controller now; a trace logs the locomotion values and heading corrections.
- 2026-10-26 owner: the opponent stayed in the block pose after a clash (it won: no reaction event, and only the
  player got BlockStop). sEndEvents now goes to both. Same log: the filter saw only PositionChange / RelaxedStart for
  the opponent and nothing from the game for the player - the game's own attacks / reactions mostly do not go through
  NotifyAnimationGraphImpl (the filter stays, as a no-op in practice; verified by the log). Footsteps during clashes
  nearly gone: two in one clash, at the moment of the player's heading corrections (37 in the first 0.5 s after
  settling), none in the others; Speed / Direction / TurnDelta read 0 on the player throughout.
- 2026-10-26 owner: the clash as its own plugin, an add-on to S2S Combat (owner's pick over standalone). S2SClash.dll
  (sfse/clash, second xmake target; its own S2SClash.ini with the [Clash] section) gets S2SCombat's CombatServices
  (lock-on hold / release, the spark effect, key codes) through an SFSE message at PostLoad (src/ClashApi.h, plain
  function pointers, versioned) and registers ClashCallbacks; S2SCombat forwards perfect blocks (dropping the parry
  stagger only when a clash starts), the player's hits, keys, menus and the tick, and keeps the player ghosted while
  the add-on asks. Without S2SClash, S2SCombat behaves as before the clash work. The graph event filter moved into
  S2SClash. Not built on the PC yet (syntax-checked here).
- 2026-10-26 dual wield (owner: looks + plugin damage, from LoreRim's dual packs; clash tabled): Dual stance in
  S2SStances.esm, S2S_LeftBlade keyword on the left-blade ARMO, S2SCombat switches the stance while it is worn, the
  converter keeps both HitFrames of a dual attack. Built here: s2s_stances\dual from LoreRim 9011100 (ring of 6, as
  v15). Next: the owner's run (moveset switch, left blade, one or two hits per swing), then plugin damage if needed.
- 2026-10-26 owner's dual test: the Dual stance plays with the left blade worn (verified: moveset switch), but the left
  blade hung at the hip outside the dual attacks (vanilla idles / walks do not put WeaponLeft in the hand), and the
  nightwear copy took the outfit's slot (outfit and legs gone, not wearable with a spacesuit). Now the blade is skinned
  to L_Wrist at the WeaponLeft rest grip (same look in the dual attacks, in the hand in every clip), and the ARMO / ARMA
  copies sit on one biped slot (BO64) no vanilla ARMO / ARMA uses (highest free bit <= 61, --left-slot overrides).
- 2026-10-26 owner: left hand open while dual wielding. Read back from the dual clips: the left finger roots sat
  143-159 deg from rest (the right 27-32): the retarget's hand_follow turns the left hand ~150 deg about the blade so
  the left weapon aims as Skyrim's, and the fingers kept Skyrim's world orientation. The extra turn of a followed hand
  is now carried to the bones under it that follow Skyrim's world deltas (fingers keep their pose in the hand; the
  right fingers shift slightly too). Rebuilt: left finger roots 15-33 deg, as the right. Delivered as
  SkyrimMelee_LoreRim_dual_stance_v2.zip. Next (owner's go): the left weapon drawn by the plugin instead of apparel.
- 2026-10-26 left weapon drawn by the plugin (any melee in the left hand): CommonLibSF on 1.16 maps NiNode
  AddChild / RemoveChild / GetObjectByName and a reference's loadedData->data3D, but no model loader (BSModelDB is RTTI
  only) and no clone: loading an arbitrary weapon model at run time needs reverse engineering (unresolved). Meanwhile
  the worn blade stays, and S2SCombat hides its node (sLeftBladeNode, NiAVObject flags +0x118 bit 0: supported, from
  Skyrim's AppCulled) while Papyrus IsWeaponDrawn says sheathed, and logs the player's 3D tree when the blade goes on
  (also answers whether the spacesuit removes the blade's node or only hides it).
- 2026-10-26 owner's run: left fingers now grip (dual stance v2 verified by screenshot); pants still gone; hide /
  show matched 0 nodes and the 3D dump listed only HumanExportRoot (CommonLibSF's NiNode::children reads empty on
  1.16); not visible with a spacesuit. Fixes: the left blade's ARMO keeps only its own addon (the nightwear ARMO lists
  more than one INDX / MODL addon: the outfit's other part came along and took the pants); the child list of a node
  is found at run time (the offset whose array elements have that node as parent, NiAVObject +0x38).
- 2026-10-26 owner: pants fixed (verified); blade still not shown with a spacesuit; lag with the blade on. The child
  list search failed (no offset in 0x110..0x200 whose elements have the node as parent at +0x38) and ran again every
  0.25 s (avg 2.4 ms per frame in the timing lines). Now at most 3 tries per session, and the first failure logs the
  root node's first 0x200 bytes (and what each pointer points at) to read the real layout from.
- 2026-10-26 owner's root-node dump (1.16): name +0x10, parent +0x38 (verified), transforms +0x40.., flags +0x118, a
  second vtable at +0x130, and at +0x138 a pointer to the children with u16 count / capacity at +0x140 (14 / 14 on
  HumanExportRoot): CommonLibSF's BSTArray children layout does not apply. The child search now also tries
  {T* data, u16 size, u16 cap}; the blade's nodes are remembered (re-walked every 2 s, or when one no longer hangs
  under the root) instead of walking the whole tree every 0.25 s.
- 2026-10-26 owner's run with the child layout fix: the 3D walk works (children at +0x138, 14 on the root; the blade's
  node longsword_left found, 1 node). Two findings. (1) The dump taken before the plugin touched any flag, spacesuit
  on, shows bit 0 of flags +0x118 set on the outfit's nodes, the hands and the head (under the suit's gloves and
  helmet) and on longsword_left: the game hides the blade as it hides the outfit under a spacesuit. xEdit's Starfield
  definitions name biped slots 0-31 for the outfit and 32-63 "SS ..." for the spacesuit (same parts twice), so the
  supported reading is that the game shows one set at a time. The blade's ARMO now lists two addons with the same
  model, one on a free outfit slot (0-31) and one on a free spacesuit slot (32-61) (`--left-slot`,
  `--left-suit-slot`; Misc 3 / SS Misc 3 if a set has no free slot, reported). To verify: blade seen with and without
  the suit, and with the suit hidden in a settlement. (2) Writing that same bit from the plugin did nothing visible
  (log: hidden / shown on 1 node, owner: the blade stayed), and cost ~0.4-0.7 ms per frame on average with the blade
  on. Dropped. The blade is now taken off on 'weaponSheathe' and put on again on 'BeginWeaponDraw' with the native
  equip (as the stance re-equip), with s2s/left_blade.h deciding (tested): the dual moveset stays on while the plugin
  has the blade put away; equipped from the menu while sheathed, it is put away on closing; after a load, the dual
  stance keyword on the player plus a blade in the bag, not worn, means the save was made with it put away
  (unverified: whether the keyword added through Papyrus AddKeyword is kept in saves). The blade forms are the ARMOs
  of the plugin that defines S2S_LeftBlade (no keyword arrays read natively).
- 2026-10-26 owner's run: sheathing took the blade off, but the native unequip answered false ("refused"), so the
  plugin dropped the parking and the next poll (not worn) switched back to one-handed; the blade stayed off. The game's
  answer is now only logged; the polls decide (an equip at the draw that a fresh poll does not confirm gives up). Still
  not visible with a spacesuit (the dump listed one longsword_left node, hidden). Owner asked for the left blade as a
  weapon instead of apparel: Starfield equips one weapon at a time (no left-hand weapon slot); proposed a paired weapon
  (one WEAP whose model holds both blades, the left one skinned to L_Wrist), to test whether a weapon NIF's skinned
  geometry binds to the actor's skeleton.
- 2026-10-26 owner chose the pair weapon test. `weapon_test_pack.py` now also writes S2S_IronSword_Pair ("Iron
  Swords (Skyrim, pair)"): a copy of the template WEAP whose model `longsword_pair.nif` is the right sword's static
  model plus the left blade's skinned shape (L_Wrist, identity bind) as a second child of the root
  (`sfnif.merge_skinned`, tested: refs and strings renumbered, skin root = the weapon's root; BSXFlags stays the
  weapon's 0, the robe's 0x10000 left out). It carries S2S_LeftBlade so S2SCombat's Actor.WornHasKeyword poll switches
  to the Dual stance. Unverified, the two things this test answers: whether the game binds a weapon model's skinned
  shape to the actor's L_Wrist (else the left blade is invisible, stuck, or at the right hand), and whether
  WornHasKeyword counts the equipped weapon's keywords (else the moveset stays one-handed and the plugin needs an
  equipped-weapon check).
- 2026-10-26 owner's pair weapon run: Actor.WornHasKeyword does count the equipped weapon's keyword (verified: "left
  blade worn -> stance S2S_StanceDual" on equipping the pair), and the weapon's 3D holds both blade shapes (node
  Longsword, two IronLongSword01:0, both visible flags). But the stance re-equip takes the weapon off for ~0.5 s, the
  next poll saw the keyword gone and switched back (log: worn -> dual, 0.5 s later off -> before, every time). Now
  the polls wait while a re-equip is under way (s2s::combat::ReequipHold, tested), and only a worn ARMO blade
  (Papyrus IsEquipped) is taken off while sheathed (the plugin had also tried to put away the unworn ARMO blade).
  Where the left blade draws is still to see (screenshot).
- 2026-10-26 owner's run with the re-equip hold: the hold worked (no poll during the swap), but the first poll after
  it still said the keyword was not worn: WornHasKeyword saw the pair's keyword when equipped from the menu, not
  after the stance re-equip, which equips the base form without instance data (supported reading: the worn check
  reads the instance's keywords). The poll now also asks Papyrus for the equipped weapon (GetEquippedWeapon) and
  Form.HasKeyword on its base form, chained in the same poll; dual = worn keyword or the weapon's keyword.
- 2026-10-26 owner's pair weapon run (screenshots + log): the dual moveset now plays with the pair weapon
  (verified). The left blade is not in the left hand: it shows dark and loose near the right hand / at the feet in
  the status screen and inventory preview, so the game does not bind a weapon model's skinned shape to the actor's
  L_Wrist (verified that it does not work this way). The 3D dumps also show the weapon node "Longsword" directly under
  the player's root (not under a hand bone) and nothing under Human_rigRoot: the game places the weapon from the
  skeleton each frame, and the bones are not child nodes (supported: a flattened bone tree as in Fallout 4). Next:
  the plugin moves a rigid left-blade node of the pair model to the left hand bone each frame. To find where the bone
  transforms live, a one-time search logs rigRoot's memory and every place within two pointer hops holding the pooled
  bone-name strings, with the floats around L_Wrist.
- 2026-10-26 owner's bone-search run: the child list was not found this time: +0x140 read 0E 00 0D 00 (14, 13), the
  reader took the first u16 as the count and rejected count > capacity. Now the smaller of the two is the count. The
  same dump confirms the transforms: local at +0x40 (3 rows of 16 bytes, translation +0x70, scale +0x7C), world at
  +0x80 (translation +0xB0 = the player's position, 1515 / -797 / -161), previous world at +0xC0.
- 2026-10-27 owner's bone-search run (with the count fix): the skeleton is an ordinary node tree under "Root" (COM,
  ..., L_Clavicle > ... > L_Wrist, R_Wrist, Weapon, WeaponLeft; ~440 nodes with the face bones), so the earlier empty
  rigRoot was the child-count bug, not a flattened bone tree. The weapon model ("Longsword") is a child of the
  player's root, beside the skeleton. Done: the pair weapon's left blade is now a rigid static shape in L_Wrist's
  frame under a node S2S_LeftHand (`sfnif.merge_under_node`, tested), and S2SCombat moves that node onto L_Wrist
  every frame while the weapon carries the dual keyword: local = inverse(parent world) * L_Wrist world
  (`s2s/xform.h`, tested), world written too. Unverified: whether the game keeps our transform for the draw (the tick
  runs at input time, so the blade may trail the hand by a frame), and whether it lines up in the hand.
- 2026-10-27 owner's follow run (screenshots + log): S2S_LeftHand found and written every frame ("follows L_Wrist"),
  but the left blade stayed fixed beside the right sword (where its L_Wrist-frame geometry lands at an identity
  local): the write had no visible effect. The full 3D listing shows the weapon model ("Longsword") under the
  skeleton's "Weapon" bone, S2S_LeftHand under it. Also the plugin's frame time went to ~23 ms (from ~5 us). Now:
  the root and nodes are looked up twice a second and on equips / menus / draws (no Player3D lock and memory queries
  every frame), the call is timed, and each frame reads back the previous frame's write (is our local still there,
  is the node's world what our local gives) and logs it every 5 s with the positions, to tell whether the game
  resets the transform or draws from somewhere else.
- 2026-10-27 owner's read-back run: our local transform on S2S_LeftHand stayed every frame (450 / 450: the game does
  not reset it), but the node's world never matched it and the blade on screen did not move: the game draws the
  weapon model's parts from its own copy of the transforms, not from the node's local / world (verified that writing
  them does nothing visible). Moving a part of a weapon needs the engine's own update path (Ghidra). Also each
  dual switch cost a ~1.7 s hitch (the 3D listing + bone search) and the 0.5 s lookups ~40 ms spikes. Now: the
  follow is off by default (sLeftHandNode empty), the listing / search only with bDualDebug = 1. The worn left blade
  (which draws in the left hand, verified 2026-10-26) is the working route again, with the spacesuit-slot addon and
  the put-away-while-sheathed fixes still to test.
- 2026-10-27 owner's worn-blade run: blade in the hand (dual moveset), but sheathing did not put it away (no "taken
  off" line: Papyrus Actor.IsEquipped on the blade ARMO never answered yes, so the plugin thought no ARMO blade was
  on) and still invisible with a spacesuit (the outfit-slot + spacesuit-slot addons did not help). Now the ARMO blade
  is "the keyword is worn and the weapon does not carry it" from the same poll. For the spacesuit, the pack prints the
  copied outfit's keywords / record flags / slots next to a vanilla spacesuit body's, to see what the game sorts by.
- 2026-10-27 owner: sheathing now puts the worn blade away and drawing brings it back (verified; the native unequip
  still answers false and works). Spacesuit check from the pack: the copied Clothes_Nightwear_01 carries
  InventoryCategoryApparel + ArmorTypeApparelOrNakedBody; a vanilla spacesuit body (Spacesuit_SpaceTrucker_Generic)
  carries InventoryCategoryArmorSuit + ArmorTypeSpacesuitBody (+ ma_ / display keywords). Slots chosen: 31 (outfit),
  61 (suit); vanilla slot use 886BFFFF6FCF7FFF. Supported reading: ArmorTypeApparelOrNakedBody files an item with
  the body layer the game hides under a shown spacesuit. The blade's ARMO now drops it (keeps
  InventoryCategoryApparel for the inventory tab). To verify: the blade drawn with the suit on. If the game still
  hides it, next is two blade copies (outfit / spacesuit) swapped by the plugin. The pack's record_flags read the
  type signature (offset 0); now offset 8.
- 2026-10-27 owner: without ArmorTypeApparelOrNakedBody the blade is never drawn (verified): the game draws worn
  items by their layer keyword. Now `--left-layers both` (default): the blade keeps the outfit's layer keyword and
  also gets ArmorTypeSpacesuitBody, to see whether either layer being shown draws it. `outfit` / `none` give the
  earlier two. If both-layers hides it under a suit too, next is two blade ARMOs (outfit / spacesuit layer) the
  plugin swaps.
- 2026-10-27 owner: with both layer keywords (outfit + ArmorTypeSpacesuitBody) the blade shows with and without a
  suit (verified), but without a suit the player's body is invisible: the game took it for a spacesuit body. Now the
  added spacesuit-layer keyword is ArmorTypeSpacesuitBackpack (`--left-suit-layer` to pick another); the pack prints
  every ArmorType keyword the game has.
- 2026-10-27 owner: the worn left blade now works end to end (verified): in the left hand with the dual moveset,
  put away on sheathe and back on draw, visible with and without a spacesuit, body kept. The blade ARMO carries
  ArmorTypeApparelOrNakedBody + ArmorTypeSpacesuitBackpack, addons on slots 31 and 61. Open: the left grip (the
  mirrored right grip) and a finger look a bit off. `--left-grip-move X Y Z` (cm) / `--left-grip-turn RX RY RZ` (deg,
  about the grip point, L_Wrist axes) tune it in the pack without touching the clips (tested).
- 2026-10-27 owner: "that finger standing out" in the dual grip. Read back from the dual clips: the left pinky root
  sat 167 deg from rest (right pinky 19, every other left finger within a few degrees of the right). Starfield's
  pinky hangs off L_Cup, which the retarget keeps at rest (no Skyrim source), and the left hand's dual-wield turn was
  only carried to children of bones that follow Skyrim (the earlier finger fix), so it stopped at L_Cup. Now every
  bone inherits its parent's turn first (tested: a pinky under a rest-kept cup keeps its curl in the turned hand).
  Rebuilt the dual stance: L_Pinky 167 -> 14 deg, every other bone within 0.05 deg of v2. Delivered as
  SkyrimMelee_LoreRim_dual_stance_v3.zip (dual folder only, as v2).
- 2026-10-27 owner: left-hand versions of another mod's weapons (All Trilogy Lightsabers, 22 WEAPs). New
  `fo4sf/sfweaponleft.py`: a Starfield weapon NIF's shapes (node transforms composed as skyrimnif: p' = s R p + t,
  R row-major) moved into L_Wrist's frame at the left grip (`skyrimweapon.left_grip_metres`, the mirrored right grip,
  same --left-grip-move / -turn tuning) and rigidly skinned to L_Wrist (identity bind, one weight per vertex); each
  LOD0 .mesh rewritten (positions, normals, tangents moved; triangles, UVs, colours, LOD lists and the meshlet split
  kept; cull data recomputed); collision and lights (NiAmbientLight) left out, object-mod parts not included.
  Materials and textures stay the mod's (it must stay enabled). `weapon_test_pack.py --left-hand-mod <plugin>`
  (its '<name> - *.ba2' next to it) adds an ARMO / ARMA per weapon to S2SWeapons.esm like the iron left blade.
  Dry run on the uploaded mod: 22 / 22 converted (Count Dooku's emitter mesh is missing from the mod's own archive).
  Tested on a synthetic mod (positions, normals, bitangent sign, skin, records). Several blades: S2SCombat now tells
  which one is worn by a per-blade keyword S2S_LB_<the ARMO's local FormID> (WornHasKeyword, every 2 s while one is
  on) instead of Papyrus IsEquipped, which never answered yes. The iron blade's IDs are unchanged; the pair weapon
  moves to the next ID (it is abandoned).
- 2026-10-27 owner: with ArmorTypeSpacesuitBackpack on the blade, drawing (the blade put on) drops O2 / CO2 into the
  red, sheathing restores it (verified): the game takes it for an empty pack. The game's ArmorType keywords: Apparel
  Head, ApparelOrNakedBody, Neuroamp, SpacesuitBackpack, SpacesuitBody, SpacesuitHelmet, SpacesuitShowAlways,
  VaruunZealot. The blade's spacesuit-layer keyword is now ArmorTypeSpacesuitShowAlways (with the outfit's), to test.
- 2026-10-27 owner: with ArmorTypeApparelOrNakedBody + ArmorTypeSpacesuitShowAlways the left blade shows with and
  without a spacesuit, the body stays visible and O2 / CO2 stays normal on draw (verified). This is the default
  (--left-layers both). Lightsaber left hands (--left-hand-mod) built with it; their grip / moveset not yet reported.
- 2026-10-27 owner chose AI-assisted reverse engineering for the any-weapon left hand: ReVa (Ghidra extension with
  an MCP server, Claude Code as client) on the owner's PC. Setup and the first-session brief in
  docs/re/ghidra-ai-setup.md (targets: the NiObject clone virtual, NiNode attach, and what the equip path calls after
  attaching a weapon so it is drawn).
- 2026-10-27 owner asked what else to look for in Ghidra, and whether the TES4 converter's (bryantmh/tes4skyrim)
  automated quest testing carries over. Read its public repo (master, last commit 2026-10-13; MIT except
  external/, OpenMW there is GPL-3.0; ideas only, no code taken). What it has: `game_bridge` (an SKSE plugin with a
  named pipe: runs console lines and returns their output, captures Papyrus output, reads memory, traces behavior
  graphs; addresses by Address Library ID with a signature-scan fallback; every game call on the main thread),
  `quest_labtest.py` (a quest's cast found from the export, the real references moved into an empty test cell after
  the quest reset, then passive observation and A / B trials with an injected change), `quest_walkthrough.py`
  (offline: fires every stage edge whose conditions can hold until nothing changes; a quest is completable when its
  completing stage is reached; the same run on the source game is the baseline), crash / hang dump capture. The
  autonomous quest-completing update itself is not public yet (unresolved). Decision: for us, (1) an S2SCombat test
  bridge replaces the OCR console reading in scripts/game when the console's run path is found (target 1 in
  docs/re/ghidra-ai-setup.md section 6; output capture needs no RE); (2) the offline walkthrough and the clean-room
  method are for when quests are converted (PLAN P5). Their lessons match ours: an engine call's answer is not
  evidence (our unequip answered false and worked), measure the effect instead; never assume the load-order index.
- 2026-10-27 owner: convert KS Hairdos SMP's physics. Decision: generate Starfield's own bone-driving cloth per SMP
  chain (plan route A) instead of an SFSE solver (route B): no runtime code, and every rule the cloth needs was
  verified on the owner's uploaded hairs (docs/armor/animation-port.md "SMP hair -> Starfield cloth"). New: a Havok
  tagfile writer (`fo4sf/hktagwrite.py`, byte-identical rewrites of the OC cloth files), the chain-cloth builder
  (`fo4sf/smpcloth.py`, bone- or object-space skin templates, its own checker), the hair re-rig (`fo4sf/skyrimhair.py`:
  head-relative placement measured on the two games' heads, simulated SMP bones as S2S_ bones, anchors merged into
  C_Head) and `scripts/armor/hair_pack.py` (KS wigs as head apparel in S2SHair.esm). The cloth template (TYPE section,
  human skeleton, body capsules) is read at conversion time from the game or a mod, never committed. Alternatives:
  reusing a game hair's rig unchanged (no KS physics), an SFSE solver (route B, kept as the fallback if the generated
  cloth looks stiff). Unresolved until the owner's run: whether it simulates in game.
- 2026-10-27 owner: vanilla Skyrim hair on the first NPC conversions, to tell NPCs apart and judge the faces. Decision:
  the face test NPCs (face_fit.py --hair) wear their own Skyrim hair / beard, converted rigidly with the SMP hair code
  (no physics: vanilla hair has none) and the hair colour baked into the texture, rather than mapping to the nearest
  Starfield hairstyle (later). Found while doing it (verified on KS Amor / Kikyo): a head part NIF's bone nodes can sit
  away from the frame it was skinned in (3.3 units up, 2.5 back); the binds are the truth, so skyrimhair now anchors on
  the skin bind of NPC Head and moves the node tree into that frame (the first KS pack would have put those wigs 4.6 cm
  low).
- 2026-10-27 owner: is the Skyrim grass Starfield grass (wind, fade, pop-in handling) or a static? It is baked patch
  statics. Starfield has a run-time grass system (GRAS / GCVR ground cover / BIOM terrain entries, per xEdit's
  definitions) that maps almost field for field onto Skyrim's. Decision: test it before changing the default: a
  read-only survey (`scripts/terrain/grass_survey.py`) answers whether hand-made worlds get ground cover by painted
  texture, and a test build (`scripts/terrain/skyrim_grass_native.py`, S2SGrass.esm) grows Skyrim's grass through
  GRAS + GCVR on the spare LTEX records the terrain overrides (never on vanilla ones: that would put Skyrim grass on
  vanilla planets), optionally through the planet's biome. The patches stay the default until it works in game.
- 2026-10-28 grass survey (owner's run): vanilla ground cover is reached only through biome terrain entries (all 96
  GCVR, none by their own texture list on any BTD); no vanilla hand-made world paints a biome-covered texture; the
  only BTDs that do are planet-trait overlays. Decision: the native grass test goes through the Skyrim world's biome
  (skyrim_grass_native.py default --biome world, entries for all 7 masks), accepting for the test that the planet
  generator may also paint the Skyrim textures on planets of that biome; a biome of our own is the clean follow-up if
  it works.
- 2026-10-28 native grass parked: no grass in game through the world's biome; the worldspace No Grass flag is off on
  our world (survey). Skyrim grass stays the baked patches; S2S Grass Native is test-only (it edits a vanilla biome).
- 2026-10-28 owner: KS wigs not seen in game. Then the no-physics copy (Steammist, C_Head + C_Chest, rest-pose binds,
  no cloth) equipped in the inventory: still not drawn (verified from his screenshot: her own short hair, no
  waist-long Steammist). So the cloth is not (only) the cause. Untested parts left: the multi-bone rest-pose binds
  (read from the robe, never written and seen in game) and the hat record. hair_pack now also writes per wig a
  head-bone copy (every vertex on C_Head in C_Head's own frame, identity bind: the worn left blade's convention,
  seen in game) and one 'S2S control hat (vanilla model)' (the template hat renamed, its own addon). Reading: control
  hat hidden -> the head slot is hidden (not our files); head-bone copy shows, no-physics not -> the binds; neither
  copy shows but the hat does -> mesh / material.
- 2026-11-02 owner, in game: 'S2S control hat (vanilla model)' shows (the head slot and the copied hat record work;
  wearing a wig also swaps her hair to the short hat hair, so the game takes the wig records as worn hats), but no
  wig copy is drawn: physics, no-physics and head-bone (the left blade's skin convention) all invisible (verified,
  screenshots). So not the cloth, not the binds. Left: what only the wigs have: the hair material (alpha-tested
  cutout, threshold 40; the left blade is opaque) or the S2SHair archive. hair_pack now adds three controls on the
  first wig: the head-bone copy with a solid material, the head-bone copy with the vanilla hat's own material, and
  the vanilla hat NIF copied into S2SHair's archive under s2s\hair\control_hat_copy.nif.
- 2026-11-02 owner, in game: solid-material and hat-material wig copies invisible too, and so is the vanilla hat NIF
  loaded from S2SHair - Main.ba2 (control_hat_copy; the archive holds all 6 NIFs, listed on his PC). So neither the
  hair mesh nor the material: the shared factor is our copied ARMA (every test item) or the new model path (data the
  game keeps per model path, e.g. morphs, missing). Note: his console's help matches EditorIDs, not names. Added the
  control `S2S_KSWig_Control_armacopy` (the ARMA copied as for a wig but naming the vanilla model path) and dumps of
  the template ARMA / ARMO subrecords and of game files named after the hat model into hair_pack.json.
- 2026-11-02 cause found (supported, from the owner's hair_pack.json + Eris files): head items ship a second model,
  <model>_facebones.nif (vanilla: outfit_akila_security_hat_f_facebones.nif next to the hat; Eris: every hair, same
  vertex count, skinned to 39 faceBone_* bones instead of C_Head). Every in-game result fits "actors with face bones
  (player, named NPCs) draw the _facebones file": the vanilla hat shows, the same hat NIF at our path (no companion)
  does not, every wig copy does not. hair_pack now writes <model>_facebones.nif for each wig and copy: C_Head's
  weights moved to one face bone (faceBone_C_HeadTop), its rest world = inverse of the bind in the vanilla hat's
  facebones NIF read from the game (binds are inverse rest worlds: checked on Eris, HeadTop at z 1.762, chin 1.568);
  the archive control gets the hat's own facebones file. To verify in game. Later: spread the weights over the face
  bones (follows chargen face shape) instead of one bone. Also for the NPC hair head parts (npc_hair.py).
- 2026-11-02 owner, in game: with the _facebones files the wigs are DRAWN (verified: facebones was the cause), but
  misplaced: the physics Steammist hangs correctly shaped about a head's height above the player; the head-bone copy
  stands as a tall column from the head upward. The face-bone rest world was read from the vanilla hat's facebones
  binds as inverse(bind); two explanations kept, one build tests both: (A) the hat's shape node carries a transform
  that its binds include (the robe convention: bind = inverse(world) @ node), now world = node @ inverse(bind), and
  the face bones are read from the cloth template hair's facebones file (vanilla bob) first, the hat's second, both
  reported in hair_pack.json "facebones"; (B) the game places facebones models at the head, so the head height is
  counted twice: control `S2S_KSWig_Control_headshift` (head-bone copy with C_Head's height taken off).
- 2026-11-02 owner, in game: the KS Steammist wig sits on the head (verified, screenshots: scalp on the head, hair
  down the back to the waist), both the head-bone copy and the physics wig; the head-shift control sits about a head
  height below the player. So explanation A: face-bone rest world = shape node @ inverse(bind) of a vanilla
  facebones file (the hat's node carries an offset); B (head counted twice) ruled out, its control removed. Open:
  hair colour (greyscale KS texture, our material does not tint: needs the vanilla hair material's tint), whether
  the cloth swings, face bones spread over the scalp instead of one bone (follows chargen face shape), the
  _facebones files for npc_hair.py's head parts.
- 2026-11-02 owner, in game: the physics wig swings and follows movement (verified: the cloth runs), but the long
  hair sinks into the back / hips: the cloth had only head colliders (the template's + S2S_head). Added body
  capsules (skyrimhair.body_capsules): neck, chest, waist, hips (horizontal), thighs, upper arms (mirrored), placed
  from the cloth skeleton's rest bone origins with estimated slim-body radii, each shrunk so no particle starts inside
  (all at full size on Steammist / Anna / Amor: their chains hang clear of the body at rest); hair_pack --body-scale
  (0 = head only), radii reported per wig in hair_pack.json cloth.body_colliders. Unverified: the radii against the
  Starfield female body; per-gender sizes.
- 2026-11-02 owner, in game (Caress, Erena, Spring, Anna): locks twist and flail while standing, sink into the body
  while moving, and his own hair shows through the scalp. Changes (each tested synthetically, unverified in game):
  (1) the wig ARMA gets biped bit 0 Hide Hair instead of 1 Morph Hair (xEdit wbDefinitionsSF1 names: 0 Hide Hair, 1
  Morph Hair, 4 Hat; the copied Akila hat addon had 0x12 = Morph Hair + Hat), --keep-own-hair for the old way;
  (2) the template's own colliders are no longer kept (sized for its hair: KS particles started inside the bob's
  head collider), S2S_head + body capsules only; (3) particle collision radius 5 mm -> 2 cm (the particles run along
  the middle of a lock, the mesh around them sank), capsule shrink margins follow it (--hair-radius); (4) damping =
  the template's (0.97 on the vanilla hairs) instead of 0.9 (--damping); (5) a soft second diagonal (stiffness 0.3,
  --twist) in every chain segment: the ribbon (A0, B0, A1, B1) could fold along B0-A1, which turns the lock about
  its length; standard-link weights scaled per link (the solver moves each end by weight x error); (6) neighbouring
  chains (roots < 12 cm) tied joint to joint (A-A, B-B, stiffness 0.5; --no-sheet): Steammist gets 70 links, the
  short KS wigs none (2-3 separate locks 15-23 cm apart, left untied).
- 2026-11-02 owner, in game: with the stability changes the KS wigs sit well (clean scalp, no sinking) but barely
  move; the ponytail lies on the back instead of trailing; front locks clip the face; the scalp does not follow his
  character's head shape. Owner: vanilla hairs only jiggle subtly, never flow (matches their damping 0.97 if it is
  the share of speed lost per second: supported reading of globalDampingPerSecond). Changes: hair_pack --damping
  default 0.6 (Settings.damping None still means the template's), --friction default 0.1 (0.3 before); S2S_face
  capsule on C_Head (chin to brow, 3.5 cm forward, r 5.5 cm, shrunk like the skull one); the scalp's C_Head weights
  spread over the face bones like the vanilla hair's facebones file (cloth template's, e.g. bob_f_facebones.nif + its
  .mesh read from the game: k = 4 nearest reference vertices mostly on face bones, inverse-distance blend, at most 4
  weights), so it follows the face-bone shape; falls back to one face bone when the mesh is not found. Unverified.
- 2026-11-02 owner, in game (face bones spread, damping 0.6): hair still clips the forehead and does not quite fit
  the face; locks twist and swing side to side instead of trailing; the hair follows Starfield's wind (verified:
  the cloth reacts to the world; no wind action in our cloth data, so the engine applies it). From his
  hair_pack.json: the vanilla bob's facebones shape node sits at C_Head (0, -0.0018, 1.6323) and its binds are
  head-relative, so node @ inverse(bind) was needed (consistent with the placement fix). Found: the ribbon's side
  direction came from each bone's own axes: neighbouring bones got opposite sides (Caress: a half-turn built into
  the ribbon) and side locks got slanted hinges. Now one side per lock, model X across the body made perpendicular to
  the segment (model Y for a lock running along X): flat ribbon at rest, hinge front to back (tested). Added
  --mass-scale (heavier hair: less wind if wind is a force, unverified; more momentum) and --skyrim-data: measures
  the female head fit (Skyrim femalehead.nif cranium onto Starfield femalehead_facebones mesh, similarity without
  rotation, as the male constants) and uses it unless --head-scale / --head-offset are given (hair_pack.json
  head_fit). Range reach per joint checked: 4 cm at the root to 40-55 cm at the tip (Anna / Spring), not the limit.
- 2026-11-02 owner: KS wigs still do not fit the face and the locks read as "a piece twisting around"; asked for a
  side-by-side head comparison, and sent OC Hairs (Nexus 14496, read for the format only) as the flowiest Starfield
  hair he has seen. OC (verified from its files): the ponytail simulates its own tube mesh (367 particles, 160
  fixed, 463 triangles; pigtails 2,182 / 3,169), particle mass 0.01 kg, radius 2 mm, friction 0.5, damping 0.9, NO
  local range, transfer motion off, constraint sets standard links + stretch links + hclVolumeConstraintMx (pigtails
  also hclBendStiffnessConstraintSetMx), colliders: convex-geometry head and torso + biceps capsules, object-space
  skin, 1 substep / 1 iteration. Ours: a two-row ribbon per lock (2 particles per joint), so twist is barely
  resisted: the gap is the sim shape, not a parameter. Next (proposed): a tube of particles per lock (rings around
  each SMP joint) with volume / bend constraints and OC-like settings, on a template whose TYPE section has those
  classes (OC's own .hkx read from the owner's install, as the bob is), convex head / torso colliders.
  Also found: Starfield's femalehead_facebones mesh is stored in C_Head's rotated frame (node rotation (0,0,-1 /
  0,1,0 / 1,0,0) at C_Head), so every head reader must apply the shape node (hair_pack.game_mesh_of does).
  New scripts/armor/hair_fit_view.py: an HTML 3D page (three.js) with the Starfield female head, the Skyrim female
  head moved by the fit, and a wig (points inside the Starfield head in red), a left-right slice slider, and counts
  per region; tested on synthetic data and rendered headless with a stand-in head and the real Anna wig.
- 2026-11-02 owner's run of hair_fit_view: "too few cranium points (0 Skyrim, 9894 Starfield)": the Skyrim head's
  skinned vertices are stored in skin space (NiSkinData overall transform) and load_female_heads used them raw;
  convert already mapped them to model space. Shared now as skyrimhair.skin_to_model (tested); the female fit in
  hair_pack --skyrim-data had the same bug (it would have reported the error and kept the male constants).
- 2026-11-02 owner's hair_fit_view run (Anna, measured female fit): scale 0.9446, offset (0.0003, -0.0212, -0.0016),
  rms 5.8 mm (male constants 0.9303 / (0.0001, -0.0199, -0.0051)). The Skyrim female head moved by the fit lies
  inside Starfield's for 24.9 % of its points (> 2 mm) and outside by > 5 mm for only 3.2 % (median gap -0.5 mm):
  the skulls differ in shape (Starfield's bulges at crown / forehead / sides), not only size, so no similarity keeps a
  Skyrim-shaped scalp out (verified as numbers; matches the red crown / hairline in his screenshots). The viewer's
  count was inflated by hair below the neck cut judged against the cut edge (deepest 312 mm): now only points within
  3 cm of the head and above its lowest 2 cm are judged. Fix: hair_pack conforms by default (skyrimhair.push_out:
  judged vertices less than 2 mm above Starfield's female base head move out along the nearest head normal, half the
  push spread to mesh neighbours, never inward; --no-conform). The viewer shows the conformed wig and the counts
  before / after (--no-push-out for the raw fit). Base head only: face sliders move the face bones on top.
- 2026-11-02 owner's viewer run with conform: judged points inside the head 596 (2.98 %, deepest 7.9 mm; forehead
  106, top 405, sides 65, back 8) -> 0 after the push-out (deepest 1.1 mm, under the 2 mm test); in game the
  hairline sits clean (verified, screenshots). He now sees the wigs as too wide or the forehead too small (hairline
  low): the push-out only moves points outward, so a Skyrim-proportioned scalp keeps its width / height. Added
  skyrimhair.fit_head_axes (a scale per model axis + shift, same both-way closest-point ICP, starting from the
  uniform fit; synthetic test recovers 0.90 / 0.96 / 0.99) used by default with --skyrim-data (hair_pack
  --uniform-fit for one scale; per-axis normals by 1/s, tangents by s), reported next to the uniform fit; the viewer
  adds the cloth template's own facebones hair (vanilla bob, green) and the hairline height at the middle of the
  forehead (lowest point within 1 cm of the head in a 3 cm band) for the wig and the vanilla hair.
- 2026-11-02 owner's viewer run (per-axis fit, Anna): scale width / depth / height 0.9586 / 0.9335 / 0.9182, rms
  5.7 mm (uniform 5.8): proportions barely matter, and Starfield's skull is relatively WIDER, so the "too wide" look
  is the hairstyle's volume, not the fit. Hairline at the middle of the forehead: Anna 83.3 mm above C_Head, vanilla
  bob_f 97.8 mm (verified, his numbers): the KS hair starts ~15 mm lower = the "small forehead" (Skyrim faces have
  shorter foreheads; the cranium fit cannot see it). Added skyrimhair.lift_hairline: the front of the wig raised,
  full at the forehead, smoothstep fade to nothing toward the back (C_Head-relative Y 0.02 -> 0.08 m) and the crown
  (Z 0.16 -> 0.12 m); points that lay on the head keep their height above it; then the conform. hair_pack lifts each
  wig up to the vanilla hair's hairline (at most 30 mm; --hairline-lift mm to force, 0 = off), reported per wig;
  the viewer previews the same. Records / face bones now read before the wig loop (the lift needs the vanilla
  hair's mesh).
- 2026-11-02 owner's viewer run after the lift: middle hairline Anna 97.6 / vanilla 97.8 mm (matched; lift 15.4 mm),
  but in game "a bit flat" and still lower than the vanilla hair beside it. Two differences the middle-only lift
  missed: the hairline curve toward the temples and the vanilla hair's thickness over the scalp (bob's crown stands
  well above Anna's in his screenshot). Added skyrimhair.hairline_profile (hairline height in 3 cm bands at -70..70
  deg around the front), lift_profile (per angle, clipped 0-30 mm, gaps interpolated, smoothed over +-10 deg),
  lift_hairline accepting the per-angle lift (fade past 70 deg and near the head axis), crown_height and add_volume
  (hair on the head pushed out along the head normal by the vanilla-minus-wig crown difference, at most 20 mm, full
  above C_Head + 7 cm, nothing at C_Head height; strands within 6 cm follow). hair_pack does lift -> volume ->
  conform (--hairline-lift mm forces a uniform lift, --volume mm), reporting both per wig; the viewer previews and
  prints the hairline per angle (before / after / vanilla) and the crown heights. Tested on synthetic spheres.
- 2026-11-02 owner asked whether the wig will look like it sits off her head (the viewer's points have gaps). Points
  are only the vertices; in game the triangles are filled. But the volume step did risk a real gap: it pushed the
  whole wig out, edge and KS 'Hairline' scalp tint included. Now add_volume fades to nothing at the wig's own
  (lifted) hairline over 3 cm (sides up to 120 deg take the temple height) and never moves shapes named like
  'hairline'; tested. The viewer gains a 'Surfaces' button: head, wig and vanilla hair drawn as shaded triangles
  (game_mesh_of now also returns triangles); rendered headless with a stand-in head and the real Anna wig.
- 2026-11-02 owner's surface view (Anna, lift + volume + conform): the edge sits on the skin all round (no gap), but
  the volume rose to its full amount within 3 cm of the hairline: a visible ridge, like a hairband. Default volume
  now at most 12 mm (skyrimhair.VOLUME_MAX) over a 5 cm rise (edge_fade). The side locks lying on the outer cheeks
  are Anna's face-framing strands on Starfield's relatively wider face (left as they are).
- 2026-11-02 owner: the KS scalp looks too low (surface view and in game). Cause found: KS wigs carry a 'Hairline'
  shape, a skin-tight scalp layer over the forehead whose texture fades out (Skyrim: alpha test 10 + blend); the
  converted cutout material kept every pixel above 10/255, so the whole fade drew as a hard band down the forehead
  (the Anna tint layer reaches about brow level, rendered headless). Now hair_pack gives tint shapes a cutout at 128
  (--tint-cutoff), the hairline / crown measurements skip the tint layer (skyrimhair.hair_points / is_tint; before,
  the tint's low edge was taken for the hairline), volume never moves it, and the viewer draws it as a separate
  see-through layer. Unverified in game.
- 2026-11-02 owner, in game after the tint cut-off: Anna's hairline sits naturally (verified, screenshot); but the
  hair floats off the skull in places (Caress: sides / temples stand off with dark showing through). The volume
  pushed everything above the ears (full from C_Head + 7 cm). Now the top of the head only (fade from C_Head + 6 cm
  to full at + 12 cm: above the hairline, the sides stay snug like the vanilla hairs), at most 8 mm by default.
- 2026-11-02 owner, in game: Anna / Erena / Spring look better (sit on the head, frame the face; verified); Caress
  shows a brown bun behind the head: not Caress geometry (it ends 12 cm behind C_Head; the bun sticks out further
  and is tinted), so the actor's own hair. Hide Hair was set on the ARMA only; now on the ARMO's BO64 too (0x11 =
  Hide Hair + Hat; supported reading from Fallout 4: the worn item's slots decide what it hides). All still look
  "strandy": candidates are the material (hard cutout at Skyrim's 40/255 where Skyrim blends the strand edges; no
  Starfield hair shading or tint), the ribbon physics pulling locks apart, and the strand-card meshes themselves.
- 2026-11-02 owner sent IDG Elegant Hair Collection (Nexus 17706, RAR5; read for the format only, nothing copied
  but the hair-shader setting values) as the look to match. Verified from its files: 50 looks-menu hairs (HDPT), each
  plain + _facebones NIF, morph.dat per hair under meshes\morphs\human\{female,male}\{chargen,performance}\<name>\
  (face sliders / expressions), NO textures and one custom .mat: the hairs use the vanilla hair materials
  (Long_Straight_Hair_Shared, Choppy_Bob, Medium_Hair_Shared ...). The custom one shows the hair shader:
  ShaderModel Hair1Layer, AlphaSettings HasOpacity, BSMaterial::HairSettingsComponent (DiffuseTransmissionScale
  0.675, DitherScale 1, EdgeMaskMin 0.5, IndirectSpecularTransmissionScale 0.05, MaxDepthOffset 0.01, Roughness
  0.5125), texture slots 0 albedo, 2 opacity, 5 AO, 12 depth offset, 20 hair ID. Added convert_material.build_hair_mat
  (that layout, from scratch), the converter's hair branch (KS diffuse colour + its alpha as opacity, flat AO /
  depth offset / ID fillers written once) and SkyrimConverter.skyrim_hair_material; hair_pack uses it for every wig
  shape by default (--classic-material for the old cutout). Hair colour tint from the actor: unverified (KS diffuse
  is near-grey; whether Hair1Layer multiplies the actor's hair colour is the in-game test). Also --reference-hair
  '<ba2>:<facebones nif>' (pack and viewer): the hair whose hairline / crown the wigs are matched to; IDG's styles
  read here (soft wave 62,498 verts, top 21 cm above C_Head; straight bob 12,730, 18 cm; KS Anna about 15 cm).
- 2026-11-02 Fill layers under raised hair; one copy of KS's two-pass wig. Owner: IDG's hair is "more 3D, filled
  in", a raised KS wig (old --volume) looks like it floats. Measured here (rays out of C_Head over the scalp,
  counting triangle hits; verified on the files): IDG extra-long straight crosses a median 18 hair sheets spread
  over 24 mm; KS Anna 4 sheets within 1 mm (Erena 5 / 12 mm, Spring 3 / 2 mm, Caress 4 / 8 mm), i.e. a thin
  shell. KS also draws every wig twice: 'KSSMP_<name>' alpha-blend (test 40) and '..._HL' alpha-test (test 200),
  identical geometry (Skyrim's two-pass soft edge). Now: skyrimhair.drop_duplicate_shapes (hair_pack with the hair
  shader, the viewer unless --classic-material) and add_volume(layers=N): the wig stays on the scalp, N copies of
  its raised part stand at volume*k/N, each turned LAYER_TURN deg about the vertical (alternating, scaled by the
  fade) to cover the gaps between cards, triangles taking under LAYER_MIN_SHARE of the volume left out (no
  z-fighting at the hairline / on strands); weights / UVs / material copied, so the copies swing with the wig.
  hair_pack / viewer --layers (default 3; 0 = the old move), default volume cap 20 mm with layers (8 without).
  On a stand-in ellipsoid head (no Starfield head here) Anna goes to 10 sheets / 20 mm with 39.5k vertices
  (42.8k before, with the duplicate). Supported, not seen in game.
- 2026-11-02 Fill layers off by default. Owner's viewer shot of Anna with 3 layers at 20 mm (IDG reference): a
  puffed helmet with a hard shelf where the copies end above the forehead and along the part: "that looks so
  choppy". LAYERS = 0 (the wig moves out by at most 8 mm, as before); --layers N kept as an option. The duplicate
  KS '_HL' shape is still dropped with the hair shader. Copying KS cards outward does not give IDG's look; IDG's
  depth is authored (many cards of different lengths at different depths).
- 2026-11-02 Wig colour: --hair-color R,G,B (hair_pack). Owner's in-game shots with the Hair1Layer material: the
  braid drew grey-white, Anna grey-brown, where Skyrim shows them blonde. Verified: Skyrim's KS shapes use shader
  type 6 (HairTint), so Skyrim multiplies the actor's hair colour into a pale texture (opaque texels average about
  sRGB (145, 128, 114) on Anna / Erena / Spring / Caress). Supported: Starfield does not tint an armor item's hair
  material by the actor's hair colour (the result in game was the texture's grey); the actor's colour is a head
  part matter, for the later looks-menu hairs. pipeline.recolor scales each channel so the visible texels (alpha >=
  128) average the chosen colour (variation kept); skyrim_hair_material(color) gets its own textures / material
  (stem suffix = hex colour); the 'Hairline' scalp fade takes the same colour (skyrim_material albedo_target).
  Default: the texture as is. Classic material: not recoloured.
- 2026-11-02 push_out eases its move into a smooth field. Owner: Anna in game has a bump over the brow where
  Skyrim's hair curves smoothly. push_out moved only the points inside / within 2 mm of Starfield's head (half the
  move spread to mesh neighbours, one card at a time), so the hair followed Starfield's forehead where it pokes
  through and Skyrim's shape beside it: a ridge at the edge of the pushed patch. Now each point moves by the largest
  needed move around it eased off by smoothstep over PUSH_BLEND (40 mm) of distance, along its own head normal, one
  field for all shapes (sources pooled per 4 mm cell: 21k points in ~2.5 s). Synthetic: a 6 mm head bump under
  smooth hair, the result's largest second difference under half the per-point push's, clearance kept.
  --push-blend mm (pack / viewer; 0 = per point). That the brow bump in game is this step (and not the hairline
  lift): supported, not verified.
- 2026-11-02 follow_head: the wig moves with the skull difference before the conform push. Owner (viewer, Anna,
  with the eased push): still a "bridge" over the brow, "it goes kind of down and bumps rather than smoothly going
  down". Cause (supported): the hair keeps Skyrim's forehead curve and is only pushed where Starfield's brow pokes
  through. Now (hair_pack with --skyrim-data, and the viewer): each Skyrim female head point, placed by the head fit,
  gets the move onto Starfield's head along the nearest Starfield normal (out at the brow, in where Starfield's
  head is smaller); a wig point takes the Gaussian (8 mm) average of the moves around it, full within 3 cm of the
  Skyrim head, none beyond 8 cm. The hair keeps its Skyrim height over the skin and curves with Starfield's
  forehead; push_out handles what is left. Synthetic: a sphere vs a head 6 mm out at the front and 4 mm in at the
  back: hair 3 mm over the Skyrim head ends ~3 mm (1.75-4.4) over Starfield's all round, smooth. --no-follow-head
  to compare. In game: unverified.
- 2026-11-02 Smoother defaults: follow_head averages over 20 mm (was 8), push_out eases over 60 mm (was 40).
  Owner (viewer, Anna, side view): the temple strand dips and bumps down the side of the face where Skyrim's is one
  smooth strand: the 8 mm average printed the face's small hollows / ridges (eye socket, temple, brow ridge) into
  the hanging hair. Synthetic: a 4 mm hollow 4 deg wide beside the brow: the hair's largest second difference halves
  with the 20 mm average. --follow-sigma / --push-blend (mm) in pack and viewer to tune. In game: unverified.
- 2026-11-02 Hair-shader opacity ramp. Owner's in-game shots (blonde --hair-color, Hair1Layer): less strandy but
  flickering, checkered dark patches. KS alpha is made for Skyrim's blending: ~20 % of Anna's texels are half clear
  (alpha 40-199; 27 % zero, 33 % 240+), and the hair shader dithers partial opacity in screen space (supported:
  the checker pattern sits where the texture is half clear). Now the hair branch stretches the opacity map
  linearly (pipeline.ramp_alpha): 48 and below clear, 112 and above solid (hair_pack --opacity-ramp LO,HI; 0,255 =
  as before). Also looked at the "back thing" (owner's side shot, ponytail wig): Spring's own mesh gathers the top
  into a raised crown above the ponytail root (KS geometry, seen in a point plot here); the 8 mm top volume adds
  to it (--volume 0 to compare).
- 2026-11-02 drape: the hair bridges the temple hollow. Owner drew (viewer, Anna, side) the path he wants: one
  smooth convex arc from the crown past the brow, where the hair now goes in over the temple and out over the
  brow (it lies 2-3 mm over Starfield's skin and so takes the skin's hollow). skyrimhair.drape: the wig's outer
  surface as distance from the cranium's least-squares sphere centre per 1.5-degree direction, morphologically
  closed over DRAPE_RADIUS (30 mm; dilate then erode: only ever raises), the rise smoothed over the cells that hold
  hair, every point within 3 cm of the head moved out radially by it (none beyond 6 cm). Front and temples only:
  full within 75 deg of the front (none past 95: ears / tucked hair / back) and below 45 deg elevation (none above
  60: the parting). Runs after volume, before push_out; scalp tint not moved. Synthetic: a 5 mm, ~2 cm hollow at the
  temple bridged (87.5 -> >90.5 mm of 92), one at the back left alone, flat parts unchanged. --drape mm (0 = off).
  In game / on the real head: unverified.
- 2026-11-02 DRAPE_RADIUS 50 mm (was 30): owner's viewer with --drape 50 smoothed the remaining wave at eye level;
  going into the in-game build as the default.
- 2026-11-02 No mirrored back faces under the hair shader. Owner's in-game shots (opacity ramp in): the hair looks
  like hair now but strands flicker dark / light. KS shapes are double-sided, so hair_pack added a mirrored copy of
  every triangle (same place, normal reversed: skyrimconvert.with_back_faces). Verified: IDG's hairs carry no
  mirrored triangles (6 styles checked: 0-2 reversed twins in 20-50k triangles), so the hair shader draws both
  sides itself (supported); the copy then z-fights the original with opposite lighting. hair_pack.back_faces_for:
  none with the hair shader (the classic cutout material keeps them). Also ~halves those shapes' vertices.
- 2026-11-02 --hair-setting NAME=VALUE (hair_pack; converter.hair_settings -> build_hair_mat). Owner: the moving
  dark spots stay on the no-physics wigs with hard edges (--opacity-ramp 100,101), so neither the cloth nor the
  dithering. Next suspect (supported, not verified): the depth offset. MaxDepthOffset 0.01 m (IDG's value) with our
  flat mid-grey DepthOffset map moves every hair pixel's depth by up to ~5 mm, more than the 2-3 mm the wig sits
  over the scalp, so the head can win the depth test in patches that change with the view. Test: MaxDepthOffset=0.
- 2026-11-02 Hair cards turned to face outward (skyrimhair.orient_outward, hair_pack with the hair shader). Owner:
  the light / dark changes stay with MaxDepthOffset=0 too ("still changing constantly lighting wise"). Verified on
  the meshes: IDG's cards all face away from the head (99-100 % of the triangles over the head face out; normals on
  the faces' side); KS's face out only about half the time (Anna 50 %, Erena 80 %: per card, 36 of Anna's 73 cards
  face the scalp), which Skyrim's two-sided lighting hides. Without the mirrored copies (a7bae09) the inward half is
  lit as facing the scalp (supported: the hair shader does not flip a back face's normal). Each connected card whose
  triangles mostly face inward (away = from C_Head + 9 cm above it, from the vertical through it below) gets its
  winding reversed and normals negated: afterwards 96-100 % face out on Anna / Erena / Spring / Caress / Gecko /
  Icarus. MaxDepthOffset stays IDG's 0.01 (it did not change the spots).
- 2026-11-02 Verified in game (owner, 6f6b560): turning the inward-facing KS cards outward fixed the light / dark
  flicker on the hair-shader wigs. Cause confirmed: the hair shader lights a card's back with the front's normal.
- 2026-11-02 owner: can the wig use the player's hair colour? As apparel, no (seen: the hair shader on an ARMO drew
  the texture's own grey). A head part takes the actor's hair colour (supported: that is how vanilla and IDG hairs
  are coloured; for our own Hair1Layer material unverified). hair_pack --head-parts: every wig also becomes a
  playable hair head part copied from the vanilla playable hair whose model is the cloth template's (bob_f), with
  its own EditorID / FULL '<wig> (Skyrim)' / MODL (the wig's NIF, its _facebones twin and cloth), its race list
  (RNAM), cap mask (NAM3) and hair category (NAM2) kept, HNAM (extra parts) and MNAM (face-slider morphs, made for
  the template's vertices) dropped. Verified from IDG's plugin: its 46 hairs are HDPT type 3 with DATA 0x01 and the
  vanilla race list 0x24A024; its overrides of HeadPartsChargenOptionsFemale / Male add none of its own hairs, so
  playable head parts reach the looks menu without list edits (supported; no list override here, so no conflict
  with IDG). No morph.dat yet: the hair does not follow face sliders / expressions.
- 2026-11-02 Owner's run: the playable hair head parts (copied from Human_Female_Hair_Bob) did not appear in the
  looks menu. So a playable flag and race list are not enough (the IDG reading above was wrong on that point; how
  IDG reaches the menu is unresolved: its override of HeadPartsChargenOptionsFemale lists only vanilla FormIDs).
  Now --head-parts also overrides the vanilla FLST HeadPartsChargenOptionsFemale (read from the owner's
  Starfield.esm) with our head parts appended; the report says how many of its entries are head parts / lists and
  whether the copied template is one of them. Load-order conflict with any other mod overriding that list.
- 2026-11-03 Verified in game (owner): with the female chargen list override the KS hairstyles appear in the
  looks menu and take the character's hair colour (our own Hair1Layer material is enough for the tint). New issue:
  close up they look like folded plastic sheets next to the vanilla bob (no fine strands). Checked here and ruled
  out: UV / strand direction (KS and IDG both run strands along +V, pointing down) and normal roughness (KS's normals
  are smoother than IDG's: 2.3 vs 7.5 deg median spread within 1 cm). Suspect (supported): the opacity ramp (48-112)
  made most of KS's soft strand alpha solid, and KS carries its strand detail in the alpha; the ramp was added
  against the flicker that turned out to be the inward-facing cards. Next test: --opacity-ramp 0,255.
- 2026-11-03 Strand maps for the hair shader (default; --no-strands for the old ramp path). Owner's looks-menu and
  in-game shots (opacity ramp 0,255): blocky maze-like patches in the hair close up, "not that hairlike compared to
  Starfield's", and "clear difference in colours in the different parts". Both read as the textures, not the mesh:
  KS's alpha is soft (made for blending), which the hair shader dithers into blocks, and KS paints broad light /
  dark shading into its albedo, which the lit, tinted shader shows as patches. pipeline.strand_maps: the alpha
  upscaled 2x and cut into crisp 2-texel strands along V (one random threshold per strand, wobbling slowly), so the
  solid share follows KS's alpha (Anna: 0.549 alpha -> 0.552 solid); the strand's random value is the hair ID map
  (per-strand variation, was flat). pipeline.flatten_albedo: each texel divided by the brightness of the visible
  texels within 24 texels (strength 0.8): broad patches evened, strand lines kept. The physics test (owner): the
  no-physics copy shows less top / bottom difference, so part of it is the cloth bones turning (the planned rig
  rework); some layering difference remains.
- 2026-11-03 separate_layers: stacked KS cards moved apart (hair_pack with the hair shader, --layer-gap mm, default
  0.8; 0 = off). Owner: with crisp strands the hair reads as hair in the looks menu, but a maze pattern stays
  "etched" into it. Verified on the meshes: KS lays cards directly on each other (Anna: in 91 % of 6 mm patches
  where cards overlap, consecutive cards lie within 0.5 mm, median gap 0; Erena 55 %, Spring 59 %), which Skyrim's
  sorted blending hides; Starfield's hair shader writes depth, so the cards z-fight and the winner changes along
  the triangles (supported: the outlines are staircase-shaped like triangle edges). Per 6 mm patch the cards are
  ordered by distance from the head and each moved out to sit 0.8 mm over the one under it, smoothed over mesh
  neighbours, 4 passes, total capped at 6 mm, outward only: Anna's stacked share 91 % -> 2 %, Erena 55 -> 9, Spring
  59 -> 12. Runs after the conform step.
- 2026-11-03 The maze / brick pattern is in KS's colour texture. Owner's looks-menu shots after separate_layers:
  the pattern stays, brick-shaped across the strands. Verified on Anna.dds: strands run down the texture, and KS
  paints horizontal light / dark bands across them every ~200 texels (darker roots, darker and warmer bands:
  Skyrim-era painted highlights); every card samples them at its own height, so neighbouring cards meet light
  against dark: bricks. (No dark fringe at low alpha: luminance 131-138 at every alpha.) flatten_albedo now evens
  per channel over a window 9 texels along the strands and 129 across them: the row-mean RGB spread falls from ~26
  to ~3.5 while the across-strand detail stays (row std 23 -> 25). The stacked-cards fix (separate_layers) stays:
  the z-fighting was measured, the pattern may have had both causes.
- 2026-11-03 Hair tangents from the UVs (skyrimhair.uv_tangents, hair_pack after every shape change). The brick
  pattern stayed after the texture fixes (owner's looks-menu shots). Verified: Starfield's convention (IDG, two
  styles) puts the tangent along dP/du (|cos| 1.0); the tangents read from KS's NIFs run along dP/dv (Anna / Erena
  |cos| 1.0 with dP/dv, ~0.2 with dP/du): the Skyrim tangent / bitangent swap. The hair shader lights along the
  strand from the tangent frame, so the hair was lit across its strands, bands breaking at the cards' quads
  (supported). Now per-vertex tangents = area-weighted dP/du, made perpendicular to the normal (degenerate UVs keep
  the old tangent, also made perpendicular). Lead, unverified: every other Skyrim conversion that copies the NIF's
  tangents (convert_static / skyrimconvert) may have the same swap, which would turn normal maps by 90 degrees.
- 2026-11-03 Verified in game (owner, c57e2b0): the UV tangents removed the brick / maze pattern ("got rid of the
  weird texture looking thing"). Remaining: "the lighting still is off": in his looks-menu shot a darker band with a
  sharp top edge under where the top layer ends (supported: the top layer's shadow on the cards under it, which
  separate_layers moved up to 6 mm apart, or the cloth bones' rotation; unresolved).
- 2026-11-03 Balanced physics ribbon (smpcloth Settings.balance, default on; hair_pack --no-balance). Owner: the
  dark lower hair stayed with --layer-gap 0 and moved up with --twist 1.0 --damping 0.9 ("that did change where the
  lighting is happening"): so it follows the cloth (verified as a dependency). Cause (supported): each lock was a
  two-row ribbon, the side row 1.5 cm to one side, so gravity turned it about its own length until it settled;
  each chain bone follows its ribbon triangle, so the bones turned and took the lower hair's normals with them
  (lit as facing sideways / down). Now a third row mirrors the side row about the joint (C = A - width x side),
  with its own triangles, links, twist brace and a B-C link holding the section's width: the section's weight sits
  on the joint, so gravity no longer turns it. The bones' own triangles (A0, B0, A1) are unchanged, so the rest
  pose and verify() results are the same (Anna: bone 6e-6, pins 6e-8).
- 2026-11-03 owner: export all of Skyrim's hairs to the looks menu, and the test NPCs with their correct Skyrim
  hair. Decisions: (1) hair_pack's steps became reusable (setup_head per sex with Starfield's / Skyrim's male or
  female head, setup_reference, shape_hair, hair_materials, add_shape_args) with the KS output unchanged;
  (2) scripts/npc/skyrim_hairs.py: hair head parts (type 3; --facial-hair adds 4) of Skyrim.esm, Update, Dawnguard,
  HearthFires, Dragonborn (FormIDs resolved through each plugin's masters, later plugins override), not extra parts,
  not the beast races (race list / model / EditorID naming Khajiit or Argonian), NPC-only ones included unless
  --playable-only; sex from the DATA flags (female 0x04, male 0x02; neither: by name; beards male); each part's
  models merged, converted rigidly (vanilla Skyrim hair has no physics), shaped for that sex's head, hair shader
  without baked colour (the character's applies), _facebones twin from the template's facebones file; the record
  copied from the first hairstyle of that sex's vanilla looks-menu list (the cloth template's, bob_f / bob_m, when
  listed), MNAM / HNAM dropped, appended to HeadPartsChargenOptionsFemale / Male; S2SSkyrimHairs.esm + ba2s;
  (3) npc_hair / face_fit --hair use the same builder (skyrim_hairs.build_part) per NPC sex with the NPC's Skyrim
  colour multiplied into the albedo (beards too, as Skyrim tints them) and the NPC's HCOL / FHCL set to the
  lightest-sounding hair colour name the game's NPCs use (by name: white, platinum, silver, grey, blond; unverified
  which is lightest: reported, --hair-color-name). Unverified in game: all of it; the head part types 3 / 4 are
  verified on xEdit's SF1 definitions (3 Hair, 4 Facial Hair, 11 Extra Hair).
- 2026-11-03 Owner's first runs: skyrim_hairs --only Nord01 built 2 hairstyles (one per sex) and they show in the
  looks menu with the chosen hair colour (verified); but the KS hairstyles vanished: S2SSkyrimHairs.esm's override of
  HeadPartsChargenOptionsFemale replaced S2SHair.esm's (verified by the result; the expected load-order conflict).
  Now skyrim_hairs keeps other plugins' list entries (--merge-plugin, default S2SHair.esm in the "S2S Hair" folder
  next to --out): that plugin becomes a master, its override's entries are remapped into our FormID space, ours come
  after both masters. face_fit: Ralof / Ysolda fitted (rms 4.4 -> 3.4 mm, 3.9 -> 3.1 mm: about 22 % of the
  difference closed, a modest fit); the test NPCs wore their template's helmeted space suit, so test NPCs now drop
  SOFT (Space Outfit, xEdit SF1 NPC_) and keep the default outfit.
- 2026-11-03 Skyrim hairstyles: owner's looks-menu shots of the converted vanilla hairs: "very flat", "a gap
  between the head and the hair like it's floating", texture "horizontal and not very hair like", patchy light /
  dark. Two changes (supported, not seen in game yet): (1) skyrim_hairs and face_fit --hair use VANILLA_DEFAULTS:
  no hairline lift, no volume, no temple bridge (drape), conform blend 15 mm, card spacing 0.3 mm. The KS steps
  move a thick layered wig; a vanilla hair is one thin shell over its own hairline layer, and every one of them lifts
  the shell off that layer (the 60 mm blend lifts a whole region by its deepest point); the KS defaults stay in
  hair_pack. (2) skyrimhair.strand_axis / strands_down: a shape whose steep triangles have dP/du pointing down more
  than dP/dv lays its strands along U; its UVs are swapped and its texture transposed (pipeline transpose=True,
  material stem _rot), because the strand maps, the band evening and the hair shader's tangent frame all assume
  strands along V (verified on KS and IDG). "Very flat" is partly the vanilla meshes themselves (few cards).
- 2026-11-03 Owner: the Skyrim hairstyles are "much better" (verified: no gap, mostly strands down), but the scalp
  is "strandy across" and some hair still has sideways lines. (1) Strand direction is now judged per card (connected
  piece), area-weighted, against the way hair runs there (down and out from a point 24 cm above C_Head, so cards on
  the crown are judged too, not just hanging ones); a shape whose cards disagree is split, the turned cards as
  '<name>_rot' with swapped UVs and the transposed texture. (2) The scalp layer (Skyrim's hairline extra parts,
  model path with 'hairline', named 'Hairline_...' so is_tint holds) gets no strand cutting, no turning and its own
  soft alpha (no ramp) in every pipeline (KS's 'Hairline' too): the strand maps had cut its fade into lines.
- 2026-11-03 Reverted the soft scalp layer (8ff9fe4). Owner's shots of that build: front hair missing (bald
  forehead), the rest smooth and flat. Supported: Skyrim's hairline extra parts carry the front hairline's own short
  hair cards, not only a scalp fade, and their alpha without the strand cut / ramp drew mostly see-through. Kept: the
  per-card strand direction (crown included) and the split of mixed shapes. The report now lists each shape (name,
  vertices, turned, material) per hairstyle (skyrim_hairs.json "shape_detail").
- 2026-11-03 Reverted the per-card strand direction too (back to 440ffc1's whole-shape check). With the soft scalp
  undone the front / top hair was still missing in the owner's shot, so the per-card turning was the cause.
  Measured here on KS (all of whose strands run along V): the per-card judgement against the hair's flow turned many
  cards wrongly (Spring 5586 of 19287 triangles, Icarus 4451 of 11796: braids, curls, ponytails lying sideways):
  strands follow a card's own length, not gravity. Next, if sideways lines remain: judge a card by its UV island
  (long in U or in V), with the owner's shape_detail report of the affected hairstyle.
- 2026-11-03 Vanilla Skyrim hair: the strand direction now comes from the texture, region by region
  (pipeline.strand_orientation: per 32-texel square, which way the alpha + luminance change most; strands vary
  across their width, not along their length). Strands are cut (strand_maps), the albedo evened (flatten_albedo) and
  each card's tangents chosen (dP/du, or dP/dv where its texture's strands run along U: skyrimhair.strands_across,
  sampled at the card's UVs, majority per card) to match. Replaces the whole-shape mesh guess (strands_down) for
  skyrim_hairs / NPC hair: owner's shot showed strands cut across on the back of the head, i.e. one texture holding
  both layouts. Checked here: DintHair and FO4 HairCurly read as all-V (0 % across), the same texture transposed as
  99.9 % across, a half / half composite as 2 % / 99 %. KS wigs unchanged (orient off; their textures are all V).
  Alternatives: per-card UV-island shape (needs the texture's layout anyway), per-card gravity (reverted: misjudged
  braids and curls).
- 2026-11-03 Verified in game (owner, 52558cc): the strand direction from the texture fixed the wrong-way lines on
  the vanilla Skyrim hairstyles. Remaining: soft dark / light patches, as on the KS wigs (no physics on these, so
  the cloth is not the whole cause of that either). Two changes: (1) vanilla hairstyles get their vertex normals
  recomputed from the final shape (skyrimhair.geometric_normals; hair_pack --geometric-normals, on in
  VANILLA_DEFAULTS, off for KS): Starfield's own convention (IDG: normals = the faces', verified), and the stored
  Skyrim normals are not moved by the shaping; the report gives per shape how many old normals pointed against
  their faces (supported cause, unverified). (2) skyrim_hairs --diagnose: per hairstyle three more looks-menu
  copies, each without one suspect: 'flat colour' (albedo one colour: if the patches stay, they are lighting, not
  the texture), 'no see-through' (opacity full: if they go, they are what shows through the strand gaps) and
  'shell normals' (every normal pointing away from the head: if they go, they come from the cards' tilt).
- 2026-11-03 skyrim_hairs report "fit" and per-shape opacity. Owner (front shot next to Skyrim): the vanilla
  hairstyle does not sit / flow from the scalp like Skyrim's: a pale band of thin strands between the forehead and
  where the dense hair starts, and the hair stands off like a helmet. Unresolved which: the hairline part's coverage
  (Skyrim blends a soft alpha, we cut it into strands: same coverage, but read as thin hair over skin), or the
  placement. Measured now per hairstyle: fit.skyrim / fit.starfield = the hair's distance to the head per region
  (front / top / left / right / back; 10th percentile = how far the inner layer floats), Skyrim's hair on Skyrim's
  fitted head vs the result on Starfield's; fit.hairline_vs_vanilla_mm = our hairline minus the vanilla Starfield
  hair's per angle; shape_detail[].skyrim_alpha (blend / test / threshold) and .opacity (alpha mean, share over
  Skyrim's threshold, share solid after the cut). The '--diagnose' 'no see-through' copy shows the coverage case.
- 2026-11-03 Diagnose round 1 (owner, back shots of one vanilla hairstyle): the normal build, 'flat colour', 'no
  see-through' and 'shell normals' all show the same light / dark patches (sharp-edged lighter blocks, darker lower
  hair). Ruled out (verified in game): the albedo, what shows through the strand gaps, the vertex normals / card
  tilt. Left: what all four shared, the per-card strand direction (the tangent frame; a hair shader's diffuse and
  highlight follow the strand, not the normal: supported, it also fits the KS band moving with the cloth bones),
  the light through the hair (DiffuseTransmissionScale 0.675, IDG's) and shadows / screen-space occlusion (not
  testable from the material). Round 2 copies: 'combed strands' (skyrimhair.comb_strands: each vertex's strand
  direction averaged with its neighbours' within 15 mm over all cards, sign-agnostic, tangent rebuilt across it)
  and 'no light through' (both transmission scales 0). The round-1 copies are dropped from --diagnose.
- 2026-11-03 Diagnose round 2 (owner, ponytail hairstyle): 'combed strands' and 'no light through' keep the same
  patches. Ruled out in game: strand direction (combing turned it by a median 2-7 deg, p90 13-26) and the
  transmission. His skyrim_hairs.json (Nord / Imperial, 48 hairstyles) shows two things instead (verified on the
  report): (1) the vanilla Skyrim hairs are low-poly shells: 200-2000 vertices per hairstyle (IDG: 20-50k
  triangles), so the shell is a few large flat facets (his shots: a faceted helmet outline, broad flat light /
  shadow areas); (2) every Nord hairline extra part (Hairline01..21) was alpha-BLENDED in Skyrim (no test), on the
  same texture as the hair: Skyrim showed it as a soft coat of hair colour on the scalp; our strand cut turns it
  into sparse thin strands, the pale band between the forehead and the hair in his front shot (supported). The fit
  report's gaps are to the nearest head vertex, so Skyrim's (coarse head) read high: not comparable; Starfield's
  2.5-3.5 mm front / sides say the shell lies on the scalp, not floating. Changes (VANILLA_DEFAULTS; hair_pack
  options, off for KS): --tessellate 3 (skyrimhair.tessellate: each triangle split 3 x 3 onto its curved PN
  triangle from the corners' normals averaged per position, no seam cracks, UVs / weights interpolated) and
  --blend-coverage 3 (shapes Skyrim alpha-blended get alpha 1 - (1 - a)^3 before the strand cut, own material
  '_c3'). The patches themselves: unresolved; with every material / shading suspect ruled out what is left is the
  geometry (shadows on large facets), which the tessellation changes. Needs a vanilla Starfield hair shot from the
  same angle as a reference.
- 2026-11-03 Owner's shots after 4a97218, next to vanilla Starfield hair (a slicked-back short style and a bun):
  the back is smoother (tessellation: the broad flat patches mostly gone, one hatched spot left at the crown) but
  the front still has a bare band between the forehead and where the Skyrim hair starts; the denser blended
  hairline did not fill it. His report (before this build) put our hairline above the vanilla hair's in the middle
  (Nord01 +13 mm at 0 deg, +35 at 10, +61 at 20; varies by style and side). Starfield's hairstyles carry extra parts
  (HNAM on the copied vanilla template; KS's head parts drop them). Now the vanilla Skyrim hairstyles keep the
  template's extra parts (hair_part_record keep_extra_parts; skyrim_hairs --no-starfield-hairline to drop), so
  whatever the template draws under its hair (supported: a hairline / scalp piece, unverified which) is drawn under
  the Skyrim hair, in the character's hair colour; the report lists them ("template_extra_parts": EditorID, type,
  model). Expectation set with the owner: the vanilla Skyrim hairs are 2011 low-poly shells (200-2000 vertices)
  and will not reach the strand detail of Starfield's own hair; the goal is that they sit right and look clean.
- 2026-11-03 Owner (5d753c2): front unchanged. His report: the templates Human_Female_Hair_Bob / Human_Male_Hair_Bob
  have no extra parts (template_extra_parts empty), so keeping HNAM added nothing (the option stays, harmless).
  The blended-hairline coverage ^3 was measured on the whole atlas (0.79 after the cut), not where the hairline
  samples it, so it says nothing about the band. Now a Skyrim-blended shape's alpha is first brought to full at
  its own part of the texture (pipeline.normalize_region_alpha: UV points spread over its triangles,
  hair_pack.uv_samples; gain = 255 / the 90th percentile of the hair texels there, capped 8x; own material per
  shape, '_r<hash>'), then ^3, then cut; the report gives per shape opacity.region (samples, alpha mean, gain, share
  solid after the cut). Not done: lowering the front hairline to the vanilla hair's: the bob's hairline is
  lopsided (side fringe: 97.8 mm above C_Head at 0 deg, 73 at +10, 47 at +20), so it is no target per angle.
- 2026-11-03 Owner (0423c52): front exactly as before, and the colour still differs a lot between parts of the
  hair (top solid and light, sides stringy with dark gaps). Reading: the region-normalised hairline changed nothing
  visible, so the bare band is not our hairline layer drawn too faint but forehead that our hair does not reach (the
  fine strokes in it are on the skin: supported, Starfield's head shading under the copied bob's cap mask NAM3),
  matching the report's +12..23 mm above the vanilla hairline at the middle. Changes (VANILLA_DEFAULTS):
  --hairline-drop 20 (skyrimhair.drop_profile: own hairline minus the vanilla hair's made symmetric, each angle the
  higher of its two sides because the bob's fringe hangs low on one side; within +-40 deg, at most 20 mm, smoothed;
  lift_hairline with negative values brings the front down along the head) and --skyrim-cutout (shapes Skyrim
  alpha-tested: pipeline.cutout_alpha remaps alpha so the strand cut is solid from 24 over Skyrim's threshold and
  empty from 24 under it: alpha 0.4-0.7 over a threshold of 0.3 had been half see-through, showing the dark
  insides). The README lists the hairstyles in looks-menu order (the menu shows no names).
- 2026-11-03 Owner (9c9cd97, front / side shots next to Skyrim): sits better on the face (the front came down);
  remaining: the parts of the hair differ strongly in colour, most where they overlap (the top piece near-white
  with a sheen, the sides grey), and the hair sits on the scalp rather than growing out of it. Not resolved here;
  diagnose round 3 instead of another guess: 'soft hairline' (Skyrim's blended layers keep their soft alpha,
  dithered by the shader, instead of the strand cut: the fade at the roots Skyrim's blending gave) and 'rougher'
  (Roughness 0.85 instead of IDG's 0.5125: a wider, weaker highlight; supported: the near-white top is the
  shader's highlight on a large smooth surface whose strands all point one way). The round-2 copies are dropped.
- 2026-11-03 Owner, diagnose round 3: 'soft hairline' and 'rougher' look exactly like the normal hairstyle; the
  colour differences between the parts are "atrocious"; strands dip into the skull where they meet at a centre
  parting; and the hair does not follow the face-shape option (round / square), unlike vanilla hair. Notes: (1) no
  material-settings-only copy has ever looked different (transmission, roughness; MaxDepthOffset on KS): either the
  settings do little or the game does not take them from our .mat (unresolved). (2) Default for the vanilla Skyrim
  hairs and NPC hair now MaxDepthOffset 0 (skyrim_hairs.VANILLA_HAIR_SETTINGS): with our flat mid-grey depth map
  IDG's 0.01 m can move hair pixels ~5 mm deeper, more than the 0-4 mm these shells lie over the skin (supported
  cause of the dipping at the parting); --diagnose now makes one '[depth]' copy with IDG's value, which also tests
  (1). (3) Face shape: vanilla / IDG hairs carry a morph.dat per hairstyle (meshes\morphs\human\<sex>\chargen\<name>\
  and \performance\). Verified header from IDG's files: 'MDAT', u32 version 3, u32 vertex count (= the hair mesh's),
  u32 morph count, then that many u32-length-prefixed names (female chargen: 'Hat', 'Overweight', 'Thin', 'Strong',
  and per head preset and region e.g. 'female_eu_md2_Forehead', '..._Chin', '..._Ears', '..._Eyes', '..._Neck',
  '..._Cheeks', '..._Jaw'); the per-vertex data after it is not decoded yet (unresolved). Next: decode it against the
  head's own morph.dat and write one for our hairs by moving each hair vertex with the head vertices under it.
  (4) Starfield's strand look: IDG's hairs use the vanilla hair materials and textures (verified 2026-11-02), i.e.
  their UVs are laid out for Starfield's textures. scripts/armor/hair_probe.py reads vanilla hairstyles' .mat
  (ContentResources.zip) and textures (game archives) and reports their settings, slots and texture statistics
  (depth map percentiles, AO, albedo spread, opacity strand direction) with small PNGs: the evidence for re-texturing
  the Skyrim cards with Starfield's hair textures.
- 2026-11-03 hair_probe.py on the owner's game (verified, his hair_probe.json): the vanilla hairs' materials are
  Medium_Hair_Shared (bob), Long_Unkempt_Wavy_Hair_Shared (hairspray bob), Beard_shared (buzz cuts); their
  textures: albedo a dark brown, mean sRGB (36-42, 22-26, 12-14), luminance spread ~10; AO mean 124-138 (p10 = median
  108-125, p90 ~190); depth offset spread per strand (p10 11-15, median 163-174, p90 ~249); hair ID median 30-48
  (p90 62-101); opacity 10-18 % solid, strands down the texture. Their settings differ per material (the bob:
  Roughness 0.25, DiffuseTransmissionScale 0.7, DirectTransmissionScale 0.2375, SpecularTransmissionScale 0.675,
  AlphaDistance 0.37, MipBase 2.5, MaxDepthOffset 0.01). Ours: Skyrim's light albedo, AO white, IDs over 0-255: a far
  brighter, patchier hair than vanilla. Now (--vanilla-maps, on for the vanilla Skyrim hairstyles): albedo recoloured
  to the vanilla mean (38, 23, 12) keeping the strand detail, a per-strand AO map in 108-190 (mostly low), hair IDs
  in 28-101. Owner's [depth] copy (IDG's MaxDepthOffset) looked the same as the new default 0 (settings-only copies
  still never differ in game; unresolved).
- 2026-11-03 Owner (f5280e6): with a brown hair colour our hairs now match vanilla's tone, with a blonde one they are
  grey-white and patchy ("the colour is still off"). Read: Starfield colours hair from colour maps shared by all
  hairstyles, a gradient that shows along each hairstyle's strands (Nexus mod 'Ombre Hair Colours', its description:
  supported, not verified), i.e. looked up by the albedo's brightness; vanilla's albedo (probe PNGs, visible texels)
  is dark with a narrow range (luminance p5-p95 ~8-46, median ~21; roots darker than tips) in one brown ratio. Ours
  had only been scaled to vanilla's mean, keeping Skyrim's wide painted range (strand highlights far up the colour
  map: white for blonde). Now pipeline.vanilla_albedo: each texel's brightness remapped by rank onto vanilla's
  percentiles, coloured in vanilla's R:G:B ratio (Skyrim's light / dark pattern kept, its range and colour vanilla's).
  Not done: darker roots (where a Skyrim card's root is is not known per card).
- 2026-11-03 Strand cards (owner: "do we need to make it so it has all the strands like Starfield's" - yes; the
  vanilla Skyrim hairs are a few shells with painted strands, which light as big surfaces under Starfield's hair
  shader whatever their textures). fo4sf.hairstrands: the shaped Skyrim hair (fitted, tessellated, its strand
  direction from the texture-read tangents) is only a guide; per layer (3, 1.5 mm apart) random seed points on it are
  traced over the guide to the root and to the tip (stopping off the guide, at sharp turns, and where the root-to-tip
  direction reverses: crown / parting), lines kept when they do not mostly overlap kept ones (7 mm cells), each a
  12 mm ribbon (+-20 %) mapped onto one strand strip of a vanilla hair texture (root at the strip's top: verified
  from Medium_Hair_Shared's albedo, darker at each strip's top), weights from the guide vertex under each point.
  The cards use the vanilla material itself (Medium_Hair_Shared.mat, the bob's; --strand-material), as IDG's hairs
  do: Starfield's strands, AO, depth, IDs and hair colour unchanged. Strips found from the vanilla opacity map at
  build time (strip_layout: 3 rows, 11-14 strips per row on the owner's Medium_Hair_Shared). skyrim_hairs
  --strand-cards adds a '(Skyrim, Starfield strands)' copy of each hairstyle next to the current conversion.
  Synthetic shell: ~400 cards, ~39k triangles, ~4 s. Unverified in game.
- 2026-11-03 Strand cards, round 2. Owner's shots of the first build: thin and wiry, not full, "gives them bangs"
  instead of following the outline, and all wavy. Causes (supported): (1) the root-to-tip sign came from "away
  from the crown", which sends the front strands of slicked-back styles forward over the forehead; (2) Skyrim's
  hairline layers reach down the forehead fading to nothing, and the cards followed their geometry, not their
  opacity; (3) Medium_Hair_Shared's strands are wavy, and the step-by-step trace zig-zagged over the guide's facets;
  (4) one strip layer over a see-through texture (vanilla opacity ~17 % solid) is thin. Now: the strand direction
  and its sign from the texture's +V (uv_strand_dirs: root to tip by the KS / Starfield convention, verified for
  both), the crown rule only where the UVs give none; per vertex coverage = the Skyrim texture's opacity at its UV
  (ramped round Skyrim's alpha-test threshold), seeds and traces only where coverage >= 0.4; the field averaged
  over the 6 nearest vertices, lines smoothed; the material Long_Straight_Hair_Shared (22 of IDG's 50 hairs use
  it, read from its NIFs); 16 mm cards, 6 mm apart, 3 layers 2 mm apart, the inner layer on the denser half of the
  strips, up to 1800 cards; and the converted Skyrim hair kept under the cards (its body; the cards give strands
  and outline). Speed: neighbour queries use scipy's cKDTree when installed (synthetic 7k-vertex guide: 3 s
  per hairstyle with it, 50 s with numpy alone) and the guide is thinned to one vertex per 4 mm.
- 2026-11-04 Strand cards round 3. Owner (7271bc7): "it just looks like the originals again, not like it's using
  Starfield's": with the converted Skyrim hair kept under the cards the Skyrim look wins (the cards' strands are
  mostly see-through, vanilla opacity ~17 % solid). Now two copies per hairstyle: '[strands]' the cards alone and
  '[strandsbase]' the cards over the Skyrim hair, both denser (5 layers 1.5 mm apart, lines 5 mm apart, 18 mm wide,
  10 mm rows, up to 3500 cards; synthetic shell: ~2100 cards, ~100k triangles in 5 shapes of ~21k vertices, 4 s).
- 2026-11-04 Strand cards round 4. Owner (3766082): the '[strands]' copy (cards alone) "does look like Starfield
  hair now", fuller and sitting right; left: a bang-like front on some styles, and from the back "choppy" instead of
  strand-like. His report: Long_Straight_Hair_Shared loaded (20 strips), coverage 50-99 %, 2600-3500 cards; some
  styles average ~10 triangles per card (Nord16: 3500 cards, 36k triangles): many short cards. Causes (supported):
  traces stopped at every gap between Skyrim's painted strands (per-vertex texture opacity), so lines broke into
  short pieces, and every card took the whole strip (its hard root edge where a card starts mid-hair: the chop);
  scalp pieces whose texture runs from the crown end their tips at the hairline (a fringe). Now: coverage averaged
  over each guide vertex's 16 neighbours, seeds where >= 0.4, traces go on while >= 0.2 (synthetic: a 38 %-gapped
  coverage traced 4 cm before, down to the hem now); cards shorter than 4 cm dropped; a strip stands for 30 cm of
  hair and a card takes its last part (tip end wispy, root end inside the strands); a line on the scalp at both
  ends whose tip is its front end on the upper forehead (> 75 mm over C_Head) is turned round (root at the
  hairline), real fringes (ending lower or hanging free) kept.
