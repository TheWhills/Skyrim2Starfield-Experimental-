// The plugin's state: settings, the controller, and the bridge from game callbacks to controller calls and back.
#pragma once

#include "ClashApi.h"
#include "s2s/controller.h"
#include "s2s/left_blade.h"

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
    // Dual wield: the worn left blade is taken off when the weapon is sheathed and put on again when it is drawn
    // (s2s/left_blade.h). left_blade_node: part of the blade's node name, for the 3D listing in the log.
    std::string left_blade_node = "longsword_left";
    bool hide_left_sheathed = true;
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
    // The player hit another actor (TESHitEvent): passed to the clash add-on (bForceClashOnHit).
    void OnPlayerHit(std::uint32_t target);
    // The weapon clash add-on (S2SClash.dll, src/ClashApi.h): its callbacks once it registered, else none.
    void RegisterClash(const api::ClashCallbacks* cb) { clash_ = cb; }
    const api::ClashCallbacks* Clash() const { return clash_.load(); }
    bool ClashActive() const { auto* c = clash_.load(); return c && c->active(); }
    // A clash runs and this key press / the left stick must not reach the game's controls.
    bool ClashHidesKey(std::uint32_t key, std::string_view user_event) const;
    bool ClashHidesMovement() const { auto* c = clash_.load(); return c && c->hides_movement(); }
    const combat::ControllerConfig& ControllerConfig() { return controller_.config(); }
    void PlayEffect(std::uint32_t toward, std::string& result);   // the sTimedBlockEffect list (timed block, clash sparks)
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
    int logged_menus_ = 0, logged_hits_ = 0, logged_player_hits_ = 0;
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
    // dual wield: the worn-keyword poll (every 0.5 s) and its last answer (-1 none yet, 0 / 1)
    double dual_poll_at_ = 0.0;
    std::atomic_int dual_worn_{-1};
    int dual_applied_ = -1;
    bool dual_missing_logged_ = false;
    // the left blade put away while sheathed (left_blade_ under lock_). A poll answer counts only if no equip /
    // unequip of the blade happened since it was asked (poll_gen_): an older one says what was worn before.
    combat::LeftBlade left_blade_;
    std::atomic_int poll_gen_{0}, worn_gen_{0};
    std::atomic_int left_action_{0};              // a LeftBlade::Action from the animation events, done in Tick
    std::atomic_int drawn_answer_{-1};            // Papyrus IsWeaponDrawn, asked once when the blade is first worn
    std::vector<std::uint32_t> blades_;           // the left blade ARMOs (S2SWeapons.esm)
    bool blades_searched_ = false;
    std::atomic<std::uint32_t> blade_id_{0};      // the one worn (or put away by us)
    // whether a worn (ARMO) blade is on, from the previous poll: only that one is put away while sheathed (the pair
    // weapon carries the keyword too and sheathes by itself)
    std::atomic_bool armor_blade_on_{false};
    std::atomic_int weapon_dual_{-1};             // the right-hand weapon carries the keyword (the pair weapon)
    std::atomic_int armor_hits_{0};
    // the stance re-equip takes the weapon off for a moment: the pair weapon's keyword is not worn then, so the polls
    // wait until it is back (owner's run 2026-10-26: dual -> one-handed right after every switch)
    combat::ReequipHold reequip_hold_;           // main thread (Tick, and Run's task)
    // after a load: 1 = to ask, 2 = asked (answers_ of blades_.size() item counts), 0 = done
    int restore_ = 1;
    std::atomic_int restore_answers_{0};
    std::atomic<std::uint32_t> blade_in_bag_{0};
    int dumps_ = 0, left_logs_ = 0;
    std::atomic<const api::ClashCallbacks*> clash_{nullptr};
};

// S2SCombat's side of src/ClashApi.h: sent to every plugin at SFSE's PostLoad (main.cpp).
const api::CombatServices* Services();

}  // namespace s2s::sfse
