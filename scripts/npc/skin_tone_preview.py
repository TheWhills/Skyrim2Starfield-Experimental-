"""Vanilla vs our skin tone textures side by side, with numbers (2026-11-11: the Orc's recoloured tones loaded in game -
hands green, the face dark and brownish; is the face texture something other than a plain colour map?). Read-only.

    python -I scripts\\npc\\skin_tone_preview.py --starfield $sf --built C:\\Modding\\work\\races\\heads --race orc --out <folder>

Per texture (male face sk0 / sk4 / sk8, female face sk4, male body sk4, male hands sk4): format, the colour of the
median pixel, the brightness spread, the alpha channel's range; skin_tone_preview.png: per row vanilla colour,
vanilla alpha, ours colour, ours alpha (256 px each); skin_tone_preview.json. The PNG holds game texture pixels:
keep it out of Git.
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))

from fo4sf import skintone, textures  # noqa: E402

FACE = "textures/actors/human/faces/chargen/{sex}_default_sk{k}_color.dds"
SAMPLES = (  # (label, vanilla, ours under textures/s2s/races/<race>/)
    ("male face sk0", FACE.format(sex="male", k=0), "face/male_sk0_color.dds"),
    ("male face sk4", FACE.format(sex="male", k=4), "face/male_sk4_color.dds"),
    ("male face sk8", FACE.format(sex="male", k=8), "face/male_sk8_color.dds"),
    ("female face sk4", FACE.format(sex="female", k=4), "face/female_sk4_color.dds"),
    ("male body sk4", "textures/actors/human/naked_body/nakedbodym_sk4_color.dds", "body/male_sk4_color.dds"),
    ("male hands sk4", "textures/actors/human/hands/defaulthandsm_sk4_color.dds", "hands/male_sk4_color.dds"))


def stats(data):
    h = textures.read_dds_header(data)
    img = skintone.decode_dds(data)
    rgb, a = img[..., :3], img[..., 3]
    lum = skintone._luma_lin(rgb)
    sel = lum > 0.002
    med = np.median(rgb[sel], axis=0) if sel.any() else np.zeros(3)
    return img, {"size": [h["width"], h["height"]], "dxgi": h["dxgi"], "mips": h["mips"],
                 "median_rgb": [int(x) for x in med],
                 "brightness_p10_p50_p90": [round(float(np.percentile(lum, q)), 4) for q in (10, 50, 90)],
                 "near_black_share": round(float((~sel).mean()), 3),
                 "alpha_min_median_max": [int(a.min()), int(np.median(a)), int(a.max())],
                 "alpha_below_250_share": round(float((a < 250).mean()), 3)}


def tile(img, size=256):
    step = max(1, img.shape[0] // size)
    t = img[::step, ::step][:size, :size]
    out = np.zeros((size, size, 3), np.uint8)
    out[:t.shape[0], :t.shape[1]] = t if t.ndim == 3 else t[..., None]
    return out


def preview(read_vanilla, read_ours, samples=SAMPLES, size=256):
    """(sheet (rows x 4 tiles RGB), report {label: {"vanilla": stats, "ours": stats}})."""
    rows, rep = [], {}
    for label, van, ours in samples:
        r, tiles = {}, []
        for key, read, path in (("vanilla", read_vanilla, van), ("ours", read_ours, ours)):
            try:
                img, r[key] = stats(read(path))
                tiles += [tile(img[..., :3], size), tile(np.repeat(img[..., 3:4], 3, -1), size)]
            except (KeyError, OSError, ValueError) as e:
                r[key] = {"error": str(e)}
                tiles += [np.zeros((size, size, 3), np.uint8)] * 2
        rep[label] = r
        rows.append(np.concatenate(tiles, 1))
    return np.concatenate(rows, 0), rep


def main(argv=None):
    import hair_probe
    import skin_tone_probe
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--built", required=True, help="race_heads' --out folder")
    ap.add_argument("--race", default="orc")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    arcs = skin_tone_probe.TextureArchives(os.path.join(a.starfield, "Data"))
    base = os.path.join(a.built, "textures", "s2s", "races", a.race.lower())

    def ours(rel):
        with open(os.path.join(base, *rel.split("/")), "rb") as fh:
            return fh.read()
    sheet, rep = preview(arcs.read, ours)
    os.makedirs(a.out, exist_ok=True)
    hair_probe.write_png(os.path.join(a.out, "skin_tone_preview.png"), sheet)
    with open(os.path.join(a.out, "skin_tone_preview.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    for label, r in rep.items():
        for key in ("vanilla", "ours"):
            print(f"{label:16} {key:7} {r[key]}")
    print(f"-> {os.path.join(a.out, 'skin_tone_preview.png')} (rows: {', '.join(s[0] for s in SAMPLES)}; columns: "
          f"vanilla colour, vanilla alpha, ours colour, ours alpha)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
