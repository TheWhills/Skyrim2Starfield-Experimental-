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
   Needs SFSE and Address Library for SFSE Plugins matching the game version (pc_checklist step 0 prints both).
5. Optional add-on: `SFSE\Plugins\S2SClash.dll` + `SFSE\Plugins\S2SClash.ini` (weapon clash; needs S2SCombat). Put it in its own MO2 mod to switch it on / off.

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

## S2SDodge (standalone dodge, 2026-11-23)

`sfse/dodge` + `s2s/dodge_only.h`: the dodge alone, for a mod without the rest of S2SCombat. It runs the same
`combat::Controller` with every other system switched off (`dodge_only`: no attack buffer, power key, queued-power
cancel, stances, dual wield, timed block / parry) and carries out only the dodge's commands (`dodge_only_command`:
graph event, stamina cost, log), so the dodge behaves exactly as in S2SCombat. Hooks: UI input (watch only), the
player's animation events (Starfield 1.16 layout, no probe), menus; no player-controls hook, hit sink or lock-on.
It switches itself off when S2SCombat.dll is loaded (both would send the dodge event).

* Build: `xmake build S2SDodge` (not built by a plain `xmake`). INI: `S2SDodge.ini` (`[Plugin]` bEnabled,
  bGhostDuringIframes, sStaminaActorValue, log counts; `[Combat]` the dodge keys only).
* Animations: `scripts/armor/sam_dodge_pack.py --dll <S2SDodge.dll>` writes the whole mod (clips, graphs, SAM fragment,
  DLL + INI). Needs SFSE, Address Library and SAM.
* Status: core tested (tests/test_dodge_only.cpp); the DLL not yet compiled or run (owner's build).
* OSF Settings (optional, Nexus 18326, github.com/ozooma10/osf-settings, GPL-3.0): with it installed the dodge key is
  rebindable in Pause > Mod Settings > Keybindings. Schema `s2sdodge.osf.json` -> `SFSE\Plugins\OSF\Settings\schemas\
  s2sdodge.json` (sam_dodge_pack --dll copies it); at kPostLoad S2SDodge registers hotkey `s2sdodge/dodge` and the
  controller's dodge key becomes a sentinel fed by the hotkey callback, and the INI key no longer dodges (an INI gamepad
  button still does). Default "L Alt" (Starfield's name as the menu shows it; "LAlt" is not in its table: OSF Settings
  then leaves the hotkey out and S2SDodge falls back to the INI key). The service
  is declared in `dodge/OsfSettings.h` (ABI 1.0 slot order) instead of including the GPL SDK header.


## Left-hand copy test (2026-11-23)
First test of the runtime left-hand copy (docs/ai/decisions.md 2026-11-23; addresses, slots and Address Library IDs in
docs/re/findings.md on branch `claude/re-findings-ni-attach`). Code: `s2s/left_copy.h` (when to make / drop, the
NiCloningProcess bytes; tested in tests/test_left_copy.cpp) and `game::MakeLeftCopy` / `DropLeftCopy` in Game.cpp.

What a press of `iLeftCopyKey` (default 43, the `\` key) does with a weapon drawn, on the main thread:
1. finds `sLeftCopyWeaponNode` ("Weapon") in the player's 3D and picks the drawn weapon's model among its children:
   `sLeftCopyModel` if set, else the first child not in `sLeftCopySkip` (the hand IK helpers R_HandIk / L_HandIk;
   first run 2026-11-23 copied R_HandIk: attach and detach worked, nothing visible). The log line lists the node's
   subtree;
2. finds the first of `sLeftCopyNodes` ("WeaponLeft", then "L_Wrist"; found: WeaponLeft) in the same walk;
3. checks that the left node's vtable slots 84 / 87 are NiNode's AttachChild / DetachChild (Address Library 147173 /
   147177); if not, it stops there and logs both addresses;
4. clones the model as the engine does (a 0x38-byte NiCloningProcess, CreateClone slot 41, ProcessClone slot 47),
   frees the cloning process the engine's way, and attaches the copy with AttachChild(copy, true).
The same key, a sheathe, an unequip, or the loading screen opening takes the copy off again (DetachChild, slot 87).
Every step logs a `left copy:` line (node names, flags, child counts, timings).

What to look for: does a second weapon show at the left hand; does it follow the hand while moving and attacking;
does it vanish on the second press / sheathe; any crash (the last `left copy:` line tells where). Skinned weapon parts
may stay at the right hand (their bones were bound to the right-hand weapon; findings.md section 3, step 7).

Owner's run 2026-11-23 (second build, screenshots + log), **verified**: the copy works. The weapon node's subtree is
`Weapon > R_HandIk, L_HandIk, Weapon > Cutlass > Cutlass:0, ProjectileNode, Cutlass_Decals:0`; the test copied the
inner `Weapon` (the model root) and the whole cutlass, glow included, showed in the left hand and moved with it.
Sheathing dropped it by itself; three make / drop pairs, no crash. A press before the weapon is in the hand fails
cleanly ("no model child"). Open: the copy flips between the right angle and pointing outward (it keeps the right
weapon's local transform under WeaponLeft, and the one-handed clips do not pose the left hand or WeaponLeft for a
weapon); the left hand does not grip (no dual moveset: S2SWeapons.esm not loaded); the lookup costs 550-590 ms (a
memory check per node in the walk).

Third build (2026-11-23): while a copy is on the dual moveset switches on (`bLeftCopyDual`, the same S2S_StanceDual
keyword as the worn left blade; no S2SWeapons.esm needed) and back off when it goes. The copy's orientation:
`iLeftCopyTurn` (one of the 24 right-angle orientations, s2s/left_copy.h turn()) then `sLeftCopyRotation` (x y z
degrees), written into the copy's local transform after the attach; `iLeftCopyTurnKey` (39 = ;) steps through the 24
live and logs the number. The weapon node and the left node are remembered per player 3D (checked before use), so
only the first press walks the 3D.

Owner's run 2026-11-23 (third build): the dual stance came on with the copy (verified: `dual wield: left blade worn
(left-hand copy) -> stance S2S_StanceDual`), but under WeaponLeft the copy faced outward in turns (the vanilla turn /
idle clips leave WeaponLeft away from the hand, as with the worn blade on 2026-10-26). Fourth build: the copy hangs
under L_Wrist (`sLeftCopyNodes = L_Wrist, WeaponLeft`) held at WeaponLeft's rest grip (`sLeftCopyGripNode`,
s2s left_grip() = skyrimweapon.left_grip_metres(), tests/test_left_copy_grip.py), so it stays in the hand in every
clip, as the worn blade. Also fixed: an attack-key release whose press came in a menu (inventory / console clicks) was
taken as a minutes-long hold and sent MeleeAttackPowerStart into the graph (the same log: 3 sends with menus open).

Owner's run 2026-11-23 (fourth build): the copy hung under L_Wrist at the grip, dual stance on, cached lookup 11 ms,
no power attack sent from menus. But the right weapon stopped showing, the copy floated away from the hand, and the
turn key changed nothing visible (the HUD showed "Left copy turn 5"). Supported hypothesis: the copy's root was named
"Weapon" like the skeleton bone, and the stance re-equip right after each copy found the attach node by name (`Prn`)
and hung the real cutlass into the copy. Fifth build: every node of the copy is renamed `S2SL_<name>` before the
attach, and every 2 s while a copy is on the log has a `left copy where:` line (the copy's world against its parent's
world times our local: shows whether our local drives it). The "power attack when you stop" is the graph's own: an
AttackStart 0.45 s after AttackStateNextAttack with no click and nothing sent by the plugin (its only events in that
log were MeleeAttack02, the back dodge).

Owner's run 2026-11-23 (fifth build): right weapon back (the rename worked), copy 0.079 m from L_Wrist (= the grip
offset: our translation is used) but at the wrong angle in every clip, and the `left copy where:` rotation never matched
our compose(). Ghidra (NiAVObject world update 0x142bd5000 -> 0x140316a50): world = local * parent in the row-vector
convention, i.e. the stored rows are our columns; the grip rotation had been written transposed (its inverse). Under
WeaponLeft in builds 2-3 this did not show (the local was the identity, and the dual clips pose WeaponLeft as the left
weapon's frame; only the vanilla turns, which leave WeaponLeft at rest, went wrong). Sixth build: ReadXform /
WriteXform go through xform store_engine / load_engine (tested against the engine's own compose).

