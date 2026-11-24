// Node transforms as the game composes them (CommonLibSF NiTransform: world = parent * local, i.e. R = Rp * Rl,
// t = tp + sp * Rp * tl, s = sp * sl). Used to put the pair weapon's left blade node onto the left hand bone:
// local = inverse(parent world) * bone world.
#pragma once

#include <array>

namespace s2s::combat {

struct Xform {
    std::array<std::array<float, 3>, 3> r{{{1, 0, 0}, {0, 1, 0}, {0, 0, 1}}};   // rows
    std::array<float, 3> t{0, 0, 0};
    float s = 1.0f;
};

Xform compose(const Xform& a, const Xform& b);     // a * b

// Starfield's NiTransform in memory (Starfield 1.16.244, 0x140316a50, the world update of NiAVObject slot 79): three
// 16-byte rows, translation at float 12, scale at float 15. The engine composes in the row-vector convention: child
// rows = local rows * parent rows, translation = local t * parent rows * parent scale + parent t. So a stored row i is
// the image of axis i, i.e. the stored matrix is the transpose of our column-vector r. Owner's run 2026-11-23: the
// left copy's grip rotation written untransposed came out wrong and the copy's world never matched compose().
void store_engine(const Xform& x, float out[16]);
Xform load_engine(const float in[16]);
Xform inverse(const Xform& a);                     // scale 0 is taken as 1
// the local transform that puts a child of `parent_world` at `target_world`
inline Xform local_for(const Xform& parent_world, const Xform& target_world) {
    return compose(inverse(parent_world), target_world);
}

}  // namespace s2s::combat
