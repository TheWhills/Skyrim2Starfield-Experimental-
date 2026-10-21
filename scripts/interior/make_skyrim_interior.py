"""One Skyrim interior cell (an inn, a house, a cave, a barrow) as a Starfield interior cell, through the same model
converter as the exterior objects and the upstream plugin writer (dotnet/PluginSpike). Outputs stay outside the repo.

    list    interior cells with reference / light / door / actor counts and whether Skyrim has a coc marker in them
    export  one cell -> <work>/export.json, convert_input.json (models), cell.json (what PluginSpike places), interior.json
    batch   many cells into one work folder (one conversion, one plugin): --cells A,B --find REGEX --connected-from CELL
            --depth N; load doors between cells of the batch are linked -> exports/, cells/<cell>.json, cells.txt,
            convert_input.json (every model once), batch.json
    check   after the conversion: which placed models converted, which failed, the PluginSpike command to run

Windows, from the repo:
    python -I scripts\\interior\\make_skyrim_interior.py list --skyrim "<Skyrim SE>\\Data\\Skyrim.esm" --find inn
    python -I scripts\\interior\\make_skyrim_interior.py export --skyrim "<Skyrim SE>\\Data\\Skyrim.esm" ^
        --cell SleepingGiantInn --work C:\\Modding\\work\\int_sleepinggiant
    python -I scripts\\terrain\\make_skyrim_objects.py convert --work C:\\Modding\\work\\int_sleepinggiant ^
        --skyrim-data "<Skyrim SE>\\Data" --content-resources "<Starfield>\\Tools\\ContentResources.zip" ^
        --texconv "<xEdit>\\Edit Scripts\\texconv.exe" --starfield-data "<Starfield>\\Data" --resume
    python -I scripts\\interior\\make_skyrim_interior.py check --work C:\\Modding\\work\\int_sleepinggiant
then the PluginSpike command `check` prints (cell "FO4Port_<cell>" in FO4Port.esm: the writer's existing name).
A whole town's interiors, linked to each other (doors to the outside stay scenery until the exterior is linked):
    python -I scripts\\interior\\make_skyrim_interior.py batch --skyrim "<Skyrim SE>\\Data\\Skyrim.esm" ^
        --find "^Riverwood" --work C:\\Modding\\work\\int_riverwood
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import exterior, fo4land, skyriminterior, skyrimrefs  # noqa: E402


def save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def outside_repo(path):
    p = os.path.abspath(path)
    if p.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--work must be outside the repository (it receives converted game data)")
    return p


def cmd_list(a):
    cells = skyriminterior.list_interiors(a.skyrim)
    if a.find:
        rx = re.compile(a.find, re.I)
        cells = [c for c in cells if rx.search(c["edid"])]
    print(f"{'EditorID':40} {'refs':>6} {'lights':>6} {'doors':>5} {'actors':>6}  coc")
    for c in cells[:a.max]:
        print(f"{c['edid'][:40]:40} {c['refs']:>6} {c['lights']:>6} {c['doors']:>5} {c['actors']:>6}  "
              f"{'yes' if c['coc'] else '-'}")
    print(f"{len(cells)} interior cells" + (f" matching {a.find!r}" if a.find else ""))
    return 0


# Owner's Sleeping Giant Inn tests (2026-10-15): PluginSpike's defaults (underground template 06BCF8, LUT image space
# 122393) left the inn dark and green-grey. What looked like Skyrim: the ship interior template 006658, the Skyrim cell's
# own ambient (CELL_AMBIENT skyrim), translated lights at 4x the template lumens, and no colour grading (LGT_NoLut
# 1C6C37; _RENAME_Test_NaturalColorInterior_IS 0606C1 looked about the same, LGT_LUT_Int_Gen_v04_curve 03D206 was dark).
INTERIOR_LIGHTING = {"LIGHTING_TEMPLATE": "006658", "LIGHT_MERGE_M": "1", "IMAGE_SPACE": "1C6C37",
                     "CELL_AMBIENT": "skyrim", "LIGHT_POWER": "4"}


def write_lighting(work, cell, a):
    """<work>/convert/lighting.json (read by PluginSpike from its output folder): defaults for this cell, under
    values already in the file (hand edits survive a re-export), under --lighting-template / --light-merge-m."""
    path = os.path.join(work, "convert", "lighting.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg = load(path) if os.path.exists(path) else {}
    entry = {**INTERIOR_LIGHTING, **cfg.get(cell, {})}       # a hand-edited value for this cell is kept
    if a.lighting_template:
        entry["LIGHTING_TEMPLATE"] = a.lighting_template
    if a.light_merge_m is not None:
        entry["LIGHT_MERGE_M"] = str(a.light_merge_m)
    cfg[cell] = entry
    save(path, cfg)
    return entry


def cmd_export(a):
    work = outside_repo(a.work)
    os.makedirs(work, exist_ok=True)
    nav_defaults = load(a.navmesh_defaults) if a.navmesh_defaults else None
    exp = skyriminterior.export_interior(a.skyrim, a.cell, navmesh_defaults=nav_defaults)
    sub, skipped = exterior.select(exp, skyrimrefs.CONVERT_TYPES)
    by_model = {}
    for r in sub["refs"]:
        by_model.setdefault(exterior.source_key(r["model"]), {"model": r["model"], "type": r["type"],
                                                              "formkey": r["formkey"]})
    models = [by_model[k] for k in sorted(by_model)]
    cell = skyriminterior.plugin_cell(exp, sub["refs"])
    save(os.path.join(work, "export.json"), exp)
    save(os.path.join(work, "convert_input.json"), {"schema_version": 2, "cell": exp["cell"], "refs": models})
    save(os.path.join(work, "cell.json"), cell)
    lighting = write_lighting(work, exp["cell"], a)
    rep = {"cell": exp["cell"], "cell_formkey": exp["cell_formkey"], "refs": len(exp["refs"]),
           "deferred": len(exp["deferred_refs"]), "to_convert": len(sub["refs"]), "models": len(models),
           "lights": sum(1 for r in cell["refs"] if r["type"] == "Light"), "skipped": len(skipped),
           "skip_reasons": exterior.reason_counts(skipped), "arrival": exp["arrival"],
           "load_doors": exp["load_doors"], "lighting": lighting}
    save(os.path.join(work, "interior.json"), rep)
    arr = exp["arrival"]
    print(f"{exp['cell']}: {rep['to_convert']} references to convert ({rep['models']} models), {rep['lights']} lights, "
          f"skipped {rep['skipped']} {rep['skip_reasons']}")
    print(f"arrival: {arr['source'] if arr else 'NONE (no coc marker, no door): add one by hand'}; "
          f"{len(rep['load_doors'])} load doors (not linked yet: doors are scenery)")
    print(f"lighting: {lighting} in {os.path.join(work, 'convert', 'lighting.json')}")
    for r in cell["refs"]:
        if r["type"] == "Light" and "light" in r:
            L = r["light"]
            ref = "" if L.get("ref_radius") is None else f" (reference override {L['ref_radius']:g})"
            flick = " flicker" if L.get("flicker") else ""
            print(f"  light {r['base_editor_id'][:32]:32} radius {L['radius']:7.1f}{ref} colour {L['color']} "
                  f"fade {L['fade']:g}{flick}")
    print(f"next: make_skyrim_objects.py convert --work {work} ... (see this script's help)")
    return 0


def cmd_batch(a):
    work = outside_repo(a.work)
    os.makedirs(os.path.join(work, "exports"), exist_ok=True)
    os.makedirs(os.path.join(work, "cells"), exist_ok=True)
    nav_defaults = load(a.navmesh_defaults) if a.navmesh_defaults else None
    names = [n.strip() for n in (a.cells or "").split(",") if n.strip()]
    with fo4land.Plugin(a.skyrim) as p:
        src = skyriminterior.Source(p, navmesh_defaults=nav_defaults)
        try:
            picked = skyriminterior.pick_cells(src, names, a.find, a.connected_from or "", a.depth, a.limit)
        except KeyError as e:
            sys.exit(str(e))
        if not picked:
            sys.exit("no interior cell matches (--cells / --find / --connected-from)")
        exports = [src.export(n) for n in picked]
    doors = skyriminterior.link_load_doors(exports)
    batch_nav = {n["formkey"] for e in exports for n in e["navmeshes"]}
    by_model, rows, cell_files = {}, [], []
    for e in exports:
        sub, skipped = exterior.select(e, skyrimrefs.CONVERT_TYPES)
        for r in sub["refs"]:
            by_model.setdefault(exterior.source_key(r["model"]), {"model": r["model"], "type": r["type"],
                                                                  "formkey": r["formkey"]})
        cell = skyriminterior.plugin_cell(e, sub["refs"], batch_nav)
        save(os.path.join(work, "exports", e["cell"] + ".json"), e)
        path = os.path.join(work, "cells", e["cell"] + ".json")
        save(path, cell)
        cell_files.append(path)
        write_lighting(work, e["cell"], a)
        rows.append({"cell": e["cell"], "to_convert": len(sub["refs"]), "skipped": len(skipped),
                     "actors": sum(1 for d in e["deferred_refs"] if d["reason"].startswith("placed actor")),
                     "navmeshes": len(e["navmeshes"]), "unreadable_navmeshes": len(e["unreadable_navmeshes"]),
                     "linked_doors": sum(1 for r in cell["refs"] if "teleport" in r),
                     "arrival": (e["arrival"] or {}).get("source")})
    models = [by_model[k] for k in sorted(by_model)]
    save(os.path.join(work, "convert_input.json"), {"schema_version": 2, "cell": "batch", "refs": models})
    with open(os.path.join(work, "cells.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(cell_files) + "\n")
    rep = {"cells": rows, "models": len(models), "load_doors": doors}
    save(os.path.join(work, "batch.json"), rep)
    for r in rows:
        print(f"  {r['cell'][:40]:40} {r['to_convert']:>5} refs  {r['navmeshes']} navmesh  "
              f"{r['linked_doors']} linked doors  {r['actors']} actors (not yet)")
    print(f"{len(rows)} cells, {len(models)} models to convert; load doors linked {doors['linked']}, "
          f"not linked {doors['unlinked'] or 0}")
    print(f"next: make_skyrim_objects.py convert --work {work} ..., then check --work {work}")
    return 0


def check_cell(work, cell, have, failed):
    placed = [r for r in cell["refs"] if r["model"] and r["type"] != "Light"]
    ok = [r for r in placed if exterior.source_key(r["model"]) in have]
    bad = [r for r in placed if exterior.source_key(r["model"]) not in have]
    reasons = {}
    for r in bad:
        why = failed.get(exterior.source_key(r["model"]), "not converted (run convert, or it was skipped)")
        key = re.sub(r"\d+", "#", why)[:80]
        reasons[key] = reasons.get(key, 0) + 1
    doors = [r for r in cell["refs"] if "teleport" in r]
    return {"cell": cell["cell"], "placed_refs": len(placed), "converted_refs": len(ok), "missing_refs": len(bad),
            "missing_reasons": reasons, "lights": sum(1 for r in cell["refs"] if r["type"] == "Light"),
            "coc_marker": any(r["base_editor_id"] == skyriminterior.COC_MARKER for r in cell["refs"]),
            "linked_doors": len(doors),
            "linked_doors_not_converted": sum(1 for r in doors if exterior.source_key(r["model"]) not in have)}


def cmd_check(a):
    work = outside_repo(a.work)
    batch = os.path.exists(os.path.join(work, "batch.json"))
    cell_args = ("@" + os.path.join(work, "cells.txt")) if batch else os.path.join(work, "cell.json")
    cells = ([load(os.path.join(work, "cells", r["cell"] + ".json")) for r in load(os.path.join(work, "batch.json"))["cells"]]
             if batch else [load(os.path.join(work, "cell.json"))])
    man_path = os.path.join(work, "convert", "manifest.json")
    if not os.path.exists(man_path):
        sys.exit(f"{man_path} missing: run make_skyrim_objects.py convert --work {work} first")
    man = load(man_path)
    have = {i["source"].lower() for i in man["items"]}
    failed = {f["nif"].lower(): f["reason"] for f in man["failures"]}
    reps = [check_cell(work, c, have, failed) for c in cells]
    files_missing = [i["model"] for i in man["items"]
                     if not os.path.exists(os.path.join(work, "convert", "meshes", *i["model"].split("\\")))]
    if batch:
        rep = {"cells": reps, "manifest_models_without_nif": files_missing[:10]}
        for r in reps:
            print(f"  {r['cell'][:40]:40} {r['converted_refs']:>5}/{r['placed_refs']:<5} converted  "
                  f"coc {'yes' if r['coc_marker'] else 'NO'}  doors {r['linked_doors']}"
                  + (f" ({r['linked_doors_not_converted']} not converted: no teleport)"
                     if r["linked_doors_not_converted"] else ""))
    else:
        rep = dict(reps[0], manifest_models_without_nif=files_missing[:10])
        print(json.dumps(rep, indent=1))
    save(os.path.join(work, "check.json"), rep)
    ok = any(r["converted_refs"] for r in reps)
    coc = reps[0]["coc_marker"]                     # the cell `coc` goes to; the others are reached by doors too
    first = reps[0]["cell"]
    staging = os.path.join(work, "convert")
    print("\nnext (needs the .NET 9 SDK; Starfield closed; PowerShell):\n"
          f"  $env:STARFIELD_DATA = \"<Starfield>\\Data\"\n"
          f"  dotnet run --project dotnet\\PluginSpike -- \"{staging}\" \"{man_path}\" \"{cell_args}\"\n"
          f"  python -I scripts\\deploy_starfield.py install --staging \"{staging}\" --starfield \"<Starfield>\"\n"
          f"in game, console: coc FO4Port_{first}\n"
          f"afterwards: python -I scripts\\deploy_starfield.py uninstall --starfield \"<Starfield>\"")
    return 0 if ok and coc and not files_missing else 1


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("cmd", choices=("list", "export", "batch", "check"))
    ap.add_argument("--skyrim", help="Skyrim.esm (read-only)")
    ap.add_argument("--cell", help="export: interior cell EditorID (from list)")
    ap.add_argument("--work", help="work folder OUTSIDE the repo")
    ap.add_argument("--lighting-template", help="export: Starfield LGTM FormID hex for the cell (default 006658)")
    ap.add_argument("--light-merge-m", type=float, help="export: merge lights closer than this many metres (default 1)")
    ap.add_argument("--navmesh-defaults", help="export: navmesh_defaults.json from navmesh_survey.py (values of the "
                                               "Starfield-only navmesh fields; default: zeros)")
    ap.add_argument("--find", default="", help="list / batch: regex on the EditorID")
    ap.add_argument("--cells", default="", help="batch: interior EditorIDs, comma-separated")
    ap.add_argument("--connected-from", default="", help="batch: this cell and the interiors behind its load doors")
    ap.add_argument("--depth", type=int, default=1, help="batch with --connected-from: doors to follow (default 1)")
    ap.add_argument("--limit", type=int, default=0, help="batch: at most this many cells (0: all)")
    ap.add_argument("--max", type=int, default=200, help="list: rows to print")
    return ap


def main(argv=None):
    a = parser().parse_args(argv)
    need = {"list": ("skyrim",), "export": ("skyrim", "cell", "work"), "batch": ("skyrim", "work"),
            "check": ("work",)}[a.cmd]
    missing = [n for n in need if not getattr(a, n)]
    if missing:
        sys.exit(f"{a.cmd} needs --" + ", --".join(missing))
    return {"list": cmd_list, "export": cmd_export, "batch": cmd_batch, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
