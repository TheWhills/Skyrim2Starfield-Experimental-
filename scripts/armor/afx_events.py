"""Which events Starfield's animation descriptors (.afx) carry, sounds above all (read-only).

2026-11-16, owner, the forge working in game: "it doesn't have the sounds, is it possible to add those?". Skyrim's forge
plays its sounds from the behaviour's clip triggers (smithing_probe: SoundPlay.NPCHumanBlacksmithHammer on each blow,
SoundPlay.NPCHumanBlacksmithForgeQuench at the trough, SoundPlay.OBJBlacksmithForge during the pull ...); our clips
carry none. Starfield plays sounds from descriptor events too, but which event name and payload (a sound record?
a Wwise event?) has to be read from its own descriptors before ours can carry any. This prints:
  1. every event of the descriptors in --folder (repeatable): file, frame, name, payload;
  2. over every .afx in the archives: each event name with its count; for names that look like sounds, the distinct
     payloads matching --match (hammer, metal, steam, water ...) with a file that uses each.

    python -I scripts\\armor\\afx_events.py --starfield "<Starfield>" --folder repair_tool_hammerstanding
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

ANIM = "meshes\\actors\\human\\animations\\"
EVENT_RE = re.compile(r"<event>\s*<frame>\s*(-?\d+)\s*</frame>\s*<name>\s*([^<]*?)\s*</name>\s*"
                      r"(?:<payload>\s*([^<]*?)\s*</payload>)?", re.S)
SOUNDISH = re.compile(r"sound|audio|wwise|sfx|foley", re.I)
MATCH = r"hammer|anvil|metal|clang|steam|hiss|water|splash|fire|quench|forge|grind|sharpen|wheel|tool|repair|weld"


def events(afx_text: str) -> list:
    """[(frame, name, payload)] of a descriptor."""
    return [(int(f), n, p or "") for f, n, p in EVENT_RE.findall(afx_text)]


def summarize(files: dict, match=MATCH) -> tuple:
    """(Counter of event names, {name: {payload: first file}}) over {file: afx text}, payloads kept for sound-like
    names when they match `match`."""
    rx = re.compile(match, re.I)
    names, payloads = Counter(), defaultdict(dict)
    for fn, text in files.items():
        for _f, n, p in events(text):
            names[n] += 1
            if SOUNDISH.search(n) and p and rx.search(p):
                payloads[n].setdefault(p, fn)
    return names, payloads


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--folder", action="append", default=[], help="a folder under animations\\furniture\\ (repeatable)")
    ap.add_argument("--match", default=MATCH)
    ap.add_argument("--max-payloads", type=int, default=60)
    a = ap.parse_args(argv)
    import furniture_anim_survey as S
    arcs = S.SfArchives(os.path.join(a.starfield, "Data"))
    afx = [n for n in arcs.names if n.endswith(".afx")]
    for folder in a.folder:
        pre = (ANIM + "furniture\\" + folder.strip("\\").lower() + "\\")
        print(f"== 1. {pre}")
        for n in [x for x in afx if x.startswith(pre) and "\\" not in x[len(pre):]]:
            data = arcs.read(n)
            evs = events(data.decode("utf-8", "replace")) if data else []
            print(f"  {n[len(pre):]}: " + (", ".join(f"{f} {nm}{' ' + p if p else ''}" for f, nm, p in evs) or "-"))
    files = {}
    for n in afx:
        data = arcs.read(n)
        if data:
            files[n] = data.decode("utf-8", "replace")
    names, payloads = summarize(files, a.match)
    print(f"== 2. {len(files)} descriptors; event names (count)")
    print("  " + ", ".join(f"{n} {c}" for n, c in names.most_common(80)))
    for n, ps in sorted(payloads.items()):
        print(f"-- {n}: {len(ps)} payloads matching")
        for p, fn in sorted(ps.items())[:a.max_payloads]:
            print(f"  {p}   ({fn})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
