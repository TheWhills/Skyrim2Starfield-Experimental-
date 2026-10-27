// Tests for node transform math (s2s/xform.h). Same mini harness as test_combat.cpp.
#include "s2s/xform.h"

#include <cmath>
#include <cstdio>

using namespace s2s::combat;

static int failures = 0;
#define CHECK(cond)                                                                   \
    do {                                                                              \
        if (!(cond)) {                                                                \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);               \
            ++failures;                                                               \
        }                                                                             \
    } while (0)

static bool near(const Xform& a, const Xform& b) {
    for (int i = 0; i < 3; ++i) {
        if (std::fabs(a.t[i] - b.t[i]) > 1e-3f) return false;
        for (int j = 0; j < 3; ++j)
            if (std::fabs(a.r[i][j] - b.r[i][j]) > 1e-4f) return false;
    }
    return std::fabs(a.s - b.s) < 1e-5f;
}

static Xform yaw(float deg, float x, float y, float z, float s = 1.0f) {
    const float c = std::cos(deg * 3.14159265f / 180.0f), n = std::sin(deg * 3.14159265f / 180.0f);
    Xform o;
    o.r = {{{c, -n, 0}, {n, c, 0}, {0, 0, 1}}};
    o.t = {x, y, z};
    o.s = s;
    return o;
}

int main() {
    // the owner's dump: the player's root at (-796.98, 1515.3, -161.5), rows (0.768, 0.640, 0) (-0.640, 0.768, 0)
    Xform root;
    root.r = {{{0.7684f, 0.6399f, 0}, {-0.6399f, 0.7684f, 0}, {0, 0, 1}}};
    root.t = {-796.98f, 1515.3f, -161.5f};
    const Xform weapon = compose(root, yaw(30, 0.3f, 0.2f, 1.1f));    // the weapon node (right hand)
    const Xform wrist = compose(root, yaw(-70, -0.3f, 0.25f, 1.0f));  // the left wrist bone
    const Xform local = local_for(weapon, wrist);
    CHECK(near(compose(weapon, local), wrist));                        // the child lands on the bone
    CHECK(near(compose(inverse(wrist), wrist), Xform{}));
    const Xform scaled = yaw(45, 1, 2, 3, 2.0f);                       // scaled parents too
    CHECK(near(compose(scaled, local_for(scaled, wrist)), wrist));
    CHECK(near(compose(yaw(10, 1, 0, 0), yaw(20, 0, 1, 0)), compose(yaw(10, 1, 0, 0), yaw(20, 0, 1, 0))));
    Xform zero;
    zero.s = 0.0f;                                                     // no division by zero
    CHECK(inverse(zero).s == 1.0f);
    if (failures) {
        std::printf("%d failure(s)\n", failures);
        return 1;
    }
    std::printf("xform: all tests passed\n");
    return 0;
}
