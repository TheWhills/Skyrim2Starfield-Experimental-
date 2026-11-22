"""Paint converted Skyrim ground textures in the staged exterior a solid colour, and put them back (2026-11-22).

    python -I scripts\\terrain\\ground_colour_test.py paint --staging C:\\Modding\\staging\\skyrim_all --colours LRocks01NoRocks=magenta,LRocks01=cyan
    python -I scripts\\terrain\\ground_colour_test.py label --staging C:\\Modding\\staging\\skyrim_all
    python -I scripts\\terrain\\ground_colour_test.py restore --staging C:\\Modding\\staging\\skyrim_all

label (2026-11-22): every converted ground texture shows its own Skyrim name in black letters on a pale colour, so any
patch in game says which texture the terrain draws there (the colour paint showed 3 of 8 textures, and no loose file
or archive problem explains the other 5).

Why: at the owner's grey band (Skyrim paints LRocks01NoRocks there at 100 %) the game shows a pale, smooth, blue-grey
ground, while our converted texture (textures\\skyrim\\ground\\lrocks01norocks_color.dds) is dark, detailed gravel. If the
band turns the painted colour, the game draws our texture there (the problem is how it looks); if it stays pale, the
game draws something else for that LTEX slot (its vanilla record's material, as seen far away in October).
paint keeps the originals in <staging>\\ground_colour_backup the first time; restore puts them back. Reinstall the
staging after either (tools\\owner\\terrain_colour_test.ps1 does both).
"""
import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import skyrimground  # noqa: E402

BACKUP = "ground_colour_backup"
GROUND = ("Data", "textures", "skyrim", "ground")


def colour_path(staging, edid):
    """The staged colour texture of a converted Skyrim ground texture (make_skyrim_overlay.py: stem ground/<edid>)."""
    stem = re.sub(r"[^a-z0-9]+", "_", edid.lower()).strip("_")
    return os.path.join(staging, *GROUND, f"{stem}_color.dds")


# 5 x 7 bitmap glyphs (rows top to bottom, 5 bits each, MSB left) for the labels: A-Z, 0-9 and '_'
GLYPHS = {
    "A": (14, 17, 17, 31, 17, 17, 17), "B": (30, 17, 17, 30, 17, 17, 30), "C": (14, 17, 16, 16, 16, 17, 14),
    "D": (30, 17, 17, 17, 17, 17, 30), "E": (31, 16, 16, 30, 16, 16, 31), "F": (31, 16, 16, 30, 16, 16, 16),
    "G": (14, 17, 16, 23, 17, 17, 15), "H": (17, 17, 17, 31, 17, 17, 17), "I": (14, 4, 4, 4, 4, 4, 14),
    "J": (7, 2, 2, 2, 2, 18, 12), "K": (17, 18, 20, 24, 20, 18, 17), "L": (16, 16, 16, 16, 16, 16, 31),
    "M": (17, 27, 21, 21, 17, 17, 17), "N": (17, 17, 25, 21, 19, 17, 17), "O": (14, 17, 17, 17, 17, 17, 14),
    "P": (30, 17, 17, 30, 16, 16, 16), "Q": (14, 17, 17, 17, 21, 18, 13), "R": (30, 17, 17, 30, 20, 18, 17),
    "S": (15, 16, 16, 14, 1, 1, 30), "T": (31, 4, 4, 4, 4, 4, 4), "U": (17, 17, 17, 17, 17, 17, 14),
    "V": (17, 17, 17, 17, 17, 10, 4), "W": (17, 17, 17, 21, 21, 21, 10), "X": (17, 17, 10, 4, 10, 17, 17),
    "Y": (17, 17, 10, 4, 4, 4, 4), "Z": (31, 1, 2, 4, 8, 16, 31), "0": (14, 17, 19, 21, 25, 17, 14),
    "1": (4, 12, 4, 4, 4, 4, 14), "2": (14, 17, 1, 2, 4, 8, 31), "3": (31, 2, 4, 2, 1, 17, 14),
    "4": (2, 6, 10, 18, 31, 2, 2), "5": (31, 16, 30, 1, 1, 17, 14), "6": (6, 8, 16, 30, 17, 17, 14),
    "7": (31, 1, 2, 4, 8, 8, 8), "8": (14, 17, 17, 14, 17, 17, 14), "9": (14, 17, 17, 15, 1, 2, 12),
    "_": (0, 0, 0, 0, 0, 0, 31)}


def label_pixels(text, size=256, scale=2):
    """RGBA [size, size, 4]: a pale background of a colour picked from the text, the text in black twice (rows at a
    quarter and three quarters), so a ground patch in game says which texture it is."""
    import zlib
    import numpy as np
    h = zlib.crc32(text.encode())
    bg = np.array([150 + (h & 0x3F), 150 + ((h >> 6) & 0x3F), 150 + ((h >> 12) & 0x3F)], np.uint8)
    px = np.zeros((size, size, 4), np.uint8)
    px[..., :3] = bg
    px[..., 3] = 255
    chars = [c for c in text.upper() if c in GLYPHS][: size // (6 * scale)]
    width = len(chars) * 6 * scale
    x0 = max(0, (size - width) // 2)
    for y0 in (size // 4 - 7 * scale // 2, 3 * size // 4 - 7 * scale // 2):
        for k, c in enumerate(chars):
            for r, bits in enumerate(GLYPHS[c]):
                for col in range(5):
                    if bits >> (4 - col) & 1:
                        y, x = y0 + r * scale, x0 + (k * 6 + col) * scale
                        px[y:y + scale, x:x + scale, :3] = 0
    return px


def label_dds(text, size=256):
    import tempfile
    from fo4sf import textures
    px = label_pixels(text, size)
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "l.dds")
        textures.write_dds_dx10(p, size, size, textures.DXGI_R8G8B8A8_UNORM, px.tobytes(), 4)
        with open(p, "rb") as fh:
            return fh.read()


def cmd_label(a):
    """Every converted ground colour texture of the staging becomes a label with its own name."""
    gdir = os.path.join(a.staging, *GROUND)
    names = sorted(f for f in os.listdir(gdir) if f.lower().endswith("_color.dds")) if os.path.isdir(gdir) else []
    for f in names:
        p = os.path.join(gdir, f)
        keep = os.path.join(a.staging, BACKUP, f)
        if not os.path.exists(keep):
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            shutil.copy2(p, keep)
        with open(p, "wb") as fh:
            fh.write(label_dds(f[:-len("_color.dds")]))
    print(f"labelled {len(names)} ground texture(s) with their names; originals in {os.path.join(a.staging, BACKUP)}")
    return 0 if names else 1


def cmd_paint(a):
    cols = skyrimground.parse_colours(a.colours)
    if not cols:
        sys.exit("--colours: nothing to paint (e.g. LRocks01NoRocks=magenta)")
    done = 0
    for edid, rgb in cols.items():
        p = colour_path(a.staging, edid)
        if not os.path.exists(p):
            print(f"  {edid}: no {p} (not a converted ground texture of this staging?)")
            continue
        keep = os.path.join(a.staging, BACKUP, os.path.basename(p))
        if not os.path.exists(keep):
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            shutil.copy2(p, keep)
        with open(p, "wb") as fh:
            fh.write(skyrimground.colour_dds(rgb))
        done += 1
        print(f"  {edid}: painted {rgb} -> {os.path.relpath(p, a.staging)}")
    print(f"painted {done} ground texture(s); originals in {os.path.join(a.staging, BACKUP)}")
    return 0 if done else 1


def cmd_restore(a):
    keep_dir = os.path.join(a.staging, BACKUP)
    if not os.path.isdir(keep_dir):
        print("nothing to restore (no backup)")
        return 0
    n = 0
    for f in sorted(os.listdir(keep_dir)):
        shutil.copy2(os.path.join(keep_dir, f), os.path.join(a.staging, *GROUND, f))
        n += 1
    shutil.rmtree(keep_dir)
    print(f"restored {n} ground texture(s)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("paint", "label", "restore"))
    ap.add_argument("--staging", required=True)
    ap.add_argument("--colours", default="", help="paint: Skyrim LTEX EditorID=colour, comma separated "
                                                  f"({', '.join(sorted(skyrimground.TEST_COLOURS))})")
    a = ap.parse_args(argv)
    return {"paint": cmd_paint, "label": cmd_label, "restore": cmd_restore}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
