#include "s2s/left_copy.h"

#include <algorithm>
#include <cctype>
#include <cstring>

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
