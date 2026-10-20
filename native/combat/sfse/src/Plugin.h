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
    void Tick();

private:
    void Run(std::vector<combat::Command> commands);     // carried out on the main thread
    combat::PlayerState State();

    std::mutex lock_;
    combat::Controller controller_;
    Settings settings_;
    float stick_x_ = 0.0f, stick_y_ = 0.0f;
    int logged_input_ = 0, logged_events_ = 0;
    bool ghost_ = false;
};

}  // namespace s2s::sfse
