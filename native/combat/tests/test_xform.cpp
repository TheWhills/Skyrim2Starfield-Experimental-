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

// The engine's own compose (Starfield 1.16.244, 0x140316a50) on the stored floats: out rows = local rows * parent rows,
// out t = local t * parent rows * parent scale + parent t, out scale = local scale * parent scale (the lane after t).
static void engine_compose(const float p[16], const float l[16], float o[16]) {
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 4; ++j)
            o[4 * i + j] = l[4 * i + 0] * p[0 + j] + l[4 * i + 1] * p[4 + j] + l[4 * i + 2] * p[8 + j];
    for (int j = 0; j < 3; ++j) o[12 + j] = (l[12] * p[j] + l[13] * p[4 + j] + l[14] * p[8 + j]) * p[15] + p[12 + j];
    o[15] = l[15] * p[15];
}

static void engine_layout() {
    const Xform parent = yaw(35, 1, 2, 3, 1.5f);
    Xform child = yaw(-80, 0.068f, -0.011f, -0.038f);
    child.r = compose(child, yaw(0, 0, 0, 0)).r;                    // a non-symmetric rotation
    float p[16], l[16], o[16];
    store_engine(parent, p);
    store_engine(child, l);
    engine_compose(p, l, o);
    CHECK(near(load_engine(o), compose(parent, child)));            // our math == the engine's on stored floats
    CHECK(near(load_engine(p), parent));                            // round trip
    CHECK(p[1] == parent.r[1][0] && p[4] == parent.r[0][1]);        // stored rows are our columns
    // the mistake of the 2026-11-23 build: rows stored as ours, untransposed, do not compose to compose()
    float wrong[16];
    store_engine(child, wrong);
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) wrong[4 * i + j] = child.r[i][j];
    engine_compose(p, wrong, o);
    CHECK(!near(load_engine(o), compose(parent, child)));
}

int main() {
    engine_layout();
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
