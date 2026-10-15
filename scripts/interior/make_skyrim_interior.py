"""One Skyrim interior cell (an inn, a house, a cave, a barrow) as a Starfield interior cell, through the same model
converter as the exterior objects and the upstream plugin writer (dotnet/PluginSpike). Outputs stay outside the repo.

    list    interior cells with reference / light / door / actor counts and whether Skyrim has a coc marker in them
    export  one cell -> <work>/export.json, convert_input.json (models), cell.json (what PluginSpike places), interior.json
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
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import exterior, skyriminterior, skyrimrefs  # noqa: E402


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


def cmd_export(a):
    work = outside_repo(a.work)
    os.makedirs(work, exist_ok=True)
    exp = skyriminterior.export_interior(a.skyrim, a.cell)
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
    rep = {"cell": exp["cell"], "cell_formkey": exp["cell_formkey"], "refs": len(exp["refs"]),
           "deferred": len(exp["deferred_refs"]), "to_convert": len(sub["refs"]), "models": len(models),
           "lights": sum(1 for r in cell["refs"] if r["type"] == "Light"), "skipped": len(skipped),
           "skip_reasons": exterior.reason_counts(skipped), "arrival": exp["arrival"],
           "load_doors": exp["load_doors"]}
    save(os.path.join(work, "interior.json"), rep)
    arr = exp["arrival"]
    print(f"{exp['cell']}: {rep['to_convert']} references to convert ({rep['models']} models), {rep['lights']} lights, "
          f"skipped {rep['skipped']} {rep['skip_reasons']}")
    print(f"arrival: {arr['source'] if arr else 'NONE (no coc marker, no door): add one by hand'}; "
          f"{len(rep['load_doors'])} load doors (not linked yet: doors are scenery)")
    print(f"next: make_skyrim_objects.py convert --work {work} ... (see this script's help)")
    return 0


def cmd_check(a):
    work = outside_repo(a.work)
    cell = load(os.path.join(work, "cell.json"))
    man_path = os.path.join(work, "convert", "manifest.json")
    if not os.path.exists(man_path):
        sys.exit(f"{man_path} missing: run make_skyrim_objects.py convert --work {work} first")
    man = load(man_path)
    have = {i["source"].lower() for i in man["items"]}
    failed = {f["nif"].lower(): f["reason"] for f in man["failures"]}
    placed = [r for r in cell["refs"] if r["model"] and r["type"] != "Light"]
    ok = [r for r in placed if exterior.source_key(r["model"]) in have]
    bad = [r for r in placed if exterior.source_key(r["model"]) not in have]
    reasons = {}
    for r in bad:
        why = failed.get(exterior.source_key(r["model"]), "not converted (run convert, or it was skipped)")
        key = re.sub(r"\d+", "#", why)[:80]
        reasons[key] = reasons.get(key, 0) + 1
    files_missing = [i["model"] for i in man["items"]
                     if not os.path.exists(os.path.join(work, "convert", "meshes", *i["model"].split("\\")))]
    coc = any(r["base_editor_id"] == skyriminterior.COC_MARKER for r in cell["refs"])
    rep = {"cell": cell["cell"], "placed_refs": len(placed), "converted_refs": len(ok), "missing_refs": len(bad),
           "missing_reasons": reasons, "lights": sum(1 for r in cell["refs"] if r["type"] == "Light"),
           "coc_marker": coc, "manifest_models_without_nif": files_missing[:10]}
    save(os.path.join(work, "check.json"), rep)
    print(json.dumps(rep, indent=1))
    out = os.path.join(work, "plugin")
    print("\nnext (needs the .NET 9 SDK; STARFIELD_DATA = your Starfield Data folder):\n"
          f"  set STARFIELD_DATA=<Starfield>\\Data\n"
          f"  dotnet run --project dotnet\\PluginSpike -- \"{out}\" \"{man_path}\" \"{os.path.join(work, 'cell.json')}\"\n"
          f"then install {out}\\FO4Port.esm plus the converted Data tree ({os.path.join(work, 'convert')}: meshes, "
          f"geometries, materials, textures) and in game: coc FO4Port_{cell['cell']}")
    return 0 if ok and coc and not files_missing else 1


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("cmd", choices=("list", "export", "check"))
    ap.add_argument("--skyrim", help="Skyrim.esm (read-only)")
    ap.add_argument("--cell", help="export: interior cell EditorID (from list)")
    ap.add_argument("--work", help="work folder OUTSIDE the repo")
    ap.add_argument("--find", default="", help="list: regex on the EditorID")
    ap.add_argument("--max", type=int, default=200, help="list: rows to print")
    return ap


def main(argv=None):
    a = parser().parse_args(argv)
    need = {"list": ("skyrim",), "export": ("skyrim", "cell", "work"), "check": ("work",)}[a.cmd]
    missing = [n for n in need if not getattr(a, n)]
    if missing:
        sys.exit(f"{a.cmd} needs --" + ", --".join(missing))
    return {"list": cmd_list, "export": cmd_export, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
