# S2SCombat: the Starfield side of the combat plugin

First draft (2026-10-20), written away from the PC: it builds against CommonLibSF's headers in a syntax-only check
(clang, MinGW target, layout asserts off), not yet with MSVC and not yet run in the game. Behaviour lives in the
tested core (`../include/s2s/controller.h`, `../src`); this folder only translates between the game and the core.
Spec: `docs/armor/combat-plugin-spec.md`.

## What the draft does
| Part | How | Status |
|---|---|---|
| Key / button input | hooks UI's input receiver (`PerformInputProcessing`, vtable read from the live UI object); keyboard VK -> scan code, mouse, gamepad (SFSE InputMap) | hook point supported (OSF Animation uses it); press / release convention unverified |
| Left stick | ThumbstickEvent raw layout (+0x30 id, +0x38 x, +0x3C y) | supported (OSF's in-game notes); sign of y unverified |
| Player animation events | replaces ProcessEvent of the player's BSTEventSink<BSAnimationGraphEvent> (+0x50) | event layout (holder, tag, payload) unverified |
| Send graph events | `NotifyAnimationGraphImpl` (CommonLibSF) | mapped; result logged at debug level |
| Set graph variables (Payload Interpreter SGVB / SGVI / SGVF, int / bool / float bindings) | Papyrus `ObjectReference.SetAnimationVariable*` through the VM (queued: a frame or two late) | native names unverified |
| Stances | arrow keys -> Papyrus `AddKeyword` / `RemoveKeyword` on S2SStances.esm's keywords (scripts/armor/stance_plugin.py, checklist step 8); every press clears the other stance keywords (they persist in saves); optional `sStanceRefreshEvents` | unverified; animation set re-evaluation while drawn unresolved |
| I-frames | `Actor.SetGhost` while the controller's i-frames run (until a hit hook exists) | unverified |
| Dodge cost | optional actor value (`sStaminaActorValue`) | owner decision |
| Lock-on | not wired (camera not mapped); logs the key presses | later |

Everything the game side does runs on the main thread through SFSE's task interface; animation events (which may come
from animation threads) only feed the controller under a lock.

## Build (Windows)
1. Visual Studio 2022 Build Tools (C++ workload) and xmake 3 (`winget install xmake`).
2. From the repo: `git submodule update --init --recursive` (CommonLibSF at `native/combat/sfse/lib/commonlibsf`, pinned
   to the commit the draft was checked against).
3. `cd native\combat\sfse`, `xmake f -m releasedbg`, `xmake`. The DLL lands in `build\windows\x64\releasedbg\`.
4. Mod folder for MO2: `SFSE\Plugins\S2SCombat.dll` + `SFSE\Plugins\S2SCombat.ini` (this folder's INI).
   Needs SFSE and Address Library for SFSE Plugins matching the game version (pc_checklist step 0 prints both).

Compile errors are expected in a first MSVC build (the check here could not see MSVC-only issues); fix and note them.

## First run: what the log answers
Log: `Documents\My Games\Starfield\SFSE\Logs\S2SCombat.log`.
1. `hooks installed` line: both hooks found their objects.
2. `key:` lines: press and release W, Alt, left mouse, an arrow key, and a gamepad button. Check that each press logs
   `down` and each release `up` once, the codes (17, 56, 256, 200, 266+), and note the `user event` names (Starfield's
   input names: useful later).
3. `anim event:` lines: draw a melee weapon and swing. Readable names (WeaponDraw, PreHitFrame, WeaponSwing,
   HitFrame, AttackEnd, FootLeft ...) confirm the event layout; garbage or a crash on the first swing means the layout
   guess is wrong: set `iLogAnimEvents = 0` and `bEnabled = 0`, report the log.
4. With a converted moveset whose clips carry MCO / PIE events: `variable` / `payload not handled yet` lines.
5. Alt while standing: `dodge` sends TKDodgeBack (nothing visible until the graph has dodge states: `send ... not
   taken by the graph` at debug level is the expected answer today).
