// The plugin's state: settings, the controller, and the bridge from game callbacks to controller calls and back.
#pragma once

#include "s2s/clash.h"
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
    int log_commands = 60;          // first N actions carried out (event sent, keyword set, lock) with their result
    int perf_seconds = 60;          // for this long after loading, the plugin's own time per frame / event every 10 s
    bool probe_layout = false;      // find BSAnimationGraphEvent's layout again (after a game update moved it)
    // Timed-block feedback: an impact effect (ImpactDataSet EditorID; "" = the best spark set found by the list),
    // played from this node of the player toward the attacker, and a camera shake (strength, seconds; 0 = none).
    std::string timed_block_effect;
    std::string timed_block_effect_node = "Weapon";
    float timed_block_shake = 0.4f, timed_block_shake_time = 0.15f;
    bool list_effect_forms = true;  // once per session: log the spark-like impact sets / explosions the game has
    // Preview: each press plays the next impact data set onto the floor and shows its form ID (to find the sparks for
    // sTimedBlockEffect by eye); the other key goes back one. 0 = off. Key codes as in [Keys].
    std::uint32_t effect_next_key = 0, effect_prev_key = 0;
};

class Plugin {
public:
    static Plugin& Get();

    void LoadSettings(const std::string& ini_path);
    const Settings& settings() const { return settings_; }

    // Game callbacks (Hooks.cpp). Input and tick come on the main thread; animation events may not.
    // true: hide this key event from the game (Controller::last_key_consumed)
    bool OnButton(std::uint32_t key, bool down, std::string_view user_event, std::uint32_t device,
                  std::int32_t id_code, float value, float held);
    // true: a press of `key` now must not reach the game's own controls (Controller::hides_power_press), in gameplay only
    bool HidesPowerPress(std::uint32_t key);
    std::uint32_t PowerKey() const { return controller_.config().power_key; }
    void NoteHiddenKey();                   // logged (first iLogCommands): an event kept from the game's controls
    void OnStick(float x, float y);
    void OnAnimEvent(std::string_view tag, std::string_view payload);
    void OnMenu(std::string_view name, bool opening);
    // The player was hit (TESHitEvent, after the game handled the hit).
    void OnHit(std::string_view attack_event, std::uint32_t aggressor, std::uint32_t weapon);
    bool Blocking(bool* graph_state = nullptr);
    // The player hit another actor (TESHitEvent): bForceClashOnHit starts a clash with it.
    void OnPlayerHit(std::uint32_t target);
    // A weapon clash is running and this key must not reach the game's controls (attack, block, movement).
    bool ClashHidesKey(std::uint32_t key, std::string_view user_event) const;
    bool ClashHidesMovement() const { return clash_active_ && clash_block_movement_; }
    // A weapon clash runs and this graph event for one of the two fighters is in [Clash] sBlockedEvents (not one the
    // plugin sends itself): the event is dropped (Hooks.cpp, any thread).
    bool ClashDropsEvent(const RE::IAnimationGraphManagerHolder* holder, const char* name);
    void Tick();
    // Animation events stop being read (the layout check in Hooks.cpp failed): logged once.
    void DisableAnimEvents(std::string_view why);

private:
    void Run(std::vector<combat::Command> commands);     // carried out on the main thread
    void PlayEffect(std::uint32_t toward, std::string& result);   // the sTimedBlockEffect list (timed block, clash sparks)
    // A clash with `opponent` if it may start (enabled, cooldown, chance, the actor close and alive); logged.
    std::vector<combat::Command> TryClash(std::uint32_t opponent, const char* why);
    combat::PlayerState State();

    std::mutex lock_;
    combat::Controller controller_;
    combat::MenuGate menus_;
    Settings settings_;
    std::atomic_bool anim_events_ = true;
    int logged_menus_ = 0, logged_hits_ = 0;
    std::atomic_int logged_commands_ = 0;
    std::vector<std::string> keyword_check_;     // keywords set last: checked on the player half a second later
    double keyword_check_due_ = -1.0;
    int keyword_checks_logged_ = 0;
    float stick_x_ = 0.0f, stick_y_ = 0.0f;
    int logged_input_ = 0, logged_events_ = 0, logged_hidden_ = 0, combat_logged_ = 0;
    std::atomic<bool> block_key_{false};
    std::atomic<double> block_key_at_{-10.0};
    int block_sig_ = 0, block_logs_ = 0;
    bool effects_listed_ = false;
    int effect_preview_ = -1;
    std::string auto_effect_;
    bool ghost_ = false;
    combat::Clash clash_;
    std::atomic_bool clash_active_{false};
    bool clash_block_movement_ = true;
    bool clash_took_lock_ = false;
    int clash_presses_logged_ = 0;
    std::atomic<const RE::IAnimationGraphManagerHolder*> clash_player_graph_{nullptr}, clash_opponent_graph_{nullptr};
    std::vector<std::string> clash_blocked_, clash_zero_;
    std::atomic_int clash_dropped_logged_{0};
    double clash_begin_at_ = -1.0;
    std::optional<float> clash_heading_;          // the player's heading held after the settle time
    std::vector<std::pair<std::uint32_t, std::string>> clash_zero_have_;   // (actor, variable) the graphs have           // the clash turned the lock-on on (released when it ends)
    std::uint32_t attack_key_ = 256, power_key_ = 0;
    std::array<std::uint32_t, 4> move_keys_{};
};

}  // namespace s2s::sfse
