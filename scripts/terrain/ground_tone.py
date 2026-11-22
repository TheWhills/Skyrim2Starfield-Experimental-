"""How bright and what colour the ground is around one spot: Skyrim's look against our converted textures (read-only).

2026-11-22, after the smooth blend: the layout and fades now follow Skyrim, but side by side our Riverwood ground is
darker, browner and less green, and some textures draw near-black with black splotches. Skyrim draws a ground texture
multiplied by the LAND vertex colour (VCLR) under it; our build bakes ONE tint per texture (its mean VCLR over all of
Tamriel, --skyrim-ground-tint vertex). This prints, per Skyrim texture within --radius of the spot:

  * share   of the area's texture weight;
  * skyrim  the diffuse texture's mean colour (sRGB, averaged in linear light) and linear luminance;
  * here    Skyrim's mean vertex colour where that texture lies in this area (what Skyrim multiplies it by here);
  * baked   the Tamriel-wide mean vertex colour our build bakes in;
  * look    Skyrim's look here (diffuse x here) against ours (the staged converted colour texture), and the ratio;
then the whole area's mix both ways. Positions as for ground_at.py.

    python -I scripts\\terrain\\ground_tone.py --skyrim "<Skyrim SE>\\Data\\Skyrim.esm" ^
        --terrain C:\\Modding\\staging\\skyrim_all --pos -1848.57 913.23 --radius 20
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import landtex, skyrimground, textures  # noqa: E402
import ground_colour_test  # noqa: E402

CELL = 4096.0
STEP = CELL / 32.0
LUMA = np.array([0.2126, 0.7152, 0.0722])


def area_textures(cells, colours, xu, yu, radius_u):
    """{ltex: (weight sum, mean VCLR (r, g, b) 0..1 under it)} over the LAND vertices within radius_u of (xu, yu)
    (Skyrim units). A cell without VCLR counts as white (no tint), as in Skyrim."""
    acc, tot = {}, {}
    for cx in range(int((xu - radius_u) // CELL), int((xu + radius_u) // CELL) + 1):
        for cy in range(int((yu - radius_u) // CELL), int((yu + radius_u) // CELL) + 1):
            ws = cells.get((cx, cy))
            if not ws:
                continue
            gx = cx * CELL + np.arange(33) * STEP
            gy = cy * CELL + np.arange(33) * STEP
            inside = ((gy[:, None] - yu) ** 2 + (gx[None, :] - xu) ** 2) <= radius_u ** 2     # [row, col]
            if not inside.any():
                continue
            vc = colours.get((cx, cy))
            c = np.ones((33, 33, 3)) if vc is None else vc.astype(np.float64) / 255.0
            for fid, w in ws.items():
                wi = np.where(inside, w, 0.0)
                s = float(wi.sum())
                if s <= 0:
                    continue
                acc[fid] = acc.get(fid, 0.0) + (c * wi[..., None]).sum(axis=(0, 1))
                tot[fid] = tot.get(fid, 0.0) + s
    return {f: (tot[f], tuple(float(v) for v in acc[f] / tot[f])) for f in tot}


def mean_linear(rgba):
    """Mean linear-light RGB (0..1) of an (h, w, 4) uint8 sRGB image."""
    return textures.srgb_to_linear(rgba[..., :3].reshape(-1, 3)).mean(axis=0).astype(np.float64)


def decode(data, texconv=""):
    """(h, w, 4) uint8 of a DDS's top mip: BC1 / BC3 in Python, other formats through texconv (if given)."""
    try:
        return textures.decode_dxt(data)
    except textures.DdsError:
        if not texconv:
            return None
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "t.dds")
        with open(src, "wb") as f:
            f.write(data)
        os.makedirs(os.path.join(tmp, "o"))
        subprocess.run([texconv, "-nologo", "-y", "-f", "R8G8B8A8_UNORM", "-m", "1", "-o", os.path.join(tmp, "o"), src],
                       capture_output=True, text=True)
        out = os.path.join(tmp, "o", "t.dds")
        if not os.path.exists(out):
            return None
        raw = open(out, "rb").read()
    h = textures.read_dds_header(raw)
    return np.frombuffer(raw, np.uint8, h["width"] * h["height"] * 4, h["data_offset"]).reshape(
        h["height"], h["width"], 4)


def srgb(lin):
    return tuple(int(round(float(v))) for v in textures.linear_to_srgb(np.asarray(lin)))


def lum(lin):
    return float(np.asarray(lin) @ LUMA)


def tint_linear(diffuse_lin, tint):
    """Skyrim's diffuse x vertex colour, multiplied in sRGB (as Skyrim and the build's --skyrim-ground-tint do), from
    the diffuse's mean linear colour (exact for a uniform texture, close for ground textures)."""
    s = textures.linear_to_srgb(diffuse_lin) * np.asarray(tint)
    return textures.srgb_to_linear(np.clip(s, 0, 255)).astype(np.float64)


def report(rows):
    """Lines for rows [(edid, share, skyrim_lin|None, here, baked|None, ours_lin|None)], biggest share first."""
    out = ["share  texture                          skyrim diffuse         here VCLR          baked tint         "
           "Skyrim look here       ours                   ours/Skyrim"]
    mix_s, mix_o, ws, wo = np.zeros(3), np.zeros(3), 0.0, 0.0
    for edid, share, sk, here, baked, ours in sorted(rows, key=lambda r: -r[1]):
        def col(lin):
            return f"{str(srgb(lin)):15} {lum(lin):.3f}" if lin is not None else f"{'(not found)':21}"
        look = tint_linear(sk, here) if sk is not None else None
        tri = "({:.2f} {:.2f} {:.2f})"
        ratio = (f"{lum(ours) / lum(look):.2f}x" if look is not None and ours is not None and lum(look) > 1e-6
                 else "-")
        out.append(f"{share:5.2f}  {edid:32} {col(sk):22} {tri.format(*here):18} "
                   f"{tri.format(*baked) if baked else '-':18} {col(look):22} {col(ours):22} {ratio}")
        if look is not None:
            mix_s += share * look
            ws += share
        if ours is not None:
            mix_o += share * ours
            wo += share
    if ws > 0 and wo > 0:
        s, o = mix_s / ws, mix_o / wo
        out.append(f"area mix: Skyrim {srgb(s)} luminance {lum(s):.3f}; ours {srgb(o)} luminance {lum(o):.3f} "
                   f"({lum(o) / max(lum(s), 1e-6):.2f}x); green share Skyrim {s[1] / max(s.sum(), 1e-6):.2f}, "
                   f"ours {o[1] / max(o.sum(), 1e-6):.2f}")
    out.append("(colours: sRGB 0..255 of the mean in linear light, then linear luminance; Starfield's vanilla dirt "
               "DirtFootprints01 averages (144, 109, 90), luminance about 0.17)")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm (its folder's archives give the diffuse textures)")
    ap.add_argument("--terrain", required=True, help="the staged exterior (e.g. C:\\Modding\\staging\\skyrim_all)")
    ap.add_argument("--pos", type=float, nargs=2, required=True, metavar=("X", "Y"), help="player.getpos x / y")
    ap.add_argument("--spawn-at", type=float, nargs=2, metavar=("X", "Y"), help="as ground_at.py")
    ap.add_argument("--radius", type=float, default=20.0, help="metres around the spot (default 20)")
    ap.add_argument("--texconv", default="", help="texconv.exe, only for textures that are not BC1 / BC3")
    a = ap.parse_args(argv)
    with open(os.path.join(a.terrain, "overlays_params.json"), encoding="utf-8") as f:
        ov = json.load(f)["overlays"][0]
    if a.spawn_at:
        sx, sy = ov["spawn"][:2]
        a.pos = [a.pos[0] - a.spawn_at[0] + sx, a.pos[1] - a.spawn_at[1] + sy]
    ox, oy = (float(v) for v in ov.get("origin_cw_m", [0, 0]))
    xu, yu = (a.pos[0] + ox) * 70.0, (a.pos[1] + oy) * 70.0
    colours = {}
    cells, ltex = landtex.read_world_textures(a.skyrim, colours=colours)
    near = area_textures(cells, colours, xu, yu, a.radius * 70.0)
    if not near:
        sys.exit(f"no Skyrim LAND textures within {a.radius:g} m of ({a.pos[0]:g}, {a.pos[1]:g})")
    baked = skyrimground.vertex_tints(cells, colours)
    from fo4sf import bsa
    src = bsa.SkyrimArchives(os.path.dirname(os.path.abspath(a.skyrim)))
    total = sum(w for w, _c in near.values())
    rows = []
    for fid, (w, here) in near.items():
        info = ltex.get(fid, {})
        edid = info.get("edid", "(engine default)" if fid == 0 else f"{fid:08X}")
        sk = ours = None
        data = src.texture(skyrimground.texture_path(info.get("diffuse", ""))) if info.get("diffuse") else None
        img = decode(data, a.texconv) if data else None
        if img is not None:
            sk = mean_linear(img)
        p = ground_colour_test.colour_path(a.terrain, edid)
        if os.path.exists(p):
            img = decode(open(p, "rb").read(), a.texconv)
            if img is not None:
                ours = mean_linear(img)
        rows.append((edid, w / total, sk, here, baked.get(fid), ours))
    print(f"ground within {a.radius:g} m of ({a.pos[0]:g}, {a.pos[1]:g}) m = Skyrim ({xu:.0f}, {yu:.0f}) units:")
    for line in report(rows):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
