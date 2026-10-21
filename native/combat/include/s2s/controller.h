// Skyrim -> Starfield combat: the per-player controller that ties the core pieces together (docs/armor/combat-plugin-spec.md).
//
// The SFSE side feeds it three things (keys, animation-graph events, a per-frame tick) and carries out the commands it
// returns (send a graph event, set a graph variable, add / remove a keyword, ...). It holds no game types, so the
// whole decision logic is tested here (tests/test_controller.cpp); the game side stays a thin translation layer.
//
// Key codes are SFSE InputMap codes, the same numbering as Key Utils / SKSE: keyboard = DirectInput scan code
// (0-255: 17 W, 56 left Alt, 200 up arrow), mouse buttons 256-263 (256 left), wheel 264 / 265, gamepad 266-281.
#pragma once

#include "s2s/combat.h"

#include <array>
#include <cstdint>
#include <map>
#include <string>
#include <string_view>
#include <vector>

namespace s2s::combat {

// Starfield input -> key code. Keyboard events carry a Windows virtual-key code (supported: OSF Animation's runtime
// notes); returns the DirectInput scan code (US layout positions), or 0 for keys without one. Mouse buttons carry
// the button index, the wheel 0x800 (up) / 0x900 (down). Gamepad buttons: SFSE::InputMap::GamepadMaskToKeycode.
std::uint32_t key_from_vk(std::uint32_t vk);
std::uint32_t key_from_mouse(std::uint32_t id);     // 0 for unknown ids

// What the game side must do. Commands come out in the order they should be carried out.
struct Command {
    enum class Kind : std::uint8_t {
        SendEvent,       // name: graph event for the player's graph
        SetVariable,     // variable: graph variable assignment
        AddKeyword,      // name: keyword EditorID to add to the player
        RemoveKeyword,   // name: keyword EditorID to remove from the player
        SpendStamina,    // amount: actor value to damage (only when the game side has a stamina value configured)
        ToggleLock,      // lock-on on / off
        SwitchTarget,    // dx / dy: screen direction
        Log,             // name: text for the plugin log (unknown payload instructions, ...)
    };
    Command(Kind k, std::string n = {}) : kind(k), name(std::move(n)) {}
    Kind kind;
    std::string name;
    VariableSet variable{VariableSet::Type::Int, "", 0.0};
    float amount = 0.0f;
    int dx = 0, dy = 0;
};

// Settings ([Combat] section of the plugin INI; defaults = the Skyrim mods' defaults, see the spec).
struct ControllerConfig {
    bool buffer_attacks = true;
    double buffer_time = 0.35, power_hold = 0.30, charge_hold = 0.80;
    std::uint32_t attack_key = 256;                            // left mouse button
    std::uint32_t dodge_key = 56;                              // left Alt (TK Dodge's default)
    std::array<std::uint32_t, 4> move_keys{17, 31, 30, 32};    // forward W, back S, left A, right D
    DodgeConfig dodge{false, Direction::Back, 0.15f, 0.0f, true};   // no stamina cost until a Starfield value is chosen
    double dodge_iframes = 0.3;                                // seconds of invulnerability from the dodge press
    double annotation_iframes = 0.3;                           // TKDR_IframeDuration without its own duration
    std::string attack_event = "MeleeAttackStart";             // Starfield melee graph events (verified names)
    std::string power_event = "MeleeAttackPowerStart";
    // Clip events built for the plugin: "" = Skyrim's own split (event "PIE", payload "@SGVI|..."); otherwise the
    // name of the host event that carries the whole Skyrim annotation in its payload (if the graph drops unknown
    // event names: unresolved, see the spec).
    std::string plugin_event_host;
    // Graph events sent after a stance change (Skyrim's Stances sends blockStart / blockStop so the animation set is
    // picked again; whether Starfield needs this is unresolved). Empty = none.
    std::vector<std::string> stance_refresh_events;
    // Graph variable set when the player is hit while blocking: 0 normal attack, 1 power attack (Dynamic Block Hit's
    // NA / PA variants; the graph picks a block-hit clip by it once variant states exist). Empty = not set.
    std::string block_hit_variable = "iS2SBlockHitType";
};

// What hit the player: from the attack data's event name (Starfield: MeleeAttackPowerStart for power attacks,
// supported hypothesis; the plugin logs the names it sees).
enum class HitKind : std::uint8_t { Unknown, Normal, Power };
HitKind hit_kind(std::string_view attack_event);

// "key = value" lines of one INI section (keys lower-cased; ';' / '#' comments; later lines win).
std::map<std::string, std::string> ini_section(std::string_view ini, std::string_view section);
// ControllerConfig from the [Combat] section; unknown keys and unreadable values are reported in `problems`.
ControllerConfig parse_config(std::string_view ini, std::vector<std::string>* problems = nullptr);

// Menus that take the keyboard (inventory, console, pause ...): while one is open, key presses are not gameplay (the
// arrow keys scroll a list, Alt is typed into the console). Fed from the game's menu open / close events. Names are
// Starfield's menu names (Console, PauseMenu, InventoryMenu: OSF Animation and CommonLibSF use these; the rest are
// supported guesses, and the plugin logs every menu name it sees so the list can be corrected).
class MenuGate {
public:
    MenuGate();
    explicit MenuGate(std::vector<std::string> blocking) : blocking_(std::move(blocking)) {}
    void on_menu(std::string_view name, bool opening);
    bool blocked() const;                       // a blocking menu is open
    const std::vector<std::string>& open() const { return open_; }
    // "A, B, C" -> {"A", "B", "C"}
    static std::vector<std::string> parse_list(std::string_view text);
private:
    std::vector<std::string> blocking_, open_;
};

// Per-frame game state the controller needs.
struct PlayerState {
    float stamina = 1e9f;      // current stamina-like value (unlimited when not configured)
    bool staggered = false;
    float stick_x = 0.0f, stick_y = 0.0f;   // movement stick: x right, y forward, -1..1
};

class Controller {
public:
    explicit Controller(ControllerConfig cfg = {}, std::vector<Binding> bindings = {});

    // A key / button went down or up (t: seconds on any steady clock).
    std::vector<Command> on_key(std::uint32_t key, bool down, double t, const PlayerState& s);
    // An animation-graph event of the player (tag and payload as the engine delivers them).
    std::vector<Command> on_anim_event(std::string_view tag, std::string_view payload, double t);
    // The player was hit (after the game handled it: TESHitEvent). blocking: the player held block.
    std::vector<Command> on_hit(HitKind kind, bool blocking, double t);
    // Once per frame.
    std::vector<Command> tick(double t, const PlayerState& s);

    AttackPhase phase() const { return phase_.phase(); }
    float turn_multiplier() const { return phase_.turn_multiplier(); }
    bool invulnerable(double t) const { return iframes_.invulnerable(t); }
    bool dodging() const { return dodging_; }
    bool normal_window() const { return normal_open_; }
    bool power_window() const { return power_open_; }
    const std::string& stance() const { return stance_; }
    const ControllerConfig& config() const { return cfg_; }

private:
    void dodge(double t, const PlayerState& s, std::vector<Command>& out);
    void fire_buffered(double t, std::vector<Command>& out);
    void movement(const PlayerState& s, float& x, float& y) const;

    ControllerConfig cfg_;
    std::vector<Binding> bindings_;
    AttackPhaseTracker phase_;
    InputBuffer buffer_;
    IFrames iframes_;
    bool normal_open_ = false, power_open_ = false, dodging_ = false, dodge_events_ = false;
    double dodge_at_ = 0.0;
    static constexpr double dodge_timeout = 3.0;
    std::array<bool, 4> move_held_{};
    std::string stance_;        // keyword of the active stance binding ("" = none)
};

}  // namespace s2s::combat
