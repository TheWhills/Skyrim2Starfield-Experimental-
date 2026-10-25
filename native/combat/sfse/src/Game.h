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
void DamageActorValue(std::string_view editor_id, float amount);

}  // namespace s2s::sfse::game
