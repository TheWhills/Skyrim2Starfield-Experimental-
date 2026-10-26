// Thin wrappers over the game for the commands the controller issues. Everything that depends on an unverified game
// detail is here or in Hooks.cpp, marked "UNVERIFIED" with what to check on the PC (sfse/README.md, "First run").
#pragma once

#include "s2s/combat.h"

namespace s2s::sfse::game {

double Now();
bool Readable(const void* ptr, std::size_t bytes);   // committed, readable memory (VirtualQuery)                                    // seconds, steady clock
RE::PlayerCharacter* Player();

// Must run on the main thread (Plugin queues them through SFSE's task interface).
bool SendEvent(std::string_view name);           // player's animation graph
bool GetVariable(std::string_view name, float& out);
bool SetVariable(const combat::VariableSet& v);  // false: not dispatched. Papyrus ObjectReference.SetAnimationVariable* (queued by the VM)
bool SetKeyword(std::string_view editor_id, bool add);   // false: keyword not found / not dispatched
bool SetGhost(bool ghost);
// Stance re-equip (Papyrus, asynchronous; report(text) runs on the VM thread): UnequipWeapon takes the weapon off and
// remembers it, EquipWeapon puts that weapon back on.
bool UnequipWeapon(std::function<void(const std::string&)> report = {});
bool EquipWeapon(std::function<void(const std::string&)> report = {});
int HasKeyword(std::string_view editor_id);     // 1 / 0, -1 when the keyword is not found
float ActorValue(std::string_view editor_id);    // < 0 when the value is not found
float PlayerHealth();                            // < 0 when not known (cached lookup: called every frame)
// Graph events (comma separated) for the actor with this form ID, tried in order until its graph takes one; returns
// what happened for the log.
std::string SendActorEvents(std::uint32_t form_id, std::string_view events);
bool Notify(std::string_view text);              // Debug.Notification (Papyrus, queued)
bool ShakeCamera(float strength, float seconds); // Game.ShakeCamera(None, ...) (Papyrus, queued)
// ObjectReference.PlayImpactEffect on the player: the ImpactDataSet `editor_id` from `node`, picked toward the actor
// `toward` (form ID; 0 = straight ahead). Returns what happened, for the log.
std::string PlayImpactToward(std::string_view editor_id, std::string_view node, std::uint32_t toward, bool down = false,
                             const std::vector<std::string>& extra_sets = {});
const std::vector<std::uint32_t>& ImpactSetIds();
void CleanupEffects();                           // deletes placed effect objects whose time is up (each tick)
bool DeferKill(bool on);                         // Actor.StartDeferredKill / EndDeferredKill on the player (Papyrus)   // every impact data set's form ID (after ListSparkForms)
// Once: logs the impact data sets / explosions whose EditorID looks like sparks (combat::spark_score) and returns the
// best impact set's EditorID ("" if none).
std::string ListSparkForms();
void DamageActorValue(std::string_view editor_id, float amount);

// Weapon clash (s2s/clash.h). ClashCheck: "" when the actor may clash (an actor, alive, within max_distance), else why
// not. The rest are Papyrus calls on that actor (queued), returning whether they were dispatched / what happened.
std::string ClashCheck(std::uint32_t form_id, float max_distance);
std::string PlaceFacing(std::uint32_t form_id, float distance);
bool SetRestrained(std::uint32_t form_id, bool on);
// Turns the player and the actor to face each other (their headings, data.angle.z, written directly; main thread).
// Owner's screenshots 2026-10-26: the player kept facing the camera's way, 35 deg off the opponent, blades not crossed.
void FaceEachOther(std::uint32_t form_id);
bool SetActorVariable(std::uint32_t form_id, const combat::VariableSet& v);

}  // namespace s2s::sfse::game
