#include "Plugin.h"

#include "Game.h"
#include "Lock.h"

namespace s2s::sfse {
namespace {

int to_int(const std::map<std::string, std::string>& m, const char* key, int fallback) {
    auto it = m.find(key);
    if (it == m.end()) return fallback;
    try {
        return std::stoi(it->second);
    } catch (...) {
        REX::WARN("[Plugin] {} = {}: not a number, {} kept", key, it->second, fallback);
        return fallback;
    }
}

const char* kind_name(combat::Command::Kind k) {
    using K = combat::Command::Kind;
    switch (k) {
        case K::SendEvent: return "event";
        case K::SetVariable: return "variable";
        case K::AddKeyword: return "add keyword";
        case K::RemoveKeyword: return "remove keyword";
        case K::SpendStamina: return "stamina";
        case K::ToggleLock: return "lock";
        case K::SwitchTarget: return "switch";
        case K::UnequipWeapon: return "stance unequip";
        case K::EquipWeapon: return "stance equip";
        case K::Log: return "log";
        case K::RestoreHealth: return "restore health";
        case K::ActorEvents: return "actor events";
        case K::Feedback: return "feedback";
        case K::DeferKill: return "deferred kill";
        case K::ClashBegin: return "clash begin";
        case K::ClashEnd: return "clash end";
        case K::Notify: return "message";
        case K::Shake: return "shake";
        case K::Spark: return "clash spark";
        case K::ActorVariable: return "actor variable";
        case K::Guard: return "guard";
    }
    return "?";
}

}  // namespace

Plugin& Plugin::Get() {
    static Plugin instance;
    return instance;
}

void Plugin::LoadSettings(const std::string& ini_path) {
    std::ifstream in(ini_path);
    if (!in) {
        REX::WARN("{} not found: defaults used (see sfse/S2SCombat.ini in the repo)", ini_path);
        return;
    }
    std::stringstream buf;
    buf << in.rdbuf();
    const std::string ini = buf.str();

    std::vector<std::string> problems;
    auto cfg = combat::parse_config(ini, &problems);
    for (const auto& p : problems) REX::WARN("{}", p);
    auto bindings = combat::parse_bindings(ini, "Keys");
    auto clash_cfg = combat::parse_clash_config(ini, &problems);
    for (const auto& p : problems) if (p.starts_with("[Clash]")) REX::WARN("{}", p);

    const auto plugin = combat::ini_section(ini, "Plugin");
    settings_.enabled = to_int(plugin, "benabled", 1) != 0;
    settings_.log_input = to_int(plugin, "ilogkeys", settings_.log_input);
    settings_.log_events = to_int(plugin, "iloganimevents", settings_.log_events);
    settings_.ghost_during_iframes = to_int(plugin, "bghostduringiframes", 1) != 0;
    if (auto it = plugin.find("sstaminaactorvalue"); it != plugin.end()) settings_.stamina_value = it->second;
    settings_.log_menus = to_int(plugin, "ilogmenus", settings_.log_menus);
    settings_.log_hits = to_int(plugin, "iloghits", settings_.log_hits);
    settings_.log_commands = to_int(plugin, "ilogcommands", settings_.log_commands);
    settings_.perf_seconds = to_int(plugin, "iperfseconds", settings_.perf_seconds);
    settings_.probe_layout = to_int(plugin, "bprobeeventlayout", 0) != 0;
    auto to_float = [&](const char* key, float& out) {
        if (auto it = plugin.find(key); it != plugin.end() && !it->second.empty()) {
            try { out = std::stof(it->second); } catch (...) { REX::WARN("[Plugin] {} = {}: not a number", key, it->second); }
        }
    };
    if (auto it = plugin.find("stimedblockeffect"); it != plugin.end()) settings_.timed_block_effect = it->second;
    if (auto it = plugin.find("stimedblockeffectnode"); it != plugin.end()) settings_.timed_block_effect_node = it->second;
    to_float("ftimedblockshake", settings_.timed_block_shake);
    to_float("ftimedblockshaketime", settings_.timed_block_shake_time);
    settings_.list_effect_forms = to_int(plugin, "blisteffectforms", 1) != 0;
    settings_.effect_next_key = static_cast<std::uint32_t>(to_int(plugin, "ieffectnextkey", 0));
    settings_.effect_prev_key = static_cast<std::uint32_t>(to_int(plugin, "ieffectprevkey", 0));
    if (auto it = plugin.find("sblockingmenus"); it != plugin.end() && !it->second.empty())
        menus_ = combat::MenuGate(combat::MenuGate::parse_list(it->second));

    const auto lk = combat::ini_section(ini, "Lock");
    LockSettings ls;
    auto f = [&](const char* key, float& out) {
        if (auto it = lk.find(key); it != lk.end()) {
            try { out = std::stof(it->second); } catch (...) { REX::WARN("[Lock] {} = {}: not a number", key, it->second); }
        }
    };
    f("fmaxdistance", ls.max_distance);
    f("ftargetheight", ls.target_height);
    f("feyeheight", ls.eye_height);
    f("fyawrate", ls.yaw_rate);
    f("fpitchrate", ls.pitch_rate);
    f("fpitchgain", ls.pitch_gain);
    f("facquiretime", ls.acquire_time);
    f("fpitchsign", ls.pitch_sign);
    ls.steer_pitch = to_int(lk, "bsteerpitch", 1) != 0;
    ls.steer_player = to_int(lk, "bsteerplayer", 0) != 0;
    ls.steer_camera = to_int(lk, "bsteercamera", 1) != 0;
    ls.hard_lock = to_int(lk, "bhardlock", 1) != 0;
    ls.block_look = to_int(lk, "bblocklook", 1) != 0;
    ls.aim_from_camera = to_int(lk, "baimfromcamera", 1) != 0;
    ls.camera_samples = to_int(lk, "icamerasamples", ls.camera_samples);
    ls.hostile_only = to_int(lk, "bhostileonly", 1) != 0;
    ls.log_targets = to_int(lk, "ilogtargets", ls.log_targets);
    if (auto it = lk.find("slockvariable"); it != lk.end()) ls.lock_variable = it->second;
    Lock::Get().Configure(ls);

    std::scoped_lock l(lock_);
    controller_ = combat::Controller(cfg, bindings);
    clash_ = combat::Clash(clash_cfg);
    clash_block_movement_ = clash_cfg.block_movement;
    clash_blocked_ = combat::MenuGate::parse_list(clash_cfg.blocked_events);
    clash_zero_ = combat::MenuGate::parse_list(clash_cfg.zero_variables);
    attack_key_ = cfg.attack_key;
    power_key_ = cfg.power_key;
    move_keys_ = cfg.move_keys;
    REX::INFO("weapon clash: {} (on perfect block {}, {} s, difficulty {}, forced on hit {})",
              clash_cfg.enabled ? "on" : "off", clash_cfg.on_perfect_block, clash_cfg.duration, clash_cfg.mode,
              clash_cfg.force_on_hit);
    REX::INFO("settings: {} key bindings, attack key {}, dodge key {}, buffer {}, plugin event host '{}'",
              bindings.size(), cfg.attack_key, cfg.dodge_key, cfg.buffer_attacks ? "on" : "off",
              cfg.plugin_event_host);
}

combat::PlayerState Plugin::State() {
    combat::PlayerState s;
    s.stick_x = stick_x_;
    s.stick_y = stick_y_;
    // Blocking: the melee graph's own variable for a held block (MeleeActions: BlockStart needs iWantBlock = 1); the
    // timed block (parry) window starts when it turns on.
    s.blocking = Blocking(&s.block_state);
    s.block_key = block_key_;
    s.health = game::PlayerHealth();
    if (!settings_.stamina_value.empty()) {
        float v = game::ActorValue(settings_.stamina_value);
        if (v >= 0.0f) s.stamina = v;
    }
    // UNVERIFIED / TODO: staggered state (no mapped flag yet): dodging out of a stagger is not blocked.
    return s;
}

bool Plugin::HidesPowerPress(std::uint32_t key) {
    if (!settings_.enabled || key == 0) return false;
    auto* player = game::Player();
    if (!player || !player->parentCell || menus_.blocked()) return false;
    std::scoped_lock l(lock_);
    return controller_.hides_power_press(key);
}

void Plugin::NoteHiddenKey() {
    if (clash_active_) return;                    // a clash holds back attack / block / movement: logged as presses
    if (logged_hidden_ < settings_.log_commands) {
        ++logged_hidden_;
        REX::INFO("power attack key kept from the game's controls (combo power attack sent by the plugin)");
    }
}

bool Plugin::OnButton(std::uint32_t key, bool down, std::string_view user_event, std::uint32_t device,
                      std::int32_t id_code, float value, float held) {
    if (!settings_.enabled) return false;
    if (logged_input_ < settings_.log_input) {
        ++logged_input_;
        REX::INFO("key: device {} id 0x{:X} -> code {} {} (value {}, held {:.2f}) user event '{}'", device, id_code,
                  key, down ? "down" : "up", value, held, user_event);
    }
    // The block key (the game's SecondaryAttack: right mouse with a melee weapon): the timed-block window starts on its
    // press. The graph's own block variables come later (iWantBlock stayed 0 for the player in the owner's run: it is
    // the AI's "block without an event" switch) or not at all.
    if (user_event == "SecondaryAttack" || key == combat::key_from_mouse(1)) {
        if (down && !block_key_) block_key_at_ = game::Now();
        block_key_ = down;
    }
    if (key == 0) return false;
    // Presses only count in gameplay: a save loaded (the player is in a cell) and no menu that takes the keys open.
    // Releases always go through, so a key held into a menu is not left "down".
    if (down) {
        auto* player = game::Player();
        if (!player || !player->parentCell || menus_.blocked()) return false;
    }
    if (down && (key == settings_.effect_next_key || key == settings_.effect_prev_key)) {
        const auto& ids = game::ImpactSetIds();
        if (!ids.empty()) {
            const int n = static_cast<int>(ids.size());
            effect_preview_ = key == settings_.effect_next_key ? (effect_preview_ + 1) % n : (effect_preview_ + n - 1) % n;
            const auto id = std::format("{:08X}", ids[effect_preview_]);
            const auto node = settings_.timed_block_effect_node;
            SFSE::GetTaskInterface()->AddTask([id, node, i = effect_preview_, n]() {
                const auto r = game::PlayImpactToward(id, node, 0, true);
                game::Notify(std::format("Impact {}/{}: 0x{}", i + 1, n, id));
                REX::INFO("effect preview {}/{}: 0x{} -> {}", i + 1, n, id, r);
            });
        }
        return true;                                   // the preview keys do nothing else
    }
    if (clash_active_) {
        // the attack key pushes the clash meter; the other keys the clash holds back do nothing else meanwhile
        if (key == attack_key_ || (power_key_ && key == power_key_) || user_event == "PrimaryAttack") {
            std::vector<combat::Command> cmds;
            {
                std::scoped_lock l(lock_);
                cmds = clash_.on_attack(down, game::Now());
                if (down && clash_presses_logged_ < 80) {
                    ++clash_presses_logged_;
                    REX::INFO("weapon clash: attack press {} (key {}), meter {:.2f}", clash_.presses(), key,
                              clash_.meter());
                }
            }
            Run(std::move(cmds));
            return true;
        }
        if (down && clash_presses_logged_ < 80) {
            ++clash_presses_logged_;
            REX::INFO("weapon clash: key {} '{}' pressed (not the attack key {})", key, user_event, attack_key_);
        }
        // No other plugin action during a clash: owner's run 2026-10-26, Alt mid-clash dodged out of it (6 m away,
        // aborted). Releases still go through, so nothing is left held.
        if (down) return ClashHidesKey(key, user_event);
    }
    auto state = State();
    std::vector<combat::Command> cmds;
    bool consumed = false;
    {
        std::scoped_lock l(lock_);
        cmds = controller_.on_key(key, down, game::Now(), state);
        consumed = controller_.last_key_consumed();
    }
    Run(std::move(cmds));
    return consumed;
}

void Plugin::OnStick(float x, float y) {
    stick_x_ = x;
    stick_y_ = y;
}

void Plugin::OnMenu(std::string_view name, bool opening) {
    if (logged_menus_ < settings_.log_menus) {
        ++logged_menus_;
        REX::INFO("menu: '{}' {}", name, opening ? "opened" : "closed");
    }
    menus_.on_menu(name, opening);
    if (opening && clash_active_ && menus_.blocked()) {
        std::vector<combat::Command> cmds;
        {
            std::scoped_lock l(lock_);
            cmds = clash_.abort(game::Now(), std::format("menu {} opened", name));
        }
        Run(std::move(cmds));
    }
}

bool Plugin::ClashDropsEvent(const RE::IAnimationGraphManagerHolder* holder, const char* name) {
    if (!clash_active_ || !holder || !name || game::SendingOwnEvent()) return false;
    const bool player = holder == clash_player_graph_.load();
    if (!player && holder != clash_opponent_graph_.load()) return false;
    const bool drop = combat::matches_prefix(name, clash_blocked_);
    // every event the filter sees for the two (first 80): shows whether the game's own attacks / reactions come
    // through this function at all (owner's run 2026-10-26: none was kept)
    if (clash_dropped_logged_.fetch_add(1) < 80)
        REX::INFO("clash: {} '{}' for the {}", drop ? "kept" : "passed", name, player ? "player" : "opponent");
    return drop;
}

bool Plugin::ClashHidesKey(std::uint32_t key, std::string_view user_event) const {
    if (!clash_active_ || key == 0) return false;
    if (key == attack_key_ || (power_key_ && key == power_key_) || user_event == "PrimaryAttack") return true;
    if (!clash_block_movement_) return false;
    if (user_event == "SecondaryAttack" || key == combat::key_from_mouse(1)) return true;
    return std::find(move_keys_.begin(), move_keys_.end(), key) != move_keys_.end();
}

std::vector<combat::Command> Plugin::TryClash(std::uint32_t opponent, const char* why) {
    const double now = game::Now();
    static std::uint32_t seed = 0x9E3779B9u;
    seed = seed * 1664525u + 1013904223u;
    const double roll = (seed >> 8) % 10000 / 100.0;
    if (!clash_.can_start(now, roll)) return {};
    const auto reason = game::ClashCheck(opponent, static_cast<float>(clash_.config().max_start_distance));
    if (!reason.empty()) {
        REX::INFO("weapon clash ({}) with {:08X} not started: {}", why, opponent, reason);
        return {};
    }
    REX::INFO("weapon clash ({}) with {:08X}: started", why, opponent);
    return clash_.start(opponent, now, roll);
}

void Plugin::OnPlayerHit(std::uint32_t target) {
    if (!settings_.enabled || !clash_.config().force_on_hit || clash_active_) return;
    std::vector<combat::Command> cmds;
    {
        std::scoped_lock l(lock_);
        cmds = TryClash(target, "bForceClashOnHit");
    }
    Run(std::move(cmds));
}

// Blocking: the block key held, or the melee graph's block state (bIsBlocking: the State Variable of the block
// states in MeleeActions) or its AI switch (iWantBlock). Changes go to the log (first 30) to check which one moves.
bool Plugin::Blocking(bool* graph_state) {
    bool graph = false, want = false;
    if (auto* player = game::Player()) {
        static const RE::BSFixedString is_blocking("bIsBlocking"), want_block("iWantBlock");
        bool b = false;
        std::int32_t w = 0;
        if (player->GetGraphVariableImplBool(is_blocking, b)) graph = b;
        if (player->GetGraphVariableImplInt(want_block, w)) want = w != 0;
    }
    // The key alone counts only while the guard is still coming up (0.4 s): the same key aims a gun, and a held
    // block shows in bIsBlocking.
    const bool key = block_key_ && game::Now() - block_key_at_ < 0.4;
    const int sig = (key ? 1 : 0) | (graph ? 2 : 0) | (want ? 4 : 0);
    if (sig != block_sig_ && block_logs_ < 30) {
        ++block_logs_;
        REX::INFO("block: key {} bIsBlocking {} iWantBlock {}", key, graph, want);
    }
    block_sig_ = sig;
    if (graph_state) *graph_state = graph;
    return key || graph || want;
}

void Plugin::OnHit(std::string_view attack_event, std::uint32_t aggressor, std::uint32_t weapon) {
    if (!settings_.enabled) return;
    // Blocking: the melee graph's own variable for a held block (MeleeActions: BlockStart needs iWantBlock = 1).
    const std::int32_t want_block = Blocking() ? 1 : 0;
    const bool read = true;
    const auto kind = combat::hit_kind(attack_event);
    const double now = game::Now();
    std::vector<combat::Command> cmds;
    bool invulnerable = false;
    {
        std::scoped_lock l(lock_);
        invulnerable = controller_.invulnerable(now);
        cmds = controller_.on_hit(kind, want_block != 0, now, aggressor);
        // a perfect block starts a weapon clash instead of the attacker's parry stagger
        if (clash_.config().on_perfect_block && !clash_.active()) {
            auto without = cmds;
            if (combat::take_perfect_block(without, aggressor)) {
                auto start = TryClash(aggressor, "perfect block");
                if (!start.empty()) {
                    without.insert(without.end(), start.begin(), start.end());
                    cmds = std::move(without);
                }
            }
        }
    }
    if (logged_hits_ < settings_.log_hits) {
        ++logged_hits_;
        REX::INFO("hit on player: attacker {:08X} weapon {:08X} attack event '{}' ({}) blocking {}{} i-frames {}",
                  aggressor, weapon, attack_event,
                  kind == combat::HitKind::Power ? "power" : kind == combat::HitKind::Normal ? "normal" : "unknown",
                  want_block, read ? "" : " (iWantBlock not readable)", invulnerable ? "on" : "off");
    }
    Run(std::move(cmds));
}

void Plugin::DisableAnimEvents(std::string_view why) {
    if (anim_events_.exchange(false)) REX::ERROR("animation events switched off: {}", why);
}

void Plugin::OnAnimEvent(std::string_view tag, std::string_view payload) {
    if (!settings_.enabled || !anim_events_) return;
    std::vector<combat::Command> cmds;
    {
        std::scoped_lock l(lock_);
        if (logged_events_ < settings_.log_events) {
            ++logged_events_;
            REX::INFO("anim event: '{}' payload '{}'", tag, payload);
        } else if (combat_logged_ < 300 && combat::is_combat_reaction_event(tag, payload)) {
            ++combat_logged_;                         // block / hit / stagger events stay visible after the cap
            REX::INFO("anim event: '{}' payload '{}'", tag, payload);
        }
        cmds = controller_.on_anim_event(tag, payload, game::Now());
    }
    Run(std::move(cmds));
}

void Plugin::Tick() {
    if (!settings_.enabled) return;
    const double now = game::Now();
    auto state = State();
    std::vector<combat::Command> cmds;
    bool invulnerable = false;
    {
        std::scoped_lock l(lock_);
        cmds = controller_.tick(now, state);
        invulnerable = controller_.invulnerable(now);
        if (clash_.active()) {
            // the opponent died, vanished or got pushed far away: no winner
            const auto why = game::ClashCheck(clash_.opponent(), static_cast<float>(clash_.config().max_start_distance * 2.0));
            auto more = why.empty() ? clash_.tick(now) : clash_.abort(now, "opponent " + why);
            cmds.insert(cmds.end(), more.begin(), more.end());
        }
        if (clash_.active() && clash_.config().ghost_player) invulnerable = true;
        if (clash_.active() && clash_active_) {
            const auto& cc = clash_.config();
            if (cc.face_each_other) {
                // both turned during the settle time; then only the player's heading is held (drift > 0.5 deg)
                if (now - clash_begin_at_ < cc.settle_time) {
                    game::FaceEachOther(clash_.opponent());
                } else if (auto* me = game::Player()) {
                    if (!clash_heading_) clash_heading_ = me->data.angle.z;
                    if (combat::heading_drifted(me->data.angle.z, *clash_heading_, 0.5f * 3.14159265f / 180.0f)) {
                        me->data.angle.z = *clash_heading_;
                        ++clash_corrections_;
                    }
                }
            }
            for (const auto& [who, name] : clash_zero_have_)
                game::SetActorVariable(who, {combat::VariableSet::Type::Float, name, 0.0});
            // why the feet move (owner, 2026-10-26: footsteps all through the clash): the graph's locomotion values
            // and the heading corrections, every 0.5 s for the first clashes
            if (now >= clash_trace_at_ && clash_traces_ < 40) {
                clash_trace_at_ = now + 0.5;
                ++clash_traces_;
                std::string line;
                for (auto* a : {static_cast<RE::Actor*>(game::Player()),
                                RE::TESForm::LookupByID<RE::Actor>(clash_.opponent())}) {
                    if (!a) continue;
                    line += std::format(" {:08X} heading {:.1f}", a->GetFormID(), a->data.angle.z * 57.2958f);
                    for (const auto& v : clash_zero_) {
                        float f = 0.0f;
                        if (a->GetGraphVariableImplFloat(RE::BSFixedString(v.c_str()), f)) line += std::format(" {} {:.2f}", v, f);
                    }
                    line += ";";
                }
                REX::INFO("clash trace:{} player heading corrections {}", line, clash_corrections_);
            }
        }
    }
    Run(std::move(cmds));
    if (settings_.list_effect_forms && !effects_listed_) {
        auto* player = game::Player();
        if (player && player->parentCell) {
            effects_listed_ = true;
            auto best = game::ListSparkForms();
            if (!best.empty()) auto_effect_ = best;
        }
    }
    game::CleanupEffects();
    Lock::Get().Update();                                    // main thread (the input hook)
    if (keyword_check_due_ >= 0.0 && now >= keyword_check_due_) {
        keyword_check_due_ = -1.0;
        if (keyword_checks_logged_ < 20) {
            ++keyword_checks_logged_;
            std::string line;
            for (const auto& k : keyword_check_) {
                const int has = game::HasKeyword(k);
                line += std::format(" {} {}", k, has < 0 ? "(not found)" : has ? "yes" : "no");
            }
            REX::INFO("keywords on the player:{}", line);
        }
        keyword_check_.clear();
    }
    if (settings_.ghost_during_iframes && invulnerable != ghost_) {
        ghost_ = invulnerable;
        SFSE::GetTaskInterface()->AddTask([g = ghost_]() { game::SetGhost(g); });
    }
}

void Plugin::Run(std::vector<combat::Command> commands) {
    if (commands.empty()) return;
    const std::string stamina = settings_.stamina_value;
    const int limit = settings_.log_commands;
    SFSE::GetTaskInterface()->AddTask([this, cmds = std::move(commands), stamina, limit]() {
        using K = combat::Command::Kind;
        for (const auto& c : cmds) {
            std::string result;
            switch (c.kind) {
                case K::SendEvent:
                    result = game::SendEvent(c.name) ? "taken by the graph" : "not taken by the graph";
                    break;
                case K::SetVariable:
                    result = game::SetVariable(c.variable) ? std::format("{} = {} dispatched", c.variable.name, c.variable.value)
                                                           : std::format("{}: not dispatched", c.variable.name);
                    break;
                case K::AddKeyword:
                case K::RemoveKeyword:
                    result = game::SetKeyword(c.name, c.kind == K::AddKeyword) ? "dispatched" : "failed";
                    if (std::find(keyword_check_.begin(), keyword_check_.end(), c.name) == keyword_check_.end())
                        keyword_check_.push_back(c.name);
                    keyword_check_due_ = game::Now() + 0.5;     // the VM runs the call within a frame or two
                    break;
                case K::SpendStamina:
                    if (!stamina.empty()) game::DamageActorValue(stamina, c.amount);
                    result = stamina.empty() ? "no stamina value set" : std::format("{}", c.amount);
                    break;
                case K::Log: REX::INFO("{}", c.name); continue;
                case K::RestoreHealth:
                    game::DamageActorValue("Health", -c.amount);           // a negative damage gives it back
                    result = std::format("{:.0f}", c.amount);
                    break;
                case K::ActorEvents: result = game::SendActorEvents(c.target, c.name); break;
                case K::DeferKill:
                    result = game::DeferKill(c.amount != 0.0f) ? (c.amount != 0.0f ? "on" : "off") : "not dispatched";
                    break;
                case K::Feedback: {
                    result = c.name.empty() ? "no message" : (game::Notify(c.name) ? "message" : "message not dispatched");
                    PlayEffect(c.target, result);
                    if (settings_.timed_block_shake > 0.0f)
                        result += game::ShakeCamera(settings_.timed_block_shake, settings_.timed_block_shake_time)
                                      ? "; shake" : "; shake not dispatched";
                    break;
                }
                case K::ClashBegin: {
                    const auto& cc = clash_.config();
                    auto* opp = RE::TESForm::LookupByID<RE::Actor>(c.target);
                    auto* me = game::Player();
                    clash_player_graph_ = me ? static_cast<const RE::IAnimationGraphManagerHolder*>(me) : nullptr;
                    clash_opponent_graph_ = opp ? static_cast<const RE::IAnimationGraphManagerHolder*>(opp) : nullptr;
                    clash_begin_at_ = game::Now();
                    clash_corrections_ = 0;
                    clash_heading_.reset();
                    clash_zero_have_.clear();
                    std::string zero;
                    for (auto* a : {static_cast<RE::Actor*>(me), opp}) {
                        if (!a) continue;
                        for (const auto& v : clash_zero_) {
                            float f = 0.0f;
                            if (a->GetGraphVariableImplFloat(RE::BSFixedString(v.c_str()), f)) {
                                clash_zero_have_.emplace_back(a->GetFormID(), v);
                                zero += std::format(" {:08X}.{}", a->GetFormID(), v);
                            }
                        }
                    }
                    result = std::format("zeroed each frame:{}; ", zero.empty() ? std::string(" none (no such variables)") : zero);
                    clash_active_ = true;
                    if (cc.place_opponent) result += game::PlaceFacing(c.target, c.amount);
                    if (cc.restrain_opponent)
                        result += game::SetRestrained(c.target, true) ? "; restrained" : "; restrain not dispatched";
                    if (cc.lock_camera) {
                        constexpr float kDeg = 3.14159265f / 180.0f;
                        clash_took_lock_ = Lock::Get().Hold(c.target, static_cast<float>(cc.camera_yaw) * kDeg,
                                                            static_cast<float>(cc.camera_pitch) * kDeg);
                        result += clash_took_lock_ ? "; lock-on taken" : "; lock-on already on it";
                    }
                    break;
                }
                case K::ClashEnd: {
                    const auto& cc = clash_.config();
                    clash_active_ = false;
                    clash_player_graph_ = nullptr;
                    clash_opponent_graph_ = nullptr;
                    clash_heading_.reset();
                    clash_zero_have_.clear();
                    result = std::format("{} attack presses, meter {:.2f}; ", clash_.presses(), clash_.meter());
                    Lock::Get().ClearOffset();
                    if (cc.restrain_opponent)
                        result += game::SetRestrained(c.target, false) ? "released" : "release not dispatched";
                    if (clash_took_lock_) {
                        clash_took_lock_ = false;
                        Lock::Get().Release("weapon clash over");
                        result += "; lock-on released";
                    }
                    break;
                }
                case K::Notify: result = game::Notify(c.name) ? "dispatched" : "not dispatched"; break;
                case K::Shake:
                    result = game::ShakeCamera(c.amount, c.dx / 1000.0f) ? "dispatched" : "not dispatched";
                    break;
                case K::Spark: PlayEffect(c.target, result); break;
                case K::Guard:
                    result = game::GuardActor(c.target, c.name, c.extra);
                    if (result.empty()) continue;                // already blocking: nothing sent, nothing logged
                    break;
                case K::ActorVariable:
                    result = std::format("{:08X} {} = {}: {}", c.target, c.variable.name, c.variable.value,
                                         game::SetActorVariable(c.target, c.variable) ? "dispatched" : "not dispatched");
                    break;
                case K::ToggleLock: Lock::Get().Toggle(); result = "lock-on toggled (result in the lock-on line)"; break;
                case K::SwitchTarget: Lock::Get().Switch(c.dx, c.dy); result = "switch"; break;
                case K::UnequipWeapon:
                    result = game::UnequipWeapon([](const std::string& r) { REX::INFO("stance re-equip: {}", r); })
                                 ? "dispatched" : "not dispatched";
                    break;
                case K::EquipWeapon:
                    result = game::EquipWeapon([](const std::string& r) { REX::INFO("stance re-equip: {}", r); })
                                 ? "dispatched" : "not dispatched";
                    break;
            }
            // the clash's per-press shakes, sparks and guard refreshes would fill the command log in one clash
            const bool chatty = c.kind == K::Shake || c.kind == K::Spark;
            if (!chatty && logged_commands_.fetch_add(1) < limit)
                REX::INFO("command: {} {} -> {}", kind_name(c.kind), c.name, result);
        }
    });
}

void Plugin::PlayEffect(std::uint32_t toward, std::string& result) {
    std::string effect = settings_.timed_block_effect.empty() ? auto_effect_ : settings_.timed_block_effect;
    if (effect.empty()) {
        result += "; no effect (none named, no spark set found)";
        return;
    }
    // a comma-separated list: the first that plays wins (each tried with every aim)
    std::vector<std::string> list;
    std::size_t start = 0;
    while (start <= effect.size()) {
        auto end = effect.find(',', start);
        if (end == std::string::npos) end = effect.size();
        std::string one = effect.substr(start, end - start);
        while (!one.empty() && one.front() == ' ') one.erase(one.begin());
        while (!one.empty() && one.back() == ' ') one.pop_back();
        if (!one.empty()) list.push_back(one);
        start = end + 1;
    }
    if (list.empty()) return;
    const std::vector<std::string> rest(list.begin() + 1, list.end());
    result += "; effect " + game::PlayImpactToward(list[0], settings_.timed_block_effect_node, toward, false, rest);
}

}  // namespace s2s::sfse
