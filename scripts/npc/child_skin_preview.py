"""The children's skin colours out of the game, side by side (2026-11-19, owner: "do we have a way to look at the
color of those textures out of game" - the face read darker than the hands in game). Read-only.

    python -I scripts\\npc\\child_skin_preview.py --starfield $sf --face $face [--texconv <texconv.exe>]

Reads face_fit's faces.json in --face (the S2S Face Test mod folder): ChildRace's body and face tone textures per
slot (child_skin_tones) from the game's archives, and each child test NPC's baked face colour texture (its
test_npc.baked_face files under textures/actors/character/facecustomization/S2SFaceTest.esm). Writes
child_skin_preview.png in --face: per row a texture (192 px) with its median colour as a swatch beside it, the
child's own STON slot marked; and child_skin_preview.json with the medians. The PNG holds game texture pixels: keep
it out of Git.
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

from fo4sf import skintone  # noqa: E402

TILE = 192
FACES_DIR = ("textures", "actors", "character", "facecustomization", "S2SFaceTest.esm")


def thumb(rgba: np.ndarray, size: int = TILE) -> np.ndarray:
    """(size, size, 3) nearest-neighbour thumbnail of an RGBA image."""
    h, w = rgba.shape[:2]
    ys = (np.arange(size) * h // size).clip(0, h - 1)
    xs = (np.arange(size) * w // size).clip(0, w - 1)
    return rgba[ys][:, xs, :3]


def tile(rgba: np.ndarray, mark: bool = False) -> tuple:
    """(row image: thumbnail + median swatch, median colour)."""
    med = skintone.median_colour(rgba)
    sw = np.zeros((TILE, TILE // 2, 3), np.uint8)
    sw[:] = med
    img = np.hstack([thumb(rgba), sw])
    if mark:                                   # a white frame: this child's own slot
        img[:4], img[-4:], img[:, :4], img[:, -4:] = 255, 255, 255, 255
    return img, list(med)


def sheet(rows) -> np.ndarray:
    """rows: [[tile image, ...], ...] -> one image, rows padded to the widest."""
    width = max(sum(t.shape[1] for t in r) for r in rows)
    out = []
    for r in rows:
        line = np.hstack(r) if r else np.zeros((TILE, 0, 3), np.uint8)
        pad = np.full((TILE, width - line.shape[1], 3), 235, np.uint8)
        out.append(np.hstack([line, pad]))
    return np.vstack(out)


def decode(data: bytes, texconv: str = "") -> np.ndarray:
    try:
        return skintone.decode_dds(data)
    except Exception:                                           # noqa: BLE001 (other formats through texconv)
        import race_heads
        return race_heads.decode_any_dds(data, texconv)


def build(report: dict, read, face_dir: str, texconv: str = "") -> tuple:
    """(sheet image, {label: median}) from faces.json's report; read: game texture path -> bytes."""
    rows, meds = [], {}
    tones = report.get("child_skin_tones") or {}
    kids = [n for n in report.get("npcs", []) if n.get("child") and isinstance(n.get("test_npc"), dict)]
    own = {}
    for n in kids:
        own.setdefault("female" if n["female"] else "male", set()).add(n["test_npc"].get("ston"))
    for key in ("male", "male_face", "female", "female_face"):
        g = tones.get(key) or {}
        if not g.get("textures"):
            continue
        row = []
        for slot, path in enumerate(g["textures"]):
            try:
                img, med = tile(decode(read(path), texconv), slot in own.get(key.split("_")[0], set()))
            except (KeyError, OSError, ValueError) as e:
                meds[f"{key} slot {slot}"] = f"not read: {e}"
                continue
            row.append(img)
            meds[f"{key} slot {slot}"] = med
        rows.append(row)
    for n in kids:
        bf = n["test_npc"].get("baked_face")
        files = bf.get("files", []) if isinstance(bf, dict) else []
        color = next((f for f in files if f.lower().endswith("_color.dds")), None)
        if color is None:
            meds[f"{n['edid']} baked face"] = "none"
            continue
        p = os.path.join(face_dir, *FACES_DIR, color)
        try:
            with open(p, "rb") as fh:
                img, med = tile(decode(fh.read(), texconv))
        except (OSError, ValueError) as e:
            meds[f"{n['edid']} baked face"] = f"not read: {e}"
            continue
        rows.append([img])
        meds[f"{n['edid']} baked face"] = med
    if not rows:
        raise SystemExit("nothing to show: run face_fit with the children first")
    return sheet(rows), meds


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--face", required=True, help="face_fit's --out (S2S Face Test), with faces.json")
    ap.add_argument("--texconv", default="")
    a = ap.parse_args(argv)
    with open(os.path.join(a.face, "faces.json"), encoding="utf-8") as fh:
        report = json.load(fh)
    import skin_tone_probe
    arcs = skin_tone_probe.TextureArchives(os.path.join(a.starfield, "Data"))
    img, meds = build(report, arcs.read, a.face, a.texconv)
    import hair_probe
    png = os.path.join(a.face, "child_skin_preview.png")
    hair_probe.write_png(png, img)
    with open(os.path.join(a.face, "child_skin_preview.json"), "w", encoding="utf-8") as fh:
        json.dump(meds, fh, indent=1)
    print("rows: male body, male face, female body, female face (tone slots 0 1 2; the children's own framed), then "
          "each child's baked face")
    for k, v in meds.items():
        print(f"  {k}: {v}")
    print(f"-> {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
