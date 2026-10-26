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
| Player animation events | replaces ProcessEvent of the player's BSTEventSink<BSAnimationGraphEvent> (+0x50) | hook works (owner's first run); Skyrim's layout (holder, tag, payload) did **not** hold. Now found at run time: the first events' 8 slots are classified with memory checks and logged (`anim probe:`), `combat::LayoutProbe` (tested) settles on the tag / payload slots, logged as `animation event layout found` |
| Send graph events | `NotifyAnimationGraphImpl` (CommonLibSF) | mapped; result logged at debug level |
| Set graph variables (Payload Interpreter SGVB / SGVI / SGVF, int / bool / float bindings) | Papyrus `ObjectReference.SetAnimationVariable*` through the VM (queued: a frame or two late) | native names unverified |
| Stances | arrow keys -> Papyrus `AddKeyword` / `RemoveKeyword` on S2SStances.esm's keywords (scripts/armor/stance_plugin.py, checklist step 8); every press clears the other stance keywords (they persist in saves); optional `sStanceRefreshEvents` | unverified; animation set re-evaluation while drawn unresolved |
| Hits on the player | **off on Starfield 1.16**: CommonLibSF has no Address Library ID for `TESHitEvent::GetEventSource` yet (ID 0; calling it stopped the game at load, owner's first run 2026-10-21). Guarded at compile time; switches on by itself once CommonLibSF maps it. Until then: TESHitEvent sink (mapped in CommonLibSF; after the game handled the hit, so it cannot cancel damage); attack event name read from the attack data with memory checks (Fallout 4 layout guess) | event mapped; attack-data layout unverified |
| Block-hit types | on a hit while `iWantBlock` (the melee graph's own block variable) is set: `iS2SBlockHitType` = 0 normal / 1 power | variable set; no graph variants use it yet |
| I-frames | `Actor.SetGhost` while the controller's i-frames run (until a hit hook exists) | unverified |
| Dodge cost | optional actor value (`sStaminaActorValue`) | owner decision |
| Lock-on | middle mouse / right stick click; targets from the high-process actor list (alive, within `fMaxDistance`; hostile only when CommonLibSF maps `Actor::IsHostileToActor`, ID 0 on 1.16: until then any living actor), chosen and switched by the core; each frame the player's angle (OBJ_REFR angle z / x) is steered toward the target and the third-person camera follows it; graph bool `TDM_TargetLock` | angle convention, units (metres?) and "camera follows heading" unverified; no line-of-sight test yet; mouse look still adds on top |

Everything the game side does runs on the main thread through SFSE's task interface; animation events (which may come
from animation threads) only feed the controller under a lock.

## Build (Windows)
1. Visual Studio 2022 Build Tools (C++ workload) and xmake 3 (`winget install xmake`).
2. From the repo: `git submodule update --init --recursive` (CommonLibSF at `native/combat/sfse/lib/commonlibsf`, pinned
   to the commit the draft was checked against).
3. `cd native\combat\sfse`, `xmake f -m releasedbg`, `xmake`. The DLL lands in `build\windows\x64\releasedbg\`.
4. Mod folder for MO2: `SFSE\Plugins\S2SCombat.dll` + `SFSE\Plugins\S2SCombat.ini` (this folder's INI).
5. Optional add-on: `SFSE\Plugins\S2SClash.dll` + `SFSE\Plugins\S2SClash.ini` (weapon clash; needs S2SCombat). Put it in its own MO2 mod to switch it on / off.
   Needs SFSE and Address Library for SFSE Plugins matching the game version (pc_checklist step 0 prints both).

Compile errors are expected in a first MSVC build (the check here could not see MSVC-only issues); fix and note them.

## First run: what the log answers
Log: `Documents\My Games\Starfield\SFSE\Logs\S2SCombat.log`.
1. `hooks installed` line: both hooks found their objects.
2. `key:` lines: press and release W, Alt, left mouse, an arrow key, and a gamepad button. Check that each press logs
   `down` and each release `up` once, the codes (17, 56, 256, 200, 266+), and note the `user event` names (Starfield's
   input names: useful later).
3. `anim probe:` lines, then `animation event layout found: tag +.., payload ..` (or `animation events switched
   off: ...` when no slot held a readable name: the plugin stops reading events instead of crashing; send the log).
   `menu:` lines: open the inventory, the console and the pause menu once; key presses are ignored while those are
   open (the names checked are in `sBlockingMenus`; the log shows Starfield's real names to correct the list).
4. `anim event:` lines: draw a melee weapon and swing. Readable names (WeaponDraw, PreHitFrame, WeaponSwing,
   HitFrame, AttackEnd, FootLeft ...) confirm the event layout; garbage or a crash on the first swing means the layout
   guess is wrong: set `iLogAnimEvents = 0` and `bEnabled = 0`, report the log.
5. `hit on player:` lines: let an enemy hit you a few times, blocking and not, and once during a dodge. The attack
   event names show whether normal and power attacks can be told apart; a hit "during i-frames" means the interim
   ghost does not stop hits.
6. Lock-on: draw a weapon near an enemy, click the middle mouse button. `lock-on: target ...` and a distance line
   (should read like metres); the view should swing to the enemy and follow it. If it tilts away vertically, set
   `fPitchSign = -1`; if it turns the wrong way sideways or not at all, send the log.
7. With a converted moveset whose clips carry MCO / PIE events: `variable` / `payload not handled yet` lines.
8. Alt while standing: `dodge` sends TKDodgeBack (nothing visible until the graph has dodge states: `send ... not
   taken by the graph` at debug level is the expected answer today).

## Owner's runs (2026-10-21)
**Verified in game (Starfield 1.16.244, CommonLibSF 9d090c4):**
- Loads with the two unmapped calls guarded (hit events, IsHostileToActor); both hooks install.
- Input: press and release both seen (`value 1 / held 0` down, `value 0 / held > 0` up) for keyboard and mouse;
  codes as expected (W 17, arrows 200 / 203 / 205 / 208, left mouse 256, wheel 265). Alt (56) logs down only, never up.
  Starfield user events seen: Forward, Sprint, Sneak, Melee, PrimaryAttack, QuickInventory, Console, Accept, Cancel,
  Up / Down (in menus), ZoomOut.
- Menu names: MainMenu, LoadingMenu, FaderMenu, HUDMenu, HUDMessagesMenu, Console, CursorMenu, MessageBoxMenu,
  DataMenu, InventoryMenu: all blocking ones are already in the default list; CursorMenu is not blocking.
- **BSAnimationGraphEvent in Starfield: tag at +0x08, payload at +0x10** (BSFixedStrings). +0x00 is not the holder
  (a value such as 100000001 or a pointer that is not the player). One probe line showed two events back to back,
  0x20 apart, so the event is probably 0x20 bytes, with +0x18 an id-like value (80000457).
- Player graph events seen with the LoreRim sword pack: BeginWeaponDraw, weaponDraw, BeginWeaponSheathe, weaponSheathe,
  UnequipComplete, ReevaluateGraphState, RelaxedStart, FootLeft / FootRight, SoundPlay (payload: sound name),
  IdleFlavor, JiggleEvaluate, StartMotionDriven, StartAnimationDriven, StartAllowRotation, AttackStart, preHitFrame,
  weaponSwing, HitFrame, CameraShake (payload "0.85,0.1,0.2"), AttackStateNextAttack, MeleeAttackStart, attackStop,
  AttackEnd (payload a time, "0.193").
- The MCO-style buffer works: a click during an attack logs `attack buffered`, then the next attack starts at
  AttackStateNextAttack (MeleeAttackStart, AttackStart). Holding the attack logs the charged-hold message.
