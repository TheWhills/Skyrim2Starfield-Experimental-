// Lock-on (True Directional Movement style, docs/armor/lock-on-design.md): target choice and switching are the tested
// core (s2s::combat::LockOn); this side gathers the candidates and steers the player's angle toward the target each
// frame. With a weapon drawn, Starfield's third-person camera follows the player's heading, so steering the heading
// turns the camera too (supported hypothesis: Skyrim / Fallout 4 lock-on mods work this way; the camera's own yaw is
// not mapped in CommonLibSF). All on the main thread.
#pragma once

#include "s2s/combat.h"

namespace s2s::sfse {

struct LockSettings {
    float max_distance = 28.0f;     // game units; Starfield's world units are taken as metres (logged on lock to check)
    float target_height = 1.3f;     // aim point above the target's feet, game units
    float eye_height = 1.6f;        // the player's look point above the feet
    float yaw_rate = 8.0f, pitch_rate = 2.0f;
    bool steer_pitch = true;
    float pitch_sign = 1.0f;        // -1 if the first run shows the camera tilting the wrong way
    bool hostile_only = true;
    std::string lock_variable = "TDM_TargetLock";   // graph bool for movesets' TDM conditions ("" = none)
    int log_targets = 20;
};

class Lock {
public:
    static Lock& Get();
    void Configure(const LockSettings& s);
    void Toggle();
    void Switch(int dx, int dy);
    void Update();                  // once per frame
    bool active() const { return locked_.has_value(); }

private:
    std::vector<combat::Candidate> Gather(combat::Angles look, combat::Vec3 eye);
    void SetLocked(std::optional<std::uint32_t> id, const char* why);

    LockSettings s_;
    combat::LockOn core_;
    std::optional<std::uint32_t> locked_;
    double last_ = -1.0;
    int logged_ = 0;
    bool diagnosed_ = false;
};

}  // namespace s2s::sfse
