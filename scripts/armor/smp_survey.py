"""Survey Skyrim HDT-SMP / FSMP physics configs and the meshes that use them (read-only): which features the configs
use (bone chains, nets, springs, collision shapes), how long and stiff the chains are, which NIFs point at which
config, whether the shapes and bones a config names exist in those NIFs, and which extra (non-skeleton) bones a
converted mesh would have to carry. Decides the physics route in docs/armor/animation-port.md.

    python -I scripts\\armor\\smp_survey.py --root "<mod folder or Data>" [--root ...] --out C:\\Modding\\work\\smp
    python -I scripts\\armor\\smp_survey.py --root "%SKY%" --skeleton "%SKY%\\meshes\\actors\\character\\character assets\\skeleton.nif" --out ...

A root is any folder holding meshes\\ or SKSE\\ (installer folders such as "00 Core" are found automatically).
"""
import argparse
import json
import os
import struct
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import nif as nifmod  # noqa: E402
from fo4sf import skeletonmap as SM  # noqa: E402
from fo4sf import skyrimnif, skyrimskin  # noqa: E402
from fo4sf import smpconfig as C  # noqa: E402


def find_roots(paths):
    roots = []
    for top in paths:
        for d, ds, _fs in os.walk(top):
            if any(x.lower() in ("meshes", "skse") for x in ds):
                roots.append(d)
                ds[:] = [x for x in ds if x.lower() not in ("meshes", "skse", "textures")]
    return roots or list(paths)


def index(roots):
    """Data-relative lower-case path -> file, for .xml and .nif (later roots override earlier, like a load order)."""
    files = {}
    for r in roots:
        for d, _ds, fs in os.walk(r):
            for f in fs:
                if f.lower().endswith((".xml", ".nif")):
                    p = os.path.join(d, f)
                    files[os.path.relpath(p, r).replace("/", "\\").lower()] = p
    return files


def default_skeleton():
    return set(SM.MAP) | set(SM.SPLIT) | set(SM.UNMAPPED) | set(SM.WORLD.values()) | {
        "NPC Root [Root]", "NPC COM [COM ]", "NPC", "WEAPON", "SHIELD", "AnimObjectA", "AnimObjectB", "AnimObjectL",
        "AnimObjectR", "TailBone01"}


def skeleton_names(path):
    with open(path, "rb") as fh:
        n = nifmod.parse(fh.read())
    return {skyrimnif._name(n, n.blocks[i]).decode("latin-1") for i in range(len(n.blocks))
            if n.type_of(i).endswith("Node")}


def nif_info(path):
    with open(path, "rb") as fh:
        n = nifmod.parse(fh.read())
    shapes, parents = [], {}
    for i, blk in enumerate(n.blocks):
        t = n.type_of(i)
        if t.endswith("TriShape") or t in skyrimnif.NITRI_TYPES:
            shapes.append(skyrimnif._name(n, blk).decode("latin-1"))
        if t.endswith("Node"):
            try:
                for c in nifmod.node_children(n, i):
                    parents[skyrimnif._name(n, n.blocks[c]).decode("latin-1")] = \
                        skyrimnif._name(n, blk).decode("latin-1")
            except struct.error:
                pass
    bones = set()
    try:
        for s in skyrimskin.skinned_shapes(n):
            bones |= {b.decode("latin-1") for b in s.bones}
    except Exception as e:   # noqa: BLE001 - report, keep surveying
        return {"error": f"skin: {e}"}
    return {"configs": C.nif_physics_paths(n), "shapes": shapes, "bones": sorted(bones), "parents": parents}


def survey(roots, skeleton):
    files = index(roots)
    configs, needs, report = {}, Counter(), {"roots": roots}
    for rel, p in sorted(files.items()):
        if not rel.endswith(".xml"):
            continue
        with open(p, "rb") as fh:
            data = fh.read()
        if b"<system" not in data:
            continue
        try:
            cfg = C.parse(data)
        except C.SmpError as e:
            configs[rel] = {"error": str(e)}
            continue
        s = C.summary(cfg)
        needs.update(s["needs"])
        configs[rel] = {"summary": s, "cfg": cfg, "users": []}
    meshes, missing_cfg, errors = 0, Counter(), []
    shape_missing, extra, anchors = Counter(), Counter(), Counter()
    for rel, p in sorted(files.items()):
        if not rel.endswith(".nif"):
            continue
        try:
            info = nif_info(p)
        except Exception as e:   # noqa: BLE001
            errors.append(f"{rel}: {e}")
            continue
        if "error" in info:
            errors.append(f"{rel}: {info['error']}")
            continue
        for cpath in info["configs"]:
            meshes += 1
            key = C.data_relative(cpath)
            entry = configs.get(key)
            if not entry or "cfg" not in entry:
                missing_cfg[key] += 1
                continue
            entry["users"].append(rel)
            chk = C.check_mesh(entry["cfg"], info["shapes"], info["bones"], skeleton)
            shape_missing.update(chk["shapes_missing"])
            for b in chk["extra_bones"]:
                extra[f"{b}  (parent {info['parents'].get(b, '?')})"] += 1
            for g in entry["summary"]["chains"]:
                for a in g["anchors"]:
                    # the skeleton bone the chain hangs from, and the Starfield bone that would carry it
                    host = a if a in skeleton else info["parents"].get(a, "?")
                    sf = [n for n, _w in SM.starfield_of(host)] or ["unmapped"]
                    anchors[f"{host} -> {'/'.join(sf)}"] += 1
    depth = Counter(g["depth"] for e in configs.values() if "summary" in e for g in e["summary"]["chains"])
    dyn = [e["summary"]["dynamic"] for e in configs.values() if "summary" in e]
    stiff = Counter(str(e["summary"]["angular_stiffness_x"]) for e in configs.values() if "summary" in e)
    report.update({
        "configs": len([e for e in configs.values() if "summary" in e]),
        "config_errors": {k: v["error"] for k, v in configs.items() if "error" in v},
        "needs": dict(needs), "chain_depths": dict(sorted(depth.items())),
        "dynamic_bones_per_config": {"max": max(dyn, default=0), "total": sum(dyn)},
        "angular_stiffness_x": dict(stiff.most_common(10)),
        "meshes_with_physics": meshes, "configs_unused": sorted(k for k, v in configs.items()
                                                                 if "users" in v and not v["users"]),
        "missing_configs": dict(missing_cfg), "shapes_named_but_missing": dict(shape_missing.most_common(30)),
        "extra_bones": dict(extra.most_common(40)), "chain_anchors": dict(anchors.most_common(40)),
        "nif_errors": errors[:30], "per_config": {k: v["summary"] for k, v in configs.items() if "summary" in v}})
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", action="append", required=True)
    ap.add_argument("--skeleton", help="Skyrim skeleton.nif (default: the bone names in skeletonmap)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    skeleton = skeleton_names(a.skeleton) if a.skeleton else default_skeleton()
    r = survey(find_roots(a.root), skeleton)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "smp_survey.json"), "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1)
    print(f"{r['configs']} configs, {r['meshes_with_physics']} mesh->config links, roots: {len(r['roots'])}")
    for k in ("needs", "chain_depths", "dynamic_bones_per_config", "angular_stiffness_x", "missing_configs",
              "configs_unused", "shapes_named_but_missing", "chain_anchors", "extra_bones", "config_errors",
              "nif_errors"):
        v = r[k]
        if isinstance(v, dict) and len(v) > 12:
            v = dict(list(v.items())[:12]) | {"...": f"{len(r[k]) - 12} more"}
        elif isinstance(v, list) and len(v) > 12:
            v = v[:12] + [f"... {len(r[k]) - 12} more"]
        print(f"{k}: {v}")
    print(f"report: {os.path.join(a.out, 'smp_survey.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
