#include "Dodge.h"

#include "Game.h"
#include "s2s/dodge_only.h"

namespace s2s::dodge {
namespace {

int to_int(const std::map<std::string, std::string>& m, const char* key, int fallback) {
    auto it = m.find(key);
    if (it == m.end() || it->second.empty()) return fallback;
    try {
        return std::stoi(it->second);
    } catch (...) {
        REX::WARN("[Plugin] {} = {}: not a number, {} kept", key, it->second, fallback);
        return fallback;
    }
}

}  // namespace

Plugin& Plugin::Get() {
    static Plugin instance;
    return instance;
}

void Plugin::LoadSettings(const std::string& ini_path) {
    std::ifstream in(ini_path);
    std::string ini;
    if (in) {
        std::stringstream buf;
        buf << in.rdbuf();
        ini = buf.str();
    } else {
        REX::WARN("{} not found: defaults used (Left Alt, events MeleeAttack01-04)", ini_path);
    }
    std::vector<std::string> problems;
    auto cfg = combat::parse_dodge_config(ini, &problems);
    for (const auto& p : problems) REX::WARN("{}", p);
    const auto plugin = combat::ini_section(ini, "Plugin");
    settings_.enabled = to_int(plugin, "benabled", 1) != 0;
    settings_.ghost_during_iframes = to_int(plugin, "bghostduringiframes", 1) != 0;
    if (auto it = plugin.find("sstaminaactorvalue"); it != plugin.end()) settings_.stamina_value = it->second;
    settings_.log_input = to_int(plugin, "ilogkeys", settings_.log_input);
    settings_.log_events = to_int(plugin, "iloganimevents", settings_.log_events);
    settings_.log_commands = to_int(plugin, "ilogcommands", settings_.log_commands);
    std::scoped_lock l(lock_);
    controller_ = combat::Controller(cfg);
    std::string evs;
    for (const auto& e : cfg.dodge_events) evs += (evs.empty() ? "" : ", ") + (e.empty() ? std::string("-") : e);
    REX::INFO("settings: dodge key {}, events [{}], i-frames {:.2f} s, {}-way{}", cfg.dodge_key, evs, cfg.dodge_iframes,
              cfg.dodge.eight_way ? 8 : 4, settings_.enabled ? "" : " (bEnabled = 0: off)");
}

void Plugin::Disable(std::string_view why) {
    if (settings_.enabled) REX::WARN("S2SDodge off: {}", why);
    settings_.enabled = false;
}

combat::PlayerState Plugin::State() const {
    combat::PlayerState s;
    s.stick_x = stick_x_;
    s.stick_y = stick_y_;
    if (!settings_.stamina_value.empty()) {
        const float v = game::ActorValue(settings_.stamina_value);
        if (v >= 0.0f) s.stamina = v;
    }
    return s;
}

void Plugin::OnButton(std::uint32_t key, bool down, std::string_view user_event) {
    if (!settings_.enabled || key == 0) return;
    if (logged_input_ < settings_.log_input) {
        ++logged_input_;
        REX::INFO("key: code {} {} user event '{}'", key, down ? "down" : "up", user_event);
    }
    // presses count only in gameplay (a save loaded, no menu that takes the keys); releases always go through
    if (down) {
        auto* player = game::Player();
        if (!player || !player->parentCell || menus_.blocked()) return;
    }
    const auto state = State();
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

void Plugin::OnAnimEvent(std::string_view tag, std::string_view payload) {
    if (!settings_.enabled) return;
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

void Plugin::OnMenu(std::string_view name, bool opening) { menus_.on_menu(name, opening); }

void Plugin::Tick() {
    if (!settings_.enabled) return;
    const double now = game::Now();
    const auto state = State();
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
    std::erase_if(commands, [](const combat::Command& c) { return !combat::dodge_only_command(c.kind); });
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
                case K::SpendStamina:
                    if (!stamina.empty()) game::DamageActorValue(stamina, c.amount);
                    result = stamina.empty() ? "no stamina value set" : std::format("{}", c.amount);
                    break;
                case K::Log:
                    if (logged_commands_.fetch_add(1) < limit) REX::INFO("{}", c.name);
                    continue;
                default:
                    continue;
            }
            if (logged_commands_.fetch_add(1) < limit)
                REX::INFO("{} '{}': {}", c.kind == K::SendEvent ? "event" : "stamina", c.name, result);
        }
    });
}

}  // namespace s2s::dodge
