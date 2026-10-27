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
