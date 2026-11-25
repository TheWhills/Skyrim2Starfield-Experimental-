r"""Skyrim's directional snow baked into the staged exterior's objects (2026-11-25; src/fo4sf/skyrimsnow.py,
docs/terrain/skyrim-objects.md "Snow on rocks").

For the placed references whose Skyrim base has a snow directional material (RockL02Snow, MountainTrim01_LightSN ...),
grouped by mesh (+ alternate textures), snow material, max angle and tilt (skyrimsnow.tilt_key), each group is
converted as a variant model: vertex colours carry the snow mask (skyrimsnow.with_snow) and every opaque material
becomes the two-layer snow material (convert_material.build_snow_mat: the object's own maps under vanilla's snow,
blended by the vertex colour). Then, as alt_textures_patch.py apply: one STAT per variant (a copy of the reference's
current STAT, own EditorID and model), the references pointed at it, the new files copied into <staging>\Data.

    python -I scripts\terrain\snow_bake.py --work C:\Modding\work\sky_all --staging C:\Modding\staging\skyrim_all ^
        --out C:\Modding\work\sky_snow --skyrim-data <Skyrim Data> --content-resources <zip> --texconv <exe> ^
        --starfield-data <Starfield Data> [--model Landscape\Rocks\RockL02.nif] [--dry-run]
--model limits it to one Skyrim mesh (the prototype); without it every snowy reference. Reinstall afterwards.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import convert_material as cm, exterior, skyrimrefs, skyrimsnow  # noqa: E402
import alt_textures_patch as atp  # noqa: E402

FLAT_AO = "Data\\textures\\skyrim\\ground\\_flat_ao.dds"          # in the staged exterior (terrain build)
FLAT_HEIGHT = "Data\\textures\\skyrim\\ground\\_flat_height.dds"
BACKUP = ".before_snow_bake"
SNOW_SEP = "|snow:"


def snow_groups(objects: dict, export_refs: list, dmat: dict, alts: dict, model=None, step: float = 15.0) -> tuple:
    """({variant key: job}, {ref src: variant key}): job = {"nif", "alt", "mato", "max_angle", "falloff", "tilt",
    "edid_from", "refs"}. Only placed references whose Skyrim base has a snow directional material."""
    by_src = {r["formkey"]: r for r in export_refs}
    want = exterior.source_key(model) if model else None
    jobs, refs = {}, {}
    for p in objects["refs"]:
        r = by_src.get(p["src"])
        d = dmat.get((r or {}).get("base_formkey") or "")
        if not d or not skyrimsnow_class(d.get("edid")):
            continue
        if want and exterior.source_key(r["model"]) != want:
            continue
        alt = alts.get(r["base_formkey"])
        tilt = skyrimsnow.tilt_key(exterior.ref_matrix(r["rot"]), step)
        ident = f"{d['edid']}:{d['max_angle']:g}:{tilt[0]}.{tilt[1]}"
        key = exterior.source_key(r["model"], alt) + SNOW_SEP + hashlib.sha1(ident.lower().encode()).hexdigest()[:8]
        job = jobs.setdefault(key, {"nif": "meshes\\" + r["model"].replace("/", "\\").lstrip("\\"), "alt": alt,
                                    "mato": d["edid"], "max_angle": d["max_angle"],
                                    "falloff": d.get("falloff") or list(skyrimsnow.DEFAULT_FALLOFF), "tilt": tilt,
                                    "edid_from": f"{r.get('base_editor_id') or 'Snow'}_T{tilt[0]}_{tilt[1]}", "refs": 0})
        job["refs"] += 1
        refs[p["src"]] = key
    return jobs, refs


def skyrimsnow_class(mato_edid):
    e = (mato_edid or "").lower()
    return "snow" in e and "lod" not in e


def convert(a, jobs: dict) -> dict:
    """Convert every job into <out>\\convert; returns {key: manifest-style item}."""
    sys.path.insert(0, HERE)
    import make_skyrim_objects as M
    from fo4sf import bsa, convert_static, skyrimconvert
    staging = os.path.join(a.out, "convert")
    os.makedirs(staging, exist_ok=True)
    ns = SimpleNamespace(starfield_data=a.starfield_data, collision_template=None, box_collision=False,
                         stair_ramp_layer=31, max_texture=None)
    conv = skyrimconvert.SkyrimConverter(bsa.SkyrimArchives(a.skyrim_data), staging, a.texconv, a.content_resources,
                                         convert_static.collision_template_from_nif(M.box_template_nif(ns)),
                                         prefix=M.ASSET_PREFIX, sf_mesh_template=M.mesh_template(ns),
                                         stair_layer=M.stair_layer(ns))
    conv.skyrim_specular = True
    conv.split_spin = False
    template = cm.read_template_path(a.content_resources, cm.SNOW_TEMPLATE_MAT)
    plain_material = conv._shape_material
    snow_mats = {}

    def snow_material(mat):
        """The two-layer snow material for one of our opaque single-layer materials (None: keep it as it is)."""
        if not mat or mat == conv.neutral or "\\effects\\" in mat.lower() or "decals" in mat.lower():
            return None
        if mat in snow_mats:
            return snow_mats[mat]
        with open(os.path.join(staging, *mat.replace("\\", "/").split("/")), encoding="utf-8-sig") as f:
            one = json.load(f)
        files = {c["Index"]: c["Data"]["FileName"] for o in one["Objects"] for c in o.get("Components", [])
                 if c.get("Type") == "BSMaterial::MRTextureFile"}
        if 2 in files or not all(s in files for s in (0, 1, 3)):     # cutouts (opacity) stay single-layer
            snow_mats[mat] = None
            return None
        stem = os.path.splitext(mat.replace("\\", "/").split("/", 2)[-1])[0]
        rel = f"materials/{M.ASSET_PREFIX}/snow/{stem}.mat"
        built = cm.build_snow_mat(template, "SKY_Snow_" + os.path.basename(stem),
                                  {0: files[0], 1: files[1], 3: files[3], 5: FLAT_AO, 6: FLAT_HEIGHT})
        p = os.path.join(staging, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(cm.dump_mat(built))
        snow_mats[mat] = rel.replace("/", "\\")
        return snow_mats[mat]

    items, failures = {}, {}
    for key in sorted(jobs):
        job = jobs[key]
        up = skyrimsnow.tilt_up(job["tilt"])
        scale, bias = job["falloff"]
        conv.shape_hook = lambda src, shapes, rep, up=up, scale=scale, bias=bias, ang=job["max_angle"]: [
            skyrimsnow.with_snow(s, up, scale, bias, ang) for s in shapes]

        def shape_material(src, s, *args, **kw):
            m = plain_material(src, s, *args, **kw)
            return snow_material(m) or m
        conv._shape_material = shape_material
        r = conv.convert_nif(job["nif"], alt_textures=job["alt"], out_suffix="_snow" + key.rsplit(":", 1)[-1])
        if not r["ok"]:
            failures[key] = r["reason"]
            continue
        items[key] = {"editor_id": exterior.plugin_editor_id(job["edid_from"], "")[:96], "source": key,
                      "model": r["out_name"].replace("/", "\\") + ".nif", "snow_materials": sum(
                          1 for m in r["materials"] if m and "\\snow\\" in m)}
    return items, failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("--work", "--staging", "--out", "--skyrim-data", "--content-resources", "--texconv", "--starfield-data"):
        ap.add_argument(k, required=True)
    ap.add_argument("--model", default="", help="only this Skyrim mesh (e.g. Landscape\\Rocks\\RockL02.nif)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-apply", action="store_true", help="convert only; the staging is left as it is")
    a = ap.parse_args(argv)
    with open(os.path.join(a.staging, "objects.json"), encoding="utf-8") as f:
        objects = json.load(f)
    with open(os.path.join(a.work, "export.json"), encoding="utf-8") as f:
        export_refs = json.load(f)["refs"]
    dmat = skyrimrefs.directional_materials(a.skyrim_data)
    alts = skyrimrefs.alternate_textures(a.skyrim_data)
    jobs, plan_refs = snow_groups(objects, export_refs, dmat, alts, a.model or None)
    models = Counter(j["nif"].lower() for j in jobs.values())
    print(f"{len(plan_refs):,} snowy references, {len(jobs):,} variants of {len(models):,} meshes"
          + (f" (only {a.model})" if a.model else ""))
    if a.dry_run or not jobs:
        return 0
    items, failures = convert(a, jobs)
    for k, why in list(failures.items())[:8]:
        print(f"  not converted: {jobs[k]['nif']}: {why}")
    print(f"converted {len(items):,} variants ({sum(1 for i in items.values() if i['snow_materials'])} with snow "
          f"materials), {len(failures)} failed")
    with open(os.path.join(a.out, "snow_items.json"), "w", encoding="utf-8") as f:
        json.dump({"items": items, "failures": failures, "refs": plan_refs}, f, indent=0)
    if a.no_apply:
        return 0
    prm = json.load(open(os.path.join(a.staging, "overlays_params.json"), encoding="utf-8"))
    plugin_path = os.path.join(a.staging, prm["plugin"])
    formids = json.load(open(os.path.join(a.staging, "formids.json"), encoding="utf-8"))
    with open(plugin_path, "rb") as f:
        plugin = f.read()
    data, objects2, formids2, rep = atp.apply_plan(objects, formids, {k: v.lower() for k, v in plan_refs.items()},
                                                   {k.lower(): dict(v, source=k) for k, v in items.items()}, plugin)
    for path in (plugin_path, os.path.join(a.staging, "objects.json"), os.path.join(a.staging, "formids.json")):
        if not os.path.exists(path + BACKUP):
            shutil.copy2(path, path + BACKUP)
    n = atp.copy_new(os.path.join(a.out, "convert"), os.path.join(a.staging, "Data"), os.path.join(a.out, "copied.txt"))
    if data != plugin:
        with open(plugin_path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(plugin_path + ".tmp", plugin_path)
    atp.save(os.path.join(a.staging, "objects.json"), objects2)
    atp.save(os.path.join(a.staging, "formids.json"), formids2)
    print(f"{rep['new bases']:,} snow STATs added, {rep['references moved']:,} references moved; Data: "
          f"{n['copied']:,} files ({n['bytes'] / 1e6:,.1f} MB)"
          + "".join(f"; {k}: {v}" for k, v in rep.items() if k not in ("new bases", "references moved")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
