"""Does Starfield ship pre-built per-NPC face data? (2026-11-06: our test NPCs' faces stay light while their dark
templates' faces match the body, even a copy that keeps the template's whole face record; hypothesis: vanilla NPCs
have baked face files named by FormID, as Skyrim's FaceGen, and ours have none.) Read-only.

Lists, over every .ba2 in Data: entries whose path holds one of the given FormIDs (8 or 6 hex digits), and how many
entries sit under face-like folders (facegen, facecustomization, facemeshes, facetint ...) with examples. Writes
--out\\facegen_probe.json.

    python -I scripts\\npc\\facegen_probe.py --starfield "D:\\...\\Starfield" --form-id 0002F617 --out C:\\Modding\\work\\facegen_probe
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2  # noqa: E402

FACE_WORDS = re.compile(r"facegen|facecustom|facemesh|facetint|faceparts|headgen|facedata", re.I)


def scan(names_by_archive, form_ids, examples: int = 15) -> dict:
    """names_by_archive {archive: [entry names]} -> report."""
    keys = {}
    for f in form_ids:
        v = int(f, 16) & 0xFFFFFF
        keys[f] = re.compile(rf"(?<![0-9a-f])(00)?{v:06x}(?![0-9a-f])", re.I)
    hits = {f: [] for f in form_ids}
    folders, samples = collections.Counter(), collections.defaultdict(list)
    for arc, names in names_by_archive.items():
        for n in names:
            low = n.replace("\\", "/").lower()
            for f, rx in keys.items():
                if rx.search(os.path.basename(low)) or rx.search(low):
                    hits[f].append(f"{arc}: {n}")
            if FACE_WORDS.search(low):
                folder = "/".join(low.split("/")[:4])
                folders[folder] += 1
                if len(samples[folder]) < examples:
                    samples[folder].append(f"{arc}: {n}")
    return {"form_id_hits": {f: h[:50] for f, h in hits.items()},
            "face_folders": folders.most_common(40), "face_examples": dict(samples)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--form-id", action="append", default=[], help="a vanilla NPC FormID (hex), repeatable")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    data = os.path.join(a.starfield, "Data")
    names = {}
    for fn in sorted(os.listdir(data)):
        if fn.lower().endswith(".ba2"):
            try:
                names[fn] = ba2.Ba2(os.path.join(data, fn)).names
            except Exception as e:                          # noqa: BLE001 (report only)
                names[fn] = []
                print(f"{fn}: not read ({e})")
    rep = scan(names, a.form_id)
    rep["archives"] = {k: len(v) for k, v in names.items()}
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "facegen_probe.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    for f, h in rep["form_id_hits"].items():
        print(f"{f}: {len(h)} archive entries", *h[:8], sep="\n  ")
    print("face-like folders:", rep["face_folders"][:12])
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
