// The worn left blade of dual wield (an ARMO carrying S2SCombat.ini sDualWornKeyword) put away while the weapon is
// sheathed and worn again when it is drawn.
//
// Why equipping: the owner's runs of 2026-10-26 showed setting the "hidden" flag (NiAVObject +0x118 bit 0) on the
// blade's node did not hide it, though the game hides the outfit under a spacesuit with that same bit (the renderer
// keeps its own copy, or the game writes the flag back). Taking the blade off and putting it on again is what the game
// itself does with worn items. Starfield shows no sheathed weapons, so the blade goes away on 'weaponSheathe' (when
// the right-hand weapon disappears) and comes back on 'BeginWeaponDraw'.
//
// While the blade is put away ("parked") the dual moveset stays on: worn() answers true, so the controller does not
// switch stance back and forth on every draw. After a game load, a parked blade (the save was made with it put away)
// is recognized by the dual stance keyword still on the player while the blade is in the inventory but not worn.
#pragma once

#include <string_view>

namespace s2s::combat {

class LeftBlade {
public:
    enum class Action { None, Park, Unpark };     // Park: unequip the blade; Unpark: equip it again

    explicit LeftBlade(bool enabled = true) : enabled_(enabled) {}

    // The worn-keyword poll's answer; returns whether the dual moveset should be on (worn, or parked by us).
    bool on_worn(bool worn);
    // The player's animation events: 'weaponSheathe' parks a worn blade, 'BeginWeaponDraw' unparks a parked one.
    Action on_event(std::string_view tag);
    // Whether the weapon is drawn, asked once when the blade is first seen worn (e.g. equipped in the menu while
    // sheathed): sheathed parks it.
    Action on_drawn(bool drawn);
    // The equip / unequip did not happen (the blade was dropped, sold, ...): forget the parking.
    void on_failed(Action what);
    // After a load (the first poll): the dual stance keyword on the player and a blade in the inventory, not worn,
    // means the save was made with the blade parked.
    void on_load(bool dual_keyword, bool blade_in_inventory, bool worn);
    void reset() { parked_ = false; worn_ = false; }

    bool parked() const { return parked_; }
    bool worn() const { return worn_ || parked_; }

private:
    bool enabled_;
    bool parked_ = false;
    bool worn_ = false;
};

}  // namespace s2s::combat
