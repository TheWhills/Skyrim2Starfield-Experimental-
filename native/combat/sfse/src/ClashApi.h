// The link between S2SCombat.dll and its add-on S2SClash.dll (the weapon clash, s2s/clash.h).
//
// S2SCombat owns the hooks (input, hit events, the player's controls) and the lock-on camera; S2SClash owns the clash.
// At SFSE's PostLoad, S2SCombat sends every plugin a message (sender "S2SCombat", type kMessage) whose data is its
// CombatServices; S2SClash answers by calling register_clash with its ClashCallbacks. Without S2SClash nothing changes
// in S2SCombat (a perfect block keeps its parry stagger). Plain function pointers: the two DLLs share no C++ objects.
#pragma once

#include <cstdint>

namespace s2s::api {

constexpr std::uint32_t kMessage = 0x53325331;   // 'S2S1'
constexpr std::uint32_t kVersion = 1;

// Implemented by S2SClash; S2SCombat calls these.
struct ClashCallbacks {
    std::uint32_t version = kVersion;
    // A perfect block (any thread): true = a clash starts, S2SCombat drops the attacker's parry stagger.
    bool (*on_perfect_block)(std::uint32_t attacker) = nullptr;
    // The player's hit landed on `target` (any thread; bForceClashOnHit).
    void (*on_player_hit)(std::uint32_t target) = nullptr;
    // A key in gameplay (main thread): true = S2SCombat does nothing else with it (the clash took it).
    bool (*on_button)(std::uint32_t key, bool down, const char* user_event) = nullptr;
    // Whether this key press / the left stick must not reach the game's controls now (main thread).
    bool (*hides_key)(std::uint32_t key, const char* user_event) = nullptr;
    bool (*hides_movement)() = nullptr;
    bool (*active)() = nullptr;           // a clash is running
    bool (*wants_ghost)() = nullptr;      // keep the player ghosted (S2SCombat owns Actor.SetGhost for i-frames)
    void (*tick)() = nullptr;             // once per frame, main thread
    void (*on_menu)(const char* name, bool opening, bool blocking_menu_open) = nullptr;
};

// Implemented by S2SCombat; S2SClash calls these (main thread).
struct CombatServices {
    std::uint32_t version = kVersion;
    void (*register_clash)(const ClashCallbacks* callbacks) = nullptr;
    // Lock-on: hold the view on `id`, yaw turned `yaw_offset` radians off it, pitch held at `pitch` radians when
    // `fixed_pitch`; true when that changed the lock (it was off or on someone else).
    bool (*lock_hold)(std::uint32_t id, float yaw_offset, float pitch, bool fixed_pitch) = nullptr;
    void (*lock_release)(const char* why) = nullptr;
    void (*lock_clear_offset)() = nullptr;
    // S2SCombat's [Plugin] sTimedBlockEffect, played toward `toward` (the clash sparks).
    void (*play_effect)(std::uint32_t toward) = nullptr;
    // Key codes S2SCombat is configured with: attack, power attack, the four move keys.
    std::uint32_t (*attack_key)() = nullptr;
    std::uint32_t (*power_key)() = nullptr;
    std::uint32_t (*move_key)(int index) = nullptr;
};

}  // namespace s2s::api
