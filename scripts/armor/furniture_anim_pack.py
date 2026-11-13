"""Skyrim's own furniture animations for our furniture (docs/npc/furniture.md "Animations"): converts each set's Skyrim
clips with hkx_to_af (decode, retarget onto Starfield's human rig, .af + .afx through CALUMI) into the set's own folder,
under the file names and tags of the vanilla Starfield furniture clips (their descriptors as templates). The folder is
put first, for furniture carrying the set's keyword, by S2SStances.esm (stance_plugin.FURNITURE_SETS) - tags it lacks
fall back to Starfield's.

Sets (mapping from the owner's furniture_anim_survey, 2026-11-13: Starfield's chair / bench graph plays these tags; the
Skyrim clips are the ones Skyrim's mt_behavior plays for chairs and benches):
  Sit (chairs, benches): actors\\human\\animations\\furniture\\s2s_sit

One seat offset for the whole set: the Idle is converted first with --align-com (its mean COM moved onto the vanilla
chair Idle's), and that shift is then applied to every clip (--com-shift), so entering, sitting and leaving line up.
No root motion: Starfield's own furniture clips carry the body's way into the seat themselves (supported hypothesis).

    python -I scripts\\armor\\furniture_anim_pack.py --calumi "<CALUMI.Animation.dll>" --skyrim-data "$sky"
        --starfield $sf --out "$mods\\S2S Furniture Anims" --work C:\\Modding\\work\\furniture_anim_pack

Writes <out>\\meshes\\actors\\human\\animations\\furniture\\<set folder>\\*.af / .afx (a loose-file mod for MO2) and
<work>\\furniture_anim_pack.json. New folder: run the Creation Kit's -GenerateAnimInfo afterwards, as for the stances.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

SKY_ANIM = "meshes\\actors\\character\\animations\\"
SF_ANIM = "meshes\\actors\\human\\animations\\"

# set -> (folder under meshes\, vanilla template folder under meshes\, [(vanilla .afx file, Skyrim clip, new tag/None)])
# new tag: a tag the template folder lacks (written under its own name, the given template's descriptor reused).
SETS = {
    "Sit": (SF_ANIM + "furniture\\s2s_sit", SF_ANIM + "furniture\\chair", [
        ("idle.afx", "male\\chair_idlebasevar1.hkx", None),
        ("idle_flavor01.afx", "male\\chair_idlebasevar2.hkx", None),
        ("idle_flavor02.afx", "male\\chair_idlebasevar1shoulders.hkx", None),
        ("idle_flavor03.afx", "male\\chair_idlebasevar2.hkx", None),
        ("idle_flavor03.afx", "male\\chair_idlebasevar1shoulders.hkx", "Idle_Flavor04"),     # benches have a fourth
        ("enterfromstand.afx", "male\\chair_frontentervar1.hkx", None),
        ("frontenterfromstand.afx", "male\\chair_frontentervar1.hkx", None),
        ("exittostand.afx", "male\\chair_frontexit.hkx", None),
        ("frontexittostand.afx", "male\\chair_frontexit.hkx", None),
        ("quickexittostand.afx", "male\\chair_frontexit.hkx", None),
        ("leftenterfromstand.afx", "male\\chair_leftenter.hkx", None),
        ("leftexittostand.afx", "male\\chair_leftexit.hkx", None),
        ("leftquickexittostand.afx", "male\\chair_leftexit.hkx", None),
        ("rightenterfromstand.afx", "male\\chair_rightenter.hkx", None),
        ("rightexittostand.afx", "male\\chair_rightexit.hkx", None),
        ("rightquickexittostand.afx", "male\\chair_rightexit.hkx", None),
        # Skyrim has no entry from behind: Rear* stay Starfield's; EnterInstant, LookDirections, Talk_*, Camera too
    ]),
}


def replace_args(anim_set: str):
    """hkx_to_af --replace values for a set: (Idle first, the rest)."""
    folder, tpl, rows = SETS[anim_set]
    args = []
    for afx, clip, tag in rows:
        a = f"{SKY_ANIM}{clip}::{tpl}\\{afx}" + (f"::{tag}" if tag else "")
        args.append(a)
    idle = [x for x in args if x.endswith("\\idle.afx")]
    return idle, [x for x in args if x not in idle]


def hkx_args(a, work, folder, replace, com=None):
    out = ["--calumi", a.calumi, "--skyrim-data", a.skyrim_data, "--starfield-data", os.path.join(a.starfield, "Data"),
           "--out", work, "--into", folder, "--no-root-motion"]
    out += ["--com-shift", f"{com[0]},{com[1]}"] if com is not None else ["--align-com"]
    for r in replace:
        out += ["--replace", r]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--calumi", required=True, help="CALUMI.Animation.dll (as for hkx_to_af)")
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="Starfield's game folder")
    ap.add_argument("--out", required=True, help="the mod folder (MO2): gets meshes\\actors\\human\\animations\\...")
    ap.add_argument("--work", required=True, help="a scratch folder outside the repository")
    ap.add_argument("--set", action="append", choices=sorted(SETS), help="only these sets (default: all)")
    ap.add_argument("--com-shift", metavar="X,Y", help="use this seat offset instead of the Idle's --align-com result")
    a = ap.parse_args(argv)
    for p in (a.out, a.work):
        if os.path.abspath(p).lower().startswith(os.path.abspath(REPO).lower()):
            sys.exit(f"{p}: must be outside the repository")
    import hkx_to_af
    report = {}
    for st in a.set or sorted(SETS):
        folder = SETS[st][0]
        work = os.path.join(a.work, st)
        idle, rest = replace_args(st)
        com = [float(x) for x in a.com_shift.split(",")] if a.com_shift else None
        if com is None:
            print(f"== {st}: Idle with --align-com (the set's seat offset)")
            rc = hkx_to_af.main(hkx_args(a, os.path.join(work, "idle"), folder, idle))
            with open(os.path.join(work, "idle", "report.json"), encoding="utf-8") as fh:
                row = json.load(fh)[0]
            if rc != 0 or "com_shift_m" not in row:
                sys.exit(f"{st}: the Idle did not convert ({row.get('error') or row})")
            com = row["com_shift_m"]
        print(f"== {st}: every clip with --com-shift {com[0]},{com[1]}")
        rc = hkx_to_af.main(hkx_args(a, os.path.join(work, "all"), folder, idle + rest, com))
        with open(os.path.join(work, "all", "report.json"), encoding="utf-8") as fh:
            rows = json.load(fh)
        src = os.path.join(work, "all", *folder.split("\\"))
        dst = os.path.join(a.out, *folder.split("\\"))
        os.makedirs(dst, exist_ok=True)
        files = sorted(f for f in os.listdir(src) if f.lower().endswith((".af", ".afx"))) if os.path.isdir(src) else []
        for f in files:
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
        report[st] = {"folder": folder, "com_shift_m": com, "clips": len(rows),
                      "failed": [r.get("clip") for r in rows if "error" in r], "files": files}
        print(f"{st}: {len(files)} files -> {dst}" + (f"; failed: {report[st]['failed']}" if report[st]["failed"] else ""))
    with open(os.path.join(a.work, "furniture_anim_pack.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    return 0 if all(not r["failed"] for r in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
