"""Starfield's animation caches (meshes\\animtextdata\\...): what the game lists for the human melee sets, read-only.

Why (docs/armor/animation-port.md): new loose clips and new tags were never found in game, while re-keyed existing
paths were. The supported hypothesis is that the caches (AnimationFileData: the resolved clip paths of one graph +
folder set; AnimationOffsets: tag -> clip, root motion, foot events) are what the engine reads, and that the Creation
Kit regenerates them. This survey records, from the installed game's archives:
  * every animtextdata file family and count
  * every AnimationFileData file that mentions the human one-handed melee folders, with its header, the number of
    paths, the folders they sit in, and whether the clips we replace are listed (meleeattack_a ... meleeblock_*)
  * copies of those files, their AnimationOffsets / AnimationStanceData / DynamicIdleData siblings (same number) and
    persistantsubgraphinfoandoffsetdata.txt into <out>\\samples, to work out the format offline

    python -I scripts\\armor\\sf_animcache_survey.py --starfield-data "<Starfield>\\Data" --out <folder>
Game files: keep the output outside the repository and do not share it publicly.
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

CACHE = re.compile(r"(^|[\\/])animtextdata[\\/]", re.I)
MELEE = re.compile(r"melee[\\/]onehanded", re.I)
OURS = ("meleeattack_a", "meleeattack_b", "meleeattack_c", "meleeattackpower_a", "meleeattacksprint",
        "meleeblock_hitreaction", "meleeblock_idle", "slidefromsprint", "sneak_meleeattack_a")


def family(name: str) -> str:
    parts = re.split(r"[\\/]", name.lower())
    i = parts.index("animtextdata") if "animtextdata" in parts else -1
    return parts[i + 1] if 0 <= i < len(parts) - 2 else (parts[-1] if i >= 0 else "?")


def set_number(name: str):
    m = re.search(r"(\d{6,})\.txt$", name, re.I)
    return m.group(1) if m else None


def describe_file_data(text: str) -> dict:
    """Header lines, path count, folders and which of our replaced clips are listed, from an AnimationFileData text."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    paths = [ln for ln in lines if re.search(r"\.(af|agx|hkx|afx)$", ln, re.I)]
    folders = collections.Counter(os.path.dirname(p.replace("\\", "/").lower()) for p in paths)
    stems = {os.path.splitext(os.path.basename(p.replace("\\", "/")))[0].lower() for p in paths}
    return {"header": lines[:4], "paths": len(paths), "folders": dict(folders.most_common(12)),
            "ours_listed": sorted(s for s in OURS if s in stems), "graphs": [p for p in paths if p.lower().endswith(".agx")][:6]}


def survey(entries, out: str, max_samples: int = 40):
    """entries: iterable of (archive name, path, reader()) for every file of the game's archives."""
    fams = collections.Counter()
    by_number = collections.defaultdict(list)
    melee_sets, other = [], []
    readers = {}
    for arc, name, read in entries:
        if not CACHE.search(name):
            continue
        fams[family(name)] += 1
        readers[name] = read
        num = set_number(name)
        if num:
            by_number[num].append(name)
        if family(name) != "animationfiledata" and "persistantsubgraph" not in name.lower():
            continue
        if "persistantsubgraph" in name.lower():
            other.append(name)
            continue
        text = read().decode("utf-8", "replace")
        if MELEE.search(text):
            d = describe_file_data(text)
            d.update({"file": name, "archive": arc, "set": num})
            melee_sets.append(d)
    os.makedirs(os.path.join(out, "samples"), exist_ok=True)
    copied = []
    for d in sorted(melee_sets, key=lambda x: (-len(x["ours_listed"]), x["file"]))[:max_samples]:
        for name in by_number.get(d["set"], [d["file"]]):
            copied.append(_copy(name, readers[name], out))
    for name in other:
        copied.append(_copy(name, readers[name], out))
    rep = {"families": dict(fams), "melee_sets": melee_sets, "copied": copied}
    with open(os.path.join(out, "animcache_report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    return rep


def _copy(name, read, out):
    dst = os.path.join(out, "samples", *re.split(r"[\\/]", name))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(read())
    return name


def archive_entries(data_dir: str):
    for fn in sorted(os.listdir(data_dir), key=str.lower):
        if not fn.lower().endswith(".ba2"):
            continue
        try:
            arc = ba2.Ba2(os.path.join(data_dir, fn))
        except Exception as e:                          # noqa: BLE001 - texture archives etc. may not be readable
            print(f"skipped {fn}: {e}")
            continue
        for i, n in enumerate(arc.names):
            if CACHE.search(n):
                yield fn, n, (lambda a=arc, k=i: a.read(k))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield-data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-samples", type=int, default=40)
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    rep = survey(archive_entries(a.starfield_data), out, a.max_samples)
    print(f"families {rep['families']}; {len(rep['melee_sets'])} sets mention melee\\onehanded; "
          f"{len(rep['copied'])} files copied to {os.path.join(out, 'samples')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
