r"""Rebuild the staged Skyrim ground textures' height maps without rebuilding the terrain (2026-11-25).

Starfield's terrain shader shifts the colour by the height map (parallax), so a height map must be the texture's real
shape. Ours were guessed from colour brightness (skyrimground.height_from_diffuse): dark specks and leaves were pushed
down and the texture smeared (owner's side-by-sides: crisp on the road objects, smeared on the ground). Now each map is
the integral of the texture's own normal map (skyrimground.height_from_normal; the method reproduces vanilla's own
height maps from their normal maps, correlation 0.63 .. 0.99).

--source normal (default): from the staged converted normal map <stem>_normal.dds (what the game draws with);
--source diffuse: the earlier brightness maps, from the LTEX's Skyrim diffuse (to compare).
Every <staging>\Data\textures\skyrim\ground\<stem>_height.dds is replaced (removed first: staging files may be hard
links into the build folder). Reinstall the exterior afterwards (tools/owner/ground_heights.ps1 does it).

    python -I scripts\terrain\ground_heights.py --skyrim <Skyrim.esm> --staging C:\Modding\staging\skyrim_all --texconv <texconv.exe>
"""
import argparse
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import bsa, landtex, skyrimground, textures  # noqa: E402


def stem_of(edid: str) -> str:
    """make_skyrim_overlay.py's ground stem for an LTEX EditorID."""
    return re.sub(r"[^a-z0-9]+", "_", edid.lower()).strip("_")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm (its folder holds the archives)")
    ap.add_argument("--staging", required=True)
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--source", choices=("normal", "diffuse"), default="normal")
    a = ap.parse_args(argv)
    ground = os.path.join(a.staging, "Data", "textures", "skyrim", "ground")
    diffuse, src = {}, None
    if a.source == "diffuse":
        for path in landtex.official_plugins(a.skyrim):   # later plugins win, but only with a texture set they hold
            with landtex.fo4land.Plugin(path) as p:       # (Update.esm's LTEX overrides name Skyrim.esm's TXSTs)
                for v in landtex.read_ltex(p).values():
                    if v["edid"] and v["diffuse"]:
                        diffuse[stem_of(v["edid"])] = v["diffuse"]
        src = bsa.SkyrimArchives(os.path.dirname(os.path.abspath(a.skyrim)))
    done, missing = [], []
    for fn in sorted(os.listdir(ground)):
        if not fn.endswith("_height.dds") or fn.startswith("_"):
            continue
        stem = fn[:-len("_height.dds")]
        if a.source == "normal":
            p = os.path.join(ground, stem + "_normal.dds")
            d = open(p, "rb").read() if os.path.isfile(p) else None
        else:
            d = src.texture(skyrimground.texture_path(diffuse[stem])) if stem in diffuse else None
        if d is None:
            missing.append(stem)
            continue
        dst = os.path.join(ground, fn)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, fn)
            if a.source == "normal":
                skyrimground.height_from_normal(d, a.texconv, out)
            else:
                skyrimground.height_from_diffuse(d, a.texconv, out)
            data = open(out, "rb").read()
        os.remove(dst)
        with open(dst, "wb") as f:
            f.write(data)
        h = textures.read_dds_header(data)
        done.append(f"{stem} {h['width']}")
    print(f"{len(done)} height maps rebuilt from the {a.source} maps ({', '.join(done[:4])}"
          f"{' ...' if len(done) > 4 else ''})" + (f"; no {a.source} map for {missing}" if missing else ""))
    return 1 if missing and not done else 0


if __name__ == "__main__":
    sys.exit(main())
