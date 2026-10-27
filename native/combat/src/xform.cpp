#include "s2s/xform.h"

namespace s2s::combat {

Xform compose(const Xform& a, const Xform& b) {
    Xform o;
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) o.r[i][j] = a.r[i][0] * b.r[0][j] + a.r[i][1] * b.r[1][j] + a.r[i][2] * b.r[2][j];
    for (int i = 0; i < 3; ++i)
        o.t[i] = a.t[i] + a.s * (a.r[i][0] * b.t[0] + a.r[i][1] * b.t[1] + a.r[i][2] * b.t[2]);
    o.s = a.s * b.s;
    return o;
}

Xform inverse(const Xform& a) {
    Xform o;
    const float s = a.s == 0.0f ? 1.0f : a.s;
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) o.r[i][j] = a.r[j][i];
    for (int i = 0; i < 3; ++i)
        o.t[i] = -(o.r[i][0] * a.t[0] + o.r[i][1] * a.t[1] + o.r[i][2] * a.t[2]) / s;
    o.s = 1.0f / s;
    return o;
}

}  // namespace s2s::combat
