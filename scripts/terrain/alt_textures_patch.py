r"""Skyrim's alternate textures on an already staged exterior, without restaging it (2026-11-25; docs/terrain/
skyrim-objects.md "Snowy roads"): every FormID, the grass, LOD, water and planet stay as installed.

Skyrim's snow roads (RoadChunkM01Snow ...) and its ground-matched rock piles, drifts and cliffs are the plain mesh with a
texture swap per shape (MODS, skyrimrefs.alternate_textures). The exterior was staged when the object pipeline grouped
references by mesh only, so those references show the plain textures. This
  plan   reads which placed references (staging objects.json, by Skyrim FormKey) have a base with alternate textures
         (the exterior's export.json for the base, Skyrim.esm + Update.esm + DLC for the swaps) and writes
         <out>/convert_input.json (one entry per mesh + swap) and <out>/alt_plan.json; then convert them:
             python -I scripts\terrain\make_skyrim_objects.py convert --work <out> ... --resume
  apply  adds one STAT per converted variant to the staged plugin (a copy of the plain model's STAT with its own
         EditorID and model; esm_patch.add_records), points those references at it (esm_patch.set_ref_bases, in
         place), copies the variant's new files into <staging>\Data (never overwriting) and records the bases in
         objects.json / formids.json. Idempotent: variants already in objects.json are left alone.
Then reinstall the exterior (tools/owner/alt_textures.ps1 does all of it).

    python -I scripts\terrain\alt_textures_patch.py plan --work C:\Modding\work\sky_all --staging C:\Modding\staging\skyrim_all --skyrim-data <Skyrim Data> --out C:\Modding\work\sky_alt
    python -I scripts\terrain\alt_textures_patch.py apply --work C:\Modding\work\sky_alt --staging C:\Modding\staging\skyrim_all
"""
import argparse
import json
import os
import shutil
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import esm_patch, exterior, skyrimrefs  # noqa: E402

EDID_PREFIX = "SKY_"
DATA_TREES = ("meshes", "geometries", "materials", "textures")
BACKUP = ".before_alt_textures"


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save(path, value, indent=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=indent)
    os.replace(tmp, path)


def plan_variants(objects: dict, export_refs: list, alts: dict) -> tuple:
    """(convert entries [{"model", "type", "formkey", "alt_textures", "base_editor_id"}], {ref src: variant key},
    counts). Only references placed in objects.json whose plain base came from the same mesh."""
    by_src = {r["formkey"]: r for r in export_refs}
    entries, refs, n = {}, {}, Counter()
    for p in objects["refs"]:
        if "#" in p["src"]:                          # turning parts placed with a reference: not a Skyrim reference
            continue
        r = by_src.get(p["src"])
        alt = alts.get(r.get("base_formkey") or "") if r else None
        if not alt:
            continue
        base = objects["bases"][p["base"]]
        if exterior.mesh_of((base.get("source") or "").lower()) != exterior.source_key(r["model"]):   # plain or done
            n["base is not the plain mesh (left as it is)"] += 1
            continue
        key = exterior.source_key(r["model"], alt)
        entries.setdefault(key, {"model": r["model"], "type": r["type"], "formkey": r["formkey"],
                                 "alt_textures": alt, "base_editor_id": r.get("base_editor_id") or ""})
        refs[p["src"]] = key
        n["references"] += 1
    return [entries[k] for k in sorted(entries)], refs, n


def cmd_plan(a):
    objects = load(os.path.join(a.staging, "objects.json"))
    exp = load(os.path.join(a.work, "export.json"))
    alts = skyrimrefs.alternate_textures(a.skyrim_data)
    models, refs, n = plan_variants(objects, exp["refs"], alts)
    save(os.path.join(a.out, "convert_input.json"), {"schema_version": 2, "cell": "skyrim_alt_textures",
                                                    "refs": models})
    save(os.path.join(a.out, "alt_plan.json"), {"refs": refs, "counts": dict(n), "bases_with_alt": len(alts)})
    print(f"{len(alts):,} Skyrim bases have alternate textures; {n['references']:,} placed references use "
          f"{len(models):,} mesh + texture variants" + "".join(f"; {k}: {v}" for k, v in n.items() if k != "references"))
    return 0


def copy_new(src_root, dst_root, log_path=None) -> Counter:
    """Copy files of the converted trees that the staging does not have (never overwriting); log_path lists them, one
    relative path per line, appended (what to delete to undo)."""
    n = Counter()
    log = open(log_path, "a", encoding="utf-8") if log_path else None
    for tree in DATA_TREES:
        for root, _dirs, files in os.walk(os.path.join(src_root, tree)):
            for fn in files:
                s = os.path.join(root, fn)
                d = os.path.join(dst_root, os.path.relpath(s, src_root))
                if os.path.exists(d):
                    n["kept"] += 1
                    continue
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
                if log:
                    log.write(os.path.relpath(s, src_root) + "\n")
                n["copied"] += 1
                n["bytes"] += os.path.getsize(s)
    if log:
        log.close()
    return n


def apply_plan(objects: dict, formids: dict, plan_refs: dict, items: dict, plugin: bytes) -> tuple:
    """The patched plugin, objects.json and formids.json (copies) and a report. items: {variant key: manifest item}."""
    objects = dict(objects, bases=list(objects["bases"]), refs=[dict(r) for r in objects["refs"]])
    formids = dict(formids, bases=dict(formids["bases"]))
    _count, _next, masters = esm_patch.header(plugin)
    have = {(b.get("source") or "").lower(): i for i, b in enumerate(objects["bases"])
            if exterior.ALT_SEP in (b.get("source") or "")}
    taken = {b["edid"].lower() for b in objects["bases"]}
    rep, new = Counter(), []                       # new: [(variant key, edid, template FormID, item, plain base)]
    plain_of = {}
    for p in objects["refs"]:
        key = plan_refs.get(p["src"])
        if key and key in items and key not in have:
            plain_of.setdefault(key, p["base"])
    for key in sorted(plain_of):
        plain = objects["bases"][plain_of[key]]
        if plain.get("door") or plain.get("anim_template") or plain["edid"] not in formids["bases"]:
            rep["variant of a door / turning / unknown base (left as it is)"] += 1
            continue
        edid = exterior.plugin_editor_id(items[key]["editor_id"], EDID_PREFIX)
        if edid.lower() in taken:
            edid += "_Alt"
        if edid.lower() in taken:
            raise ValueError(f"EditorID {edid} taken")
        taken.add(edid.lower())
        new.append((key, edid, (masters << 24) | int(formids["bases"][plain["edid"]], 16), items[key], plain))
    records = [(tpl, {b"EDID": esm_patch.zstring(edid), b"MODL": esm_patch.zstring(item["model"])})
               for _k, edid, tpl, item, _p in new]
    if records:
        plugin, fids = esm_patch.add_records(plugin, b"STAT", records)
    else:
        fids = []
    for (key, edid, _tpl, item, plain), fid in zip(new, fids):
        have[key] = len(objects["bases"])
        objects["bases"].append({k: v for k, v in dict(plain, edid=edid, model=item["model"], source=item["source"])
                                 .items() if k in ("edid", "model", "source", "collision", "bounds")})
        formids["bases"][edid] = f"{fid & 0xFFFFFF:06X}"
    ref_ids = formids["refs"]
    to_set = {}
    for p in objects["refs"]:
        key = plan_refs.get(p["src"])
        if key not in have or p["base"] == have[key]:
            continue
        if p["src"] not in ref_ids:
            rep["reference without a FormID (left as it is)"] += 1
            continue
        b = objects["bases"][have[key]]
        to_set[(masters << 24) | int(ref_ids[p["src"]], 16)] = (masters << 24) | int(formids["bases"][b["edid"]], 16)
        p["base"] = have[key]
    plugin, nset, missing = esm_patch.set_ref_bases(plugin, to_set)
    if missing:
        raise ValueError(f"{len(missing)} references not found in the plugin, e.g. {missing[0]:08X}")
    rep.update({"new bases": len(new), "references moved": nset})
    return plugin, objects, formids, rep


def cmd_apply(a):
    prm = load(os.path.join(a.staging, "overlays_params.json"))
    objects = load(os.path.join(a.staging, "objects.json"))
    formids = load(os.path.join(a.staging, "formids.json"))
    plan = load(os.path.join(a.work, "alt_plan.json"))
    man = load(os.path.join(a.work, "convert", "manifest.json"))
    items = {i["source"].lower(): i for i in man["items"]}
    failed = {f["nif"].lower(): f["reason"] for f in man.get("failures", [])}
    plugin_path = os.path.join(a.staging, prm["plugin"])
    with open(plugin_path, "rb") as f:
        plugin = f.read()
    data, objects2, formids2, rep = apply_plan(objects, formids, {k: v.lower() for k, v in plan["refs"].items()},
                                               items, plugin)
    lost = Counter(failed[v.lower()] for v in plan["refs"].values() if v.lower() in failed)
    if a.dry_run:
        print(dict(rep), f"; not converted: {sum(lost.values())} references")
        return 0
    for path in (plugin_path, os.path.join(a.staging, "objects.json"), os.path.join(a.staging, "formids.json")):
        if not os.path.exists(path + BACKUP):         # one-time backups: the staging as it was before the first apply
            shutil.copy2(path, path + BACKUP)
    n = copy_new(os.path.join(a.work, "convert"), os.path.join(a.staging, "Data"), os.path.join(a.work, "copied.txt"))
    if data != plugin:
        tmp = plugin_path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, plugin_path)
    save(os.path.join(a.staging, "objects.json"), objects2)
    save(os.path.join(a.staging, "formids.json"), formids2)
    print(f"{rep['new bases']:,} variant STATs added, {rep['references moved']:,} references moved to them; Data: "
          f"{n['copied']:,} files copied ({n['bytes'] / 1e6:,.0f} MB), {n['kept']:,} already there"
          + "".join(f"; {k}: {v}" for k, v in rep.items() if k not in ("new bases", "references moved")))
    for reason, c in lost.most_common(8):
        print(f"  not converted, {c} references keep the plain textures: {reason}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--work", required=True, help="the exterior's make_skyrim_objects.py work folder (export.json)")
    p.add_argument("--staging", required=True)
    p.add_argument("--skyrim-data", required=True)
    p.add_argument("--out", required=True, help="work folder for the variants (its own convert)")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("apply")
    p.add_argument("--work", required=True, help="the variants' work folder (plan --out)")
    p.add_argument("--staging", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_apply)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
