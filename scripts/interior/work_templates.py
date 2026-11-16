"""Starfield's NPC work furniture: every FURN carrying FurnitureClassWork, with its animation keyword, flags and marker
(read-only).

2026-11-16 (owner, in game, verified by A/B): Hilde tans by herself in a build where the forge is left a static
(riverwood_doors -SkipKind forge), and did not while the forge shared the tanning rack's template (NPCStanding_WipeWall,
AnimFurnStanding_WipeWall). So each Skyrim work set wants its own Starfield template: work furniture (FurnitureClassWork,
what Alvor's sandbox picks), not IgnoredBySandbox (the standing repair hammer: packages must name it), a standing pose,
and an animation keyword no other set of ours uses. This lists the candidates grouped by animation keyword, with how
many FURN share each keyword, the record flags (IgnoredBySandbox shows on NPCRepair_ToolStanding_Hammer: compare) and
the marker model.

    python -I scripts\\interior\\work_templates.py --starfield "<Starfield>"
"""
import argparse
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

# the AnimFurn keywords our sets already sit on (stance_plugin FURNITURE_SETS)
OURS = {"AnimFurnChair", "AnimFurnBench", "AnimFurnLeaningBartopFront", "AnimFurnBartender", "AnimFurnDeskLean",
        "AnimFurnStanding_Sweep", "AnimFurnPharmaWorkbench", "AnimFurnIndustrialWorkbench", "AnimFurnGalleyWorkbench",
        "AnimFurnStanding_WipeWall"}
REFERENCE = "NPCRepair_ToolStanding_Hammer"      # IgnoredBySandbox (SfInspect, owner 2026-11-16)


def group(rows) -> dict:
    """{anim keyword: [row]} for rows (edid, fid, flags, [keyword names], marker)."""
    out = defaultdict(list)
    for r in rows:
        anim = [k for k in r[3] if k.lower().startswith("animfurn")] or ["(none)"]
        for k in anim:
            out[k].append(r)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True)
    a = ap.parse_args(argv)
    from fo4sf import fo4land, sfplugin
    esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    recs = sfplugin.records(esm, [b"FURN", b"KYWD"])
    kw = {fid & 0xFFFFFF: sfplugin.edid(s) for t, _h, s, fid in recs if t == b"KYWD"}
    rows, ref = [], None
    for t, h, s, fid in recs:
        if t != b"FURN":
            continue
        names = [kw.get(k & 0xFFFFFF, f"{k:08X}") for k in sfplugin.keywords(s)]
        flags = int.from_bytes(h[8:12], "little")
        marker = next((fo4land.zstring(d) for sg, d in s if sg == b"XMRK"), "")
        row = (sfplugin.edid(s), fid, flags, names, marker)
        if row[0] == REFERENCE:
            ref = row
        if "FurnitureClassWork" in names:
            rows.append(row)
    if ref:
        print(f"reference (IgnoredBySandbox): {ref[0]} {ref[1]:08X} flags 0x{ref[2]:08X} {', '.join(ref[3])}")
    g = group(rows)
    print(f"{len(rows)} FURN with FurnitureClassWork, {len(g)} animation keywords ('*' = one of our sets already)")
    for k in sorted(g, key=lambda k: (k in OURS, -len(g[k]), k)):
        print(f"== {'*' if k in OURS else ' '} {k}: {len(g[k])}")
        for e, fid, flags, names, marker in sorted(g[k])[:12]:
            other = [n for n in names if n != k and n != "FurnitureClassWork"]
            print(f"   {e} {fid:08X} flags 0x{flags:08X} marker {marker or '-'}; {', '.join(other) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
