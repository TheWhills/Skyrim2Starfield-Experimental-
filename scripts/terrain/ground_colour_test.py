"""Paint converted Skyrim ground textures in the staged exterior a solid colour, and put them back (2026-11-22).

    python -I scripts\\terrain\\ground_colour_test.py paint --staging C:\\Modding\\staging\\skyrim_all --colours LRocks01NoRocks=magenta,LRocks01=cyan
    python -I scripts\\terrain\\ground_colour_test.py restore --staging C:\\Modding\\staging\\skyrim_all

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
    ap.add_argument("cmd", choices=("paint", "restore"))
    ap.add_argument("--staging", required=True)
    ap.add_argument("--colours", default="", help="paint: Skyrim LTEX EditorID=colour, comma separated "
                                                  f"({', '.join(sorted(skyrimground.TEST_COLOURS))})")
    a = ap.parse_args(argv)
    return cmd_paint(a) if a.cmd == "paint" else cmd_restore(a)


if __name__ == "__main__":
    sys.exit(main())
