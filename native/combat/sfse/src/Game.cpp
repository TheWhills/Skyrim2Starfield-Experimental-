#include "Game.h"

namespace s2s::sfse::game {
namespace {

// Calls a Papyrus method on the player (ObjectReference / Actor scripts). The VM queues the call; it runs within a
// frame or two, which is soon enough for MCO routing variables and stance keywords.
// UNVERIFIED: the native names exist in Starfield's Papyrus (ObjectReference.SetAnimationVariableBool / Int / Float,
// AddKeyword / RemoveKeyword, Actor.SetGhost: Fallout 4 has all of them). pc_checklist.ps1 step 1 lists which of these
// strings Starfield.exe contains; the plugin log shows "dispatch failed" when a call is refused.
template <class... Args>
bool CallOnPlayer(const char* script, const char* function, Args... args) {
    auto* player = Player();
    auto* game = RE::GameVM::GetSingleton();
    auto* vm = game ? game->GetVM() : nullptr;
    if (!player || !vm) return false;
    const auto handle = vm->GetObjectHandlePolicy().GetHandleForObject(RE::BSScript::GetVMTypeID<RE::Actor>(),
                                                                       static_cast<RE::Actor*>(player));
    if (!handle) {
        REX::WARN("{}.{}: no script handle for the player", script, function);
        return false;
    }
    auto pack = [=](RE::BSScrapArray<RE::BSScript::Variable>& out) {
        out.clear();
        out.resize(sizeof...(Args));
        std::size_t i = 0;
        ((RE::BSScript::PackVariable(out[i++], args)), ...);
        return true;
    };
    if (!vm->DispatchMethodCall(handle, RE::BSFixedString(script), RE::BSFixedString(function), pack,
                                RE::BSTSmartPointer<RE::BSScript::IStackCallbackFunctor>(), 0)) {
        REX::WARN("{}.{}: dispatch failed", script, function);
        return false;
    }
    return true;
}

}  // namespace

double Now() {
    using clock = std::chrono::steady_clock;
    static const auto start = clock::now();
    return std::chrono::duration<double>(clock::now() - start).count();
}

RE::PlayerCharacter* Player() { return RE::PlayerCharacter::GetSingleton(); }

bool SendEvent(std::string_view name) {
    auto* player = Player();
    if (!player) return false;
    // IAnimationGraphManagerHolder::NotifyAnimationGraphImpl (vtable slot 1, mapped in CommonLibSF). Returns false
    // when the graph has no transition for the event in its current state.
    return player->NotifyAnimationGraphImpl(RE::BSFixedString(std::string(name).c_str()));
}

bool GetVariable(std::string_view name, float& out) {
    auto* player = Player();
    return player && player->GetGraphVariableImplFloat(RE::BSFixedString(std::string(name).c_str()), out);
}

bool SetVariable(const combat::VariableSet& v) {
    const std::string name = v.name;
    switch (v.type) {
        case combat::VariableSet::Type::Bool:
            return CallOnPlayer("ObjectReference", "SetAnimationVariableBool", RE::BSFixedString(name.c_str()), v.value != 0.0);
        case combat::VariableSet::Type::Int:
            return CallOnPlayer("ObjectReference", "SetAnimationVariableInt", RE::BSFixedString(name.c_str()),
                         static_cast<std::int32_t>(v.value));
        case combat::VariableSet::Type::Float:
            return CallOnPlayer("ObjectReference", "SetAnimationVariableFloat", RE::BSFixedString(name.c_str()),
                         static_cast<float>(v.value));
    }
    return false;
}

bool SetKeyword(std::string_view editor_id, bool add) {
    auto* keyword = RE::TESForm::LookupByEditorID<RE::BGSKeyword>(RE::BSFixedString(std::string(editor_id).c_str()));
    if (!keyword) {
        REX::WARN("keyword {} not found by EditorID (is the plugin that adds it loaded?)", editor_id);
        return false;
    }
    return CallOnPlayer("ObjectReference", add ? "AddKeyword" : "RemoveKeyword", keyword);
}

int HasKeyword(std::string_view editor_id) {
    auto* player = Player();
    auto* keyword = RE::TESForm::LookupByEditorID<RE::BGSKeyword>(RE::BSFixedString(std::string(editor_id).c_str()));
    if (!player || !keyword) return -1;
    return player->HasKeyword(keyword) ? 1 : 0;
}

bool SetGhost(bool ghost) { return CallOnPlayer("Actor", "SetGhost", ghost); }

float ActorValue(std::string_view editor_id) {
    auto* player = Player();
    auto* info = RE::TESForm::LookupByEditorID<RE::ActorValueInfo>(RE::BSFixedString(std::string(editor_id).c_str()));
    if (!player || !info) return -1.0f;
    return static_cast<RE::ActorValueOwner*>(player)->GetActorValue(*info);
}

void DamageActorValue(std::string_view editor_id, float amount) {
    auto* player = Player();
    auto* info = RE::TESForm::LookupByEditorID<RE::ActorValueInfo>(RE::BSFixedString(std::string(editor_id).c_str()));
    if (!player || !info) return;
    static_cast<RE::ActorValueOwner*>(player)->ModActorValue(RE::ACTOR_VALUE_MODIFIER::kDamage, *info, -amount);
}

}  // namespace s2s::sfse::game
