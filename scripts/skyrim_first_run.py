"""First run on real game files: one command that checks the setup, reads Skyrim, surveys thousands of Skyrim meshes
(read-only, fast) and converts a small sample, then writes ONE short report to paste back. Nothing is installed into
either game; everything goes to --work (outside the repo).

    python -I scripts\\skyrim_first_run.py --skyrim-data "<Skyrim Special Edition>\\Data" --starfield "<Starfield>"
        --texconv "<xEdit>\\Edit Scripts\\texconv.exe" --work C:\\Modding\\work\\skyrim_first_run
        [--around Riverwood] [--radius 2] [--survey 3000] [--sample 20]

Steps (a failed step is recorded and the run goes on wherever it can):
  1 setup    Python packages (numpy, Pillow, lz4), .NET 9 SDK, texconv, Skyrim.esm, Starfield.esm,
             Tools\\ContentResources.zip, the box-collision template in Starfield's archives
  2 terrain  Tamriel's LAND extent, holes, heights, seams, the overlay size the build would choose, the arrival cell
  3 archives every Skyrim .bsa opens (version, files), one mesh and one texture read back
  4 objects  every placed reference of Tamriel: counts by type and by what the pipeline would do with it
  5 survey   up to --survey distinct models placed in Tamriel, parsed only (no conversion): geometry block types,
             shapes found, collision decoded, unsupported collision types, collision bounds against render bounds,
             parse errors grouped by message. This is the check of the Skyrim formats read from nif.xml.
  6 sample   --sample models placed within --radius cells of --around, really converted (textures through texconv,
             collision boxes, materials): per-model result, collision method and box count, material fallbacks.
Writes <work>\\report.txt (short, paste this) and <work>\\report.json (everything).
"""
import argparse
import importlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(HERE, "terrain"))

BOX_TEMPLATE_NIF = "meshes/setdressing/historicaloilportraits/historicaloilportraits_shackleton.nif"


class Run:
    def __init__(self, work):
        self.work = work
        self.steps = {}
        self.lines = []

    def step(self, name, fn):
        t0 = time.time()
        try:
            res = fn()
            self.steps[name] = {"ok": True, "seconds": round(time.time() - t0, 1), **(res or {})}
        except Exception as e:                       # noqa: BLE001  (every step is reported, the run goes on)
            self.steps[name] = {"ok": False, "seconds": round(time.time() - t0, 1),
                                "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}
        s = self.steps[name]
        print(f"[{'ok' if s['ok'] else 'FAIL'}] {name} ({s['seconds']} s)" + ("" if s["ok"] else f": {s['error']}"))
        return s


def top(counter, n=12):
    return dict(sorted(counter.items(), key=lambda kv: -kv[1])[:n])


def bump(d, k, n=1):
    d[k] = d.get(k, 0) + n


# ---------------------------------------------------------------------------------------------------------- steps
def setup(a):
    out, problems = {"python": sys.version.split()[0], "os": platform.platform()}, []
    for mod in ("numpy", "PIL", "lz4"):
        try:
            m = importlib.import_module(mod)
            out[mod] = getattr(m, "__version__", "ok")
        except ImportError:
            out[mod] = None
            problems.append(f"pip install {'pillow' if mod == 'PIL' else mod}")
    try:
        sdks = subprocess.run(["dotnet", "--list-sdks"], capture_output=True, text=True, timeout=60).stdout
        out["dotnet_sdks"] = [l.split()[0] for l in sdks.splitlines() if l.strip()]
        if not any(v.startswith("9.") for v in out["dotnet_sdks"]):
            problems.append("install the .NET 9 SDK (needed to build the plugins)")
    except (OSError, subprocess.SubprocessError):
        out["dotnet_sdks"] = None
        problems.append("dotnet not found: install the .NET 9 SDK")
    files = {"texconv": a.texconv, "Skyrim.esm": os.path.join(a.skyrim_data, "Skyrim.esm"),
             "Starfield.esm": os.path.join(a.starfield, "Data", "Starfield.esm"),
             "ContentResources.zip": os.path.join(a.starfield, "Tools", "ContentResources.zip")}
    for k, p in files.items():
        out[k] = os.path.isfile(p)
        if not out[k]:
            problems.append(f"missing {k}: {p}")
    out["box_template"] = box_template(a) is not None
    if not out["box_template"]:
        problems.append(f"{BOX_TEMPLATE_NIF} not found in Starfield - Meshes*.ba2")
    out["problems"] = problems
    return out


def box_template(a):
    from fo4sf import ba2
    d = os.path.join(a.starfield, "Data")
    if not os.path.isdir(d):
        return None
    for fn in sorted(os.listdir(d)):
        if fn.lower().startswith("starfield - meshes") and fn.lower().endswith(".ba2"):
            try:
                arc = ba2.Ba2(os.path.join(d, fn))
            except Exception:                        # noqa: BLE001
                continue
            i = arc.find(BOX_TEMPLATE_NIF)
            if i is not None:
                return arc.read(i)
    return None


def terrain(a, state):
    import make_skyrim_overlay as sk
    from fo4sf import skyrimland
    land = skyrimland.SkyrimLand(os.path.join(a.skyrim_data, "Skyrim.esm"))
    state["land"] = land
    s = land.summary()
    arrival = land.cell_by_edid(a.around) if not re.fullmatch(r"-?\d+,-?\d+", a.around) else \
        tuple(int(v) for v in a.around.split(","))
    state["arrival"] = arrival
    seams = land.seams()
    return {"extent": s["extent"], "extent_m": s["extent_m"], "cells_with_land": s["cells_with_vhgt"],
            "holes": s["holes"], "heights_m": [round(v, 1) for v in s["heights_m"]],
            "default_land_units": s["default_land_units"], "default_water_units": s["default_water_units"],
            "seam_max_units": seams["max_abs"], "overlay_cells": sk.single_tile_n(land.extent),
            "arrival": {"name": a.around, "cell": list(arrival) if arrival else None},
            "similar_names": [e for e, _ in land.find_cells(re.escape(a.around[:5]))][:8] if arrival is None else []}


def archives(a, state):
    from fo4sf import bsa
    src = bsa.SkyrimArchives(a.skyrim_data)
    state["src"] = src
    out = {"archives": [{"file": os.path.basename(x.path), "version": x.version, "files": len(x.names)}
                        for x in src.archives]}
    meshes = [n for x in src.archives for n in x.names if n.endswith(".nif")]
    # only textures\ .dds: other archives hold .dds too (interface, ...) that the texture lookup never asks for
    texs = [n for x in src.archives for n in x.names if n.endswith(".dds") and n.startswith("textures\\")]
    out["meshes"], out["textures"] = len(set(meshes)), len(set(texs))
    out["dds_outside_textures"] = sum(1 for x in src.archives for n in x.names
                                      if n.endswith(".dds") and not n.startswith("textures\\"))
    if meshes:
        m = src.mesh(meshes[0])
        out["mesh_read"] = {"name": meshes[0], "bytes": len(m) if m is not None else None}
    if texs:
        t = src.texture(texs[0])
        out["texture_read"] = {"name": texs[0], "bytes": len(t) if t is not None else None,
                               "magic": t[:4].decode("latin-1") if t is not None else None}
        if t is None:
            raise RuntimeError(f"texture listed in an archive could not be read back: {texs[0]}")
    return out


def objects(a, state):
    from fo4sf import exterior, skyrimrefs
    exp = skyrimrefs.export_world(os.path.join(a.skyrim_data, "Skyrim.esm"))
    state["export"] = exp
    types, actions = {}, {}
    for r in exp["refs"]:
        bump(types, r["type"])
        act, code, _ = exterior.classify(r, skyrimrefs.CONVERT_TYPES)
        bump(actions, "convert" if act == "convert" else code)
    models = {exterior.source_key(r["model"]) for r in exp["refs"]
              if exterior.classify(r, skyrimrefs.CONVERT_TYPES)[0] == "convert"}
    state["models"] = models
    return {"references": len(exp["refs"]), "deferred": len(exp["deferred_refs"]), "types": top(types, 16),
            "actions": actions, "distinct_models_to_convert": len(models),
            "disabled": sum(1 for r in exp["refs"] if r["disabled"]),
            "persistent": sum(1 for r in exp["refs"] if r["persistent"])}


def survey(a, state):
    from fo4sf import nif, skyrimnif
    src = state["src"]
    names = sorted(state["models"])
    if len(names) > a.survey:                        # spread over the whole sorted list, not one folder
        step = len(names) / a.survey
        names = [names[int(i * step)] for i in range(a.survey)]
    res = {"models": len(names), "missing": 0, "parse_failed": 0, "no_geometry": 0, "with_collision": 0,
           "collision_overlaps_render": 0, "collision_misplaced": 0, "misplaced_fixed_by": {},
           "misplaced_body_classes": {}, "misplaced_all": [], "parse_failed_all": [], "missing_all": [], "double_sided_shapes": 0,
           "double_sided_too_big": 0, "models_with_double_sided": 0}
    blocks, geom, errors, unsupported, bs_versions = {}, {}, {}, {}, {}
    misplaced = []
    for name in names:
        raw = src.mesh(name)
        if raw is None:
            res["missing"] += 1
            res["missing_all"].append(name)
            continue
        try:
            n = nif.parse(raw)
            bump(bs_versions, n.bs_version)
            for i in range(len(n.blocks)):
                t = n.type_of(i)
                if t.startswith("bhk") or t.startswith("hk") or "TriShape" in t or "TriStrips" in t:
                    bump(blocks, t)
            shapes = skyrimnif.trishapes(n)
            if not shapes:
                res["no_geometry"] += 1
                continue
            for s in shapes:
                bump(geom, n.type_of(s.block))
            two = [s for s in shapes if skyrimnif.double_sided(n, s.shader_ref)]
            res["double_sided_shapes"] += len(two)
            res["double_sided_too_big"] += sum(1 for s in two if 2 * len(s.positions) > 0xFFFF)
            res["models_with_double_sided"] += bool(two)
            rep = {}
            pts, tris = skyrimnif.collision_triangles(n, rep)
            for u in rep.get("unsupported", []):
                bump(unsupported, u)
            if tris:
                res["with_collision"] += 1
                rp = []
                for s in shapes:
                    r = s.rotation
                    for x, y, z in s.positions:
                        rp.append(tuple(s.scale * (r[3 * k] * x + r[3 * k + 1] * y + r[3 * k + 2] * z) + s.translation[k]
                                        for k in range(3)))
                lo = [min(p[k] for p in rp) for k in range(3)]
                hi = [max(p[k] for p in rp) for k in range(3)]
                clo = [min(p[k] for p in pts) for k in range(3)]
                chi = [max(p[k] for p in pts) for k in range(3)]
                size = max(hi[k] - lo[k] for k in range(3)) or 1.0

                def overlaps(p):
                    a = [min(q[k] for q in p) for k in range(3)]
                    b = [max(q[k] for q in p) for k in range(3)]
                    return all(a[k] <= hi[k] + 0.25 * size and b[k] >= lo[k] - 0.25 * size for k in range(3))
                if overlaps(pts):
                    res["collision_overlaps_render"] += 1
                else:
                    res["collision_misplaced"] += 1
                    # which body-transform rule would put this collision on the visible model?
                    fixes = []
                    for mode in skyrimnif.BODY_TRANSFORM_MODES:
                        if mode == skyrimnif.BODY_TRANSFORM_DEFAULT:
                            continue
                        alt, _t = skyrimnif.collision_triangles(n, None, body_transform=mode)
                        if alt and overlaps(alt):
                            fixes.append(mode)
                            bump(res["misplaced_fixed_by"], mode)
                    if not fixes:
                        bump(res["misplaced_fixed_by"], "nothing")
                    for b in rep.get("body_list", []):
                        bump(res["misplaced_body_classes"], f"{b['class']} layer {b['layer']}")
                    res["misplaced_all"].append(name)
                    if len(misplaced) < 15:
                        misplaced.append({"model": name, "render": [lo, hi], "collision": [clo, chi],
                                          "fixed_by": fixes, "bodies": rep.get("body_list", [])[:4]})
        except Exception as e:                       # noqa: BLE001
            res["parse_failed"] += 1
            res["parse_failed_all"].append(name)
            key = re.sub(r"\d+", "#", f"{type(e).__name__}: {e}")[:90]
            if key not in errors:
                errors[key] = {"count": 0, "example": name}
            errors[key]["count"] += 1
    res.update(nif_bs_versions=bs_versions, geometry_blocks=top(geom), havok_and_geometry_block_types=top(blocks, 30),
               unsupported_collision=top(unsupported),
               parse_errors=dict(sorted(errors.items(), key=lambda kv: -kv[1]["count"])[:12]),
               misplaced_examples=misplaced)
    return res


def armor(a, state):
    """Armor inventory (ARMO / ARMA) and a read-only parse of up to --armor-survey worn meshes with the skin reader."""
    from fo4sf import nif, skyrimarmor, skyrimskin
    inv = skyrimarmor.read_armor(os.path.join(a.skyrim_data, "Skyrim.esm"))
    out = {"inventory": skyrimarmor.summary(inv)}
    src = state["src"]
    worn = sorted({w for m in inv["arma"].values() for w in skyrimarmor.worn_models(m)})
    if len(worn) > a.armor_survey:
        step = len(worn) / a.armor_survey
        worn = [worn[int(i * step)] for i in range(a.armor_survey)]
    res = {"meshes": len(worn), "missing": 0, "parse_failed": 0, "no_skin": 0, "skinned_shapes": 0,
           "weight_sources": {}, "max_bones_per_shape": 0, "shapes_over_80_bones": 0, "unweighted_vertices": 0,
           "out_of_range_triangles": 0, "body_parts": {}}
    bones, errors = {}, {}
    for name in worn:
        raw = src.mesh(name)
        if raw is None:
            res["missing"] += 1
            continue
        try:
            shapes = skyrimskin.skinned_shapes(nif.parse(raw))
        except Exception as e:                       # noqa: BLE001
            res["parse_failed"] += 1
            key = re.sub(r"\d+", "#", f"{type(e).__name__}: {e}")[:90]
            errors.setdefault(key, {"count": 0, "example": name})["count"] += 1
            continue
        if not shapes:
            res["no_skin"] += 1
        for sh in shapes:
            c = skyrimskin.check(sh)
            res["skinned_shapes"] += 1
            bump(res["weight_sources"], c["weight_source"])
            res["max_bones_per_shape"] = max(res["max_bones_per_shape"], c["bones"])
            res["shapes_over_80_bones"] += c["bones"] > 80
            res["unweighted_vertices"] += c["unweighted_vertices"]
            res["out_of_range_triangles"] += c["out_of_range_triangles"]
            for bp in c["body_parts"]:
                bump(res["body_parts"], bp)
            for b in sh.bones:
                bump(bones, b.decode("latin-1"))
    res["bone_names"] = dict(sorted(bones.items(), key=lambda kv: -kv[1]))
    res["parse_errors"] = dict(sorted(errors.items(), key=lambda kv: -kv[1]["count"])[:12])
    out["survey"] = res
    return out


def sample(a, state):
    from fo4sf import convert_static, exterior, skyrimconvert, skyrimrefs
    arrival = state.get("arrival") or (0, 0)
    near = [r for r in state["export"]["refs"]
            if abs(r["exterior_cell"][0] - arrival[0]) <= a.radius and abs(r["exterior_cell"][1] - arrival[1]) <= a.radius
            and exterior.classify(r, skyrimrefs.CONVERT_TYPES)[0] == "convert"]
    by_kind = {}
    for r in near:                                   # a spread: landscape, architecture, clutter, ...
        key = exterior.source_key(r["model"])
        kind = key.split("\\")[1] if key.count("\\") > 1 else "other"
        by_kind.setdefault(kind, [])
        if key not in by_kind[kind]:
            by_kind[kind].append(key)
    picked = []
    while len(picked) < a.sample and any(by_kind.values()):
        for kind in sorted(by_kind):
            if by_kind[kind] and len(picked) < a.sample:
                picked.append(by_kind[kind].pop(0))
    template = convert_static.collision_template_from_nif(box_template(a))
    staging = os.path.join(a.work, "sample_convert")
    shutil.rmtree(staging, ignore_errors=True)
    conv = skyrimconvert.SkyrimConverter(state["src"], staging, a.texconv,
                                         os.path.join(a.starfield, "Tools", "ContentResources.zip"), template)
    results, methods = [], {}
    for name in picked:
        t0 = time.time()
        r = conv.convert_nif(name)
        c = r.get("collision_report") or {}
        bump(methods, c.get("method") or c.get("source") or ("failed" if not r["ok"] else "none"))
        results.append({"model": name, "ok": r["ok"], "reason": r.get("reason"), "shapes": r.get("shapes"),
                        "fallback_materials": r.get("fallback_materials"),
                        "skipped_effect_shapes": r.get("skipped_effect_shapes"),
                        "double_sided_shapes": r.get("double_sided_shapes"),
                        "collision": {k: c[k] for k in ("source", "method", "boxes", "column_cell_m",
                                                        "collision_overlaps_render", "unsupported") if k in c},
                        "seconds": round(time.time() - t0, 1)})
    return {"arrival_cell": list(arrival), "candidates_near": len(near), "converted": sum(r["ok"] for r in results),
            "failed": sum(not r["ok"] for r in results), "collision_methods": methods,
            "material_fallbacks": dict(list(conv.material_errors.items())[:10]),
            "materials_ok": conv.stats["materials_ok"], "results": results, "staging": staging}


# ---------------------------------------------------------------------------------------------------------- report
def summary(run) -> str:
    s = run.steps
    L = ["Skyrim2Starfield first run", "=" * 26]
    for name in ("setup", "terrain", "archives", "objects", "survey", "armor", "sample"):
        st = s.get(name)
        if st is None:
            L.append(f"{name}: not run")
            continue
        L.append(f"{name}: {'ok' if st['ok'] else 'FAIL ' + st['error']} ({st['seconds']} s)")
    st = s.get("setup", {})
    if st.get("problems"):
        L.append("  setup problems: " + "; ".join(st["problems"]))
    t = s.get("terrain", {})
    if t.get("ok"):
        L.append(f"  terrain: extent {t['extent']}, {t['cells_with_land']} cells, {t['holes']} holes, heights "
                 f"{t['heights_m']} m, overlay {t['overlay_cells']} cells, seams max {t['seam_max_units']} units, "
                 f"arrival {t['arrival']}" + (f", similar {t['similar_names']}" if t["similar_names"] else ""))
    ar = s.get("archives", {})
    if ar.get("ok"):
        L.append(f"  archives: {len(ar['archives'])} BSA ({', '.join(str(x['version']) for x in ar['archives'][:3])}...), "
                 f"{ar['meshes']} meshes, {ar['textures']} textures, texture read {ar.get('texture_read')}")
    o = s.get("objects", {})
    if o.get("ok"):
        L.append(f"  objects: {o['references']} refs + {o['deferred']} deferred; {o['distinct_models_to_convert']} "
                 f"models to convert; actions {o['actions']}")
        L.append(f"  types: {o['types']}")
    v = s.get("survey", {})
    if v.get("ok"):
        L.append(f"  survey: {v['models']} models, missing {v['missing']}, parse failed {v['parse_failed']}, no geometry "
                 f"{v['no_geometry']}, with collision {v['with_collision']} (overlap {v['collision_overlaps_render']}, "
                 f"MISPLACED {v['collision_misplaced']})")
        L.append(f"  NIF BS versions {v['nif_bs_versions']}; geometry {v['geometry_blocks']}")
        L.append(f"  havok/geometry blocks {v['havok_and_geometry_block_types']}")
        L.append(f"  unsupported collision (incl. non-unit body rotations) {v['unsupported_collision']}")
        L.append(f"  double-sided shapes {v.get('double_sided_shapes', 0)} in {v.get('models_with_double_sided', 0)} "
                 f"models (too big to double: {v.get('double_sided_too_big', 0)})")
        for k, e in v["parse_errors"].items():
            L.append(f"  parse error x{e['count']}: {k} (e.g. {e['example']})")
        L.append(f"  misplaced collision fixed by body-transform rule: {v.get('misplaced_fixed_by')}; bodies "
                 f"{dict(sorted(v.get('misplaced_body_classes', {}).items(), key=lambda kv: -kv[1])[:8])}")
        for m in v["misplaced_examples"][:5]:
            L.append(f"  misplaced: {m['model']} render {fmt(m['render'])} collision {fmt(m['collision'])} "
                     f"fixed by {m.get('fixed_by')}")
    ar = s.get("armor", {})
    if ar.get("ok"):
        i, v = ar["inventory"], ar["survey"]
        L.append(f"  armor: {i['armo_playable']} playable ARMO ({i['armor_types']}), {i['arma']} ARMA, {i['worn_meshes']} "
                 f"worn meshes ({i['arma_weight_slider']} ARMA with weight slider), races {i['arma_races']}")
        L.append(f"  armor slots {i['slots']}")
        L.append(f"  worn-mesh survey: {v['meshes']} meshes, missing {v['missing']}, parse failed {v['parse_failed']}, "
                 f"no skin {v['no_skin']}, {v['skinned_shapes']} skinned shapes, weights from {v['weight_sources']}, "
                 f"max bones/shape {v['max_bones_per_shape']} (>80: {v['shapes_over_80_bones']}), unweighted vertices "
                 f"{v['unweighted_vertices']}, bad triangles {v['out_of_range_triangles']}")
        L.append(f"  body parts {v['body_parts']}")
        L.append(f"  bones used ({len(v['bone_names'])}): " + ", ".join(list(v["bone_names"])[:80]))
        for k, e in v["parse_errors"].items():
            L.append(f"  armor parse error x{e['count']}: {k} (e.g. {e['example']})")
    sm = s.get("sample", {})
    if sm.get("ok"):
        L.append(f"  sample: {sm['converted']} converted, {sm['failed']} failed near cell {sm['arrival_cell']}; "
                 f"collision {sm['collision_methods']}; materials ok {sm['materials_ok']}")
        for r in sm["results"]:
            L.append(f"    {'ok ' if r['ok'] else 'FAIL'} {r['model']}: " + (r["reason"] or
                     f"shapes {r['shapes']}, fallback mats {r['fallback_materials']}, {r['collision']}, {r['seconds']} s"))
        for k, e in list(sm["material_fallbacks"].items())[:5]:
            L.append(f"    material fallback {k}: {e}")
    for name, st in s.items():
        if not st["ok"]:
            L.append(f"--- {name} trace ---\n{st['trace']}")
    return "\n".join(L) + "\n"


def fmt(box):
    return "[" + ", ".join("(" + ", ".join(f"{c:.0f}" for c in v) + ")" for v in box) + "]"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True, help="Skyrim Special Edition Data folder")
    ap.add_argument("--starfield", required=True, help="Starfield install folder (has Data and Tools)")
    ap.add_argument("--texconv", required=True, help="texconv.exe (xEdit's Edit Scripts folder)")
    ap.add_argument("--work", required=True, help="output folder OUTSIDE the repo")
    ap.add_argument("--around", default="Riverwood", help="exterior cell EditorID or X,Y for the sample (default Riverwood)")
    ap.add_argument("--radius", type=int, default=2, help="sample: cells around --around")
    ap.add_argument("--survey", type=int, default=3000, help="models to parse in the read-only survey")
    ap.add_argument("--sample", type=int, default=20, help="models to really convert")
    ap.add_argument("--armor-survey", type=int, default=400, help="worn armor meshes to parse in the armor step")
    a = ap.parse_args(argv)
    if os.path.abspath(a.work).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--work must be outside the repository (it receives converted game data)")
    os.makedirs(a.work, exist_ok=True)
    run, state = Run(a.work), {}
    run.step("setup", lambda: setup(a))
    run.step("terrain", lambda: terrain(a, state))
    if run.step("archives", lambda: archives(a, state))["ok"] and run.step("objects", lambda: objects(a, state))["ok"]:
        run.step("survey", lambda: survey(a, state))
        run.step("armor", lambda: armor(a, state))
        if run.steps["setup"].get("box_template") and os.path.isfile(a.texconv):
            run.step("sample", lambda: sample(a, state))
    with open(os.path.join(a.work, "report.json"), "w", encoding="utf-8") as f:
        json.dump(run.steps, f, indent=1, default=str)
    text = summary(run)
    with open(os.path.join(a.work, "report.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print("\n" + text)
    print(f"Paste {os.path.join(a.work, 'report.txt')} back into the chat.")
    return 0 if all(st["ok"] for st in run.steps.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
