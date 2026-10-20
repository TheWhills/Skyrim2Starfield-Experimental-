# Lock-on for Starfield melee: what True Directional Movement does, and our design

Owner request (2026-10-20): TDM-style lock-on, eventually. Read from TDM 2.3.1's source
(github.com/ersh1/TrueDirectionalMovement, commit 57b913a, 2026-09-01) for behaviour only. TDM is
**GPL-3.0-or-later with a modding exception and a GPL linking exception**: nothing of it is copied here or into our
plugin; this file describes behaviour in our own words, and the numbers are its user-facing defaults (tuning starting
points). Starfield-side facts come from libxse/commonlibsf (commit 9d090c4, 2026-10-06; GPL-3.0 with the same kind of
exceptions; read only).

## What TDM's lock-on does (verified from the source)

**Turning it on.** One key toggles it (default: middle mouse; optionally holding the POV key). Not during dialogue.
The first target is chosen as:
1. the actor under the crosshair, if it is a valid target;
2. otherwise the best of the "high process" actors (the ones near the player the engine fully simulates), scored by
   distance (automatic re-lock), or by distance x (1 - cos(angle from the camera's forward)) when the player pressed
   the key (favours what you are looking at without ignoring distance).

**Valid target:** a character (not the player, not the player's mount), alive, not an essential actor in bleedout,
within the lock distance (default 2000 units, about 28.6 m; x2 for large races, x4 for extra large), not invisible,
hostile to the player (option), and in line of sight.

**Keeping it.** Every frame the lock drops when: the target dies, is disabled or unloaded, goes past the distance
x 1.05 (hysteresis, so it does not flicker at the edge), turns invisible, dialogue starts, VATS starts, or line of
sight has been lost for more than 2 s. Optionally the next target is picked when one dies.

**Switching.** Mouse flick (sensitivity setting), scroll wheel, right stick, or optional keys. A switch in a
direction first tries another **target point on the same actor** (per-race bone lists from TOML files; default is
the torso or head body-part node), then another actor: every valid actor is projected to the screen, only those on
the requested side count, and the score is screen distance x (2 - alignment with the requested direction), so a
target roughly in that direction beats a closer one off to the side. A 0.25 s cooldown per direction stops repeats.

**While locked.**
* The character turns to face the target (except while sprinting or dodging, and not when only head tracking would
  do: no input, not attacking or blocking, target within 45 degrees).
* The camera is turned toward the target every frame with exponential smoothing (default yaw speed 8, pitch speed
  2), aiming at a point lowered by distance x 0.25 so the target sits in the upper half of the screen, kept at least
  35 units above the ground outdoors. An option swings the camera behind the target.
* "Relaxed" mode: the camera stays free and only follows when the target nears the screen edge (15 % margin).
* Crosshair hidden; a reticle widget over the target point (through TrueHUD).
* Projectiles: predictive aim from the target's velocity, or homing, or none.
* It tells other mods: graph variable `TDM_TargetLock` (bool) and a spell on the player that conditions can test
  (LoreRim's 19 folders test that effect).

**Attack phases (used by lock-on and by its directional movement).** It listens to animation events and keeps an
attack phase (none / start / mid / end) from the clips' own markers: start on preHitFrame, CastOKStart,
MCO_AttackInitiate, MCO_InputBuffer, TDM_AttackStart, Collision_AttackStart; mid on weaponSwing, TDM_AttackMid,
Collision_Add; end on HitFrame, MCO_WinOpen, MCO_Recovery, BFCO_NextWinStart, BFCO_DIY_recovery, TDM_AttackEnd;
none on attackStop, MCO_WinClose, BFCO_DIY_EndLoop. The turn speed toward the target is scaled per phase (fast in
the wind-up, slow in the swing, locked at the end), which is why locked-on attacks still track a moving enemy but
cannot spin mid-swing. Without a lock, "melee magnetism" does the same toward the closest valid actor within 250
units and a cone around the facing direction.

**Hooks it needs in Skyrim:** movement and look input handlers (to read and rewrite stick / mouse input), the
third-person camera state (its free-rotation yaw / pitch), player update, the animation-graph event sink, rotation
setters (to scale turn speed), head tracking, projectile launch (aim help), and the HUD.

## Starfield: what exists (CommonLibSF, verified in its headers) and what does not

| Need | Starfield / CommonLibSF | Status |
|---|---|---|
| Nearby actors | `ProcessLists::highActorHandles` | available |
| Hostility | `Actor` hostility functions | available |
| Animation events in, events out | `BSAnimationGraphEvent` sink on references; `NotifyAnimationGraphImpl`; graph variable getters | available (graph variable *setters* not in the header yet) |
| Camera | `PlayerCamera` singleton, `CameraState::kThirdPerson` | singleton available; the third-person state's layout (its yaw / pitch offsets) is **not reverse engineered** in CommonLibSF yet |
| World to screen (switching by side) | `NiCamera` world-to-screen | available |
| Input | look / movement handler vtables listed by ID only | needs reverse engineering, or read input another way |
| Line of sight | not in the headers | needs finding (or our own ray cast) |
| **Melee steering toward a target** | **`BGSMeleeAimAssistModel` (form type MAAM)**: outer / inner cone angle, steering degrees per second, snap steering multipliers for the outer / inner ring, max distance, enabled | **built into the game, data-driven** |

The last row is the important find: Starfield already has TDM's "melee magnetism" as a record type, and the vanilla
melee descriptors set `bAlignWithAimAssistTarget` on about 50 clips (see animation-port.md). So the swing-tracking
part of lock-on is partly built in.

## Design (ours)

Order: the plugin core first (input table, payload commands, i-frames, dodge), then:

1. **No plugin: tune melee aim assist.** Read the vanilla MAAM records and which weapons use them (extend
   weapon_anim_survey.py), then a plugin record override with wider cones / faster steering for the converted
   weapons. Gives "soft lock" (attacks curve onto the nearest enemy) and tells us how far the built-in steering goes.
2. **Lock-on module in the combat plugin.**
   * Target choice and validity as above (crosshair actor first, then the distance x angle score; same validity
     list; distance hysteresis; 2 s line-of-sight grace). Our own code.
   * Lock state exposed the same two ways TDM does: graph variable `TDM_TargetLock` (same name, so converted
     movesets' conditions need no edits) and a keyword or effect on the player.
   * Facing: feed the locked target to Starfield's melee aim assist / align-with-target path if it can be pointed at
     a chosen actor; otherwise turn the player ourselves with per-phase turn speeds from the attack phase tracker
     (the same marker list as above, which our converted clips already carry in their .afx events).
   * Camera: needs the third-person state's yaw / pitch offsets found first (OSF Animation already drives
     Starfield's camera from SFSE; its approach is the first place to look). Smoothing and offsets as TDM's
     defaults, then tuned.
   * Switching: mouse flick / scroll / stick through the input layer; screen-side scoring as above.
   * Reticle: an effect shader or art object on the target first; a HUD widget later.
3. **Later:** directional movement (body turns to the movement direction), relaxed mode, lock behind target,
   projectile aim help once bows / spells exist.

Open questions (to test in game): does Starfield's aim assist accept a target we choose; is the weapon-drawn
third-person body already turned by the camera (so a camera lock alone turns the player); what MAAM values vanilla
melee weapons use.
