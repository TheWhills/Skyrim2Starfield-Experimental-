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
int HasKeyword(std::string_view editor_id);     // 1 / 0, -1 when the keyword is not found
float ActorValue(std::string_view editor_id);    // < 0 when the value is not found
void DamageActorValue(std::string_view editor_id, float amount);

}  // namespace s2s::sfse::game
