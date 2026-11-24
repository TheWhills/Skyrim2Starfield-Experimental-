#include "s2s/left_copy.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>

namespace s2s::combat {

namespace {
bool iequals(std::string_view a, std::string_view b) {
    return a.size() == b.size() && std::equal(a.begin(), a.end(), b.begin(), [](char x, char y) {
               return std::tolower(static_cast<unsigned char>(x)) == std::tolower(static_cast<unsigned char>(y));
           });
}
}  // namespace

std::array<std::uint8_t, CloningProcessLayout::kSize> cloning_process_bytes(std::uint32_t copy_type) {
    using L = CloningProcessLayout;
    std::array<std::uint8_t, L::kSize> b{};
    std::memcpy(b.data() + L::kCopyType, &copy_type, 4);
    b[L::kAppendChar] = '$';
    b[L::kFlag] = 1;
    const float one = 1.0f;
    for (int i = 0; i < 3; ++i) std::memcpy(b.data() + L::kScale + 4 * i, &one, 4);
    return b;
}

std::vector<std::string_view> split_names(std::string_view list) {
    std::vector<std::string_view> out;
    while (!list.empty()) {
        const auto comma = list.find(',');
        auto name = list.substr(0, comma);
        list = comma == std::string_view::npos ? std::string_view{} : list.substr(comma + 1);
        while (!name.empty() && std::isspace(static_cast<unsigned char>(name.front()))) name.remove_prefix(1);
        while (!name.empty() && std::isspace(static_cast<unsigned char>(name.back()))) name.remove_suffix(1);
        if (!name.empty()) out.push_back(name);
    }
    return out;
}

int pick_model(const std::vector<std::string_view>& children, std::string_view override_name,
               const std::vector<std::string_view>& skip) {
    for (std::size_t i = 0; i < children.size(); ++i) {
        if (!override_name.empty()) {
            if (iequals(children[i], override_name)) return static_cast<int>(i);
            continue;
        }
        if (std::none_of(skip.begin(), skip.end(), [&](std::string_view s) { return iequals(children[i], s); }))
            return static_cast<int>(i);
    }
    return -1;
}

namespace {
using M = std::array<std::array<float, 3>, 3>;
M mul(const M& a, const M& b) {
    M r{};
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            for (int k = 0; k < 3; ++k) r[i][j] += a[i][k] * b[k][j];
    return r;
}
M axis_rot(int axis, float rad) {
    const float c = std::cos(rad), s = std::sin(rad);
    if (axis == 0) return {{{1, 0, 0}, {0, c, -s}, {0, s, c}}};
    if (axis == 1) return {{{c, 0, s}, {0, 1, 0}, {-s, 0, c}}};
    return {{{c, -s, 0}, {s, c, 0}, {0, 0, 1}}};
}
M snap(M m) {
    for (auto& row : m)
        for (auto& v : row) v = std::round(v);
    return m;
}
}  // namespace

Xform turn(int index) {
    // the 24 = 6 directions for the x axis (+x, -x, +y, -y, +z, -z: identity, z180, z90, z-90, y-90, y90) x 4 turns
    // about the new x axis
    static const float q = 1.5707963267948966f;
    static const M face[6] = {snap(axis_rot(2, 0)),      snap(axis_rot(2, 2 * q)), snap(axis_rot(2, q)),
                              snap(axis_rot(2, -q)),     snap(axis_rot(1, -q)),    snap(axis_rot(1, q))};
    const int i = ((index % 24) + 24) % 24;
    Xform x;
    x.r = snap(mul(face[i / 4], axis_rot(0, q * static_cast<float>(i % 4))));
    return x;
}

Xform euler_degrees(float x, float y, float z) {
    const float k = 3.14159265358979f / 180.0f;
    Xform r;
    r.r = mul(axis_rot(2, z * k), mul(axis_rot(1, y * k), axis_rot(0, x * k)));
    return r;
}

bool parse_degrees(std::string_view text, float out[3]) {
    std::string s(text);
    for (auto& c : s)
        if (c == ',') c = ' ';
    float v[3];
    int n = 0;
    std::size_t pos = 0;
    while (n < 3) {
        while (pos < s.size() && s[pos] == ' ') ++pos;
        if (pos >= s.size()) break;
        std::size_t used = 0;
        try {
            v[n] = std::stof(s.substr(pos), &used);
        } catch (...) {
            return false;
        }
        pos += used;
        ++n;
    }
    while (pos < s.size() && s[pos] == ' ') ++pos;
    if (n != 3 || pos != s.size()) return false;
    for (int i = 0; i < 3; ++i) out[i] = v[i];
    return true;
}

std::string copy_node_name(std::string_view name) {
    if (name.empty() || name.starts_with(kCopyNamePrefix)) return std::string(name);
    return std::string(kCopyNamePrefix) + std::string(name);
}

HandSlots hand_slots(std::uint32_t left_id, std::uint32_t right_id) {
    HandSlots h;
    if (right_id) h.right_weapon = kSlotRightHand;
    if (left_id && left_id != right_id) h.left_weapon = kSlotLeftHand;
    return h;
}

std::string format_hand_pair(const HandPair& p) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "right=%08X\nleft=%08X\n", p.right, p.left);
    return buf;
}

std::optional<HandPair> parse_hand_pair(std::string_view text) {
    HandPair p;
    while (!text.empty()) {
        const auto nl = text.find('\n');
        auto line = text.substr(0, nl);
        text = nl == std::string_view::npos ? std::string_view{} : text.substr(nl + 1);
        const auto eq = line.find('=');
        if (eq == std::string_view::npos) continue;
        auto key = line.substr(0, eq);
        while (!key.empty() && std::isspace(static_cast<unsigned char>(key.back()))) key.remove_suffix(1);
        while (!key.empty() && std::isspace(static_cast<unsigned char>(key.front()))) key.remove_prefix(1);
        const auto id = parse_form_id(line.substr(eq + 1));
        if (iequals(key, "right")) p.right = id.value_or(0);
        if (iequals(key, "left")) p.left = id.value_or(0);
    }
    if (!p.right || !p.left) return std::nullopt;
    return p;
}

AfterLoad after_load(bool records_set, std::uint32_t expected_left, std::uint32_t left_in_hand, bool drawn,
                     bool left_model, bool right_model, double waited) {
    const bool has_left = left_in_hand != 0 && left_in_hand != 0x1F4u;     // 000001F4 = fists
    if (!has_left) return records_set ? AfterLoad::UndoRecords : AfterLoad::Nothing;
    if (records_set && left_in_hand == expected_left) {
        if (!drawn || (left_model && right_model)) return AfterLoad::Keep;
        if (waited < kAfterLoadWait) return AfterLoad::Wait;
    }
    return AfterLoad::Redo;
}

std::optional<std::uint32_t> parse_form_id(std::string_view text) {
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.front()))) text.remove_prefix(1);
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.back()))) text.remove_suffix(1);
    if (text.size() > 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) text.remove_prefix(2);
    if (text.empty() || text.size() > 8) return std::nullopt;
    std::uint32_t v = 0;
    for (char c : text) {
        int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (d < 0) return std::nullopt;
        v = v * 16 + static_cast<std::uint32_t>(d);
    }
    if (v == 0) return std::nullopt;
    return v;
}

FollowStep follow_step(bool on_wrist, bool active, long refs_now, long refs_at_move, bool new_model_under_weaponleft) {
    if (!on_wrist) return FollowStep::Forget;
    if (!active || refs_now < refs_at_move || new_model_under_weaponleft) return FollowStep::LetGo;
    return FollowStep::Keep;
}

Xform left_grip() {
    Xform g;
    g.r = {{{-0.179094f, 0.980503f, 0.080866f}, {-0.231144f, 0.037960f, -0.972179f}, {-0.956294f, -0.192803f, 0.219839f}}};
    g.t = {0.068f, -0.011f, -0.038f};
    return g;
}

Xform oriented(const Xform& original, int turn_index, const float degrees[3]) {
    Xform out = original;
    out.r = mul(original.r, mul(turn(turn_index).r, euler_degrees(degrees[0], degrees[1], degrees[2]).r));
    return out;
}

LeftCopy::Action LeftCopy::on_key() {
    if (!enabled_ || busy()) return Action::None;
    pending_ = attached_ ? Action::Drop : Action::Make;
    return pending_;
}

LeftCopy::Action LeftCopy::on_event(std::string_view tag) {
    if (!enabled_ || !attached_ || busy()) return Action::None;
    if (iequals(tag, "weaponSheathe") || iequals(tag, "UnequipComplete")) {
        pending_ = Action::Drop;
        return pending_;
    }
    return Action::None;
}

LeftCopy::Action LeftCopy::on_menu(std::string_view name, bool opening) {
    if (!enabled_ || !attached_ || busy() || !opening || !iequals(name, "LoadingMenu")) return Action::None;
    pending_ = Action::Drop;
    return pending_;
}

void LeftCopy::on_result(Action what, bool ok) {
    if (what == Action::Make) attached_ = ok;
    if (what == Action::Drop) attached_ = false;
    if (what == pending_) pending_ = Action::None;
}

}  // namespace s2s::combat
