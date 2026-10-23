#include "Game.h"

namespace s2s::sfse::game {
namespace {

// Calls a Papyrus method on the player (ObjectReference / Actor scripts). The VM queues the call; it runs within a
// frame or two, which is soon enough for MCO routing variables and stance keywords.
// UNVERIFIED: the native names exist in Starfield's Papyrus (ObjectReference.SetAnimationVariableBool / Int / Float,
// AddKeyword / RemoveKeyword, Actor.SetGhost: Fallout 4 has all of them). pc_checklist.ps1 step 1 lists which of these
// strings Starfield.exe contains; the plugin log shows "dispatch failed" when a call is refused.
// Receives a Papyrus call's return value (on the VM's thread).
class Callback final : public RE::BSScript::IStackCallbackFunctor {
public:
    explicit Callback(std::function<void(const RE::BSScript::Variable&)> fn) : fn_(std::move(fn)) {}
    void CallQueued() override {}
    void CallCanceled() override {}
    void StartMultiDispatch() override {}
    void EndMultiDispatch() override {}
    void operator()(RE::BSScript::Variable result) override { if (fn_) fn_(result); }
private:
    std::function<void(const RE::BSScript::Variable&)> fn_;
};

using Packer = std::function<void(RE::BSScrapArray<RE::BSScript::Variable>&)>;

bool Dispatch(const char* script, const char* function, Packer pack,
              std::function<void(const RE::BSScript::Variable&)> on_result = {}) {
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
    auto args = [pack = std::move(pack)](RE::BSScrapArray<RE::BSScript::Variable>& out) {
        out.clear();
        pack(out);
        return true;
    };
    RE::BSTSmartPointer<RE::BSScript::IStackCallbackFunctor> cb;
    if (on_result) cb = RE::BSTSmartPointer<RE::BSScript::IStackCallbackFunctor>(new Callback(std::move(on_result)));
    if (!vm->DispatchMethodCall(handle, RE::BSFixedString(script), RE::BSFixedString(function), args, cb, 0)) {
        REX::WARN("{}.{}: dispatch failed", script, function);
        return false;
    }
    return true;
}

template <class... Args>
bool CallOnPlayer(const char* script, const char* function, Args... args) {
    return Dispatch(script, function, [=](RE::BSScrapArray<RE::BSScript::Variable>& out) {
        out.resize(sizeof...(Args));
        std::size_t i = 0;
        ((RE::BSScript::PackVariable(out[i++], args)), ...);
    });
}

}  // namespace

// Reads memory only after VirtualQuery says it is committed and readable: for layouts CommonLibSF may not match on the
// running game version. A system call per check: fine for rare paths (a key press), not per frame.
bool Readable(const void* a_ptr, std::size_t a_len) {
    if (!a_ptr) return false;
    REX::W32::MEMORY_BASIC_INFORMATION mbi{};
    if (!REX::W32::VirtualQuery(a_ptr, &mbi, sizeof(mbi)) || mbi.state != REX::W32::MEM_COMMIT) return false;
    if (mbi.protect & (REX::W32::PAGE_NOACCESS | 0x100u)) return false;            // no access / guard page
    const auto ok = mbi.protect & (REX::W32::PAGE_READONLY | REX::W32::PAGE_READWRITE | REX::W32::PAGE_WRITECOPY |
                                   REX::W32::PAGE_EXECUTE_READ | REX::W32::PAGE_EXECUTE_READWRITE | 0x80u);
    const auto end = reinterpret_cast<std::uintptr_t>(mbi.baseAddress) + mbi.regionSize;
    return ok && reinterpret_cast<std::uintptr_t>(a_ptr) + a_len <= end;
}

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

// Papyrus Actor.GetEquippedWeapon(0) -> UnequipItem(weapon, false, true) -> EquipItem(weapon, false, true), each step
// in the previous one's return callback so they run in order. The weapon value is passed back as the VM returned it
// (no unpacking to a game type). Starfield picks the weapon's animation set at equip time (owner, 2026-10-23).
// UNVERIFIED: the three names in Starfield's Papyrus (Fallout 4 has them with these signatures); checklist step 1b.
bool ReequipWeapon(std::function<void(const std::string&)> report) {
    return Dispatch("Actor", "GetEquippedWeapon",
        [](RE::BSScrapArray<RE::BSScript::Variable>& out) {
            out.resize(1);
            RE::BSScript::PackVariable(out[0], static_cast<std::int32_t>(0));
        },
        [report](const RE::BSScript::Variable& weapon) {
            if (!weapon.is<RE::BSScript::Object>() || !RE::BSScript::get<RE::BSScript::Object>(weapon)) {
                if (report) report("no weapon equipped");
                return;
            }
            auto item = std::make_shared<RE::BSScript::Variable>(weapon);
            auto args = [item](RE::BSScrapArray<RE::BSScript::Variable>& out) {
                out.resize(3);
                out[0] = *item;
                RE::BSScript::PackVariable(out[1], false);
                RE::BSScript::PackVariable(out[2], true);          // silent
            };
            const bool ok = Dispatch("Actor", "UnequipItem", args, [args, report](const RE::BSScript::Variable&) {
                const bool again = Dispatch("Actor", "EquipItem", args);
                if (report) report(again ? "weapon re-equipped" : "EquipItem not dispatched");
            });
            if (!ok && report) report("UnequipItem not dispatched");
        });
}

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
