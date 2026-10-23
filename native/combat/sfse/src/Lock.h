// Lock-on (True Directional Movement style, docs/armor/lock-on-design.md): target choice and switching are the tested
// core (s2s::combat::LockOn); this side gathers the candidates and steers the player's angle toward the target each
// frame. With a weapon drawn, Starfield's third-person camera follows the player's heading, so steering the heading
// turns the camera too (supported hypothesis: Skyrim / Fallout 4 lock-on mods work this way; the camera's own yaw is
// not mapped in CommonLibSF). All on the main thread.
#pragma once

#include "s2s/combat.h"
#include "s2s/controller.h"

namespace s2s::sfse {

struct LockSettings {
    float max_distance = 28.0f;     // game units; Starfield's world units are taken as metres (logged on lock to check)
    float target_height = 1.3f;     // aim point above the target's feet, game units
    float eye_height = 1.6f;        // the player's look point above the feet
    float yaw_rate = 8.0f, pitch_rate = 2.0f;
    bool steer_pitch = true;
    // Turn the player's heading toward the target. Off by default: owner, 2026-10-23 - the player turned but Starfield's
    // third-person camera did not follow (its own yaw / pitch are not mapped yet; see CameraProbe).
    bool steer_player = false;
    bool steer_camera = true;       // turn the third-person camera toward the target (ThirdPersonState rotation)
    int camera_samples = 0;         // while locked: camera rotation + third-person state floats, every 0.5 s, N times
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
    // every nearby actor (key presses), or with `only` just the actor behind that handle (each frame while locked:
    // owner's run 2026-10-23, gathering all ~76 actors every frame cost 5-36 ms per frame)
    std::vector<combat::Candidate> Gather(combat::Angles look, combat::Vec3 eye,
                                          std::optional<std::uint32_t> only = std::nullopt);
    void SetLocked(std::optional<std::uint32_t> id, const char* why);

    LockSettings s_;
    combat::LockOn core_;
    std::optional<std::uint32_t> locked_;
    double last_ = -1.0;
    int logged_ = 0;
    bool diagnosed_ = false, cell_list_bad_ = false, cell_bad_logged_ = false;
    // The high-process actor array's place in ProcessLists, found at run time (combat::scan_handle_arrays).
    std::vector<combat::HandleArray> actors_at_;
    std::unordered_map<std::uint32_t, std::uint32_t> handle_of_;     // FormID -> actor handle, from the last full gather
    double next_report_ = 0.0, next_camera_ = 0.0;
    int camera_logged_ = 0;
    std::vector<float> camera_last_;
    void CameraProbe(double now, float player_yaw);
    // The third-person camera's rotation (ThirdPersonState +0x170, when that state is the current one and the value is
    // a unit quaternion); nullopt otherwise. Look() falls back to the player's heading.
    std::optional<combat::Angles> CameraAngles() const;
    bool SetCameraAngles(combat::Angles a) const;
    combat::Angles Look() const;
    bool camera_warned_ = false;
    double next_scan_ = 0.0;
    int scans_logged_ = 0;
};

}  // namespace s2s::sfse
