"""Skyrim's exterior objects on the Tamriel terrain overlay (docs/terrain/skyrim-objects.md): core64c's object path with
Skyrim as the source. Rocks, trees, ruins, buildings, bridges and clutter become Starfield statics at Skyrim
position / 70 on the SKY_Tamriel overlay built by make_skyrim_overlay.py.

    python scripts/terrain/make_skyrim_objects.py export  --skyrim <Skyrim.esm> --work <work> [--cells X0 X1 Y0 Y1]
    python scripts/terrain/make_skyrim_objects.py select  --work <work> --terrain <staged Tamriel overlay>
    python scripts/terrain/make_skyrim_objects.py convert --work <work> --skyrim-data <Skyrim SE Data>
           --content-resources <Starfield\\Tools\\ContentResources.zip> --texconv <texconv.exe>
           --starfield-data <Starfield Data> (or --collision-template <vanilla box NIF>) [--max-texture 1024] [--resume]
    python scripts/terrain/make_skyrim_objects.py grass   --work <work> --terrain <overlay> --skyrim <Skyrim.esm>
           --skyrim-data <Skyrim SE Data> --content-resources <zip> --texconv <texconv.exe> [--around Riverwood --radius 2]
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
grass    Skyrim's grass (LTEX GNAM -> GRAS) scattered once around --around (default Riverwood, --radius cells) and
         merged per cell and model into patch statics -> <work>/grass (src/fo4sf/skyrimgrass.py); stage adds them.
lod      after stage: distant-object LOD (composite NIFs per object and block, lodsettings) for large statics into
         <out>/Data in vanilla Starfield's layout (src/fo4sf/skyrimlod.py); --sf-esm rebuilds the plugins.
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
import struct
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
    return prm, prm["overlays"][0]


def to_local(refs, ov):
    """Copies of the references with positions in the overlay's own frame: local = Skyrim position - the overlay's
    origin (origin_cw_m, whole 100 m cells; [0, 0] for Tamriel with --frame skyrim, the city's centre for --frame local).
    Heights are lifted by the overlay's height_offset_m (make_skyrim_overlay.py --height-offset; 0 by default), the
    same amount the terrain was."""
    ox, oy = (float(v) * 70.0 for v in ov["origin_cw_m"])
    oz = float(ov.get("height_offset_m") or 0.0) * 70.0
    if ox == 0.0 and oy == 0.0 and oz == 0.0:
        return refs
    return [dict(r, pos=[r["pos"][0] - ox, r["pos"][1] - oy, r["pos"][2] + oz]) for r in refs]


# ---------------------------------------------------------------------------------------------------------- export
def around_cells(esm, around, radius):
    """(X0, X1, Y0, Y1): the Skyrim cells within `radius` of an exterior cell EditorID ("Riverwood") or "X,Y"."""
    if re.fullmatch(r"-?\d+,-?\d+", around):
        x, y = (int(v) for v in around.split(","))
    else:
        from fo4sf import skyrimland
        land = skyrimland.SkyrimLand(esm)
        c = land.cell_by_edid(around)
        if c is None:
            similar = [e for e, _ in land.find_cells(re.escape(around[:5]))][:8]
            sys.exit(f"no exterior cell {around!r} in {esm}" + (f"; similar: {similar}" if similar else ""))
        x, y = c
    return x - radius, x + radius, y - radius, y + radius


def cmd_export(a):
    t0 = time.time()
    cells = tuple(a.cells) if a.cells else None
    if a.around:
        if cells:
            sys.exit("pass --cells or --around, not both")
        cells = around_cells(a.skyrim, a.around, a.radius)
        print(f"{a.around}: cells x {cells[0]}..{cells[1]}, y {cells[2]}..{cells[3]}")
    exp = skyrimrefs.export_world(a.skyrim, a.world_edid, cells)
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
    for r in to_local(sub["refs"], ov):
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


# ---------------------------------------------------------------------------------------------------------- grass
def cmd_grass(a):
    """Skyrim's grass around --around (src/fo4sf/skyrimgrass.py) -> <work>/grass: per-cell merged patch models
    (meshes, geometries, materials, textures) + grass.json (bases and references in stage's final form)."""
    import numpy as np
    from fo4sf import bsa, landtex, skyrimconvert, skyrimgrass, skyrimland, skyrimnif
    from fo4sf import nif as nifmod
    t0 = time.time()
    _prm, ov = terrain_overlay(a.terrain)
    x0, x1, y0, y1 = (tuple(a.cells) if a.cells else around_cells(a.skyrim, a.around or "Riverwood", a.radius))
    print(f"grass: Skyrim cells x {x0}..{x1}, y {y0}..{y1}; spacing {a.grass_spacing:g} m, density x{a.grass_density:g}")
    ltex_grass, gras = skyrimgrass.read_grass(a.skyrim)
    land = skyrimland.SkyrimLand(a.skyrim, a.world_edid)
    colours = {}
    weights, _ltex = landtex.read_world_textures(a.skyrim, land.land_source, colours)
    print(f"grass: {len(gras)} GRAS records, {len(ltex_grass)} landscape textures with grass")
    rng = np.random.default_rng(a.seed)
    spacing = a.grass_spacing * 70.0
    out = os.path.join(a.work, "grass")
    if os.path.isdir(out):                            # a fresh scatter: no patches of an earlier run left behind
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)
    # pass 1: scatter every cell; per model the mean Skyrim vertex colour (LAND VCLR) under its instances, which
    # Skyrim multiplies into grass the way it does into the ground (src/fo4sf/skyrimgrass.py)
    cells_inst, tint_acc, why, used_g = {}, {}, {}, set()
    for cy in range(y0, y1 + 1):
        for cx in range(x0, x1 + 1):
            ws, hg = weights.get((cx, cy)), land.grids.get((cx, cy))
            if not ws or hg is None:
                continue
            inst = skyrimgrass.scatter(ws, hg, ltex_grass, gras, spacing, rng, a.grass_density, land.water.get((cx, cy)),
                                       why)
            used_g.update(g for g, *_r in inst)
            vc = colours.get((cx, cy))
            by_model = {}
            for g, x, y, z, yaw, sc in inst:
                m = gras[g]["model"]
                by_model.setdefault(m, []).append((cx * skyrimgrass.CELL + x, cy * skyrimgrass.CELL + y, z, yaw, sc))
                if vc is not None and a.grass_tint == "vertex":
                    acc = tint_acc.setdefault(m, [0.0, 0.0, 0.0, 0])
                    c = skyrimgrass.vertex_colour(vc, x, y)
                    acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]; acc[3] += 1
            if by_model:
                cells_inst[(cx, cy)] = by_model
    tints = {m: (v[0] / v[3], v[1] / v[3], v[2] / v[3]) for m, v in tint_acc.items() if v[3]}
    print(f"grass: candidates {sum(why.values()):,}: " + ", ".join(f"{k} {v:,}" for k, v in
                                                                 sorted(why.items(), key=lambda kv: -kv[1])))
    painted = {g for f in weights.get(((x0 + x1) // 2, (y0 + y1) // 2), {}) for g in ltex_grass.get(f, [])}
    for g in sorted(used_g | painted, key=lambda g: gras[g]["edid"] if g in gras else ""):
        if g in gras:
            r = gras[g]
            print(f"  GRAS {r['edid']:24} density {r['density']:3} slope {r['min_slope']}-{r['max_slope']} "
                  f"from water {r['units_from_water']} (rule {r['water_rule']}) pos range {r['position_range']:g} "
                  f"height range {r['height_range']:g}  {r['model']}")
    print(f"grass: scattered {sum(len(p) for bm in cells_inst.values() for p in bm.values()):,} instances in "
          f"{time.time() - t0:.0f} s")
    conv = skyrimconvert.SkyrimConverter(bsa.SkyrimArchives(a.skyrim_data), out, a.texconv, a.content_resources, None,
                                         prefix=ASSET_PREFIX, max_texture=a.max_texture)
    models, failed = {}, {}

    def model(name, tint):
        if name in models or name in failed:
            return models.get(name)
        try:
            raw = conv.src.mesh(name)
            if raw is None:
                raise FileNotFoundError("not in the Skyrim archives")
            src = nifmod.parse(raw)
            shapes = skyrimnif.trishapes(src)
            mats = [conv._shape_material(src, sh, flat_normal_ok=True, albedo_tint=tint)   # grass: often no normal
                    for sh in shapes]
            keep = []
            for sh, m in zip(shapes, mats):
                if m is None:
                    continue
                if skyrimnif.double_sided(src, sh.shader_ref):
                    sh = skyrimconvert.with_back_faces(sh) or sh
                keep.append((sh, m))
            if not keep:
                raise ValueError("no drawable shape")
            models[name] = (src, keep)
        except Exception as e:                       # noqa: BLE001  (reported; that grass is left out)
            failed[name] = f"{type(e).__name__}: {e}"
        return models.get(name)

    bases, refs, counts = [], [], {}
    total = 0
    oz = float(ov.get("height_offset_m") or 0.0)
    for (cx, cy), by_model in sorted(cells_inst.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if cx == x0:
            print(f"  row y {cy}: {total:,} instances built, {time.time() - t0:.0f} s")
        if True:
            for mname, pts in sorted(by_model.items()):
                full = "meshes\\" + mname.replace("/", "\\").lstrip("\\")
                mdl = model(full, tints.get(mname))
                if mdl is None:
                    continue
                src, keep = mdl
                origin = ((cx + 0.5) * skyrimgrass.CELL, (cy + 0.5) * skyrimgrass.CELL, min(p[2] for p in pts))
                merged = skyrimgrass.instance_shapes([k[0] for k in keep], pts, origin, skyrimconvert.MAX_VERTICES)
                if not merged:
                    continue
                stem = skyrimgrass.patch_stem(cx, cy, mname)
                out_name = f"{ASSET_PREFIX}/grass/{stem}"
                files = skyrimconvert.convert_static_sse(src, [m for _i, m in merged], out_name,
                                                         [keep[i][1] for i, _m in merged], None, {})
                for relp, data in files.items():
                    pth = os.path.join(out, *relp.split("/"))
                    os.makedirs(os.path.dirname(pth), exist_ok=True)
                    with open(pth, "wb") as f:
                        f.write(data)
                pos = [origin[0] / 70.0 - float(ov["origin_cw_m"][0]), origin[1] / 70.0 - float(ov["origin_cw_m"][1]),
                       origin[2] / 70.0 + oz]
                cell = tg.sf_cell_of(pos[0], pos[1])
                if not (ov["cell_min"] <= cell[0] <= ov["cell_max"] and ov["cell_min"] <= cell[1] <= ov["cell_max"]):
                    continue
                edid = (EDID_PREFIX + "Grass_" + re.sub(r"[^A-Za-z0-9_]", "_", stem))[:200]
                bases.append({"edid": edid, "model": out_name.replace("/", "\\") + ".nif", "source": full,
                              "collision": "none"})
                refs.append({"src": f"grass:{cx},{cy}:{stem}", "base": len(bases) - 1, "cell": list(cell),
                             "pos": [round(v, 5) for v in pos], "rot": [0.0, 0.0, 0.0], "scale": 1.0,
                             "disabled": False})
                counts[mname] = counts.get(mname, 0) + len(pts)
                total += len(pts)
    for m, t in sorted(tints.items(), key=lambda kv: -counts.get(kv[0], 0))[:5]:
        print(f"  tint {', '.join(f'{v:.2f}' for v in t)}  {m}")
    save(os.path.join(out, "grass.json"), {"bases": bases, "refs": refs, "instances": counts, "failed": failed,
                                           "tints": tints,
                                           "cells": [x0, x1, y0, y1], "spacing_m": a.grass_spacing,
                                           "density": a.grass_density})
    print(f"grass: {total:,} instances of {len(counts)} models in {len(refs):,} patches; "
          f"{len(failed)} models failed; {time.time() - t0:.0f} s")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {v:7,}  {k}")
    for k, v in list(failed.items())[:5]:
        print(f"  FAILED {k}: {v}")
    return 0


def add_cell_index(out, sf_esm, env_from=""):
    """The WRLD cell index (OFST / CLSZ) that the Creation Kit writes and Mutagen does not, added to the plugin
    TerrainOverlays just wrote (scripts/tools/world_offsets.py; layout verified on LC030World first). env_from: a
    vanilla world whose music / ambient set / environment maps (ZNAM, WAMB, XEMP, XWEM) are copied first: both NeonCity
    and NewAtlantis have them, ours had none (owner's compare_worlds run; the ocean-spot "underwater" coating)."""
    sys.path.insert(0, os.path.join(REPO, "scripts", "tools"))
    import world_offsets
    from fo4sf import fo4land
    prm = load(os.path.join(out, "overlays_params.json"))
    if env_from:
        with fo4land.Plugin(sf_esm) as p:
            env = world_offsets.world_fields(p.buf, p.body, env_from, world_offsets.ENV_FIELDS)
        print(f"world fields from {env_from}: " + ", ".join(f"{k.decode()}={v.rstrip(bytes(1)).decode('latin-1') if k in (b'XEMP', b'XWEM') else v.hex()}"
                                                          for k, v in env.items()))
        for ov in prm["overlays"]:
            world_offsets.set_fields(os.path.join(out, prm["plugin"]), ov["world"], env)
    with fo4land.Plugin(sf_esm) as p:
        reading = world_offsets.verify(p.buf, p.body, "LC030World", log=lambda *x: None)
    if not reading:
        print("cell index: no reading explains LC030World's OFST; not written")
        return
    for ov in prm["overlays"]:
        world_offsets.write(os.path.join(out, prm["plugin"]), ov["world"], reading)


# ---------------------------------------------------------------------------------------------------------- lod
def cmd_lod(a):
    """Distant-object LOD for a staged build (src/fo4sf/skyrimlod.py): composite LOD NIFs + lodsettings into
    <out>/Data, marks those bases distant_lod in objects.json, and with --sf-esm rebuilds the plugins."""
    from fo4sf import skyrimlod
    t0 = time.time()
    prm, ov = terrain_overlay(a.out)
    obj_path = os.path.join(a.out, "objects.json")
    objects = load(obj_path)
    data = os.path.join(a.out, "Data")
    distant_sea(a, objects, data, ov)
    river_meshes(a, prm, objects, data)
    if a.standalone_materials:                       # biome coating at the ocean spot (src/fo4sf/lodmatfix.py)
        from fo4sf import lodmatfix
        ms = lodmatfix.apply_standalone(data)
        print(f"materials: {ms['rebuilt']:,} of {ms['materials']:,} rebuilt standalone (nothing inherited from vanilla); "
              f"{ms['kept']:,} kept (cutouts, decals, glass, ground)" + (f", {ms['failed']} unreadable" if ms["failed"] else ""))
    if not a.metal_fix:
        pass                                         # owner, 2026-10-17: with it near rock and ground turned shiny too
    elif not a.texconv:
        print("materials: metalness fix skipped, needs --texconv")
    else:                                            # glossy, metal-looking object LOD (src/fo4sf/lodmatfix.py)
        from fo4sf import lodmatfix
        ms = lodmatfix.apply(data, a.texconv)
        print(f"materials: black metalness texture in {ms['patched']:,} of {ms['materials']:,} materials"
              + (f" ({ms['failed']} unreadable)" if ms["failed"] else ""))
    # composite LOD (vanilla city layout) is opt-in: it never drew for our world (docs "Distant-object LOD"); object
    # LOD (objectlod.py, the Creation Kit's -MockWorldSpaceLOD layout) is what works, written after the plugin build
    st = skyrimlod.build(objects, data, ov["world"], ov["cell_min"], ov["cell_max"], a.lod_min_radius,
                         layer=a.lod_layer or None, write=a.composite_lod or bool(a.vanilla_test))
    flagged = set(st["flag_bases"])
    # object bounds (STAT OBND) for every static: vanilla statics all have them; ours had none, and the owner's
    # Creation Kit then called all 19,494 of our large-reference entries "not a large ref" (zero-size objects)
    nb = 0
    for b in objects["bases"]:
        if b.get("door") or b.get("bounds"):
            continue
        try:
            bb = skyrimlod.model_bounds(data, b["model"])
        except (OSError, ValueError, struct.error):
            bb = None
        if bb:
            b["bounds"] = bb
            nb += 1
    print(f"lod: object bounds for {nb:,} statics")
    for i, b in enumerate(objects["bases"]):
        b.pop("distant_lod", None)
        b.pop("lod_layer", None)
        if i in flagged:
            b["distant_lod"] = True
            b["lod_layer"] = a.lod_layer or skyrimlod.layer_name(b["edid"])
    # large references (WRLD RNAM): every LOD reference, listed in each cell its bounds cover. Both worlds whose
    # composite LOD draws (NewAtlantis, ShatteredSpace's Dazra) have RNAM; the Mars template and ours had none
    # (owner's compare_worlds.py run).
    for r in objects["refs"]:
        r.pop("large_cells", None)
        r.pop("full_lod", None)
    if not a.no_large_refs:
        for ri, cells in st["large_refs"].items():
            objects["refs"][ri]["large_cells"] = cells
    # "Is Full LOD" (REFR record flag bit 16, 0x10000; xEdit wbDefinitionsSF1): the reference draws its full model at
    # any distance. What Starfield modders use for custom locations, where the Creation Kit's LOD layers produce
    # nothing (r/starfieldmods, Nexus forums); composite LOD never drew for our world. Same references as the LOD
    # ones (radius x scale >= --lod-min-radius), so only the big, far-visible objects pay for it.
    if a.full_lod:
        for ri in st["large_refs"]:
            objects["refs"][ri]["full_lod"] = True
        print(f"lod: {len(st['large_refs']):,} references flagged Is Full LOD")
    save(obj_path, objects)
    if a.vanilla_test:
        from fo4sf import ba2
        import glob as _g
        found = sorted(_g.glob(os.path.join(a.vanilla_test, "Starfield - *.ba2")))
        found.sort(key=lambda p: "lodmeshes" not in p.lower())           # the LOD archive first, then the rest
        arcs = {}

        def read(name):
            for p in found:
                if p not in arcs:
                    try:
                        arcs[p] = ba2.Ba2(p)
                    except Exception:                    # noqa: BLE001 (texture archives etc. we cannot index)
                        arcs[p] = None
                if arcs[p] is not None and arcs[p].find(name) is not None:
                    return arcs[p].read(name)
            raise FileNotFoundError(name)
        n = skyrimlod.vanilla_test(data, ov["world"], read)
        print(f"lod: VANILLA TEST, {n:,} composite NIFs replaced by Gagarin's crane LOD (60 m above our objects, "
              f"moved in the vertices)")
    if st["nif_files"]:
        print(f"lod: composite lodsettings {st['lodsettings']}; {st['objects_with_lod']:,} objects, "
              f"{st['instances']:,} references (radius >= {a.lod_min_radius:g} m; {st['skipped_small']:,} smaller "
              f"skipped) -> {st['nif_files']:,} composite NIFs, {st['meshes']:,} meshes "
              f"({st['mesh_bytes'] / 2 ** 20:,.0f} MiB)")
    if a.sf_esm:
        pp = os.path.join(a.out, "overlays_params.json")
        if prm.get("water"):                         # world-level water lists, as NewAtlantis (on Jemison's ocean) has
            prm["water"]["world_lists"] = bool(a.water_world_lists)
            save(pp, prm, indent=1)
        subprocess.run(["dotnet", "run", "--project", os.path.join(REPO, "dotnet", "TerrainOverlays"), "-c", "Release",
                        "--", a.sf_esm, a.out], check=True)
        add_cell_index(a.out, a.sf_esm, a.world_env_from)
    if not a.no_object_lod:
        object_lod(a, objects, data, ov["world"])
    print(f"lod: done in {time.time() - t0:.0f} s")
    return 0


def skyrimsea_defaults():
    from fo4sf import skyrimsea
    return skyrimsea.COLOUR, skyrimsea.ROUGHNESS


def distant_sea(a, objects, data, ov):
    """Flat sea pieces at Skyrim's sea level, drawn at any distance through object LOD (src/fo4sf/skyrimsea.py): cell
    water only draws in the loaded cells. Needs the overlay's sea_level_m (make_skyrim_overlay.py build) and
    --content-resources / --texconv for its material."""
    from fo4sf import skyrimsea
    if a.no_distant_sea:
        n = skyrimsea.remove(objects)
        print(f"distant sea: off{f' ({n} earlier sea bases removed)' if n else ''}")
        return
    sea = ov.get("sea_level_m")
    missing = [n for n, v in (("sea_level_m in overlays_params.json (rebuild the terrain with today's "
                               "make_skyrim_overlay.py)", sea is not None),
                              ("--content-resources", a.content_resources), ("--texconv", a.texconv)) if not v]
    if missing:
        skyrimsea.remove(objects)
        print(f"distant sea: skipped, needs {', '.join(missing)}")
        return
    st = skyrimsea.add(objects, data, ov["cell_min"], ov["cell_max"], float(sea), a.content_resources, a.texconv,
                       reach_m=a.sea_reach, double_sided=a.sea_double_sided,
                       colour=tuple(int(v) for v in a.sea_colour.split(",")), roughness=a.sea_roughness)
    print(f"distant sea: {st['pieces']} pieces ({st['tile_m']:g} m tiles over the map, reaching {st['reach_m']:g} m "
          f"past it) at z {st['z']:g} m (sea level {float(sea):g} m)")


def river_meshes(a, prm, objects, data):
    """--river-meshes: Skyrim's rivers / lakes as flat water statics at each water cell's level (skyrimsea.add_rivers),
    for Jemison's ocean spot, where our cell water did not draw."""
    from fo4sf import skyrimsea
    if not a.river_meshes:
        n = skyrimsea.remove(objects, skyrimsea.RIVER_EDID, skyrimsea.RIVER_SRC)
        if n:
            print("river meshes: off (earlier ones removed)")
        return
    if not (a.content_resources and a.texconv):
        sys.exit("--river-meshes needs --content-resources and --texconv (for the water material)")
    cells = (prm.get("water") or {}).get("cells") or []
    material = skyrimsea.write_material(data, a.content_resources, a.texconv,
                                        tuple(int(v) for v in a.river_colour.split(",")), a.river_roughness,
                                        rel=skyrimsea.RIVER_MAT_REL, tex_rel=skyrimsea.RIVER_TEX_REL)
    n = skyrimsea.add_rivers(objects, data, cells, material)
    print(f"river meshes: {n} water pieces (one per river / lake cell)"
          + ("" if n else "; overlays_params.json has no water cells (build the terrain with --skyrim-water)"))


def object_lod(a, objects, data, world):
    """Object LOD in the Creation Kit's -MockWorldSpaceLOD layout (src/fo4sf/objectlod.py), from objects.json and the
    plugin's formids.json. --ck-lod-reference <the CK's Objects folder> checks ours against the CK's (and picks the
    rotation convention that matches)."""
    from fo4sf import objectlod
    fpath = os.path.join(a.out, "formids.json")
    if not os.path.isfile(fpath):
        print("object LOD: no formids.json (run with --sf-esm first); skipped")
        return
    ids = load(fpath)["bases"]
    base_fids = {i: int(ids[b["edid"]], 16) for i, b in enumerate(objects["bases"]) if b["edid"] in ids}
    names = [n for n in (a.object_lod_names.split(",") if a.object_lod_names else
                         [world.replace("_", ""), world]) if n]
    names = list(dict.fromkeys(names))
    convention = a.lod_rotation
    if a.ck_lod_reference:
        st = objectlod.compare(a.ck_lod_reference, world.replace("_", ""), objects, base_fids)
        rot = st.pop("rot")
        best = max(rot, key=rot.get)
        print(f"object LOD vs Creation Kit: {st}; rotation conventions matching: "
              f"{dict(sorted(rot.items(), key=lambda kv: -kv[1])[:4])}")
        if rot[best] > 0:
            convention = best
    print(f"object LOD: rotation convention {convention}")
    sizes = [float(v) for v in a.object_lod_sizes.split(",")] if a.object_lod_sizes else [0.0]
    sizes = (sizes * 4)[:4] if len(sizes) == 1 else sizes
    min_size = {lv: sz for lv, sz in zip(objectlod.LEVELS, sizes) if sz > 0}
    counts = {}
    lodset, levels = objectlod.plan(objects, base_fids, convention=convention, min_size=min_size or None,
                                    skip_plants=not a.object_lod_plants, stats=counts)
    if lodset is None:
        print("object LOD: no references")
        return
    print(f"object LOD: references per level (of {len(objects['refs']):,}): "
          + ", ".join(f"level {lv}: {n:,}" + (f" (>= {min_size[lv]:g} m)" if lv in min_size else "")
                      for lv, n in counts.items())
          + ("" if a.object_lod_plants else "; trees and plants left out"))
    n = objectlod.write(data, names, lodset, levels, os.path.join(data, f"{world.lower()}.objectlod.json"))
    print(f"object LOD: lodsettings {lodset}, {sum(len(b) for b in levels.values()):,} block files per name, "
          f"names {names} -> {n:,} files")


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
    sel = dict(sel, refs=to_local(sel["refs"], ov))
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
    grass_json = os.path.join(a.work, "grass", "grass.json")
    if os.path.isfile(grass_json) and not a.no_grass:     # make_skyrim_objects.py grass: merged patches, appended
        gr = load(grass_json)
        off = len(objects["bases"])
        taken = {b["edid"].lower() for b in objects["bases"]}
        objects["bases"] += [b for b in gr["bases"] if b["edid"].lower() not in taken]
        if len(objects["bases"]) != off + len(gr["bases"]):
            sys.exit("grass base EditorIDs clash with object bases")
        objects["refs"] += [dict(r, base=r["base"] + off) for r in gr["refs"]]
        for tree in DATA_TREES:
            link_tree(os.path.join(a.work, "grass", tree), os.path.join(out, "Data", tree))
        print(f"grass: {len(gr['refs']):,} patches ({sum(gr['instances'].values()):,} instances) from {grass_json}")
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
        add_cell_index(out, a.sf_esm)
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
    ap.add_argument("cmd", choices=("export", "select", "convert", "grass", "stage", "lod", "check"))
    ap.add_argument("--skyrim", help="export: Skyrim.esm")
    ap.add_argument("--world-edid", default="Tamriel")
    ap.add_argument("--around", default="", help="export: cells around an exterior cell EditorID (Riverwood) or X,Y")
    ap.add_argument("--radius", type=int, default=2, help="export with --around: cells each side (default 2: 5 x 5)")
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
    ap.add_argument("--grass-spacing", type=float, default=0.3,
                    help="grass: metres between grass candidates (default 0.3 = Skyrim's iMinGrassSize 20 units; "
                         "bigger = sparser, smaller files and a faster build)")
    ap.add_argument("--grass-tint", choices=("vertex", "none"), default="vertex",
                    help="grass: 'vertex' (default) multiplies each grass texture by the mean Skyrim vertex colour "
                         "under it, as Skyrim tints grass with the ground")
    ap.add_argument("--grass-density", type=float, default=1.0, help="grass: multiplier on each grass's density")
    ap.add_argument("--seed", type=int, default=1, help="grass: random seed (same seed, same grass)")
    ap.add_argument("--lod-min-radius", type=float, default=20.0,
                    help="lod: only statics whose bounding radius x scale is at least this many metres (default 20: "
                         "mountains, cliffs, buildings)")
    ap.add_argument("--vanilla-test", default="",
                    help="lod: Starfield Data folder; replace our composite NIFs with a vanilla Gagarin crane composite "
                         "(diagnostic: does the engine load our files at all)")
    ap.add_argument("--lod-layer", default="",
                    help="lod: put every LOD object in this one layer (composites named after it); a vanilla LAYR "
                         "EditorID (e.g. NA_LOD_TheMast) is used as is instead of a new layer (diagnostic)")
    ap.add_argument("--full-lod", action="store_true",
                    help="lod: flag the big references (--lod-min-radius) Is Full LOD (full model at any distance)")
    ap.add_argument("--composite-lod", action="store_true",
                    help="lod: also write composite LOD (vanilla city layout; never drew for our world)")
    ap.add_argument("--no-object-lod", action="store_true",
                    help="lod: do not write object LOD (the Creation Kit's -MockWorldSpaceLOD layout)")
    ap.add_argument("--object-lod-names", default="",
                    help="lod: comma-separated world names for the object LOD files (default: the world EditorID "
                         "without underscores, as the CK writes it, and with them)")
    ap.add_argument("--object-lod-sizes", default="8,12,24,48",
                    help="lod: smallest object (largest extent x scale, metres) in object LOD levels 1,2,4,8; "
                         "one value for all levels; 0 = every reference (the full list made the game run out of RAM)")
    ap.add_argument("--world-env-from", default="",
                    help="lod: copy music / ambient / environment maps (ZNAM WAMB XEMP XWEM) from this vanilla world, "
                         "e.g. NewAtlantis (ours had none; ocean-spot coating)")
    ap.add_argument("--water-world-lists", action="store_true",
                    help="lod: list the cell water heights on the world too (XCLW / WHGT), as NewAtlantis does")
    ap.add_argument("--standalone-materials", action="store_true",
                    help="lod: EXPERIMENT, rebuild plain object materials without vanilla inheritance (olive coating at "
                         "the ocean spot); re-run stage to undo")
    ap.add_argument("--metal-fix", action="store_true",
                    help="lod: EXPERIMENT, black metalness texture in every material (made everything shinier in game; "
                         "re-run stage to undo: it relinks the converted materials)")
    ap.add_argument("--river-colour", default="18,36,34", help="lod --river-meshes: water colour R,G,B (sRGB)")
    ap.add_argument("--river-roughness", type=int, default=140,
                    help="lod --river-meshes: 0..255 (60 read as bright opaque cyan: the sky's reflection)")
    ap.add_argument("--river-meshes", action="store_true",
                    help="lod: rivers / lakes as flat water objects too (Jemison's ocean spot drew no cell water)")
    ap.add_argument("--no-distant-sea", action="store_true", help="lod: no flat distant sea pieces")
    ap.add_argument("--sea-reach", type=float, default=60000.0, help="lod: how far the distant sea reaches past the map (m)")
    ap.add_argument("--sea-colour", default=",".join(map(str, skyrimsea_defaults()[0])),
                    help="lod: distant sea colour R,G,B (sRGB 0..255)")
    ap.add_argument("--sea-roughness", type=int, default=skyrimsea_defaults()[1],
                    help="lod: distant sea roughness 0..255 (lower = shinier, more sky reflection)")
    ap.add_argument("--sea-double-sided", action="store_true",
                    help="lod: draw the distant sea from below too (if it turns out invisible from above)")
    ap.add_argument("--object-lod-plants", action="store_true", help="lod: keep trees and plants in object LOD")
    ap.add_argument("--lod-rotation", default="zyx+",
                    help="lod: rotation convention of object LOD instances (default zyx+: matched 10,140 of 10,220 "
                         "Creation Kit instances; --ck-lod-reference re-checks and picks the best)")
    ap.add_argument("--ck-lod-reference", default="",
                    help="lod: the Creation Kit's Objects folder (Meshes\\Terrain\\<World>\\Objects) to compare with")
    ap.add_argument("--no-large-refs", action="store_true",
                    help="lod: do not list the LOD references as the world's large references (WRLD RNAM)")
    ap.add_argument("--no-grass", action="store_true", help="stage: leave out <work>/grass even if it exists")
    ap.add_argument("--limit", type=int, default=10 ** 9)
    ap.add_argument("--resume", action="store_true", help="convert: reuse verified per-model checkpoints")
    a = ap.parse_args(argv)
    need = {"export": ("skyrim", "work"), "select": ("work", "terrain"),
            "convert": ("work", "skyrim_data", "content_resources", "texconv"),
            "grass": ("skyrim", "skyrim_data", "content_resources", "texconv", "terrain", "work"),
            "stage": ("work", "terrain", "out"), "lod": ("out",), "check": ("out",)}[a.cmd]
    missing = [f"--{k.replace('_', '-')}" for k in need if not getattr(a, k)]
    if a.cmd == "convert" and not (a.collision_template or a.starfield_data):
        missing.append("--collision-template or --starfield-data")
    if missing:
        sys.exit(f"{a.cmd} needs {' '.join(missing)}")
    return {"export": cmd_export, "select": cmd_select, "convert": cmd_convert, "grass": cmd_grass, "stage": cmd_stage, "lod": cmd_lod,
            "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
