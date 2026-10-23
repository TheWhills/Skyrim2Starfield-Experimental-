// Implementation of include/s2s/controller.h.
#include "s2s/controller.h"

#include <algorithm>
#include <cctype>
#include <charconv>
#include <cmath>
#include <cstdlib>

namespace s2s::combat {
namespace {

std::string_view trim(std::string_view s) {
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.front()))) s.remove_prefix(1);
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.back()))) s.remove_suffix(1);
    return s;
}

std::string lower(std::string_view s) {
    std::string out(s);
    for (auto& c : out) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return out;
}

bool is(std::string_view a, std::string_view b) { return lower(a) == lower(b); }

bool is_any(std::string_view e, std::initializer_list<std::string_view> names) {
    return std::any_of(names.begin(), names.end(), [&](std::string_view n) { return is(e, n); });
}

bool read_uint(std::string_view s, std::uint32_t& out) {
    s = trim(s);
    bool hex = s.size() > 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X');
    if (hex) s.remove_prefix(2);
    if (s.empty()) return false;
    auto res = std::from_chars(s.data(), s.data() + s.size(), out, hex ? 16 : 10);
    return res.ec == std::errc() && res.ptr == s.data() + s.size();
}

bool read_double(std::string_view s, double& out) {
    std::string tmp(trim(s));
    if (tmp.empty()) return false;
    char* end = nullptr;
    double v = std::strtod(tmp.c_str(), &end);
    if (!end || *end != '\0') return false;
    out = v;
    return true;
}

bool read_bool(std::string_view s, bool& out) {
    auto v = lower(trim(s));
    if (v == "1" || v == "true" || v == "yes" || v == "on") return out = true, true;
    if (v == "0" || v == "false" || v == "no" || v == "off") return out = false, true;
    return false;
}

// "Name=Value" binding argument for the int / bool / float actions.
std::optional<VariableSet> binding_variable(const Binding& b) {
    auto eq = b.argument.find('=');
    if (eq == std::string::npos) return std::nullopt;
    VariableSet v{VariableSet::Type::Int, std::string(trim(std::string_view(b.argument).substr(0, eq))), 0.0};
    if (v.name.empty() || !read_double(std::string_view(b.argument).substr(eq + 1), v.value)) return std::nullopt;
    if (is(b.action, "bool")) {
        v.type = VariableSet::Type::Bool;
        v.value = v.value != 0.0 ? 1.0 : 0.0;
    } else if (is(b.action, "float")) {
        v.type = VariableSet::Type::Float;
    } else {
        v.value = std::trunc(v.value);
    }
    return v;
}

Command event(std::string name) { return {Command::Kind::SendEvent, std::move(name)}; }
Command log(std::string text) { return {Command::Kind::Log, std::move(text)}; }

}  // namespace

// ------------------------------------------------------------------------------------------------ key codes
std::uint32_t key_from_vk(std::uint32_t vk) {
    static constexpr std::uint8_t letters[26] = {0x1E, 0x30, 0x2E, 0x20, 0x12, 0x21, 0x22, 0x23, 0x17, 0x24, 0x25, 0x26, 0x32,
                                                 0x31, 0x18, 0x19, 0x10, 0x13, 0x1F, 0x14, 0x16, 0x2F, 0x11, 0x2D, 0x15, 0x2C};
    static constexpr std::uint8_t numpad[10] = {0x52, 0x4F, 0x50, 0x51, 0x4B, 0x4C, 0x4D, 0x47, 0x48, 0x49};
    if (vk >= 'A' && vk <= 'Z') return letters[vk - 'A'];
    if (vk >= '1' && vk <= '9') return 0x02 + (vk - '1');
    if (vk == '0') return 0x0B;
    if (vk >= 0x60 && vk <= 0x69) return numpad[vk - 0x60];
    if (vk >= 0x70 && vk <= 0x79) return 0x3B + (vk - 0x70);                 // F1-F10
    switch (vk) {
        case 0x08: return 0x0E;  case 0x09: return 0x0F;  case 0x0D: return 0x1C;  // backspace, tab, enter
        case 0x10: return 0x2A;  case 0x11: return 0x1D;  case 0x12: return 0x38;  // shift, ctrl, alt (left)
        case 0x13: return 0xC5;  case 0x14: return 0x3A;  case 0x1B: return 0x01;  // pause, caps lock, escape
        case 0x20: return 0x39;  case 0x21: return 0xC9;  case 0x22: return 0xD1;  // space, page up, page down
        case 0x23: return 0xCF;  case 0x24: return 0xC7;                            // end, home
        case 0x25: return 0xCB;  case 0x26: return 0xC8;  case 0x27: return 0xCD;  // left, up, right
        case 0x28: return 0xD0;  case 0x2D: return 0xD2;  case 0x2E: return 0xD3;  // down, insert, delete
        case 0x5B: return 0xDB;  case 0x5C: return 0xDC;  case 0x5D: return 0xDD;  // windows keys, menu key
        case 0x6A: return 0x37;  case 0x6B: return 0x4E;  case 0x6D: return 0x4A;  // numpad * + -
        case 0x6E: return 0x53;  case 0x6F: return 0xB5;                            // numpad . /
        case 0x7A: return 0x57;  case 0x7B: return 0x58;                            // F11, F12
        case 0x90: return 0x45;  case 0x91: return 0x46;                            // num lock, scroll lock
        case 0xA0: return 0x2A;  case 0xA1: return 0x36;  case 0xA2: return 0x1D;  // left / right shift, left ctrl
        case 0xA3: return 0x9D;  case 0xA4: return 0x38;  case 0xA5: return 0xB8;  // right ctrl, left / right alt
        case 0xBA: return 0x27;  case 0xBB: return 0x0D;  case 0xBC: return 0x33;  // ; = ,
        case 0xBD: return 0x0C;  case 0xBE: return 0x34;  case 0xBF: return 0x35;  // - . /
        case 0xC0: return 0x29;  case 0xDB: return 0x1A;  case 0xDC: return 0x2B;  // ` [ backslash
        case 0xDD: return 0x1B;  case 0xDE: return 0x28;                            // ] '
        default: return 0;
    }
}

std::uint32_t key_from_mouse(std::uint32_t id) {
    if (id < 8) return 256 + id;
    if (id == 0x800) return 264;
    if (id == 0x900) return 265;
    return 0;
}

// ------------------------------------------------------------------------------------------------ menus
MenuGate::MenuGate()
    : blocking_({"Console", "PauseMenu", "MainMenu", "LoadingMenu", "InventoryMenu", "DataMenu", "ContainerMenu",
                 "BarterMenu", "DialogueMenu", "FavoritesMenu", "PowersMenu", "SkillsMenu", "StatusMenu",
                 "GalaxyStarMapMenu", "BSMissionMenu", "PhotoModeMenu", "CharGenMenu", "LooksMenu", "WorkshopMenu",
                 "SpaceshipEditorMenu", "ShipCrewMenu", "CraftingMenu", "ResearchMenu", "PickpocketMenu",
                 "MessageBoxMenu", "SleepWaitMenu", "TextInputMenu", "BookMenu"}) {}

void MenuGate::on_menu(std::string_view name, bool opening) {
    auto it = std::find_if(open_.begin(), open_.end(), [&](const std::string& m) { return is(m, name); });
    if (opening && it == open_.end()) open_.emplace_back(name);
    if (!opening && it != open_.end()) open_.erase(it);
}

bool MenuGate::blocked() const {
    return std::any_of(open_.begin(), open_.end(), [&](const std::string& m) {
        return std::any_of(blocking_.begin(), blocking_.end(), [&](const std::string& b) { return is(b, m); });
    });
}

std::vector<std::string> MenuGate::parse_list(std::string_view text) {
    std::vector<std::string> out;
    std::size_t start = 0;
    while (start <= text.size()) {
        auto end = text.find(',', start);
        if (end == std::string_view::npos) end = text.size();
        auto name = trim(text.substr(start, end - start));
        if (!name.empty()) out.emplace_back(name);
        start = end + 1;
    }
    return out;
}

// ------------------------------------------------------------------------------------------------ pool strings
std::optional<std::string> pool_string_at(std::uintptr_t a_addr,
                                          const std::function<bool(const void*, std::size_t)>& readable) {
    // BSStringPool::Entry (CommonLibSF, 0x18 bytes): +0x08 length or, when flags (+0x14) has kExternal (0x2), a pointer
    // to the entry that holds the text (+0x08). The text follows the leaf entry. CommonLibSF's c_str() follows that
    // chain without checks; on a slot that is not a string it can walk into unmapped memory (owner's second run: the
    // game crashed while loading). Every hop is checked here instead, at most 8.
    if (!readable(reinterpret_cast<const void*>(a_addr), sizeof(void*))) return std::nullopt;
    auto entry = *reinterpret_cast<const std::uintptr_t*>(a_addr);
    if (!entry) return std::string();
    for (int hop = 0;; ++hop) {
        if (hop >= 8 || !readable(reinterpret_cast<const void*>(entry), 0x18)) return std::nullopt;
        const auto flags = *reinterpret_cast<const std::uint8_t*>(entry + 0x14);
        if (!(flags & 0x2)) break;
        entry = *reinterpret_cast<const std::uintptr_t*>(entry + 0x08);
        if (!entry) return std::nullopt;
    }
    const auto length = *reinterpret_cast<const std::uint32_t*>(entry + 0x08);
    if (length > 256) return std::nullopt;
    const char* text = reinterpret_cast<const char*>(entry + 0x18);
    if (!readable(text, length + 1)) return std::nullopt;
    std::string out;
    for (std::uint32_t i = 0; i < length; ++i) {
        const char ch = text[i];
        if (ch < 0x20 || ch > 0x7E) return std::nullopt;
        out.push_back(ch);
    }
    if (text[length] != '\0') return std::nullopt;
    return out;
}

// ------------------------------------------------------------------------------------------------ layout probe
LayoutProbe::State LayoutProbe::feed(const std::vector<Slot>& slots) {
    if (state_ != State::Probing) return state_;
    ++seen_;
    int tag = -1, payload = -1, holder = -1;
    for (int i = 0; i < static_cast<int>(slots.size()); ++i) {
        if (slots[i] == Slot::Self && holder < 0) holder = i;
        if (tag < 0 && slots[i] == Slot::Text) {
            tag = i;
        } else if (tag >= 0 && payload < 0 && (slots[i] == Slot::Text || slots[i] == Slot::EmptyText)) {
            payload = i;
        }
    }
    if (tag >= 0 && streak_ > 0 && tag == tag_ && payload == payload_) {
        ++streak_;
    } else if (tag >= 0) {
        tag_ = tag;
        payload_ = payload;
        streak_ = 1;
    } else {
        streak_ = 0;
    }
    if (holder >= 0) holder_ = holder;
    if (streak_ >= needed_) {
        state_ = State::Found;
    } else if (seen_ >= give_up_) {
        state_ = State::Failed;
        tag_ = payload_ = -1;
    }
    return state_;
}

// ------------------------------------------------------------------------------------------------ settings
std::map<std::string, std::string> ini_section(std::string_view ini, std::string_view section) {
    std::map<std::string, std::string> out;
    bool in = false;
    std::size_t start = 0;
    while (start <= ini.size()) {
        auto end = ini.find('\n', start);
        if (end == std::string_view::npos) end = ini.size();
        auto line = trim(ini.substr(start, end - start));
        start = end + 1;
        if (line.empty() || line.front() == ';' || line.front() == '#') continue;
        if (line.front() == '[') {
            auto close = line.find(']');
            in = close != std::string_view::npos && is(trim(line.substr(1, close - 1)), section);
            continue;
        }
        auto eq = line.find('=');
        if (!in || eq == std::string_view::npos) continue;
        auto value = trim(line.substr(eq + 1));
        auto comment = value.find_first_of(";#");          // trailing comment
        if (comment != std::string_view::npos) value = trim(value.substr(0, comment));
        out[lower(trim(line.substr(0, eq)))] = std::string(value);
    }
    return out;
}

ControllerConfig parse_config(std::string_view ini, std::vector<std::string>* problems) {
    ControllerConfig c;
    auto bad = [&](const std::string& k, const std::string& v) {
        if (problems) problems->push_back("[Combat] " + k + " = " + v + ": not understood, default kept");
    };
    for (const auto& [k, v] : ini_section(ini, "Combat")) {
        bool ok = true;
        double d = 0;
        if (k == "bbufferattacks") ok = read_bool(v, c.buffer_attacks);
        else if (k == "fbuffertime") ok = read_double(v, c.buffer_time);
        else if (k == "fpowerhold") ok = read_double(v, c.power_hold);
        else if (k == "fchargehold") ok = read_double(v, c.charge_hold);
        else if (k == "uattackkey") ok = read_uint(v, c.attack_key);
        else if (k == "udodgekey") ok = read_uint(v, c.dodge_key);
        else if (k == "umoveforwardkey") ok = read_uint(v, c.move_keys[0]);
        else if (k == "umovebackkey") ok = read_uint(v, c.move_keys[1]);
        else if (k == "umoveleftkey") ok = read_uint(v, c.move_keys[2]);
        else if (k == "umoverightkey") ok = read_uint(v, c.move_keys[3]);
        else if (k == "beightwaydodge") ok = read_bool(v, c.dodge.eight_way);
        else if (k == "bdodgecancelsattacks") ok = read_bool(v, c.dodge.allow_attack_cancel);
        else if (k == "fdodgestaminacost") {
            if ((ok = read_double(v, d))) c.dodge.stamina_cost = static_cast<float>(d);
        } else if (k == "fdodgedeadzone") {
            if ((ok = read_double(v, d))) c.dodge.dead_zone = static_cast<float>(d);
        }
        else if (k == "fdodgeiframes") ok = read_double(v, c.dodge_iframes);
        else if (k == "fannotationiframes") ok = read_double(v, c.annotation_iframes);
        else if (k == "sidledodge") {
            ok = false;
            for (int i = 0; i < 8; ++i)
                if (is(dodge_event(static_cast<Direction>(i)), "TKDodge" + v)) {
                    c.dodge.idle_direction = static_cast<Direction>(i);
                    ok = true;
                }
        } else if (k == "sattackevent") c.attack_event = v;
        else if (k == "spowerattackevent") c.power_event = v;
        else if (k == "spluginevent" || k == "splugineventhost") c.plugin_event_host = v;
        else if (k == "sblockhitvariable") c.block_hit_variable = v;
        else if (k == "bstancerepeatneutral") {
            ok = v == "0" || v == "1";
            if (ok) c.stance_repeat_neutral = v == "1";
        }
        else if (k == "bstancereequip") {
            ok = v == "0" || v == "1";
            if (ok) c.stance_reequip = v == "1";
        }
        else if (k == "fstancereequipwait") {
            if ((ok = read_double(v, d) && d >= 0.0))
                c.stance_reequip_wait = d;
        }
        else if (k == "fstancereequipdelay") {
            if ((ok = read_double(v, d) && d >= 0.0))
                c.stance_reequip_delay = d;
        }
        else if (k == "sstancerefreshevents") {
            c.stance_refresh_events.clear();
            std::size_t start = 0;
            while (start <= v.size()) {
                auto end = v.find(',', start);
                if (end == std::string::npos) end = v.size();
                auto name = trim(std::string_view(v).substr(start, end - start));
                if (!name.empty()) c.stance_refresh_events.emplace_back(name);
                start = end + 1;
            }
        }
        else continue;                      // other keys belong to the game side (logging, actor values)
        if (!ok) bad(k, v);
    }
    return c;
}

// ------------------------------------------------------------------------------------------------ controller
Controller::Controller(ControllerConfig cfg, std::vector<Binding> bindings)
    : cfg_(std::move(cfg)), bindings_(std::move(bindings)) {
    buffer_.buffer_time = cfg_.buffer_time;
    buffer_.power_hold = cfg_.power_hold;
    buffer_.charge_hold = cfg_.charge_hold;
}

void Controller::movement(const PlayerState& s, float& x, float& y) const {
    x = s.stick_x;
    y = s.stick_y;
    if (std::sqrt(x * x + y * y) >= cfg_.dodge.dead_zone) return;      // the stick wins when it is used
    x = (move_held_[3] ? 1.0f : 0.0f) - (move_held_[2] ? 1.0f : 0.0f);
    y = (move_held_[0] ? 1.0f : 0.0f) - (move_held_[1] ? 1.0f : 0.0f);
}

void Controller::dodge(double t, const PlayerState& s, std::vector<Command>& out) {
    if (dodging_ || !can_dodge(s.stamina, s.staggered, phase_.phase(), cfg_.dodge)) {
        out.push_back(log(dodging_ ? "dodge ignored: already dodging" : "dodge refused (stamina / stagger / attack)"));
        return;
    }
    float x = 0, y = 0;
    movement(s, x, y);
    out.push_back(event(std::string(dodge_event(dodge_direction(x, y, cfg_.dodge)))));
    if (cfg_.dodge.stamina_cost > 0) {
        Command c{Command::Kind::SpendStamina};
        c.amount = cfg_.dodge.stamina_cost;
        out.push_back(c);
    }
    iframes_.open(t, cfg_.dodge_iframes);
    buffer_.clear();                        // an attack pressed before the dodge does not fire after it
    dodging_ = true;                        // until TKDR_DodgeEnd, or (clips without TKDR events) the i-frames' end
    dodge_events_ = false;
    dodge_at_ = t;
}

void Controller::fire_buffered(double t, std::vector<Command>& out) {
    if (auto a = buffer_.take(t, power_open_, normal_open_))
        out.push_back(event(a->kind == AttackKind::Normal ? cfg_.attack_event : cfg_.power_event));
}

std::vector<Command> Controller::on_key(std::uint32_t key, bool down, double t, const PlayerState& s) {
    std::vector<Command> out;
    for (std::size_t i = 0; i < move_held_.size(); ++i)
        if (key == cfg_.move_keys[i]) move_held_[i] = down;

    if (key == cfg_.attack_key && cfg_.buffer_attacks) {
        if (down) {
            buffer_.press(t);
        } else {
            AttackKind kind = buffer_.release(t);
            // The game handles a press itself when no attack runs or the matching window is open: only a press in
            // a closed window during an attack is kept for the next window (MCO's input buffer).
            bool game_takes_it = phase_.phase() == AttackPhase::None ||
                                 (kind == AttackKind::Normal ? normal_open_ : power_open_);
            if (game_takes_it || kind == AttackKind::Charged) buffer_.clear();
            else out.push_back(log(kind == AttackKind::Normal ? "attack buffered" : "power attack buffered"));
        }
    }
    if (key == cfg_.dodge_key && down) dodge(t, s, out);

    if (!down) return out;
    for (const auto& b : bindings_) {
        if (b.key != key) continue;
        if (is(b.action, "event")) {
            out.push_back(event(b.argument));
        } else if (is_any(b.action, {"int", "bool", "float"})) {
            if (auto v = binding_variable(b)) {
                Command c{Command::Kind::SetVariable};
                c.variable = *v;
                out.push_back(c);
            } else {
                out.push_back(log("binding " + b.name + ": argument must be Name=Value"));
            }
        } else if (is(b.action, "keyword")) {
            // Stances: the keyword bindings form one exclusive group; a binding without a keyword (LoreRim's right
            // arrow) goes back to the neutral stance (no keyword), and so does pressing the active stance again when
            // bStanceRepeatNeutral = 1 (otherwise a repeat keeps the stance). Every press
            // removes all the group's other keywords, not only the one remembered here: a keyword added by Papyrus
            // stays on the player in the save, and a loaded save may carry another stance than this session saw.
            const bool back = b.argument.empty() || (cfg_.stance_repeat_neutral && is(stance_, b.argument));
            std::string target = back ? std::string() : b.argument;
            std::vector<std::string> group;
            for (const auto& other : bindings_)
                if (is(other.action, "keyword") && !other.argument.empty() && !is(other.argument, target) &&
                    std::none_of(group.begin(), group.end(), [&](const std::string& g) { return is(g, other.argument); }))
                    group.push_back(other.argument);
            for (const auto& g : group) out.push_back({Command::Kind::RemoveKeyword, g});
            if (!target.empty()) out.push_back({Command::Kind::AddKeyword, target});
            if (!is(stance_, target)) {
                for (const auto& ev : cfg_.stance_refresh_events) out.push_back(event(ev));
                if (cfg_.stance_reequip) reequip_due_ = t + cfg_.stance_reequip_delay;
            }
            stance_ = target;
        } else if (is(b.action, "dodge")) {
            if (key != cfg_.dodge_key) dodge(t, s, out);
        } else if (is(b.action, "lock")) {
            out.push_back({Command::Kind::ToggleLock});
        } else if (is_any(b.action, {"switch_left", "switch_right", "switch_up", "switch_down"})) {
            Command c{Command::Kind::SwitchTarget};
            c.dx = is(b.action, "switch_left") ? -1 : is(b.action, "switch_right") ? 1 : 0;
            c.dy = is(b.action, "switch_up") ? 1 : is(b.action, "switch_down") ? -1 : 0;
            out.push_back(c);
        } else {
            out.push_back(log("binding " + b.name + ": unknown action " + b.action));
        }
    }
    return out;
}

std::vector<Command> Controller::on_anim_event(std::string_view tag, std::string_view payload, double t) {
    std::vector<Command> out;
    if (equip_due_ >= 0.0 && is(tag, "UnequipComplete")) {         // the stance re-equip's unequip went through
        equip_due_ = -1.0;
        out.push_back({Command::Kind::EquipWeapon});
    }
    // The Skyrim annotation this event stands for ("PIE.@SGVI|MCO_nextattack|2", "MCO_WinOpen", ...).
    std::string text;
    if (!cfg_.plugin_event_host.empty() && is(tag, cfg_.plugin_event_host)) text = std::string(payload);
    else if (payload.empty()) text = std::string(tag);
    else text = std::string(tag) + "." + std::string(payload);
    auto p = parse_payload(text);
    std::string_view name = p ? std::string_view(p->host) : std::string_view(text);

    AttackPhase before = phase_.phase();
    AttackPhase now = phase_.on_event(text);
    if (now == AttackPhase::Start && before != AttackPhase::Start) normal_open_ = power_open_ = false;   // new swing

    if (is_any(name, {"MCO_WinOpen", "BFCO_NextWinStart"})) normal_open_ = true;
    else if (is_any(name, {"MCO_PowerWinOpen", "BFCO_NextPowerWinStart"})) power_open_ = true;
    else if (is(name, "MCO_WinClose")) normal_open_ = false;
    else if (is(name, "MCO_PowerWinClose")) power_open_ = false;
    if (now == AttackPhase::None) normal_open_ = power_open_ = false;
    if (normal_open_ || power_open_) fire_buffered(t, out);

    if (is(name, "TKDR_DodgeStart")) {
        dodging_ = dodge_events_ = true;
        dodge_at_ = t;
    } else if (is(name, "TKDR_DodgeEnd")) {
        dodging_ = dodge_events_ = false;
    }
    else if (is(name, "TKDR_IframeDuration")) iframes_.open(t, cfg_.annotation_iframes);
    else if (is(name, "TKDR_IframeEnd")) iframes_.close(t);

    if (p) {
        if (auto v = as_variable_set(*p)) {
            Command c{Command::Kind::SetVariable};
            c.variable = *v;
            out.push_back(c);
        } else {
            out.push_back(log("payload not handled yet: " + text));   // CAMSHAKE, CAST, $custom, ...
        }
    }
    return out;
}

HitKind hit_kind(std::string_view attack_event) {
    if (trim(attack_event).empty()) return HitKind::Unknown;
    return lower(attack_event).find("power") != std::string::npos ? HitKind::Power : HitKind::Normal;
}

std::vector<Command> Controller::on_hit(HitKind kind, bool blocking, double t) {
    std::vector<Command> out;
    if (iframes_.invulnerable(t))
        out.push_back(log("hit during i-frames (the interim ghost did not stop it: a damage hook is needed)"));
    if (blocking && !cfg_.block_hit_variable.empty()) {
        Command c{Command::Kind::SetVariable};
        c.variable = {VariableSet::Type::Int, cfg_.block_hit_variable, kind == HitKind::Power ? 1.0 : 0.0};
        out.push_back(c);
    }
    return out;
}

std::vector<Command> Controller::tick(double t, const PlayerState& s) {
    std::vector<Command> out;
    if (cfg_.buffer_attacks && buffer_.charge_started(t))
        out.push_back(log("charged attack hold reached (no charged-attack states in the graph yet)"));
    // A dodge ends with TKDR_DodgeEnd; clips without TKDR events end it when the i-frames run out; a lost end event
    // cannot block dodging for longer than dodge_timeout.
    if (dodging_ && ((!dodge_events_ && !iframes_.invulnerable(t)) || t - dodge_at_ > dodge_timeout))
        dodging_ = dodge_events_ = false;
    if (reequip_due_ >= 0.0 && t >= reequip_due_ && equip_due_ < 0.0) {
        reequip_due_ = -1.0;
        equip_due_ = t + cfg_.stance_reequip_wait;
        out.push_back({Command::Kind::UnequipWeapon});
    } else if (equip_due_ >= 0.0 && t >= equip_due_) {
        equip_due_ = -1.0;
        out.push_back({Command::Kind::EquipWeapon});
    }
    (void)s;                                // stamina regeneration etc. stay with the game
    return out;
}

}  // namespace s2s::combat
