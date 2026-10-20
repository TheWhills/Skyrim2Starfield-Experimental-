// Thin wrappers over the game for the commands the controller issues. Everything that depends on an unverified game
// detail is here or in Hooks.cpp, marked "UNVERIFIED" with what to check on the PC (sfse/README.md, "First run").
#pragma once

#include "s2s/combat.h"

namespace s2s::sfse::game {

double Now();                                    // seconds, steady clock
RE::PlayerCharacter* Player();

// Must run on the main thread (Plugin queues them through SFSE's task interface).
bool SendEvent(std::string_view name);           // player's animation graph
bool GetVariable(std::string_view name, float& out);
void SetVariable(const combat::VariableSet& v);  // Papyrus ObjectReference.SetAnimationVariable* (queued by the VM)
void SetKeyword(std::string_view editor_id, bool add);
void SetGhost(bool ghost);
float ActorValue(std::string_view editor_id);    // < 0 when the value is not found
void DamageActorValue(std::string_view editor_id, float amount);

}  // namespace s2s::sfse::game
