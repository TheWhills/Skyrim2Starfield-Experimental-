"""Skyrim's exterior objects on the Tamriel terrain overlay (docs/terrain/skyrim-objects.md): core64c's object path with
Skyrim as the source. Rocks, trees, ruins, buildings, bridges and clutter become Starfield statics at Skyrim
position / 70 on the SKY_Tamriel overlay built by make_skyrim_overlay.py.

    python scripts/terrain/make_skyrim_objects.py export  --skyrim <Skyrim.esm> --work <work> [--cells X0 X1 Y0 Y1]
    python scripts/terrain/make_skyrim_objects.py select  --work <work> --terrain <staged Tamriel overlay>
    python scripts/terrain/make_skyrim_objects.py convert --work <work> --skyrim-data <Skyrim SE Data>
           --content-resources <Starfield\\Tools\\ContentResources.zip> --texconv <texconv.exe>
           --starfield-data <Starfield Data> (or --collision-template <vanilla box NIF>) [--max-texture 1024] [--resume]
    python scripts/terrain/make_skyrim_objects.py stage   --work <work> --terrain <overlay> --out <dir> [--sf-esm <Starfield.esm>]
    python scripts/terrain/make_skyrim_objects.py check   --out <dir>

export   every placed reference of the worldspace (or a cell rectangle) -> <work>/export.json (schema v2, as FO4's).
select   exterior.classify each reference (convert, or skip with a reason: lights, markers, effects, water, actors)
         -> selected.json, convert_input.json (one entry per model), selection.json (counts, skipped refs).
convert  every selected model through skyrimconvert.SkyrimConverter -> <work>/convert (meshes, geometries,
         materials, textures under the 'skyrim' prefix) + manifest.json; --resume reuses verified checkpoints.
stage    places the converted references (exterior.place) in the overlay's cells, hard-links the converted files and
         copies the overlay's own Data files (BTD, mask) into <out>/Data, writes objects.json, overlays_params.json
         (+ "objects"), the overlay's plan.json, skipped.json; with --sf-esm runs dotnet/TerrainOverlays.
check    every model / mesh / material / texture file present, references inside the BTD, each object's origin height
         against the terrain under it (the frame check), collision kinds, archive size estimate -> offline_check.json.
Everything this writes stays outside the repo (derived game data).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
from fo4sf import btd, exterior, skyrimrefs  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402

EDID_PREFIX = "SKY_"
ASSET_PREFIX = "skyrim"
# the identity-rotation plain-box prop the FO4 converter uses as its box template (docs/spikes/S6-collision.md)
BOX_TEMPLATE_NIF = "meshes/setdressing/historicaloilportraits/historicaloilportraits_shackleton.nif"
DATA_TREES = ("meshes", "geometries", "materials", "textures")
ARCHIVE_BUDGET = int(3.8 * 2 ** 30)       # one stored archive stays below 4 GiB (docs/terrain/core64c.md)


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save(path, value, indent=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=indent)
    os.replace(tmp, path)


def terrain_overlay(terrain):
    prm = load(os.path.join(terrain, "overlays_params.json"))
    if len(prm["overlays"]) != 1:
        sys.exit("the terrain folder must hold ONE overlay (make_skyrim_overlay.py build)")
    ov = prm["overlays"][0]
    if [float(v) for v in ov["origin_cw_m"]] != [0.0, 0.0]:
        sys.exit(f"overlay origin {ov['origin_cw_m']} != [0, 0]: objects use local = Skyrim position / 70")
    return prm, ov


# ---------------------------------------------------------------------------------------------------------- export
def cmd_export(a):
    t0 = time.time()
    exp = skyrimrefs.export_world(a.skyrim, a.world_edid, tuple(a.cells) if a.cells else None)
    save(os.path.join(a.work, "export.json"), exp)
    types = {}
    for r in exp["refs"]:
        types[r["type"]] = types.get(r["type"], 0) + 1
    print(f"{len(exp['refs']):,} references + {len(exp['deferred_refs']):,} deferred (actors, hazards) in "
          f"{exp['stats']['cells']:,} cells; {time.time() - t0:.1f} s")
    print("types: " + ", ".join(f"{k} {v:,}" for k, v in sorted(types.items(), key=lambda kv: -kv[1])))
    return 0


# ---------------------------------------------------------------------------------------------------------- select
def cmd_select(a):
    exp = load(os.path.join(a.work, "export.json"))
    _prm, ov = terrain_overlay(a.terrain)
    sub, skipped = exterior.select(exp, skyrimrefs.CONVERT_TYPES)
    cmin, cmax = ov["cell_min"], ov["cell_max"]
    by_model, outside = {}, 0
    for r in sub["refs"]:
        by_model.setdefault(exterior.source_key(r["model"]), {"model": r["model"], "type": r["type"],
                                                              "formkey": r["formkey"]})
        c = tg.sf_cell_of(r["pos"][0] / 70.0, r["pos"][1] / 70.0)
        outside += not (cmin <= c[0] <= cmax and cmin <= c[1] <= cmax)
    models = [by_model[k] for k in sorted(by_model)]
    save(os.path.join(a.work, "selected.json"), sub)
    save(os.path.join(a.work, "convert_input.json"), {"schema_version": 2, "cell": "skyrim_objects", "refs": models})
    rep = {"refs": len(exp["refs"]), "deferred": len(exp["deferred_refs"]), "to_convert": len(sub["refs"]),
           "models": len(models), "skipped": len(skipped), "skip_reasons": exterior.reason_counts(skipped),
           "outside_overlay": outside, "convert_types": list(skyrimrefs.CONVERT_TYPES), "skipped_refs": skipped}
    save(os.path.join(a.work, "selection.json"), rep)
    print(f"convert {rep['to_convert']:,} references ({rep['models']:,} models), skip {rep['skipped']:,}: "
          f"{rep['skip_reasons']}; outside the overlay {outside:,}")
    return 0


# ---------------------------------------------------------------------------------------------------------- convert
def editor_id(source, taken):
    stem = re.sub(r"[^A-Za-z0-9_]", "_", os.path.splitext(source.replace("\\", "/").rsplit("/", 1)[-1])[0])
    name = stem
    if name.lower() in taken:
        name = stem + "_" + hashlib.sha256(source.lower().encode()).hexdigest()[:10]
    taken.add(name.lower())
    return name


def box_template_nif(a) -> bytes:
    """The vanilla box-collision NIF: --collision-template, else read from the Starfield archives (--starfield-data)."""
    if a.collision_template:
        with open(a.collision_template, "rb") as f:
            return f.read()
    from fo4sf import ba2
    for fn in sorted(os.listdir(a.starfield_data)):
        if fn.lower().startswith("starfield - meshes") and fn.lower().endswith(".ba2"):
            arc = ba2.Ba2(os.path.join(a.starfield_data, fn))
            i = arc.find(BOX_TEMPLATE_NIF)
            if i is not None:
                return arc.read(i)
    sys.exit(f"{BOX_TEMPLATE_NIF} not found in {a.starfield_data}\\Starfield - Meshes*.ba2; pass --collision-template")


def checkpoint_signature(a):
    from fo4sf import checkpoints
    from pathlib import Path
    code = sorted(Path(REPO, "src", "fo4sf").glob("*.py")) + [Path(__file__)]
    archives = sorted(p for p in Path(a.skyrim_data).iterdir() if p.suffix.lower() == ".bsa")
    return {"version": 1, "kind": "skyrim", "archives": [checkpoints.archive_identity(p) for p in archives],
            "content": {str(p.resolve()): checkpoints.digest(p) for p in
                        [*code, Path(a.texconv), Path(a.content_resources)]},
            "box_template": hashlib.sha256(box_template_nif(a)).hexdigest(),
            "max_texture": a.max_texture or None}


def cmd_convert(a):
    from fo4sf import bsa, checkpoints, convert_static, skyrimconvert
    t0 = time.time()
    models = load(os.path.join(a.work, "convert_input.json"))["refs"]
    names = sorted({"meshes\\" + m["model"].replace("/", "\\").lstrip("\\") for m in models}, key=str.lower)
    staging = os.path.join(a.work, "convert")
    os.makedirs(staging, exist_ok=True)
    src = bsa.SkyrimArchives(a.skyrim_data)
    template = convert_static.collision_template_from_nif(box_template_nif(a))
    cache = checkpoints.Checkpoints(staging, checkpoint_signature(a), prefix=ASSET_PREFIX) if a.resume else None
    ids_path = os.path.join(staging, "editorids.json")
    ids = load(ids_path) if os.path.exists(ids_path) else {}
    taken = {v.lower() for v in ids.values()}
    conv, items, failures, reused = None, [], [], 0
    print(f"{len(names):,} models; converting up to {a.limit:,}")
    for k, name in enumerate(names[:a.limit]):
        r = cache.load(name) if cache else None
        if r is not None:
            reused += 1
        else:
            if conv is None:
                conv = skyrimconvert.SkyrimConverter(src, staging, a.texconv, a.content_resources, template,
                                                     prefix=ASSET_PREFIX, max_texture=a.max_texture)
            r = conv.convert_nif(name)
            if cache:
                try:
                    cache.save(name, r)
                except (OSError, ValueError) as e:
                    print(f"  checkpoint unavailable for {name}: {e}")
        if not r["ok"]:
            failures.append({"nif": name, "reason": r["reason"]})
            continue
        key = name.lower()
        if key not in ids:
            ids[key] = editor_id(name, taken)
        items.append({"editor_id": ids[key], "model": r["out_name"].replace("/", "\\") + ".nif", "source": name,
                      "shapes": r["shapes"], "fallback_materials": r["fallback_materials"],
                      "collision_report": r.get("collision_report") or {}})
        if (k + 1) % 200 == 0:
            print(f"  {k + 1:,} / {min(len(names), a.limit):,} models, {len(failures):,} failed, "
                  f"{time.time() - t0:.0f} s")
            save(ids_path, ids)
    stats = dict(conv.stats) if conv else {"materials_ok": 0, "materials_fallback": 0}
    stats.update(assets=len(items), failed=len(failures), reused=reused)
    reasons = {}
    for f in failures:
        r = re.sub(r"\d+", "#", f["reason"])[:80]
        reasons[r] = reasons.get(r, 0) + 1
    coll = {}
    for i in items:
        c = i["collision_report"]
        k = c.get("method") if c.get("source") == "skyrim-boxes" else c.get("source", "none")
        coll[k] = coll.get(k, 0) + 1
    save(ids_path, ids)
    manifest = {"items": items, "failures": failures, "material_fallbacks": conv.material_errors if conv else {},
                "stats": stats, "collision": coll, "failure_reasons": reasons, "seconds": round(time.time() - t0, 1)}
    save(os.path.join(staging, "manifest.json"), manifest, indent=1)
    print(json.dumps({"converted": len(items), **stats, "collision": coll, "seconds": manifest["seconds"]}))
    for r, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  FAIL x{n}: {r}")
    return 0


# ---------------------------------------------------------------------------------------------------------- stage
def link_tree(src, dst):
    """Hard-link (copy across volumes) every file under src into dst; returns the number of files."""
    n = 0
    for root, _dirs, files in os.walk(src):
        for fn in files:
            s = os.path.join(root, fn)
            d = os.path.join(dst, os.path.relpath(s, src))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if os.path.exists(d):
                if os.path.getsize(d) == os.path.getsize(s) and os.path.samefile(s, d):
                    n += 1
                    continue
                os.remove(d)
            try:
                os.link(s, d)
            except OSError:
                shutil.copy2(s, d)
            n += 1
    return n


def collision_kind(item):
    c = item.get("collision_report") or {}
    if c.get("source") == "skyrim-boxes":
        return "skyrim-" + c.get("method", "boxes")
    return c.get("source") or "none"


def cmd_stage(a):
    t0 = time.time()
    prm, ov = terrain_overlay(a.terrain)
    sel = load(os.path.join(a.work, "selected.json"))
    selrep = load(os.path.join(a.work, "selection.json"))
    man = load(os.path.join(a.work, "convert", "manifest.json"))
    bases, placed, skipped_conv = exterior.place(sel, man, ov["cell_min"], ov["cell_max"], EDID_PREFIX)
    items = {i["source"].replace("/", "\\").lower(): i for i in man["items"]}
    for b in bases:
        b["collision"] = collision_kind(items[b["key"]])
    skipped = selrep["skipped_refs"] + skipped_conv
    total = selrep["refs"] + selrep["deferred"]
    if len(placed) + len(skipped) != total:          # selection's skipped list already holds the deferred actors
        sys.exit(f"accounting: {len(placed)} placed + {len(skipped)} skipped != {total} exported")
    terrain_ids = {e.lower() for e in (ov["world"], ov["block"], ov["location"], ov["anchor"]["edid"], ov["coc"],
                                       ov["coc"] + "Marker")}
    clash = sorted({b["edid"].lower() for b in bases} & terrain_ids)
    if clash:
        sys.exit(f"base EditorIDs clash with the overlay's records: {clash}")
    out = a.out
    os.makedirs(out, exist_ok=True)
    for root, _dirs, files in os.walk(os.path.join(a.terrain, "Data")):     # the overlay's own BTD, mask, copies
        for fn in files:
            s = os.path.join(root, fn)
            d = os.path.join(out, os.path.relpath(s, a.terrain))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
    for tree in DATA_TREES:
        n = link_tree(os.path.join(a.work, "convert", tree), os.path.join(out, "Data", tree))
        print(f"Data\\{tree}: {n:,} files")
    objects = {"world": ov["world"], "edid_prefix": EDID_PREFIX,
               "bases": [{k: b[k] for k in ("edid", "model", "source", "collision") if k in b} for b in bases],
               "refs": [{k: p[k] for k in ("src", "base", "cell", "pos", "rot", "scale", "disabled")} for p in placed]}
    save(os.path.join(out, "objects.json"), objects)
    save(os.path.join(out, "overlays_params.json"), dict(prm, objects="objects.json"), indent=1)
    save(os.path.join(out, "skipped.json"), {"counts": exterior.reason_counts(skipped), "refs": skipped})
    for name in ("plan.json", "expected.json", "README.txt", "preview.png", "skyrim_source.json"):
        if os.path.isfile(os.path.join(a.terrain, name)):
            shutil.copy2(os.path.join(a.terrain, name), os.path.join(out, name))
    print(f"{len(bases):,} bases, {len(placed):,} references placed, {len(skipped):,} skipped "
          f"({exterior.reason_counts(skipped)}); {time.time() - t0:.0f} s")
    if a.sf_esm:
        subprocess.run(["dotnet", "run", "--project", os.path.join(REPO, "dotnet", "TerrainOverlays"), "-c", "Release",
                        "--", a.sf_esm, out], check=True)
    else:
        print(f"next: dotnet run --project dotnet/TerrainOverlays -c Release -- <Starfield.esm> {out}")
    return 0


# ---------------------------------------------------------------------------------------------------------- check
def check(out):
    """Offline checks of a staged objects build; returns (ok, report)."""
    prm = load(os.path.join(out, "overlays_params.json"))
    ov = prm["overlays"][0]
    obj = load(os.path.join(out, "objects.json"))
    data = os.path.join(out, "Data")
    checks, missing = [], []

    def need(cond, what):
        checks.append((what, bool(cond)))

    need(obj["world"] == ov["world"], f"objects.json names the overlay world {ov['world']}")
    for b in obj["bases"]:
        p = os.path.join(data, "meshes", *b["model"].replace("\\", "/").split("/"))
        if not os.path.isfile(p):
            missing.append(b["model"])
    need(not missing, f"every base model exists ({len(obj['bases'])} bases; missing {missing[:5]})")
    # every material / geometry the converted NIFs name
    from fo4sf import nif, sfnif
    gone = set()
    for b in obj["bases"]:
        p = os.path.join(data, "meshes", *b["model"].replace("\\", "/").split("/"))
        if not os.path.isfile(p):
            continue
        with open(p, "rb") as f:
            m = nif.parse(f.read())
        for i, blk in enumerate(m.blocks):
            if m.type_of(i) == "BSGeometry":
                for ref in sfnif.parse_bsgeometry(blk).meshes:
                    if ref is not None:
                        g = os.path.join(data, "geometries", *ref.path.decode("latin-1").split("\\")) + ".mesh"
                        if not os.path.isfile(g):
                            gone.add(g)
        for s in m.strings:
            t = s.decode("latin-1")
            if t.lower().endswith(".mat") and not os.path.isfile(os.path.join(data, *t.replace("\\", "/").split("/"))):
                gone.add(t)
    need(not gone, f"every geometry and material file a model names exists (missing {sorted(gone)[:5]})")
    texmiss = set()
    for root, _d, files in os.walk(os.path.join(data, "materials")):
        for fn in files:
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                for t in re.findall(r'"(Data\\\\[^"]+?\.(?:dds|DDS))"', f.read()):
                    rel = t.replace("\\\\", "/")[5:]
                    if rel.lower().startswith(f"textures/{ASSET_PREFIX}/") and \
                            not os.path.isfile(os.path.join(data, *rel.split("/"))):
                        texmiss.add(rel)
    need(not texmiss, f"every converted texture a material names exists (missing {sorted(texmiss)[:5]})")
    cmin, cmax = ov["cell_min"], ov["cell_max"]
    inside = all(cmin <= r["cell"][0] <= cmax and cmin <= r["cell"][1] <= cmax for r in obj["refs"])
    need(inside, f"every reference lies in the BTD's cells {cmin}..{cmax}")
    # frame check: an object's origin against the terrain under it (rocks and trees sit on the ground in Skyrim)
    with open(os.path.join(out, *ov["btd_file"].split("/")), "rb") as f:
        t = btd.read(f.read())
    dz = []
    o = tg.grid_origin(t.ncx)
    for r in obj["refs"]:
        x, y, z = r["pos"]
        u = min(max((x - o) / tg.SF_STEP_M, 0.0), t.heights_raw.shape[1] - 1.001)
        v = min(max((y - o) / tg.SF_STEP_M, 0.0), t.heights_raw.shape[0] - 1.001)
        c, rr = int(u), int(v)
        fu, fv = u - c, v - rr
        h = t.heights_raw[rr:rr + 2, c:c + 2].astype(float) / 65535.0 * (t.hmax - t.hmin) + t.hmin
        g = h[0, 0] * (1 - fu) * (1 - fv) + h[0, 1] * fu * (1 - fv) + h[1, 0] * (1 - fu) * fv + h[1, 1] * fu * fv
        dz.append(z - g)
    dz.sort()
    q = (lambda f: round(dz[min(len(dz) - 1, int(f * len(dz)))], 3)) if dz else (lambda f: None)
    near = sum(1 for d in dz if abs(d) <= 3.0)
    frame = {"refs": len(dz), "median_m": q(0.5), "p05_m": q(0.05), "p95_m": q(0.95),
             "within_3m": near, "within_3m_share": round(near / len(dz), 3) if dz else None}
    need(not dz or abs(frame["median_m"]) <= 2.0,
         f"object origins sit on the terrain (median origin - ground {frame['median_m']} m)")
    kinds = {}
    for r in obj["refs"]:
        k = obj["bases"][r["base"]]["collision"]
        kinds[k] = kinds.get(k, 0) + 1
    size = 0
    for root, _d, files in os.walk(data):
        size += sum(os.path.getsize(os.path.join(root, fn)) for fn in files)
    need(size <= ARCHIVE_BUDGET, f"Data tree {size / 2 ** 30:.2f} GiB fits one stored archive (< 3.8 GiB)")
    rep = {"checks": checks, "frame": frame, "collision_refs": kinds, "bases": len(obj["bases"]),
           "refs": len(obj["refs"]), "initially_disabled": sum(1 for r in obj["refs"] if r["disabled"]),
           "data_bytes": size}
    return all(c[1] for c in checks), rep


def cmd_check(a):
    ok, rep = check(a.out)
    for what, good in rep["checks"]:
        print(("  ok   " if good else "  FAIL ") + what)
    print(json.dumps({k: v for k, v in rep.items() if k != "checks"}, indent=1))
    save(os.path.join(a.out, "offline_check.json"), rep, indent=1)
    print("CHECK", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("export", "select", "convert", "stage", "check"))
    ap.add_argument("--skyrim", help="export: Skyrim.esm")
    ap.add_argument("--world-edid", default="Tamriel")
    ap.add_argument("--cells", type=int, nargs=4, metavar=("X0", "X1", "Y0", "Y1"),
                    help="export: only this inclusive Skyrim cell rectangle (e.g. a first test around Riverwood)")
    ap.add_argument("--work", help="work folder outside the repo (export, selection, conversion)")
    ap.add_argument("--terrain", help="the staged Tamriel overlay (make_skyrim_overlay.py build --out)")
    ap.add_argument("--out", help="stage / check: output folder outside the repo")
    ap.add_argument("--sf-esm", default="", help="stage: Starfield.esm, to build the plugins with dotnet/TerrainOverlays")
    ap.add_argument("--skyrim-data", help="convert: Skyrim Special Edition Data folder (BSA archives, loose files)")
    ap.add_argument("--content-resources", help="convert: Starfield Tools\\ContentResources.zip (material templates)")
    ap.add_argument("--texconv", help="convert: texconv.exe")
    ap.add_argument("--collision-template", help="convert: a vanilla Starfield NIF with one box body (as convert_batch)")
    ap.add_argument("--starfield-data", help="convert: Starfield Data folder, to read the box template from its archives "
                                             "instead of --collision-template")
    ap.add_argument("--max-texture", default="", help="convert: texture caps, e.g. 1024 or color=1024,normal=512")
    ap.add_argument("--limit", type=int, default=10 ** 9)
    ap.add_argument("--resume", action="store_true", help="convert: reuse verified per-model checkpoints")
    a = ap.parse_args(argv)
    need = {"export": ("skyrim", "work"), "select": ("work", "terrain"),
            "convert": ("work", "skyrim_data", "content_resources", "texconv"),
            "stage": ("work", "terrain", "out"), "check": ("out",)}[a.cmd]
    missing = [f"--{k.replace('_', '-')}" for k in need if not getattr(a, k)]
    if a.cmd == "convert" and not (a.collision_template or a.starfield_data):
        missing.append("--collision-template or --starfield-data")
    if missing:
        sys.exit(f"{a.cmd} needs {' '.join(missing)}")
    return {"export": cmd_export, "select": cmd_select, "convert": cmd_convert, "stage": cmd_stage,
            "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
