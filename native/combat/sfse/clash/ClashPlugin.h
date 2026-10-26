// S2SClash: the weapon clash (s2s/clash.h) as an add-on to S2SCombat (src/ClashApi.h). S2SCombat feeds it perfect
// blocks, keys and a per-frame tick through ClashCallbacks; the clash's commands are carried out here, with
// S2SCombat's lock-on and spark effect through CombatServices.
#pragma once

#include "ClashApi.h"
#include "s2s/clash.h"

namespace s2s::clash {

class ClashPlugin {
public:
    static ClashPlugin& Get();

    void LoadSettings(const std::string& ini_path);
    void Connect(const api::CombatServices* services);   // S2SCombat's message: register the callbacks
    void InstallGraphFilter();                           // SFSE kPostDataLoad
    const api::ClashCallbacks& callbacks() const { return callbacks_; }

    // ClashCallbacks
    bool OnPerfectBlock(std::uint32_t attacker);
    void OnPlayerHit(std::uint32_t target);
    bool OnButton(std::uint32_t key, bool down, std::string_view user_event);
    bool HidesKey(std::uint32_t key, std::string_view user_event) const;
    bool HidesMovement() const { return active_ && cfg_.block_movement; }
    bool Active() const { return active_; }
    bool WantsGhost() const { return active_ && cfg_.ghost_player; }
    void Tick();
    void OnMenu(std::string_view name, bool opening, bool blocking_menu_open);

    // the graph event filter (Hooks: NotifyAnimationGraphImpl)
    bool DropsEvent(const RE::IAnimationGraphManagerHolder* holder, const char* name);

private:
    std::vector<combat::Command> TryStart(std::uint32_t opponent, const char* why);   // lock_ held
    void Run(std::vector<combat::Command> commands);                                 // on the main thread

    std::mutex lock_;
    combat::ClashConfig cfg_;
    combat::Clash clash_;
    const api::CombatServices* services_ = nullptr;
    api::ClashCallbacks callbacks_;
    std::atomic_bool active_{false};
    bool took_lock_ = false;
    int presses_logged_ = 0, log_commands_ = 60;
    std::atomic_int commands_logged_{0};
    std::atomic<const RE::IAnimationGraphManagerHolder*> player_graph_{nullptr}, opponent_graph_{nullptr};
    std::vector<std::string> blocked_, zero_;
    std::atomic_int filter_logged_{0};
    double begin_at_ = -1.0, trace_at_ = 0.0;
    int traces_ = 0, corrections_ = 0;
    std::optional<float> heading_;                                   // the player's heading held after the settle time
    std::vector<std::pair<std::uint32_t, std::string>> zero_have_;   // (actor, variable) the graphs have
};

}  // namespace s2s::clash
