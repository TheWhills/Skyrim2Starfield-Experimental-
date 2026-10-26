// Weapon clash: a Cinematic Clash style standoff (the Skyrim mod's behaviour as described by its INI; no code taken).
//
// A clash starts when the player perfect-blocks a melee hit (the Starfield stand-in for two blades meeting: Starfield
// has no weapon-on-weapon collision). Both fighters hold their guard, locked together; the player mashes attack to push
// a meter (0..1, starting at 0.5) toward 1 while the opponent pushes it back toward 0 at a steady rate. The meter at 1
// is a win (the opponent staggers), at 0 a loss (the player staggers); when the time runs out it is a draw (both
// recoil) or, with timeout_resolution, a win for whichever side the meter favours.
//
// Game-independent: the plugin feeds it the trigger, attack presses and a tick, and carries out the commands
// (s2s/controller.h Command) it returns. Tested in tests/test_clash.cpp.
#pragma once

#include "s2s/controller.h"

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace s2s::combat {

struct ClashConfig {
    bool enabled = true;
    bool on_perfect_block = true;      // a perfect block starts a clash (instead of the attacker's parry stagger)
    double trigger_chance = 100.0;     // percent
    double cooldown = 1.0;             // seconds between two clashes (from the end of one)
    double max_start_distance = 3.0;   // game units between the two (checked by the game side)
    double duration = 5.0;
    double press_gain = 0.09;          // meter per attack press
    int mode = 1;                      // 0 easy, 1 normal, 2 hard
    double presses_per_second[3] = {3.0, 4.0, 5.0};   // the opponent's push, as the press rate that holds the meter still
    bool hold_to_mash = false;         // a held attack button counts as presses at the difficulty's rate
    int timeout_resolution = 0;        // 0: the timer running out is a draw; 1: the side the meter favours wins
    // Seconds at the start before the opponent pushes (the guard comes up, the camera swings round, the message
    // shows): owner's run 2026-10-26 lost every clash in 1.4 s before any press could land.
    double grace_time = 1.0;
    double clash_distance = 0.7;       // owner: 1.0 looked a little far       // game units between the two while locked (the opponent is placed there)
    // Graph events, tried in order until the actor's graph takes one (comma-separated). Empty = none.
    // Sent once to both at the start, before the guard: an attack still running keeps the graph out of its block
    // states (Cinematic Clash interrupts it the same way in Skyrim; Starfield names: the plugin's cancel event).
    std::string interrupt_events = "ActionInterrupt";
    std::string guard_events = "BlockStart";                         // both sides, at the start and to keep the guard up
    double guard_interval = 0.5;                                     // the guard event is sent again this often
    std::string guard_variable = "iWantBlock";                       // opponent's int set to 1 while locked ("" = none)
    std::string loser_events = "StaggerStart, recoilLargeStart, recoilStart";
    std::string winner_events;                                       // the winner's (none by default)
    std::string draw_events = "recoilStart, StaggerStart";
    // Float graph variable set on whoever staggers, just before the events: loser / draw magnitude (Skyrim's
    // staggerMagnitude; whether Starfield's graph reads it is unresolved). Empty = not set.
    std::string stagger_variable = "staggerMagnitude";
    double loser_magnitude = 1.0, draw_magnitude = 0.25;
    std::string end_events = "BlockStop";                            // the player's graph, when the clash is over
    // Feedback (no on-screen meter yet: the messages say how it is going).
    bool messages = true;
    std::string start_message = "Weapon clash! Mash attack!";
    std::string start_message_hold = "Weapon clash! Hold attack!";
    std::string win_message = "You overpowered your opponent!";
    std::string lose_message = "You were overpowered!";
    std::string draw_message = "Neither of you gives way!";
    std::string winning_message = "Pushing them back...";            // the meter crossing 0.75 toward the player
    std::string losing_message = "Losing ground...";                 // the meter crossing 0.25 toward the opponent
    bool shake_on_press = true;
    float shake_strength = 0.12f;
    double spark_interval = 0.25;                                    // seconds between spark bursts (0 = none)
    // Game side (carried out by the plugin for ClashBegin / ClashEnd):
    bool place_opponent = true;       // move the opponent to clash_distance in front of the player, facing them
    bool restrain_opponent = true;    // Actor.SetRestrained on the opponent while locked (no attacks, no walking off)
    bool lock_camera = true;          // lock-on to the opponent for the clash (released after unless it was on before)
    // The lock-on's view turned this far off the opponent while locked (degrees; yaw + = the camera swings round to the
    // player's left so both fighters show side-on, pitch + = looks further down). 0 / 0 = straight at them.
    double camera_yaw = 35.0, camera_pitch = 5.0;
    bool block_movement = true;       // movement keys / stick and the block key do not reach the game while locked
    bool ghost_player = true;         // the player takes no hits while locked (Actor.SetGhost)
    bool force_on_hit = false;        // testing: every melee hit the player lands on an actor starts a clash
};

// "[Clash]" section of the plugin INI; unknown keys and unreadable values go to `problems`.
ClashConfig parse_clash_config(std::string_view ini, std::vector<std::string>* problems = nullptr);

// A perfect block's commands (Controller::on_hit) turned into a clash trigger: removes the parry events sent to
// `attacker` (the clash replaces the attacker's stagger) and returns whether there were any - i.e. whether the hit
// was a perfect block from a known attacker.
bool take_perfect_block(std::vector<Command>& cmds, std::uint32_t attacker);

class Clash {
public:
    enum class Outcome : std::uint8_t { None, Win, Lose, Draw, Abort };

    explicit Clash(ClashConfig cfg = {}) : cfg_(std::move(cfg)) {}
    const ClashConfig& config() const { return cfg_; }

    // Whether a clash may start now (enabled, not running, cooldown over, the chance roll in 0..100 under the chance).
    bool can_start(double t, double roll) const;
    // Starts a clash against `opponent` (form ID); empty when it may not start.
    std::vector<Command> start(std::uint32_t opponent, double t, double roll = 0.0);
    // The attack key during a clash (down / up). Returns the commands; `consumed` = keep the key from the game.
    std::vector<Command> on_attack(bool down, double t);
    std::vector<Command> tick(double t);
    // Ends a running clash without a winner (opponent dead / gone / too far, a menu, a load).
    std::vector<Command> abort(double t, std::string_view why);

    bool active() const { return active_; }
    std::uint32_t opponent() const { return opponent_; }
    double meter() const { return meter_; }
    int presses() const { return presses_; }   // attack presses counted in the running / last clash
    Outcome last_outcome() const { return outcome_; }
    // the opponent's push per second
    double push_rate() const;

private:
    std::vector<Command> finish(Outcome o, double t);
    void guard(std::vector<Command>& out, double t);

    ClashConfig cfg_;
    bool active_ = false, held_ = false;
    std::uint32_t opponent_ = 0;
    double meter_ = 0.5, started_ = 0.0, last_tick_ = 0.0, ended_ = -1e9;
    double next_guard_ = 0.0, next_spark_ = 0.0;
    int zone_ = 0, presses_ = 0;     // -1 losing (meter < 0.25), 0 middle, 1 winning (> 0.75): messages on entering a zone
    Outcome outcome_ = Outcome::None;
};

}  // namespace s2s::combat
