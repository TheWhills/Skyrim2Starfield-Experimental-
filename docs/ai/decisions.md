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
- 2026-11-05 Strand cards round 5. Owner (d93c27d, dark hair): the back smoother; the front hairline "especially
  choppy": a row of blunt, card-wide blocks (roots now at the hairline, each the full 18 mm wide and a layer's
  height off the scalp, all cut at the same coverage line). Now each card from its root: width from 30 % to full
  over 2 cm (its u range narrows with it: fewer strands, not thinner ones), height from a quarter of its layer
  offset to full over 2 cm (grows out of the scalp), and 0-2 cm cut off its root at random (no straight row of
  card starts).
- 2026-11-05 Strand cards round 6. Owner (668da6f): a style that used to sit too high now has a fringe down to the
  brows, and other hairlines do not start where the hair's shape says. Cause (supported): round 4's smoothed
  coverage (16 neighbours, traces on while >= 0.2) carries cards from the hair onto the faded lower part of Skyrim's
  blended hairline layers, which reach down the forehead. Now a blended layer counts as hair only where its alpha is
  at least 0.5 (skyrim_hairs.skyrim_coverage, BLEND_SOLID), before the smoothing; the random root trim halved to
  0-1 cm (the hairline was set back unevenly).
- 2026-11-05 Armor conversion engine: Outfit Studio. Owner asked for the most long-term-friendly way to convert
  clothes and armor. Reviewed: SFport WIP (MIT; FO4 -> Starfield; Outfit-Studio-style fit: skeleton retarget, smoothed
  body-to-body displacement, push-out, weights and the body's morphs from the nearest Starfield body point; all NIF /
  morph IO through PyNifly's NiflyDLL; its notes: not verified in game) and BodySlide and Outfit Studio v6.1.0
  (ousnius, Nexus Starfield 18449, owner's download; verified from its files: Starfield target game, Starfield
  skeletons, .mesh and morph.dat export, 8 bones per vertex, import of another game's NIF, automation scripts, and a
  built-in MCP server, `OutfitStudio.exe --mcp`, localhost:47823, whose guides cover conform, weight copy, clipping,
  cross-game conversion and batching). Chosen: Outfit Studio does the fitting, weights, body morphs and export; our
  Python picks the armor, drives it over MCP from the owner's PC, converts materials (its guide: Starfield materials
  not mapped) and writes the plugin (Robes of Oblivion layout). Reasons: the fitting is maintained by the tool's
  author and already handles skirts, straps, chains and rigid parts; any bad piece can be fixed by hand in the same
  program. Our own pure-Python fit (SFport's method) stays the fallback if its Starfield output fails in game
  (unresolved: Starfield support is new). First step: scripts/armor/os_probe.py, a read-only look at the server's
  real tools and argument schemas. Side finding (verified on a vanilla female body morph.dat from PyNifly's test
  files with our own reader): morph.dat = 'MDAT', 3 axes, vertex count, key count, length-prefixed key names, record
  count, offset count (= vertices), 16-byte records (3 half-float deltas, u16 colour, packed normal and tangent),
  20-byte per-vertex entries (first record, 128-bit key mask); the body has three keys: Overweight, Thin, Strong.
- 2026-11-05 Worn layer for converted Skyrim clothes and armor (owner's choice): BOTH on the apparel (outfit) layer,
  never the spacesuit layer. Reasons (owner): Skyrim NPCs walk around in their own outfits and never flip between
  suit and apparel; an NPC taken to space wears whatever real Starfield spacesuit is in its spacesuit slot, over the
  apparel (the game hides the outfit layer under a shown suit, verified with the left blade 2026-10-26). Records:
  apparel keywords (InventoryCategoryApparel + ArmorTypeApparelOrNakedBody for body pieces, ArmorTypeApparelHead for
  helmets / hats) on outfit slots 0-31; no spacesuit-layer keyword (ArmorTypeSpacesuitBody hides the naked body
  wholesale and made it invisible; SpacesuitBackpack broke O2 / CO2; SpacesuitShowAlways would draw the armor and a
  real suit together). Skyrim body armor already carries its visible skin, so the body piece must hide the naked body
  through the apparel body slot as vanilla outfits do. Separate Skyrim pieces (gauntlets, boots, circlets, amulets)
  go on free outfit slots. Kept as a converter setting (mesh unchanged, only keywords and slots differ) so other
  layouts stay testable. Unresolved, first in-game checks: whether apparel applies damage resistance from the ARMO
  (where Skyrim's armor rating goes), and that the converted body piece hides the naked body without holes.
- 2026-11-05 Later phase, direction only (owner): a Tamriel planet. From space an ocean world with Tamriel's continent
  (shapes traced by us from maps, not their art), each province a fitting biome, mountains where the maps put them;
  province landing areas (Skyrim, later converted Cyrodiil / Morrowind through TES4 AutoConvert) placed at their
  places on it. Scale (owner's choice): the worldspaces keep their real game scale (Skyrim ~7 km across), so the
  planet is small, moon-sized, and the continent is only as big as the provinces need; neighbouring provinces can meet
  at their border ranges (Jerall: edge-to-edge overlays, or a generated bridge overlay). Reason: also what the
  upcoming seamless-landing mod (Frederik Wessberg; reads planets' height tiles and biome maps) would show from orbit.
  To work out then: a small body's gravity, atmosphere and day length set Earth-like on the planet record; the planet
  height / biome rules (unresolved in terrain notes); the lat/long -> planet cell placement rule (unresolved). After
  Skyrim works on its own planet and the 2 x 2 seam test.
- 2026-11-05 owner (round 6 shots: the shell copy and [strands]): neither has a good hairline; the cards are still
  choppy, card-sized light / dark blocks, worst on light hair (reference: a vanilla Starfield long hair from behind,
  fine continuous strands of one tone; Skyrim's own hair, a soft hairline swept back). Hypothesis (supported by the
  numbers, not verified): 18 mm cards 5 mm apart overlap ~3.6 times within a layer at depths within 0.75 mm, so
  neighbours cross each other and each shows its own strip in blocks. Round 7 copies next to [strands] (unchanged):
  [strandsthin] 7 mm cards at three fixed depths per layer (grow_cards `slots`: gap / 3 apart) instead of random
  ones; [strandsline] the same over Skyrim's own hairline layers (its alpha-blended shapes, the soft fade into the
  scalp; hairline_shapes; report: skyrim_hairline_shapes, 0 = the style has none). [strandsbase] dropped from the
  copies (code kept). Reading the result: thin smoother than strands -> the overlap; line's front better than thin's
  -> Skyrim's hairline layer is the way to the hairline.
- 2026-11-05 owner (round 7, HairFemaleNord01 / 05): [strandsthin] better (finer strands, fewer blocks: supports
  the overlap hypothesis); [strandsline] failed: the Nord styles' blended "hairline" layers cap the whole top, drawn
  over the cards, with a dark comb fringe and pale blobs. Owner, drawing a smooth curve over the shot: "the hairline
  is so wrong ... not starting at a part of the head consistently; you'd want to see it starting from a smooth curved
  line". Cause: each card's root is where its trace stopped (the Skyrim alpha's ragged edge) minus a random trim.
  Round 8: [strandsedge] = thin cards + one smooth front hairline per style (hairstrands.hairline_curve: per 5 deg
  from -80 to +80 round the forehead, the 15th-percentile height of the style's covered hair lying on the scalp,
  filled and averaged over +-25 deg); to_hairline: a front root on the scalp below the curve is cut back to it, one
  stopping above it is carried on down over the guide to it (up to 6 cm), and such roots skip the random trim; the
  back and sides past 80 deg are untouched. Report: hairline_curve_cm, hairline_roots (cut / carried / kept /
  dropped). Copies now [strands], [strandsthin], [strandsedge]; [strandsline] code kept, not built.
- 2026-11-05 owner (round 8, HairFemaleNord01): [strandsedge] lost the Skyrim hair's shape: the plain copy keeps a
  centre parting with two swept sections; the cards criss-cross there; vanilla Starfield hair (pigtails shot) parts
  cleanly and hugs the scalp. Causes (supported, from the code): the guide's direction field averaged the k nearest
  vertices across pieces, so at a parting the two sides' opposite directions mixed into sideways / random ones;
  the voxel thinning kept one vertex per 4 mm cell, dropping one side of a parting; round 8's curve carried roots
  that sit at a parting (strands falling to the sides) down to the front hairline. Round 9 (same [strandsedge]):
  Guide.island (mesh pieces), thinning per voxel and piece, field() averages only the nearest vertex's piece and
  strands running its way; to_hairline carries only roots combed back from the face; layers 1 mm apart (was 1.5).
- 2026-11-05 owner (round 9 shots): the strand copies still look wrong (choppy, roots splayed on the forehead);
  "the KS hair versions look far far better than our tests ... I'm wondering if we've gone too far. Those were
  simple, there were just some lighting issues, almost certainly caused by us using a hair shader that expects
  strands". Strand cards paused (code kept, --strand-cards off by default). Next: the KS wigs as looks-menu hair
  with the generic cutout material (hair_pack --classic-material: no Hair1Layer shader) to see whether the
  light / dark patches go. Known trade-off: the classic material is not tinted by the character's hair colour
  (unresolved for head parts; the KS textures are pale grey, so --hair-color bakes a colour in until then).
- 2026-11-05 owner: KS Anna as a looks-menu hair with --classic-material (+ --hair-color 170,140,100) "looks way
  worse" (flat, the cards' rectangles visible) and "that weird line is still there" (a dark line along the hair's
  outline). Reverted to the hair shader (the default). Finding (verified by that shot): the dark line is not the
  hair shader's doing; it stays with the plain cutout material, so it is geometry or draw order (next to look at).
- 2026-11-05 Study of IDG Elegant Hair Collection v1.4.1 (owner's download; read-only scratchpad tools
  idg_hairline.py / idg_detail.py; verified on its files): 50 styles, one skinned shape each, all on vanilla hair
  materials (Long_Straight_Hair_Shared, Medium_Hair_Shared, ...), no textures of their own. Fit to the head: C_Head
  plus 16-36 faceBone_* bones, 8 weights per vertex, and per style a chargen and a performance morph.dat (~50 keys:
  Hat, per-preset Forehead / Chin / Ears such as female_eu_md2_Forehead, Overweight / Thin / Strong): the hair
  follows face sliders, head presets and hats. Cards (mesh pieces): 234-3565 per style, typically 300-1000, wide
  ribbons (median ~34-39 mm across at root and middle, no root taper). Hairline: 12-110 cards in the front row
  (median ~27), roots 3.5-7 mm apart, on one smooth curve ~10-11 cm above C_Head mid-forehead falling to 3-6 cm at
  the temples; one sheet at the very hairline, thickening behind it (front rays cross 1-15 cards, 0-33 mm).
  KEY FINDING: every IDG mesh carries vertex colours, ours carry none (skyrimhair._mesh passes no colours): R runs
  ~95 at a card's root to ~230 at its tip (corr with the card's v 0.26-0.61), G ~70-120 varying per card and along
  it, B = A = 255. Supported hypothesis: Hair1Layer reads these (root darkening / per-strand variation); without them
  the shader's input is constant, a candidate for the KS wigs' light / dark bands and the dark outline. Next
  (owner's call): vertex colours on the KS wigs (R from the strand's root-to-tip, G per card), then morph.dat
  (format known) for head shapes.
- 2026-11-05 owner: "do all of them" (the IDG findings). (1) Vertex colours on every hair mesh we write (KS wigs,
  Skyrim hairs, strand cards): skyrimhair.strand_colors / strand_vertex_colors, R 70 at a strand's root rising to
  232 at its tip (STRAND_R, from IDG's per-card profile), G a random 70-130 per card + 15 along it, B = A = 255;
  the strand's run from the texture (V, or U where Skyrim paints across); --no-vertex-colors for the old meshes.
  (2) [strandsidg], IDG's card layout: the whole strip from its top (roots) stretched over each card (full_strip),
  no root taper, 35 mm cards ~6 mm apart at four fixed depths, roots on the smooth hairline curve, one sheet at the
  hairline (layer L's front cards start L x 8 mm further back), dark-root colours. Supported, not seen in game.
- 2026-11-05 owner: vanilla Skyrim hairs built the KS wigs' way (--tessellate 1 --no-geometric-normals
  --no-vanilla-maps --no-skyrim-cutout --blend-coverage 1 --hairline-drop 0, MaxDepthOffset 0.01) "do seem better".
  Those are now skyrim_hairs' defaults (VANILLA_DEFAULTS keeps only lift / volume / drape off, push_blend, layer gap;
  VANILLA_HAIR_SETTINGS empty); every old extra stays an option. Also --skyrim-overrides <mod folder> (repeatable,
  MO2-style, case-insensitive): loose meshes / textures of a Skyrim mod win over Data and the archives. For the
  owner's "Vanilla hair remake SMP" (Nexus 63979, read here: 271 NIFs over the vanilla hair paths, e.g. female
  hair01 4,014 vertices on 8 'JG Hair01' physics bones + NPC Head, 93 HDT-SMP configs, MIT; no plugin, no
  textures): built rigid for now (its physics bones follow the head); its SMP configs as Starfield cloth is later.
- 2026-11-05 owner: the KS-way Skyrim hairs with the remake "look really good, use these hairs for conversion";
  next Ralof and Ysolda "with their faces and generic greetings", hair colour matched. face_fit.py --hairs-plugin
  (npc_records.py): Skyrim names from the string tables, the converted looks-menu head parts by Skyrim EditorID
  (S2SSkyrimHairs.esm + its masters become masters; FormIDs kept as stored), template beard dropped when Skyrim has
  none, HCOL / FHCL = nearest Starfield colour name (palette RGB when known, else colour words, else unchanged), the
  template chosen with a voice type (generic Starfield greetings; Skyrim voices later, needs audio conversion).
  Starfield hair colours are names whose colours are not known here: hair_color_probe.py (read-only) collects HCOL
  names, CLFM records, archive / Creation Kit files about hair colour and decodes their textures -> hair_colors.json.
- 2026-11-05 owner: Skyrim voice lines, using UNITY's proven Starfield chain (owner's notes + unity_wem_gen.py:
  WwiseConsole 2021.1.14 with Starfield's Wwise project, Vorbis Quality High, Windows; LipGenerator on the raw wav
  with the text as a plain string; ffxc into a registered voice folder; files named by INFO FormID), saved as
  docs/npc/voice-pipeline.md. Built the Skyrim half: skyrimdialog.py (DIAL / INFO / dlstrings / speakers / .fuz)
  and skyrim_voice.py (an NPC's greeting lines -> xwm -> wav -> wem + ffxanim on the owner's PC). Synthetic tests
  only; next the Starfield voice type + greeting records, then Ralof's lines in game.
- 2026-11-05 owner's hair_color_probe run (verified from its report): Starfield.esm's NPCs use 22 hair colour names
  (Black 795, Brown 440, BlackBrown 433, DirtyBlonde 317, SaltAndBrown 189, Jet 189, Copper 171, Platinum 135, Amber
  112, SaltAndPepper 55, Auburn 51, Grey 43, White 29, then Violet, Blue, Blonde, Ruby, Fuchsia, Teal, AquaPurple,
  Yellow, TealBlonde), facial hair 13 of them; no CLFM record ties a name to a colour; the file search matched names
  inside unrelated words ('Ruby' in 'shrubyucca') and its one-entry palette was wrong. Fixed: names only as whole
  words of file names under a hair folder, a measured palette used only when it covers 3+ names; until the real
  colours are found, npc_records.NAME_RGB gives the 14 natural names a colour judged from the name (approximate) and
  the NPC gets the nearest to its Skyrim RGB (never a fantasy colour). The faces.json sent was a run without
  --npc / --hairs-plugin (no npc_conversion block).
- 2026-11-05 owner: Ralof had red hair in game (that build used the probe's bad one-entry palette: 'Ruby' for
  everyone). The rerun's report matched by RGB alone: Ralof's HairColor03BrightBlond (CLFM 81, 77, 57) -> Brown,
  Ysolda's HairColor06Auburn (48, 35, 33) -> BlackBrown: Skyrim's CLFM RGB is a dark tint multiplied into the
  texture. Now the Skyrim colour's EditorID words pick the family (blonde / brown / red incl. auburn, copper, amber /
  black / grey), 'bright' / 'dark' the lightest / darkest in it, RGB only to break ties or without words; natural
  names only. Expected now: Ralof Blonde, Ysolda Auburn. Voice run (verified: 10 of 10 lines got .wem and .ffxanim on
  the owner's PC) but every text was empty: response texts are in .ILSTRINGS, not .DLSTRINGS (descriptions);
  fixed, the lips need rebuilding with the real words.
- 2026-11-05 owner's voice run (verified, lines.json): 34,427 response strings read, every line has its text, all
  10 lines got .wem and a lip file built from the words. Seen: Skyrim's generic hellos include lines for a player
  of a race ('What do you want, little elf?') or relationship ('Every time I look at you my blood boils'). Now lines
  whose conditions concern the player (run on the target, or naming Player / PlayerRef) are left out
  (skyrimdialog.about_player; --keep-player-lines), the rest list their other conditions. Next, the Starfield records:
  dialogue_probe.py (read-only) dumps vanilla greeting topics with their responses, a few voice types and how the
  generic voice files are named, to copy the real structure.
- 2026-11-05 owner in game: Ralof's hair "definitely blonde", Ysolda's "a bit dark but still reddish" (verified:
  colour by Skyrim's colour names works); faces: "not sure their features are being matched to anything or if
  they're just generic faces" (the fit closes ~22 % of the face difference, rms 4.4 -> 3.4 mm, 3.9 -> 3.1 mm).
  face_fit --preview: faces_preview\<NPC>.png (Starfield base head, the Skyrim face moved onto it = the fit's target,
  our fit; front, side and a heat map of the change), to judge how much of the face carries over without the game.
  Voice lines (owner's run): 'What do you want, little elf / cat / lizard / Imperial?' kept a Skyrim function 130
  this code had named GetIsSex: it is GetPCIsRace (129-131 GetPCIsClass / Race / Sex), now about the player and left
  out; world-interaction topics (WI..., 'No! Don't hurt me again!') left out of greetings. dialogue_probe found no
  topic at the top level: Starfield keeps topics in their quests' child groups; it now walks every depth.
  Verified there: voice types VTYP (EDID, DNAM u8, ANAM for the two named voices = 000C866C, PNAM u8) and the generic
  voice files named <8-hex FormID>.wem (sound/voice/starfield.esm/genericmaleeventoned/).
- 2026-11-05 owner's face previews (Ralof, Ysolda; verified from the pictures): the Skyrim face moved onto
  Starfield's head (the fit's target) is lumpy at Skyrim's ~900-vertex spacing (noise from transfer's nearest-vertex
  average), and our fit reproduces the broad changes (jaw, chin, cheeks) weaker; 8 of Ralof's dials sit at the
  +-1 limit. Changes: facefit.smooth_field (the displacement smoothed over Starfield's mesh, --smooth 10 default),
  fit(limit=...) with --dial-limit (default 1, the looks menu's range; >1 is a test of what the game takes) and the
  report's sliders_at_limit; facepreview.orientation (Starfield's head mesh is not Z-up: the faces lay sideways).
  Starfield dialogue (verified, dialogue_probe): topics live in their quest's child group (type 10), responses in the
  topic's type-7 group; greeting DIAL: PNAM f32 50 (priority), QNAM quest, DATA 00 07 7D 00, SNAM 'HELO', TIFL the
  INFO FormIDs + TIFC count; INFO: ENAM flags, optional GNAM = its info group (an INFO with flags 0x40, an EditorID
  and the shared conditions), TRDA 12 bytes, TROT, NAM1 text id, NAM2-4, NAM9 8-byte timestamp, CTDA (32 bytes, same
  layout as Skyrim's), NAM0, INAM. 486 greeting topics, 126,347 INFOs. Probe extended: greeting quests by response
  count, the condition functions they use, generic dialogue quests in full.
- 2026-11-05 Greeting records for the converted NPCs (npc_voice.py, face_fit --voice-lines): per NPC a voice type
  (DNAM 2 woman / 0 man, as the named vanilla voices), one quest copied from vanilla DialogueGeneric (owner's probe:
  EDID, FULL, DNAM 11 01 00 00 05 ..., two conditions - dropped -, NEXT, ANAM), its greeting topic in the quest's
  type-10 group, one INFO per converted line in the topic's type-7 group with CTDA GetIsID (72, seen in vanilla
  greetings) the NPC, NAM1 the text; files at Sound\Voice\S2SFaceTest.esm\<voice type>\<INFO FormID 8 hex>.wem /
  .ffxanim; the NPC's VTCK set to its voice type. sfplugin.build gained child groups (children={FormID: (group type,
  records)}). Unverified: whether the game plays them (the quest must run; TRDA / NAM9 are filled neutral), whether
  the lip file compiled against S2SVoiceBuild.esm's registered folder plays from ours. Also: the previews were upside
  down (the flared neck read as the wider cranium); the open neck rim now marks the bottom.
- 2026-11-05 Owner: Ralof only ever shows "Hmph." as a subtitle, silent. "Hmph." is his first converted greeting
  (lines.json), so our quest / topic / GetIsID response are picked (supported). The INFOs had ENAM 0, so the game
  always took the first one: they now carry Random (ENAM u16 0x0002), the last of each NPC's lines Random End (0x0020)
  (xEdit's Fallout 4 ENAM layout, assumed for Starfield: supported, not verified). The silent audio is unresolved:
  first check that the build's Sound\Voice\S2SFaceTest.esm\<voice type> folder reached the MO2 mod.
- 2026-11-05 More Sliders (Nexus Starfield 18445, v2.1; owner: more face-shape sliders for the fit). Read on its
  files: the regions files have 307 sliders per sex (116 move its new faceBone_MS_* bones); its _facebones head NIFs
  list the vanilla bones first and the new ones after (male 53 + 168, female 50 + 177, binds included) and still point
  at the vanilla head .mesh; the new bones' weights exist only at load time, made by its SFSE plugin from
  MoreSlidersFaceBones_recipe.txt (MESH <mesh> <vertices> <moves> <checksum>, then W <vertex> <parent> <child>
  <alpha16>: alpha16 / 65535 of the parent bone's weight moves to the child, in order). face_fit --facebones-recipe
  applies the same moves to the vanilla mesh (facefit.load_recipe / apply_recipe), so with the mod's --regions and
  --head-nif the new sliders move the fit's head as in game. In game the NPCs need the mod (SFSE) installed;
  whether it reshapes NPCs as well as the player (its ini: PlayerBoneCheck=0) is unverified.
- 2026-11-05 Owner: Ralof's voice files are in the mod (Sound\Voice\S2SFaceTest.esm\S2S_MaleNord_Ralof\00000805-807
  .wem + .ffxanim, the INFO FormIDs without the load-order byte), yet the line is silent. Our INFOs' TRDA carried
  response number 0; now 1 (Bethesda numbers responses from 1). Hypothesis, to be checked in game; next suspects: the
  Wwise conversion settings, a missing TROT.
- 2026-11-05 Owner's run with More Sliders (faces.json): recipe applied (male 29,806 moves, female 29,593, every new
  bone weighted), 307 sliders, Ralof rms 4.3 -> 2.8 mm (vanilla set: -> ~3.2), but 278 dials used and 73 at +-1, and
  in game his face is "entirely and completely deformed". Cause (supported): near-duplicate sliders bought small
  residuals by cancelling each other at full strength (ridge 1e-6), and left / right sliders chased the transfer's
  asymmetric noise. Now: --ridge 0.05 (each dial's size costs 5 % of an average dial's effect, relative to the mean
  of diag(A^T A)) and the target averaged with its mirror image (--no-symmetry to skip); faces.json reports ridge,
  max_error_m, max_change_m. Also the greetings: Ralof now cycles his lines (Random flag: verified), still silent with
  the files in place. scripts/npc/voice_swap_test.py writes a vanilla generic .wem under our file names in a separate
  mod: heard -> our .wem conversion is wrong; silent -> the records / names are.
- 2026-11-05 Voice swap test (owner): a vanilla genericmaleeventoned .wem under our response file names stays silent
  too (subtitles shown), so the game does not look up / play Sound\Voice\<plugin>\<voice type>\<INFO FormID>.wem for
  our responses: the records or the naming are wrong, not our .wem conversion (verified). The vanilla file names seen
  (00000330, 0000115e) are below Starfield's first FormID (0x800), so the "file = INFO FormID" assumption from UNITY is
  in doubt. dialogue_probe.py now reports how genericmaleeventoned's file names relate to Starfield.esm's INFOs (as
  FormIDs, or as a u32 inside some subrecord) and dumps matching responses in full.
- 2026-11-05 Voice file naming solved on the owner's probe (verified): Starfield names a response's audio after the u32
  at TRDA bytes 4-7 (3,973 of 4,248 genericmaleeventoned .wem names; 33 match INFO FormIDs, the rest coincidences).
  TRDA = u32 emotion keyword (FFFFFFFF or a KYWD), u32 audio file ID (24-bit values in vanilla), f32. npc_voice now
  writes the file's ID there (still the response FormID without its load-order byte, so file names are unchanged);
  the TRDA "response number" hypothesis was wrong. Vanilla ENAM values seen: 0x0A, 0x02, 0x400, 0x402, 0x308 (info
  groups); the Random reading of 0x02 still stands (lines vary in game).
- 2026-11-06 Owner, in game: Ralof's and Ysolda's Skyrim greetings play with audio and their mouths move (verified):
  TRDA audio ID + loose .wem / .ffxanim under Sound\Voice\<plugin>\<voice type>\ works; the lips compiled under the
  Skyrim line names and renamed still play.
- 2026-11-06 Owner: next for the test NPCs, eye colour, skin tone and eyebrows; compare two men and two women
  (Ralof + Nazeem, Ysolda + Saadia: Nord and Redguard, so skin tone shows). Starfield's NPC fields for these are not
  known yet (hair colour is a name, HCOL / FHCL): scripts/npc/npc_face_probe.py dumps Starfield's human NPCs' field
  stats, head parts by type and HumanRace, and the Skyrim NPCs' eyes / brows head parts, texture lighting and tint
  layers (with the race's mask kind: skin tone ...), before writing any mapping.
- 2026-11-06 Eyes / skin / brows, from the owner's npc_face_probe (verified field meanings by value): Starfield NPC_
  ECOL = eye colour name (Brown, Hazel, Iron, Grey, Green, Blue, Red, BrownDark, Copper, RedDevil, Sulfur; 2,598 of
  2,983 faced humans), BCOL = brow colour name (hair colour names), STON = skin tone u8 0-8, eyebrows = head part
  type 6 (Human_Male_Eyebrow_Stern ...), eyes = head parts types 12 / 2 (left / right; colour is ECOL, not a part).
  Vanilla order ... DPLT, STON, HCOL, BCOL, ECOL. face_fit now sets ECOL from the Skyrim eyes head part's name
  (npc_records.EYE_WORDS; NPCs without their own use the race's default HEAD part: Nazeem), STON from the skin tone
  tint's luminance (ASSUMED 0 lightest .. 8 darkest; Ralof / Ysolda -> 1, Saadia -> 6, Nazeem -> 8: the in-game
  check decides the direction), BCOL = the matched hair colour. Brow SHAPE is not mapped yet (Skyrim brows are
  numbered, not named: needs a look at their textures). Test NPCs: Ralof + Nazeem, Ysolda + Saadia.
- 2026-11-06 Owner's screenshot of Nazeem / Saadia: STON works on the body (Nazeem dark, Saadia medium: 8 = darkest,
  verified) but Nazeem's face stays light. The template's face skin is a texture layer: TNAM "Dermaesthetic" with
  QNAM "Asian_Female_yo1_Sk3" (ethnicity_sex_age_Sk<shade>, VNAM textures/actors/human/face), so the face keeps the
  template's skin. npc_face_probe now lists every Dermaesthetic texture with the STON it is used with, to choose
  one per NPC. Also: Skyrim NPCs without a hair head part (Nazeem) now get their race's default hair (HEAD).
- 2026-11-06 Face skin (owner's second npc_face_probe): 2,901 Dermaesthetic layers use 80 textures named
  <African|Asian|European>_<Male|Female>_<yo1|md1|md2|ol1>_Sk<1|3|6|8> (capitalisation varies; 3 male_as_md2_sk*_Derm_color
  odd ones). Vanilla pairs Sk with STON loosely (African faces with STON 0-8, European_Female_md1_Sk8 with STON 0), so
  "Sk = the tone it was painted for" is a reading of the names (supported, not verified). face_fit sets the test
  NPC's Dermaesthetic texture: ethnicity from the Skyrim race (Redguard -> African; Nord / Imperial / Breton / Elder
  -> European), its sex, md1 when present, Sk nearest the STON chosen for the body. faces.json face_colors.face_skin.
- 2026-11-06 Owner: Nazeem / Saadia still white-faced with STON 8 / 6 and African Dermaesthetic set (faces.json
  confirms both were written), and they spawned in spacesuits. So the face colour comes from another field of the
  template (unknown; not STON, not Dermaesthetic). Now each test NPC copies the plain, voiced vanilla NPC of its sex
  whose STON and Dermaesthetic ethnicity are nearest (pick_template skin=), so the unknown field comes with it; once
  that works, diff the template against a light one to find the field. Test NPCs drop DOFT / CNTO / COCT (outfit,
  inventory) as well. Skyrim NPCs without HCLF get their race's usual hair colour (Redguard Black).
- 2026-11-06 Owner: with skin-matched templates Saadia's face still white, both still in spacesuits, and Nazeem
  "a random black guy with Starfield default hair and beard, not our Nazeem". Supported cause: Starfield template
  actors: TPTA lists template NPCs and ACBS bytes 14-15 hold the template flags (seen 0x6C13, 0x4C1A, 0x7E7F ...),
  so the copy took traits (face, hair) and inventory (the spacesuits) from the template's templates. Test NPCs now
  drop TPLT / TPTA and clear those flags (face_fit.without_templates). Also added: --keep-blend-morphs (test whether
  BMPN / BMPV, e.g. female_af_md1_Mouth, carry the face skin colour) and scripts/npc/npc_dump.py (our NPC vs its
  vanilla template, field by field).
- 2026-11-06 Owner's npc_dump: Saadia's record equals her dark template ChargenPresetFemale01 in every colour field
  (STON 06, Dermaesthetic African_Female_md1_Sk6 + VNAM female_af_md1_sk6_derm_color.dds, no TPTA) yet her face is
  white in game, also without More Sliders (owner). Remaining difference: we drop BMPN / BMPV (blend morph presets,
  female_af_md1_Mouth ...) and FMRI / FMRG. The layer textures sit under postblenddetails, i.e. over a base made from
  the blend presets: hypothesis, the base face skin comes from BMPN / BMPV. Test: --keep-blend-morphs (now keeps
  FMRI / FMRG too). Also found: a texture layer's VNAM is the .dds path; the Dermaesthetic VNAM is now set from the
  path vanilla uses with that name (npc_records.dermaesthetic_paths). Spacesuits gone? not yet reported.
- 2026-11-06 Owner: still spacesuits with DOFT / SOFT / CNTO / TPTA all gone (Saadia's template has no outfit at all),
  while Ralof earlier (template outfit kept) wore plain underwear: an NPC with no outfit seems to get a default one
  with a spacesuit. Test plugin now has its own empty outfit (OTFT S2S_NoOutfit, empty INAM) set as DOFT and SOFT of
  every test NPC. Faces with --keep-blend-morphs: still lighter than the body (owner screenshots), maybe less;
  next control: the vanilla template spawned beside the copy, to tell our bug from how Starfield renders faces.
- 2026-11-06 Owner: no more spacesuits with the empty outfit (verified). faces.json test_npc now also gives the
  template's FormID and placeatme command (the console's help finds no NPC EditorIDs in Starfield).
- 2026-11-06 Owner's control: the vanilla template ChargenPresetFemale01 spawned beside our Saadia has a dark face
  matching her body; ours stays light, with --keep-blend-morphs too (verified our bug). Left as differences: our
  ~283 face dials (with More Sliders ids 401-665) vs the template's 29, hair head part, colours, voice, name.
  Hypothesis: our dial set makes the game skip baking the face texture. --control-npcs writes each NPC a second time
  with the template's own face data (S2SFaceControl_<edid>, "<name> (template face)") to tell.
- 2026-11-06 Owner's control: "Saadia (template face)" (the template's whole face record, our hair / colours /
  outfit / name) is as light-faced as our fitted Saadia, while the vanilla template itself is dark. So neither our
  dials nor the colour fields cause it; the difference is outside the record. Hypothesis: vanilla NPCs have
  pre-built face data in the archives by FormID (as Skyrim's FaceGen) and new NPCs get a runtime face without the skin
  tone. scripts/npc/facegen_probe.py lists archive entries named by given FormIDs and face-like folders.
- 2026-11-06 Verified (owner's facegen_probe): Starfield pre-builds each vanilla NPC's face: meshes/actors/character/
  facegendata/facegeom/starfield.esm/<FormID 8 hex>.nif (Starfield - FaceMeshes.ba2) and textures/actors/character/
  facecustomization/starfield.esm/<FormID>_color / _normal / _rough / _ao.dds (Textures01, patch overrides);
  8,659 such textures, 1,552 face meshes. New NPCs have none: the game builds the shape at runtime (our dials show)
  but its face colour is a default light one; this is the light-face bug. One template (0000913A) has none.
  face_fit --baked-face-textures: templates restricted to NPCs with baked textures, and the template's four textures
  copied to textures/actors/character/facecustomization/S2SFaceTest.esm/<our FormID, no load-order byte>_*.dds.
  The facegeom mesh is NOT copied (it would freeze the template's face shape); whether the game uses the textures
  without a mesh is the in-game test. Real fix later: bake our own (shape mesh + colour) per NPC.
- 2026-11-06 Verified in game (owner screenshot): with the template's baked face textures copied under our FormID
  (no baked face mesh), Saadia's face matches her dark body and our fitted shape still shows. --baked-face-textures
  is now the default (--no-baked-face-textures to skip); when no template with baked textures fits, any template is
  used without them. Borrowed textures carry the template's own face detail (wrinkles, makeup); baking our own per
  NPC is the later step.
- 2026-11-06 Owner: Ralof looks weathered since the baked textures: they are his template's (BE_CF02_DmitriMoldavski),
  wear included. Template choice now also weighs 0.5 per rough texture layer (Accents, ColorlessAccents, Scars,
  EnvironmentMask) and +2 for an old (ol) face skin, after skin tone / ethnicity. Own per-NPC face textures later.
  Next (owner): clothing, starting with the Outfit Studio probe.
- 2026-11-06 Owner's first os_probe run (verified): Outfit Studio's MCP server answers (outfit-studio 1.0.0, 153
  tools: import_from_game, fit_to_body, copy_bone_weights, conform_sliders, export_slider_data dat = Starfield
  morph.dat, validate_project, render_view, get_guide ...). But its target game was Skyrim SE: browse_archives listed
  _ResourcePack.bsa and Creation Club .bsa files, no reference templates, no slider sets; so no naked_f.nif. The
  owner sets Outfit Studio to Starfield and re-runs. os_probe now reports the target game from the archive names and
  fetches get_guide's topic list and every guide (up to 25) into calls/.
- 2026-11-06 Armor route from Outfit Studio's own guides (owner's os_probe2, get_guide: "Converting between games",
  "Converting models from other programs", "Bone weights", "Conforming sliders"): no Skyrim -> Starfield conversion
  reference exists, so treat Skyrim gear like an outside model: import_from_game (Skyrim NIF + Skyrim body as a
  guide; weights don't carry over) -> load_reference Starfield body -> scale_to_body -> fit_pose_to_shapes ->
  unpose_shapes -> fit_to_body (non-rigid, keeps folds / buckles; rigidParts for metal) -> copy_bone_weights (8 per
  vertex in Starfield) -> conform_sliders -> validate_project -> export_file + export_slider_data dat (morph.dat).
  OS does not map Starfield materials: ours do. Waiting for a probe with OS set to Starfield (reference templates,
  body path).
- 2026-11-06 Owner's os_probe3 with Outfit Studio on Starfield (verified): Starfield archives browsed, naked_f.nif
  loaded (6,616 vertices), all 24 calls ok, but the reference skeleton was Skyrim's (NPC Head [Head] at z 120) and
  the body rendered lying on its side; BodySlide's Config.xml names res\skeleton_female_sf.nif
  (DefaultSkeletonReference), which is not in res. scripts/armor/os_skeleton.py copies the game's own skeleton
  (characterassets/female/skeleton.nif, as HumanRace ANAM) there. No Starfield reference templates or slider sets
  exist and OS cannot import morph.dat: body sliders will be written by us as per-slider OBJs for import_slider_data.
- 2026-11-06 os_probe4 (verified): with Outfit Studio restarted it uses the Starfield skeleton (C_Head at z 1.63 m,
  C_Hips 1.06 m) and the naked body renders upright (res\skeleton_female_sf.nif was already there; the earlier
  probes ran before the restart). First driver scripts/armor/os_convert.py: Skyrim NPC outfit -> worn meshes (race
  addon, _1 weight variant) -> Outfit Studio sequence from its guides; stops at the first failing step and saves every
  result. Body sliders (morph.dat), materials and plugin records come after the first fitted render.
- 2026-11-06 First os_convert run on Ralof (owner): all 22 steps ran and a NIF exported, but unusable. Starfield's
  naked_m reported bounds z -114 .. -8 while drawn standing; the Skyrim gear came in at z 0 .. 117 and scale_to_body
  moved its feet to the body's reported -112.7, i.e. under the drawn body; copy_bone_weights then found no body in
  reach (every gear vertex unweighted, validate errors). Supported cause: the body's NIF node transform is applied
  for display only. Now: shape_transforms op apply on the body right after loading it, and the run stops unless the
  body stands at z ~0 and the scaled Skyrim figure overlaps it in height. Also seen: Skyrim's body NIF brings two
  shapes (MaleUnderwear_1, MaleUnderwearBody:0), the cuirass a skin shape (MaleBodyStormcloak), the cuffs a
  HandMale_Big1stperson shape; the skin shapes' role in Starfield apparel is open.
- 2026-11-06 Second os_convert run: shape_transforms apply moved the body only 1.6 units (z -112.7 .. -5.9): the node
  transform was not the cause; correction of the entry above. Revised reading (supported): Starfield's skinned body
  lives at z -113 .. -6 in its mesh space and is drawn standing through its skin transform; the first run's fit
  (fit_to_body found the body beside the gear, mean moves 2-5) was right in that space, and only the weight copy /
  display missed because the gear had no skin transform. Now: no transform bake; copy_bone_weights with
  copySkinTransform true, transformGeometry false; the run still stops if the scaled figure does not overlap the body.
- 2026-11-06 Third os_convert run (verified in its render and validate): with copySkinTransform the gear sits on
  Starfield's body and takes its weights (2,036 vertices cleaned to 8 bones; 66 cloak-hem and 51 boot-tip vertices
  left unweighted, beyond the default 10-unit search). But export_file wrote a Gamebryo 20.2.0.7 NIF with NiTriShape /
  BSShaderPPLightingProperty / BSDismemberSkinInstance: the imported Skyrim shape types, not Starfield's BSGeometry +
  .mesh. Now: shapes still unweighted get a second copy at proximityRadius 25, and the set is saved (save_project,
  copyReference false) and built with BodySlide (build_outfits into out\build), which should write the target game's
  format; to check on the next run's file list. Textures are white: Skyrim textures are not in Starfield's Data
  (materials are ours to make).
- 2026-11-06 Fourth os_convert run (verified): the second weight copy at radius 25 left 0 unweighted (validate ok);
  BodySlide's build (build_outfits) wrote the same old-format NIF as export_file. Read with skyrimskin: BS version
  173 header, NiTriShape blocks, skin instance and skin data with 0 bones (weights dropped), only the skin transform
  translation (0, 0.0018, -1.632) m: Outfit Studio cannot write Starfield files for shapes imported from Skyrim.
  So scripts/armor/os_export.py pulls the fitted gear over MCP (get_shape_geometry, list_bones, get_weights),
  calibrates Outfit Studio's units by an affine fit of the body to the game's naked .mesh (same vertex order; run
  stops over 2 mm rms), writes BSGeometry + .mesh with the hair writer (4 weights per vertex) and an
  S2SArmorTest.esm (ARMO / ARMA copied from Clothes_Nightwear_01, worn model -> our NIF, one addon; OTFT). Material:
  the nightwear's, for a shape test only. Tool answer formats (geometry / weights) are parsed tolerantly: first run
  checks them.
- 2026-11-06 Outfit Studio's get_shape_geometry answers in "<x>List" rows with a "<x>Format" text (verified:
  "triangleFormat": "[triangle index, vertex 1, vertex 2, vertex 3]", "triangleList": [[0, 0, 1, 2], ...]); the first
  parser read 0 positions. os_export now reads any <x>List / <x>Format pair by its column names (first column the
  index) and names the answer's keys when the count is wrong.
- 2026-11-06 os_export on the owner's PC (verified offline): Outfit Studio's view of Starfield's body maps onto the
  game's naked_m .mesh with 0.00 mm rms at scale 0.01429 (1 / 69.98: Havok units, metres in the .mesh); all 5 gear
  shapes (MaleBodyStormcloak 398 v / 27 bones, StormCloak 699 / 33, Boots 202 / 8, HandMale_Big1stperson 1670 / 18,
  PrisonerCuffs 3630 / 17) fully weighted; S2SArmorTest.esm ARMO 01000801, OTFT 01000802, material borrowed from
  Outfit_Nightwear_LowerBody_01.mat. In-game check pending.

## 2026-11-06 — Converted armor uses the naked body's skin binds (Claude)
- verified (owner screenshots): os_export's first armor, with binds = inverse of the skeleton NIF's rest world (the hair
  convention), rendered in game as tall vertical pillars with the hands and cuffs above the head.
- supported: the gear positions are calibrated into the naked body mesh's own space (0.00 mm rms) and its weights are
  copied from that body, so the body's binds for the same bones are the ones that match. os_export now writes each
  bone's bind straight from the body NIF's BSSkin::BoneData (sphere radius +0.15 m) and stops if the gear uses a bone
  the body is not skinned to. unresolved: in-game result of this change.
- verified (owner screenshots, same day): with the body's binds the Stormcloak gear sits on the body and follows it;
  one thin spike rises from the back of the neck far above the head. unresolved: cause. armor_check.py reports body
  bones whose bind disagrees with the skeleton or that move no body vertex, and gear vertices on them or far outside
  the body.
- verified (owner screenshots + armor_check, same day): the spike follows the FIRST shape in the NIF (all shapes: neck;
  without the skin piece: neck; without skin piece and coat, boots first: a thick pillar from the left boot past the
  head), while armor_check finds every vertex inside the body, every triangle index valid and binds matching the
  skeleton. unresolved: a first-shape special case (writer) vs. data in that shape; os_export --reverse tests it, and
  the export now lists the ARMA fields copied from the vanilla nightwear (a morph or bone-scale reference there would
  be applied to our mesh).
- verified (owner, same day): with --reverse the spike moved to the cuffs (now first) and the boots were clean, so it
  belongs to the first shape, not to any shape's data. Copied ARMA fields: EDID BO64 RNAM DNAM MOD2 FLLD MOD3 FLLDx5
  NAM4 NAM6 MODL MNAM TNAM SNAM VNAM BSMPx2. supported (not yet tested): FLLD lists the nightwear's own files (body
  morph data applied to shape 0 by vertex number); os_export now prints those fields and --drop-fields leaves them out.
  Also seen: the Skyrim gloves (shape "HandMale_Big1stperson") hang at the hips, following hip bones, because the
  Starfield body skin has no hand bones to copy from.
- verified (owner, same day): --drop-fields FLLD did not remove the spike. In motion it is a rigid bar swinging with
  the body (up when standing, forward when running): a vertex placed far from its bone, not a bad rest position.
  supported: it comes off the first shape's first bone (boots first: L_Calf, left boot; coat/skin first: C_Chest,
  upper back). nif_dump.py compares our NIF's blocks with the vanilla nightwear NIF to find what differs.
- verified (nif_dump, same day): vanilla Outfit_Nightwear_LowerBody_01_M.nif's BSGeometry carries a translation of
  (0.000, -0.002, +1.632) m (rotation ~identity): vertices stay in the body mesh's space and the shape is lifted to the
  actor's. Ours wrote 0. Other differences (block order, NiNode flag 0x20000000, unsorted bones) look cosmetic.
  os_export now copies the naked body NIF's own shape transform onto every shape (--no-shape-offset: old behaviour).
  unresolved: whether this removes the bar in game.
- verified (owner, same day): the body's shape offset (+1.632 m) on every shape changed nothing visible, the bar
  included: the game ignores a skinned BSGeometry's transform. The vanilla nightwear has ONE shape, so nif_dump
  --find-multi now dumps vanilla clothes NIFs with several skinned shapes for the multi-shape layout.
- verified (nif_dump --find-multi, same day): vanilla multi-shape worn NIFs (outfit_miner_utilitysuit_helmet_f/_m)
  use our layout per shape (BSGeometry, extras, SkinAttach, BSSkin::Instance root 0 / bone refs -1 / tail 0,
  BoneData 68 B per bone, shader); their shape translations differ between shapes (1.632 m on some, 0 on others).
  Vanilla extras we lack: LOD1/LOD2 meshes, and a NiIntegersExtraData [1, 201] per shape. Neither explains a bar on
  the first shape only. os_export --anchor puts a 1 mm one-bone triangle first (test and workaround).
- verified (owner screenshots, same day): with the 1 mm one-bone anchor shape first, the bar is gone and every real
  shape renders in place. The game mishandles the first shape of our worn NIFs (cause unresolved); the anchor is now
  the default (--no-anchor to leave it out).

## 2026-11-06 — Gear fitted by skeleton and body shape instead of Outfit Studio (Claude)
- verified (owner screenshots): Outfit Studio's fit_to_body + copy_bone_weights left the Stormcloak collar ~20 cm
  above the Starfield neck (over the face), the gloves on hip / thigh weights (the Starfield body has no hand bones),
  and the coat folded. Owner: fit the Starfield body "the way it does on Skyrim's".
- decision: fo4sf.gearfit + scripts/armor/gear_fit.py. Per Skyrim bone a transform (overall similarity fit of the
  matched joints, then joint onto Starfield's joint, direction onto Starfield's, stretched by the length ratio clamped
  0.75-1.33); gear vertices blend their OWN Skyrim weights; the Skyrim body moved the same way gives the offset onto
  the Starfield surface, smoothed and carried onto nearby gear; gear inside the Starfield body pushed out to 4 mm.
  Weights: Skyrim bones renamed by skeletonmap (hands -> *_Wrist, fingers mapped). Binds: inverse(skeleton rest
  world) @ the body mesh frame (world @ bind of the game's body, identical for every body bone, armor_check).
- supported (synthetic tests) / unresolved (in game): the clamp, smoothing and gap values; skin pieces follow the
  body offset without push-out.
- verified (owner, same day): first gear_fit run rendered nothing and blanked the inventory preview. Report: pelvis
  turned 53 deg and squashed to the 0.75 clamp, lower spine 0.75 (Skyrim's pelvis joint sits level with the spine
  base; Starfield has 4 spine bones to Skyrim's 3). Torso bones (pelvis, spine 0-2) now only move onto Starfield's
  joints. gear_fit writes nothing when a shape has non-finite vertices or vertices > 0.5 m outside the body box.
  unresolved: whether the blank came from far vertices or something else (armor_check on the next output).
- verified (owner screenshots, same day): with torso bones unturned the gear renders and fits far better: collar below
  the chin, gloves on the hands following the fingers, boots on the feet. Left: torso tipped back (chest forward, hem
  behind) and Starfield skin through boot knees / upper arms. The overall similarity fit now uses only the axial and
  leg joints (Skyrim's A-pose arm angle tipped the torso); arms keep their per-bone turns. supported: the poke-through
  is the player's body sliders (gear fitted to the default naked_m; no morph data yet).
- verified (owner screenshots, same day): with the axial-only fit the gear sits right on the thinnest body slider
  (collar, gloves, boots, coat); on the owner's default body the body pokes through (boots, upper arms, gloves).
  Supported: the gear needs a morph.dat (body sliders Overweight / Thin / Strong) like vanilla worn meshes.
  fo4sf.sfmorph reads / writes the layout noted 2026-11-02; scripts/armor/morph_probe.py finds where the game keeps
  clothing and body morphs and checks the reader against them. Also open: a forward bulge at the chest in the side
  view; Starfield hands poking through the gloves (the hands are a separate mesh, not in the push-out surface).
- verified (morph_probe, same day): vanilla clothing morphs live at meshes/morphs/<NIF path below meshes, no .nif>/
  chargen/<shape name lower case>/morph.dat (e.g. clothes/outfit_nightwear_01/outfit_nightwear_01_m/chargen/
  outfit_nightwear_lowerbody_01_m), keys Overweight / Thin / Strong, one entry per mesh vertex; fo4sf.sfmorph reads
  all 17 found with records in vertex order and vertex counts matching their meshes (nightwear lower body 2792).
  supported (not yet in game): the rule for our NIF (meshes/morphs/s2s/ralof_outfit/chargen/<shape>/morph.dat).
  gear_fit now writes one per shape: each gear vertex takes the inverse-distance blend of the 6 nearest body
  vertices' deltas from the naked body's own chargen morph.dat (found by vertex count under meshes/morphs/human).
- verified (owner screenshots, same day): with morph.dat files the coat follows heavier body sliders (supported: the
  path rule works). Left: orange skin bleeding through the grey Skyrim skin piece (MaleBodyStormcloak, drawn with
  the borrowed material over Starfield's body), and a chest shelf (body offset up to 68 mm). gear_fit now drops
  Skyrim bare-skin pieces by default (--keep-skin keeps them); body offsets count only where the moved Skyrim body and
  the Starfield body face the same way (cos > 0.7) and are capped at 4 cm.
- verified (owner, same day): the chest bulge is not in the original; feet are fully covered and the shins do not
  show through in Skyrim; Starfield fingers poke through the gloves. Changes: the torso bones (pelvis, spine 0-2)
  now share the overall fit's transform (moving each onto its own Starfield joint stepped the chest forward of the
  belly); the push-out measures against the body's triangles (closest point on the triangles around the 6 nearest
  vertices) instead of the nearest vertex, which missed points between the shins' and feet's sparse vertices; the
  game's hands mesh (found under meshes/actors/human by name and hand bones) joins the push-out surface.
  unresolved: in-game result.
- verified (owner screenshots, same day): gloves clean with the hands mesh (hands_3rd_m.nif) in the push-out; chest
  flat. Still: orange slots in the boot shins (owner: in Skyrim the legs do not show) and toes / heels out of the boots
  when running. MaleBodyStormcloak is not spare skin: Skyrim paints the trousers on that body-textured piece, so it
  is kept again by default (--drop-skin leaves such pieces out) and pushed out at 2 mm. Feet: the moved Skyrim foot
  region's box (vertices >= 0.5 on Foot + Toe0) is fitted per axis onto Starfield's foot box (clamp 0.9-1.35),
  applied to the Foot / Toe transforms. unresolved: in game.
- verified (owner run, same day): the foot box fit never ran: Skyrim's malebody_1.nif has no feet or hands (they are
  malefeet_1 / malehands_1). gear_fit now loads those into the Skyrim body and says when foot sizing is skipped.
  The kept MaleBodyStormcloak piece makes the bare forearms grey (it carries the skin AND the painted trousers; with
  the borrowed material it is all grey). gear_fit now prints each Skyrim shape's diffuse texture, to decide how to
  split skin from cloth on such pieces.
- verified (owner run, same day): MaleBodyStormcloak uses textures\actors\character\male\MaleBody_1.dds and
  HandMale_Big1stperson MaleHands_1.dds: Ralof's bare forearms / neck and bare hands, not trousers or gloves (the
  "painted trousers" idea was wrong). gear_fit now leaves out shapes whose diffuse is under textures\actors\character\
  (--keep-skin keeps them). Foot box fit ran (scale [0.9, 0.947, 1.072]); the heel still showed when running: gear
  within 2.5 cm of the body now takes the nearest body / hands vertex's weights, blended back to its own Skyrim weights
  by 5 cm (vanilla clothing is skinned like the body under it). Shins: boots are not inside the base body (pushed 0),
  so the slots there are the heavier slider poking through (morph applied weakly or not; unresolved).
- verified (owner, same day): skin shapes left out (arms / hands now Starfield's), cuffs on the wrists, heel follows
  the boot when running. The shin slots show at the thinnest AND heaviest slider (worse when heavier) while the boots
  sit outside the base body (pushed 0), and the earlier Outfit Studio export had the same ovals: supported cause =
  back faces culled (Skyrim draws SLSF2_Double_Sided shapes from both sides; our material is one-sided). gear_fit
  --back-faces auto (default) mirrors Skyrim's double-sided shapes (skyrimconvert.with_back_faces), all / none for
  testing; morph.dat gets the copies' deltas too.
- verified (owner, same day): --back-faces all changed nothing: the shin / toe gaps are not culled faces. Cause
  (supported): the Skyrim boots have 202 vertices; every vertex is outside the leg (pushed 0) but the flat faces between
  them cut through the calf and toes. gearfit.cover now checks the other way: body points coming through a gear face
  (closest point inside the face, within 4 cm, less than the gap inside) push the 3 nearest gear vertices out along
  their normals by the shortfall, 4 rounds. Back faces stay opt-in (--back-faces auto = Skyrim's double-sided only).
- verified (owner, same day): cover closed the shin / toe gaps but made the gear thick and the cuffs spiky (StormCloak
  400, PrisonerCuffs 1730 vertices moved). Owner: the leg's own shape differs between the games. Changes: the
  Skyrim->Starfield body offset is carried by facing body points only (cos^2 of the normals, k 24, within 10 cm;
  smoothing 2 x within 3 cm) so the shin and calf keep their own differences; cover only pushes faces that look away
  from the body (inner layers left), spreads each push over the vertex's neighbours (no spikes) and caps the total at
  2.5 cm. unresolved: in game.
- verified (owner screenshots, same day): with facing-only shape transfer and the smooth capped cover the Stormcloak
  outfit covers the legs and feet without bulk (cuffs 315 vertices moved instead of 1730). Fit accepted for now.
- decision (owner: "add the textures now"): gear_fit converts each kept shape's Skyrim texture set with the repo's
  SkyrimConverter (_shape_material: colour / normal / rough DDS + .mat, alpha test kept; prefix s2s) and packs
  materials / textures as "S2SArmorTest - Main.ba2" / "- Textures.ba2" (hair_pack.pack; loose without Archive2).
  Shapes that fall back keep the nightwear material. texconv default: the owner's xEdit Texconvx64.exe path.
- verified (owner screenshots + Skyrim reference, same day): with the converted Skyrim textures (SkyrimConverter
  materials in "S2SArmorTest - Main / Textures.ba2") Ralof's Stormcloak outfit reads as the original in Starfield.
  Notes: gaps between the sleeve hems and the arm and at part of the boots; the collar thicker than in Skyrim.
  Supported cause: every fit step moved gear outward only. gearfit.keep_gap now pulls each vertex that sat within
  6 cm of Skyrim's body back to its Skyrim gap (closest distance on the triangles of both bodies; at most 4 cm), before
  push-out and cover.
- verified (owner, same day): keep_gap ran (coat 256, boots 30, cuffs 1507 vertices pulled in) but the notes stayed.
  Supported: the band under the sleeves is Starfield's built-in undershirt (part of the naked body) showing below
  Ralof's short chainmail sleeves, not a mesh gap; the boot seam at the ankle came from the foot box fit (it moved
  the foot section only), now off by default (--size-feet). gear_fit prints per shape the median gap to the body in
  Skyrim and now (all, and the top tenth: the collar) to judge the neck with numbers.
- verified (gap report, same day): median gap to the body Skyrim -> now: coat 16.8 -> 26.3 mm, collar (top tenth)
  29.1 -> 31.2 mm, boots 22.3 -> 36.8 mm, boot tops 32 -> 56 mm, cuffs 7.2 -> 6.8 mm. So the collar sits as in Skyrim
  (its look comes from Starfield's thicker neck), while the low-poly boots (202 vertices) and coat (699) are left loose by
  cover pushing flat faces over Starfield's leg / torso shape. gear_fit now tessellates shapes under 2000 vertices
  3 x 3 (skyrimhair.tessellate, PN patches, UVs and weights carried) before the fit (--tessellate 1 = off). Sleeve band:
  supported = Starfield's built-in undershirt below Ralof's short chainmail sleeves (owner to check unequipped).
- verified (owner, same day): tessellated boots / coat look good; left: a crack at the heel, the cowl bulging far out
  behind the neck, and Starfield's grey undershirt showing below Ralof's short sleeves (owner: Skyrim's bare arm runs
  up under the sleeve; needed for other armors too). Changes: the neck bone moves with the torso (NO_TURN; its own
  joint pulled the chest + neck weighted cowl apart); gearfit.weld puts Skyrim seam copies back on one point after
  the fit. The undershirt is a separate mesh (clothes/naked/naked_m.nif, Naked_M_Swimsuit): scripts/armor/slot_probe.py
  lists the slots of HumanRace's skin armor, the clothes\naked addons and full outfits, to choose our ARMA's slots so
  the game hides it (supported, unverified).
- verified (owner + gap report, same day): with tessellation the cowl's median gap matched Skyrim (collar 28.7 -> 29.8
  mm) yet it still bulged behind / in front of the neck, and part of the chest showed through. Supported causes: (1)
  both gaps were measured to the BODY meshes, which stop at the base of the neck: the cowl was fitted against the
  shoulders, never the neck; (2) the PN (curved) patches of skyrimhair.tessellate balloon a folded cowl and dip
  elsewhere. Changes: the head joins both surfaces (Starfield malehead_facebones.nif mesh in skeleton space with its
  weights; Skyrim malehead.nif head shape only), tessellation is flat (gear_fit.flat_subdivide) and skips the skin
  shapes that are dropped anyway (the bare hands had been split to 13370 vertices).
- verified (slot_probe, same day): HumanRace's skin armor Skin_Naked = AA_Naked_Body (slot 3, naked_m.nif) +
  AA_Naked_Hands (slot 6); no separate undershirt mesh (the grey shirt is the naked body's own look). Vanilla
  outfits cover slot 3 (nightwear UpperBody 3+5, miner shirt 3+5) and bring their own skin piece
  (AA_Clothes_Nightwear_01_Skin, slot 13). Ours copied only the nightwear LowerBody slot (7), so the whole naked body
  stays under Ralof's outfit: the leg / chest poke-through and the shirt under the sleeves. Plan (owner: "Skyrim's
  arm goes up higher"): cover slot 3 and add our own skin piece cut from Starfield's body where Skyrim's bare-skin
  piece lies (forearms up under the sleeves, neck, calves), with a vanilla outfit-skin material; slot_probe now lists
  each addon's shapes, vertex counts and materials to pick that material and check the skin piece's layout.
- owner (same day): the cowl still bulged far forward. Head bone now moves with the torso (its own joint is farther
  forward); only the NECK part of both heads (>= 0.3 weight on neck / chest bones) joins the fit surfaces (the face and
  jaw had pushed the cowl out).
- verified (slot_probe models, same day): the nightwear's own skin piece (AA_Clothes_Nightwear_01_Skin, slot 13) is
  a 938-vertex cut of the body using the body's material (Materials\Actors\Human\Naked_Body\Male\Naked_M_Body.mat).
  Decision: gear_fit hides the naked body like vanilla outfits (our ARMA / ARMO BO64 = slots 3, 5, 7; os_export
  slot_bits) and adds its own skin piece "S2S_Skin": the Starfield body vertices within 3 cm of where Skyrim's
  body-skin pieces (MaleBody-textured: MaleBodyStormcloak = bare forearms up under the sleeves, neck, calves) lie
  after the fit, with the body's UVs, weights and material, and the body's own slider deltas vertex for vertex.
  Hands keep slot 6. --no-skin-piece = old behaviour. Neck / head: still too high (owner) -> they keep the torso's
  transform but take their own joint's height (DROP_TO_JOINT). unresolved: all in game.
- verified (owner, same day): with the naked body hidden and S2S_Skin (1401 body vertices) the calves are clean; the
  arms showed shards and the chest orange patches. Supported cause: the body has up to 8 weights per vertex and the
  writer 4; the extra entries shifted the following vertices onto wrong bones. The skin piece now keeps the 4 largest.
  Neck: Skyrim Neck weights go to C_Neck_Twist (WEIGHT_REMAP; the Starfield body turns its neck with it, C_Neck moves
  no body vertex) so the cowl turns with the head; the neck's gear is squashed in height about the neck joint by the
  Starfield / Skyrim neck length ratio (clamp 0.7-1.0; owner: turtleneck vs Skyrim's half turtleneck).
- verified (owner, same day): arms show, but break in the middle as if two weight sets (supported: the skin piece cut
  to 4 weights bends apart from the game's hands mesh, which keeps 8); the cowl neither drops nor turns with the head;
  chest patches remain (appeared with tessellation). Changes: skyrimhair._mesh writes 8 weights per vertex when a
  shape needs more (the body's own skin keeps up to 8); gear_fit prints the neck height / ratio and the bones the top
  tenth of each shape follows; --debug-dir writes the fit as OBJ (Starfield surface, fitted shapes, Skyrim gear / body)
  plus fit_debug.zip, to render outside the game.
- verified (owner + fit_debug OBJ cross-sections, same day): (1) the skin piece kept one size and the default skin
  tone while the game's hands followed the sliders: it sat inside the clothing addon; it now has its own addon copied
  from the vanilla AA_Clothes_Nightwear_01_Skin (slot 13) and its own NIF S2S\<name>_Skin.nif + morph.dat, the ARMO
  listing both (INDX / MODL pairs rebuilt). (2) Mid-sagittal cut: Skyrim's cowl top sits level with the top of the
  neck region, ours ~5 cm above it (the turtleneck): gear around the neck (full within 7 cm of its axis, none past
  14 cm) is squashed in height above the clavicles by Starfield / Skyrim (clavicles -> head joint), clamp 0.6-1.0,
  the moved Skyrim body too. (3) Chest cuts at x 0.03-0.09: the coat lies ~2 cm outside the body, the skin piece is not
  there: the patches are subdivided faces folded over by neighbours moved apart; the fit's moves are now averaged with
  each vertex's neighbours (3 rounds) and pushed out again. The debug export lost Skyrim shapes with ':' in their name
  (Windows file names). unresolved: in game.
- verified (owner, red skin test, same day): the skin piece takes the skin tone; on heavier sliders it showed through
  on the chest (it ran under the cowl where Skyrim's bare-skin piece does). The skin piece now keeps only body points
  with no gear straight out from them (closest gear point within 6 cm along the body normal), plus 2 rings of overlap
  under the gear's edges, as vanilla outfit skin pieces cover only visible skin.
- verified (owner, same day): our armor does not change size with the body sliders at all (arms, chest), so our
  morph.dat files are not applied. The path rule was wrong: vanilla nightwear morphs sit under
  morphs\clothes\outfit_nightwear_01\outfit_nightwear_01_m\chargen\<shape>\ while its NIF is
  Outfit_Nightwear_LowerBody_01_M.nif; a Nexus article (starfield/articles/268) says morph files are "referenced in esm
  files". supported: a record field names the morph, and our copied records still name the nightwear's (which also
  fits the first-shape bar: the nightwear lower body's one-shape morph applied to our shape 0 by vertex number).
  scripts/armor/morph_ref_probe.py searches every Starfield.esm record for the morph folder name. Neck squash came
  out 1.0 (Starfield clavicle -> head joint not shorter than Skyrim's): the "5 cm higher" read compared neck regions
  cut by weights, not comparable; unresolved.
- 2026-11-06 (Claude, armor) Body-slider morphs need their own MRPH record. verified (morph_ref_probe on the owner's
  Starfield.esm): MRPH 00026685 MORPH_Clothes_Nightwear_01_LowerBody_M, fields EDID TCMP MOBC, TCMP = the folder
  holding morph.dat; our copied ARMA's NAM4 = 0x00026685 (NAM6 0x00026688, the female one). So one ARMA names one
  morph, and our outfit had the nightwear's morph and never read ours. gear_fit now writes one NIF + ARMA + MRPH per
  shape (os_export.write_armor_parts): the MRPH copied from the one the template addon names, TCMP pointed at the
  folder gearfit.morph_path writes into, NAM4 / NAM6 both at it; no anchor shape. MOBC unresolved: copied, except a
  u32 equal to the template model's first-shape vertex count is set to the part's. Gear parts get distinct slots
  ([3, 5], [7], [8], ...; supported: vanilla outfits give each addon its own slots), the skin part its template's
  (13). --one-nif keeps the old layout.
- 2026-11-06 (Claude, armor) First in-game test of one addon + MRPH per shape: coat and skin piece show, the boots
  stand up as two tall pillars and the cuffs do not show. MOBC came out ff000000 (255) in the template, not a vertex
  count. unresolved which change did it (our morph.dat now read for the first time, the boots' / cuffs' own slots
  7 and 8, or one shape per NIF with no anchor). gear_fit --test-variants writes a "[no morph]" armor (addons without
  NAM4 / NAM6) and a "[same slots]" armor (gear addons on 3, 5, 7) next to the main one, to tell them apart in one
  session.
- 2026-11-06 (Claude, armor) Variant test results (owner, in game): "[no morph]": no pillars, no slider following;
  "[same slots]": like the main armor (pillars, follows sliders); main: the coat follows the weight slider now, but
  pillars rise from the coat around the thighs, and boots, cuffs and the skin piece's arms do not show. So: slots are
  not the cause; our morph.dat is read now and something in it throws a few vertices. Changes: (1) morph.dat entries
  with no records carry the running record index, not 0 (supported: a reader taking the record count from the next
  entry's index would read far past for the vertex before an empty one; gear_fit prints the vanilla nightwear morph's
  own empty-entry convention to verify); deltas are capped at 15 cm and the per-shape maxima printed. (2) ARMO INDX 0
  on every addon (supported: numbered 0..3 only addon 0, the coat, showed; earlier the separate skin addon at INDX 1
  never showed either; Fallout 4 uses INDX as the armor's variant index; gear_fit prints the template's INDX list to
  verify). (3) Collar weights from the whole Starfield head too (fit weight_src), not only its neck-weighted part:
  the collar had no C_Head weight and did not turn with the head.
- 2026-11-07 (Claude, armor) In game after INDX 0 (owner's screenshots): boots, cuffs and the skin piece's arms now
  show (verified: INDX numbering hid every addon but the first). Pillars remain, now from several pieces, one
  skin-coloured from the skin piece, whose deltas are the body's own records copied verbatim, so the values are
  unlikely the cause (supported). gear_fit --morph-test adds three test armors: [zero morph] (our layout, all deltas
  0), [vanilla body] (vanilla naked body model + the game's body morph folder, through our copied ARMA / MRPH) and
  [body our morph] (vanilla body model + the body morph.dat parsed and rebuilt by sfmorph; the run prints whether the
  rebuild is byte for byte the game's). unresolved until tested.
- 2026-11-07 (Claude, armor) --morph-test run: our writer rebuilds the game's body morph.dat byte for byte
  (verified), the nightwear morph has no empty entries, and our pieces' deltas are all finite and under 81 mm
  (verified from the printed stats). So our morph.dat files are well formed; the pillars come from how the game
  applies them to our pieces (unresolved: waiting for which of [zero morph] / [vanilla body] / [body our morph] show
  pillars). Collar: the clavicle-to-head ratio is 1.0, so the neck squash does nothing, but the cowl's front still
  stands up to the chin (owner's screenshot). New step chin_clearance: gear with the Skyrim head within 8 cm straight
  above it keeps that gap (times the skeleton scale) under the Starfield head; lowered only, neighbours follow,
  pushed out again after.
- 2026-11-07 (Claude, armor) Pillars found (verified by the --morph-test armors in game): [zero morph] none,
  [vanilla body] and [body our morph] none (records and morph writer fine), our pieces with real deltas: pillars.
  Cause (supported, fits every sighting): .mesh positions are int16 over a scale equal to the largest coordinate in
  mesh space (z about -1.6 m at the feet / hem, the mesh frame sits at head height), so the outermost vertices'
  morphed positions overflow and wrap to the other end: pillars from the coat hem and boot soles straight up.
  skyrimhair._mesh now adds MORPH_MARGIN 0.25 m to the scale (deltas are capped at 0.15 m); precision cost ~0.01 mm.
  Also verified: AA_Naked_Body's model is the Starfield undershirt/swimsuit body, not the bare body. Collar: chin
  clearance lowered 55 coat vertices, up to 76 mm.
- 2026-11-07 (Claude, armor) In game after the scale margin (owner): no pillars, every piece follows the weight
  slider (verified). Left: the cowl stands off the back and sides of the neck instead of rounding it, and a strip of
  bare body shows between the skin piece and the sleeve hems. New step neck_wrap: above the clavicles, each gear
  vertex's horizontal gap out from the neck / head surface (a ray from the neck joint's axis) in Skyrim is kept over
  Starfield's (gaps under 2.5 cm fully, none past 4.5 cm; at least 4 mm), moved horizontally, smoothed, pushed out
  again. Skin piece: COVER_MARGIN 2 -> 5 rings kept under the gear's edges.
- 2026-11-07 (Claude, armor) Collar compared on the owner's fit_debug_2 meshes (verified): Skyrim's Stormcloak cowl
  top rim lies 19-33 mm from the neck's axis (the neck is ~50 mm in radius), 115 of its vertices inside Skyrim's
  neck, up to 48 mm deep: the top is buried in the neck and only the lower part shows (the half turtleneck). Our
  push-out lifted the whole rim out round the neck. New step bury: gear above the Skyrim clavicles deeper than 3 mm
  inside Skyrim's neck / head stays inside Starfield's at the same depth (times the skeleton scale); neck_wrap now
  only moves gear that was outside. chin_clearance taken out of the fit (it dropped the cowl's back 7.6 cm under the
  skull, owner's side view: front and back at different heights). Debug export: whole heads added
  (sf_head.obj, skyhead_full.obj) and file names made Windows-safe.
- 2026-11-07 (Claude, armor) Collar measured on the owner's new fit debug meshes (whole heads, crowns aligned,
  Skyrim times 0.9365; verified): relative to the crown, Starfield's shoulders lie 3-5 cm lower than Skyrim's at the
  same distance from the neck (a longer visible neck), and our cowl's sides sat 2.5-3.5 cm closer to the neck and
  1.5-2 cm higher than Skyrim's, so its sides climbed the neck like a turtleneck; the buried top was fine (all 118
  buried vertices inside). New step drape (before neck_wrap and bury): gear above the Skyrim clavicles with an
  upward-facing Skyrim body surface within 10 cm straight below keeps its direction and distance from the neck axis
  (times scale) and its height above that surface over Starfield's; moves over 10 cm are refused (another surface
  below). Offline on the same meshes: the cowl's half-width at 22-25 cm below the crown went from 103-127 mm back to
  119-141 mm (Skyrim 142-193). unresolved in game.
- 2026-11-07 (Claude, armor) After drape (owner): the cowl still sits up on the chest and runs visibly into the neck,
  and the texture's cloth lines wiggle where Skyrim's curve smoothly. Measured on the debug meshes: the cowl
  vertices round the neck sat 2-3.5 cm closer to the neck than Skyrim's (scaled), keep_gap pulling them to their
  Skyrim gap from whatever surface is nearest (now Starfield's neck wall). Changes: (1) keep_gap off above the Skyrim
  clavicles; (2) shoulder_drop: per direction round the neck, the height difference between Starfield's shoulder top
  and the fitted Skyrim body's (9-13 cm from the neck axis; offline on Ralof: about 0 at the front, -1 cm at the
  sides, -6 cm at the back) moves everything near the neck above the clavicles, body and gear alike, before the
  surface steps; (3) relax: the fit's total moves smoothed 8 rounds over the mesh, then pushed out with the push
  spread to neighbours (the per-vertex steps made the wiggles, supported); drape and neck_wrap off by default.
- 2026-11-07 (Claude, armor) shoulder_drop measured +30 mm at the front on Ralof (it compared heights of sloped
  surfaces at the same x, y; Starfield's throat sits further back) and raised the cowl's front to the chin: now off
  by default. Replaced by collar_height_field: per direction round the neck, the visible collar top (outside the
  body and the head) is brought down to Skyrim's distance below the crown (heads lined up at the crown, scaled);
  never raised. Offline on the owner's 4th debug meshes: front -5 cm, sides -2 to -4 cm, back 0. The buried part is
  first placed where Skyrim has it relative to the head (crown and neck axis lined up), then bury: the x=0 cut now
  runs straight across inside the neck as Skyrim's (it had run up into the head). Owner's drawn line (front low on
  the chest, back over the base of the neck) matches.
- 2026-11-07 (Claude, armor) Head weights for the collar off by default (gear_fit --head-weights turns them on): owner,
  looking at Skyrim: the cowl sits low on the outfit and does not follow the neck or head at all. Gear near the neck
  copies the body's / neck part's skin weights, like the skin under it.
- 2026-11-07 (Claude, armor) After collar_height (owner): much better; left: the cowl stands out further than Skyrim's
  (the x=0 cut showed ours 1-2 cm forward of Skyrim's at the throat: Starfield's throat sits further back) and its
  side rises when the head turns. Changes: neck_wrap back on by default (keeps Skyrim's horizontal gap from the
  neck; offline on the 4th debug meshes it brought the front onto Skyrim's line); above the Skyrim clavicles gear
  keeps its own Skyrim weights instead of the neck skin's (blended in over 3 cm), so it moves like Skyrim's.
- 2026-11-07 (Claude, armor) Hadvar (owner, verified from the run): only ArmorImperialLightBoots came out of his
  default outfit (os_convert.outfit_armor followed each leveled list's first entry only), and the boots, as the
  first piece, took the body's slots 3 + 5: the naked body vanished with nothing over it. Now a leveled list gives
  its first entry that resolves to armor (every entry when flagged Use All), unresolved outfit items are printed, and
  each piece's Starfield slots come from its Skyrim biped slot (32 body -> 3 + 5, 37 feet -> 7, 33 hands /
  34 forearms -> 8, others 9-12).
- 2026-11-07 (Claude, armor) Hadvar in game (owner, with Skyrim running shots): cuirass, bracers and boots show; the
  tassets lift with each leg when running and open round the legs, where Skyrim's hang. Skyrim's skirt chains
  (Skirt[FBLR]Bone01-03) have no Starfield bones and the nearest-body weights copied the thigh skin's onto them.
  Now skirt bones split between C_Hips and the thighs (front / back 0.5 + 0.25 + 0.25, sides 0.6 + 0.4 of their
  own thigh; supported, to tune), and skirt-weighted vertices keep those weights instead of the body's. The run
  prints how many vertices each piece has on skirt bones (if Skyrim weighted the tassets to the thighs, none).
- 2026-11-07 (Claude, armor) Hadvar after skirt shares (owner): running better; at rest the tassets stand out and up
  like a tutu where Skyrim's hang straight down, and in a wide combat stance the thighs show through them. Changes:
  skirt-weighted vertices get a gradient instead of fixed shares (C_Hips at the top, thigh share 0.2 -> 0.8 down to
  knee height, split between the thighs by left / right position, supported, to tune), and they are left out of
  cover (push-out still keeps them off the body). Shape not yet measured: needs the debug meshes.
- 2026-11-07 (Claude, armor) Hadvar skirt measured on the owner's debug meshes (verified): Skyrim's tassets are
  modelled flared (bind pose an A, 27 cm from the centre at the hem against 20 cm hips, hem ~0.60 m); in game
  Skyrim's animations turn the skirt bones so it hangs. Starfield has no skirt bones, so ours kept a shortened flare
  (hem 0.65-0.69 m, the back 6 cm out behind the seat): the tutu. New step hang_skirt: skirt-weighted vertices below
  the top band go to the convex outline of the body's section (both legs and hips) + 2 cm + their layer (up to 3 cm
  over the innermost skirt vertex of their band and direction), hanging from the skirt's top ring at their Skyrim
  distance from it (scaled): in and down. Offline on the same meshes: skirt hangs straight, hem back at ~0.60 m.
- 2026-11-07 (Claude, armor) Hadvar after hang_skirt (owner): skirt shape better but hugs the legs (they come through
  in a wide stance) and the thigh skin under it shows holes. HANG_GAP 2 -> 4 cm. Skin piece now the WHOLE Starfield
  body minus what the body armour itself covers (gear within 3.5 cm straight out, so skin under a hanging skirt
  stays; boots / gauntlets do not remove skin, so the body armour alone keeps its feet and hands-side skin), as
  discussed with the owner: the body armour hides the naked body, so it must bring every bit it does not cover.
- 2026-11-07 (Claude, armor) Owner's side views (Skyrim vs ours): Skyrim's in-game skirt leaves room in front of the
  thigh and tilts out a little; ours lay on it. hang_skirt now keeps 35 % of the skirt's own outward flare on top
  of the 4 cm gap, both growing from nothing over the first 15 cm below the skirt's top (no step at the belt).
- 2026-11-07 (Claude, armor) Hadvar skirt shape approved by the owner; in the wide combat stance the thighs still came
  through the middle of the skirt. Skirt gradient now 0.3 -> 0.9 thigh share, rising with the square root of the way
  down (the middle follows the legs sooner).
- 2026-11-07 (Claude, armor) Farengar (mage robes, owner): robe body fine; the neckline stands up the neck as a band
  collar where Skyrim's is low at the base of the neck. Measured on the debug meshes: collar_height_field asked for
  2-3.4 cm down all round, and push-out put it straight back up the neck. Now what the collar step brings down within
  8.5 cm of the neck axis is not pushed back out (also not by neck_wrap's or bury's push-outs): the neckline is where
  the cloth meets the skin, as Skyrim's (offline: back of the neck shows again). Also neck_inside (horizontal
  inside-the-neck gap kept, final step), the collar drop printed, and part file names keep ':N' (Farengar's
  boots:0 / boots:1 both wrote boots.nif).
- 2026-11-07 (Claude, armor) Farengar: the new "neck steps" report showed wrap False: no Skyrim neck joint among the
  fitted shapes' bones (robe and body have no neck-weighted vertices), so collar height, neck_wrap, neck_inside and
  the hidden-part placement were all skipped and push-out stretched the beige collar trim up the neck. wrap_params
  now falls back to the head joint (same axis).
- 2026-11-07 (Claude, armor) Farengar neckline better after the head-joint fallback; owner: the beige trim is still
  thicker and stands closer round the neck than Skyrim's (texture shows the stretch). For measuring it: the debug
  export now writes UVs and each gear shape's diffuse texture as PNG (texconv), and the run prints the edge-length
  ratio against Skyrim (scaled) above the clavicles (10/50/90 %).
- 2026-11-07 (Claude, armor) Farengar textured comparison (debug meshes with UVs and the robe texture, crowns lined
  up, verified): the beige trim's band at the back lies 54-123 mm from the neck axis in Skyrim but 32-69 mm in ours,
  ~1 cm higher; front and sides match within ~1 cm. Cause (supported): neck_wrap measured Skyrim's gap from the
  shoulders at that height and Starfield's from the neck (Starfield's shoulders sit lower under the head), pulling the
  band in. neck_wrap now acts only where both rays meet the neck / head mesh itself. Edge-length relaxation tried
  offline (90th percentile stretch 1.72 -> 1.18) but it wrinkled the back; not used. Collar step skipped for shapes
  with nothing above the clavicles (boots had printed a collar drop).
- 2026-11-07 (Claude, armor) Collar transplant (owner, textured comparison without heads: the beige trim does not go
  round the neck flat and wide; verified offline on his Farengar debug meshes that a whole-collar copy matches
  Skyrim's ring): gear within 11 cm of the neck opening (Skyrim distance, scaled; blended out by 17 cm) is copied
  from Skyrim, placed by the centres of the two bodies' neck openings (open edges near x = 0 at the top of each body
  mesh; Farengar: Skyrim 1.601 m, Starfield 1.519 m). Parts visible in Skyrim then keep Skyrim's gap to the body and
  are pushed out; parts hidden inside Skyrim's neck stay hidden. Runs after the other neck steps (which still act
  beyond its reach).
- 2026-11-07 (Claude, armor) Collar transplant in game (owner): "way closer to Skyrim"; the shoulder tops showed
  through the robe at every weight. The copy reached them (11 cm full, 17 cm blend): now 9 cm full, 13 cm blend
  (offline: ring still Skyrim's, front trim slightly wider). Owner also reports a hand clipping on the thinnest body;
  not yet located.
- 2026-11-07 (Claude, armor) Farengar (owner): skin through the shoulders and the beige trim at all weights, and on
  the thinnest body the hands through the sleeve cuffs. (1) Skin piece overlap under the gear's edges: one ring,
  then at most 2 cm from visible skin (supported: five rings on the shoulders' large triangles reached the shoulder
  tops from the neck opening, under robe 5 mm off the body). (2) Gear within 3 cm of the hands mesh takes no
  body-slider move, full by 8 cm (the forearm shrinks under Thin, the separate hands mesh does not).
- 2026-11-07 (Claude, armor) Shoulder skin diamonds on Farengar found (verified on the debug meshes with the skin
  piece exported): the skin piece sits exactly on the body; the robe's corners are 4 mm out on the shoulder tops but
  its face centres dip to 1.2 mm inside the body (convex shoulders, faces wider than the body's), so 21 shoulder-top
  skin vertices had no robe over them. New step push_faces_out: faces whose corners are all outside and whose centre
  is under 3 mm out (but not deeper than 1 cm) are lifted along the body normal, up to 6 mm a round, 3 rounds.
  Offline: 240 vertices lifted, no uncovered shoulder skin left.
- 2026-11-07 (Claude, armor) Shoulders fixed by push_faces_out (owner). Left: neck skin through Farengar's collar
  trim, worst on the thinnest body. At default weight none of the trim's visible vertices is inside body or head
  (verified on the debug meshes), so the slider is the cause (supported): the trim shrinks with the body's Thin, the
  head mesh's neck does not. Gear within 3 cm of the head mesh now gets no Thin delta (full by 8 cm).
- 2026-11-07 (Claude, armor) Farengar collar trim (owner): no clipping looking straight ahead at default; skin through
  the trim when the head turns. Above the clavicles the gear kept its own weights (no neck bones), while the neck
  skin under it turns. Now gear within 1 cm of the head mesh takes the neck skin's weights (blended to its own by
  2.5 cm); the rest of the collar still keeps its own (the head-weights option stays off by default). Also the
  skin piece now drops skin with gear up to 1.5 cm under it (the neckline brought down into the body), not only
  over it. The Thin change of the previous commit stays.
- 2026-11-07 (Claude, armor) Ralof re-run with everything since (owner): collar much better from the front; from
  behind the arm stops short of the chainmail sleeve and the gap shows. The whole-body skin piece now drops skin only
  under gear within 1.2 cm (was 3.5 cm): under looser gear (sleeve backs, hems) the skin stays, so nothing is seen
  through. Poke-through under tight gear is still prevented by the drop and push_faces_out.
- 2026-11-07 (Claude, armor) Skin piece back to Skyrim's own rule (owner asked whether Skyrim hides the legs under a
  robe; verified from the runs: Farengar's robe NIF brings only an 86-vertex neck/chest skin shape, robes_skin, and
  his robe's slots are 31, 32, 42, not 37: under the robe Skyrim shows no legs, and the feet come from its separate
  naked-feet slot). Skin piece = the Starfield body where Skyrim's bare-skin shapes lie (with the overlap under gear
  edges), plus the feet (body vertices mostly on Foot / Toe / Ankle bones) when the body armour does not cover
  Skyrim slot 37, so boots stay removable. --whole-skin keeps the whole-body variant.
- 2026-11-07 (Claude, armor) Owner's next test: Ralof, Ysolda, Nazeem and Saadia in game wearing their own outfits.
  gear_fit --add keeps the other outfits already in S2SArmorTest.esm (this --name's records replaced) and their
  converted textures (_staging kept, packed again each run); face_fit --outfits-plugin S2SArmorTest.esm makes it a
  master and sets each test NPC's DOFT / SOFT to the OTFT named S2S_<NPC EditorID>_outfit_Outfit. Female bodies
  (Ysolda, Saadia) go through gear_fit for the first time: unresolved.
- 2026-11-07 (Claude, armor) gear_fit --add re-runs keep the outfit's ARMO and OTFT FormIDs (reused by EditorID;
  other new records numbered past every record in the plugin), so test NPCs pointing at an outfit stay dressed after
  an outfit is re-fitted. Owner's first four-NPC test: NPCs spawned without their outfits (cause not yet known).
- 2026-11-07 (Claude, armor) Ysolda / Saadia in game (owner): thin lines across the chest and an outlined
  rectangle on the back. Measured on their debug meshes (verified): the lines follow the lower edge of Starfield's
  female head mesh, which lies exactly on the body (and on our skin piece) over the upper chest and back; the
  dresses themselves match Skyrim's shape. Low necklines leave that edge uncovered, where our skin piece, with
  re-encoded positions (morph margin), recomputed normals / tangents and median-frame binds, did not match the body
  under the head's edge (supported). The skin piece now keeps the vanilla body's own encoding: scale, int16
  positions, packed normals and tangents, and the body's own per-bone binds.
- 2026-11-07 (Claude, armor) Saadia's dress (owner, textured comparison): the halter strap and the bust line from the
  white bodice to the dark band jagged where Skyrim's curve smoothly. New last step final_relax (before
  push_faces_out): the fit's change from the skeleton-blended shape smoothed 12 rounds over the mesh (the shape's own
  detail kept), then everything visible in Skyrim pushed out with the push spread to neighbours; parts hidden in
  Skyrim and the lowered neckline exempt. Offline on Saadia's debug meshes (Skyrim shape as base): strap and bodice
  edge smooth, no visible vertex inside the body.
- 2026-11-07 (Claude, armor) After final_relax (owner): Ysolda's neckline shows dark brown patches, Saadia's halter
  straps go under the skin (worse on heavier bodies), and her sleeve top under the arm skin. Measured (verified, on
  the earlier debug meshes): Ysolda's dress has a brown chest panel 219 of whose upper vertices lie inside Skyrim's
  body (hidden by the skin); the fit pushed 136 of them out. Saadia: 73 visible strap vertices inside Starfield's
  head mesh, whose flap covers the upper chest and back but was not in the push-out surface. Changes: keep_hidden
  (last step) puts gear hidden in Skyrim back inside at its Skyrim depth (3 mm-3 cm); the head mesh's vertices below
  the neck joint + 2 cm join the push-out surface. The sleeve-top clip not yet measured.
- 2026-11-07 (Claude, armor) After keep_hidden (owner): Ysolda's brown still on the chest, Saadia's straps still
  clipping. Measured on the new debug meshes (verified): the remaining Skyrim-hidden chest-panel vertices (Ysolda 63,
  Saadia 201, 3-31 mm inside Skyrim's breasts) measured as outside the separate underwear (bra) shape, which was part
  of the Skyrim body surface; keep_hidden never saw them as hidden. Underwear shapes (name with "underwear", not
  "body") now left out of the Skyrim body. Saadia: 42 strap vertices up to 4 mm inside the head mesh at 1.45-1.52 m,
  above the flap band: the head band joined to the surface widened to the neck joint + 5 cm.
- 2026-11-07 (Claude, armor) Owner: on his own character Saadia's straps are fine at default weight but sink into
  the skin on heavier and thinner bodies; her sleeve band sinks into the upper arm on heavy bodies; the bust looks
  pointed. Slider deltas: gear near the head now takes the head mesh's own morph deltas (its morph.dat found by
  vertex count; body and head merged as one source; the Thin hold near the head dropped when found), and the blend
  is 1/d^2 over the 4 nearest (was 1/d over 6) so gear grows as much as the skin right under it. Bust shape not yet
  measured.
- 2026-11-07 (Claude, armor) Textured z-buffered render of Saadia's dress with the skin and head drawn as in game
  (Skyrim: its own skin piece + head; ours: our skin piece + head) showed our skin piece through the bodice top over
  the bust. Measured (verified): of 411 dress vertices inside Skyrim's full body only 83 lie within 2 cm of skin
  Skyrim draws (the outfit's bare-skin shapes, the head); the others are visible in Skyrim since the naked body is not
  drawn under an outfit. keep_hidden had sunk 208 of them into Starfield's bust. "Hidden in Skyrim" now means inside
  the body AND within 2 cm of drawn skin; it drives keep_hidden, bury, final_relax's exemption and the collar's
  no-push-out exemption (the latter also left Saadia's visible halter straps inside the skin near the neck).
- 2026-11-07 (Claude, armor) Owner on the textured render: Saadia's straps run a different path, the bust is mangled,
  the shape over the arm differs. Offline on his debug meshes (verified visually, textured z-buffer render): the
  fit's placement smoothed (25 rounds) plus Skyrim's own detail (Skyrim shape minus its smoothed self) gave a clean
  bust, Skyrim's lacing and straps. New step detail transfer (before final_relax): the detail is posed by the same
  bone blend as the points (blend(S + L) - blend(S)); skirt-weighted and collar-kept vertices exempt.
- 2026-11-07 (Claude, npc) Beards (owner's choice): Skyrim beards are worn as the closest-shaped vanilla Starfield
  beard instead of converted ones. scripts/npc/beard_match.py: Skyrim.esm facial-hair HDPTs (type 4) placed on
  Starfield's head by skyrimhair.convert, Starfield.esm facial-hair HDPTs read from the game archives, symmetric
  mean closest-point distance, best first; writes beard_match.json (editable). face_fit --beard-map uses it in
  npc_dress for the facial-hair head part (unresolved until run: Starfield beard meshes' placement and type ids).
- 2026-11-07 (Claude, armor) The 2 cm-from-drawn-skin-vertices rule (previous commit) made half of Ysolda's brown
  chest panel count as visible (the Skyrim skin pieces are low-poly, and part of the panel lies under the dress's own
  outer layer), so it was pushed out and showed. "Hidden in Skyrim" is now computed by rendering: z-buffers of what
  Skyrim draws (all the outfit's shapes, including its skin pieces, plus the head) from 18 views (8 azimuths at 0
  and 35 degrees, 2 from above; none from below), a point hidden if inside Skyrim's body and behind something by
  more than 1 mm in every view. Checked on the debug meshes: Ysolda's remaining "seen" brown is the corset band under
  the bust, visible in Skyrim's render too.
- 2026-11-07 (Claude, armor) Owner on the detail-transfer preview: gaps along Ysolda's sleeve seam and at the trim.
  Cause (verified offline): smoothing ran on the mesh as stored, where UV seams are separate vertex copies, so each
  side of a seam was smoothed apart. Detail transfer and final_relax now smooth over seam-joined triangles
  (seam_tris: one vertex per Skyrim position) and copy the result back to the copies; offline the seam and trim close.

## 2026-11-07 — Gear kept outside the body at each slider's extreme (slider_clearance)
- Owner: straps on Saadia/Ysolda fine at default weight, clip at heavy/thin. Gear deltas were 1/d² blends of body deltas, so where gear sat 1–3 mm over the skin a slider that grows the body faster than its nearest-vertex blend let skin through. (supported — matches in-game reports; synthetic test reproduces it)
- gear_fit.morph_files now checks each slider key: morphed gear vs morphed body+head. A vertex outside at default (>0.5 mm) that sinks under SLIDER_GAP 2 mm gets the shortfall added along the morphed normal, spread to neighbours over 2 seam-aware rounds. Skin piece exempt. Printed as "<name> slider clearance". (verified by unittest; in-game unresolved)

## 2026-11-07 — Ysolda's brown flap at the back of the neck: visibility crop bug + hidden gear drawn in
- Cause (verified on the owner's Ysolda debug meshes): seen_from_outside cropped the covering meshes to 25 cm round the query in 3-D. The crown of the head fell outside, so the (180, 70) view looked into the open neck from above and counted the lining tucked 5–8 cm inside Skyrim's neck as visible. Not sky_hidden, so keep_hidden skipped it and the fit left it ~3 cm outside behind Starfield's neck: the brown flap. Fix: no 3-D crop; faces cropped per view to the query's screen square. Synthetic test: point low in a tall closed box stays hidden.
- keep_tucked: gear Skyrim keeps out of sight but not inside its body (e.g. the V-neck lining, collar tab, underarm) is drawn in to no further out than its Skyrim gap (scaled, at least TUCK_MIN 1.5 mm, below visible gear at GAP 4 mm). Inward only; skirts and collar_keep exempt. Offline on the debug meshes the flap and the side protrusion are gone, Saadia unchanged. (verified offline; in-game unresolved)
- slider clearance now reports its largest raise (was printed as 0 mm).

## 2026-11-08 — Bust smoothing (smooth_final) and slider-extreme debug meshes
- Owner's side view of Saadia: "how unsmooth the breast area is". On the debug meshes the blouse's top fold (a fold, not an open edge) went up and down 4–5 mm every 1–2 cm across the bust and rose ~1 cm over the cleavage where Skyrim's curve dips. Cause: keep-Skyrim-gap and push-out to GAP, vertex by vertex against two faceted bodies, print both bodies' facets into the cloth; final_relax pushed back out to the full GAP after its smoothing. (verified offline)
- smooth_final: after final_relax, the fit's moves smoothed 30 rounds (sky_hidden / collar_keep / skirt vertices pinned); gear that was outside and sinks under 0.75 GAP (= FACE_GAP 3 mm, so push_faces_out does not re-ripple it) pushed back to that only. Offline render: edge, sleeve tops and blouse folds smooth like Skyrim. (verified offline; in-game unresolved)
- Tried first and dropped: smoothing only along open edges (the wavy line is a fold, not an edge).
- --debug-dir now also writes fit_<shape>@<slider>.obj (every worn shape incl. S2S_Skin) and sf_head@<slider>.obj at each slider's full extreme, for offline clipping checks at Thin / Overweight / Strong. (supported)

## 2026-11-08 — Gear lying on the skin keeps the skin's weights above the clavicles too (SKIN_HUG)
- Owner's chargen shots of Saadia (default / Strong / Overweight): the halter straps covered by skin at every size, also at default. Debug meshes at each slider extreme (bind pose) show the straps 3–4 mm over the skin and fully visible at every extreme, so the bind-pose shape and the morphs are not the cause. Above the clavicles the straps took Skyrim's own weights (the 2026-11-07 cowl rule); the skin under them has the body's / head flap's weights, so in the standing pose (arms down) strap and skin move apart by more than the gap. (supported: inference from bind-pose renders vs in-game; posed check not done)
- Now: own weights above the clavicles are blended out within SKIN_HUG (6 mm full skin weights … 15 mm own weights) of the Starfield body surface, as HEAD_HUG does at the head. A cowl standing off the skin keeps its own weights (test). Possible regression to watch: Ralof's cowl where it lies within 6–15 mm of the shoulders now follows the shoulder skin.
- Side profile (owner's drawing: rounder bust): the cloth follows Starfield's body, whose bust is lower and smaller than Skyrim's (profile slice verified on the debug meshes). A hollow-bridging pass (outward-only fill of hollows deeper than Skyrim's) barely changed the profile and was dropped; making the cloth rounder than the body means standing it off the skin. Not done; owner to decide.

## 2026-11-08 — Straps farther off the skin (STRAP_GAP); --round-bust experiment
- Owner, after SKIN_HUG: "straps are still too close to body, with skin clipping" at default / Strong / Overweight in chargen. So the skin weights were not (or not the whole) cause. In the bind-pose debug meshes the straps are 3–4 mm off the body and visible at every slider extreme; in game something puts the skin 3–4 mm farther out than our model (pose, the player's head, or shading) — unresolved which. Pragmatic fix: visible gear from Skyrim's clavicles down to 2 cm below them stays STRAP_GAP 8 mm off the skin, ramping to GAP by 6 cm below (lift_to, outward only, hidden / collar_keep / skirt vertices exempt). (supported: owner's report; in-game unresolved)
- --round-bust (off by default, for A/B): on the front of the chest (Starfield body normal forward > 0.5, 4–30 cm below the clavicles) the gear is not carried inward with the body's change and not pulled in to Skyrim's gap, so it keeps Skyrim's rounder shape where Starfield's bust is smaller (owner drew that line). Synthetic test only checks it never draws gear in and leaves the back alone; whether it rounds the profile is to be seen in game. (unresolved)
- 2026-11-08 Owner: the 8 mm strap gap fixed Saadia's straps, but a brown band now shows round Ralof's neck under the cowl. Suspect (unverified): STRAP_GAP lifts the cowl's inner rim / the cuirass's neck band (both visible from some view in Skyrim, so not tucked) 8 mm off the neck. --strap-gap added (0 = off) to confirm; Ralof's debug meshes requested.
- 2026-11-08 Owner on --round-bust: "a bunch of space between the breast and body now" and the shape "still jagged and not rounded". round_bust stays off (default). The jagged outline: a slice through Saadia's debug meshes shows the blouse front as straight 1.5–3 cm segments with kinks: flat_subdivide keeps Skyrim's low-poly outline (the fit only moves those flat facets). --curved (off by default, A/B): Phong tessellation (share CURVE 0.6) on normals averaged per position (no cracks at UV seams), bulge capped at CURVE_CAP 12 % of the longest edge so folds do not balloon as PN patches did on Ralof's cowl. Synthetic test: a curved split of an octahedron lies closer to the sphere and stays crack-free. (in-game unresolved)
- 2026-11-08 Owner: --strap-gap 0 removed Ralof's brown band (confirmed: STRAP_GAP was the cause). On his debug meshes the cowl's inner rim, 6–11 cm from the neck's axis, was lifted 8 mm off the neck and the cowl's inside showed through the gap. Now no strap lift within STRAP_NECK 8.5 cm of the neck's axis (from the Starfield head's ring 25 cm below the crown), full past 10.5 cm; Saadia's straps lie ≥ 10 cm out. --round-bust only acts on female outfits (owner: breast handling must never touch male outfits; later, male and female versions of an outfit as Starfield does).
- Saadia's sleeves (owner's shots; debug render): Skyrim's sleeve tops sit low on the upper arm in one smooth line; ours sit 2–3 cm higher, near the shoulder top, with a wavy edge, so the shoulder clips through. Not fixed yet.
- Bust: owner's reference, Starfield's own female undersuit, is rounder and fuller than the naked body; Starfield's clothes do not follow the naked bust. Idea (not done): fit the torso over a vanilla Starfield tight female outfit mesh instead of the naked body.
- 2026-11-08 Owner comparing our renders with Skyrim's: the bodice's top trim, the bust's side outline and the sleeve tops (Saadia) and the cowl's lower edge (Ralof) are still jagged where Skyrim's are smooth curves. Smoothing the debug result once more (smooth_final + push_faces_out offline) took the jaggedness out, so the order is now: strap lift, keep_tucked, smooth_final (then the strap lift again on the lifted vertices), push_faces_out, keep_tucked again, keep_hidden — the steps that move single vertices no longer run after the smoothing, except on hidden ones. (verified offline on the smoothing; in-game unresolved)
- Owner: Nazeem shows a seam / dark band at the neck and Ralof's cowl front sits lower than Skyrim's after the strap changes. The strap lift is now on for female outfits only (default; --strap-gap overrides): it was added for Saadia's halter straps over the female head mesh's chest flap, and on male collars it opened gaps at the neck. (supported)
- 2026-11-08 Owner: Ralof's and Nazeem's necks fixed (male strap lift off). Saadia's sleeve tops "give out" and fold at the front of the armpit with the arms down (in game), while smooth in the bind pose (debug render): the sleeve took the nearest body vertex's weights, by the armpit often a chest / back vertex, so with the arms down part of the sleeve stayed with the torso. body_weights_near now matches limb to limb: gear whose own weights are > 50 % arm bones (arm_share) takes weights only from body vertices > 50 % arm, the rest only from the others. (supported; in-game unresolved)
- Nazeem: a bulge and a crease line across the chest (owner). Debug meshes: the robe front at the pecs stands 35–37 mm off Starfield's chest (Skyrim: 10–19 mm off Skyrim's), above it pulled down to 4 mm by the collar steps: a tent. Starfield's male chest is ~2 cm flatter; the cloth kept Skyrim's absolute position. Which step keeps it out is unresolved; --debug-steps (with --debug-dir) now writes the gear after each group of fit steps (fit_<shape>@step<n>_<name>.obj) to find it.
- 2026-11-08 Owner, on our renders vs Skyrim's (Saadia): "can we not make the bottom look like the top?" Plan: a conform mode — Skyrim's outfit posed on Starfield's skeleton, bent by a smooth (wide) field of the Skyrim-body → Starfield-body offsets, then only collisions fixed with a smooth spread push — instead of the chain of per-vertex steps. To prototype it offline, --debug-steps now also writes the posed gear (step 0_posed), Skyrim's body posed on Starfield's skeleton (skybody_posed.obj) and where its offsets take it (skybody_posed_to_sf.obj).
- 2026-11-08 Found where the jaggedness starts (verified on Saadia's --debug-steps meshes): step 0, the outfit only posed on Starfield's skeleton before any fitting, already has the jagged top trim, bumpy bust and dented sleeve tops. Linear blend skinning with Skyrim's weights between two different skeletons moves neighbouring vertices with different weight mixes up to ~2 cm apart. smooth_pose: the posing move (posed - rest) smoothed over the mesh (POSE_ROUNDS 40, UV seams joined), for the gear and for Skyrim's body alike. Offline: the posed trim becomes one curve with Skyrim's dip at the centre. (verified offline)
- Offline prototype of the conform method on the smoothed pose (smooth wide field of the Skyrim-body → Starfield-body offsets, σ 4 cm, facing-weighted; then collisions pushed out with the push smoothed over the mesh, 25 rounds; Skyrim-hidden parts not pushed): trim, sleeve tops and back edge come out as smooth as Skyrim's (render shown to the owner). Not in the build yet; smooth_pose is, under the existing steps.
- 2026-11-08 Owner after smooth_pose: Saadia "actually looks really good"; only the sleeve top at the back of the upper arm by the armpit needs to stand out more (skin comes through there with the arms down), "slightly noticed it in the same place in the other outfits". arm_top_gap: gear mostly on arm bones from the shoulder joint (L_/R_Biceps) to 35 % of the way to the elbow stays ARM_GAP 8 mm off the skin, fading to GAP by 60 %; all outfits, both sexes; lifted with the strap lift (before smooth_final, again after it). (supported; in-game unresolved)
- 2026-11-08 Owner: the armpit no longer clips. Nazeem's chest still stands out (side view). --conform (option, for A/B against the current fit): after smooth_pose, the gear moves by conform_field (the Skyrim-body → Starfield-body offsets averaged with a Gaussian, σ CONFORM_SIGMA 4 cm, weighted to body points the gear lies outside of), then conform_push clears the body with the push smoothed over the mesh (CONFORM_ROUNDS 15; Skyrim-hidden parts not pushed); keep_gap, cover, relax, detail transfer and final_relax are skipped; the collar steps, skirt hanging and the tail (strap / arm lift, tuck, smooth_final, faces, hidden) stay. Synthetic test: the ripple survives and the cloth clears the body. Offline prototype on Saadia matched Skyrim's edges. (in-game unresolved)
- Owner ran beard_match.py: 50 Skyrim beards → 16 Starfield ones; 22 of them land on Human_Male_Beard_Patchy (chamfer distance favours the sparse, face-covering mesh) — to be checked in game; matches can be edited in beard_match.json.
- 2026-11-08 Owner: NPCs and outfits "fitting well enough for now"; next an armor (iron). gear_fit --armor EDID (repeatable): those Skyrim armor records instead of the NPC's outfit, worn by the NPC's race and sex.
- 2026-11-08 Iron armor (owner: "actually looks pretty good"). Helmet: the neck steps treated it as a collar (3187 vertices "wrapped round the neck", up to 15 cm) and its untextured eye-shadow shape ("shades", fallback material) showed as a band over the eyes. Owner: helmets are a separate step, worn the way Starfield's hats are; work them out from Starfield's hats. gear_fit now leaves head gear (Skyrim slots 30 / 31 / 41-43 without 32) out unless --helmets. Open: the cuirass's arm openings do not go round the arms (compare the openings on the Skyrim and Starfield bodies); the gauntlets were classed as a skin piece (median 3 mm off the hands) and so not fitted — to check.
- 2026-11-08 Owner: toes through the bottom of the boots again (Ralof's, the female outfits', the iron boots). Verified on Saadia's --debug-steps meshes: after the fit steps no shoe vertex was inside Starfield's foot (step 3), 30 after final_relax and 140 (down to -14.7 mm) after keep_hidden. The visibility views never look from below, so the soles counted as hidden in Skyrim and were put back "inside the body as in Skyrim"; since the 3-D crop fix more of them count as unseen. Feet and hands (end_share > 0.3 on foot / toe / hand / finger bones) are now never sky_hidden or sky_tucked, and smooth_pose pins them too. (verified cause offline; in-game unresolved)
- 2026-11-08 Iron cuirass armholes (owner: torn / arm through the armor at the armpit when aiming). Debug meshes, bind pose: Skyrim's armhole rim rolls 20–30 mm inside the shoulder (rope trim), ours too; at the bottom of the armhole the rim lies on the skin (ours 1.5 mm, Skyrim 0.3 mm), so the pose decides. With the limb-to-limb weight rule the rim (Skyrim: partly arm-weighted) took only the torso's skin weights and stayed put while the arm swung into it. body_weights_near now mixes the nearest arm vertex's and the nearest torso vertex's weights by the gear's own arm share (ARM_MIX: torso at ≤ 0.2, arm at ≥ 0.8). (supported; in-game unresolved)
- 2026-11-08 Owner's rebuild (sole fix included): toes still through the iron and Stormcloak boots and the female shoes; a seam across the Stormcloak sleeves. Verified on the debug meshes: no boot vertex is inside the foot at the toe, but the foot's toe tip stands up to 2 cm out through the boot between its vertices (push-out only moves gear vertices inside the body). skin_through: body points out through foot / hand gear (or within GAP under it) push the nearest gear vertices out along the gear's own normal (≤ 6 mm per round, spread smoothly), last step before weld. Offline: Stormcloak boot fully covered, iron toe covered with the shape kept; the sole stays jagged (pre-existing). Sleeve seam: the arm share used for the arm / torso skin-weight mix is now smoothed over the mesh (smooth_share, 8 rounds), so neighbours do not take weights from different limbs. (supported; in-game unresolved)
- 2026-11-08 Owner after the rebuild: shoes fixed on the outfits. Iron cuirass (--conform): skin through the left shoulder; armhole still pinched, armpit see-through; Ralof's under-arm seam still there. Iron debug steps: the armhole is a teardrop already right after the body-offset shift (step 1), so the rim took the arm skin's offsets (Starfield's arm thicker, closer to the chest); holes in the shoulder appear at the collar step, whose correction hit the 10 cm clamp in one direction ("collar brought down by -100..0 mm"). Now: body offsets limb to limb (gear takes the torso's or the arm's Skyrim-body offsets, blended by its own smoothed arm share, ARM_MIX), for the old fit and --conform; the collar correction no more than COLLAR_SPREAD 3 cm below its median direction. (supported; in-game unresolved)
- 2026-11-08 Owner: sky seen through the iron cuirass's armpit when aiming; a see-through seam under Ralof's arm; his drawing of the round armhole path vs ours. Verified on the debug meshes: (1) the body round the armpit was not in the skin piece (the gear covers it with the arms out; Ralof: 33 of 241 armpit-side body vertices kept) and raising the arm opens the armhole over it: skin_piece now always keeps the body within ARMPIT_REACH 8 cm of the arm / torso weight seam (armpits()). (2) The armhole stayed a teardrop with a notch after the limb-matched shift: ring_restore fits the armhole loop's posed Skyrim shape onto the fitted loop (Procrustes similarity) and applies it to the loop and, fading, 5 cm round it, then conform_push clears the body; loops mostly on arm bones (sleeve edges) are left. Offline on the iron debug meshes the armhole comes out round like Skyrim's, nothing inside the body. (supported; in-game unresolved)
- 2026-11-08 Owner: iron armor left for now. Ralof: under the arm the mail sleeve and the tunic come apart (before: see-through, now the armpit skin shows); it should be cuirass to sleeve to arm, no skin. Cause (supported): the sleeve and the tunic are separate parts of one shape; Skyrim's arm share jumps ~0 → ~1 across the join and the mesh smoothing (smooth_share) did not cross it, so the sleeve took the arm skin's weights / offsets and the tunic the torso's, and they parted in motion. The arm share is now averaged in space (smooth_share_near, Gaussian over gear points within 3.5 cm, across separate parts) for both the skin-weight mix and the limb-matched offsets.
- 2026-11-08 Owner: with the arm share averaged in space, Ralof's mail sleeves stood off the arms while running (the sleeve tops took part torso weights). Now the skin-weight mix uses the gear's own arm share again (unsmoothed), and at the join of arm and torso parts (own arm share 0.05-0.95, or arm parts within 1.5 cm of torso parts) the gear keeps Skyrim's own weights, made for that join, fading to the skin's between 3 and 7 cm from it (join_keep, blend_weights). Unresolved in game.
- 2026-11-08 Owner: the sleeve-to-tunic disconnect on Ralof came with today's changes. Measured on his debug meshes (sleeve parts vs the rest, bind pose): 11:38 build 1st/5th/10th percentile gap 2.6/8.3/13.5 mm (Skyrim 4.4/7.4/9.2), 13:22 build 8.1/13.0/20.6 mm; in between came smooth_pose and arm_top_gap (sleeve tops 8 mm off the upper arm, for Saadia's armpit). arm_top_gap now skips the sleeve-tunic join (join_keep ≥ 0.5). (supported; smooth_pose not ruled out)
- 2026-11-08 Ralof's sleeve still detached after the arm-lift change (gap 6.5/11/17 mm vs 2.6/8.3/13.5 at 11:38, Skyrim 4.4/7.4/9.2). Compared the 11:38 and 15:2x debug meshes pair by pair along the join: the sleeve edge moved ~10 mm down and 5 mm out, the tunic edge next to it ~4 mm in: the limb-matched body offsets split them (sleeve: arm offsets, tunic: torso offsets). Now within the join zone (join_keep) both take the unsplit offsets. ring_restore also skips armholes with another part (a sleeve) attached along them (Ralof's tunic; the iron cuirass's armhole is still restored). (verified cause offline; in-game unresolved)
- 2026-11-08 Owner (angry, rightly): Ralof's sleeves stand far off the tunic in game, "this was NOT an issue before", "are you even checking it on Starfield's body". I was checking only the bind pose (arms out) in the debug meshes; the gaps open in the game's standing pose and I have no posed check. Reverted to the 11:38 behaviour: limb-matched skin weights, ARM_MIX, the join-zone weight keep and the limb-split body offsets are all behind gear_fit --limb-match (gearfit.LIMB_MATCH, default off); nearest skin as before. Kept: smooth_pose, the foot fixes, armpit skin, arm-top lift (not at joins), ring_restore (not where a sleeve is attached). Next: a posed debug export (arms down) so gaps are checked before the owner looks.
- 2026-11-08 Real cause of Ralof's detached sleeves (verified on his 14:29 --debug-steps meshes, gap sleeve ↔ rest at 1st/5th/10th percentile): fine through the collar step (3.4/7.3/10.7 mm, Skyrim 4.4/7.4/9.2), opened by the detail-transfer step (5.5/10.5/19.7) and the later smoothings (final 7.7/12.8/19.9). The mail sleeves and the tunic are separate parts of one shape; every mesh smoothing (detail transfer, final_relax, smooth_final, smooth_pose) smoothed each part on its own. Smoothing step 4's placement offline: per part 33/37/42 mm apart, with the parts linked 5.2/8.3/11.7. seam_tris now links each vertex to the nearest vertex of another part within PART_JOIN 1.2 cm (extra degenerate triangles), so all smoothing crosses part joins; ring_restore uses join=False (it needs the parts). Probably also behind the earlier Stormcloak "seam" and the iron armhole tear. (verified offline)
- 2026-11-08 Owner, in game: Ralof's sleeve is reconnected with the part-linked smoothing (verified).
- 2026-11-08 Owner: a sliver of armpit skin between Ralof's sleeve and tunic when aiming. His newest --debug-steps meshes: the bind-pose gap is at or under Skyrim's after every step (final 3.9/6.0/8.3 and 2.9/5.7/8.9 mm vs Skyrim 4.4/7.4/9.2), so it comes from the pose. join_weights: across part links (part_links) both ends take their averaged weights, spread at half / quarter strength over two mesh rings, so the join bends as one. (supported; in-game unresolved)
- 2026-11-08 Exterior <-> interior load doors (owner: connect the Riverwood inn to Riverwood): batch --exterior, stage --interiors, PluginSpike EXTERIOR_DIR / EXTERIOR_DOORS; the exterior door's XTEL set by an override in FO4Port.esm (FO4Port masters the exterior plugin, which avoids a circular master pair). Details in docs/interior/skyrim-interiors.md. Tests: exterior_doors / link_load_doors exterior, mark_load_doors; C# uncompiled.
- 2026-11-08 Verified in game (owner): Riverwood <-> Sleeping Giant Inn load doors work both ways (FO4Port.esm overriding the installed exterior's door; no exterior rebuild).
- 2026-11-08 Exterior navmesh (owner: "convert the exterior mesh, and build a way to compare those meshes between Skyrim and how it appears starfield"): make_skyrim_navmesh.py export / compare, exteriornavmesh.py, PluginSpike EXTERIOR_NAVMESH, navmesh_survey.py --exterior; docs/terrain/exterior-navmesh.md. Skyrim navmeshes split at Starfield's 100 m cells by triangle centre, inner seams become edge links (supported; --no-split for A/B). Parent grid written as (Y, X) in Mutagen's Coordinates (supported by xEdit; compare checks the bytes against XCLC). Grid order, outdoor triangle height from the vanilla survey (unresolved until the PC run). No NAVI (unresolved). Synthetic tests: split, links, grid, export -> plugin -> compare round trip, survey. C# uncompiled.
- 2026-11-08 Owner pointed to tes4skyrim (bryantmh) for how it converts navmeshes between Bethesda games. Its findings from Skyrim's pathfinder (method only, no code copied): navmeshes count only when listed in the master's NAVI (plugins override it with their own entries; the game merges), load doors need XNDP, the search grid is row-major (rows along Y) with each triangle in every grid cell it overlaps, seam links are Portal (type 0). Our interior navmeshes had no NAVI entry and no XNDP. PluginSpike now writes a NAVI override of Starfield.esm's (ours only; tail bytes copied from Starfield's most common entry; master indices from a second write pass) and XNDP; build_grid uses exact triangle/cell overlap; seam links Portal. navmesh_survey --exterior surveys NAVI (and --navi-esm for the DLC: does its override carry only its own entries?); compare checks NAVI entries and XNDP. (supported for Starfield; NAVI merge semantics unresolved — NAVI=off escape)
- 2026-11-08 Exterior navmesh measured on the owner's PC: parent grid Y,X (400/400, verified), grid order yx (0.9998, verified), vanilla triangles stay in their cell (split verified as the right shape), outdoor height FLT_MAX (verified), ShatteredSpace.esm overrides NAVI 000FF1 with only its own 29,270 entries (merge, strongly supported). First build compiled: 103 navmeshes, NAVI 103/103, XNDP 14/14. NVMI tail fixed to 00 00000000 (79 % of vanilla; PluginSpike's own inference read 0F00000000 from 748 entries, wrong). Edge-link "mismatch" 615 = same in Skyrim's own data (T-junction seams); check reworked to a gap measure. Grid bounds != vertex bbox in vanilla (unresolved; survey samples added).
- 2026-11-08 Vanilla exterior navmesh grid bounds = vertex bbox with max z FLT_MAX (survey samples, verified); export writes that, PluginSpike / serialize_starfield keep FLT_MAX unscaled.
- 2026-11-08 Sun never high over Riverwood (owner): set_planet_latlon.py shows / moves the planet record's CNAM master-worldspace latitude in place (staged + installed copy if identical, overlays_params.json). Pole sun path hypothesis (supported); axial tilt unresolved.
- 2026-11-08 Owner: an invisible hump in Riverwood's road (player climbs over it, Ralof stuck there in combat pathing) - collision, not navmesh (supported). which_ref.py maps a console FormID / position to the converted ref, its Skyrim source and NIF to find it. Unresolved until the owner's lookup.
- 2026-11-08 terrain_view.py (owner asked for a terrain visualizer for the invisible hump): window of the staged BTD around a spot vs Skyrim LAND + offset, 3x3 bump map, objects / water pieces, HTML with 2-D views and a three.js 3-D view (checked offline with a synthetic BTD; three.js served locally in the check).
- 2026-11-08 Owner's getpos at the hump hunt were the Riverwood spawn itself (225.70, -627.74, z 184.15: the planet's merged grid, not the exterior frame where the ground is ~382 m); which_ref.py gained --spawn-at (as ground_at / terrain_view) to shift game positions into the exterior frame.
- 2026-11-08 Invisible hump at Riverwood's arrival: verified in game to be SKY_RoadStraightLongRamp01's collision (owner disabled the ref, walked over fine). The installed exterior (skyrim_all) has only box collision (no skyrim-native anywhere: converted before / without native collision); the road is a "landscape" path, so column boxes. collision_view.py (visible mesh vs Skyrim's Havok collision vs our boxes) showed on the synthetic dome that merged column tops crept up to 2 m above Skyrim's surface: each column was compared with the run's running maximum. Fixed: a merged box's columns all lie within TOP_TOL 0.1 m (column_boxes). The proper fix for the exterior is a reconversion with native collision (--starfield-data), as the interiors already have (verified walking).
- 2026-11-08 Exterior collision fix path: exterior_collision.ps1 = convert C:\Modding\work\sky_all with --starfield-data (native collision, box fallback with the fixed merge), refresh_models.py copies only the meshes tree over the staged files of the same names (plugins / FormIDs / LOD / grass / planet untouched, so FO4Port's overrides stay valid), deploy_skyrim_exterior uninstall + install. Unverified in game.
- 2026-11-08 NPC schedules started (owner: try an NPC with their schedule; Orgnar). PACK layouts of Skyrim and Starfield are the same shape (xEdit defs; supported): plan = same schedule, Starfield template matched by EditorID, inputs remapped. package_survey.py (Skyrim NPC packages / placement / ownership, Starfield templates) first; docs/npc/schedules.md.
- 2026-11-08 Orgnar: one package (SandboxWorking, all day, near an XMarker r 3.66 m). make_schedule.py + PluginSpike ACTORS: vanilla-package copy per Starfield template (Sandbox 00002CB1), inputs by name, XMarker 0x3B placed when the Skyrim marker was not, radius as float bits (supported by xEdit; Mutagen u32), NPC = copy of face_fit's vanilla template (generic look for now), persistent ACHR. C# uncompiled.
- 2026-11-08 make_schedule: conditioned / quest-owned packages left out by default, packages located outside the batch interiors left out, Eat -> Sandbox (eating allowed). From the Delphine / Embry survey.
- 2026-11-08 Verified: Starfield PACK PLDT radius is a float (vanilla raw bits 40A00000 = 5.0, 40400000 = 3.0). First NPC-with-packages build compiled (Orgnar, Delphine, Embry).
- 2026-11-08 Owner: inn NPCs wander instead of following packages; room doors do not open. Fix attempt: clean vanilla package copies (no quest / scripts / conditions / alias inputs), XMarker looked up; room (non-load) doors left out as open doorways (INNER_DOORS=static to keep).
- 2026-11-08 Verified in game: Orgnar's converted package does not run (GetIsCurrentPackage 0, GetCurrentAIProcedure -1). A/B added: the vanilla package copied is appended unchanged after ours.
- 2026-11-08 Verified: Starfield's getcurrentaiprocedure works (vanilla guard 11); Orgnar (-1) runs no procedure. Clearing IsCharGenFacePreset / SimpleActor on the NPC copy (the ChargenPreset base) as the next test.
- 2026-11-08 Correction: getcurrentaiprocedure -1 is not evidence of "no procedure" (vanilla bartender Nyssa Marcano also -1); the entry above calling it verified was wrong.
- 2026-11-08 Verified (format): Starfield PSDT month is stored +1 (form version >= 122, xEdit; Starfield 582): 0 = any. We wrote Skyrim's -1 (= any there) raw through Mutagen, so no converted package could run; all 297 packages of ShopkeeperSchedules.esm use 0. make_schedule now writes month + 1; Energy x 0.01 (Skyrim 0-100, Starfield 0-1: supported by the mod). In-game result unverified.
- 2026-11-08 Verified in game: with month 0, Orgnar's converted package runs (GetIsCurrentPackage 05000E64 = 1, stays behind the bar). Next: Skyrim furniture / idle markers to Starfield ones.
- 2026-11-08 Furniture started (docs/npc/furniture.md): Skyrim marker positions are in the NIF (BSFurnitureMarkerNode), Starfield's in the FURN record (SNAM, 28-byte elements from version 555; xEdit, supported). furniture_survey.py first, to choose between a Starfield FURN per Skyrim base (our model + SNAM from the NIF) and vanilla marker-only furniture placed at the Skyrim markers.
- 2026-11-08 Furniture plan chosen from the survey (verified: Starfield picks furniture animations by KWDA keywords, SNAM z is 0, idle-style actions are marker-only furniture): each Skyrim FURN / IDLM base -> a copy of a vanilla Starfield furniture of the same kind with our model and the Skyrim NIF markers (make_furniture.py, PluginSpike FURNITURE). Crafting stations left as statics. C# uncompiled; in game unverified.
- 2026-11-08 Verified in game + survey: copied marker-only furniture keeps Is Marker (0x800000) and is not drawn (missing benches); cleared when our model is used. Bar counters now Starfield's bar furniture (NPCBartender_Standing, NPCLeaningBartopFront, NPCDeskLean) instead of the rail lean.
- 2026-11-08 Furniture: chairs / benches copy real vanilla furniture (FoundCanvasChair01_Free, Bench_UtilityA02) after the marker-only copies could not be used by the player (unverified which part caused it; FURNITURE_MODEL=vanilla A/B). Marker stand-off to be measured (furniture_standoff.py) rather than guessed; applied with make_furniture --shift.
- 2026-11-08 Verified (measured on vanilla placements): Starfield bar markers stand at the counter face, Skyrim's 0.31-0.32 m back, counter tops 1.10 m in both. Bartender / bartop-lean markers shifted +0.30 m by default (make_furniture DEFAULT_SHIFT). In game unverified.
- 2026-11-08 Verified in game: bartender on the bar with the +0.30 m shift; chairs, benches (real vanilla templates) and beds usable by the player. Open: NPCs using beds / chairs / sweep markers on their own; Allow Wandering still forced on sandboxes (make_schedule NO_FURNITURE).
- 2026-11-08 Scheduled NPCs use their face-test NPC (S2SFaceTest.esm) by OVERRIDE, not copy: their Skyrim greetings are GetIsID-conditioned on that record. FO4Port.esm gains the face plugin chain as masters (written with an explicit load order; all full masters). Alternative (copy + re-point the greetings) rejected: more records to keep in step. C# uncompiled.
- 2026-11-08 Outfits on scheduled NPCs: (1) gear parts get distinct biped slots (Embry's shirt and pants shared [3, 5]; only the pants showed; supported: one addon per slot). (2) Test NPCs get a fixed body per sex (MWGT / MRSV of ChargenPresetFemale04_Swap / ChargenPresetFemale04) instead of their face template's (Delphine's CF_KlaudiaSwist body pushed through the shoulders of the dress Ysolda wears cleanly). Alternative: map Skyrim weight to MWGT later, once outfits follow every body.
- 2026-11-08 Races: target is faithful playable races with working sliders, not baked heads (owner). race_survey.py first (Skyrim RACE head data, chargen .tri sliders via a new FRTRI003 reader, topology vs Nord; Starfield RACE chargen, head part types incl. Creature parts, bone modifiers, archive character files). Plan in docs/npc/races.md, decided on the survey's results.
- 2026-11-09 Races (survey verified): all humanoid Skyrim races share one head per sex; the race is one morph (MaleHeadRaces.tri); chargen sliders are shared (36 continuous + 96 presets). Starfield HumanRace's phenotypes are the same idea (region-keyed head morph.dat). Proposal: humanoid races as new phenotypes inside HumanRace (not new RACE records), Skyrim presets as morph-group entries, continuous sliders as new face dials; beast races as their own RACE with a converted head on Starfield face bones. Next: read the head morph.dat / regions, offline transfer + render. docs/npc/races.md.
- 2026-11-09 Races decided (owner): separate RACE per Skyrim race, thin over HumanRace (armor / subgraph / morph race = HumanRace, its keywords); phenotypes first. Found: morph.dat max 128 keys, so Skyrim phenotypes may need their own head part. race_probe.py: head morph keys / regions, HumanRace-by-name counts, race morphs transferred + viewer.
