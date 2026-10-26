#include "Game.h"
#include "s2s/controller.h"

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

bool DispatchOn(RE::TESObjectREFR* self, const char* script, const char* function, Packer pack,
                std::function<void(const RE::BSScript::Variable&)> on_result = {}) {
    auto* game = RE::GameVM::GetSingleton();
    auto* vm = game ? game->GetVM() : nullptr;
    if (!self || !vm) return false;
    const auto handle = self->IsActor()
                            ? vm->GetObjectHandlePolicy().GetHandleForObject(RE::BSScript::GetVMTypeID<RE::Actor>(),
                                                                             static_cast<RE::Actor*>(self))
                            : vm->GetObjectHandlePolicy().GetHandleForObject(RE::BSScript::GetVMTypeID<RE::TESObjectREFR>(),
                                                                             self);
    if (!handle) {
        REX::WARN("{}.{}: no script handle for {:08X}", script, function, self->GetFormID());
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

bool Dispatch(const char* script, const char* function, Packer pack,
              std::function<void(const RE::BSScript::Variable&)> on_result = {}) {
    return DispatchOn(Player(), script, function, std::move(pack), std::move(on_result));
}

template <class... Args>
bool CallOnPlayer(const char* script, const char* function, Args... args) {
    return Dispatch(script, function, [=](RE::BSScrapArray<RE::BSScript::Variable>& out) {
        out.resize(sizeof...(Args));
        std::size_t i = 0;
        ((RE::BSScript::PackVariable(out[static_cast<std::uint32_t>(i++)], args)), ...);
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

namespace {
std::atomic<std::uint32_t> g_weapon_id{0};   // FormID of the weapon UnequipWeapon took off (0: none)

// Native equip / unequip through ActorEquipManager (mapped on 1.16: Singleton, EquipObject, UnequipObject,
// BGSObjectInstance ctor), base form without instance data, as the console's equipitem / unequipitem do (owner,
// 2026-10-23: those console commands re-pick the stance; Papyrus UnequipItem returned but changed nothing).
bool EquipNative(std::uint32_t form_id, bool equip) {
    auto* player = Player();
    auto* mgr = RE::ActorEquipManager::GetSingleton();
    auto* form = form_id ? RE::TESForm::LookupByID(form_id) : nullptr;
    if (!player || !mgr || !form) return false;
    RE::BGSObjectInstance item(form, nullptr);
    return equip ? mgr->EquipObject(player, item, nullptr, false, false, true, true, false)
                 : mgr->UnequipObject(player, item, nullptr, false, false, true, true, nullptr);
}
}  // namespace

// Stance re-equip, in two steps the controller spaces out: Papyrus Actor.GetEquippedWeapon(0) finds the weapon (its
// VM handle carries the FormID in the low 32 bits), then the native unequip on the main thread; EquipWeapon equips
// that FormID again.
bool UnequipWeapon(std::function<void(const std::string&)> report) {
    return Dispatch("Actor", "GetEquippedWeapon",
        [](RE::BSScrapArray<RE::BSScript::Variable>& out) {
            out.resize(1);
            RE::BSScript::PackVariable(out[0], static_cast<std::int32_t>(0));
        },
        [report](const RE::BSScript::Variable& weapon) {
            auto obj = weapon.is<RE::BSScript::Object>() ? RE::BSScript::get<RE::BSScript::Object>(weapon) : nullptr;
            if (!obj) {
                if (report) report("no weapon equipped");
                return;
            }
            const auto id = static_cast<std::uint32_t>(obj->GetHandle() & 0xFFFFFFFFull);
            g_weapon_id = id;
            SFSE::GetTaskInterface()->AddTask([id, report]() {
                const bool ok = EquipNative(id, false);
                if (report) report(std::format("unequip {:08X}: {}", id, ok ? "done" : "refused"));
            });
        });
}

bool EquipWeapon(std::function<void(const std::string&)> report) {
    const auto id = g_weapon_id.exchange(0);
    if (!id) {
        if (report) report("nothing to equip (no weapon was unequipped)");
        return false;
    }
    const bool ok = EquipNative(id, true);         // already on the main thread (Plugin::Run's task)
    if (report) report(std::format("equip {:08X}: {}", id, ok ? "done" : "refused"));
    return ok;
}

float ActorValue(std::string_view editor_id) {
    auto* player = Player();
    auto* info = RE::TESForm::LookupByEditorID<RE::ActorValueInfo>(RE::BSFixedString(std::string(editor_id).c_str()));
    if (!player || !info) return -1.0f;
    return static_cast<RE::ActorValueOwner*>(player)->GetActorValue(*info);
}

float PlayerHealth() {
    static const RE::ActorValueInfo* info = RE::TESForm::LookupByEditorID<RE::ActorValueInfo>(RE::BSFixedString("Health"));
    auto* player = Player();
    if (!player || !info) return -1.0f;
    return static_cast<RE::ActorValueOwner*>(player)->GetActorValue(*info);
}

bool Notify(std::string_view text) {
    auto* game = RE::GameVM::GetSingleton();
    auto* vm = game ? game->GetVM() : nullptr;
    if (!vm) return false;
    auto args = [msg = std::string(text)](RE::BSScrapArray<RE::BSScript::Variable>& out) {
        out.clear();
        out.resize(1);
        RE::BSScript::PackVariable(out[0], msg);
        return true;
    };
    RE::BSTSmartPointer<RE::BSScript::IStackCallbackFunctor> cb;
    return vm->DispatchStaticCall(RE::BSFixedString("Debug"), RE::BSFixedString("Notification"), args, cb, 0);
}

bool ShakeCamera(float strength, float seconds) {
    auto* game = RE::GameVM::GetSingleton();
    auto* vm = game ? game->GetVM() : nullptr;
    if (!vm) return false;
    auto args = [strength, seconds](RE::BSScrapArray<RE::BSScript::Variable>& out) {
        out.clear();
        out.resize(3);                                  // [0] stays None: the shake is not tied to a source
        RE::BSScript::PackVariable(out[1], strength);
        RE::BSScript::PackVariable(out[2], seconds);
        return true;
    };
    RE::BSTSmartPointer<RE::BSScript::IStackCallbackFunctor> cb;
    return vm->DispatchStaticCall(RE::BSFixedString("Game"), RE::BSFixedString("ShakeCamera"), args, cb, 0);
}

// An impact data set by EditorID or by form ID ("0x00137372" / "00137372"): Starfield keeps no EditorIDs for these at
// run time (owner's log 2026-10-26: all 275 sets nameless), so the INI and the preview key use form IDs.
RE::BGSImpactDataSet* ImpactSet(std::string_view name) {
    std::string s(name);
    while (!s.empty() && s.back() == ' ') s.pop_back();
    if (s.empty()) return nullptr;
    std::string hex = s.starts_with("0x") || s.starts_with("0X") ? s.substr(2) : s;
    if (!hex.empty() && hex.size() <= 8 && hex.find_first_not_of("0123456789abcdefABCDEF") == std::string::npos) {
        if (auto* f = RE::TESForm::LookupByID(static_cast<std::uint32_t>(std::stoul(hex, nullptr, 16))))
            if (f->GetFormType() == RE::FormType::kIPDS) return static_cast<RE::BGSImpactDataSet*>(f);
    }
    return RE::TESForm::LookupByEditorID<RE::BGSImpactDataSet>(RE::BSFixedString(s.c_str()));
}

std::mutex g_spawned_lock;
std::vector<std::pair<RE::NiPointer<RE::TESObjectREFR>, double>> g_spawned;     // effect objects to delete, and when

// A placed object as the effect: owner's pick 0x000550C3 is a placed reference (form type REFR), so its base object
// is placed at the player's node (ObjectReference.PlaceAtNode, FO4's signature; supported) and deleted 1.5 s later.
std::string PlaceEffectObject(RE::TESForm* form, std::string_view node) {
    RE::TESForm* base = form;
    if (form->GetFormType() == RE::FormType::kREFR) {
        auto b = static_cast<RE::TESObjectREFR*>(form)->GetBaseObject();
        base = b.get();
    }
    if (!base) return "the reference has no base object";
    const auto base_id = base->GetFormID();
    const auto base_type = static_cast<int>(base->GetFormType());
    const bool ok = Dispatch("ObjectReference", "PlaceAtNode",
                             [node = std::string(node), base](RE::BSScrapArray<RE::BSScript::Variable>& out) {
                                 out.resize(7);
                                 RE::BSScript::PackVariable(out[0], RE::BSFixedString(node.c_str()));
                                 RE::BSScript::PackVariable(out[1], base);
                                 RE::BSScript::PackVariable(out[2], 1);
                                 RE::BSScript::PackVariable(out[3], false);
                                 RE::BSScript::PackVariable(out[4], false);
                                 RE::BSScript::PackVariable(out[5], true);
                                 RE::BSScript::PackVariable(out[6], false);
                             },
                             [](const RE::BSScript::Variable& v) {
                                 auto* ref = RE::BSScript::UnpackVariable<RE::TESObjectREFR>(v);
                                 if (!ref) return;
                                 std::scoped_lock l(g_spawned_lock);
                                 g_spawned.emplace_back(RE::NiPointer<RE::TESObjectREFR>(ref), Now() + 1.5);
                             });
    return std::format("base object {:08X} (form type {}) placed at node {}: {}", base_id, base_type, node,
                       ok ? "dispatched" : "not dispatched");
}

void CleanupEffects() {
    std::vector<RE::NiPointer<RE::TESObjectREFR>> due;
    {
        std::scoped_lock l(g_spawned_lock);
        const double now = Now();
        for (auto it = g_spawned.begin(); it != g_spawned.end();) {
            if (now >= it->second) {
                due.push_back(it->first);
                it = g_spawned.erase(it);
            } else {
                ++it;
            }
        }
    }
    for (auto& r : due) {
        if (!r) continue;
        DispatchOn(r.get(), "ObjectReference", "Disable", [](RE::BSScrapArray<RE::BSScript::Variable>& out) {
            out.resize(1);
            RE::BSScript::PackVariable(out[0], false);
        });
        DispatchOn(r.get(), "ObjectReference", "Delete", [](RE::BSScrapArray<RE::BSScript::Variable>& out) { out.clear(); });
    }
}

bool DeferKill(bool on) {
    return Dispatch("Actor", on ? "StartDeferredKill" : "EndDeferredKill",
                    [](RE::BSScrapArray<RE::BSScript::Variable>& out) { out.clear(); });
}

std::string PlayImpactToward(std::string_view editor_id, std::string_view node, std::uint32_t toward, bool down,
                             const std::vector<std::string>& extra_sets) {
    auto* set = ImpactSet(editor_id);
    if (!set) {
        std::string hex(editor_id);
        if (hex.starts_with("0x") || hex.starts_with("0X")) hex = hex.substr(2);
        RE::TESForm* f = nullptr;
        if (!hex.empty() && hex.size() <= 8 && hex.find_first_not_of("0123456789abcdefABCDEF") == std::string::npos)
            f = RE::TESForm::LookupByID(static_cast<std::uint32_t>(std::stoul(hex, nullptr, 16)));
        return f ? std::format("'{}' (form type {}, not an impact data set): {}", editor_id,
                               static_cast<int>(f->GetFormType()), PlaceEffectObject(f, node))
                 : std::format("'{}': no impact data set by that form ID / EditorID (no form with that ID)", editor_id);
    }
    auto* player = Player();
    if (!player) return "no player";
    // the pick ray: from the node toward the attacker's chest height (owner's NPCs: within 1-3 m), else ahead
    float dx = 0.0f, dy = 1.0f, dz = 0.0f;
    if (auto* a = toward ? RE::TESForm::LookupByID<RE::Actor>(toward) : nullptr) {
        dx = a->data.location.x - player->data.location.x;
        dy = a->data.location.y - player->data.location.y;
        dz = 0.0f;
        const float len = std::sqrt(dx * dx + dy * dy);
        if (len > 1e-3f) { dx /= len; dy /= len; } else { dx = 0.0f; dy = 1.0f; }
    }
    // PlayImpactEffect returns false when its pick ray hits nothing (or the node is not found). Owner's run
    // 2026-10-26: dispatched on every timed block, nothing seen: the result is now logged and, on false, the next
    // aim is tried - toward the attacker, then down between the two, then straight down from the root node.
    struct Aim { std::string node; float x, y, z, len; const char* what; };
    auto aims = std::make_shared<std::vector<Aim>>();
    if (down) {
        aims->push_back({std::string(node), 0.0f, 0.0f, -1.0f, 10.0f, "down from the node"});
    } else {
        const float s = 0.6f;
        aims->push_back({std::string(node), dx, dy, 0.0f, 5.0f, "toward the attacker"});
        aims->push_back({std::string(node), dx * s, dy * s, -0.8f, 10.0f, "down toward the attacker"});
    }
    aims->push_back({std::string(), 0.0f, 0.0f, -1.0f, 10.0f, "straight down from the root"});
    // Every listed set is tried with every aim until one plays (owner's run 2026-10-26: the blade-block set returned
    // false for every aim, even straight down onto a metal floor - it likely holds only weapon-vs-weapon entries).
    auto sets = std::make_shared<std::vector<std::pair<RE::BGSImpactDataSet*, std::string>>>();
    sets->emplace_back(set, std::string(editor_id));
    for (const auto& extra : extra_sets)
        if (auto* s2 = ImpactSet(extra)) sets->emplace_back(s2, extra);
    auto try_aim = std::make_shared<std::function<void(std::size_t)>>();
    const std::size_t n_aims = aims->size();
    *try_aim = [sets, aims, try_aim, n_aims](std::size_t k) {
        if (k >= n_aims * sets->size()) {
            REX::INFO("effect: none of the {} impact sets played with any aim", sets->size());
            return;
        }
        auto* set = (*sets)[k / n_aims].first;
        const auto id = (*sets)[k / n_aims].second;
        const std::size_t i = k;
        const auto a = (*aims)[k % n_aims];
        Dispatch("ObjectReference", "PlayImpactEffect",
                 [set, a](RE::BSScrapArray<RE::BSScript::Variable>& out) {
                     out.resize(8);
                     RE::BSScript::PackVariable(out[0], set);
                     RE::BSScript::PackVariable(out[1], RE::BSFixedString(a.node.c_str()));
                     RE::BSScript::PackVariable(out[2], a.x);
                     RE::BSScript::PackVariable(out[3], a.y);
                     RE::BSScript::PackVariable(out[4], a.z);
                     RE::BSScript::PackVariable(out[5], a.len);
                     RE::BSScript::PackVariable(out[6], false);
                     RE::BSScript::PackVariable(out[7], false);
                 },
                 [try_aim, a, i, id](const RE::BSScript::Variable& v) {
                     const bool played = v.is<bool>() && RE::BSScript::get<bool>(v);
                     static std::atomic<int> logged{0};
                     if (logged.fetch_add(1) < 150)
                         REX::INFO("effect '{}' {} (node '{}'): {}", id, a.what, a.node,
                                   played ? "played" : (v.is<bool>() ? "returned false" : "no bool result"));
                     if (!played) (*try_aim)(i + 1);
                 });
    };
    (*try_aim)(0);
    return std::format("'{}' dispatched (result in the 'effect' line)", editor_id);
}

std::vector<std::uint32_t> g_impact_ids;
const std::vector<std::uint32_t>& ImpactSetIds() { return g_impact_ids; }

std::string ListSparkForms() {
    // Form IDs of the master files' first 4M records, looked up one by one (once; the log gives the time). Starfield
    // keeps EditorIDs for these record types (LookupByEditorID works for actor values and keywords).
    const auto t0 = std::chrono::steady_clock::now();
    REX::INFO("effects: listing spark-like impact sets and explosions (once per session; bListEffectForms = 0 to skip)");
    std::vector<std::pair<int, std::string>> sets;
    std::vector<std::string> explosions, all_sets;
    g_impact_ids.clear();
    int n_sets = 0, n_expl = 0;
    for (std::uint32_t id = 1; id < 0x00400000u; ++id) {
        auto* f = RE::TESForm::LookupByID(id);
        if (!f) continue;
        const auto type = f->GetFormType();
        if (type != RE::FormType::kIPDS && type != RE::FormType::kEXPL) continue;
        const char* ed = f->GetFormEditorID();
        const std::string name = ed ? ed : "";
        if (type == RE::FormType::kIPDS) {
            ++n_sets;
            all_sets.push_back(name.empty() ? std::format("[{:08X}]", id) : name);
            g_impact_ids.push_back(id);
            if (int sc = combat::spark_score(name)) sets.emplace_back(sc, name);
        } else {
            ++n_expl;
            if (combat::spark_score(name)) explosions.push_back(name);
        }
    }
    std::stable_sort(sets.begin(), sets.end(), [](const auto& a, const auto& b) { return a.first > b.first; });
    std::string list;
    for (std::size_t i = 0; i < sets.size() && i < 40; ++i) list += " " + sets[i].second;
    std::string elist;
    for (std::size_t i = 0; i < explosions.size() && i < 20; ++i) elist += " " + explosions[i];
    const auto ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    REX::INFO("effects: {} impact data sets ({} with 'spark':{}), {} explosions (spark-like:{}) in {:.0f} ms", n_sets,
              sets.size(), list.empty() ? std::string(" none") : list, n_expl, elist.empty() ? std::string(" none") : elist,
              ms);
    // every impact data set by name (or form ID when it has no EditorID), 40 per line: to pick sTimedBlockEffect by hand
    for (std::size_t i = 0; i < all_sets.size(); i += 40) {
        std::string line;
        for (std::size_t j = i; j < all_sets.size() && j < i + 40; ++j) line += " " + all_sets[j];
        REX::INFO("effects: impact data sets {}-{}:{}", i + 1, std::min(all_sets.size(), i + 40), line);
    }
    if (!sets.empty()) REX::INFO("effects: timed-block sparks will use '{}' (sTimedBlockEffect names another)", sets[0].second);
    return sets.empty() ? std::string() : sets[0].second;
}

std::string SendActorEvents(std::uint32_t form_id, std::string_view events) {
    auto* actor = form_id ? RE::TESForm::LookupByID<RE::Actor>(form_id) : nullptr;
    if (!actor) return std::format("{:08X}: no such actor", form_id);
    std::string tried;
    std::size_t start = 0;
    while (start <= events.size()) {
        auto end = events.find(',', start);
        if (end == std::string_view::npos) end = events.size();
        auto name = events.substr(start, end - start);
        while (!name.empty() && name.front() == ' ') name.remove_prefix(1);
        while (!name.empty() && name.back() == ' ') name.remove_suffix(1);
        start = end + 1;
        if (name.empty()) continue;
        if (actor->NotifyAnimationGraphImpl(RE::BSFixedString(std::string(name).c_str())))
            return std::format("{:08X}: '{}' taken{}", form_id, name, tried.empty() ? "" : " (not taken: " + tried + ")");
        tried += (tried.empty() ? "" : ", ") + std::string(name);
    }
    return std::format("{:08X}: none taken ({})", form_id, tried);
}

// Through Papyrus (ObjectReference.DamageValue / RestoreValue, queued by the VM), not ActorValueOwner::ModActorValue:
// the owner's game crashed right after the first native call to it (2026-10-25, a held-block hit's give-back), and
// CommonLibSF's two ModActorValue overloads (slots 06 / 07) are not verified on 1.16.
void DamageActorValue(std::string_view editor_id, float amount) {
    auto* info = RE::TESForm::LookupByEditorID<RE::ActorValueInfo>(RE::BSFixedString(std::string(editor_id).c_str()));
    if (!info || amount == 0.0f) return;
    if (amount > 0.0f) CallOnPlayer("ObjectReference", "DamageValue", info, amount);
    else CallOnPlayer("ObjectReference", "RestoreValue", info, -amount);
}

}  // namespace s2s::sfse::game
