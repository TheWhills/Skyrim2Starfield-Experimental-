#include "ClashPlugin.h"

#include "Game.h"

namespace s2s::clash {
namespace game = sfse::game;
namespace {

using K = combat::Command::Kind;

// C-style trampolines for the callback table
bool CbPerfectBlock(std::uint32_t attacker) { return ClashPlugin::Get().OnPerfectBlock(attacker); }
void CbPlayerHit(std::uint32_t target) { ClashPlugin::Get().OnPlayerHit(target); }
bool CbButton(std::uint32_t key, bool down, const char* user) { return ClashPlugin::Get().OnButton(key, down, user ? user : ""); }
bool CbHidesKey(std::uint32_t key, const char* user) { return ClashPlugin::Get().HidesKey(key, user ? user : ""); }
bool CbHidesMovement() { return ClashPlugin::Get().HidesMovement(); }
bool CbActive() { return ClashPlugin::Get().Active(); }
bool CbWantsGhost() { return ClashPlugin::Get().WantsGhost(); }
void CbTick() { ClashPlugin::Get().Tick(); }
void CbMenu(const char* name, bool opening, bool blocking) { ClashPlugin::Get().OnMenu(name ? name : "", opening, blocking); }

const char* kind_name(K k) {
    switch (k) {
        case K::SendEvent: return "event";
        case K::ActorEvents: return "actor events";
        case K::ClashBegin: return "clash begin";
        case K::ClashEnd: return "clash end";
        case K::Notify: return "message";
        case K::Shake: return "shake";
        case K::Spark: return "spark";
        case K::ActorVariable: return "actor variable";
        case K::Guard: return "guard";
        case K::Log: return "log";
        default: return "?";
    }
}

// ---- the graph event filter: Actor's and PlayerCharacter's IAnimationGraphManagerHolder::NotifyAnimationGraphImpl
// (slot 1, vtables through RTTI). Owner's run 2026-10-26: the game's own attacks / reactions mostly do not come
// through it (only PositionChange / RelaxedStart seen); kept, harmless, logged.
using Notify_t = bool(RE::IAnimationGraphManagerHolder*, const RE::BSFixedString&);
Notify_t* g_notify_actor = nullptr;
Notify_t* g_notify_player = nullptr;

bool NotifyActor(RE::IAnimationGraphManagerHolder* a_this, const RE::BSFixedString& a_event) {
    if (ClashPlugin::Get().DropsEvent(a_this, a_event.c_str())) return false;
    return g_notify_actor(a_this, a_event);
}

bool NotifyPlayer(RE::IAnimationGraphManagerHolder* a_this, const RE::BSFixedString& a_event) {
    if (ClashPlugin::Get().DropsEvent(a_this, a_event.c_str())) return false;
    return g_notify_player(a_this, a_event);
}

}  // namespace

ClashPlugin& ClashPlugin::Get() {
    static ClashPlugin instance;
    return instance;
}

void ClashPlugin::LoadSettings(const std::string& ini_path) {
    std::ifstream in(ini_path);
    std::string ini;
    if (in) {
        std::stringstream buf;
        buf << in.rdbuf();
        ini = buf.str();
    } else {
        REX::WARN("{} not found: defaults used (see sfse/S2SClash.ini in the repo)", ini_path);
    }
    std::vector<std::string> problems;
    auto cfg = combat::parse_clash_config(ini, &problems);
    for (const auto& p : problems) REX::WARN("{}", p);
    std::scoped_lock l(lock_);
    cfg_ = cfg;
    clash_ = combat::Clash(cfg);
    blocked_ = combat::MenuGate::parse_list(cfg.blocked_events);
    zero_ = combat::MenuGate::parse_list(cfg.zero_variables);
    REX::INFO("weapon clash: {} (on perfect block {}, {} s, difficulty {}, forced on hit {})", cfg.enabled ? "on" : "off",
              cfg.on_perfect_block, cfg.duration, cfg.mode, cfg.force_on_hit);
}

void ClashPlugin::Connect(const api::CombatServices* services) {
    if (!services || services->version != api::kVersion || !services->register_clash) {
        REX::ERROR("S2SCombat's interface is version {}, this S2SClash needs {}: not connected (update both together)",
                   services ? services->version : 0, api::kVersion);
        return;
    }
    services_ = services;
    callbacks_.on_perfect_block = &CbPerfectBlock;
    callbacks_.on_player_hit = &CbPlayerHit;
    callbacks_.on_button = &CbButton;
    callbacks_.hides_key = &CbHidesKey;
    callbacks_.hides_movement = &CbHidesMovement;
    callbacks_.active = &CbActive;
    callbacks_.wants_ghost = &CbWantsGhost;
    callbacks_.tick = &CbTick;
    callbacks_.on_menu = &CbMenu;
    services_->register_clash(&callbacks_);
    REX::INFO("connected to S2SCombat");
}

void ClashPlugin::InstallGraphFilter() {
    static bool installed = false;
    if (installed) return;
    installed = true;
    static std::uintptr_t first_vtable = 0;
    auto hook = [](const auto& ids, const char* what, Notify_t* replacement, Notify_t*& original) {
        std::vector<std::uintptr_t> vtables;
        for (const auto& id : ids) vtables.push_back(id.address());
        auto found = combat::rtti_base_vtable(vtables, ".?AVIAnimationGraphManagerHolder@@",
                                              [](const void* p, std::size_t n) { return game::Readable(p, n); });
        if (!found || found->vtable == first_vtable) {
            REX::WARN("clash event filter: {} not hooked", what);
            return;
        }
        first_vtable = found->vtable;
        REL::Relocation<std::uintptr_t> vtbl{found->vtable};
        original = reinterpret_cast<Notify_t*>(vtbl.write_vfunc(1, replacement));
        REX::INFO("clash event filter: {} hooked ({} vtable {} of {})", what, found->complete_class, found->index,
                  vtables.size());
    };
    hook(RE::VTABLE::Actor, "Actor", &NotifyActor, g_notify_actor);
    hook(RE::VTABLE::PlayerCharacter, "PlayerCharacter", &NotifyPlayer, g_notify_player);
}

bool ClashPlugin::DropsEvent(const RE::IAnimationGraphManagerHolder* holder, const char* name) {
    if (!active_ || !holder || !name || game::SendingOwnEvent()) return false;
    const bool player = holder == player_graph_.load();
    if (!player && holder != opponent_graph_.load()) return false;
    const bool drop = combat::matches_prefix(name, blocked_);
    if (filter_logged_.fetch_add(1) < 80)
        REX::INFO("clash: {} '{}' for the {}", drop ? "kept" : "passed", name, player ? "player" : "opponent");
    return drop;
}

std::vector<combat::Command> ClashPlugin::TryStart(std::uint32_t opponent, const char* why) {
    const double now = game::Now();
    static std::uint32_t seed = 0x9E3779B9u;
    seed = seed * 1664525u + 1013904223u;
    const double roll = (seed >> 8) % 10000 / 100.0;
    if (!clash_.can_start(now, roll)) return {};
    const auto reason = game::ClashCheck(opponent, static_cast<float>(cfg_.max_start_distance));
    if (!reason.empty()) {
        REX::INFO("weapon clash ({}) with {:08X} not started: {}", why, opponent, reason);
        return {};
    }
    REX::INFO("weapon clash ({}) with {:08X}: started", why, opponent);
    return clash_.start(opponent, now, roll);
}

bool ClashPlugin::OnPerfectBlock(std::uint32_t attacker) {
    if (!cfg_.on_perfect_block || active_) return false;
    std::vector<combat::Command> cmds;
    {
        std::scoped_lock l(lock_);
        if (clash_.active()) return false;
        cmds = TryStart(attacker, "perfect block");
    }
    if (cmds.empty()) return false;
    Run(std::move(cmds));
    return true;
}

void ClashPlugin::OnPlayerHit(std::uint32_t target) {
    if (!cfg_.force_on_hit || active_) return;
    std::vector<combat::Command> cmds;
    {
        std::scoped_lock l(lock_);
        if (clash_.active()) return;
        cmds = TryStart(target, "bForceClashOnHit");
    }
    Run(std::move(cmds));
}

bool ClashPlugin::OnButton(std::uint32_t key, bool down, std::string_view user_event) {
    if (!active_ || !services_) return false;
    const auto attack = services_->attack_key(), power = services_->power_key();
    if (key == attack || (power && key == power) || user_event == "PrimaryAttack") {
        std::vector<combat::Command> cmds;
        {
            std::scoped_lock l(lock_);
            cmds = clash_.on_attack(down, game::Now());
            if (down && presses_logged_ < 80) {
                ++presses_logged_;
                REX::INFO("weapon clash: attack press {} (key {}), meter {:.2f}", clash_.presses(), key, clash_.meter());
            }
        }
        Run(std::move(cmds));
        return true;
    }
    if (down && presses_logged_ < 80) {
        ++presses_logged_;
        REX::INFO("weapon clash: key {} '{}' pressed (not the attack key {})", key, user_event, attack);
    }
    // No S2SCombat action during a clash (owner's run 2026-10-26: Alt mid-clash dodged out of it); releases go
    // through, so nothing is left held.
    return down;
}

bool ClashPlugin::HidesKey(std::uint32_t key, std::string_view user_event) const {
    if (!active_ || key == 0 || !services_) return false;
    const auto attack = services_->attack_key(), power = services_->power_key();
    if (key == attack || (power && key == power) || user_event == "PrimaryAttack") return true;
    if (!cfg_.block_movement) return false;
    if (user_event == "SecondaryAttack" || key == combat::key_from_mouse(1)) return true;
    for (int i = 0; i < 4; ++i)
        if (key == services_->move_key(i)) return true;
    return false;
}

void ClashPlugin::OnMenu(std::string_view name, bool opening, bool blocking_menu_open) {
    if (!opening || !active_ || !blocking_menu_open) return;
    std::vector<combat::Command> cmds;
    {
        std::scoped_lock l(lock_);
        cmds = clash_.abort(game::Now(), std::format("menu {} opened", name));
    }
    Run(std::move(cmds));
}

void ClashPlugin::Tick() {
    const double now = game::Now();
    std::vector<combat::Command> cmds;
    {
        std::scoped_lock l(lock_);
        if (!clash_.active()) return;
        // the opponent died, vanished or got pushed far away: no winner
        const auto why = game::ClashCheck(clash_.opponent(), static_cast<float>(cfg_.max_start_distance * 2.0));
        cmds = why.empty() ? clash_.tick(now) : clash_.abort(now, "opponent " + why);
        if (clash_.active() && active_) {
            if (cfg_.face_each_other) {
                // both turned during the settle time; then only the player's heading is held (drift > 0.5 deg)
                if (now - begin_at_ < cfg_.settle_time) {
                    game::FaceEachOther(clash_.opponent());
                } else if (auto* me = game::Player()) {
                    if (!heading_) heading_ = me->data.angle.z;
                    if (combat::heading_drifted(me->data.angle.z, *heading_, 0.5f * 3.14159265f / 180.0f)) {
                        me->data.angle.z = *heading_;
                        ++corrections_;
                    }
                }
            }
            for (const auto& [who, name] : zero_have_)
                game::SetActorVariable(who, {combat::VariableSet::Type::Float, name, 0.0});
            if (now >= trace_at_ && traces_ < 40) {              // locomotion values and heading corrections
                trace_at_ = now + 0.5;
                ++traces_;
                std::string line;
                for (auto* a : {static_cast<RE::Actor*>(game::Player()),
                                RE::TESForm::LookupByID<RE::Actor>(clash_.opponent())}) {
                    if (!a) continue;
                    line += std::format(" {:08X} heading {:.1f}", a->GetFormID(), a->data.angle.z * 57.2958f);
                    for (const auto& v : zero_) {
                        float f = 0.0f;
                        if (a->GetGraphVariableImplFloat(RE::BSFixedString(v.c_str()), f)) line += std::format(" {} {:.2f}", v, f);
                    }
                    line += ";";
                }
                REX::INFO("clash trace:{} player heading corrections {}", line, corrections_);
            }
        }
    }
    Run(std::move(cmds));
}

void ClashPlugin::Run(std::vector<combat::Command> commands) {
    if (commands.empty()) return;
    SFSE::GetTaskInterface()->AddTask([this, cmds = std::move(commands)]() {
        for (const auto& c : cmds) {
            std::string result;
            switch (c.kind) {
                case K::SendEvent: result = game::SendEvent(c.name) ? "taken by the graph" : "not taken by the graph"; break;
                case K::ActorEvents: result = game::SendActorEvents(c.target, c.name); break;
                case K::Log: REX::INFO("{}", c.name); continue;
                case K::ClashBegin: {
                    auto* opp = RE::TESForm::LookupByID<RE::Actor>(c.target);
                    auto* me = game::Player();
                    player_graph_ = me ? static_cast<const RE::IAnimationGraphManagerHolder*>(me) : nullptr;
                    opponent_graph_ = opp ? static_cast<const RE::IAnimationGraphManagerHolder*>(opp) : nullptr;
                    {
                        std::scoped_lock l(lock_);
                        begin_at_ = game::Now();
                        corrections_ = 0;
                        heading_.reset();
                        zero_have_.clear();
                        std::string zero;
                        for (auto* a : {static_cast<RE::Actor*>(me), opp}) {
                            if (!a) continue;
                            for (const auto& v : zero_) {
                                float f = 0.0f;
                                if (a->GetGraphVariableImplFloat(RE::BSFixedString(v.c_str()), f)) {
                                    zero_have_.emplace_back(a->GetFormID(), v);
                                    zero += std::format(" {:08X}.{}", a->GetFormID(), v);
                                }
                            }
                        }
                        result = std::format("zeroed each frame:{}; ", zero.empty() ? std::string(" none") : zero);
                    }
                    active_ = true;
                    if (cfg_.place_opponent) result += game::PlaceFacing(c.target, c.amount);
                    if (cfg_.restrain_opponent)
                        result += game::SetRestrained(c.target, true) ? "; restrained" : "; restrain not dispatched";
                    if (cfg_.lock_camera && services_) {
                        constexpr float kDeg = 3.14159265f / 180.0f;
                        took_lock_ = services_->lock_hold(c.target, static_cast<float>(cfg_.camera_yaw) * kDeg,
                                                          static_cast<float>(cfg_.camera_pitch) * kDeg, true);
                        result += took_lock_ ? "; lock-on taken" : "; lock-on already on it";
                    }
                    break;
                }
                case K::ClashEnd: {
                    active_ = false;
                    player_graph_ = nullptr;
                    opponent_graph_ = nullptr;
                    {
                        std::scoped_lock l(lock_);
                        heading_.reset();
                        zero_have_.clear();
                        result = std::format("{} attack presses, meter {:.2f}; ", clash_.presses(), clash_.meter());
                    }
                    if (services_) services_->lock_clear_offset();
                    if (cfg_.restrain_opponent)
                        result += game::SetRestrained(c.target, false) ? "released" : "release not dispatched";
                    if (took_lock_ && services_) {
                        took_lock_ = false;
                        services_->lock_release("weapon clash over");
                        result += "; lock-on released";
                    }
                    break;
                }
                case K::Notify: result = game::Notify(c.name) ? "dispatched" : "not dispatched"; break;
                case K::Shake: result = game::ShakeCamera(c.amount, c.dx / 1000.0f) ? "dispatched" : "not dispatched"; break;
                case K::Spark:
                    if (services_) services_->play_effect(c.target);
                    break;
                case K::Guard:
                    result = game::GuardActor(c.target, c.name, c.extra);
                    if (result.empty()) continue;                // already blocking: nothing sent, nothing logged
                    break;
                case K::ActorVariable:
                    result = std::format("{:08X} {} = {}: {}", c.target, c.variable.name, c.variable.value,
                                         game::SetActorVariable(c.target, c.variable) ? "dispatched" : "not dispatched");
                    break;
                default: result = "not a clash command (ignored)"; break;
            }
            const bool chatty = c.kind == K::Shake || c.kind == K::Spark;
            if (!chatty && commands_logged_.fetch_add(1) < log_commands_ * 4)
                REX::INFO("command: {} {} -> {}", kind_name(c.kind), c.name, result);
        }
    });
}

}  // namespace s2s::clash
