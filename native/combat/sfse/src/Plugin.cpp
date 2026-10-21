#include "Plugin.h"

#include "Game.h"

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
        case K::Log: return "log";
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

    const auto plugin = combat::ini_section(ini, "Plugin");
    settings_.enabled = to_int(plugin, "benabled", 1) != 0;
    settings_.log_input = to_int(plugin, "ilogkeys", settings_.log_input);
    settings_.log_events = to_int(plugin, "iloganimevents", settings_.log_events);
    settings_.ghost_during_iframes = to_int(plugin, "bghostduringiframes", 1) != 0;
    if (auto it = plugin.find("sstaminaactorvalue"); it != plugin.end()) settings_.stamina_value = it->second;
    settings_.log_menus = to_int(plugin, "ilogmenus", settings_.log_menus);
    settings_.log_hits = to_int(plugin, "iloghits", settings_.log_hits);
    if (auto it = plugin.find("sblockingmenus"); it != plugin.end() && !it->second.empty())
        menus_ = combat::MenuGate(combat::MenuGate::parse_list(it->second));

    std::scoped_lock l(lock_);
    controller_ = combat::Controller(cfg, bindings);
    REX::INFO("settings: {} key bindings, attack key {}, dodge key {}, buffer {}, plugin event host '{}'",
              bindings.size(), cfg.attack_key, cfg.dodge_key, cfg.buffer_attacks ? "on" : "off",
              cfg.plugin_event_host);
}

combat::PlayerState Plugin::State() {
    combat::PlayerState s;
    s.stick_x = stick_x_;
    s.stick_y = stick_y_;
    if (!settings_.stamina_value.empty()) {
        float v = game::ActorValue(settings_.stamina_value);
        if (v >= 0.0f) s.stamina = v;
    }
    // UNVERIFIED / TODO: staggered state (no mapped flag yet): dodging out of a stagger is not blocked.
    return s;
}

void Plugin::OnButton(std::uint32_t key, bool down, std::string_view user_event, std::uint32_t device,
                      std::int32_t id_code, float value, float held) {
    if (!settings_.enabled) return;
    if (logged_input_ < settings_.log_input) {
        ++logged_input_;
        REX::INFO("key: device {} id 0x{:X} -> code {} {} (value {}, held {:.2f}) user event '{}'", device, id_code,
                  key, down ? "down" : "up", value, held, user_event);
    }
    if (key == 0) return;
    // Presses only count in gameplay: a save loaded (the player is in a cell) and no menu that takes the keys open.
    // Releases always go through, so a key held into a menu is not left "down".
    if (down) {
        auto* player = game::Player();
        if (!player || !player->parentCell || menus_.blocked()) return;
    }
    auto state = State();
    std::vector<combat::Command> cmds;
    {
        std::scoped_lock l(lock_);
        cmds = controller_.on_key(key, down, game::Now(), state);
    }
    Run(std::move(cmds));
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
}

void Plugin::OnHit(std::string_view attack_event, std::uint32_t aggressor, std::uint32_t weapon) {
    if (!settings_.enabled) return;
    // Blocking: the melee graph's own variable for a held block (MeleeActions: BlockStart needs iWantBlock = 1).
    std::int32_t want_block = 0;
    auto* player = game::Player();
    const bool read = player && player->GetGraphVariableImplInt(RE::BSFixedString("iWantBlock"), want_block);
    const auto kind = combat::hit_kind(attack_event);
    const double now = game::Now();
    std::vector<combat::Command> cmds;
    bool invulnerable = false;
    {
        std::scoped_lock l(lock_);
        invulnerable = controller_.invulnerable(now);
        cmds = controller_.on_hit(kind, want_block != 0, now);
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
    }
    Run(std::move(cmds));
    if (settings_.ghost_during_iframes && invulnerable != ghost_) {
        ghost_ = invulnerable;
        SFSE::GetTaskInterface()->AddTask([g = ghost_]() { game::SetGhost(g); });
    }
}

void Plugin::Run(std::vector<combat::Command> commands) {
    if (commands.empty()) return;
    const std::string stamina = settings_.stamina_value;
    SFSE::GetTaskInterface()->AddTask([cmds = std::move(commands), stamina]() {
        using K = combat::Command::Kind;
        for (const auto& c : cmds) {
            switch (c.kind) {
                case K::SendEvent: {
                    bool ok = game::SendEvent(c.name);
                    REX::DEBUG("send {}: {}", c.name, ok ? "taken" : "not taken by the graph");
                    break;
                }
                case K::SetVariable: game::SetVariable(c.variable); break;
                case K::AddKeyword: game::SetKeyword(c.name, true); break;
                case K::RemoveKeyword: game::SetKeyword(c.name, false); break;
                case K::SpendStamina:
                    if (!stamina.empty()) game::DamageActorValue(stamina, c.amount);
                    break;
                case K::Log: REX::INFO("{}", c.name); break;
                case K::ToggleLock:
                case K::SwitchTarget:
                    // TODO (lock-on-design.md): needs the third-person camera mapped; the core LockOn is ready.
                    REX::INFO("{}: lock-on is not wired to the game yet", kind_name(c.kind));
                    break;
            }
        }
    });
}

}  // namespace s2s::sfse
