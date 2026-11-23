// Tests for the left-hand copy test's game-independent part (s2s/left_copy.h). Same mini harness as test_combat.cpp.
#include "s2s/left_copy.h"

#include <cstdio>
#include <cmath>
#include <cstring>

using namespace s2s::combat;
using A = LeftCopy::Action;
using L = CloningProcessLayout;

static int failures = 0;
#define CHECK(cond)                                                                   \
    do {                                                                              \
        if (!(cond)) {                                                                \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);               \
            ++failures;                                                               \
        }                                                                             \
    } while (0)

// The bytes the engine writes at 0x140e4b9b0: maps zeroed, copy type, 0x2400 at +0x24 ('$' at +0x25), 1, scale 1.
static void cloning_process_layout() {
    const auto b = cloning_process_bytes(0x12345678u);
    CHECK(b.size() == 0x38);
    for (std::size_t i = 0; i < 0x20; ++i) CHECK(b[i] == 0);             // root, +0x08, count, spare
    std::uint32_t t = 0;
    std::memcpy(&t, b.data() + L::kCopyType, 4);
    CHECK(t == 0x12345678u);
    std::uint16_t w = 0;
    std::memcpy(&w, b.data() + 0x24, 2);
    CHECK(w == 0x2400);                                                 // the engine's 16-bit store
    CHECK(b[L::kAppendChar] == '$');
    CHECK(b[L::kFlag] == 1);
    CHECK(b[0x27] == 0);
    for (int i = 0; i < 3; ++i) {
        float f = 0.0f;
        std::memcpy(&f, b.data() + L::kScale + 4 * i, 4);
        CHECK(f == 1.0f);
    }
    for (std::size_t i = 0x34; i < 0x38; ++i) CHECK(b[i] == 0);
}

static void key_toggles() {
    LeftCopy c;
    CHECK(c.on_key() == A::Make);
    CHECK(c.on_key() == A::None);                 // still being made
    c.on_result(A::Make, true);
    CHECK(c.attached());
    CHECK(c.on_key() == A::Drop);
    c.on_result(A::Drop, true);
    CHECK(!c.attached());
    CHECK(c.on_key() == A::Make);
    c.on_result(A::Make, false);                  // failed (no weapon drawn, node missing): nothing on
    CHECK(!c.attached());
    CHECK(c.on_key() == A::Make);
}

static void sheathe_unequip_and_load_drop() {
    LeftCopy c;
    CHECK(c.on_event("weaponSheathe") == A::None);           // nothing on
    CHECK(c.on_menu("LoadingMenu", true) == A::None);
    c.on_key();
    c.on_result(A::Make, true);
    CHECK(c.on_event("BeginWeaponDraw") == A::None);
    CHECK(c.on_event("WeaponSheathe") == A::Drop);           // any case
    CHECK(c.on_event("weaponSheathe") == A::None);           // the game sends it twice: one drop
    c.on_result(A::Drop, true);
    c.on_key();
    c.on_result(A::Make, true);
    CHECK(c.on_event("UnequipComplete") == A::Drop);
    c.on_result(A::Drop, false);                             // a failed drop is not retried
    CHECK(!c.attached());
    c.on_key();
    c.on_result(A::Make, true);
    CHECK(c.on_menu("LoadingMenu", false) == A::None);       // closing: too late, the 3D is new
    CHECK(c.on_menu("InventoryMenu", true) == A::None);
    CHECK(c.on_menu("LoadingMenu", true) == A::Drop);
}

static void names_and_model_pick() {
    const auto l = split_names(" WeaponLeft, ,L_Wrist ,");
    CHECK(l.size() == 2);
    CHECK(l.size() == 2 && l[0] == "WeaponLeft" && l[1] == "L_Wrist");
    CHECK(split_names("").empty());
    // the owner's run 2026-11-23: the "Weapon" node's children
    const std::vector<std::string_view> kids{"R_HandIk", "L_HandIk", "Weapon"};
    const auto skip = split_names("R_HandIk, l_handik");
    CHECK(pick_model(kids, "", skip) == 2);
    CHECK(pick_model(kids, "", {}) == 0);
    CHECK(pick_model(kids, "weapon", skip) == 2);          // override, any case
    CHECK(pick_model(kids, "Longsword", skip) == -1);      // override not there: nothing (no guessing)
    CHECK(pick_model({"R_HandIk", "L_HandIk"}, "", skip) == -1);
}

static bool near(float a, float b) { return std::fabs(a - b) < 1e-4f; }

static void turns_and_angles() {
    // 24 distinct proper rotations (orthonormal, determinant +1), 0 = identity, index wraps
    for (int i = 0; i < 24; ++i) {
        const auto r = turn(i).r;
        const float det = r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1]) -
                          r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0]) +
                          r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]);
        CHECK(near(det, 1.0f));
        for (int j = 0; j < i; ++j) CHECK(turn(j).r != r);
    }
    CHECK(turn(0).r == Xform{}.r);
    CHECK(turn(24).r == turn(0).r && turn(-1).r == turn(23).r);
    // 90 degrees about z takes x to y
    const auto z90 = euler_degrees(0, 0, 90).r;
    CHECK(near(z90[1][0], 1.0f) && near(z90[0][0], 0.0f));
    float d[3] = {9, 9, 9};
    CHECK(parse_degrees(" 0, 90 -45.5 ", d) && d[0] == 0 && d[1] == 90 && near(d[2], -45.5f));
    CHECK(!parse_degrees("0 90", d) && !parse_degrees("a b c", d) && !parse_degrees("1 2 3 4", d));
    CHECK(d[2] == -45.5f);                                       // untouched on failure
    // oriented keeps translation and scale, turns only the rotation
    Xform o;
    o.t = {1, 2, 3};
    o.s = 2;
    const float none[3] = {0, 0, 0};
    const auto same = oriented(o, 0, none);
    CHECK(same.t == o.t && same.s == 2 && same.r == o.r);
    const float y180[3] = {0, 180, 0};
    const auto flipped = oriented(o, 0, y180);
    CHECK(near(flipped.r[0][0], -1) && near(flipped.r[2][2], -1) && flipped.t == o.t);
}

static void disabled() {
    LeftCopy c(false);
    CHECK(c.on_key() == A::None);
    CHECK(c.on_event("weaponSheathe") == A::None);
}

int main() {
    cloning_process_layout();
    key_toggles();
    sheathe_unequip_and_load_drop();
    names_and_model_pick();
    turns_and_angles();
    disabled();
    if (failures) {
        std::printf("%d failure(s)\n", failures);
        return 1;
    }
    std::printf("left copy: all passed\n");
    return 0;
}
