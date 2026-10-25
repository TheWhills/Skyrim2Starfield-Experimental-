// Skyrim -> Starfield combat: the game-independent core of the combat SFSE plugin (docs/armor/combat-plugin-spec.md).
//
// Everything here is plain C++20 with no game types, so it builds and is tested on any platform; the SFSE side
// (input hooks, animation-graph event sink, camera, damage) translates game data into these calls. Behaviour is
// written from the owner's mods' data formats (Payload Interpreter annotations, MCO / BFCO markers, TK Dodge,
// True Directional Movement) as described in the docs; no code from those mods is used.
#pragma once

#include <array>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace s2s::combat {

// ------------------------------------------------------------------------------------------------ payloads
// One Payload Interpreter style annotation: "<host event>.@<INSTR>|arg|arg..." or "<host event>.$<custom>".
// Instructions are case sensitive (as Payload Interpreter's); unknown ones are kept so a caller can log them.
struct Payload {
    std::string host;               // the annotation event that carries it ("PIE", "HitFrame", ...)
    std::string instruction;        // "SGVI", "SGVF", "SGVB", "CAST", "CAMSHAKE", ... or the custom name after '$'
    bool custom = false;            // "$name": a user-defined instruction
    std::vector<std::string> args;
};
std::optional<Payload> parse_payload(std::string_view text);

// A graph-variable assignment from SGVB / SGVI / SGVF ("@SGVF|MCO_AttackSpeed|0.9"); nullopt for other instructions
// or malformed arguments. The misspelt "SVGF" found in many LoreRim clips is NOT accepted (Payload Interpreter ignores
// unknown instructions, so in Skyrim those lines do nothing).
struct VariableSet {
    enum class Type { Bool, Int, Float } type;
    std::string name;
    double value;
};
std::optional<VariableSet> as_variable_set(const Payload& p);

// ------------------------------------------------------------------------------------------------ attack phase
// TDM-style attack phase from animation event names (MCO / BFCO / Precision / vanilla markers). The plugin scales the
// player's turn speed by phase: fast in the wind-up, slow in the swing, locked at the end.
enum class AttackPhase : std::uint8_t { None, Start, Mid, End };
class AttackPhaseTracker {
public:
    // Feed every animation event of the player; returns the phase after it.
    AttackPhase on_event(std::string_view event);
    AttackPhase phase() const { return phase_; }
    // Turn-speed multiplier for the current phase (defaults are starting points to tune in game).
    float turn_multiplier() const;
    std::array<float, 4> multipliers{1.0f, 1.0f, 0.25f, 0.0f};   // None, Start, Mid, End
private:
    AttackPhase phase_ = AttackPhase::None;
};

// ------------------------------------------------------------------------------------------------ input buffer
// Attack presses are remembered for a short time so a press slightly before the next-attack window still counts;
// holding the button longer than `power_hold` makes a power attack, longer than `charge_hold` a charged one (MCO
// charged power attacks: intro, loop while held, outro on release).
enum class AttackKind : std::uint8_t { Normal, Power, Charged };
struct BufferedAttack { AttackKind kind; double pressed_at; };
class InputBuffer {
public:
    double buffer_time = 0.35;     // seconds a press is remembered
    double power_hold = 0.30;      // held at least this long: power attack
    double charge_hold = 0.80;     // held at least this long: charged power attack
    void press(double t);
    // Release: classifies the press by how long it was held and queues it. Returns the kind queued.
    AttackKind release(double t);
    // While held: a charged attack starts as soon as the hold passes charge_hold (returns true once).
    bool charge_started(double t);
    bool holding() const { return held_; }
    // The next window opened (MCO_WinOpen / BFCO_NextWinStart ...): take a queued attack still in time, if any.
    std::optional<BufferedAttack> take(double t, bool power_window_open, bool normal_window_open);
    void clear() { queued_.reset(); }
private:
    bool held_ = false, charge_sent_ = false;
    double down_at_ = 0.0;
    std::optional<BufferedAttack> queued_;
};

// ------------------------------------------------------------------------------------------------ i-frames
// Invulnerability windows. Opened by an annotation (TKDR_IframeDuration style start + duration, or start / end
// event pairs) or directly by the dodge; the plugin's hit hook asks `invulnerable(now)`.
class IFrames {
public:
    void open(double t, double duration);       // [t, t + duration)
    void open_until_closed(double t);           // start event without a duration: until close()
    void close(double t);
    bool invulnerable(double t) const;
private:
    std::vector<std::pair<double, double>> windows_;
};

// ------------------------------------------------------------------------------------------------ dodge
// TK Dodge style: the direction from the movement input relative to the character's facing; standing still gives
// `idle_direction`. 4-way or 8-way. Event names follow TK Dodge ("TKDodgeForward" ...) so ported clips keep working.
enum class Direction : std::uint8_t { Forward, ForwardRight, Right, BackRight, Back, BackLeft, Left, ForwardLeft };
struct DodgeConfig {
    bool eight_way = false;
    Direction idle_direction = Direction::Back;
    float dead_zone = 0.15f;                    // stick / key input magnitude below this = standing still
    float stamina_cost = 10.0f;
    bool allow_attack_cancel = true;
};
// x = right, y = forward (character space); returns the direction to dodge in.
Direction dodge_direction(float x, float y, const DodgeConfig& cfg);
std::string_view dodge_event(Direction d);       // "TKDodgeForward", ... ("TKDodgeForwardRight" for diagonals)
// Can the player dodge now? (stamina enough, not staggered, not mid-attack unless cancelling is allowed)
bool can_dodge(float stamina, bool staggered, AttackPhase phase, const DodgeConfig& cfg);

// ------------------------------------------------------------------------------------------------ lock-on
// TDM-style target choice and switching (docs/armor/lock-on-design.md). Units: game units; angles: radians.
struct Vec3 { float x = 0, y = 0, z = 0; };
struct Candidate {
    std::uint32_t id = 0;
    Vec3 position;                 // target point (torso / head bone) in world space
    float size_multiplier = 1.0f;  // larger creatures can be locked from further away
    bool alive = true, hostile = true, visible = true, line_of_sight = true;
    bool under_crosshair = false;
    float screen_x = 0, screen_y = 0;   // projected position, for switching
    bool on_screen = true;
};
enum class SelectMode : std::uint8_t { Closest, Center, Combined };
struct LockOnConfig {
    float max_distance = 2000.0f;         // about 28.6 m
    float keep_hysteresis = 1.05f;        // a locked target is dropped only past max_distance * this
    float lost_sight_grace = 2.0f;        // seconds without line of sight before the lock drops
    bool hostile_only = true;
    float switch_cooldown = 0.25f;
};
class LockOn {
public:
    explicit LockOn(LockOnConfig cfg = {}) : cfg_(cfg) {}
    // Choose a target: the crosshair actor if valid, else the best by mode. camera_forward: unit vector, z ignored.
    std::optional<std::uint32_t> acquire(const std::vector<Candidate>& cands, Vec3 player, Vec3 camera_forward,
                                         SelectMode mode);
    // Per frame: keeps or drops the current target. Returns false when the lock dropped.
    bool update(const std::vector<Candidate>& cands, Vec3 player, double now);
    // Switch towards a screen side: -1 left / +1 right (dx), or up / down (dy). Respects the cooldown.
    std::optional<std::uint32_t> switch_target(const std::vector<Candidate>& cands, Vec3 player, int dx, int dy,
                                               double now);
    std::optional<std::uint32_t> target() const { return target_; }
    void release() { target_.reset(); }
private:
    bool valid(const Candidate& c, Vec3 player, float distance_scale) const;
    LockOnConfig cfg_;
    std::optional<std::uint32_t> target_;
    double last_seen_ = 0.0, last_switch_ = -1e9;
    int last_switch_dx_ = 0, last_switch_dy_ = 0;
};

// Aiming the player at a lock-on target (the game side writes the player's angle each frame; with a weapon drawn the
// third-person camera follows the player's heading). Angles in radians, in the Bethesda reference convention
// (Skyrim / Fallout 4 OBJ_REFR angle; Starfield keeps the struct, the signs are a supported hypothesis the first run
// checks): yaw (angle.z) 0 = facing +Y, growing clockwise seen from above (+X at +pi/2); pitch (angle.x) > 0 = looking
// down.
struct Angles { float pitch = 0, yaw = 0; };
float wrap_pi(float a);                                  // into (-pi, pi]
Angles aim_angles(Vec3 from, Vec3 to);
Vec3 look_forward(Angles a);                             // unit vector the angles look along
// Starfield's third-person camera rotation: a quaternion (w, x, y, z) in ThirdPersonState (+0x170 on 1.16), the
// camera's world rotation as yaw about Z then pitch about X: q = Rz(-yaw) * Rx(-pitch), yaw clockwise from +Y and pitch
// positive looking down, as Angles. Read from the owner's camera-probe log 2026-10-23 (the yaw follows the camera root's
// forward row to 0.1 deg over two samples 43 deg apart).
struct Quat { float w = 1, x = 0, y = 0, z = 0; };
Angles camera_angles(Quat q);
Quat camera_quat(Angles a);
// Moves `cur` toward `want` (shortest way round for yaw): each axis closes the fraction min(1, rate * dt) of its gap
// (rates per second; TDM's camera yaw 8 / pitch 2 are the defaults). Pitch is clamped to +-max_pitch.
Angles steer(Angles cur, Angles want, float dt, float yaw_rate = 8.0f, float pitch_rate = 2.0f,
             float max_pitch = 1.2f);
// Where `to` sits relative to the view from `from` looking along `look`: x = yaw offset (right +), y = pitch offset
// (up +), radians. Used as the "screen" position for target switching when no projection is available.
void view_offset(Angles look, Vec3 from, Vec3 to, float& x, float& y);

// Input events the game's controls should not see while the lock holds the camera: mouse moves (InputEvent type 1)
// and any stick but the left one (thumbstick type 4; the left stick, id 0x0B, still moves the player).
bool hides_look_event(std::uint32_t event_type, std::int32_t stick_id);

// Whether the lock writes the player's pitch (actor angle.x). The third-person camera keeps its own yaw but takes its
// up / down from the player's pitch (owner's run 2026-10-25: yaw followed the target, the height stayed where it was
// when the lock started), so the pitch is written whenever the camera is steered, or the player is.
bool lock_writes_player_pitch(bool steer_camera, bool steer_player, bool steer_pitch);

// The player's angle.x in third person is a per-frame look input, not an angle: the camera adds it to its pitch and
// the game zeroes it (owner's log 2026-10-25: written 4-31 deg each frame, read back 0, the camera ran to its 79 deg
// limit). The lock writes the share of the remaining error it should close this frame, capped at max_step radians.
float pitch_input(float look_pitch, float want_pitch, float gain, float max_step = 0.35f);

// Where the view is aimed from: the camera's own position when it is near the player (third person sits behind and
// beside the player, and the crosshair is on the camera's ray), otherwise the player's eye.
Vec3 aim_origin(Vec3 player_eye, const Vec3* camera, float max_offset = 10.0f);

// ------------------------------------------------------------------------------------------------ input table
// "key -> action" configuration (Key Utils / Stances style): lines "Name = key|action|argument" in an INI section.
// Actions: "event" (send a graph event), "int" / "bool" / "float" (set a graph variable), "keyword" (toggle an
// actor keyword: stances), "dodge", "lock" (toggle lock-on), "switch_left" / "switch_right".
struct Binding { std::string name; std::uint32_t key; std::string action; std::string argument; };
std::vector<Binding> parse_bindings(std::string_view ini, std::string_view section = "Keys");

}  // namespace s2s::combat
