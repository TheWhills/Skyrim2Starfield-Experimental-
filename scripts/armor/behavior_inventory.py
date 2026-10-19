"""Inventory Skyrim behaviour graphs (.hkx hkbBehaviorGraph / hkbCharacter / hkbProject files), read-only: per creature
folder, how many states / clips / blends / state machines, the animation files the clips play, the events and
variables the graphs use, and Bethesda's own generator classes (BS*). This is the map of what each Skyrim creature's
behaviour needs on the Starfield side (docs/armor/animation-port.md "Creatures", "patcher").

    python -I scripts\\armor\\behavior_inventory.py --dir "<Skyrim Data or extracted meshes>" --out C:\\Modding\\work\\behaviors

Field-offset independent: strings are found through the pointer fixups that start inside each object (so it also
reads Pandora's template copies, whose objects carry 8 extra leading bytes). Which string is which field is told by
its shape (an animation path ends in .hkx), not by offset. Supported hypothesis: event / variable names are the
strings of hkbBehaviorGraphStringData; clip names and animation paths those of hkbClipGenerator.
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

from fo4sf import hkpackfile  # noqa: E402


def object_strings(pf):
    """[(offset, class, [strings])] for every object: the 0-terminated strings its pointers (inside its byte range)
    lead to, directly or through one array of char* (string arrays)."""
    s = pf.data_section
    objs = sorted(pf.objects())
    ends = [o for o, _ in objs[1:]] + [s.end]
    ptrs = sorted(s.local.items())
    data, base = pf.data, s.start

    def cstr(t):
        a = base + t
        e = data.find(b"\0", a, min(a + 512, base + s.end))
        if e <= a:
            return None
        b = data[a:e]
        return b.decode("latin-1") if all(32 <= c < 127 for c in b) else None
    out = []
    import bisect
    for (o, c), end in zip(objs, ends):
        i = bisect.bisect_left(ptrs, (o, -1))
        strs, seen = [], set()                               # pointer slots already read through an array
        while i < len(ptrs) and ptrs[i][0] < end:
            if ptrs[i][0] in seen:                           # Havok writes an object's arrays right after it
                i += 1
                continue
            t = ptrs[i][1]
            v = cstr(t)
            if v is not None and len(v) >= 1:
                strs.append(v)
            else:                                            # an array of char*: follow its element pointers
                j = bisect.bisect_left(ptrs, (t, -1))
                k = 0
                while j < len(ptrs) and ptrs[j][0] == t + pf.ptr_size * k and k < 4096:
                    w = cstr(ptrs[j][1])
                    if w is None:
                        break
                    strs.append(w)
                    seen.add(ptrs[j][0])
                    j += 1
                    k += 1
            i += 1
        out.append((o, c, strs))
    return out


def inventory(files):
    per = collections.defaultdict(lambda: {"files": 0, "classes": collections.Counter(), "animations": set(),
                                           "events": set(), "variables": set(), "failed": 0})
    for rel, data in files:
        parts = rel.replace("\\", "/").lower().split("/")
        key = "/".join(parts[parts.index("actors") + 1:parts.index("actors") + 2]) if "actors" in parts else parts[0]
        e = per[key]
        e["files"] += 1
        try:
            pf = hkpackfile.Packfile(data)
        except Exception:                                   # noqa: BLE001
            e["failed"] += 1
            continue
        for _o, c, strs in object_strings(pf):
            e["classes"][c] += 1
            if c == "hkbClipGenerator" or c == "BSSynchronizedClipGenerator":
                e["animations"].update(x.replace("\\", "/").lower() for x in strs if x.lower().endswith(".hkx"))
            elif c == "hkbBehaviorGraphStringData":
                # eventNames, attributeNames, variableNames, characterPropertyNames (in that order in Havok 2010)
                e["events"].update(strs)
            elif c in ("hkbCharacterStringData",):
                e["animations"].update(x.replace("\\", "/").lower() for x in strs if x.lower().endswith(".hkx"))
    out = {}
    for k, e in sorted(per.items()):
        cl = e["classes"]
        out[k] = {"files": e["files"], "failed": e["failed"],
                  "state_machines": cl["hkbStateMachine"], "states": cl["hkbStateMachineStateInfo"],
                  "clips": cl["hkbClipGenerator"], "synchronized_clips": cl["BSSynchronizedClipGenerator"],
                  "blends": cl["hkbBlenderGenerator"], "behavior_graphs": cl["hkbBehaviorGraph"],
                  "bethesda_classes": dict(sorted((c, n) for c, n in cl.items() if c.startswith("BS"))),
                  "animation_files": len(e["animations"]), "animation_examples": sorted(e["animations"])[:12],
                  "graph_strings": len(e["events"]), "graph_string_examples": sorted(e["events"])[:40]}
    return out


def gather(root):
    for d, _dirs, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(".hkx"):
                p = os.path.join(d, fn)
                with open(p, "rb") as fh:
                    yield os.path.relpath(p, root), fh.read()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="a folder holding behaviors (e.g. extracted meshes\\actors)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    inv = inventory(gather(a.dir))
    with open(os.path.join(a.out, "behaviors.json"), "w", encoding="utf-8") as fh:
        json.dump(inv, fh, indent=1)
    lines = [f"{'creature':24} {'graphs':>6} {'SMs':>5} {'states':>6} {'clips':>6} {'sync':>5} {'blends':>6} {'anims':>6}"]
    for k, v in inv.items():
        lines.append(f"{k:24} {v['behavior_graphs']:6} {v['state_machines']:5} {v['states']:6} {v['clips']:6} "
                     f"{v['synchronized_clips']:5} {v['blends']:6} {v['animation_files']:6}")
    text = "\n".join(lines)
    with open(os.path.join(a.out, "behaviors.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
