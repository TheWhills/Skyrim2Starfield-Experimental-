"""Skyrim's flame textures and our palette bakes as one contact sheet (read-only), to fix the converted flames by eye.

2026-11-15, owner's first in-game look at flames v1 (skyrimfire): candle flames white, very bright, static; the hearth
flames faint and blue. Both depend on what the textures hold (is the atlas grey in RGB or only in alpha? which palette
row is orange? is CandleFlame01 coloured or white with the colour from the shader?), which the cloud workspace cannot
see. This writes flame_textures.png (rows below, each panel 192 px high, black background) and prints channel stats and
the effect shaders' emissive colours:
  row 1: FXFireAtlas04 RGB | alpha | bakes over black: u = green with palette row 0 / 0.5 / 1, u = alpha row 0 / 0.5 / 1
  row 2: GradFireExplosion RGB | alpha (the palette, stretched)
  row 3: CandleFlame01 RGB | alpha | CandleGlow01 RGB | alpha | FXFireAtlas02 RGB | alpha | WoodFires01_g RGB | alpha

    python -I scripts\\interior\\flame_textures.py --skyrim-data "<Skyrim SE>\\Data" --out <folder>
"""
import argparse
import os
import struct
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import bsa, nif as nifmod, skyrimfire, textures  # noqa: E402

ATLAS = "textures\\effects\\fxfireatlas04.dds"
PALETTE = "textures\\effects\\gradients\\gradfireexplosion.dds"
OTHERS = ["textures\\effects\\candleflame01.dds", "textures\\effects\\candleglow01.dds",
          "textures\\effects\\fxfireatlas02.dds", "textures\\clutter\\woodfires\\woodfires01_g.dds"]
MODELS = ["meshes\\clutter\\woodfires\\fireplacewood01burning.nif", "meshes\\mps\\mpscandleflame01.nif"]
PANEL = 192


def write_png(path, rgb):
    h, w = rgb.shape[:2]
    raw = b"".join(b"\x00" + rgb[y].astype(np.uint8).tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def fit(img, height=PANEL, width=None):
    """Nearest-neighbour resize of an (h, w, 3) image to `height` rows (width keeps the aspect unless given)."""
    h, w = img.shape[:2]
    width = width or max(1, round(w * height / h))
    ys = np.minimum((np.arange(height) * h / height).astype(int), h - 1)
    xs = np.minimum((np.arange(width) * w / width).astype(int), w - 1)
    return img[ys][:, xs]


def over_black(rgba):
    return (rgba[:, :, :3].astype(np.float32) * (rgba[:, :, 3:4].astype(np.float32) / 255.0)).astype(np.uint8)


def grey(plane):
    return np.repeat(plane[:, :, None], 3, axis=2)


def stats(name, rgba):
    r, g, b, a = (rgba[:, :, k].astype(np.int32) for k in range(4))
    same = float(np.mean((np.abs(r - g) <= 8) & (np.abs(g - b) <= 8)))
    mean_rgb = [round(float(x.mean()), 1) for x in (r, g, b)]
    print(f"  {name}: {rgba.shape[1]}x{rgba.shape[0]} mean RGB {mean_rgb} A {round(float(a.mean()), 1)}; "
          f"RGB range {int(min(r.min(), g.min(), b.min()))}..{int(max(r.max(), g.max(), b.max()))}, "
          f"A range {int(a.min())}..{int(a.max())}; grey pixels {same:.0%}")


def palette_rows(pal):
    """The palette's colours at 5 points along u for its top, middle and bottom rows."""
    h, w = pal.shape[:2]
    for name, y in (("top", 0), ("middle", h // 2), ("bottom", h - 1)):
        pts = [pal[y, min(w - 1, int(u * (w - 1)))].tolist() for u in (0, 0.25, 0.5, 0.75, 1.0)]
        print(f"  palette {name} row (u 0, .25, .5, .75, 1): {pts}")


def row(panels, gap=4):
    h = max(p.shape[0] for p in panels)
    parts = []
    for p in panels:
        parts += [p, np.zeros((h, gap, 3), np.uint8)]
    return np.concatenate(parts[:-1], axis=1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    sky = bsa.SkyrimArchives(a.skyrim_data)
    print("== effect shaders (emissive colour, multiple, flags)")
    for m in MODELS:
        raw = sky.mesh(m)
        if raw is None:
            print(f"  {m}: not found")
            continue
        n = nifmod.parse(raw)
        for i in range(len(n.blocks)):
            if n.type_of(i) == "BSEffectShaderProperty":
                e = skyrimfire.effect_shader(n, i)
                print(f"  {m} #{i}: {e['source']} grey={e['greyscale'] or '-'} colour "
                      f"{[round(x, 3) for x in e.get('emissive_color', [])]} x{round(e.get('emissive_multiple', 0), 3)} "
                      f"flags1 {e['flags1']:08X} palette colour/alpha {e['palette_color']}/{e['palette_alpha']}")
    print("== particle systems (where they sit: the system's and its emitter object's model-space position)")
    for m in MODELS:
        raw = sky.mesh(m)
        if raw is None:
            continue
        n = nifmod.parse(raw)
        try:
            world = nifmod.world_transforms(n)
        except Exception:                                           # noqa: BLE001
            world = None

        def where(i):
            try:
                return [round(float(x), 2) for x in world(i)[0]] if world and 0 <= i < len(n.blocks) else None
            except Exception:                                       # noqa: BLE001
                return None
        for ps in skyrimfire.particle_systems(n):
            for mod in ps["modifiers"]:
                if mod.get("type") in skyrimfire.EMITTERS:
                    b = n.blocks[mod["block"]]
                    obj = struct.unpack_from("<i", b, 13 + 56)[0] if len(b) >= 73 else -1
                    print(f"  {m} {ps['name']}: system at {where(ps['block'])}, emitter object #{obj} "
                          f"({n.type_of(obj) if 0 <= obj < len(n.blocks) else '-'}) at {where(obj)}, "
                          f"volume {mod.get('volume')}")
    print("== textures")
    img = {}
    for t in [ATLAS, PALETTE] + OTHERS:
        d = sky.texture(t)
        if d is None:
            print(f"  {t}: not found")
            continue
        img[t] = textures.decode_dxt(d)
        stats(t, img[t])
    rows = []
    if ATLAS in img and PALETTE in img:
        palette_rows(img[PALETTE])
        at = img[ATLAS]
        h = PANEL * 2
        panels = [fit(at[:, :, :3], h), fit(grey(at[:, :, 3]), h)]
        for use_alpha in (False, True):
            for r in (0.0, 0.5, 1.0):
                src = at.copy()
                if use_alpha:
                    src[:, :, 1] = src[:, :, 3]
                panels.append(fit(over_black(skyrimfire.palette_bake(src, img[PALETTE], True, True, row=r)), h))
        rows.append(row(panels))
        pal = img[PALETTE]
        rows.append(row([fit(pal[:, :, :3], PANEL // 2, 768), fit(grey(pal[:, :, 3]), PANEL // 2, 768)]))
    panels = []
    for t in OTHERS:
        if t in img:
            panels += [fit(img[t][:, :, :3]), fit(grey(img[t][:, :, 3]))]
    if panels:
        rows.append(row(panels))
    if rows:
        w = max(r.shape[1] for r in rows)
        sheet = np.concatenate([np.pad(r, ((0, 8), (0, w - r.shape[1]), (0, 0)), constant_values=40) for r in rows])
        out = os.path.join(a.out, "flame_textures.png")
        write_png(out, sheet)
        print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
