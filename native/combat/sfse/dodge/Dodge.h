// S2SDodge: the standalone dodge plugin (s2s/dodge_only.h). The same Controller as S2SCombat with every other system
// off; only the dodge's commands are carried out. Hooks: UI's input receiver (watch only, as S2SCombat's), the player's
// animation-graph event sink (dodge end, attack phase) and menu open / close (keys in menus are not gameplay).
#pragma once

#include "s2s/controller.h"

namespace s2s::dodge {

struct Settings {
    bool enabled = true;
    bool ghost_during_iframes = true;
    std::string stamina_value;
    int log_input = 20, log_events = 0, log_commands = 40;
};

class Plugin {
public:
    static Plugin& Get();
    void LoadSettings(const std::string& ini_path);
    const Settings& settings() const { return settings_; }
    void Disable(std::string_view why);

    void OnButton(std::uint32_t key, bool down, std::string_view user_event);
    void OnStick(float x, float y);
    void OnAnimEvent(std::string_view tag, std::string_view payload);
    void OnMenu(std::string_view name, bool opening);
    void Tick();

private:
    void Run(std::vector<combat::Command> commands);
    combat::PlayerState State() const;

    std::mutex lock_;
    combat::Controller controller_;
    combat::MenuGate menus_;
    Settings settings_;
    float stick_x_ = 0.0f, stick_y_ = 0.0f;
    int logged_input_ = 0, logged_events_ = 0;
    std::atomic_int logged_commands_ = 0;
    bool ghost_ = false;
};

// Hooks.cpp of S2SDodge: call once the game data is loaded; safe to call again.
bool InstallHooks();

}  // namespace s2s::dodge
