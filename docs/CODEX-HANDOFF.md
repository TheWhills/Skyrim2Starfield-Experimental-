# Codex / Claude / Grok status

Owner: dasscooby. Goal: finish the verified interior slice before actor implementation.

## Goal and acceptance

Vault 111, Vault 81, Red Rocket cave, Vault 114, Prydwen, Hotel Rexford, Boston Public Library, Parsons: walkable floors/stairs, clear doorways, correct door swing/body ownership/frame collision, acceptable materials and recoverable deployment. Require in-game evidence tied to exact revision/artifact hashes. Unreadable results are inconclusive. Preserve Fallout 4 gameplay and Starfield native physics/modern capabilities. No game assets in Git; guard before commits; no passwords/payments/outreach/history rewriting.

Next: [actor milestone proposal](ACTOR-MILESTONE.md), #31. Planning only until interiors pass; assignments not yet acknowledged.

## Owners / locks

- Claude: collision/Havok (`sfcollision`, `fo4collision`, `hkpackfile`, `hktagfile`, `meshcollision`), `convert_static.py`, `pipeline.py`, `scripts/convert_batch.py`, `dotnet/PluginSpike`, game scripts/staging/live control. Do not overwrite active edits.
- Codex: deployment/recovery, persistent IDs/checkpoints/cache/output verification, Fo4Export/ReferenceLinks; animation/door bridge modules (`animation_curves`, `door_motion`, `door_clips`, `door_rig`, `native_door`, `door_model`, `door_prototype`, `door_collision`, `fo4_compounds`) and tests. Owns this status/archive. Shared `sfnif.py`: announce exact function before edits.
- Grok: acceptance oracle and `route_eval.judge` plausibility. No other game scripts/collision/doors/live control without a new claim.

## Current evidence / remaining work

Acceptance blocker (Grok8819a03/#32): prompt-recording runs have no hinged door OPEN-verified from both sides and no pinned eight-cell evidence. Older Rexford/Vault81 geometric pairs lack prompt verbs; not activation acceptance. Load-door pass/walk-through/fall-through fails. Different runs/builds must not be combined into one verified result.

Claude reported at56e3e37: Vault114 doors traversed after runner fixes; raised-door diagnosis withdrawn. Rexford:21 PASS/4 BLOCKED/1 UNREAD walks,8 stair passes. Vault81:2/3 stall doors traversed;19DA36 unresolved. Vault114 stairs:6 pass,2 stuck. Historical reports, not Codex validation or full slice acceptance.

Collision reported:3,012 native/243 source-none/199 box/36 surface boxes. Synthetic regression covers source-none without invented physics.

Claude b166d6c reports Parsons load door solid; teleport absent,9 models rebuilt with stable IDs. Codex:2 synthetic policy tests cover static collision routing/reporting and normal hinged control; historical swing reproduced. Runtime evidence belongs to Claude; reconcile later load failures against exact artifact hashes.

Door prototype:30 rigs/60 clips read back,42 selected source bodies/62 leaves; offline only, not installed, native moving linkage/activation still unverified. Collision ownership contract:14-byte target/flags/data/BodyID; shared systems select the body's node index, never every body per attachment.

`.af` samples: Open/Close sizes vary. Claude confirmed the second u16 at 0x28 matches named rig-bone counts in four families; frame rate and track mapping remain unknown. Details: research note and #32.

Codex:13 checkpoint/44 deploy tests; guard passes. Cache/resume validate success, inputs and hashes; a successful conversion whose dependency inventory fails now blocks batch verification. Deploy prevents overwrites, atomically rewrites/restores Plugins.txt, checks for concurrent edits during updates and recovery, preserves a config file created after uninstall's snapshot, validates manifest-owned plugin entries, preserves format/path, tracks published files, and limits uninstall to known artifacts. Recovery preserves changed/unproven files; legacy manifests may need manual cleanup. No live install changed.

## Coordination / housekeeping

Check #29-32 each session; publish concise evidence and blockers there. Keep this file <4KB. [History](handoff-archive/2026-10-07-codex-history.md).

Delete reviewed scratch/recordings; never commit recordings. Keep staging\multi. Inspect before cleaning Codex's staging\codex-resume-smoke and research\codex-reflect.
