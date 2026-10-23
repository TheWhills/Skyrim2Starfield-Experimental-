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
