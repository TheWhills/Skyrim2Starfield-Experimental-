// Tests for the dual wield left blade put away while sheathed (s2s/left_blade.h). Same mini harness as test_combat.cpp.
#include "s2s/left_blade.h"

#include <cstdio>

using namespace s2s::combat;
using A = LeftBlade::Action;

static int failures = 0;
#define CHECK(cond)                                                                   \
    do {                                                                              \
        if (!(cond)) {                                                                \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);               \
            ++failures;                                                               \
        }                                                                             \
    } while (0)

static void sheathe_and_draw() {
    LeftBlade b;
    CHECK(!b.on_worn(false));
    CHECK(b.on_event("weaponSheathe") == A::None);             // nothing worn: nothing to put away
    CHECK(b.on_worn(true));
    CHECK(b.on_event("BeginWeaponDraw") == A::None);           // worn, not parked
    CHECK(b.on_event("WeaponSheathe") == A::Park);             // any case
    CHECK(b.parked());
    CHECK(b.on_worn(false));                                   // taken off by us: the moveset stays dual
    CHECK(b.on_event("weaponSheathe") == A::None);             // the game sends it twice
    CHECK(b.on_event("BeginWeaponDraw") == A::Unpark);
    CHECK(b.on_worn(true));                                    // the poll after the equip
    CHECK(!b.parked());
    CHECK(b.on_event("weaponSheathe") == A::Park);
    CHECK(b.on_event("BeginWeaponDraw") == A::Unpark);
    CHECK(!b.on_worn(false));                                  // the equip did not happen: the moveset goes back
    CHECK(!b.parked());
}

static void equipped_while_sheathed() {
    LeftBlade b;
    b.on_worn(true);
    CHECK(b.on_drawn(true) == A::None);
    CHECK(b.on_drawn(false) == A::Park);
    CHECK(b.on_drawn(false) == A::None);                       // once
    CHECK(b.worn());
}

static void failures_and_removal() {
    LeftBlade b;
    b.on_worn(true);
    CHECK(b.on_event("weaponSheathe") == A::Park);
    b.on_failed(A::Park);                                      // could not take it off: still worn, not parked
    CHECK(!b.parked() && b.worn());
    CHECK(b.on_event("weaponSheathe") == A::Park);
    CHECK(b.on_event("BeginWeaponDraw") == A::Unpark);
    b.on_failed(A::Unpark);                                    // no blade known
    CHECK(!b.on_worn(false));                                  // the moveset goes back
    CHECK(b.on_event("BeginWeaponDraw") == A::None);
}

static void after_a_load() {
    LeftBlade b;
    b.on_load(true, true, false);                              // saved while put away
    CHECK(b.parked() && b.worn());
    CHECK(b.on_event("BeginWeaponDraw") == A::Unpark);
    LeftBlade c;
    c.on_load(false, true, false);                             // in the bag, never worn with the dual stance
    CHECK(!c.worn());
    c.on_load(true, false, false);                             // the keyword left over, no blade
    CHECK(!c.worn());
    c.on_load(true, true, true);                               // worn: nothing parked
    CHECK(c.worn() && !c.parked());
}

static void disabled() {
    LeftBlade b(false);
    b.on_worn(true);
    CHECK(b.on_event("weaponSheathe") == A::None);
    CHECK(b.on_drawn(false) == A::None);
    b.on_load(true, true, false);
    CHECK(!b.parked());
}

int main() {
    sheathe_and_draw();
    equipped_while_sheathed();
    failures_and_removal();
    after_a_load();
    disabled();
    if (failures) {
        std::printf("%d failure(s)\n", failures);
        return 1;
    }
    std::printf("left blade: all tests passed\n");
    return 0;
}
