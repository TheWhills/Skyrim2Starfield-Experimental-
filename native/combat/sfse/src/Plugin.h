// The plugin's state: settings, the controller, and the bridge from game callbacks to controller calls and back.
#pragma once

#include "s2s/controller.h"

namespace s2s::sfse {

struct Settings {
    bool enabled = true;
    int log_input = 40;             // first N key / button events written to the log (device, code, user event)
    int log_events = 300;           // first N animation events of the player written to the log (tag, payload)
    bool ghost_during_iframes = true;   // Actor.SetGhost while i-frames run (until a hit hook exists)
    std::string stamina_value;      // actor value EditorID the dodge cost uses ("" = no cost)
    int log_menus = 60;             // first N menu open / close events written to the log (to check the menu names)
    int log_hits = 30;              // first N hits on the player written to the log (attacker, weapon, attack event)
};

class Plugin {
public:
    static Plugin& Get();

    void LoadSettings(const std::string& ini_path);
    const Settings& settings() const { return settings_; }

    // Game callbacks (Hooks.cpp). Input and tick come on the main thread; animation events may not.
    void OnButton(std::uint32_t key, bool down, std::string_view user_event, std::uint32_t device,
                  std::int32_t id_code, float value, float held);
    void OnStick(float x, float y);
    void OnAnimEvent(std::string_view tag, std::string_view payload);
    void OnMenu(std::string_view name, bool opening);
    // The player was hit (TESHitEvent, after the game handled the hit).
    void OnHit(std::string_view attack_event, std::uint32_t aggressor, std::uint32_t weapon);
    void Tick();
    // Animation events stop being read (the layout check in Hooks.cpp failed): logged once.
    void DisableAnimEvents(std::string_view why);

private:
    void Run(std::vector<combat::Command> commands);     // carried out on the main thread
    combat::PlayerState State();

    std::mutex lock_;
    combat::Controller controller_;
    combat::MenuGate menus_;
    Settings settings_;
    std::atomic_bool anim_events_ = true;
    int logged_menus_ = 0, logged_hits_ = 0;
    float stick_x_ = 0.0f, stick_y_ = 0.0f;
    int logged_input_ = 0, logged_events_ = 0;
    bool ghost_ = false;
};

}  // namespace s2s::sfse
