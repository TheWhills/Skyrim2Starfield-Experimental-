"""Which clips the Creation Kit's animation cache resolved for a folder set (read-only): for every AnimationFileData
file that names our folder, the clip paths it resolved OUTSIDE that folder, i.e. Starfield clips still playing on our
furniture.

2026-11-15, owner, in game: seated Hilde (and the male player) still drop the arms straight down behind the hips now
and then, after every tag of chair, bench, their animflavor / female folders and furniture\\common was answered. The
furniture graph's upper-body layer (NPC_IdlePartialBody) switches clips by name (HandsBehind, ArmCrossed, DataSlate
...); the cache says what each set really resolved.

    python -I scripts\\armor\\anim_cache_clips.py --cache "<mods>\\S2S AnimInfo\\Meshes\\AnimTextData\\AnimationFileData"
        --folder s2s_sit
"""
import argparse
import os
import re
import sys
from collections import Counter

CLIP = re.compile(r"[\w\\/ .-]+\.(?:af|hkx)\b", re.I)


def outside_clips(text: str, folder: str):
    """(names our folder?, Counter of clip paths not under `folder`) for one cache file's text."""
    f = folder.lower().replace("/", "\\")
    clips = [m.group(0).strip().replace("/", "\\") for m in CLIP.finditer(text)]
    ours = any(("\\" + f + "\\") in c.lower() or c.lower().startswith(f + "\\") for c in clips)
    return ours, Counter(c for c in clips if ("\\" + f + "\\") not in c.lower() and not c.lower().startswith(f + "\\"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", required=True, help="the AnimationFileData folder")
    ap.add_argument("--folder", required=True, help="our folder's name, e.g. s2s_sit")
    a = ap.parse_args(argv)
    total, files = Counter(), 0
    for fn in sorted(os.listdir(a.cache)):
        if not fn.lower().endswith(".txt"):
            continue
        with open(os.path.join(a.cache, fn), encoding="utf-8", errors="replace") as fh:
            ours, other = outside_clips(fh.read(), a.folder)
        if ours:
            files += 1
            total.update(other)
    print(f"{files} cache files name {a.folder}; clips they resolve elsewhere ({len(total)}):")
    for clip, n in sorted(total.items(), key=lambda kv: kv[0].lower()):
        print(f"  {clip}  (in {n} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
