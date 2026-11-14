"""Skyrim's own furniture animations for our furniture (docs/npc/furniture.md "Animations"): converts each set's Skyrim
clips with hkx_to_af (decode, retarget onto Starfield's human rig, .af + .afx through CALUMI) into the set's own folder,
under the file names and tags of the vanilla Starfield furniture clips (their descriptors as templates). The folder is
put first, for furniture carrying the set's keyword, by S2SStances.esm (stance_plugin.FURNITURE_SETS) - tags it lacks
fall back to Starfield's.

Sets (mapping from the owner's furniture_anim_survey, 2026-11-13 / 14: the tags the templates' folders have; the
Skyrim clips are the ones Skyrim's mt_behavior plays for that furniture), each in actors\\human\\animations\\furniture\\:
  Sit (chairs, benches) s2s_sit; RailLean, WallLean, Counter, LeanTable, Sweep, Alchemy, Enchant, Cook, Tanning
  (s2s_<name>); make_furniture.ANIM_SET_RULES says which Skyrim furniture gets which.

One offset per set: the Idle is converted first with --align-com (its mean COM moved onto the vanilla template Idle's),
and that shift is then applied to every clip of the set, so entering, idling and leaving line up; measured offsets are
kept in COM_SHIFT.
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
def standing_set(folder, template, idle, flavors=(), enter=None, exit_=None, n_flavors=0, instant=False):
    """Rows for a set built on one idle loop: Idle, every Idle_FlavorNN slot the template folder has (n_flavors) filled
    from `flavors` in turn (the idle itself when there are none: a vanilla flavor would play Starfield's own pose in
    the middle of ours), EnterFromStand, ExitToStand and QuickExitToStand, EnterInstant (spawning in place) when the
    template has it. Flavors must start and end on the idle's pose (Skyrim's transitions into another loop do not)."""
    rows = [("idle.afx", idle, None)]
    pool = list(flavors) or [idle]
    rows += [(f"idle_flavor{i:02d}.afx", pool[(i - 1) % len(pool)], None) for i in range(1, n_flavors + 1)]
    if enter:
        rows.append(("enterfromstand.afx", enter, None))
    if exit_:
        rows += [("exittostand.afx", exit_, None), ("quickexittostand.afx", exit_, None)]
    if instant:
        rows.append(("enterinstant.afx", idle, None))
    return (SF_ANIM + "furniture\\" + folder, SF_ANIM + "furniture\\" + template, rows)


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
    # 2026-11-14 (owner's survey of the templates' folders: every one has Idle, Idle_FlavorNN, EnterFromStand,
    # ExitToStand, QuickExitToStand; sweep and wipe-wall also EnterInstant). Skyrim clips: mt_behavior's furniture clips.
    "RailLean": standing_set("s2s_raillean", "leaningbartopfront", "railleanidle.hkx", (), "railleanenter.hkx",
                             "railleanexit.hkx", 6),
    "WallLean": standing_set("s2s_walllean", "leaningbartopfront", "wall_idlebackloop.hkx", (),
                             "wall_idlebackenter.hkx", "wall_idlebackexit.hkx", 6),
    # the counter's arms-on-counter / wiping loops are other poses (reached by transition clips): idle only for now
    "Counter": standing_set("s2s_counter", "bartender", "animobjectcounteridleloopright.hkx", (),
                            "animobjectcounterenter.hkx", "animobjectcounterexit.hkx", 5),
    "LeanTable": standing_set("s2s_leantable", "desklean", "idleleantable.hkx", ("idleleantable_point.hkx",),
                              "idleleantable_enter.hkx", "idleleantable_exit.hkx", 4),
    # Skyrim's sweeping has no exit clip: ExitToStand stays Starfield's. The broom: Starfield's descriptor events.
    "Sweep": standing_set("s2s_sweep", "standing_sweep", "animobjectsweepingidlebase.hkx",
                          ("animobjectsweepingidlevar1.hkx",), "animobjectsweepingidlestart.hkx", None, 5, instant=True),
    "Alchemy": standing_set("s2s_alchemy", "workbench\\pharmaworkbench", "craftingalchemybenchstirboth.hkx",
                            ("craftingalchemybenchpoundboth.hkx", "craftingalchemybenchtap.hkx"),
                            "craftingalchemybenchenter.hkx", "craftingalchemybenchexit.hkx", 5),
    "Enchant": standing_set("s2s_enchant", "workbench\\industrialworkbench", "craftingenchantingbenchidle.hkx",
                            ("craftingenchantingbenchidlecircle.hkx",), "craftingenchantingbenchenter.hkx",
                            "craftingenchantingbenchexit.hkx", 6),
    "Cook": standing_set("s2s_cook", "workbench\\galleyworkbench", "craftingcookingpotstir.hkx", (),
                         "craftingcookingpotenter.hkx", "craftingcookingpotexit.hkx", 0),
    "Tanning": standing_set("s2s_tanning", "standing_wipewall", "craftingtanningidleb.hkx",
                            ("craftingtanningidlea.hkx",), "craftingtanningenterb.hkx", "craftingtanningexitb.hkx", 5,
                            instant=True),
}

# Seat / stand offset per set (metres, X,Y): measured once by the Idle's --align-com and kept, so reruns skip that pass.
# Sets not listed are aligned to their template's Idle on each run; (0, 0) keeps Skyrim's own placement (WallLean:
# Skyrim leans back on the wall, the template's actor faces a counter, so its COM is no guide).
COM_SHIFT = {"Sit": (0.027, -0.091), "WallLean": (0.0, 0.0)}


# Descriptor variables left out of our copies (2026-11-14, owner, in game: seated on our bench the arms were pulled back
# and twisted inward, hands by the hips; af_pose showed the clip itself has them forward on the thighs, as in Skyrim).
# Starfield's chair and bench descriptors keep bEnableHandIK on over the whole Idle (and its enters / exits): the graph
# then pulls the hands to IK targets of Starfield's furniture models, which our converted Skyrim models do not have.
# Skyrim's clips place the hands themselves.
DROP_VARIABLES = ("bEnableHandIK",)

# Hands resting on the thighs: at least this far above the hip-knee line and to the outside of it (metres), by arm IK
# (hkx_to_af --hand-clearance). 2026-11-14 (owner, in game: the seated hands sink into the thighs). af_pose
# hands_on_thighs: our Idle 0.047 / 0.063 above, 0.004 / 0.034 inside; Starfield's chair Idle 0.129 / 0.136 above,
# 0.026 / 0.030 outside.
HAND_CLEARANCE = {"Sit": (0.13, 0.03)}


def strip_variables(afx_text: str, names=DROP_VARIABLES) -> str:
    """An .afx descriptor without the <variable> entries named `names` (any case)."""
    import re
    want = {n.lower() for n in names}

    def keep(m):
        nm = re.search(r"<name>\s*([^<]*?)\s*</name>", m.group(0))
        return "" if nm and nm.group(1).lower() in want else m.group(0)
    out = re.sub(r"[ \t]*<variable>.*?</variable>[ \t]*\r?\n?", keep, afx_text, flags=re.S)
    return re.sub(r"[ \t]*<variables>\s*</variables>[ \t]*\r?\n?", "", out)


def parse_pair(value):
    """'0.027,-0.091' or ['0.027', '-0.091'] or ['0.027,-0.091'] (PowerShell splits an unquoted pair) -> floats."""
    text = ",".join(value) if isinstance(value, (list, tuple)) else str(value)
    return [float(x) for x in text.replace(" ", ",").split(",") if x]


def replace_args(anim_set: str):
    """hkx_to_af --replace values for a set: (Idle first, the rest)."""
    folder, tpl, rows = SETS[anim_set]
    args = []
    for afx, clip, tag in rows:
        a = f"{SKY_ANIM}{clip}::{tpl}\\{afx}" + (f"::{tag}" if tag else "")
        args.append(a)
    idle = [x for x in args if x.endswith("\\idle.afx")]
    return idle, [x for x in args if x not in idle]


def hkx_args(a, work, folder, replace, com=None, hands=None):
    out = ["--calumi", a.calumi, "--skyrim-data", a.skyrim_data, "--starfield-data", os.path.join(a.starfield, "Data"),
           "--out", work, "--into", folder, "--no-root-motion"]
    out += ["--com-shift", f"{com[0]},{com[1]}"] if com is not None else ["--align-com"]
    if hands:
        out += ["--hand-clearance", ",".join(str(x) for x in hands)]
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
    ap.add_argument("--com-shift", metavar="X,Y", nargs="+",
                    help="with one --set: use this offset instead of COM_SHIFT / the Idle's --align-com result "
                         "(PowerShell splits an unquoted X,Y in two: both forms are taken)")
    ap.add_argument("--hand-clearance", metavar="UP,OUT", help="override HAND_CLEARANCE for the sets run")
    a = ap.parse_args(argv)
    for p in (a.out, a.work):
        if os.path.abspath(p).lower().startswith(os.path.abspath(REPO).lower()):
            sys.exit(f"{p}: must be outside the repository")
    if a.com_shift and len(a.set or SETS) != 1:
        sys.exit("--com-shift is one set's offset: give it with exactly one --set")
    import hkx_to_af
    report = {}
    for st in a.set or list(SETS):
        folder = SETS[st][0]
        work = os.path.join(a.work, st)
        idle, rest = replace_args(st)
        com = parse_pair(a.com_shift) if a.com_shift else (list(COM_SHIFT[st]) if st in COM_SHIFT else None)
        hands = parse_pair(a.hand_clearance) if a.hand_clearance else HAND_CLEARANCE.get(st)
        if com is None:
            print(f"== {st}: Idle with --align-com (the set's seat offset)")
            rc = hkx_to_af.main(hkx_args(a, os.path.join(work, "idle"), folder, idle))
            with open(os.path.join(work, "idle", "report.json"), encoding="utf-8") as fh:
                row = json.load(fh)[0]
            if rc != 0 or "com_shift_m" not in row:
                print(f"{st}: the Idle did not convert ({row.get('error') or row}); set skipped")
                report[st] = {"folder": folder, "failed": [row.get("clip")], "error": row.get("error"), "files": []}
                continue
            com = row["com_shift_m"]
            print(f"{st}: offset {com[0]},{com[1]} (add to COM_SHIFT to keep it)")
        print(f"== {st}: every clip with --com-shift {com[0]},{com[1]}")
        rc = hkx_to_af.main(hkx_args(a, os.path.join(work, "all"), folder, idle + rest, com, hands))
        with open(os.path.join(work, "all", "report.json"), encoding="utf-8") as fh:
            rows = json.load(fh)
        src = os.path.join(work, "all", *folder.split("\\"))
        dst = os.path.join(a.out, *folder.split("\\"))
        os.makedirs(dst, exist_ok=True)
        files = sorted(f for f in os.listdir(src) if f.lower().endswith((".af", ".afx"))) if os.path.isdir(src) else []
        stripped = 0
        for f in files:
            if f.lower().endswith(".afx"):
                with open(os.path.join(src, f), encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                new = strip_variables(text)
                stripped += new != text
                with open(os.path.join(dst, f), "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
            else:
                shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
        print(f"{st}: {', '.join(DROP_VARIABLES)} left out of {stripped} descriptors")
        lifted = {r["name"]: r["hands_lifted"] for r in rows if r.get("hands_lifted")}
        if hands:
            top = max((v["max_lift_m"] for d in lifted.values() for v in d.values()), default=0.0)
            print(f"{st}: hands kept {hands[0]} m above the thighs, {len(lifted)} clips, lifted up to {top} m")
        report[st] = {"folder": folder, "com_shift_m": com, "hand_clearance": hands, "hands_lifted": lifted, "clips": len(rows), "hand_ik_stripped": stripped,
                      "failed": [r.get("clip") for r in rows if "error" in r], "files": files}
        print(f"{st}: {len(files)} files -> {dst}" + (f"; failed: {report[st]['failed']}" if report[st]["failed"] else ""))
    with open(os.path.join(a.work, "furniture_anim_pack.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    return 0 if all(not r["failed"] for r in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
