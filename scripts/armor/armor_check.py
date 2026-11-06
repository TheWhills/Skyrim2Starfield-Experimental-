"""Find what pulls a converted armor out of shape in game (2026-11-06: after os_export moved to the body's binds the
Stormcloak gear sat on the body, but a thin spike rose from the back of the neck to well above the head).

Reads the armor NIF written by os_export (from the mod folder), its .mesh files and the game's naked body, and reports:
  - body: how many skinned shapes / skin blocks the NIF holds, and for every bone the body's skin lists, how many body
    vertices it moves and whether its bind agrees with the skeleton (bind x rest world should be the same matrix for
    every bone; a bone that disagrees, or that no body vertex uses, can throw gear vertices far away);
  - each armor shape: bones it uses (flagged as above), the vertices weighted to flagged bones, and vertices lying
    far outside the body's box (bad positions).
Writes armor_check.json next to the armor; prints a short summary.

    python -I scripts\\armor\\armor_check.py --starfield "D:\\...\\Starfield" --mod "<mod folder>" --name Ralof_outfit
"""
import argparse
import json
import os
import sys
from typing import Dict, List

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "npc"))

from fo4sf import facefit, sfmesh, sfnif  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
import hkx_to_af  # noqa: E402
import npc_hair  # noqa: E402
import os_convert  # noqa: E402


def bind_matrix(bind, transpose: bool = False) -> np.ndarray:
    """4x4 of a skin bind (sphere, rot 9 row-major, trans 3, scale): mesh point -> bone space."""
    _sp, rot, trans, scale = bind
    r = np.array(rot, float).reshape(3, 3)
    if transpose:
        r = r.T
    m = np.eye(4)
    m[:3, :3] = r * float(scale or 1.0)
    m[:3, 3] = trans
    return m


def bind_agreement(names: List[str], binds: list, world: Dict[str, np.ndarray]):
    """({bone: metres off the common mesh->skeleton map}, transpose used). world[b] @ bind[b] is the same matrix for
    every bone whose bind matches the skeleton; how far each bone's matrix moves points 1 m around differs from the
    median is its error."""
    best = None
    for tr in (False, True):
        ms = {n: world[n] @ bind_matrix(b, tr) for n, b in zip(names, binds) if n in world}
        if not ms:
            return {}, tr
        med = np.median(np.stack(list(ms.values())), axis=0)
        probe = np.array([[0, 0, 0, 1], [1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1]], float).T
        err = {n: float(np.abs((m - med) @ probe)[:3].max()) for n, m in ms.items()}
        score = float(np.median(list(err.values())))
        if best is None or score < best[0]:
            best = (score, err, tr)
    return best[1], best[2]


def nif_shapes(nif_bytes: bytes):
    """[(mesh path LOD0, skin dict)] for each BSGeometry, pairing each with the skin blocks that follow it."""
    n = nifmod.parse(nif_bytes)
    out, types = [], [n.type_of(i) for i in range(len(n.blocks))]
    geo = [i for i, t in enumerate(types) if t == "BSGeometry"]
    for k, i in enumerate(geo):
        g = sfnif.parse_bsgeometry(n.blocks[i])
        paths = [m.path.decode("latin-1") for m in g.meshes if m is not None]
        end = geo[k + 1] if k + 1 < len(geo) else len(n.blocks)
        sub = nifmod.NifFile.__new__(nifmod.NifFile)
        sub.__dict__.update(n.__dict__)
        sub.blocks = n.blocks[:end]
        skin = sfnif.parse_skin(sub)
        out.append((g, paths, skin))
    return out, types


def check(body_nif: bytes, body_mesh: bytes, armor_nif: bytes, armor_meshes: Dict[str, bytes],
          world: Dict[str, np.ndarray], far: float = 0.3) -> Dict:
    rep = {}
    _paths, body_skin = facefit.starfield_head_parts(body_nif)
    bnames = [b.decode("latin-1") for b in body_skin.get("bones", [])]
    bpos, bw = facefit.mesh_arrays(sfmesh.parse(body_mesh))
    used = {n: 0 for n in bnames}
    for vw in bw:
        for bi, w in vw:
            if bi < len(bnames) and w > 0.01:
                used[bnames[bi]] += 1
    err, tr = bind_agreement(bnames, body_skin.get("binds", []), world)
    lo, hi = bpos.min(0) - far, bpos.max(0) + far
    _shapes, types = nif_shapes(body_nif)
    rep["body"] = {"skin_blocks": {t: types.count(t) for t in ("BSGeometry", "SkinAttach", "BSSkin::BoneData")},
                   "box_m": [lo.round(3).tolist(), hi.round(3).tolist()], "transpose": tr,
                   "bones": {n: {"body_vertices": used[n], "bind_error_m": round(err.get(n, -1.0), 4),
                                 "in_skeleton": n in world} for n in bnames}}
    bad = {n for n in bnames if used[n] == 0 or err.get(n, 9.0) > 0.01}
    rep["flagged_bones"] = sorted(bad)
    shapes, _t = nif_shapes(armor_nif)
    rep["shapes"] = {}
    for g, paths, skin in shapes:
        key = "geometries/" + paths[0].replace("\\", "/") + ".mesh"
        names = [b.decode("latin-1") for b in skin.get("bones", [])]
        pos, ws = facefit.mesh_arrays(sfmesh.parse(armor_meshes[key]))
        on_bad = {}
        for v, vw in enumerate(ws):
            for bi, w in vw:
                if names[bi] in bad and w > 0.01:
                    on_bad.setdefault(names[bi], []).append(v)
        out = [v for v, p in enumerate(pos) if np.any(p < lo) or np.any(p > hi)]
        rep["shapes"][paths[0]] = {
            "vertices": len(pos), "bones": names,
            "flagged_bones": {n: {"vertices": len(vs), "first": vs[:5]} for n, vs in on_bad.items()},
            "outside_body_box": len(out),
            "outside_examples": [{"v": v, "m": pos[v].round(3).tolist(),
                                  "weights": [(names[b], round(w, 3)) for b, w in ws[v]]} for v in out[:8]]}
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--mod", required=True, help="the mod folder os_export wrote into")
    ap.add_argument("--name", required=True)
    ap.add_argument("--female", action="store_true")
    a = ap.parse_args(argv)
    data = os.path.join(a.starfield, "Data")
    body_nif, _ = hkx_to_af.vanilla_file(os_convert.SF_BODY[a.female], data)
    paths, _ = facefit.starfield_head_parts(body_nif)
    body_mesh, _ = hkx_to_af.vanilla_file("geometries/" + paths[0].replace("\\", "/") + ".mesh", data)
    with open(os.path.join(a.mod, "meshes", "S2S", f"{a.name}.nif"), "rb") as fh:
        armor_nif = fh.read()
    meshes = {}
    for _g, ps, _s in nif_shapes(armor_nif)[0]:
        rel = "geometries/" + ps[0].replace("\\", "/") + ".mesh"
        with open(os.path.join(a.mod, *rel.split("/")), "rb") as fh:
            meshes[rel] = fh.read()
    world = npc_hair.skeleton_world(hkx_to_af.vanilla_file(npc_hair.SF_SKELETON, data)[0])
    rep = check(body_nif, body_mesh, armor_nif, meshes, world)
    dst = os.path.join(a.mod, "armor_check.json")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print("body:", rep["body"]["skin_blocks"], "transpose" if rep["body"]["transpose"] else "row-major")
    print("flagged body bones (no body vertices or bind off the skeleton):", len(rep["flagged_bones"]))
    for p, s in rep["shapes"].items():
        fb = ", ".join(f"{n} ({v['vertices']})" for n, v in s["flagged_bones"].items()) or "none"
        print(f"  {p}: {s['vertices']} v, outside body box {s['outside_body_box']}, on flagged bones: {fb}")
    print("wrote", dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
