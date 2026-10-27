#include "s2s/left_blade.h"

#include <algorithm>
#include <cctype>

namespace s2s::combat {

namespace {
bool same(std::string_view a, std::string_view b) {
    return a.size() == b.size() && std::equal(a.begin(), a.end(), b.begin(), [](char x, char y) {
               return std::tolower(static_cast<unsigned char>(x)) == std::tolower(static_cast<unsigned char>(y));
           });
}
}  // namespace

bool LeftBlade::on_worn(bool worn) {
    worn_ = worn;
    if (worn || unparking_) parked_ = false;   // put on again (or that did not work: the blade is gone)
    unparking_ = false;
    return this->worn();
}

LeftBlade::Action LeftBlade::on_event(std::string_view tag) {
    if (!enabled_) return Action::None;
    if (same(tag, "weaponSheathe") && worn_ && !parked_) {
        parked_ = true;
        worn_ = false;
        return Action::Park;
    }
    if (same(tag, "BeginWeaponDraw") && parked_) {
        unparking_ = true;
        return Action::Unpark;
    }
    return Action::None;
}

LeftBlade::Action LeftBlade::on_drawn(bool drawn) {
    if (!enabled_ || drawn || !worn_ || parked_) return Action::None;
    parked_ = true;
    worn_ = false;
    return Action::Park;
}

void LeftBlade::on_failed(Action what) {
    if (what == Action::Park) {
        parked_ = false;
        worn_ = true;               // still on
    } else if (what == Action::Unpark) {
        parked_ = false;            // gone: the next poll (not worn) switches the moveset back
        unparking_ = false;
    }
}

void LeftBlade::on_load(bool dual_keyword, bool blade_in_inventory, bool worn) {
    worn_ = worn;
    parked_ = enabled_ && !worn && dual_keyword && blade_in_inventory;
}

}  // namespace s2s::combat
