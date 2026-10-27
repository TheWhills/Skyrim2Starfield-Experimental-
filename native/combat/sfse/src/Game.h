// Thin wrappers over the game for the commands the controller issues. Everything that depends on an unverified game
// detail is here or in Hooks.cpp, marked "UNVERIFIED" with what to check on the PC (sfse/README.md, "First run").
#pragma once

#include "s2s/combat.h"

namespace s2s::sfse::game {

double Now();
bool Readable(const void* ptr, std::size_t bytes);   // committed, readable memory (VirtualQuery)                                    // seconds, steady clock
RE::PlayerCharacter* Player();
// True while the plugin itself sends a graph event on this thread (SendEvent / SendActorEvents): the clash's event
// filter (Hooks.cpp) lets those through.
bool SendingOwnEvent();

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
// Papyrus Actor.WornHasKeyword on the player (FO4 / Skyrim name; supported): result(worn) on the VM thread. -1 = no
// keyword with that EditorID (the plugin that adds it is not loaded), 0 = not dispatched, 1 = asked.
int WornHasKeyword(std::string_view editor_id, std::function<void(bool)> result);
// Papyrus Actor.IsWeaponDrawn on the player (supported name): result(drawn) on the VM thread.
bool IsWeaponDrawn(std::function<void(bool)> result);
// The player's 3D (loadedData's data3D; CommonLibSF layout, memory-checked): every node's name under it, one per line
// ("<depth spaces><name> flags <hex>"), at most max_nodes. For finding the left blade's node.
std::string DumpPlayer3D(int max_nodes);
// Where the skeleton keeps its bones (they are not child nodes on 1.16): rigRoot's memory, and every place within two
// pointer hops of it holding the pooled "L_Wrist" / "R_Wrist" / "WEAPON" / "COM" / "Root" strings, with the floats
// around the first L_Wrist (its transforms, to be read), the weapon node's transforms and the player's position.
std::string DumpBoneSearch();
// The pair weapon's left blade: the node `node_name` of the player's 3D put onto the bone `bone_name` (its local
// transform from the parent's and the bone's world transforms; main thread, every frame). 1 = moved, 0 = a node not
// found (looked for again after 1 s), -1 no 3D, -2 no child list.
int FollowBone(std::string_view node_name, std::string_view bone_name);
void InvalidateBoneFollow();                     // the 3D may be rebuilt (equip, menu, load): look the nodes up again
std::string BoneFollowReport();                  // read-backs and time since the last report
// Dual wield's left blade (s2s/left_blade.h). ArmorsBesideKeyword: the ARMO forms of the plugin file that defines the
// keyword (S2SWeapons.esm: its ARMOs are the left blades). IsEquipped / ItemCount: Papyrus Actor.IsEquipped /
// ObjectReference.GetItemCount on the player, result on the VM thread. EquipForm: the native equip / unequip of a base
// form on the player (main thread; as the stance re-equip).
std::vector<std::uint32_t> ArmorsBesideKeyword(std::string_view editor_id);
bool IsEquipped(std::uint32_t form_id, std::function<void(bool)> result);
// Papyrus: the right-hand weapon's base form has the keyword (Actor.GetEquippedWeapon, then Form.HasKeyword on it).
// WornHasKeyword alone loses the pair weapon's keyword after the stance re-equip (equipped without instance data).
bool EquippedWeaponHasKeyword(std::string_view editor_id, std::function<void(bool)> result);
bool ItemCount(std::uint32_t form_id, std::function<void(int)> result);
bool EquipForm(std::uint32_t form_id, bool equip);
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
// Command::Kind::Guard: "" when the actor's guard is already up (bIsBlocking), else what was sent.
std::string GuardActor(std::uint32_t form_id, std::string_view guard_events, std::string_view interrupt_events);
bool SetActorVariable(std::uint32_t form_id, const combat::VariableSet& v);

}  // namespace s2s::sfse::game
