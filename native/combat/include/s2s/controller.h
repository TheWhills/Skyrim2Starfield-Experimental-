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

#include <deque>
#include <array>
#include <cstdint>
#include <map>
#include <functional>
#include <optional>
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
        UnequipWeapon,   // unequip the player's weapon, remembering it (first half of a stance re-equip)
        EquipWeapon,     // equip the weapon UnequipWeapon took off (makes the game pick the stance's animation set)
        Log,             // name: text for the plugin log (unknown payload instructions, ...)
        RestoreHealth,   // amount: health given back to the player (a parried hit's damage)
        ActorEvents,     // name: comma-separated graph events for actor `target`, tried in order until one is taken
        Feedback,        // timed block landed: name = on-screen message ("" none), target = attacker (sparks, shake)
    };
    Command(Kind k, std::string n = {}) : kind(k), name(std::move(n)) {}
    Kind kind;
    std::string name;
    VariableSet variable{VariableSet::Type::Int, "", 0.0};
    float amount = 0.0f;
    int dx = 0, dy = 0;
    std::uint32_t target = 0;   // ActorEvents: the actor (form ID)
};

// Settings ([Combat] section of the plugin INI; defaults = the Skyrim mods' defaults, see the spec).
struct ControllerConfig {
    bool buffer_attacks = true;
    double buffer_time = 0.35, power_hold = 0.30, charge_hold = 0.80;
    std::uint32_t attack_key = 256;                            // left mouse button
    std::uint32_t dodge_key = 56;                              // left Alt (TK Dodge's default)
    // Starfield's own power attack key (the "Melee" control, V by default: a separate key, like BFCO's keyboard
    // mode, not Skyrim's long hold). 0 = none.
    std::uint32_t power_key = 47;
    std::array<std::uint32_t, 4> move_keys{17, 31, 30, 32};    // forward W, back S, left A, right D
    DodgeConfig dodge{false, Direction::Back, 0.15f, 0.0f, true};   // no stamina cost until a Starfield value is chosen
    double dodge_iframes = 0.3;                                // seconds of invulnerability from the dodge press
    double annotation_iframes = 0.3;                           // TKDR_IframeDuration without its own duration
    std::string attack_event = "MeleeAttackStart";             // Starfield melee graph events (verified names)
    std::string power_event = "MeleeAttackPowerStart";
    // The power attack started mid-combo (power_in_combo): the stance packs' combo -> power transitions listen to this
    // plugin-only event. With the game's own MeleeAttackPowerStart the game played its standing power attack again
    // when the combo ended, even with the key kept from its controls (owner, 2026-10-23). S2S_ComboPower (a pack whose combo
    // power transitions used it) is not taken by the graph at all (owner's log; supported: only known event names).
    std::string combo_power_event = "MeleeAttackPowerStart";
    // Clip events built for the plugin: "" = Skyrim's own split (event "PIE", payload "@SGVI|..."); otherwise the
    // name of the host event that carries the whole Skyrim annotation in its payload (if the graph drops unknown
    // event names: unresolved, see the spec).
    std::string plugin_event_host;
    // Graph events sent after a stance change (Skyrim's Stances sends blockStart / blockStop so the animation set is
    // picked again; whether Starfield needs this is unresolved). Empty = none.
    std::vector<std::string> stance_refresh_events;
    // Pressing the active stance's key again goes back to neutral (LoreRim / Stances' toggle). Off by default: in the
    // owner's first stance test, quick double presses left every redraw in neutral.
    bool stance_repeat_neutral = false;
    // Re-equip the weapon after a stance change, once the stance keys have been quiet for stance_reequip_delay
    // seconds: Starfield picks the weapon's animation set at equip time (owner, 2026-10-23: the stance clips showed
    // only after a reload or a re-equip, not after a redraw). Quick presses (up, up, left) give one re-equip.
    // The equip follows the game's UnequipComplete event, or stance_reequip_wait seconds after the unequip when that
    // event does not come (owner's run: unequip + equip sent together did nothing visible, no UnequipComplete).
    bool stance_reequip = true;
    double stance_reequip_delay = 0.25;
    double stance_reequip_wait = 0.5;
    // Graph variable set when the player is hit while blocking: 0 normal attack, 1 power attack (Dynamic Block Hit's
    // NA / PA variants; the graph picks a block-hit clip by it once variant states exist). Empty = not set.
    std::string block_hit_variable = "iS2SBlockHitType";
    // Timed block: a hit taken while blocking, within parry_window seconds of the block key going down, does no damage
    // (all of it is given back: the most health held over the window) and the attacker gets parry_events (the first
    // its graph takes); timed_block_message shows on screen. One per block press. 0 = off.
    double parry_window = 0.25;
    bool parry_restore_health = true;
    std::string parry_events = "StaggerStart, recoilStart, recoilLargeStart";
    std::string timed_block_message = "Timed block";
    // Valhalla Combat's split (its defaults: timed 0.3 s, perfect 0.15 s): a timed block negates the damage and shows
    // the feedback; only a perfect block (pressed within perfect_block_window seconds) also sends parry_events to the
    // attacker (owner: the attacker recoiling on every timed block was not what Skyrim did). 0 = every timed block.
    double perfect_block_window = 0.12;
    // Any other hit taken while blocking: this share of its damage is given back (Skyrim's block takes most of a hit;
    // the game's own block reduction on 1.16 is not known). 0 = the game's damage as is.
    double block_reduction = 0.6;
    // A blocked hit drops the guard on 1.16 (owner's runs: bIsBlocking off ~0.3 s after each blocked hit, key still
    // held). While the block key stays down, block_reraise_event goes to the player's graph (every 0.3 s at most, for
    // block_reraise_window seconds after the hit) to bring the guard back up. Empty = off.
    std::string block_reraise_event = "BlockStart";
    double block_reraise_window = 1.5;
    // A power attack (power_key, or a held attack key) during a combo: send power_event to the graph at once. Vanilla Starfield has
    // no combo -> power transition, so the game does not send it mid-combo and played the standing power attack
    // after the combo instead (owner, 2026-10-23); the stance packs add combo -> power states that need the event.
    bool power_in_combo = true;
    // The game queues its own standing power attack from a power key press it could not start mid-combo and plays it
    // once the combo is over, even with the key kept from PlayerControls (owner's runs, 2026-10-23: one queued attack
    // per press, an AttackStart with no attack press and nothing sent by the plugin). When such an AttackStart comes
    // within queued_power_window seconds of the last mid-combo press (or of the last one cancelled), the plugin sends
    // cancel_event (a top-level MeleeAttackPower_A / MeleeAttackCombo -> None transition the stance packs add).
    // Graph event per dodge direction (Direction order: Forward, ForwardRight, Right, BackRight, Back, BackLeft, Left,
    // ForwardLeft); "" = TKDodge<Direction>. Starfield graphs only take event names they already know (owner's logs
    // 2026-10-23: TKDodgeBack and S2S_ComboPower "not taken by the graph"), so the stance packs' dodge states listen to
    // the NPC melee attack events (npc_meleeattacks.agx), which the game does not send to the player.
    std::array<std::string, 8> dodge_events{"MeleeAttack01", "", "MeleeAttack04", "", "MeleeAttack02", "", "MeleeAttack03", ""};
    bool cancel_queued_power = true;
    double queued_power_window = 3.0;
    std::string cancel_event = "ActionInterrupt";
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

// Finds where an engine event keeps its strings when the layout is not known (Starfield's BSAnimationGraphEvent:
// Skyrim's holder / tag / payload order did not hold on the owner's first run). The game side classifies the first
// slots (8-byte fields) of each event; the probe settles on the first readable name as the tag and the next string
// slot (possibly empty) as the payload once `needed` events in a row agree, or gives up after `give_up` events.
class LayoutProbe {
public:
    enum class Slot { Other, Self, Text, EmptyText };   // Self: points at the object whose sink got the event
    enum class State { Probing, Found, Failed };
    explicit LayoutProbe(int needed = 3, int give_up = 40) : needed_(needed), give_up_(give_up) {}
    State feed(const std::vector<Slot>& slots);
    State state() const { return state_; }
    int tag() const { return tag_; }                // slot index, -1 until found
    int payload() const { return payload_; }        // slot index, -1 when the events carry no payload slot
    int holder() const { return holder_; }          // first Self slot seen with the found layout, -1 if none
private:
    int needed_, give_up_, seen_ = 0, streak_ = 0, tag_ = -1, payload_ = -1, holder_ = -1;
    State state_ = State::Probing;
};

// The text of the BSFixedString stored at `slot` (an engine string-pool pointer), reading memory only where
// `readable(ptr, bytes)` allows: nullopt when it is not a string (unreadable, a chain longer than 8 hops or a loop,
// over 256 characters, non-printable), "" for a null pointer (an empty string).
std::optional<std::string> pool_string_at(std::uintptr_t slot,
                                          const std::function<bool(const void*, std::size_t)>& readable);

// MSVC x64 RTTI: which of a class's vtables belongs to its base class `base` (a type-descriptor name such as
// ".?AVBSInputEventReceiver@@"). Each vtable's slot -1 points at its Complete Object Locator (signature 1, +0x04 the
// subobject offset, +0x0C type descriptor RVA, +0x10 class hierarchy RVA, +0x14 its own RVA); the hierarchy lists the
// base classes with their offsets (mdisp). Memory is read only where `readable` allows.
struct RttiVtable {
    std::size_t index = 0;          // into the vtables given
    std::uintptr_t vtable = 0;
    std::string complete_class;     // the most-derived class's type name (for the log)
};
std::optional<RttiVtable> rtti_base_vtable(const std::vector<std::uintptr_t>& vtables, std::string_view base,
                                           const std::function<bool(const void*, std::size_t)>& readable);
// The most-derived class name (".?AVActor@@") of the object whose vtable this is, "" when it has no readable RTTI.
// Animation events worth logging after the general cap (block, hit, stagger, recoil reactions): tag or payload
// mentions one of them, case-insensitive (BlockHitStart, StaggerStart, recoilStart, SoundPlay '...BlockUp3rd').
bool is_combat_reaction_event(std::string_view tag, std::string_view payload);

// Spark-like effect forms by EditorID (impact data sets for the timed-block sparks): a score for picking one when the
// INI names none - 0 = not a candidate; "spark" or "metal" is required (none of the owner's 275 sets had "spark"),
// melee / blade / block / weapon / sword / metal add to it.
int spark_score(std::string_view editor_id);

// TESHitEvent on Starfield 1.16 (owner's log 2026-10-25, verified both ways: an NPC hitting the player and the player
// hitting it): the hit data's aggressor handle at +0x40 and its target handle at +0x48 (CommonLibSF: +0x40 / +0x44);
// the event's own target / cause pointers (CommonLibSF +0xF0 / +0xF8) are null.
struct HitHandles { std::uint32_t aggressor = 0, target = 0; };
constexpr std::ptrdiff_t kHitAggressor = 0x40, kHitTarget = 0x48;
HitHandles hit_handles(const void* event);
std::string rtti_class_name(std::uintptr_t vtable, const std::function<bool(const void*, std::size_t)>& readable);

// Arrays of actor handles inside an engine object whose layout is not known (Starfield's ProcessLists: CommonLibSF's
// highActorHandles at +0x58 was always empty on 1.16, owner's runs). Every 8-byte aligned offset in [0, span) is read
// as a BSTArray in either layout - {u32 size, u32 capacity, T* data} (CommonLibSF's) or {T* data, u32 capacity, u32 size}
// - and kept when it is plausible (size <= capacity <= 16384, data readable) and holds at least one handle that
// `is_actor(handle)` accepts. Sorted by that count, most first. Memory is read only where `readable` allows.
struct HandleArray {
    std::ptrdiff_t offset = 0;
    bool data_first = false;        // {data, capacity, size} instead of {size, capacity, data}
    std::uint32_t size = 0;
    int actors = 0;
};
std::vector<HandleArray> scan_handle_arrays(std::uintptr_t base, std::size_t span,
                                            const std::function<bool(const void*, std::size_t)>& readable,
                                            const std::function<bool(std::uint32_t)>& is_actor);
// The handles of the array found by scan_handle_arrays (same reading rules); empty when it no longer looks valid.
std::vector<std::uint32_t> read_handle_array(std::uintptr_t base, const HandleArray& a,
                                             const std::function<bool(const void*, std::size_t)>& readable);

// Objects of one class in a block of writable memory, found by their vtable: every 8-byte aligned word in
// [begin, begin + bytes) equal to `vtable` whose next 16 bytes look like a BSTArray in either layout (size <= capacity
// <= 4096; data readable or, for an empty array, anything). For event sources whose GetEventSource has no Address
// Library ID on 1.16 (TESHitEvent): the source is a static object in the game's data, its vtable is mapped.
// The block itself must be readable; other memory is read only where `readable` allows.
std::vector<std::uintptr_t> find_vtable_objects(std::uintptr_t begin, std::size_t bytes, std::uintptr_t vtable,
                                                const std::function<bool(const void*, std::size_t)>& readable);

// Per-frame game state the controller needs.
struct PlayerState {
    float stamina = 1e9f;      // current stamina-like value (unlimited when not configured)
    bool staggered = false;
    bool blocking = false;     // blocking (the block key while the guard comes up, or the graph's block state)
    bool block_key = false;    // the block key is physically down
    bool block_state = false;  // the graph is in its block states (bIsBlocking)
    float health = -1.0f;      // current health (< 0: not known)
    float stick_x = 0.0f, stick_y = 0.0f;   // movement stick: x right, y forward, -1..1
};

class Controller {
public:
    explicit Controller(ControllerConfig cfg = {}, std::vector<Binding> bindings = {});

    // A key / button went down or up (t: seconds on any steady clock).
    std::vector<Command> on_key(std::uint32_t key, bool down, double t, const PlayerState& s);
    // Whether the key event just passed to on_key should be hidden from the game: the power attack key pressed during a
    // combo (and its release), which the plugin turns into the combo's power attack; the game would also queue its
    // standing power attack and play it afterwards (owner, 2026-10-23).
    bool last_key_consumed() const { return consumed_last_; }
    // Whether a press of `key` now should never reach the game's own controls: the power attack key while an attack
    // runs and bPowerInCombo is on. The plugin sends the combo's power attack itself; the game queued its standing
    // power attack from the same press and played it after the combo one (owner, 2026-10-23).
    bool hides_power_press(std::uint32_t key) const {
        return cfg_.power_key && key == cfg_.power_key && cfg_.power_in_combo && phase_.phase() != AttackPhase::None;
    }
    // An animation-graph event of the player (tag and payload as the engine delivers them).
    std::vector<Command> on_anim_event(std::string_view tag, std::string_view payload, double t);
    // The player was hit (after the game handled it: TESHitEvent). blocking: the player held block.
    // attacker: the hitting actor's form ID (0: not known; a parry then gives health back without the stagger).
    std::vector<Command> on_hit(HitKind kind, bool blocking, double t, std::uint32_t attacker = 0);
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
    bool consumed_last_ = false, power_key_consumed_ = false;
    double reequip_due_ = -1.0; // when to unequip after a stance change (< 0: none pending)
    int queued_powers_ = 0;     // power key presses the game may still play as standing power attacks
    double queued_until_ = -1.0, last_send_at_ = -1.0, last_attack_press_at_ = -1.0;
    double cancel_check_at_ = -1.0, cancel_candidate_at_ = -1.0;   // an AttackStart that may be a queued one
    double equip_due_ = -1.0;   // when to equip again at the latest (< 0: not waiting for an unequip)
    bool block_held_ = false, parried_ = false;   // parried_: this block press already parried once
    double block_up_at_ = -1e9;                   // when the block went up (tick saw iWantBlock turn on)
    std::deque<std::pair<double, float>> health_; // (t, health) over the last parry window, for the give-back
    float giveback_to_ = -1.0f;                   // a parry keeps health at this ...
    float giveback_share_ = 1.0f;                 // ... giving back this share of what was lost
    double giveback_until_ = -1.0;                // ... until then (< 0: nothing pending)
    double blocked_hit_at_ = -1e9, reraised_at_ = -1e9;
};

}  // namespace s2s::combat
