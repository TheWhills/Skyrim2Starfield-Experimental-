# Combat SFSE plugin: specification

One plugin brings Skyrim's modded melee combat to Starfield. Its game-independent logic is `native/combat`
(C++20, tested here); the SFSE side translates game input / events into it and its decisions back into the game.
Labels: **verified** (seen in files or in game), **supported** (strong evidence), **unresolved** (to test).
Sources: animation-port.md (dated entries), lock-on-design.md, the owner's mods (format only; no mod code is used).

## Why a plugin at all
Papyrus cannot read keys and runs late (a hit's type would be known one hit late); new animation tags / files are not
found without the animation caches (Creation Kit check pending: pc_checklist.ps1 step 1). Everything below that needs
input, frame timing or damage rules needs SFSE.

## Modules

| Module | Does | Core (native/combat) | Game side needs | Status |
|---|---|---|---|---|
| Input table | key / held direction -> action (graph event, graph variable, keyword toggle, dodge, lock, switch) from an INI section, like Key Utils / Stances (arrows = stances) | `parse_bindings`, `Controller::on_key` | keyboard / mouse / gamepad hook; actor keyword add / remove; graph event / variable set | core done; game side drafted |
| Payload commands | runs Payload Interpreter instructions found in clip events: SGVB / SGVI / SGVF (graph variables; MCO routing and attack speed), CAST, APPLYSPELL / UNAPPLYSPELL, CAMSHAKE, SETGHOST, PLAYPARTICLE; `$name` custom commands from INI files; typo `SVGF` ignored as in Skyrim | `parse_payload`, `as_variable_set`, `Controller::on_anim_event` | animation-graph event sink on the player (and NPCs); spells, camera shake, particles | parser done; SGV* drafted (Papyrus) |
| Attack phase | none / start / mid / end from MCO / BFCO / Precision / vanilla markers (preHitFrame, weaponSwing, HitFrame, MCO_WinOpen, MCO_WinClose, ...); turn speed per phase (fast wind-up, slow swing, locked end) | `AttackPhaseTracker` | event sink; player turn-rate hook | core done |
| Input buffer | presses remembered 0.35 s and fired when the next window opens; hold >= 0.3 s = power attack, >= 0.8 s = charged (MCO intro / loop / outro) | `InputBuffer`, `Controller` (only presses in a closed window during an attack are kept; the game handles the rest) | attack input hook; send MeleeAttackStart / MeleeAttackPowerStart / charge events | core done; game side drafted (no charged states yet) |
| Dodge | TK Dodge behaviour: direction from movement input (4 or 8 way; standing = back), stamina cost, may cancel attacks; sends TKDodgeForward / Back / Left / Right (+ diagonals) so ported clips and graphs keep their names | `dodge_direction`, `dodge_event`, `can_dodge`, `Controller` | dodge key; stamina (Starfield: O2? owner decides); graph states for the dodge clips (new tags: cache route or plugin) | core done; clips convert (motion data reader); game side drafted |
| I-frames | invulnerability windows from clip events (start + duration, or start / end pairs) and from the dodge; hits during a window are ignored (a hit hook, not a ghost flag) | `IFrames` | damage / hit hook | core done; draft uses Actor.SetGhost meanwhile |
| Block hits | before the block reaction plays, set a graph variable for the hit type: normal / power attack / near guard-break (Dynamic Block Hit's NA / PA / ST) so variants can be picked; guard break = Starfield's stagger clips | (variable set) | hit-while-blocking hook | design |
| Lock-on | TDM behaviour: crosshair actor first, then distance x angle score; validity (alive, hostile, line of sight, 2000 units x size, hysteresis 1.05, 2 s sight grace); switching by screen side with a 0.25 s cooldown; graph variable `TDM_TargetLock` so movesets' conditions port; camera follow; target marker | `LockOn` | actor list, line of sight, world-to-screen, third-person camera yaw / pitch (not yet mapped in CommonLibSF), melee aim assist target | core done; camera unresolved |
| Stances | four clip sets switched by keys: an actor keyword per stance whose HumanRace animation entry lists that stance's folder first | (input table) | keyword toggle; re-evaluate the weapon's animation set while drawn (**unresolved**) | design |
| Slots (fallback) | if the Creation Kit cannot rebuild the animation caches: let the graph find new tags / files | - | engine research | only if needed |
| NPCs | movesets for NPCs (SCAR-style action data: distance, angle, chance) | later | AI combat hooks | later |

## Data the plugin reads (verified formats)
* Clip events (Skyrim annotations; the converter keeps these in `<clip>.events.json` so far, writing them into the
  .afx is pending): MCO_WinOpen / WinClose /
  PowerWinOpen / PowerWinClose / Recovery / TransitionOpen / ChargedAttack, BFCO_NextWinStart / NextPowerWinStart /
  DIY_recovery / DIY_EndLoop, `PIE.@...` payloads, Collision_* (Precision; optional), TKDR_* (dodge / i-frames).
* INI: `[Keys]` bindings (`name = key|action|argument`, keys as DirectInput scan codes like Key Utils: 200 up, 203
  left, 208 down, 205 right, 56 left Alt; 0x100+ mouse), dodge / lock-on / i-frame settings (defaults below),
  `$name` custom payload definitions.

## Defaults (starting points, from the Skyrim mods' defaults)
Dodge: 4-way, idle = back, stamina 10, attack cancel on, i-frames 0.3 s. Input: buffer 0.35 s, power 0.30 s, charge
0.80 s. Lock-on: 2000 units, hysteresis 1.05, sight grace 2 s, hostile only, switch cooldown 0.25 s, camera yaw speed
8 / pitch speed 2, pitch offset 0.25 x distance. Turn multipliers by phase: none 1, start 1, mid 0.25, end 0.

## Build and test
* Core: `cmake -S native/combat -B build && cmake --build build && ctest --test-dir build` (any OS; run by
  tests/test_native_combat.py; also clean under ASan / UBSan with gcc and clang, 2026-10-20).
* Controller (`include/s2s/controller.h`): the per-player glue logic, also game-independent and tested
  (tests/test_controller.cpp): keys / animation events / ticks in, commands out (send event, set variable, add /
  remove keyword, spend stamina, lock-on, log); INI parsing (`[Combat]`, `[Keys]`); Starfield VK / mouse codes ->
  Key Utils codes.
* SFSE plugin (`native/combat/sfse`, first draft 2026-10-20): Windows, Visual Studio 2022 Build Tools + xmake +
  CommonLibSF (submodule pinned to the commit checked against) + Address Library for SFSE; built on the owner's PC
  (Microsoft downloads are blocked from the cloud workspace; pc_checklist.ps1 step 7 builds it when xmake is
  installed). Checked here only as a syntax-only compile against CommonLibSF's headers (clang, MinGW target, layout
  asserts off). Hook points, the animation-event layout and the Papyrus names it relies on are listed in
  `sfse/README.md` with what the first run's log answers.

## Order
1. Input table + payload commands + attack phase (no new animations needed: works with the converted movesets).
2. Input buffer and charged attacks.
3. Dodge + i-frames (needs dodge states in the graph).
4. Block-hit types.
5. Lock-on (after the camera is mapped).
6. Stances (after the stance-folder test), NPCs.
