"""Build the three test BTDs for terrain experiment 1 (docs/terrain/architecture.md, section 5).

    python scripts/terrain/make_exp1_btd.py <Starfield Data dir> <staging dir>

Writes <staging>/Data/Terrain/FO4TX_World01.btd, FO4TX_Shared02.btd, FO4TX_World03.btd (5 x 5 cells, 640 x 640 samples,
height range -500..1000 m like most vanilla BTDs) and <staging>/expected.json. Land textures (LTEX table, quadrant map,
weights of the first cell) are copied from vanilla terrain/landingoverlay01.btd so only the heights are ours.

Heights, in world metres, assuming BTD cell i = world cell i - 2 and rows south to north (supported, not verified in game):
    everywhere           10.0
    pad A  x 20..40,  y 20..40     10 + D        (D = 25 / 35 / 45 for World01 / World02 / World03: tells which file loaded)
    pad B  x 60..80,  y 20..40     10 + D / 2
    pit C  x 20..40,  y 60..80      5.0
Game data never enters the repo: the output goes to the staging folder.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from fo4sf import ba2, btd  # noqa: E402

N = 5                       # cells per side
STEP = 100.0 / 128          # metres per sample
ORIGIN = -(N // 2) * 100.0  # world x/y of the BTD's SW corner
HMIN, HMAX = -500.0, 1000.0
PADS = {"FO4TX_World01.btd": 25.0, "FO4TX_Shared02.btd": 35.0, "FO4TX_World03.btd": 45.0}


def heights(d):
    idx = np.arange(N * 128)
    x = ORIGIN + idx * STEP                     # sample positions (cell corners)
    X, Y = np.meshgrid(x, x)                    # Y[row] = south -> north
    h = np.full(X.shape, 10.0)
    h[(X >= 20) & (X <= 40) & (Y >= 20) & (Y <= 40)] = 10.0 + d
    h[(X >= 60) & (X <= 80) & (Y >= 20) & (Y <= 40)] = 10.0 + d / 2
    h[(X >= 20) & (X <= 40) & (Y >= 60) & (Y <= 80)] = 5.0
    return h


def main(data_dir, staging):
    ref = btd.read(ba2.Ba2(os.path.join(data_dir, "Starfield - Terrain01.ba2")).read("terrain/landingoverlay01.btd"))
    quad = np.tile(ref.quad_map[0:1, 0:1, :], (N * 2, N * 2, 1))
    weights = np.tile(ref.weights[:128, :128], (N, N))
    out = os.path.join(staging, "Data", "Terrain")
    os.makedirs(out, exist_ok=True)
    expected = {}
    for name, d in PADS.items():
        h = heights(d)
        t = btd.Btd(6, HMIN, HMAX, list(ref.ltex), btd.quantize(h, HMIN, HMAX), weights, quad)
        data = btd.write(t)
        back = btd.read(data)
        assert np.abs(back.heights_m() - h).max() < (HMAX - HMIN) / 65535
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)
        expected[name] = {"ground": 10.0, "padA_x20-40_y20-40": 10.0 + d, "padB_x60-80_y20-40": 10.0 + d / 2,
                          "pitC_x20-40_y60-80": 5.0, "bytes": len(data)}
        print(f"{name}: {len(data):,} bytes, pad A {10 + d} m")
    with open(os.path.join(staging, "expected.json"), "w") as f:
        json.dump(expected, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
