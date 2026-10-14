"""core64c: every Fallout 4 exterior object of the 64 x 64-cell core on the core64 terrain (docs/terrain/core64c.md).

    dotnet run --project dotnet/Fo4Land -c Release -- <Fallout4.esm> export-exterior Commonwealth -55 <y0> 54 <y0+9> <work>/export/band_<y0>_<y0+9>.json
           (11 bands, y0 = -55, -45, ..., 45: one band at a time keeps the exporter's memory small)
    python scripts/terrain/make_core64c.py select  --work <work> --core <terrain_core64>
    python scripts/terrain/make_core64c.py measure --work <work> --fo4-data <FO4 Data>
    python scripts/convert_batch.py --cell-json <work>/convert_input.json --staging <work>/convert --prefix fo4core
           --max-texture <cap> --types <printed by select> --limit 1000000 --resume  + the usual converter arguments
    python scripts/terrain/make_core64c.py stage --work <work> --core <terrain_core64> --out <terrain_core64c> --sf-esm <Starfield.esm>
           [--views]
    python scripts/terrain/make_core64c.py check --work <work> --core <terrain_core64> --out <terrain_core64c>
           [--fo4 <Fallout4.esm>] [--fo4-data <FO4 Data>] [--sf-data <Starfield Data>]
    python scripts/terrain/make_core64c.py verify-data --out <terrain_core64c>

select   reads every export band, classifies every reference (exterior.select: convert, or skip with a reason, never
         silently) and writes selected.json (the references to place, slimmed to the fields placing needs),
         convert_input.json (one entry per model: all convert_batch needs) and selection.json (counts, skipped refs).
measure  before converting: models, materials and textures the converter would write (a dry run of its material
         logic over the FO4 archives' DDS headers: no texture is decoded), their size at full resolution and under
         texture caps, the mesh size (from the source NIF sizes) and the references per region; measure.json.
stage    places the converted references (exterior.place) in the core64 worldspace, hard-links the converted files
         into Data\\ (no second copy), copies core64's Data files (BTD, its meshes\\terrain copy, mask), writes
         objects.json and builds FO4TerrainCore.esm + FO4TerrainCore_Mars.esm with dotnet/TerrainOverlays (objects
         after every core64 record: core64's FormIDs do not move, the Mars plugin stays byte-identical), and plan.json:
         core64's probes within 500 m of the arrival re-judged with the objects, object tops at three familiar places
         (each dropped on twice), with --views screenshot spots, and open terrain waypoints so that no teleport moves
         the player more than 2 cells along an axis (build_plan).
check    raw-walks the plugin (core64 records unchanged, REFRs per cell, bases, positions), object z - terrain z under
         every placed origin (BTD; with --fo4 also FO4's own LAND), every model / geometry / material / texture file,
         every plan point re-derived from the converted collision, every runner teleport (cells per axis) and the
         step time, archive size; offline_check.json, and data_manifest.json (size and time of every staged file).
verify-data  is the staged tree still the one check passed? (Data\\ is hard-linked to the conversion work folder.)
Everything this writes stays outside the repo (derived game data).
"""
import argparse
import glob
import json
import math
import os
import shutil
import statistics
import struct
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
from fo4sf import btd, exterior  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402

sys.path.insert(0, HERE)
import make_exp2c as x2c  # noqa: E402
import overlay_records  # noqa: E402

EDID_PREFIX = "FO4Core_"
ASSET_PREFIX = "fo4core"
DATA_TREES = ("meshes", "geometries", "materials", "textures")
# fields of an exported reference that placing, reporting and the plan need (the export has about 25)
SLIM_KEYS = ("formkey", "type", "base_editor_id", "base_formkey", "model", "pos", "rot", "scale", "disabled",
             "persistent", "exterior_cell")
# Every large vanilla Starfield archive stops just below 4 GiB (Starfield - Textures02, Meshes01, Voices01, ...:
# 4,294,061,043 to 4,294,946,755 bytes, never more; read-only directory listing, 2026-10-11): Bethesda's own archives
# split at 2^32 bytes. Whether the engine reads an archive beyond 4 GiB is unresolved, so one archive stays below it.
ARCHIVE_LIMIT = 2 ** 32
ARCHIVE_BUDGET = int(3.8 * 2 ** 30)       # what the staged Data tree may hold (headroom for the archive's own tables)
REGION_CELLS = 16                         # report references per 16 x 16 Starfield cells (1.6 km)


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save(path, value, indent=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=indent)
    os.replace(tmp, path)


def core_params(core):
    """(overlays_params.json, its single overlay) of the staged core64 terrain."""
    prm = load(os.path.join(core, "overlays_params.json"))
    if len(prm["overlays"]) != 1:
        sys.exit(f"{core}: core64c needs exactly one overlay, found {len(prm['overlays'])}")
    return prm, prm["overlays"][0]


def slim(ref):
    out = {k: ref.get(k) for k in SLIM_KEYS}
    out["enable_parent"] = ref.get("enable_parent")
    return out


def region_of(cell, size=REGION_CELLS):
    return int(math.floor(cell[0] / size)), int(math.floor(cell[1] / size))


# ------------------------------------------------------------------------------------------------------------- select
def select_bands(paths):
    """Every export band through exterior.select: (kept slim references, skipped entries, totals)."""
    kept, skipped = [], []
    tot = {"bands": 0, "cells": 0, "refs": 0, "deferred": 0}
    seen = set()
    for p in paths:
        export = load(p)
        tot["bands"] += 1
        tot["cells"] += len((export.get("exterior") or {}).get("cells") or [])
        tot["refs"] += len(export["refs"])
        tot["deferred"] += len(export.get("deferred_refs", []))
        sub, skip = exterior.select(export)
        for r in sub["refs"]:
            if r["formkey"] in seen:
                raise ValueError(f"{r['formkey']} exported twice (overlapping bands?)")
            seen.add(r["formkey"])
            kept.append(slim(r))
        skipped += skip
        del export, sub
    return kept, skipped, tot


def convert_list(kept):
    """One entry per model (convert_batch --cell-json reads only "model" and "type")."""
    by_model = {}
    for r in kept:
        by_model.setdefault(exterior.source_key(r["model"]), {"model": r["model"], "type": r["type"],
                                                               "formkey": r["formkey"]})
    return [by_model[k] for k in sorted(by_model)]


def cmd_select(a):
    t0 = time.time()
    paths = sorted(glob.glob(os.path.join(a.work, "export", "band_*.json")))
    if not paths:
        sys.exit(f"no export bands in {os.path.join(a.work, 'export')}")
    kept, skipped, tot = select_bands(paths)
    _prm, ov = core_params(a.core)
    cmin, cmax = ov["cell_min"], ov["cell_max"]
    regions, cells = {}, {}
    for r in kept:
        c = tg.sf_cell_of(r["pos"][0] / exterior.UNITS_PER_METRE, r["pos"][1] / exterior.UNITS_PER_METRE)
        cells[c] = cells.get(c, 0) + 1
        g = region_of(c)
        regions[g] = regions.get(g, 0) + 1
    models = convert_list(kept)
    save(os.path.join(a.work, "selected.json"), {"core": os.path.abspath(a.core), "refs": kept})
    save(os.path.join(a.work, "convert_input.json"), {"schema_version": 2, "cell": "core64c", "refs": models})
    rep = {"bands": [os.path.basename(p) for p in paths], **tot, "to_convert": len(kept), "models": len(models),
           "skipped": len(skipped), "skip_reasons": exterior.reason_counts(skipped),
           "skip_types": type_counts(skipped), "convert_types": list(exterior.CONVERT_TYPES),
           "sf_cells_with_refs": len(cells), "refs_per_sf_cell_max": max(cells.values()) if cells else 0,
           "densest_sf_cells": [[list(c), n] for c, n in sorted(cells.items(), key=lambda kv: -kv[1])[:10]],
           "outside_core_cells": sum(n for c, n in cells.items() if not (cmin <= c[0] <= cmax and cmin <= c[1] <= cmax)),
           "in_mask_ring": sum(n for c, n in cells.items() if cmin <= c[0] <= cmax and cmin <= c[1] <= cmax
                               and (c[0] in (cmin, cmax) or c[1] in (cmin, cmax))),
           "regions": {f"{g[0]},{g[1]}": n for g, n in sorted(regions.items())}, "region_cells": REGION_CELLS,
           "seconds": round(time.time() - t0, 1), "skipped_refs": skipped}
    save(os.path.join(a.work, "selection.json"), rep)
    print(f"{rep['refs']:,} references + {rep['deferred']:,} deferred in {rep['cells']:,} FO4 cells: convert "
          f"{rep['to_convert']:,} ({rep['models']:,} models), skip {rep['skipped']:,}: {rep['skip_reasons']}")
    print(f"Starfield cells with references {rep['sf_cells_with_refs']}, max {rep['refs_per_sf_cell_max']} per cell; "
          f"outside the core {rep['outside_core_cells']}, in the mask ring {rep['in_mask_ring']}; {rep['seconds']} s")
    print("convert_batch --types " + ",".join(exterior.CONVERT_TYPES))
    return 0


def type_counts(skipped):
    out = {}
    for s in skipped:
        k = f"{s['reason']}:{s.get('type')}"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ------------------------------------------------------------------------------------------------------------ measure
BC_BYTES_PER_BLOCK = {"BC1": 8, "BC4": 8, "BC5": 16}


def bc_size(fmt, width, height, cap=0):
    """Bytes of a block-compressed DDS (DX10 header, 148 B) with texconv's full mip chain (floor(log2(max side)) + 1
    levels), top levels dropped until both sides are at most `cap` (0 = no cap), exactly as textures.cap_dds does."""
    w, h = max(1, int(width)), max(1, int(height))
    n = max(w, h).bit_length()
    drop = 0
    while cap and max(max(1, w >> drop), max(1, h >> drop)) > cap and drop < n - 1:
        drop += 1
    bb = BC_BYTES_PER_BLOCK[fmt]
    return 148 + sum(max(1, (max(1, w >> i) + 3) // 4) * max(1, (max(1, h >> i) + 3) // 4) * bb for i in range(drop, n))


class DryConverter:
    """The converter's material decisions (pipeline.Converter._shape_material: BGSM, blended decal, texture set,
    effect glass / grime decal, neutral) without converting anything: _convert_texture_set / _convert_glass record
    which outputs a material would get (format, source dimensions read from the archive's DX10 records)."""

    def __init__(self, src):
        from fo4sf import pipeline
        self.pipeline = pipeline
        conv = pipeline.Converter.__new__(pipeline.Converter)    # no texconv, no template, no neutral material
        conv.src, conv.prefix, conv._materials, conv._blend_cache = src, ASSET_PREFIX, {}, {}
        conv.stats = {"assets": 0, "failed": 0, "materials_ok": 0, "materials_fallback": 0}
        conv.material_errors = {}
        conv.neutral = "materials\\neutral.mat"
        conv._convert_texture_set = self._texture_set
        conv._convert_glass = self._glass
        self.conv, self.src = conv, src
        self.outputs = {}                                        # material stem -> [(kind, fmt, w, h)]
        self.mat_stem = {}                                       # material path the shapes get -> stem
        self.dims_cache = {}

    def dims(self, name):
        n = name.replace("\\", "/").lstrip("/")
        n = n if n.lower().startswith("textures/") else "textures/" + n
        if n.lower() not in self.dims_cache:
            got = None
            for a in self.src.textures:
                i = a.find(n)
                if i is not None:
                    e = a.entries[i]
                    got = (e.width, e.height)
                    break
            self.dims_cache[n.lower()] = got
        return self.dims_cache[n.lower()]

    def _texture_set(self, stem, diffuse, normal, spec, smoothness=1.0, spec_mult=1.0, alpha_test=False,
                     alpha_ref=128, decal=False):
        d = self.dims(diffuse)
        n = self.dims(normal) if normal else None
        s = self.dims(spec) if spec else None
        if d is None or (n is None and not decal):
            raise FileNotFoundError("diffuse or normal texture missing from archives")
        nd = n or (4, 4)
        out = [("color", "BC1", *d), ("normal", "BC5", *nd),
               ("rough", "BC4", *(s if s else (max(4, nd[0] // 4), max(4, nd[1] // 4))))]
        if alpha_test or decal:
            out.append(("opacity", "BC4", *d))                   # upper bound: only when the alpha really cuts out
        self.outputs[stem] = out
        return self._mat(stem)

    def _mat(self, stem):
        path = f"materials\\{ASSET_PREFIX}\\{stem}.mat"
        self.mat_stem[path] = stem
        return path

    def _glass(self, base, normal):
        d = self.dims(base) if base else None
        if d is None:
            raise FileNotFoundError("glass base texture missing")
        n = self.dims(normal) if normal else None
        stem = "glass/" + base.lower() + "|" + (normal or "").lower()
        self.outputs[stem] = [("color", "BC1", *d)] + ([("normal", "BC5", *n)] if n else []) + [("rough", "BC4", 16, 16)]
        return self._mat(stem)

    def model(self, name):
        """(ok, reason, materials used) for one model, by the converter's own shape and material logic."""
        from fo4sf import nif
        raw = self.src.mesh(name)
        if raw is None:
            return False, "not in the mesh archives", []
        try:
            src = nif.parse(raw)
            shapes = [s for s in nif.fo4_trishapes(src) if s.positions and s.triangles]
        except Exception as e:                                   # noqa: BLE001  (the converter fails it the same way)
            return False, f"{type(e).__name__}: {e}", []
        if not shapes:
            return False, "no static BSTriShape geometry", []
        mats = [self.conv._shape_material(src, s) for s in shapes]
        if all(m is None for m in mats):
            return False, "only effect-shader shapes", []
        return True, "", sorted({m for m in mats if m})


def mesh_entry_size(src, name):
    for a in src.meshes:
        i = a.find(name)
        if i is not None:
            return a.entries[i].unpacked or a.entries[i].packed
    return 0


def cmd_measure(a):
    from fo4sf import pipeline
    t0 = time.time()
    src = pipeline.Fo4Archives(a.fo4_data)
    models = load(os.path.join(a.work, "convert_input.json"))["refs"]
    sel = load(os.path.join(a.work, "selection.json"))
    dry = DryConverter(src)
    ok, failed, mats_of, nif_bytes = [], {}, {}, 0
    for k, m in enumerate(models):
        name = exterior.source_key(m["model"])
        good, why, mats = dry.model(name)
        if good:
            ok.append(name)
            mats_of[name] = mats
            nif_bytes += mesh_entry_size(src, name)
        else:
            failed[name] = why
        if (k + 1) % 2000 == 0:
            print(f"  {k + 1:,} / {len(models):,} models, {len(dry.outputs):,} texture sets, {time.time() - t0:.0f} s",
                  flush=True)
    caps = [int(c) for c in a.caps.split(",") if c.strip()]
    tex = {"materials": len(dry.outputs), "textures": sum(len(v) for v in dry.outputs.values()),
           "by_kind": {}, "full_bytes": 0, "capped_bytes": {str(c): 0 for c in caps}, "max_side": {}}
    for outs in dry.outputs.values():
        for kind, fmt, w, h in outs:
            full = bc_size(fmt, w, h)
            k = tex["by_kind"].setdefault(kind, {"count": 0, "full_bytes": 0})
            k["count"] += 1
            k["full_bytes"] += full
            tex["full_bytes"] += full
            side = str(max(w, h))
            tex["max_side"][side] = tex["max_side"].get(side, 0) + 1
            for c in caps:
                tex["capped_bytes"][str(c)] += bc_size(fmt, w, h, cap=c)
    tex["max_side"] = dict(sorted(tex["max_side"].items(), key=lambda kv: int(kv[0])))
    from fo4sf import textures as tx
    tex["kind_caps"] = {}
    for spec in (x for x in a.kind_caps.split(";") if x.strip()):
        kc = tx.parse_texture_caps(spec)
        tex["kind_caps"][spec] = sum(bc_size(f, w, h, cap=kc.get(k, 0)) for outs in dry.outputs.values()
                                     for k, f, w, h in outs)
    # mesh output size: converted .nif + .mesh bytes per source NIF byte, from a finished conversion (exp2c) if given
    ratio = None
    if a.calibrate and os.path.isfile(os.path.join(a.calibrate, "manifest.json")):
        man = load(os.path.join(a.calibrate, "manifest.json"))
        src_b = sum(mesh_entry_size(src, i["source"]) for i in man["items"])
        out_b = sum(os.path.getsize(os.path.join(r, f)) for t in ("meshes", "geometries")
                    for r, _d, fs in os.walk(os.path.join(a.calibrate, t)) for f in fs)
        ratio = out_b / src_b if src_b else None
    mesh_est = int(nif_bytes * ratio) if ratio else None
    # a split by region (REGION_CELLS x REGION_CELLS Starfield cells, each with its own archive) at full resolution:
    # every region archive needs the textures of every material its models use, so shared materials repeat
    mat_bytes = {st: sum(bc_size(f, w, h) for _k, f, w, h in outs) for st, outs in dry.outputs.items()}
    nif_size = {n: mesh_entry_size(src, n) for n in ok}
    regions = {}
    for r in load(os.path.join(a.work, "selected.json"))["refs"]:
        name = exterior.source_key(r["model"])
        if name not in mats_of:
            continue
        g = region_of(tg.sf_cell_of(r["pos"][0] / exterior.UNITS_PER_METRE, r["pos"][1] / exterior.UNITS_PER_METRE))
        regions.setdefault(g, {"refs": 0, "models": set()})
        regions[g]["refs"] += 1
        regions[g]["models"].add(name)
    split = {}
    for g, v in sorted(regions.items()):
        stems = {dry.mat_stem[m] for n in v["models"] for m in mats_of[n] if m in dry.mat_stem}
        tb = sum(mat_bytes[st] for st in stems)
        mb = int(sum(nif_size[n] for n in v["models"]) * (ratio or 0))
        split[f"{g[0]},{g[1]}"] = {"refs": v["refs"], "models": len(v["models"]), "materials": len(stems),
                                   "texture_bytes_full": tb, "mesh_bytes_estimate": mb, "archive_estimate": tb + mb}
    rep = {"region_split_full_resolution": {
               "region_cells": REGION_CELLS, "regions": split,
               "sum_bytes": sum(v["archive_estimate"] for v in split.values()),
               "largest_region_bytes": max(v["archive_estimate"] for v in split.values()),
               "regions_over_budget": sum(1 for v in split.values() if v["archive_estimate"] > ARCHIVE_BUDGET)},
           "references": sel["refs"] + sel["deferred"], "to_convert_refs": sel["to_convert"], "models": len(models),
           "models_converting": len(ok), "models_failing": len(failed), "failing": failed, "textures": tex,
           "source_nif_bytes": nif_bytes, "mesh_bytes_per_source_byte": ratio, "mesh_bytes_estimate": mesh_est,
           "archive_limit": ARCHIVE_LIMIT, "archive_budget": ARCHIVE_BUDGET,
           "seconds": round(time.time() - t0, 1)}
    rep["data_estimate"] = {"full": tex["full_bytes"] + (mesh_est or 0),
                            **{f"cap_{c}": tex["capped_bytes"][str(c)] + (mesh_est or 0) for c in caps}}
    fits = [c for c in caps if rep["data_estimate"][f"cap_{c}"] <= ARCHIVE_BUDGET]
    rep["largest_cap_within_budget"] = max(fits) if fits else None
    save(os.path.join(a.work, "measure.json"), rep, indent=1)
    gib = 2 ** 30
    print(f"{len(models):,} models: {len(ok):,} convert, {len(failed):,} fail; {tex['materials']:,} materials, "
          f"{tex['textures']:,} textures; {time.time() - t0:.0f} s")
    print(f"textures full resolution {tex['full_bytes'] / gib:.2f} GiB; " +
          ", ".join(f"cap {c}: {tex['capped_bytes'][str(c)] / gib:.2f} GiB" for c in caps))
    print(f"meshes: source {nif_bytes / gib:.2f} GiB, estimate {(mesh_est or 0) / gib:.2f} GiB (ratio {ratio})")
    print(f"largest cap within the {ARCHIVE_BUDGET / gib:.2f} GiB budget: {rep['largest_cap_within_budget']}")
    for spec, b in tex["kind_caps"].items():
        print(f"textures with {spec}: {b / gib:.2f} GiB; with meshes {(b + (mesh_est or 0)) / gib:.2f} GiB")
    rs = rep["region_split_full_resolution"]
    print(f"full resolution split into {len(rs['regions'])} regions of {REGION_CELLS} x {REGION_CELLS} cells: "
          f"{rs['sum_bytes'] / gib:.2f} GiB in all (one archive: {rep['data_estimate']['full'] / gib:.2f}), largest "
          f"{rs['largest_region_bytes'] / gib:.2f} GiB, {rs['regions_over_budget']} over the budget")
    return 0


# ------------------------------------------------------------------------------------------------------------ terrain
class Terrain:
    """The core64 BTD (raw u16 heights), decoded with the formula and edge clamping of make_cw_overlays.decode_at and
    tg.point_interp; the local frame is the CW frame (core64's origin is CW (0, 0): position = FO4 position / 70)."""

    def __init__(self, path):
        t = btd.read(overlay_records.read_bytes(path))
        self.raw, self.hmin, self.hmax, self.n = t.heights_raw, t.hmin, t.hmax, t.ncx
        self.step = (self.hmax - self.hmin) / 65535.0
        self.origin = tg.grid_origin(self.n)

    def window(self, x0, y0, x1, y1):
        """(heights in metres, origin x, origin y) of the samples covering [x0, x1] x [y0, y1] (plus one sample)."""
        last = self.raw.shape[0] - 1
        c0 = min(max(int(math.floor((x0 - self.origin) / tg.SF_STEP_M)) - 1, 0), last)
        c1 = min(max(int(math.ceil((x1 - self.origin) / tg.SF_STEP_M)) + 1, 0), last)
        r0 = min(max(int(math.floor((y0 - self.origin) / tg.SF_STEP_M)) - 1, 0), last)
        r1 = min(max(int(math.ceil((y1 - self.origin) / tg.SF_STEP_M)) + 1, 0), last)
        win = self.hmin + self.raw[r0:r1 + 1, c0:c1 + 1].astype(np.float64) / 65535.0 * (self.hmax - self.hmin)
        return win, self.origin + c0 * tg.SF_STEP_M, self.origin + r0 * tg.SF_STEP_M

    def bilinear(self, xs, ys):
        """Bilinear height at many points at once (tg.point_interp's "bilinear" rule and clamping)."""
        xs, ys = np.asarray(xs, np.float64), np.asarray(ys, np.float64)
        rows, cols = self.raw.shape
        u = np.clip((xs - self.origin) / tg.SF_STEP_M, 0.0, cols - 1.0)
        v = np.clip((ys - self.origin) / tg.SF_STEP_M, 0.0, rows - 1.0)
        c = np.minimum(u.astype(np.int64), cols - 2)
        r = np.minimum(v.astype(np.int64), rows - 2)
        fu, fv = u - c, v - r
        h = lambda rr, cc: self.hmin + self.raw[rr, cc].astype(np.float64) / 65535.0 * (self.hmax - self.hmin)  # noqa: E731
        return (h(r, c) * (1 - fu) * (1 - fv) + h(r, c + 1) * fu * (1 - fv) + h(r + 1, c) * (1 - fu) * fv
                + h(r + 1, c + 1) * fu * fv)


class CoreWorld(x2c.World):
    """make_exp2c.World over a part of the core: the placed references whose origin lies in `area` (x0, y0, x1, y1),
    their converted collision, and a window of the core BTD around it. Indices k are into this local list."""

    def __init__(self, data_dir, bases, placed, terrain, area, margin=60.0):
        x0, y0, x1, y1 = area
        self.bases = bases
        self.placed = [p for p in placed if x0 - margin <= p["pos"][0] <= x1 + margin
                       and y0 - margin <= p["pos"][1] <= y1 + margin]
        self.model_tris, self.collision_errors = {}, {}
        from fo4sf import sfbodies
        for i in sorted({p["base"] for p in self.placed}):
            try:
                with open(os.path.join(data_dir, "meshes", bases[i]["model"]), "rb") as f:
                    bodies = sfbodies.nif_bodies(f.read())
                self.model_tris[i] = np.array([t for body in bodies for t in body["triangles"]],
                                              np.float64).reshape(-1, 3, 3)
            except (OSError, ValueError, struct.error) as e:
                self.collision_errors[bases[i]["model"]] = f"{type(e).__name__}: {e}"
        self.tris, self.owners = exterior.world_triangles(self.model_tris, self.placed)
        self.index = exterior.SurfaceIndex(self.tris, self.owners)
        self.heights, self.ox, self.oy = terrain.window(x0 - margin, y0 - margin, x1 + margin, y1 + margin)
        self.area = (x0, y0, x1, y1)
        self.step, self.hmin, self.n = terrain.step, terrain.hmin, terrain.n
        self.by_src = {p["src"]: k for k, p in enumerate(self.placed)}

    def ground(self, x, y):
        return tg.point_interp(self.heights, self.ox, self.oy, tg.SF_STEP_M, x, y)["bilinear"]

    def ground_all(self, x, y):
        return tg.point_interp(self.heights, self.ox, self.oy, tg.SF_STEP_M, x, y)

    def segment_blocked(self, p0, p1, ignore=(), step=2.0):
        """Does the segment p0 -> p1 (x, y, z) cross a collision triangle of a placed object not in `ignore`, or run
        under the terrain? (Line of sight for a screenshot spot.)"""
        p0, p1 = np.asarray(p0, np.float64), np.asarray(p1, np.float64)
        d = p1 - p0
        n = max(2, int(math.hypot(d[0], d[1]) / step) + 1)
        for t in np.linspace(0.0, 1.0, n):
            q = p0 + t * d
            if self.ground(q[0], q[1]) > q[2]:
                return True
        idx = np.unique(np.concatenate([self.index.near(*(p0 + t * d)[:2], step) for t in np.linspace(0.0, 1.0, n)]))
        if not len(idx):
            return False
        if ignore:
            idx = idx[~np.isin(self.owners[idx], list(ignore))]
        tri = self.tris[idx]
        e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        h = np.cross(d, e2)
        det = (e1 * h).sum(axis=1)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = p0 - tri[:, 0]
        u = (s * h).sum(axis=1) * inv
        q = np.cross(s, e1)
        v = (q * d).sum(axis=1) * inv
        t = (q * e2).sum(axis=1) * inv
        return bool((ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-6) & (t < 1 - 1e-6)).any())


# ---------------------------------------------------------------------------------------------------------------- plan
NEAR_M = 510.0              # core64 probes this close to the arrival (exact in the core64 run, 2026-10-11)
AREA_M = 560.0              # local collision world: arrival +- this (every point and every teleport position)
DROP_MARGIN = 40.0          # drop at least this far above the highest expected landing of the entry (as core64)
TOP_CLEAR = 10.0            # and at least this far above every collision top within 1 m of a point
REF_LABEL = x2c.REF_LABEL
SHOP = "1B5F12:Fallout4.esm"            # RedRExt_Workshop02: Red Rocket shop floor and roof (exp2c)
STATION = "0211C0:Fallout4.esm"         # RedRExt_Workshop01: the station (rocket tower, canopy)
HOUSE_ROOF = "01DAAC:Fallout4.esm"      # Res01PlayerHouseRoofRR: the player's house in Sanctuary, its roof
MUSEUM = "01CC81:Fallout4.esm"          # ConcordMuseumBLD (ConcordMuseum01.nif): Museum of Freedom, Concord
# familiar object tops (judged: each >= x2c.MIN_DISCRIMINATION above the terrain under it) and screenshot spots
# (terrain south of the landmark: the runner faces north, heading 0, at every point and takes a screenshot there)
TOPS = (("redrocket_roof", SHOP), ("sanctuary_house_roof", HOUSE_ROOF), ("concord_museum_roof", MUSEUM))
VIEWS = (("view_redrocket", (STATION, SHOP)), ("view_sanctuary_house", (HOUSE_ROOF,)), ("view_concord_museum", (MUSEUM,)))
ROOF_FLAT_TOL = (0.02, 0.1, 0.25)       # level first; a low-pitched roof only if no level part is found
AGAIN = "_again"            # entry 2 drops on every roof twice in a row (about 70 s apart): late streaming vs absent
# Teleport rule (supported hypothesis, docs/terrain/core64c.md "Teleport rule", scripts/terrain/teleport_audit.py).
# The runner's Teleport types setpos x, then y, then z (scripts/game/qstep.ps1), so each setpos moves one axis. In the
# overlay runs so far (core64, core64b, exp2b, exp2b2, exp2b3, exp2c, exp2d, exp3: 173 teleports from a position where
# the previous one had landed), 144 of the 145 teleports that moved the player at most 2 cells along each axis landed
# (the other: exp2b's second attempt, where the player fell through the world), while 11 of the 28 that moved 3 or more cells
# along an axis relocated the player 8.2 to 11.8 km further along that axis ("Boundary Reached") or hung at the drop
# height, all 6 in core64 among them. Distance alone does not separate them: exp3 moved 250.5 and 267.0 m along one axis
# within 2 cells and landed, and hung after 248.7 m across 3 cells. A single-axis move of at most 200 m crosses at most
# 2 cell borders whatever the overlay's merge offset, so every teleport of a plan stays within MAX_AXIS_M per axis.
CELL_M = 100.0
MAX_AXIS_CELLS = 2
MAX_AXIS_M = MAX_AXIS_CELLS * CELL_M
# The runner hops legs longer than hop_m (qstep.ps1: ceil(d / hop_m) equal teleports, Euclidean d, none before the
# first point). Its step timeout, 150 + 90 s per point (testqueue.py step_timeout), does not count hops, so a plan keeps
# every leg within HOP_M by adding terrain waypoints (each a judged reading, and 90 s more timeout); hop_m stays a
# safety net for a leg without a usable waypoint.
HOP_M, HOP_WAIT_MS = int(MAX_AXIS_M), 7000
WAYPOINT_SPACING_M = 185.0  # ideal waypoint spacing: 15 m of slack below HOP_M for finding open terrain nearby
WAYPOINT_SEARCH_M = 30.0
WAYPOINT_MAX_SPREAD = 0.1   # m of terrain relief under the 0.6 m landing disc (about an 8 % grade): read within 0.5 m
WAYPOINT_PREFIX = "wp_"
# The runner's step costs (screenshot times of core64 / core64b, 2026-10-11): spawn shot 45 to 49 s after the step
# starts; a point (teleport, fall, read, screenshot) 68 to 73 s at settle 8 to 12 s; a hop 46 s (core64b: +46 s for
# one, +137 s for three); a "still hanging" re-read 28.5 s (core64: two per relocated probe, +57 s). An entry keeps
# MIN_MARGIN_S between its estimated last point and the step timeout: four re-reads (core64b had 138 s).
SPAWN_S, POINT_S, HOP_S, REREAD_S = 49.0, 62.0, 46.0, 29.0
MIN_MARGIN_S = 4 * REREAD_S + 4.0
# core64's merge offset on Mars (spawn read - spawn_local in all seven core64 / core64b runs: -1200.0029,
# -2700.0043 or -2699.9243): whole cells, used only to report cell changes in the frame the runs had
CORE64_OFFSET = (-1200.0, -2700.0)
FIRST_POINT_MAX_M = 100.0
REFR_NOTE = ("owner / nearby_object refr_in_plugin: the reference's FormID inside FO4TerrainCore.esm (6 hex digits). At "
             "run time the game prefixes the plugin's load-order index, which depends on the plugins loaded before it "
             "(the vanilla masters, BlueprintShips, the SFBGS plugins, FO4Port.esm, ...); this plan assumes none and "
             "needs none (no anchor: the merge offset comes from spawn_local)")
RUNNER_KEYS = x2c.RUNNER_KEYS
ENTRY_OWN = ("label", "points", "drop_z", "z_ref", "spawn_local", "settle_ms", "hop_m", "hop_wait_ms")
ROLES = ("terrain within 500 m", "familiar object tops", "informational")


def object_top(world, k, label, drop_z, tols=ROOF_FLAT_TOL):
    """The landing point on placed object k with the most level neighbourhood (exterior.pick_points), level first,
    then up to the next flat tolerance (a pitched roof). Returns a plan point dict or None."""
    for tol in tols:
        picks = exterior.pick_points(world.index, world.ground, k, world.bounds(k), drop_z, count=1, flat_tol=tol)
        if picks:
            x, y, land, free = picks[0]
            return {"label": label, "x": round(x, 4), "y": round(y, 4), "kind": "object_top",
                    "expect": round(land["centre"], 4), "landing": x2c.landing_json(world, land),
                    "above_terrain": round(land["centre"] - land["ground"], 4), "flat_tol": tol,
                    "discrimination": round(x2c.discrimination(world, x, y, land["centre"]), 4),
                    "owner": world.describe(k)}
    return None


def view_spot(world, label, owners, drop_z, dmin=20.0, dmax=90.0):
    """Open terrain south of a landmark (the runner faces north at every point) from where the landmark's middle is
    in sight: the nearest candidate (2 m grid, at most 25 degrees off north) that x2c.reference_ok accepts (level,
    nothing above the terrain within 1 m) and whose line of sight from eye height (1.7 m) is not blocked."""
    ks = [world.by_src[o] for o in owners]
    if not all((world.owners == k).any() for k in ks):
        return None                                      # disabled or without collision: no target to look at
    b = [world.bounds(k) for k in ks]
    cx = (min(v[0] for v in b) + max(v[2] for v in b)) / 2
    cy = (min(v[1] for v in b) + max(v[3] for v in b)) / 2
    y_south = min(v[1] for v in b)
    zs = world.tris[np.isin(world.owners, ks)][:, :, 2]
    target = (cx, cy, float(zs.min() + zs.max()) / 2)
    cands = []
    for d in np.arange(dmin, dmax + 1e-9, 2.0):
        for dx in np.arange(-d * 0.45, d * 0.45 + 1e-9, 2.0):
            x, y = cx + dx, y_south - d
            cands.append((math.hypot(dx, cy - y), round(x, 4), round(y, 4)))
    for _, x, y in sorted(cands):
        g = x2c.reference_ok(world, x, y, clear=1.0)
        if g is None:
            continue
        if world.segment_blocked((x, y, g + 1.7), target, ignore=set(ks)):
            continue
        land = world.landing(x, y, drop_z)
        return {"label": label, "x": x, "y": y, "kind": "view", "expect": round(g, 4), "terrain_expect": round(g, 4),
                "landing": x2c.landing_json(world, land), "target": [round(v, 3) for v in target],
                "distance_to_target_m": round(math.hypot(target[0] - x, target[1] - y), 1),
                "owner": world.describe(ks[0])}
    return None


def setpos_hits(world, cur, target_xy, drop_z, capsule=x2c.CAPSULE):
    """What each position one runner Teleport passes through from cur (x, y, z) to target_xy overlaps (x2c's capsule):
    [(x, y, z, hits)]."""
    return [(x, y, z, exterior.capsule_hits(world.index, world.ground, x, y, z, radius=capsule[0], height=capsule[1]))
            for x, y, z in exterior.setpos_path(cur, target_xy, drop_z)]


def waypoints_needed(d, spacing=None):
    """Waypoints a leg of d metres gets (add_waypoints): legs of up to `spacing` (WAYPOINT_SPACING_M) none, then one
    more per `spacing`."""
    return max(0, math.ceil(d / (spacing or WAYPOINT_SPACING_M) - 1e-9) - 1)


def seq_key(start, seq, legs=None):
    """(extra teleports, teleport position cost, length) of visiting seq (points) from start (x, y, z: where the
    player stands): what order_entry minimises. With legs (a Legs), each leg as add_waypoints will travel it (its
    waypoints, or the runner's hops where none was found, and x2c.position_cost of every position its teleports pass
    through); without, waypoints_needed per leg and no position cost."""
    extra, cost, total, here = 0, 0, 0.0, tuple(start)
    for p in seq:
        if legs is None:
            d = math.hypot(p["x"] - here[0], p["y"] - here[1])
            extra, total = extra + waypoints_needed(d), total + d
        else:
            lp = legs(here, p)
            extra, cost, total = extra + lp["extra"], cost + lp["cost"], total + lp["length"]
        here = (p["x"], p["y"], p["expect"])
    return extra, cost, round(total, 3)


def spoke_order(start, points, sector_deg=45.0):
    """Points near the arrival (< 100 m) first, then by bearing sector around the arrival, outward in one sector and
    inward in the next (a zig-zag over the spokes), so no jump crosses the arrival or skips a sector at 500 m."""
    def bearing(p):
        return math.degrees(math.atan2(p["y"] - start[1], p["x"] - start[0])) % 360.0

    def dist(p):
        return math.hypot(p["x"] - start[0], p["y"] - start[1])
    near = sorted((p for p in points if dist(p) < 100), key=lambda p: (dist(p), p["label"]))
    far = [p for p in points if dist(p) >= 100]
    sectors = {}
    for p in far:
        sectors.setdefault(int(bearing(p) // sector_deg), []).append(p)
    out = list(near)
    for n, s in enumerate(sorted(sectors)):
        out += sorted(sectors[s], key=lambda p: (dist(p), p["label"]), reverse=bool(n % 2))
    return out


def two_opt(order, key):
    """Reverse sub-sequences while that lowers key(sequence)."""
    order = list(order)
    best = key(order)
    improved = True
    while improved:
        improved = False
        for i in range(len(order) - 1):
            for j in range(i + 1, len(order)):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                k = key(cand)
                if k < best:
                    order, best, improved = cand, k, True
    return order


def order_entry(start, points, legs=None, exhaustive=8):
    """Visiting order of points from start (x, y, z: where the player stands before the first of them): up to
    `exhaustive` points every order, more points a spoke zig-zag around start improved by 2-opt, both by seq_key
    (fewest extra teleports, then the fewest teleport positions in objects, then the shortest way). Ties keep the
    given order."""
    import itertools

    def key(seq):
        return seq_key(start, seq, legs)
    if len(points) <= exhaustive:
        return list(min(itertools.permutations(points), key=key))
    return two_opt(spoke_order(start, points), key)


def waypoint_ok(world, x, y, drop_z):
    """Can (x, y) be a judged terrain waypoint? The three interpolation rules agree within one quantisation step (as
    check requires of every terrain point), at most WAYPOINT_MAX_SPREAD of relief under the 0.6 m landing disc, no
    object standing above the terrain within x2c.TERRAIN_CLEAR_RADII (1 m) and none reaching into a 3 m column of
    radius 1 m, the drop lands on the terrain. Returns (terrain height, disc spread) or None."""
    hs = world.ground_all(x, y)
    if max(hs.values()) - min(hs.values()) > world.step:
        return None
    disc = [world.ground(x + dx, y + dy) for dx, dy in exterior.disc_offsets(0.6)]
    if max(disc) - min(disc) > WAYPOINT_MAX_SPREAD:
        return None
    if exterior.nearby_object(world.index.top, world.ground, x, y, drop_z, radii=x2c.TERRAIN_CLEAR_RADII) is not None:
        return None
    if any(h != "terrain" for h in exterior.capsule_hits(world.index, world.ground, x, y, hs["bilinear"] + 0.02,
                                                         radius=1.0, height=3.0)):
        return None
    if world.landing(x, y, drop_z)["on_object"]:
        return None
    return hs["bilinear"], max(disc) - min(disc)


def waypoint(world, prev, ideal, target, legs_left, arrival, drop_z, label):
    """The terrain point (waypoint_ok) nearest `ideal` within WAYPOINT_SEARCH_M (2 m grid) that keeps the leg from
    prev (x, y, z) within HOP_M, can still reach target (x, y) in legs_left legs of HOP_M, lies within NEAR_M of the
    arrival and whose teleport from prev overlaps no placed object. A terrain plan point or None."""
    n = int(WAYPOINT_SEARCH_M / 2.0)
    cands = sorted((i * i + j * j, ideal[0] + 2.0 * i, ideal[1] + 2.0 * j)
                   for i in range(-n, n + 1) for j in range(-n, n + 1) if 4.0 * (i * i + j * j) <= WAYPOINT_SEARCH_M ** 2)
    for _, x, y in cands:
        x, y = round(x, 4), round(y, 4)
        if (math.hypot(x - prev[0], y - prev[1]) > HOP_M or math.hypot(target[0] - x, target[1] - y) > HOP_M * legs_left
                or math.hypot(x - arrival[0], y - arrival[1]) > NEAR_M):
            continue
        ok = waypoint_ok(world, x, y, drop_z)
        if ok is None or any(h != "terrain" for *_pos, hits in setpos_hits(world, prev, (x, y), drop_z) for h in hits):
            continue
        g, spread = ok
        return {"label": label, "x": x, "y": y, "kind": "terrain", "expect": round(g, 4), "terrain_expect": round(g, 4),
                "landing": x2c.landing_json(world, world.landing(x, y, drop_z)), "nearby_object": None,
                "waypoint": True, "disc_spread": round(spread, 4)}
    return None


def leg_plan(world, a, b, arrival, drop_z):
    """How the plan travels from a (x, y, z: where the player stands) to point b: waypoints_needed() terrain waypoints
    (waypoint(), unlabelled), each near its evenly spaced place, or none when one is not found (the runner then hops
    the leg, hop_m); "extra": the teleports that adds, "cost": x2c.position_cost of every position the leg's
    teleports pass through (after a hop the player is assumed at the drop height), "length": metres."""
    d = math.hypot(b["x"] - a[0], b["y"] - a[1])
    n = waypoints_needed(d)
    wps, prev = [], tuple(a)
    for i in range(1, n + 1):
        ideal = (a[0] + (b["x"] - a[0]) * i / (n + 1), a[1] + (b["y"] - a[1]) * i / (n + 1))
        w = waypoint(world, prev, ideal, (b["x"], b["y"]), n + 1 - i, arrival, drop_z, "")
        if w is None:
            break
        wps.append(w)
        prev = (w["x"], w["y"], w["expect"])
    left = len(wps) < n or math.hypot(b["x"] - prev[0], b["y"] - prev[1]) > HOP_M
    if left:
        wps = []
    chain = [{"label": "", "x": a[0], "y": a[1], "expect": a[2]}] + wps + [b]
    tps = runner_teleports(chain, HOP_M)[1:]                  # the first is a itself (no hop before it)
    cost, cur, k = 0, tuple(a), 1
    for label, x, y in tps:
        cost += sum(x2c.position_cost(hits) for *_pos, hits in setpos_hits(world, cur, (x, y), drop_z))
        if label is None:
            cur = (x, y, drop_z)
        else:
            cur, k = (x, y, chain[k]["expect"]), k + 1
    return {"waypoints": wps, "left": left, "extra": len(tps) - 1, "cost": cost, "length": round(d, 3)}


class Legs:
    """leg_plan of every leg asked for, computed once: what order_entry weighs and add_waypoints puts in."""

    def __init__(self, world, arrival, drop_z):
        self.world, self.arrival, self.drop_z, self.memo = world, arrival, drop_z, {}

    def __call__(self, a, b):
        key = (round(a[0], 4), round(a[1], 4), round(a[2], 4), round(b["x"], 4), round(b["y"], 4), round(b["expect"], 4))
        if key not in self.memo:
            self.memo[key] = leg_plan(self.world, a, b, self.arrival, self.drop_z)
        return self.memo[key]


def add_waypoints(world, start, seq, arrival, drop_z, legs=None):
    """seq with the terrain waypoints of every leg (leg_plan; start (x, y, z): where the player stands before seq[0]),
    labelled wp_01, wp_02, ... in travel order, so no leg is longer than HOP_M and the runner hops none. Returns
    (points, legs left to the runner's hops)."""
    legs = legs or Legs(world, arrival, drop_z)
    out, cur, left, k = [], tuple(start), [], 0
    for p in seq:
        lp = legs(cur, p)
        if lp["left"]:
            left.append({"to": p["label"], "from": [round(cur[0], 4), round(cur[1], 4)], "length_m": round(lp["length"], 1)})
        for w in lp["waypoints"]:
            k += 1
            out.append(dict(w, label=f"{WAYPOINT_PREFIX}{k:02d}"))
        out.append(p)
        cur = (p["x"], p["y"], p["expect"])
    return out, left


def entry_drop(world, points):
    """Drop height of an entry: DROP_MARGIN above its highest expected landing and TOP_CLEAR above every collision
    top within 1 m of any of its points, rounded up to 5 m."""
    top = max(p["expect"] for p in points) + DROP_MARGIN
    for p in points:
        for dx, dy in exterior.disc_offsets(1.0):
            s = world.index.surfaces(p["x"] + dx, p["y"] + dy)
            if s:
                top = max(top, s[0][0] + TOP_CLEAR)
    return float(math.ceil(top / 5.0) * 5.0)


def settle_for(drop, lowest):
    import make_cw_overlays as cwo
    return cwo.settle_ms(drop, lowest)


def plan_entry(base, label, drop_z, points, z_ref, spawn_local, settle_ms):
    """One runner entry: every key of core64's entry `base` except the ones core64c sets (ENTRY_OWN), then its own."""
    e = {k: v for k, v in base.items() if k not in ENTRY_OWN}
    e.update(label=label, spawn_local=spawn_local, z_ref=z_ref, drop_z=drop_z, settle_ms=settle_ms,
             hop_m=HOP_M, hop_wait_ms=HOP_WAIT_MS, points=[{k: p[k] for k in x2c.POINT_KEYS} for p in points])
    return e


def runner_teleports(points, hop_m=HOP_M):
    """The teleports qstep.ps1 makes for an entry's points, in order: [(label, x, y)], label None for a hop. No hop
    before the first point (its hop origin is the first point itself); a later leg of d metres (Euclidean) becomes
    ceil(d / hop_m) equal teleports."""
    out = []
    if not points:
        return out
    hx, hy = points[0]["x"], points[0]["y"]
    for p in points:
        if hop_m:
            n = math.ceil(math.hypot(p["x"] - hx, p["y"] - hy) / hop_m)
            out += [(None, hx + (p["x"] - hx) * h / n, hy + (p["y"] - hy) * h / n) for h in range(1, n)]
        out.append((p["label"], p["x"], p["y"]))
        hx, hy = p["x"], p["y"]
    return out


def axis_cells(d, cell=CELL_M):
    """The most cell borders a move of d metres along one axis can cross, whatever the frame's offset."""
    return int(math.ceil(abs(d) / cell - 1e-9))


def axis_moves(start, teleports, offset=CORE64_OFFSET):
    """Each teleport from where the player stood (start (x, y): the arrival): {"to", "dx", "dy", "cells": the most
    cells it can move the player along an axis whatever the merge offset, "cells_core64": along an axis in core64's
    measured frame}. qstep.ps1 sets x, then y, then z: each setpos moves one axis."""
    out, cur = [], tuple(start[:2])
    for label, x, y in teleports:
        dx, dy = x - cur[0], y - cur[1]
        core = max(abs(math.floor((x + offset[0]) / CELL_M) - math.floor((cur[0] + offset[0]) / CELL_M)),
                   abs(math.floor((y + offset[1]) / CELL_M) - math.floor((cur[1] + offset[1]) / CELL_M)))
        out.append({"to": label or "hop", "dx": round(dx, 2), "dy": round(dy, 2),
                    "cells": max(axis_cells(dx), axis_cells(dy)), "cells_core64": int(core)})
        cur = (x, y)
    return out


def runner_seconds(n_points, settle_ms, hops):
    """Estimated seconds from the start of a terrain step to its last point saved (SPAWN_S, POINT_S + settle, HOP_S)."""
    return SPAWN_S + n_points * (POINT_S + settle_ms / 1000.0) + hops * HOP_S


def runner_timeout(n_points):
    """testqueue.py step_timeout of a terrain test (claude/integration-1011 dcf8ad6): 150 + 90 * (points + 1) s."""
    return 150 + 90 * (n_points + 1)


def entry_travel(start, entry):
    """The runner's teleports through one plan entry from start (x, y): hops, the longest single-axis move, the most
    cells per axis (any frame and core64's), and the time estimate against the step timeout."""
    tps = runner_teleports(entry["points"], entry.get("hop_m") or 0)
    moves = axis_moves(start, tps)
    hops = sum(1 for t in tps if t[0] is None)
    est = runner_seconds(len(entry["points"]), entry["settle_ms"], hops)
    to = runner_timeout(len(entry["points"]))
    return {"teleports": len(tps), "hops": hops,
            "max_axis_move_m": round(max(max(abs(m["dx"]), abs(m["dy"])) for m in moves), 1),
            "max_axis_cells": max(m["cells"] for m in moves),
            "max_axis_cells_core64": max(m["cells_core64"] for m in moves),
            "estimated_s": round(est), "timeout_s": to, "margin_s": round(to - est), "moves": moves}


def teleport_report(world, start, entry):
    """x2c.path_report over the runner's teleports, hops included: what each position of each teleport overlaps
    (start (x, y, z): where the player stands after the coc). The player is assumed to stand at a point's expected
    landing after it, and at the drop height after a hop. Returns ([{"to", "positions"}], every position clear)."""
    out, ok, cur = [], True, tuple(start)
    want = {p["label"]: p["expect"] for p in entry["points"]}
    for label, x, y in runner_teleports(entry["points"], entry.get("hop_m") or 0):
        steps = []
        for px, py, pz, hits in setpos_hits(world, cur, (x, y), entry["drop_z"]):
            ok = ok and not hits
            steps.append([round(px, 4), round(py, 4), round(pz, 4),
                          [world.placed[h]["src"] if isinstance(h, int) else h for h in hits]])
        out.append({"to": label or "hop", "positions": steps})
        cur = (x, y, entry["drop_z"] if label is None else want[label])
    return out, ok


def validate_plan(plan, base, kinds):
    """Problems of the entries against the runner's keys and core64's entry (x2c.validate_plan's rules with this
    experiment's own keys): unknown keys, a base key not carried, z_ref not this entry's terrain reference, duplicate
    labels, point keys."""
    problems = []
    for i, e in enumerate(plan):
        tag = f"entry {i + 1}"
        problems += [f"{tag}: key {k!r} is not read by the runner" for k in e if k not in RUNNER_KEYS]
        problems += [f"{tag}: core64 key {k!r} not carried" for k, v in base.items() if k not in ENTRY_OWN and e.get(k) != v]
        labels = [p["label"] for p in e.get("points", [])]
        if len(set(labels)) != len(labels):
            problems.append(f"{tag}: duplicate point labels")
        if e.get("z_ref") not in labels or kinds.get((i, e.get("z_ref"))) != "terrain_ref":
            problems.append(f"{tag}: z_ref {e.get('z_ref')!r} is not its terrain reference point")
        problems += [f"{tag}: point {p.get('label')} keys {sorted(p)}" for p in e.get("points", [])
                     if tuple(sorted(p)) != tuple(sorted(x2c.POINT_KEYS))]
    return problems


def scenario_reads(world, entry, meta, scenario):
    """x2c.scenario_reads with this plan's kinds: terrain points (terrain, terrain_ref, terrain_near_object, view)
    read the terrain without objects; object points then land on the highest terrain sample under their disc.
    landing_max: every point reads the highest collision or terrain under its 0.6 m landing disc (what the dropped
    player may rest on: an object reaching into the disc of a terrain point shows here)."""
    reads = []
    for p in entry["points"]:
        on_terrain = meta[p["label"]]["kind"] in ("terrain", "terrain_ref", "terrain_near_object", "view")
        if scenario == "no_objects":
            reads.append(p["expect"] if on_terrain else
                         max(world.ground(p["x"] + dx, p["y"] + dy) for dx, dy in exterior.disc_offsets(0.6)))
        elif scenario == "flat_terrain":
            reads.append(world.hmin if on_terrain else p["expect"])
        elif scenario == "landing_max":
            reads.append(world.landing(p["x"], p["y"], entry["drop_z"])["z"])
        else:
            raise ValueError(scenario)
    return reads


SCENARIOS = (("no_objects", "flat_terrain", "landing_max"), ("no_objects", "landing_max"), ("no_objects", "landing_max"))


def build_plan(world, ov, base, core_exp, views=False):
    """Three entries, each ONE coc arrival at core64's COC marker, heights judged against the terrain reference
    zref_ground read in the same test (z_ref), its first point:
    1 terrain within 500 m  core64's probes within NEAR_M of the arrival that stay clear of objects (exact in core64)
    2 object tops           Red Rocket shop roof, the Sanctuary player house roof, the Concord museum roof (each at
                            least x2c.MIN_DISCRIMINATION above the terrain: without the objects the entry fails), each
                            dropped on twice in a row (<label>_again, about 70 s later: late streaming vs absent)
    3 informational         core64 probes now on or near an object; with views, screenshot spots south of the three
                            places (only useful once the runner sets the time of day: PR #73)
    Points are ordered by order_entry; add_waypoints puts open terrain waypoints (judged like the probes) on every
    leg longer than WAYPOINT_SPACING_M, so every teleport stays within MAX_AXIS_CELLS cells per axis without the
    runner's hops, which its step timeout does not count. Returns (plan, expected-json part)."""
    sx, sy, sz = ov["spawn"]
    land_spawn = world.landing(sx, sy, sz)
    start = (sx, sy, land_spawn["centre"])
    spawn_local = [sx, sy, round(land_spawn["centre"], 4)]
    ref = x2c.reference_point(world, (sx, sy))
    if ref is None:
        sys.exit(f"no open level terrain within {x2c.REF_SEARCH} m of the arrival for {REF_LABEL}")

    near, seen = [], set()
    for e in core_exp["entries"]:
        for p in e["points"]:
            if p["from_arrival_m"] <= NEAR_M and p["label"] not in seen:
                seen.add(p["label"])
                near.append({"label": p["label"], "x": p["x_cw"], "y": p["y_cw"], "expect": p["expect"],
                             "core64": {"kind": p["kind"], "from_arrival_m": p["from_arrival_m"]}})
    terr = x2c.terrain_points(world, near, 300.0)
    for t, p in zip(terr, near):
        t["core64"] = p["core64"]
    judged_terrain = [p for p in terr if p["kind"] == "terrain"]
    info = [p for p in terr if p["kind"] != "terrain"]

    tops, missing = [], []
    for label, src in TOPS:
        k = world.by_src.get(src)
        if k is not None and not (world.owners == k).any():
            k = None                                     # disabled or without collision
        p = object_top(world, k, label, 300.0) if k is not None else None
        if p is None or p["discrimination"] < x2c.MIN_DISCRIMINATION:
            missing.append({"label": label, "src": src, "reason": "not placed or no collision" if k is None else
                            "no landing point" if p is None else f"only {p['discrimination']} m above the terrain"})
            if p is not None:
                info.append(p)
            continue
        p["object_class"] = x2c.object_class(p["discrimination"])
        tops.append(p)
    if not tops:
        sys.exit(f"no familiar object top: {missing}")
    if views:
        for label, owners in VIEWS:
            if all(o in world.by_src for o in owners):
                v = view_spot(world, label, owners, 300.0)
                if v is not None:
                    info.append(v)
                    continue
            missing.append({"label": label, "src": owners[0], "reason": "no open terrain with a clear view south of it"})

    groups, plan, kinds, left = [], [], {}, []
    labels = [f"terrain_core64c 1/3 (terrain within {NEAR_M:.0f} m): core64's probes near the arrival that stay clear "
              f"of objects and open terrain waypoints between them, relative to {REF_LABEL} (a flat or missing BTD "
              f"fails)",
              f"terrain_core64c 2/3 (familiar object tops): Red Rocket shop roof, Sanctuary player house roof, Concord "
              f"museum roof, >= {x2c.MIN_DISCRIMINATION} m above the terrain, each dropped on twice in a row "
              f"(<roof>{AGAIN}), relative to {REF_LABEL} (fails if the objects are missing)",
              "terrain_core64c 3/3 (informational: the runner's verdict is expected to be FAIL HEIGHTS, read point by "
              "point): core64 probes now on or near objects (e_500m: a maple's collision reaches into the landing "
              "disc; ne_200m: 0.8 m from a 7 m cliff)" + (", screenshot spots facing north at Red Rocket, the "
                                                          "Sanctuary house and the Concord museum" if views else "")]
    ref_xyz = (ref["x"], ref["y"], ref["expect"])
    legs = Legs(world, (sx, sy), 300.0)
    for i, pts in enumerate((judged_terrain, tops, info)):
        order = order_entry(ref_xyz, pts, legs)
        if i == 1:
            order = [q for p in order for q in (p, dict(p, label=p["label"] + AGAIN, again_of=p["label"]))]
        order, gaps = add_waypoints(world, ref_xyz, order, (sx, sy), 300.0, legs)
        order = [ref] + order
        drop = entry_drop(world, order)
        settle = settle_for(drop, min(p["expect"] for p in order))
        groups.append(order)
        left.append(gaps)
        plan.append(plan_entry(base, labels[i], drop, order, REF_LABEL, spawn_local, settle))
        kinds.update({(i, p["label"]): p["kind"] for p in order})
    problems = validate_plan(plan, base, kinds)
    if problems:
        sys.exit("plan: " + "; ".join(problems))
    entries = []
    for i, (e, g) in enumerate(zip(plan, groups)):
        meta = {p["label"]: p for p in g}
        pred = {}
        for sc in SCENARIOS[i]:
            v, worst, _ = x2c.judge_heights(e["points"], scenario_reads(world, e, meta, sc), e["z_ref"])
            pred[sc] = {"verdict": v, "worst_m": round(worst, 3)}
        paths, clear = teleport_report(world, start, e)
        travel = entry_travel(start, e)
        if travel["max_axis_cells"] > MAX_AXIS_CELLS or travel["margin_s"] < MIN_MARGIN_S:
            sys.exit(f"entry {i + 1}: a teleport moves {travel['max_axis_cells']} cells along an axis (at most "
                     f"{MAX_AXIS_CELLS}) or the step keeps {travel['margin_s']} s of {travel['timeout_s']} s (at least "
                     f"{MIN_MARGIN_S:.0f})")
        here, legs = start[:2], []
        for p in e["points"]:
            legs.append(round(math.hypot(p["x"] - here[0], p["y"] - here[1]), 1))
            here = (p["x"], p["y"])
        entries.append({"label": e["label"], "role": ROLES[i], "drop_z": e["drop_z"], "settle_ms": e["settle_ms"],
                        "z_ref": e["z_ref"], "predicted": pred, "teleports_clear": clear, "legs_m": legs,
                        "longest_leg_m": max(legs), "waypoints": sum(1 for p in g if p.get("waypoint")),
                        "legs_left_to_runner_hops": left[i],
                        "travel": {k: v for k, v in travel.items() if k != "moves"},
                        "teleport_positions_on_objects": sum(
                            1 for t in paths for pos in t["positions"] if any(h != "terrain" for h in pos[3])),
                        "moves": travel["moves"], "teleports": paths})
    return plan, {"spawn": {"marker": ov["spawn"], "landing": x2c.landing_json(world, land_spawn),
                            "spawn_local": spawn_local, "core64_spawn_local": base["spawn_local"]},
                  "reference": ref, "entries": entries, "missing": missing, "views": bool(views),
                  "points": [dict(p, entry=i) for i, g in enumerate(groups) for p in g]}


# --------------------------------------------------------------------------------------------------------------- stage
def link_tree(src, dst):
    """Hard-link every file of src into dst (same volume: no second copy of the converted files), copying when a link
    is not possible; a file already linked to the same source is kept. Returns (linked, copied, kept)."""
    linked = copied = kept = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for fn in files:
            s, d = os.path.join(root, fn), os.path.join(dst, rel, fn)
            if os.path.exists(d):
                if os.path.samefile(s, d):
                    kept += 1
                    continue
                os.remove(d)
            try:
                os.link(s, d)
                linked += 1
            except OSError:
                shutil.copy2(s, d)
                copied += 1
    return linked, copied, kept


def data_files(out):
    """[(path relative to Data with '/', bytes)] of the staged Data tree, sorted."""
    data = os.path.join(out, "Data")
    files = []
    for root, _dirs, names in os.walk(data):
        for fn in names:
            p = os.path.join(root, fn)
            files.append((os.path.relpath(p, data).replace(os.sep, "/"), os.path.getsize(p)))
    return sorted(files)


def ba2_size(files):
    """Size of a General BA2 holding `files` stored (no compression), as Archive2 writes it: 24-byte header (+ 8 in
    v2/v3), a 36-byte record per file, the data, then the name table (u16 length + name). An estimate within the
    header variant; the dry run in check measures the real one."""
    return 32 + sum(36 + b + 2 + len(n) for n, b in files)


def terrain_edids(prm):
    out = set()
    for o in prm["overlays"]:
        out |= {o["world"], o["block"], o["location"], o["anchor"]["edid"], o["coc"], o["coc"] + "Marker"}
    return {e.lower() for e in out}


def place_all(a, ov):
    sel = load(os.path.join(a.work, "selected.json"))
    man = load(os.path.join(a.work, "convert", "manifest.json"))
    bases, placed, skipped_conv = exterior.place(sel, man, ov["cell_min"], ov["cell_max"], EDID_PREFIX)
    items = {i["source"].replace("/", "\\").lower(): i for i in man["items"]}
    for b in bases:
        b["collision"] = x2c.collision_kind(items[b["key"]])
    return bases, placed, skipped_conv, man


def cmd_stage(a):
    t0 = time.time()
    prm, ov = core_params(a.core)
    core_plan = load(os.path.join(a.core, "plan.json"))
    core_exp = load(os.path.join(a.core, "expected.json"))
    selrep = load(os.path.join(a.work, "selection.json"))
    bases, placed, skipped_conv, man = place_all(a, ov)
    skipped = selrep["skipped_refs"] + skipped_conv
    total = selrep["refs"] + selrep["deferred"]
    if len(placed) + len(skipped) != total:
        sys.exit(f"accounting: {len(placed)} placed + {len(skipped)} skipped != {total} exported")
    clash = sorted({b["edid"].lower() for b in bases} & terrain_edids(prm))
    if clash:
        sys.exit(f"base EditorIDs clash with core64's records: {clash}")
    print(f"{len(bases):,} bases, {len(placed):,} references placed, {len(skipped):,} skipped "
          f"({exterior.reason_counts(skipped)}); {time.time() - t0:.0f} s")

    out = a.out
    os.makedirs(out, exist_ok=True)
    base_files = x2c.copy_base_data(a.core, out)                       # BTD, its meshes\terrain copy, mask
    for tree in DATA_TREES:
        ln, cp, kp = link_tree(os.path.join(a.work, "convert", tree), os.path.join(out, "Data", tree))
        print(f"Data\\{tree}: {ln} linked, {cp} copied, {kp} kept")
    files = data_files(out)
    data_bytes = sum(b for _, b in files)
    archive = ba2_size(files)
    print(f"Data tree: {len(files):,} files, {data_bytes / 2 ** 30:.3f} GiB; one stored archive about "
          f"{archive / 2 ** 30:.3f} GiB (limit {ARCHIVE_LIMIT / 2 ** 30:.0f} GiB, budget {ARCHIVE_BUDGET / 2 ** 30:.2f})")
    if archive > ARCHIVE_BUDGET:
        sys.exit("the Data tree does not fit one archive below 4 GiB: lower convert_batch --max-texture, or split it "
                 "into region plugins with their own archives (docs/terrain/core64c.md)")

    objects = {"world": ov["world"], "edid_prefix": EDID_PREFIX,
               "bases": [{k: b[k] for k in ("edid", "model", "door", "source", "collision") if k in b} for b in bases],
               "refs": [{k: p[k] for k in ("src", "base", "cell", "pos", "rot", "scale", "disabled")} for p in placed]}
    save(os.path.join(out, "objects.json"), objects)
    save(os.path.join(out, "overlays_params.json"), dict(prm, objects="objects.json"), indent=1)
    save(os.path.join(out, "skipped.json"), {"counts": exterior.reason_counts(skipped), "types": type_counts(skipped),
                                             "refs": skipped})
    for name in ("preview.png",):
        if os.path.isfile(os.path.join(a.core, name)):
            shutil.copy2(os.path.join(a.core, name), os.path.join(out, name))

    t1 = time.time()
    if a.sf_esm:
        subprocess.run(["dotnet", "run", "--project", os.path.join(REPO, "dotnet", "TerrainOverlays"), "-c", "Release",
                        "--", a.sf_esm, out], check=True)
    plugin_s = round(time.time() - t1, 1)

    t2 = time.time()
    terrain = Terrain(os.path.join(out, *ov["btd_file"].split("/")))
    sx, sy = ov["spawn"][:2]
    area = (sx - AREA_M, sy - AREA_M, sx + AREA_M, sy + AREA_M)
    world = CoreWorld(os.path.join(out, "Data"), bases, placed, terrain, area)
    if world.collision_errors:
        sys.exit(f"converted collision unreadable: {world.collision_errors}")
    print(f"local world: {len(world.placed):,} references, {len(world.model_tris):,} models, {len(world.tris):,} "
          f"collision triangles ({time.time() - t2:.0f} s)")
    plan, exp = build_plan(world, ov, core_plan[0], core_exp, views=a.views)
    save(os.path.join(out, "plan.json"), plan, indent=1)
    ids = load(os.path.join(out, "formids.json")) if os.path.exists(os.path.join(out, "formids.json")) else None
    for p in exp["points"]:
        for o in (p.get("owner"), (p.get("nearby_object") or {}).get("owner")):
            if o and ids:
                o["refr_in_plugin"] = ids["refs"][o["src"]]
    tex = dict(man["stats"].get("textures") or {})
    log_path = os.path.join(a.work, "convert", "texture_log.json")
    if os.path.isfile(log_path):
        log = load(log_path)
        caps = {}
        for v in log.values():
            caps[v["kind"]] = v["cap"]
        tex.update(caps=caps, by_kind={k: {"textures": sum(1 for v in log.values() if v["kind"] == k),
                                           "full_bytes": sum(v["bytes"] for v in log.values() if v["kind"] == k),
                                           "written_bytes": sum(v["out_bytes"] for v in log.values() if v["kind"] == k)}
                                       for k in sorted(caps)})
    expected = {
        "experiment": "terrain_core64c", "core": os.path.abspath(a.core), "base_files": base_files,
        "hypothesis": "FO4 position / 70 = core64 position in metres for terrain and objects alike (core64's origin is "
                      "CW (0, 0)); an object's collision then sits on the BTD as in FO4",
        "objects": {"exported": total, "placed": len(placed), "bases": len(bases),
                    "doors": sum(1 for b in bases if "door" in b),
                    "initially_disabled": sum(p["disabled"] for p in placed),
                    "fo4_persistent_placed_temporary": sum(p["fo4_persistent"] for p in placed),
                    "enable_parent_not_translated": sum(p["enable_parent"] for p in placed),
                    "collision": {k: sum(1 for p in placed if bases[p["base"]]["collision"] == k)
                                  for k in sorted({b["collision"] for b in bases})},
                    "skipped": exterior.reason_counts(skipped)},
        "data": {"files": len(files), "bytes": data_bytes, "archive_estimate": archive,
                 "archive_limit": ARCHIVE_LIMIT, "textures": tex,
                 "texture_caps": ",".join(f"{k}={v}" for k, v in sorted((tex.get("caps") or {}).items())) or "none"},
        "times_s": {"stage_place": round(t1 - t0, 1), "plugin": plugin_s, "plan": round(time.time() - t2, 1)},
        "refr_in_plugin": REFR_NOTE,
        **exp}
    save(os.path.join(out, "expected.json"), expected, indent=1)
    readme(out, prm, ov, plan, expected)
    for i, e in enumerate(plan):
        d = expected["entries"][i]
        t = d["travel"]
        print(f"entry {i + 1} ({d['role']}): {len(e['points'])} points ({d['waypoints']} waypoints) from {e['drop_z']} m, "
              f"settle {e['settle_ms']} ms, predicted {d['predicted']}, longest leg {d['longest_leg_m']} m, longest "
              f"single-axis move {t['max_axis_move_m']} m ({t['max_axis_cells']} cells), {t['hops']} runner hops, "
              f"about {t['estimated_s']} s of {t['timeout_s']} s, teleports clear {d['teleports_clear']}")
    print(f"spawn_local {expected['spawn']['spawn_local']}; missing {expected['missing']}; {time.time() - t0:.0f} s")
    return 0


def readme(out, prm, ov, plan, exp):
    pl = [prm["plugin"], prm["mars"]["plugin"]]
    base = os.path.splitext(prm["plugin"])[0]
    o, d = exp["objects"], exp["data"]
    ref = exp["reference"]
    lines = [
        "Terrain core64c (Claude, 2026-10-12). NOT deployed, NOT queued. Recipe: docs/terrain/core64c.md",
        "(branch claude/terrain-core64-objects). Base: core64 (" + exp["core"] + "): the same BTD, mask, Location,",
        "Mars registration, anchor, COC marker and FormIDs, plus EVERY Fallout 4 exterior object of the 64 x 64-cell",
        f"core that converts: {o['placed']:,} references of {o['bases']:,} models (STAT, {o['doors']} rigged DOOR) at",
        f"FO4 position / 70 in {ov['world']}, in the same plugin after core64's records. Skipped and why: skipped.json",
        f"({', '.join(f'{k} {v:,}' for k, v in o['skipped'].items())}).",
        f"Data tree {d['files']:,} files, {d['bytes'] / 2 ** 30:.2f} GiB (textures capped {d['texture_caps']}),",
        f"one stored archive of about {d['archive_estimate'] / 2 ** 30:.2f} GiB (vanilla archives stop below 4 GiB).",
        "",
        "Install (game closed). The runner does it:",
        f"  scripts/game/exp_install.py install --exp-dir <this folder> --starfield <game> --plugins {','.join(pl)} --pack",
        f"  --pack builds \"{base} - Main.ba2\" from Data\\ (Archive2 -format=General -compression=None: every entry",
        "  stored, BTD included; textures load from the General archive, verified with exp2c on 2026-10-11).",
        f"Queue: testqueue.py plan-terrain --staging <build> --exp-dir <this folder> --out <queue> --plugins {','.join(pl)} --fresh",
        "Never install together with another terrain experiment (every Mars plugin overrides MarsPlanetData). core64,",
        "core64b and core64e use the same plugin and archive names: exp_install.py uninstall first (it refuses otherwise).",
        "The installer builds the archive in %TEMP% (C:) and copies it to the game's Data folder.",
        "",
        f"Plan: {len(plan)} entries, each ONE coc {plan[0]['coc']} arrival (fresh launch). spawn_local {plan[0]['spawn_local']}",
        f"= where the player lands under the COC marker {ov['spawn']}. Heights are judged relative to {REF_LABEL}",
        f"({ref['x']}, {ref['y']} -> {ref['expect']}: open level terrain {ref['distance_from_arrival']} m from the arrival,",
        f"nothing above it within {x2c.REF_CLEAR} m), the first point of every entry.",
        f"Teleports: every one moves the player at most {MAX_AXIS_CELLS} cells ({MAX_AXIS_M:.0f} m) along each axis. "
        f"Legs longer than {WAYPOINT_SPACING_M:.0f} m",
        f"get open terrain waypoints ({WAYPOINT_PREFIX}NN: at most {WAYPOINT_MAX_SPREAD:g} m of relief under the landing "
        "disc, no object within 1 m;",
        f"judged like the probes), so the runner hops none; hop_m {HOP_M} ({HOP_WAIT_MS} ms) stays as a safety net.",
        "Why (supported hypothesis, docs/terrain/core64c.md \"Teleport rule\", scripts/terrain/teleport_audit.py):",
        "in the overlay runs so far a teleport of 3 or more cells along an axis relocated the player 8.2 to 11.8 km",
        "(\"Boundary Reached\") or hung 11 of 28 times (all 6 in core64), one of at most 2 cells landed 144 of 145 times.",
        "The runner faces north at every point and takes a screenshot there; every arrival so far was at night on Mars",
        "(the runner on claude/integration-1011 sets no time of day)" + ("." if exp.get("views") else
                                                                       "; the screenshot spots are left out (stage --views)."),
    ]
    meta = {(q["entry"], q["label"]): q for q in exp["points"]}
    for i, e in enumerate(plan):
        dd = exp["entries"][i]
        pr, t = dd["predicted"], dd["travel"]
        lines += ["", f"  {e['label']}",
                  f"  {len(e['points'])} points ({dd['waypoints']} waypoints), drop_z {e['drop_z']}, settle {e['settle_ms']} ms; "
                  f"predicted without the objects: {pr['no_objects']['verdict']} (worst {pr['no_objects']['worst_m']} m)" +
                  (f", on flat terrain: {pr['flat_terrain']['verdict']} (worst {pr['flat_terrain']['worst_m']} m)"
                   if "flat_terrain" in pr else "") +
                  f", resting on the highest surface under each 0.6 m disc: {pr['landing_max']['verdict']} (worst "
                  f"{pr['landing_max']['worst_m']} m)",
                  f"  longest leg {dd['longest_leg_m']} m, longest single-axis move {t['max_axis_move_m']} m (at most "
                  f"{t['max_axis_cells']} cells), {t['hops']} runner hops; about {t['estimated_s']} s to the last point of the "
                  f"{t['timeout_s']} s step timeout ({t['margin_s']} s to spare)"]
        for p in e["points"]:
            m = meta[(i, p["label"])]
            owner = (m.get("owner") or {}).get("edid", "")
            near = m.get("nearby_object") or {}
            what = {"terrain": "terrain (waypoint)" if m.get("waypoint") else "terrain (core64 probe)",
                    "terrain_ref": "terrain, the Z reference",
                    "terrain_covered": "core64 probe now on " + owner,
                    "terrain_near_object": f"terrain, {owner} {near.get('height', 0):.2f} m high at {near.get('distance')} m",
                    "object_top": f"top of {owner}, {m.get('discrimination', 0):.2f} m above the terrain under the disc" +
                                  (" (second drop)" if m.get("again_of") else ""),
                    "view": f"screenshot spot, {m.get('distance_to_target_m')} m south of {owner}"}[m["kind"]]
            lines.append(f"    {p['label']:<30} x {p['x']:>10.4f}  y {p['y']:>10.4f}  -> {p['expect']:.4f}   {what}")
    lines += ["", "Files: " + ", ".join(pl) + ", Data\\ (core64's BTD, its meshes\\terrain copy and mask; converted meshes,",
              "geometries, materials, textures under fo4core\\), objects.json, formids.json, skipped.json, plan.json,",
              "expected.json, offline_check.json (make_core64c.py check). Uninstall: exp_install.py uninstall.",
              "Data\\ is hard-linked to the conversion work folder (no second copy): a rewrite there changes this tree. Before",
              "installing run make_core64c.py verify-data --out <this folder> (sizes and times as checked; exit 1 if any differ)."]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------------------------------------------- check
def abs_stats(values):
    v = np.abs(np.asarray(values, np.float64))
    return {"count": int(v.size), "median_mm": round(float(np.median(v)) * 1000, 2),
            "p95_mm": round(float(np.percentile(v, 95)) * 1000, 2), "p99_mm": round(float(np.percentile(v, 99)) * 1000, 2),
            "max_mm": round(float(v.max()) * 1000, 2), "within_1cm": int((v <= 0.01).sum()),
            "within_5cm": int((v <= 0.05).sum())}


def compound_top(fo4_data, owner, x, y, drop_z):
    """FO4's own collision top of `owner` at (x, y) below drop_z, for models whose bodies routes.collision_bodies
    skips (hknpDynamicCompoundShape): every bhkNPCollisionObject body of the source NIF decoded with Codex's
    fo4_compounds.decode_body (instances applied), placed like routes.collision_bodies places a body (node world
    transform, Havok units = metres) and then like the reference. Bodies with their own position or rotation are not
    placed (that convention is unverified, fo4collision.decode_bodies) and are counted. Returns (top, layer, report)."""
    sys.path.insert(0, os.path.join(REPO, "scripts", "game"))
    import routes
    from fo4sf import ba2, fo4_compounds, hkpackfile, nif as nifmod
    name = "meshes\\" + owner["model"].replace("/", "\\").split("\\", 1)[1]
    blob = None
    for fn in sorted(os.listdir(fo4_data)):
        if fn.lower().startswith("fallout4 - meshes") and fn.lower().endswith(".ba2"):
            arc = ba2.Ba2(os.path.join(fo4_data, fn))
            if arc.find(name) is not None:
                blob = arc.read(name)
                break
    rep = {"model": name, "bodies": 0, "leaves": 0, "skipped_body_transform": 0, "errors": []}
    if blob is None:
        rep["errors"].append("not in the FO4 mesh archives")
        return None, None, rep
    f = nifmod.parse(blob)
    world = nifmod.world_transforms(f)
    tops = []
    for i in range(len(f.blocks)):
        if f.type_of(i) != "bhkNPCollisionObject":
            continue
        target, _, data = struct.unpack_from("<iHi", f.blocks[i], 0)
        body = struct.unpack_from("<I", f.blocks[i], 10)[0] if len(f.blocks[i]) >= 14 else 0
        if not (0 <= data < len(f.blocks)) or f.type_of(data) != "bhkPhysicsSystem":
            continue
        n, = struct.unpack_from("<I", f.blocks[data], 0)
        pack_blob = f.blocks[data][4:4 + n]
        try:
            d = fo4_compounds.decode_body(pack_blob, body)
            p = hkpackfile.Packfile(pack_blob)
            sysobj = next(o for o, c in p.objects() if c == "hknpPhysicsSystemData")
            at, _nb = p.array(sysobj + 64)
            layer = p.unpack("<I", at + 96 * body + 20)[0] & 0x7F
        except (hkpackfile.PackfileError, IndexError, StopIteration, ValueError, struct.error) as e:
            rep["errors"].append(f"body {body}: {type(e).__name__}: {e}")
            continue
        rep["bodies"] += 1
        q = d["quaternion_xyzw"]
        if any(abs(v) > 1e-6 for v in d["position_havok_units"]) or abs(abs(q[3]) - 1.0) > 1e-6:
            rep["skipped_body_transform"] += 1
            continue
        tr, rot, _ = world(target)
        for leaf in d["leaves"]:
            rep["leaves"] += 1
            pts = [exterior.to_world(tuple(a + b * routes.UNIT for a, b in zip(routes.apply(rot, v), tr)),
                                     owner["pos"], owner["rot"], owner["scale"]) for v in leaf["points"]]
            z = exterior.top_z([tuple(pts[k] for k in t) for t in leaf["triangles"]], x, y, below=drop_z)
            if z is not None:
                tops.append((z, layer))
    top, layer = max(tops) if tops else (None, None)
    return top, layer, rep


def signed_stats(values):
    v = np.asarray(values, np.float64)
    return {k: round(float(np.percentile(v, q)), 4) for k, q in (("p1", 1), ("median", 50), ("p99", 99))} | {
        "min": round(float(v.min()), 4), "max": round(float(v.max()), 4)}


def archive_dry_run(archive2, out, scratch, files):
    """Build the archive exp_install.py --pack would build (Archive2 -format=General -compression=None, every top-level
    folder of Data) into `scratch`, read its header back and delete it: (report, problems)."""
    from fo4sf import ba2
    data = os.path.join(out, "Data")
    os.makedirs(scratch, exist_ok=True)
    path = os.path.join(scratch, "core64c_dry - Main.ba2")
    folders = sorted(d for d in os.listdir(data) if os.path.isdir(os.path.join(data, d)))
    t0 = time.time()
    r = subprocess.run([archive2, ",".join(folders), f"-create={path}", f"-root={data}", "-format=General",
                        "-compression=None"], cwd=data, capture_output=True, text=True)
    rep = {"seconds": round(time.time() - t0, 1), "returncode": r.returncode}
    problems = []
    try:
        if r.returncode != 0 or not os.path.isfile(path):
            return rep, [f"Archive2 failed: {(r.stdout or '')[-300:]} {(r.stderr or '')[-300:]}"]
        rep["bytes"] = os.path.getsize(path)
        arc = ba2.Ba2(path)
        rep["entries"] = len(arc.entries)
        rep["packed_entries"] = sum(1 for e in arc.entries if e.packed)
        names = {e.name.replace("\\", "/").lower() for e in arc.entries}
        want = {n.lower() for n, _ in files}
        rep["missing"] = sorted(want - names)[:20]
        rep["extra"] = sorted(names - want)[:20]
        if rep["packed_entries"]:
            problems.append(f"{rep['packed_entries']} entries packed")
        if names != want:
            problems.append("archive entries differ from the Data tree")
        return rep, problems
    finally:
        if os.path.exists(path):
            os.remove(path)


def cmd_check(a):
    import make_cw_overlays as cwo
    t0 = time.time()
    out = a.out
    prm, ov = core_params(out)
    cprm, _cov = core_params(a.core)
    plan = load(os.path.join(out, "plan.json"))
    exp = load(os.path.join(out, "expected.json"))
    objects = load(os.path.join(out, "objects.json"))
    ids = load(os.path.join(out, "formids.json"))
    checks, rep = [], {}

    def need(cond, what):
        checks.append([what, bool(cond)])

    # 1. core64 unchanged: params, Data files, Mars plugin, every core64 record of the main plugin
    need({k: v for k, v in prm.items() if k != "objects"} == cprm and prm.get("objects") == "objects.json",
         "overlays_params.json = core64's + objects")
    for rel in exp["base_files"] + [prm["mars"]["plugin"]]:
        need(os.path.isfile(os.path.join(a.core, *rel.split("/"))) and
             x2c.sha256(os.path.join(out, *rel.split("/"))) == x2c.sha256(os.path.join(a.core, *rel.split("/"))),
             f"{rel} byte-identical to core64")
    terrain = Terrain(os.path.join(out, *ov["btd_file"].split("/")))
    def need_core64(cond, what):
        # core64's anchor ref in overlays_params.json carries an assumed load-order byte; core64c's plan has no anchor
        need(cond, what + " (core64's anchor; core64c's plan has no anchor and assumes no load-order index)"
             if "load-order byte" in what else what)
    cwo.check_plugins(out, prm, {ov["tag"]: terrain.raw}, need_core64, rep,
                      overlay_records.vanilla_mars_count(a.sf_data))
    mk = cwo.mask_report(out, ov["world"], ov["n"], tuple(ov["mask_outer_edges"]))
    need(mk["pixels_differ"] == 0, f"mask exact ({mk['outer_edges']})")
    old = overlay_records.walk_plugin(os.path.join(a.core, prm["plugin"]))
    new = overlay_records.walk_plugin(os.path.join(out, prm["plugin"]))
    by = {r["fid"]: r for r in new["records"]}
    same = sum(1 for r in old["records"] if r["fid"] in by and by[r["fid"]]["sig"] == r["sig"]
               and by[r["fid"]]["flags"] == r["flags"] and by[r["fid"]]["fields"] == r["fields"])
    need(same == len(old["records"]), f"every core64 record unchanged ({same}/{len(old['records'])})")
    old_max = max(r["fid"] & 0xFFFFFF for r in old["records"])
    old_fids = {o["fid"] for o in old["records"]}
    added = [r for r in new["records"] if r["fid"] not in old_fids]
    need(added and min(r["fid"] & 0xFFFFFF for r in added) > old_max,
         f"every new record's FormID after core64's last (0x{old_max:06X})")
    need(new["masters"] == ["Starfield.esm"], f"masters {new['masters']}")
    del old

    # 2. object records: STAT / DOOR = bases, models, dependencies, REFRs as objects.json, cells
    own = len(new["masters"]) << 24
    recs = new["records"]
    stats = [r for r in recs if r["sig"] in ("STAT", "DOOR")]
    need(len(stats) == len(objects["bases"]), f"{len(stats):,} STAT/DOOR = {len(objects['bases']):,} bases")
    from fo4sf import fo4land
    missing = [m for m in (fo4land.zstring(overlay_records.field(r, "MODL", b"")) for r in stats)
               if not os.path.isfile(os.path.join(out, "Data", "meshes", m))]
    need(not missing, f"every base model is in Data\\meshes ({len(missing)} missing: {missing[:5]})")
    problems, worst_pos, worst_rot = x2c.ref_record_check(recs, own, objects, ids)
    need(not problems, f"every REFR matches objects.json ({len(problems)} problems: {problems[:3]})")
    need(worst_pos < 1e-3 and worst_rot < 1e-5, f"REFR position / rotation as written (worst {worst_pos:.2e} m, {worst_rot:.2e} rad)")
    refrs = sum(1 for r in recs if r["sig"] == "REFR")
    need(refrs == len(objects["refs"]) + 2, f"{refrs:,} REFR = {len(objects['refs']):,} objects + COC marker + anchor")
    rep["plugin_records"] = {s: sum(1 for r in recs if r["sig"] == s) for s in sorted({r["sig"] for r in recs})}
    rep["plugin_bytes"] = new["bytes"]
    del new, recs, by, stats
    cells = x2c.walk_cells(os.path.join(out, prm["plugin"]))
    per_cell = {}
    for r in objects["refs"]:
        per_cell[tuple(r["cell"])] = per_cell.get(tuple(r["cell"]), 0) + 1
    want = dict(per_cell)
    want[tuple(ov["spawn_cell"])] = want.get(tuple(ov["spawn_cell"]), 0) + 1        # + the COC marker
    got = {c["grid"]: len(c["refs"]) for c in cells.values() if c["grid"] is not None and c["refs"]}
    need(got == want, f"REFRs per exterior cell as objects.json ({len(got):,} cells with references)")
    wrong = [r["src"] for r in objects["refs"] if list(r["cell"]) != list(tg.sf_cell_of(r["pos"][0], r["pos"][1]))]
    need(not wrong, f"every reference in the cell of its written position ({len(wrong)} not: {wrong[:5]})")
    rep["cells"] = {"with_refs": len(got), "max_refs": max(got.values()), "densest": sorted(
        ([list(k), v] for k, v in got.items()), key=lambda kv: -kv[1])[:5]}
    deps = x2c.dependency_check(os.path.join(out, "Data"), [b["model"] for b in objects["bases"]], prefix=ASSET_PREFIX,
                                vanilla=x2c.vanilla_textures(a.sf_data))
    need(not deps["missing"], f"every geometry / material / texture the models name exists ({deps['missing_count']} "
                              f"missing: {deps['missing'][:5]}; {deps['counts']})")
    rep["dependencies"] = deps

    # 3. object z - terrain z under every placed origin: the BTD, and with --fo4 FO4's own LAND
    pos = np.array([r["pos"] for r in objects["refs"]], np.float64)
    g = terrain.bilinear(pos[:, 0], pos[:, 1])
    dz = pos[:, 2] - g
    rep["object_minus_btd"] = {"objects": int(len(dz)), "abs": abs_stats(dz), "signed_m": signed_stats(dz), "histogram_m": {
        f"{lo}..{hi}": int(((dz >= lo) & (dz < hi)).sum()) for lo, hi in
        ((-500, -1), (-1, -0.25), (-0.25, -0.05), (-0.05, 0.05), (0.05, 0.25), (0.25, 1), (1, 500))}}
    by_src = {r["src"]: i for i, r in enumerate(objects["refs"])}
    k = by_src.get(STATION)
    if k is not None:
        gb = terrain.bilinear([pos[k, 0]], [pos[k, 1]])[0]
        need(abs(pos[k, 2] - gb) <= terrain.step, f"Red Rocket station z - BTD = {(pos[k, 2] - gb) * 1000:.2f} mm "
                                                     f"(within one step {terrain.step * 1000:.2f} mm)")
    if a.fo4:
        xs, ys = pos[:, 0] * 70.0 / 4096.0, pos[:, 1] * 70.0 / 4096.0
        box = (int(math.floor(xs.min())) - 1, int(math.floor(xs.max())) + 1, int(math.floor(ys.min())) - 1,
               int(math.floor(ys.max())) + 1)
        g4 = np.array([np.nan if v is None else v for v in x2c.fo4_ground(a.fo4, objects["refs"], box)], np.float64)
        ok = np.isfinite(g4)
        diff = g[ok] - g4[ok]
        rep["btd_minus_fo4_land_under_objects"] = abs_stats(diff)
        worst = np.argsort(-np.abs(diff))[:5]
        idx = np.nonzero(ok)[0]
        rep["btd_minus_fo4_land_under_objects"]["worst"] = [
            {"src": objects["refs"][idx[j]]["src"], "pos": objects["refs"][idx[j]]["pos"],
             "edid": objects["bases"][objects["refs"][idx[j]]["base"]]["edid"], "btd_minus_fo4_mm": round(float(diff[j]) * 1000, 1)}
            for j in worst]
        rep["btd_minus_fo4_land_under_objects"]["no_fo4_land"] = int((~ok).sum())
        dz4 = pos[ok, 2] - g4[ok]
        rep["object_minus_fo4_land"] = {"abs": abs_stats(dz4), "signed_m": signed_stats(dz4)}
        if k is not None:
            need(abs(pos[k, 2] - g4[k]) < 1e-3, f"Red Rocket station z - FO4 LAND = {(pos[k, 2] - g4[k]) * 1000:.2f} mm (FO4: 0)")
        s = rep["btd_minus_fo4_land_under_objects"]
        print(f"BTD - FO4 LAND under {s['count']:,} origins: median {s['median_mm']} mm, p99 {s['p99_mm']} mm, "
              f"max {s['max_mm']} mm")

    # 4. every plan point re-derived from the converted collision (local world) and the predicted verdicts
    bases, placed = objects["bases"], [dict(r) for r in objects["refs"]]
    sx, sy = ov["spawn"][:2]
    world = CoreWorld(os.path.join(out, "Data"), bases, placed, terrain, (sx - AREA_M, sy - AREA_M, sx + AREA_M, sy + AREA_M))
    need(not world.collision_errors, f"local world: converted collision decodes ({len(world.collision_errors)} errors)")
    metas = {(q["entry"], q["label"]): q for q in exp["points"]}
    kinds = {kk: q["kind"] for kk, q in metas.items()}
    core_plan = load(os.path.join(a.core, "plan.json"))
    pr = validate_plan(plan, core_plan[0], kinds)
    need(not pr, f"plan entries: runner keys, core64's keys carried, z_ref on its terrain reference ({pr[:3]})")
    land0 = world.landing(*ov["spawn"])
    need(all(abs(land0["centre"] - e["spawn_local"][2]) < 1e-3 and e["spawn_local"][:2] == ov["spawn"][:2] for e in plan),
         f"spawn_local = where the player lands under the COC marker ({land0['centre']:.4f})")
    need(exterior.clearance(world.index, ov["spawn"][0], ov["spawn"][1], land0["centre"]) >= x2c.PLAYER_HEIGHT,
         "room for the player above the arrival")
    pts = []
    for e, entry in enumerate(plan):
        need(entry["coc"] == ov["coc"], f"entry {e + 1}: coc {entry['coc']}")
        p0 = entry["points"][0]
        d0 = math.hypot(p0["x"] - sx, p0["y"] - sy)
        need(entry.get("hop_m") == HOP_M and entry.get("hop_wait_ms") == HOP_WAIT_MS and d0 <= FIRST_POINT_MAX_M,
             f"entry {e + 1}: first point {p0['label']} {d0:.1f} m from the arrival (the runner never hops there), "
             f"hop_m {entry.get('hop_m')}, hop_wait_ms {entry.get('hop_wait_ms')}")
        travel = entry_travel((sx, sy), entry)
        need(travel["max_axis_cells"] <= MAX_AXIS_CELLS,
             f"entry {e + 1}: each of the runner's {travel['teleports']} teleports ({travel['hops']} hops) moves the "
             f"player at most {MAX_AXIS_CELLS} cells along each axis whatever the merge offset (longest single-axis move "
             f"{travel['max_axis_move_m']} m; at most {travel['max_axis_cells_core64']} cells in core64's frame)")
        need(travel["margin_s"] >= MIN_MARGIN_S,
             f"entry {e + 1}: about {travel['estimated_s']} s to the last point of the {travel['timeout_s']} s step "
             f"timeout ({travel['margin_s']} s to spare, at least {MIN_MARGIN_S:.0f})")
        rep.setdefault("travel", []).append({k: v for k, v in travel.items() if k != "moves"})
        low = min(p["expect"] for p in entry["points"])
        need(entry["settle_ms"] >= 1000.0 * cwo.fall_seconds(entry["drop_z"], low),
             f"entry {e + 1}: settle {entry['settle_ms']} ms covers the fall")
        here = ov["spawn"][:2]
        for p in entry["points"]:
            meta = metas[(e, p["label"])]
            d = math.hypot(p["x"] - sx, p["y"] - sy)
            need(d <= NEAR_M, f"{p['label']}: {d:.0f} m from the arrival (<= {NEAR_M:.0f})")
            land = world.landing(p["x"], p["y"], entry["drop_z"])
            if meta["kind"] in ("terrain", "terrain_ref", "terrain_near_object", "view"):
                hs = world.ground_all(p["x"], p["y"])
                err = max(abs(v - p["expect"]) for v in hs.values())
                need(not land["on_object"] and err <= world.step, f"{p['label']}: terrain, decoded within one step")
                if meta["kind"] != "terrain_near_object":
                    near = exterior.nearby_object(world.index.top, world.ground, p["x"], p["y"], entry["drop_z"],
                                                  radii=x2c.TERRAIN_CLEAR_RADII)
                    need(near is None, f"{p['label']}: no object within {x2c.TERRAIN_CLEAR_RADII[-1]} m")
                if meta["kind"] == "terrain_ref":
                    need(x2c.reference_ok(world, p["x"], p["y"]) is not None, f"{p['label']} (entry {e + 1}): level open terrain")
            else:
                owner = world.by_src[meta["owner"]["src"]]
                err = abs(land["centre"] - p["expect"])
                need(land["on_object"] and land["owner"] == owner and err < 1e-3,
                     f"{p['label']}: lands on {meta['owner']['edid']} at {p['expect']} (error {err * 1000:.2f} mm)")
                if e == 1:
                    dd = x2c.discrimination(world, p["x"], p["y"], p["expect"])
                    need(dd >= x2c.MIN_DISCRIMINATION, f"{p['label']}: {dd:.2f} m above the terrain under its disc")
            tops = [s[0][0] for dx, dy in exterior.disc_offsets(1.0) if (s := world.index.surfaces(p["x"] + dx, p["y"] + dy))]
            need(entry["drop_z"] >= max(tops + [p["expect"]]) + TOP_CLEAR - 1e-6,
                 f"{p['label']}: drop_z {entry['drop_z']} >= every collision top within 1 m + {TOP_CLEAR:g}")
            pts.append({"entry": e, "label": p["label"], "kind": meta["kind"], "expect": p["expect"],
                        "landing": x2c.landing_json(world, land), "error_mm": round(err * 1000, 3),
                        "from_previous_m": round(math.hypot(p["x"] - here[0], p["y"] - here[1]), 1)})
            here = (p["x"], p["y"])
        meta = {p["label"]: metas[(e, p["label"])] for p in entry["points"]}
        pred = {sc: x2c.judge_heights(entry["points"], scenario_reads(world, entry, meta, sc), entry["z_ref"])[:2]
                for sc in SCENARIOS[e]}
        need(x2c.judge_heights(entry["points"], [p["expect"] for p in entry["points"]], entry["z_ref"])[0] == "PASS",
             f"entry {e + 1} passes on its own expectations")
        if e == 0:
            need(pred["flat_terrain"][0] == "FAIL" and pred["no_objects"][0] == "PASS",
                 f"entry 1 fails on flat terrain ({pred['flat_terrain'][1]:.2f} m) and does not depend on the objects")
        if e == 1:
            need(pred["no_objects"][0] == "FAIL" and pred["no_objects"][1] >= x2c.MIN_DISCRIMINATION,
                 f"entry 2 fails without the objects (worst {pred['no_objects'][1]:.2f} m)")
    rep["points"] = pts
    if a.fo4_data:
        rep["fo4_collision_tops"] = x2c.fo4_collision_tops(a.fo4_data, plan, metas)
        for t in rep["fo4_collision_tops"]:
            t["decoder"] = "routes.collision_bodies"
            if t["fo4_top"] is None:                    # compound bodies: Codex's fo4_compounds decoder instead
                drop = plan[t["entry"]]["drop_z"]
                pt = next(p for p in plan[t["entry"]]["points"] if p["label"] == t["label"])
                top, layer, crep = compound_top(a.fo4_data, metas[(t["entry"], t["label"])]["owner"], pt["x"], pt["y"], drop)
                t.update(fo4_top=None if top is None else round(top, 5), layer=layer, decoder="fo4_compounds.decode_body",
                         compound=crep, diff_mm=None if top is None else round((top - t["expect"]) * 1000, 3))
        for t in rep["fo4_collision_tops"]:
            if t["entry"] == 1:
                need(t["diff_mm"] is not None and abs(t["diff_mm"]) < 1.0 and t["layer"] == 1,
                     f"{t['label']}: FO4's own collision top {t['fo4_top']} (layer {t['layer']}) = expect ({t['diff_mm']} mm)")

    # 5. the archive the installer builds: one General archive, every entry stored, below 4 GiB
    files = data_files(out)
    est = ba2_size(files)
    rep["archive"] = {"files": len(files), "data_bytes": sum(b for _, b in files), "estimate_bytes": est,
                      "by_folder": {f: sum(b for n, b in files if n.split("/")[0].lower() == f)
                                    for f in sorted({n.split("/")[0].lower() for n, _ in files})}}
    need(est < ARCHIVE_LIMIT, f"one stored archive about {est / 2 ** 30:.3f} GiB < 4 GiB")
    need(all(n.isascii() for n, _ in files), "archive paths are plain ASCII")
    # FO4's own file names keep their spaces (e.g. "loose planks 01.nif"); exp2c packed 33 such paths the same way
    # and its objects loaded in game, so they are counted, not refused
    rep["archive"]["paths_with_spaces"] = sum(1 for n, _ in files if " " in n)
    if a.archive2 and a.scratch:
        dry, probs = archive_dry_run(a.archive2, out, a.scratch, files)
        rep["archive"]["dry_run"] = dry
        need(not probs and dry.get("bytes", ARCHIVE_LIMIT) < ARCHIVE_LIMIT,
             f"Archive2 dry run: {dry.get('bytes', 0) / 2 ** 30:.3f} GiB, {dry.get('entries')} entries, "
             f"{dry.get('packed_entries')} packed ({probs})")
    rep["checks"] = checks
    rep["pass"] = all(c[1] for c in checks)
    man = data_manifest(out, [prm["plugin"], prm["mars"]["plugin"]])
    save(os.path.join(out, MANIFEST), {"checked": time.strftime("%Y-%m-%dT%H:%M:%S"), "pass": rep["pass"], "files": man})
    rep["data_manifest"] = {"file": MANIFEST, "files": len(man)}
    rep["seconds"] = round(time.time() - t0, 1)
    save(os.path.join(out, "offline_check.json"), rep, indent=1)
    for what, good in checks:
        if not good or len(checks) < 400:
            print(("  ok   " if good else "  FAIL ") + what)
    print(f"{sum(1 for c in checks if c[1])} of {len(checks)} checks ok; {rep['seconds']} s")
    print("CHECK", "PASS" if rep["pass"] else "FAIL")
    return 0 if rep["pass"] else 1


MANIFEST = "data_manifest.json"


def data_manifest(out, plugins=()):
    """{path under out: [size, mtime_ns]} of every file of out\\Data and the given plugins. Data is hard-linked to the
    conversion work folder: an in-place rewrite there changes the staged file's size or time (a replaced file, a new
    link, leaves it alone)."""
    files = {}
    for root, _dirs, names in os.walk(os.path.join(out, "Data")):
        for n in names:
            path = os.path.join(root, n)
            st = os.stat(path)
            files[os.path.relpath(path, out).replace(os.sep, "/")] = [st.st_size, st.st_mtime_ns]
    for pl in plugins:
        st = os.stat(os.path.join(out, pl))
        files[pl] = [st.st_size, st.st_mtime_ns]
    return files


def manifest_diff(old, new):
    return {"missing": sorted(set(old) - set(new)), "added": sorted(set(new) - set(old)),
            "changed": sorted(k for k in set(old) & set(new) if list(old[k]) != list(new[k]))}


def cmd_verify_data(a):
    """Is the staged tree still the one `check` passed? Exit 0 only if it passed and nothing changed since."""
    path = os.path.join(a.out, MANIFEST)
    if not os.path.isfile(path):
        print(f"no {MANIFEST}: run make_core64c.py check first")
        return 1
    m = load(path)
    prm, _ov = core_params(a.out)
    diff = manifest_diff(m["files"], data_manifest(a.out, [prm["plugin"], prm["mars"]["plugin"]]))
    for k, v in diff.items():
        if v:
            print(f"{len(v)} {k}: {v[:5]}")
    good = m.get("pass") and not any(diff.values())
    print(f"{len(m['files']):,} files as checked on {m.get('checked')} (check {'PASS' if m.get('pass') else 'FAIL'}): "
          + ("unchanged" if good else "NOT the checked tree"))
    return 0 if good else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--work", required=True)
    s.add_argument("--core", required=True, help="the staged core64 terrain (overlays_params.json, plugins, Data)")
    s = sub.add_parser("measure")
    s.add_argument("--work", required=True)
    s.add_argument("--fo4-data", required=True)
    s.add_argument("--caps", default="256,512,1024,2048")
    s.add_argument("--kind-caps", default="color=1024,normal=512,rough=256,opacity=512",
                   help="per-kind cap sets to price, separated by ';' (convert_batch --max-texture syntax)")
    s.add_argument("--calibrate", default="", help="a finished convert_batch staging (e.g. exp2c's) for the mesh size")
    for name in ("stage", "check"):
        s = sub.add_parser(name)
        s.add_argument("--work", required=True)
        s.add_argument("--core", required=True)
        s.add_argument("--out", required=True)
        if name == "stage":
            s.add_argument("--sf-esm", default="", help="Starfield.esm: build the plugins with dotnet/TerrainOverlays")
            s.add_argument("--views", action="store_true",
                           help="add screenshot spots to entry 3 (useful once the runner sets the time of day, PR #73)")
        else:
            s.add_argument("--sf-data", default="", help="Starfield Data (vanilla Mars entries, texture archives)")
            s.add_argument("--fo4", default="", help="Fallout4.esm: FO4's own terrain under every object")
            s.add_argument("--fo4-data", default="", help="FO4 Data: object tops against FO4's own collision")
            s.add_argument("--archive2", default="", help="Archive2.exe: build the archive into --scratch and measure it")
            s.add_argument("--scratch", default="", help="folder for the Archive2 dry run (deleted afterwards)")
    s = sub.add_parser("verify-data", help="is the staged tree still the one check passed (sizes and times)?")
    s.add_argument("--out", required=True)
    a = ap.parse_args()
    return {"select": cmd_select, "measure": cmd_measure, "stage": cmd_stage, "check": cmd_check,
            "verify-data": cmd_verify_data}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
