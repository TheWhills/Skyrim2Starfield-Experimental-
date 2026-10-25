// Implementation of include/s2s/combat.h (see there and docs/armor/combat-plugin-spec.md).
#include "s2s/combat.h"

#include <algorithm>
#include <cctype>
#include <charconv>
#include <cmath>
#include <limits>

namespace s2s::combat {
namespace {

std::string_view trim(std::string_view s) {
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.front()))) s.remove_prefix(1);
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.back()))) s.remove_suffix(1);
    return s;
}

std::vector<std::string> split(std::string_view s, char sep) {
    std::vector<std::string> out;
    std::size_t start = 0;
    for (std::size_t i = 0; i <= s.size(); ++i) {
        if (i == s.size() || s[i] == sep) {
            out.emplace_back(trim(s.substr(start, i - start)));
            start = i + 1;
        }
    }
    return out;
}

bool to_double(std::string_view s, double& out) {
    s = trim(s);
    if (s.empty()) return false;
    std::string tmp(s);
    if (tmp.front() == '.') tmp.insert(tmp.begin(), '0');                 // ".9" is written in some packs
    if (tmp.size() > 1 && tmp[0] == '-' && tmp[1] == '.') tmp.insert(1, "0");
    char* end = nullptr;
    out = std::strtod(tmp.c_str(), &end);
    return end && *end == '\0';
}

bool iequals(std::string_view a, std::string_view b) {
    return a.size() == b.size() && std::equal(a.begin(), a.end(), b.begin(), [](char x, char y) {
               return std::tolower(static_cast<unsigned char>(x)) == std::tolower(static_cast<unsigned char>(y));
           });
}

bool any_of(std::string_view e, std::initializer_list<std::string_view> names) {
    return std::any_of(names.begin(), names.end(), [&](std::string_view n) { return iequals(e, n); });
}

float length2d(Vec3 a) { return std::sqrt(a.x * a.x + a.y * a.y); }
Vec3 sub(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
float length(Vec3 a) { return std::sqrt(a.x * a.x + a.y * a.y + a.z * a.z); }

}  // namespace

// ------------------------------------------------------------------------------------------------ payloads
std::optional<Payload> parse_payload(std::string_view text) {
    text = trim(text);
    auto at = text.find(".@");
    auto dollar = text.find(".$");
    bool custom = false;
    std::size_t cut = at;
    if (dollar != std::string_view::npos && (at == std::string_view::npos || dollar < at)) {
        cut = dollar;
        custom = true;
    }
    if (cut == std::string_view::npos) return std::nullopt;
    Payload p;
    p.host = std::string(trim(text.substr(0, cut)));
    std::string_view rest = text.substr(cut + 2);
    while (!rest.empty() && (rest.front() == '@' || rest.front() == '$' || rest.front() == '.')) rest.remove_prefix(1);
    auto parts = split(rest, '|');
    if (parts.empty() || parts[0].empty()) return std::nullopt;
    p.instruction = parts[0];
    p.custom = custom;
    p.args.assign(parts.begin() + 1, parts.end());
    return p;
}

std::optional<VariableSet> as_variable_set(const Payload& p) {
    if (p.custom || p.args.size() < 2) return std::nullopt;
    VariableSet v;
    if (p.instruction == "SGVB") v.type = VariableSet::Type::Bool;
    else if (p.instruction == "SGVI") v.type = VariableSet::Type::Int;
    else if (p.instruction == "SGVF") v.type = VariableSet::Type::Float;
    else return std::nullopt;
    v.name = p.args[0];
    if (v.name.empty() || !to_double(p.args[1], v.value)) return std::nullopt;
    if (v.type == VariableSet::Type::Int) v.value = std::trunc(v.value);
    if (v.type == VariableSet::Type::Bool) v.value = v.value != 0.0 ? 1.0 : 0.0;
    return v;
}

// ------------------------------------------------------------------------------------------------ attack phase
AttackPhase AttackPhaseTracker::on_event(std::string_view e) {
    std::string host;                                                   // "HitFrame.@CAMSHAKE..." counts as HitFrame
    if (auto p = parse_payload(e)) {
        host = p->host;
        e = host;
    }
    if (any_of(e, {"preHitFrame", "CastOKStart", "MCO_AttackInitiate", "MCO_PowerAttackInitiate", "MCO_InputBuffer",
                   "TDM_AttackStart", "Collision_AttackStart", "Collision_Start"})) {
        if (phase_ != AttackPhase::Mid) phase_ = AttackPhase::Start;
    } else if (any_of(e, {"weaponSwing", "weaponLeftSwing", "TDM_AttackMid", "Collision_Add"})) {
        if (phase_ != AttackPhase::End) phase_ = AttackPhase::Mid;
    } else if (any_of(e, {"HitFrame", "MCO_WinOpen", "MCO_PowerWinOpen", "MCO_TransitionOpen", "MCO_Recovery",
                          "BFCO_NextWinStart", "BFCO_NextPowerWinStart", "BFCO_DIY_recovery", "BFCO_DIY_Rcovery",
                          "TDM_AttackEnd", "Collision_AttackEnd"})) {
        phase_ = AttackPhase::End;
    } else if (any_of(e, {"attackStop", "TDM_AttackStop", "MCO_WinClose", "MCO_PowerWinClose", "BFCO_DIY_EndLoop",
                          "MCO_TransitionClose", "AttackStop", "AttackEnd"})) {   // AttackEnd: Starfield's name
        phase_ = AttackPhase::None;
    }
    return phase_;
}

float AttackPhaseTracker::turn_multiplier() const { return multipliers[static_cast<std::size_t>(phase_)]; }

// ------------------------------------------------------------------------------------------------ input buffer
void InputBuffer::press(double t) {
    held_ = true;
    charge_sent_ = false;
    down_at_ = t;
}

AttackKind InputBuffer::release(double t) {
    double held = t - down_at_;
    held_ = false;
    AttackKind kind = charge_sent_ ? AttackKind::Charged
                      : held >= power_hold ? AttackKind::Power
                                           : AttackKind::Normal;
    if (kind != AttackKind::Charged) queued_ = BufferedAttack{kind, t};   // a charged attack already started
    charge_sent_ = false;
    return kind;
}

bool InputBuffer::charge_started(double t) {
    if (held_ && !charge_sent_ && t - down_at_ >= charge_hold) {
        charge_sent_ = true;
        return true;
    }
    return false;
}

std::optional<BufferedAttack> InputBuffer::take(double t, bool power_window_open, bool normal_window_open) {
    if (!queued_) return std::nullopt;
    if (t - queued_->pressed_at > buffer_time) {
        queued_.reset();
        return std::nullopt;
    }
    bool ok = queued_->kind == AttackKind::Power ? power_window_open : normal_window_open;
    if (!ok) return std::nullopt;
    auto out = queued_;
    queued_.reset();
    return out;
}

// ------------------------------------------------------------------------------------------------ i-frames
void IFrames::open(double t, double duration) {
    if (duration > 0) windows_.emplace_back(t, t + duration);
}

void IFrames::open_until_closed(double t) { windows_.emplace_back(t, std::numeric_limits<double>::infinity()); }

void IFrames::close(double t) {
    for (auto& w : windows_)
        if (w.first <= t && w.second > t) w.second = t;
    windows_.erase(std::remove_if(windows_.begin(), windows_.end(),
                                  [&](const auto& w) { return w.second <= t - 10.0; }),   // forget old windows
                   windows_.end());
}

bool IFrames::invulnerable(double t) const {
    return std::any_of(windows_.begin(), windows_.end(), [&](const auto& w) { return w.first <= t && t < w.second; });
}

// ------------------------------------------------------------------------------------------------ dodge
Direction dodge_direction(float x, float y, const DodgeConfig& cfg) {
    if (std::sqrt(x * x + y * y) < cfg.dead_zone) return cfg.idle_direction;
    // angle clockwise from forward: 0 forward, 90 right, 180 back, 270 left
    double a = std::atan2(x, y) * 180.0 / 3.14159265358979323846;
    if (a < 0) a += 360.0;
    if (cfg.eight_way) {
        int sector = static_cast<int>(std::floor((a + 22.5) / 45.0)) % 8;
        return static_cast<Direction>(sector);
    }
    int sector = static_cast<int>(std::floor((a + 45.0) / 90.0)) % 4;
    return static_cast<Direction>(sector * 2);
}

std::string_view dodge_event(Direction d) {
    switch (d) {
        case Direction::Forward: return "TKDodgeForward";
        case Direction::ForwardRight: return "TKDodgeForwardRight";
        case Direction::Right: return "TKDodgeRight";
        case Direction::BackRight: return "TKDodgeBackRight";
        case Direction::Back: return "TKDodgeBack";
        case Direction::BackLeft: return "TKDodgeBackLeft";
        case Direction::Left: return "TKDodgeLeft";
        case Direction::ForwardLeft: return "TKDodgeForwardLeft";
    }
    return "TKDodgeBack";
}

bool can_dodge(float stamina, bool staggered, AttackPhase phase, const DodgeConfig& cfg) {
    if (staggered || stamina < cfg.stamina_cost) return false;
    if (phase != AttackPhase::None && !cfg.allow_attack_cancel) return false;
    return true;
}

// ------------------------------------------------------------------------------------------------ aiming
float wrap_pi(float a) {
    constexpr float two_pi = 6.28318530717958647692f, pi = 3.14159265358979323846f;
    a = std::fmod(a + pi, two_pi);
    if (a <= 0) a += two_pi;
    return a - pi;
}

Angles aim_angles(Vec3 from, Vec3 to) {
    Vec3 d = sub(to, from);
    float horiz = length2d(d);
    Angles out;
    out.yaw = std::atan2(d.x, d.y);                     // 0 along +Y, +X at +pi/2 (clockwise from above)
    out.pitch = -std::atan2(d.z, horiz);                // above = negative (looking up)
    return out;
}

Vec3 look_forward(Angles a) {
    float c = std::cos(a.pitch);
    return {std::sin(a.yaw) * c, std::cos(a.yaw) * c, -std::sin(a.pitch)};
}

Angles camera_angles(Quat q) {
    // q = (ca cb, ca sb, sa sb, sa cb) with ca / sa = cos / sin (a / 2), a = -yaw, and cb / sb for b = -pitch
    const float a = 2.0f * std::atan2(q.z, q.w);
    const float ca = std::cos(a / 2), sa = std::sin(a / 2);
    const float sb = std::fabs(ca) >= std::fabs(sa) ? q.x / ca : q.y / sa;
    const float cb = std::fabs(ca) >= std::fabs(sa) ? q.w / ca : q.z / sa;
    const float b = 2.0f * std::atan2(sb, cb);
    return {wrap_pi(-b), wrap_pi(-a)};
}

Quat camera_quat(Angles ang) {
    const float a = -ang.yaw, b = -ang.pitch;
    const float ca = std::cos(a / 2), sa = std::sin(a / 2), cb = std::cos(b / 2), sb = std::sin(b / 2);
    return {ca * cb, ca * sb, sa * sb, sa * cb};
}

Angles steer(Angles cur, Angles want, float dt, float yaw_rate, float pitch_rate, float max_pitch) {
    float ky = std::min(1.0f, std::max(0.0f, yaw_rate * dt));
    float kp = std::min(1.0f, std::max(0.0f, pitch_rate * dt));
    Angles out;
    out.yaw = wrap_pi(cur.yaw + wrap_pi(want.yaw - cur.yaw) * ky);
    out.pitch = std::clamp(cur.pitch + (want.pitch - cur.pitch) * kp, -max_pitch, max_pitch);
    return out;
}

bool hides_look_event(std::uint32_t event_type, std::int32_t stick_id) {
    return event_type == 1 || (event_type == 4 && stick_id != 0x0B);
}

bool lock_writes_player_pitch(bool steer_camera, bool steer_player, bool steer_pitch) {
    return steer_pitch && (steer_camera || steer_player);
}

float pitch_input(float look_pitch, float want_pitch, float gain, float max_step) {
    const float step = (want_pitch - look_pitch) * std::clamp(gain, 0.0f, 1.0f);
    return std::clamp(step, -max_step, max_step);
}

bool lock_acquired(Angles look, Angles want, float since_lock, float max_time, float tolerance) {
    if (since_lock >= max_time) return true;
    return std::fabs(wrap_pi(want.yaw - look.yaw)) <= tolerance && std::fabs(want.pitch - look.pitch) <= tolerance;
}

Vec3 aim_origin(Vec3 player_eye, const Vec3* camera, float max_offset) {
    if (!camera || !std::isfinite(camera->x) || !std::isfinite(camera->y) || !std::isfinite(camera->z)) return player_eye;
    const float dx = camera->x - player_eye.x, dy = camera->y - player_eye.y, dz = camera->z - player_eye.z;
    return dx * dx + dy * dy + dz * dz <= max_offset * max_offset ? *camera : player_eye;
}

void view_offset(Angles look, Vec3 from, Vec3 to, float& x, float& y) {
    Angles a = aim_angles(from, to);
    x = wrap_pi(a.yaw - look.yaw);
    y = -(a.pitch - look.pitch);
}

// ------------------------------------------------------------------------------------------------ lock-on
bool LockOn::valid(const Candidate& c, Vec3 player, float distance_scale) const {
    if (!c.alive || !c.visible || !c.line_of_sight) return false;
    if (cfg_.hostile_only && !c.hostile) return false;
    return length(sub(c.position, player)) <= cfg_.max_distance * c.size_multiplier * distance_scale;
}

std::optional<std::uint32_t> LockOn::acquire(const std::vector<Candidate>& cands, Vec3 player, Vec3 fwd,
                                             SelectMode mode) {
    for (const auto& c : cands)
        if (c.under_crosshair && valid(c, player, 1.0f) && (!target_ || c.id != *target_)) {
            target_ = c.id;
            return target_;
        }
    float fl = length2d(fwd);
    Vec3 f = fl > 0 ? Vec3{fwd.x / fl, fwd.y / fl, 0} : Vec3{0, 1, 0};
    std::optional<std::uint32_t> best;
    double best_score = std::numeric_limits<double>::infinity();
    for (const auto& c : cands) {
        if (!valid(c, player, 1.0f) || (target_ && c.id == *target_)) continue;
        Vec3 d = sub(c.position, player);
        float dist = length(d);
        float dot = dist > 0 ? (d.x * f.x + d.y * f.y) / dist : 1.0f;
        double score = mode == SelectMode::Closest ? dist
                       : mode == SelectMode::Center ? -dot
                                                     : dist * (1.0 - dot);
        if (score < best_score) {
            best_score = score;
            best = c.id;
        }
    }
    if (best) target_ = best;
    return best;
}

bool LockOn::update(const std::vector<Candidate>& cands, Vec3 player, double now) {
    if (!target_) return false;
    auto it = std::find_if(cands.begin(), cands.end(), [&](const Candidate& c) { return c.id == *target_; });
    if (it == cands.end() || !it->alive || !it->visible || (cfg_.hostile_only && !it->hostile)) {
        target_.reset();
        return false;
    }
    if (length(sub(it->position, player)) > cfg_.max_distance * it->size_multiplier * cfg_.keep_hysteresis) {
        target_.reset();
        return false;
    }
    if (it->line_of_sight) last_seen_ = now;
    else if (now - last_seen_ > cfg_.lost_sight_grace) {
        target_.reset();
        return false;
    }
    return true;
}

std::optional<std::uint32_t> LockOn::switch_target(const std::vector<Candidate>& cands, Vec3 player, int dx, int dy,
                                                   double now) {
    if (!target_) return std::nullopt;
    if (dx == last_switch_dx_ && dy == last_switch_dy_ && now - last_switch_ < cfg_.switch_cooldown) return std::nullopt;
    auto cur = std::find_if(cands.begin(), cands.end(), [&](const Candidate& c) { return c.id == *target_; });
    if (cur == cands.end()) return std::nullopt;
    float wx = static_cast<float>(dx), wy = static_cast<float>(dy);
    float wl = std::sqrt(wx * wx + wy * wy);
    if (wl == 0) return std::nullopt;
    wx /= wl;
    wy /= wl;
    std::optional<std::uint32_t> best;
    double best_score = std::numeric_limits<double>::infinity();
    for (const auto& c : cands) {
        if (c.id == *target_ || !c.on_screen || !valid(c, player, 1.0f)) continue;
        float sx = c.screen_x - cur->screen_x, sy = c.screen_y - cur->screen_y;
        if (sx * wx + sy * wy <= 0) continue;                           // not on the requested side
        float dist = std::sqrt(sx * sx + sy * sy);
        float align = dist > 0 ? (sx * wx + sy * wy) / dist : 1.0f;
        double score = dist * (2.0 - align);                            // closer to the requested direction wins
        if (score < best_score) {
            best_score = score;
            best = c.id;
        }
    }
    if (best) {
        target_ = best;
        last_switch_ = now;
        last_switch_dx_ = dx;
        last_switch_dy_ = dy;
    }
    return best;
}

// ------------------------------------------------------------------------------------------------ input table
std::vector<Binding> parse_bindings(std::string_view ini, std::string_view section) {
    std::vector<Binding> out;
    bool in = false;
    for (const auto& raw : split(ini, '\n')) {
        std::string_view line = trim(raw);
        if (line.empty() || line.front() == ';' || line.front() == '#') continue;
        if (line.front() == '[') {
            auto close = line.find(']');
            in = close != std::string_view::npos && iequals(trim(line.substr(1, close - 1)), section);
            continue;
        }
        if (!in) continue;
        auto eq = line.find('=');
        if (eq == std::string_view::npos) continue;
        auto parts = split(trim(line.substr(eq + 1)), '|');
        if (parts.size() < 2) continue;
        std::uint32_t key = 0;
        const auto& k = parts[0];
        bool hex = k.size() > 2 && (k.rfind("0x", 0) == 0 || k.rfind("0X", 0) == 0);
        const char* first = k.data() + (hex ? 2 : 0);
        const char* last = k.data() + k.size();
        auto res = std::from_chars(first, last, key, hex ? 16 : 10);
        if (res.ec != std::errc() || res.ptr != last) continue;
        out.push_back({std::string(trim(line.substr(0, eq))), key, parts[1], parts.size() > 2 ? parts[2] : ""});
    }
    return out;
}

}  // namespace s2s::combat
