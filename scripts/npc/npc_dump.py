"""Every subrecord of named NPCs, from our test plugin and from Starfield.esm side by side (2026-11-06: the test
NPCs' faces stay white and they spawn in spacesuits; compare each with the vanilla NPC it was copied from). Read-only;
writes --out\\npc_dump.json and prints the fields that differ.

    python -I scripts\\npc\\npc_dump.py --starfield "D:\\...\\Starfield" --plugin "<mod>\\S2SFaceTest.esm" --faces "<mod>\\faces.json" --out C:\\Modding\\work\\npc_dump
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import sfplugin  # noqa: E402
import npc_face_probe  # noqa: E402

SHAPE = {"FMSI", "FMRS", "FMRI", "FMRG", "BMPN", "BMPV"}      # face dials: expected to differ, summarised


def by_edid(path, names):
    want = {n.lower() for n in names}
    return {sfplugin.edid(s).lower(): s for _t, _h, s, _f in sfplugin.records(path, [b"NPC_"])
            if sfplugin.edid(s).lower() in want}


def compare(ours, theirs) -> dict:
    a, b = npc_face_probe.dump(ours), npc_face_probe.dump(theirs)
    key = lambda rows: [(r["sig"], str(r["value"])) for r in rows if r["sig"] not in SHAPE]   # noqa: E731
    ka, kb = key(a), key(b)
    return {"only_ours": [f"{s}={v}" for s, v in ka if (s, v) not in kb],
            "only_template": [f"{s}={v}" for s, v in kb if (s, v) not in ka],
            "shape_counts": {"ours": {s: sum(r["sig"] == s for r in a) for s in sorted(SHAPE)},
                             "template": {s: sum(r["sig"] == s for r in b) for s in sorted(SHAPE)}},
            "ours": a, "template": b}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--plugin", required=True)
    ap.add_argument("--faces", required=True, help="face_fit.py's faces.json (which template each NPC copied)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    with open(a.faces, encoding="utf-8") as fh:
        rows = [r for r in json.load(fh).get("npcs", []) if isinstance(r.get("test_npc"), dict)]
    ours = by_edid(a.plugin, [f"S2SFace_{r['edid']}" for r in rows])
    tpl = by_edid(os.path.join(a.starfield, "Data", "Starfield.esm"), [r["test_npc"]["template"] for r in rows])
    rep = {}
    for r in rows:
        o, t = ours.get(f"s2sface_{r['edid']}".lower()), tpl.get(r["test_npc"]["template"].lower())
        if o is None or t is None:
            rep[r["edid"]] = {"error": "record not found", "ours": o is not None, "template": t is not None}
            continue
        rep[r["edid"]] = dict(template_edid=r["test_npc"]["template"], **compare(o, t))
        print(f"== {r['edid']} vs {r['test_npc']['template']}")
        print("  only ours:    ", rep[r["edid"]]["only_ours"])
        print("  only template:", rep[r["edid"]]["only_template"])
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "npc_dump.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print("report:", os.path.join(a.out, "npc_dump.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
