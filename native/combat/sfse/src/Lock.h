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
    float pitch_gain = 0.5f;        // share of the up / down error fed to the camera each frame (hard lock)
    float acquire_time = 0.4f;      // a new lock swings the view onto the target over this many seconds, then holds it
    bool hard_lock = true;          // hold the view on the target every frame (TDM-like) instead of easing toward it
    bool block_look = true;         // mouse look and the right stick do not reach the game while locked
    bool aim_from_camera = true;    // aim from the camera's position (where the crosshair ray starts)
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
    // Lock onto this actor (a weapon clash): true when that changed the lock (it was off or on someone else).
    bool Hold(std::uint32_t id);
    void Release(const char* why);
    void Update();                  // once per frame
    bool active() const { return locked_.has_value(); }
    bool BlocksLook() const { return locked_.has_value() && s_.block_look; }

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
    std::optional<combat::Angles> CameraAngles();
    bool SetCameraAngles(combat::Angles a, combat::Angles look);
    const RE::ActorValueInfo* HealthInfo();
    combat::Angles Look();
    // ThirdPersonState, memory-checked at most once a second (VirtualQuery per frame cost ~1 ms: owner's run)
    std::byte* ThirdPerson();
    std::byte* camera_state_ = nullptr;
    double camera_checked_at_ = -10.0;
    // did the last write survive to the next frame? (logged every 0.5 s, 10 times per lock)
    std::optional<combat::Angles> wrote_;
    // the target itself between validations (every kRecheck s through its handle): position read each frame
    RE::NiPointer<RE::Actor> target_ref_;
    const void* camera_root_ = nullptr;       // checked once readable; re-checked when the camera's root changes
    bool origin_logged_ = false;
    double locked_at_ = -10.0;                // when the current target was taken (easing in)
    bool acquired_ = false;
    std::optional<combat::Angles> ease_from_;  // the view when the target was taken
    int ease_traces_ = 0;
    const RE::ActorValueInfo* health_info_ = nullptr;
    bool health_looked_up_ = false;
    std::optional<float> last_health_;
    int health_logs_ = 0;
    const void* checked_cam_ = nullptr;
    double target_checked_at_ = -10.0;
    double next_write_check_ = 0.0;
    int write_checks_ = 0;
    bool camera_warned_ = false;
    double next_scan_ = 0.0;
    int scans_logged_ = 0;
};

}  // namespace s2s::sfse
