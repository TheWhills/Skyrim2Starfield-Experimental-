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
    // graph bools set true on the player while a dodge runs, false after (Papyrus SetAnimationVariableBool)
    std::vector<std::string> dodge_bools;
    // graph variables logged at each dodge's start and 0.25 s into it ("name" = bool, "name:i" int, "name:f" float)
    std::vector<std::string> log_variables;
    int log_dodges = 20;
    bool use_osf_settings = true;   // take the dodge key from OSF Settings' Keybindings when it is installed
};

// The controller's dodge key while OSF Settings delivers the press (never a real SFSE key code).
inline constexpr std::uint32_t kOsfDodgeKey = 0xFFFF0001u;
// SFSE key codes from here on are gamepad buttons (InputMap::kMacro_GamepadOffset): an INI gamepad dodge key keeps
// working next to the OSF Settings keyboard binding.
inline constexpr std::uint32_t kGamepadKeys = 266;

class Plugin {
public:
    static Plugin& Get();
    void LoadSettings(const std::string& ini_path);
    const Settings& settings() const { return settings_; }
    void Disable(std::string_view why);
    // At SFSE kPostLoad: register the dodge hotkey with OSF Settings when it is installed (schema s2sdodge.json).
    void ConnectOsfSettings();
    void OnOsfDodge();

    void OnButton(std::uint32_t key, bool down, std::string_view user_event);
    void OnStick(float x, float y);
    void OnAnimEvent(std::string_view tag, std::string_view payload);
    void OnMenu(std::string_view name, bool opening);
    void Tick();

private:
    void Run(std::vector<combat::Command> commands);
    void OnDodgeChange(bool dodging, double now);
    std::string Variables() const;
    combat::PlayerState State() const;

    std::mutex lock_;
    combat::Controller controller_;
    combat::ControllerConfig cfg_;
    std::uint32_t ini_dodge_key_ = 56;
    std::atomic_bool osf_dodge_{false};
    combat::MenuGate menus_;
    Settings settings_;
    float stick_x_ = 0.0f, stick_y_ = 0.0f;
    int logged_input_ = 0, logged_events_ = 0;
    std::atomic_int logged_commands_ = 0;
    bool ghost_ = false;
    bool was_dodging_ = false;
    double dodge_started_ = -1.0;      // >= 0: the mid-dodge log line is still due
    int dodges_logged_ = 0;
};

// Hooks.cpp of S2SDodge: call once the game data is loaded; safe to call again.
bool InstallHooks();

}  // namespace s2s::dodge
