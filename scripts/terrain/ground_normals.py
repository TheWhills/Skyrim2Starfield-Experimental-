r"""Ground normal map strength, without rebuilding the terrain (2026-11-25).

Owner, in game: the ground draws its bumps as dark 3D dents while the same texture (the same normal map file, byte for
byte) on the road meshes looks flat and crisp; with a flat normal map the ground's dents vanished (A/B test). So
Starfield's terrain shader shades a normal map more deeply than the object shader does. This scales the tangent x / y
of every staged ground normal map by --strength (z follows: the shader rebuilds it), always from the original maps,
kept once in <staging>\ground_normals_original (outside Data: not packed), so runs never compound; --strength 1
restores them. Reinstall afterwards (tools/owner/ground_heights.ps1 -NormalStrength runs it).

    python -I scripts\terrain\ground_normals.py --staging C:\Modding\staging\skyrim_all --texconv <texconv.exe> --strength 0.5
"""
import argparse
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import skyrimground, textures  # noqa: E402

KEEP = "ground_normals_original"


def scale_planes(x, y, strength: float):
    """Tangent x / y scaled by strength, kept inside the unit disc."""
    import numpy as np
    x, y = x * strength, y * strength
    r = np.hypot(x, y)
    k = np.where(r > 0.999, 0.999 / np.maximum(r, 1e-9), 1.0)
    return x * k, y * k


def scaled(data: bytes, strength: float, texconv: str) -> bytes:
    """A BC5 SNORM normal map with x / y scaled by strength."""
    import numpy as np
    x, y = scale_planes(*skyrimground.normal_planes(data, texconv), strength)
    to_unorm = lambda v: np.clip(np.round((v + 1.0) / 2.0 * 255.0), 0, 255).astype(np.uint8)  # noqa: E731
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "n.dds")
        textures.write_rg8_snorm(p, to_unorm(x), to_unorm(y))
        textures.texconv(texconv, p, tmp, "BC5_SNORM")
        return open(p, "rb").read()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", required=True)
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--strength", type=float, required=True, help="1 = the converted maps as they are")
    a = ap.parse_args(argv)
    ground = os.path.join(a.staging, "Data", "textures", "skyrim", "ground")
    keep = os.path.join(a.staging, KEEP)
    os.makedirs(keep, exist_ok=True)
    n = 0
    for fn in sorted(os.listdir(ground)):
        if not fn.endswith("_normal.dds"):
            continue
        src, orig = os.path.join(ground, fn), os.path.join(keep, fn)
        if not os.path.exists(orig):
            shutil.copy2(src, orig)
        data = open(orig, "rb").read()
        out = data if abs(a.strength - 1.0) < 1e-6 else scaled(data, a.strength, a.texconv)
        os.remove(src)                                   # staging files may be hard links into the build folder
        with open(src, "wb") as f:
            f.write(out)
        n += 1
    print(f"{n} ground normal maps at strength {a.strength:g} (originals in {keep})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
