"""The gear os_convert.py fitted in Outfit Studio, written as real Starfield files, with a test plugin to wear it.

Why (owner 2026-11-06, os_convert runs 3 and 4): the fit and the weight copy work in Outfit Studio, but neither its
export_file nor BodySlide's build writes Starfield's format for shapes imported from Skyrim: both wrote a Gamebryo
20.2.0.7 NIF with NiTriShape / BSShaderPPLightingProperty, and with no bones at all (skin instance and skin data with
0 bones; only the skin transform, translation (0, 0.0018, -1.632) m). So this pulls the fitted shapes out of the open
project over MCP and writes them with this repo's skinned-NIF writer (the one the converted hairs use).

  1. units: Outfit Studio shows Starfield meshes in its own units around that skin offset (the male body at
     z -114 .. -8). The reference body's vertices (get_shape_geometry) are fitted to the same body read from the game
     (naked_m .mesh, metres, same vertex order) by least squares (an affine map); the residual is reported and the
     run stops when it is over --max-residual.
  2. each gear shape: positions, normals, UVs, triangles (get_shape_geometry), its bones (list_bones) and their
     weights (get_weights all), mapped to metres; at most 4 weights per vertex (the writer's limit), renormalised.
  3. files: meshes\\S2S\\<name>.nif + geometries\\...\\*.mesh with the naked body's own skin binds for
     each bone (the gear's weights are copied from that body, and its positions are in that body mesh's space).
  4. S2SArmorTest.esm: ARMO + ARMA copied from vanilla Clothes_Nightwear_01 (the Robes of Oblivion layout, docs/armor/
     robes-of-oblivion-reference.md) with the worn model pointed at our NIF, and an outfit (OTFT) holding it.
     The material is the nightwear's (shape test: textures will look wrong); real materials come next.

Run with Outfit Studio still holding os_convert's project (do not close it in between):

    python -I scripts\\armor\\os_export.py --starfield "D:\\...\\Starfield" --name Ralof_outfit --out "<MO2 mods>\\S2S Armor Test"
"""
import argparse
import json
import os
import re
import struct
import sys
from typing import Dict, List, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "npc"))

from fo4sf import facefit, sfmesh, sfplugin, skyrimhair  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
import hkx_to_af  # noqa: E402
import npc_hair  # noqa: E402
import os_convert  # noqa: E402
import os_probe  # noqa: E402

PLUGIN = "S2SArmorTest.esm"
TEMPLATE_ARMOR = "Clothes_Nightwear_01"
CHUNK = 20000                         # get_shape_geometry: at most 20000 vertices per call


# ------------------------------------------------------------------------------------- reading tool answers
def _rows(obj, *keys):
    for k in keys:
        if isinstance(obj, dict) and isinstance(obj.get(k), list):
            return obj[k]
    return None


def columns(fmt: str) -> List[str]:
    """Column names of a format text such as "[triangle index, vertex 1, vertex 2, vertex 3]" (lower case)."""
    return [c.strip().lower() for c in fmt.strip().strip("[]").split(",") if c.strip()]


def listed(answer: dict) -> Dict[str, Tuple[List[str], list]]:
    """{prefix: (columns, rows)} of every "<prefix>List" with a "<prefix>Format" in a tool answer (Outfit Studio's
    form, seen 2026-11-06: "triangleFormat": "[triangle index, vertex 1, vertex 2, vertex 3]", "triangleList")."""
    out = {}
    if not isinstance(answer, dict):
        return out
    for k, v in answer.items():
        if k.endswith("List") and isinstance(v, list):
            fmt = answer.get(k[:-4] + "Format")
            out[k[:-4]] = (columns(fmt) if isinstance(fmt, str) else [], v)
    return out


def _pick(cols: List[str], row, names) -> list:
    idx = [next((i for i, c in enumerate(cols) if c == n), None) for n in names]
    return [row[i] for i in idx] if all(i is not None for i in idx) else None


def _by_index(cols, rows, names, default_cols):
    """{vertex index: values} from rows whose first column is an index; the value columns by name, else by position."""
    out = {}
    for r in rows:
        if not isinstance(r, (list, tuple)):
            continue
        vals = _pick(cols, r, names) if cols else None
        if vals is None:
            vals = list(r[1:1 + default_cols])
        out[int(r[0])] = vals
    return out


def geometry(answer: dict) -> Dict[str, list]:
    """positions / normals / uvs (per vertex, in vertex order) and triangles of a get_shape_geometry answer.
    Accepts Outfit Studio's "<x>List" + "<x>Format" rows (first column the index), plain parallel lists
    ({"positions": [[x, y, z], ...]}) or vertex records ({"vertices": [{"index", "position", "normal", "uv"}]})."""
    out = {}
    for prefix, (cols, rows) in listed(answer).items():
        p = prefix.lower()
        if p.startswith("tri"):
            out["triangles"] = [tuple(int(x) for x in r[-3:]) for r in rows if isinstance(r, (list, tuple))]
            continue
        if p.startswith("pos") or (p.startswith("vert") and "nx" not in cols and "u" not in cols):
            d = _by_index(cols, rows, ["x", "y", "z"], 3)
            out["positions"] = [d[i] for i in sorted(d)]
        elif p.startswith("norm"):
            d = _by_index(cols, rows, ["x", "y", "z"], 3)
            out["normals"] = [d[i] for i in sorted(d)]
        elif p.startswith("uv") or p.startswith("tex"):
            d = _by_index(cols, rows, ["u", "v"], 2)
            out["uvs"] = [d[i] for i in sorted(d)]
        elif p.startswith("vert"):                           # one combined vertex list
            for key, names, n in (("positions", ["x", "y", "z"], 3), ("normals", ["nx", "ny", "nz"], 3),
                                  ("uvs", ["u", "v"], 2)):
                d = {}
                for r in rows:
                    vals = _pick(cols, r, names)
                    if vals is not None:
                        d[int(r[0])] = vals
                if d:
                    out[key] = [d[i] for i in sorted(d)]
    # Outfit Studio's vertex records (verified 2026-11-06): "vertexData": [{"index", "normal", "position", "uv"}]
    verts = next((v for v in (_rows(answer, "vertexData"), _rows(answer, "vertices")) if v and isinstance(v[0], dict)),
                 None)
    if verts:
        verts = sorted(verts, key=lambda v: v.get("index", v.get("vertex", 0)))
        for key, names in (("positions", ("position", "pos")), ("normals", ("normal",)), ("uvs", ("uv", "texCoord"))):
            vals = [next((v[n] for n in names if n in v), None) for v in verts]
            if any(x is not None for x in vals) and key not in out:
                out[key] = vals
    for key, names in (("positions", ("positions",)), ("normals", ("normals",)), ("uvs", ("uvs", "UVs"))):
        rows = _rows(answer, *names)
        if rows is not None and key not in out:
            out[key] = rows
    tris = _rows(answer, "triangles", "tris")
    if tris is not None and "triangles" not in out:
        out["triangles"] = [tuple(t.get("vertices") or t.get("indices") or t.get("points")) if isinstance(t, dict)
                            else tuple(t) for t in tris]
    return out


def weight_list(answer: dict) -> List[Tuple[int, float]]:
    """[(vertex, weight)] of a get_weights answer: "<x>List" rows [vertex, weight] (with a "<x>Format"), or
    {"weights": [{"vertex"/"index", "weight"}] | [[v, w]] | {v: w}}."""
    for prefix, (cols, rows) in listed(answer).items():
        if rows and isinstance(rows[0], (list, tuple)) and len(rows[0]) >= 2:
            wi = next((i for i, c in enumerate(cols) if "weight" in c), len(rows[0]) - 1)
            return [(int(r[0]), float(r[wi])) for r in rows]
    w = answer.get("weights") if isinstance(answer, dict) else None
    if w is None and isinstance(answer, dict):
        w = answer.get("vertices")
    if not (isinstance(w, list) and w and isinstance(w[0], dict)) and isinstance(answer, dict):
        # any list of records that carry a weight ("weightData", "vertexWeights", ...)
        w = next((v for v in answer.values() if isinstance(v, list) and v and isinstance(v[0], dict)
                  and any("weight" in k.lower() for k in v[0])), w)
    if isinstance(w, dict):
        return [(int(k), float(v)) for k, v in w.items()]
    out = []
    for r in w or []:
        if isinstance(r, dict):
            wk = next((k for k in r if "weight" in k.lower()), "value")
            out.append((int(r.get("vertex", r.get("index"))), float(r.get(wk))))
        else:
            out.append((int(r[0]), float(r[1])))
    return out


def bone_names(answer: dict) -> List[str]:
    rows = _rows(answer, "bones") or []
    return [r["name"] if isinstance(r, dict) else str(r) for r in rows]


# ------------------------------------------------------------------------------------------------ geometry
def fit_affine(src: np.ndarray, dst: np.ndarray) -> Tuple[np.ndarray, float]:
    """(4x4 affine mapping src points onto dst, RMS residual in dst units) by least squares."""
    a = np.hstack([src, np.ones((len(src), 1))])
    m, *_ = np.linalg.lstsq(a, dst, rcond=None)
    res = float(np.sqrt(np.mean(np.sum((a @ m - dst) ** 2, axis=1))))
    t = np.eye(4)
    t[:3, :3], t[:3, 3] = m[:3].T, m[3]
    return t, res


def apply(t: np.ndarray, pts) -> np.ndarray:
    p = np.asarray(pts, float).reshape(-1, 3)
    return p @ t[:3, :3].T + t[:3, 3]


def turn_normals(t: np.ndarray, normals) -> np.ndarray:
    n = np.asarray(normals, float).reshape(-1, 3) @ np.linalg.inv(t[:3, :3])
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def tangents(pos: np.ndarray, nor: np.ndarray, uvs, tris) -> np.ndarray:
    """Per-vertex tangents from the UV gradients (Lengyel), orthogonalised against the normals."""
    t = np.zeros_like(pos)
    uv = np.asarray(uvs, float).reshape(-1, 2) if len(uvs) else np.zeros((len(pos), 2))
    for a, b, c in tris:
        e1, e2 = pos[b] - pos[a], pos[c] - pos[a]
        d1, d2 = uv[b] - uv[a], uv[c] - uv[a]
        r = d1[0] * d2[1] - d2[0] * d1[1]
        if abs(r) < 1e-12:
            continue
        tv = (e1 * d2[1] - e2 * d1[1]) / r
        t[[a, b, c]] += tv
    t -= nor * np.sum(t * nor, axis=1, keepdims=True)
    bad = np.linalg.norm(t, axis=1) < 1e-9
    if bad.any():                              # no usable UVs: any direction across the normal
        alt = np.cross(nor[bad], np.array([0.0, 0.0, 1.0]))
        alt[np.linalg.norm(alt, axis=1) < 1e-9] = (1.0, 0.0, 0.0)
        t[bad] = alt
    return t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)


def limit_weights(per_vertex: List[Dict[str, float]], k: int = skyrimhair.MAX_WEIGHTS) -> List[List[Tuple[str, float]]]:
    out = []
    for d in per_vertex:
        top = sorted(d.items(), key=lambda kv: -kv[1])[:k]
        s = sum(w for _b, w in top)
        out.append([(b, w / s) for b, w in top] if s > 0 else [])
    return out


# ------------------------------------------------------------------------------------------------ pulling
def pull_shape(s, shape: str, count: int) -> Dict:
    """Geometry and weights of one shape of the open project."""
    geo = {"positions": [], "normals": [], "uvs": []}
    tris, last_keys = None, []
    for start in range(0, max(count, 1), CHUNK):
        inc = ["positions", "normals", "uvs"] + (["triangles"] if start == 0 else [])
        raw = s("get_shape_geometry", shape=shape, start=start, count=min(CHUNK, count - start), include=inc)
        last_keys = list(raw.keys()) if isinstance(raw, dict) else []
        g = geometry(raw)
        for k in geo:
            geo[k] += list(g.get(k) or [])
        if start == 0:
            tris = g.get("triangles")
    if len(geo["positions"]) != count:
        raise os_convert.StepFailed(f"{shape}: {len(geo['positions'])} positions read, {count} vertices "
                                    f"(answer keys: {sorted(last_keys)})")
    if not tris:
        raise os_convert.StepFailed(f"{shape}: no triangles in get_shape_geometry's answer")
    per = [dict() for _ in range(count)]
    for b in bone_names(s("list_bones", shape=shape)):
        for v, w in weight_list(s("get_weights", shape=shape, bone=b, all=True)):
            if 0 <= v < count and w > 0:
                per[v][b] = per[v].get(b, 0.0) + w
    return dict(geo, triangles=tris, weights=per)


def vertex_counts(s) -> Dict[str, int]:
    return {r["name"]: r.get("vertices", 0) for r in s("list_shapes").get("shapes", [])}


# ------------------------------------------------------------------------------------------------ plugin
def armor_records(sf_esm: str, nif_rel: str, name: str, masters: int, full: str, drop=()):
    """[ARMA, ARMO, OTFT] copied from the vanilla template armor with the worn model pointed at nif_rel (Data-relative
    under meshes\\), new EditorIDs and FormIDs. Returns (records, report)."""
    recs = {fid: (t, h, subs) for t, h, subs, fid in sfplugin.records(sf_esm, [b"ARMO", b"ARMA", b"OTFT"])}
    armo = next(((fid, r) for fid, r in recs.items() if r[0] == b"ARMO" and sfplugin.edid(r[2]) == TEMPLATE_ARMOR),
                None)
    if armo is None:
        raise SystemExit(f"no ARMO {TEMPLATE_ARMOR} in {sf_esm}")
    addon = next((struct.unpack_from("<I", bytes(d), 0)[0] for s, d in armo[1][2] if s == b"MODL" and len(d) >= 4
                  and struct.unpack_from("<I", bytes(d), 0)[0] in recs), None)
    if addon is None:
        raise SystemExit(f"{TEMPLATE_ARMOR}: no ARMA")
    otft = next(r for r in recs.values() if r[0] == b"OTFT")
    a_fid, o_fid, t_fid = (sfplugin.new_form_id(i, masters) for i in range(3))
    _t, ah, asubs = recs[addon]
    model = sfplugin.zs(nif_rel)
    asubs = [(sub, d) for sub, d in asubs if sub.decode("latin-1") not in drop]
    arma = (b"ARMA", ah, sfplugin.edit(asubs, {b"EDID": sfplugin.zs(f"S2S_{name}_AA"), b"MOD2": model,
                                                b"MOD3": model}), a_fid)
    osubs, seen = [], False
    for s, d in armo[1][2]:
        if s == b"MODL" and len(d) >= 4 and struct.unpack_from("<I", bytes(d), 0)[0] in recs:
            if seen:
                continue                        # one addon: ours
            seen = True
            d = struct.pack("<I", a_fid) + bytes(d)[4:]
        osubs.append((s, d))
    osubs = sfplugin.edit(osubs, {b"EDID": sfplugin.zs(f"S2S_{name}"), b"FULL": sfplugin.zs(full)})
    armor = (b"ARMO", armo[1][1], osubs, o_fid)
    outfit = (b"OTFT", otft[1], [(b"EDID", sfplugin.zs(f"S2S_{name}_Outfit")), (b"INAM", struct.pack("<I", o_fid))],
              t_fid)
    rep = {"template": TEMPLATE_ARMOR, "template_addon": f"{addon:08X}", "ARMA": f"{a_fid:08X}",
           "ARMO": f"{o_fid:08X}", "OTFT": f"{t_fid:08X}", "model": nif_rel}
    return [arma, armor, outfit], rep


def nif_material(nif_bytes: bytes) -> str:
    m = re.search(rb"[Mm]aterials\\[\x20-\x7e]+?\.mat", nif_bytes)
    return m.group(0).decode("latin-1") if m else ""


# ------------------------------------------------------------------------------------------------ main
def export(client, sf_data: str, name: str, out: str, max_residual: float = 0.002, skip=(), reverse=False) -> Dict:
    s = os_convert.Session(client, os.path.join(out, "_os_export"))
    rep = {"steps": s.rows}
    status = s("get_status")
    body = (status.get("reference") or {}).get("shape")
    gear = [n for n in status.get("outfitShapes", []) if n != body]
    skipped = [n for n in gear if n.lower() in {x.lower() for x in skip}]
    gear = [n for n in gear if n not in skipped]
    rep["skipped"] = skipped
    if reverse:
        gear = gear[::-1]
    if not body or not gear:
        raise os_convert.StepFailed("open project has no reference body or no gear: run os_convert.py first")
    counts = vertex_counts(s)
    female = "_f" in body.lower() or "naked_f" in body.lower()
    nif_bytes, _ = hkx_to_af.vanilla_file(os_convert.SF_BODY[female], sf_data)
    paths, _skin = facefit.starfield_head_parts(nif_bytes)
    real, _w = facefit.mesh_arrays(sfmesh.parse(hkx_to_af.vanilla_file(
        "geometries/" + paths[0].replace("\\", "/") + ".mesh", sf_data)[0]))
    shown = pull_shape(s, body, counts[body])["positions"]
    if len(shown) != len(real):
        raise os_convert.StepFailed(f"body: {len(shown)} vertices in Outfit Studio, {len(real)} in the game's mesh")
    t, res = fit_affine(np.asarray(shown, float), real)
    rep["calibration"] = {"rms_m": res, "matrix": t.round(6).tolist(),
                          "scale": float(np.cbrt(abs(np.linalg.det(t[:3, :3]))))}
    if res > max_residual:
        raise os_convert.StepFailed(f"body calibration residual {res:.4f} m > {max_residual} m")
    shapes = []
    for g in gear:
        d = pull_shape(s, g, counts[g])
        pos = apply(t, d["positions"])
        nor = turn_normals(t, d["normals"]) if len(d["normals"]) == len(pos) else np.tile([0.0, 0.0, 1.0], (len(pos), 1))
        uv = [tuple(map(float, u)) for u in d["uvs"]] if len(d["uvs"]) == len(pos) else [(0.0, 0.0)] * len(pos)
        tri = [tuple(int(i) for i in x) for x in d["triangles"]]
        w = limit_weights(d["weights"])
        missing = sum(1 for x in w if not x)
        shapes.append(skyrimhair.HairShape(g.encode("latin-1"), pos, nor, tangents(pos, nor, uv, tri), uv, tri, w,
                                           -1, -1, -1, colors=[(255, 255, 255, 255)] * len(pos)))
        rep.setdefault("shapes", {})[g] = {"vertices": len(pos), "triangles": len(tri), "unweighted": missing,
                                           "bones": sorted({b for x in w for b, _ in x})}
    world = npc_hair.skeleton_world(hkx_to_af.vanilla_file(npc_hair.SF_SKELETON, sf_data)[0])
    unknown = sorted({b for sh in shapes for x in sh.weights for b, _ in x} - set(world))
    if unknown:
        raise os_convert.StepFailed(f"bones not in Starfield's skeleton: {unknown}")
    body_binds = dict(zip([b.decode("latin-1") for b in _skin.get("bones", [])], _skin.get("binds", [])))
    unbound = sorted({b for sh in shapes for x in sh.weights for b, _ in x} - set(body_binds))
    if unbound:
        raise os_convert.StepFailed(f"bones the body is not skinned to: {unbound}")
    rep["body_transform"] = shape_transform(nif_bytes)
    return dict(rep, shapes_data=shapes, world=world, body_binds=body_binds)


def shape_transform(nif_bytes: bytes):
    """(translation, rotation 9) of the first BSGeometry of a NIF: the lift vanilla worn meshes give their shapes
    (vertices stay in the body mesh's space)."""
    from fo4sf import sfnif
    try:
        n = nifmod.parse(nif_bytes)
    except Exception:                               # not a NIF (synthetic tests): no offset
        return [0.0, 0.0, 0.0], [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]
    for i, b in enumerate(n.blocks):
        if n.type_of(i) == "BSGeometry":
            g = sfnif.parse_bsgeometry(b)
            return [round(float(x), 6) for x in g.translation], [round(float(x), 6) for x in g.rotation]
    return [0.0, 0.0, 0.0], [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]


def anchor_shape(body_binds: Dict[str, tuple], bone: str = "C_Chest"):
    """A 1 mm triangle, all three corners on one bone, to stand first in the NIF (2026-11-06: the game throws a rigid
    bar off the FIRST shape of our NIFs, whichever shape that is; a shape that only moves rigidly cannot stretch)."""
    if bone not in body_binds:
        bone = sorted(body_binds)[0]
    _sp, rot, trans, scale = body_binds[bone]
    r = np.array(rot, float).reshape(3, 3)
    origin = -r.T @ np.array(trans, float) / (float(scale) or 1.0)       # the bone's origin in mesh space
    pos = origin + np.array([[0, 0, 0], [0.001, 0, 0], [0, 0.001, 0]])
    nor = np.tile([0.0, 0.0, 1.0], (3, 1))
    uv = [(0.0, 0.0), (0.01, 0.0), (0.0, 0.01)]
    return skyrimhair.HairShape(b"S2S_Anchor", pos, nor, tangents(pos, nor, uv, [(0, 1, 2)]), uv, [(0, 1, 2)],
                                [[(bone, 1.0)]] * 3, -1, -1, -1, colors=[(255, 255, 255, 255)] * 3)


SPHERE_MARGIN = 0.15   # metres added to the body's per-bone bounding sphere: the gear sits a little outside the body


def body_nif_files(shapes, materials: List[str], body_binds: Dict[str, tuple], out_name: str,
                   transform=None) -> Dict[str, bytes]:
    """{"meshes/<out_name>.nif", "geometries/...mesh"}: the gear skinned with the naked body's own binds (2026-11-06:
    binds from the skeleton's rest world put the gear in tall pillars in game; the positions are calibrated into the
    body mesh's space, so the body's binds are the ones that match). Spheres: the body's, widened by SPHERE_MARGIN."""
    from fo4sf import convert_static, sfmesh, sfnif
    files, skinned = {}, []
    for i, sh in enumerate(shapes):
        bones = sorted({b for vw in sh.weights for b, _w in vw})
        m = skyrimhair._mesh(sh, bones, False)
        data = sfmesh.serialize(m)
        d, f = convert_static.mesh_file_path(data)
        files[f"geometries/{d}/{f}.mesh"] = data
        binds = []
        for b in bones:
            sphere, rot, trans, scale = body_binds[b]
            binds.append((tuple(sphere[:3]) + (float(sphere[3]) + SPHERE_MARGIN,), tuple(rot), tuple(trans), scale))
        skinned.append(sfnif.SkinnedShape(sh.name or f"Shape{i}".encode(), f"{d}\\{f}".encode(),
                                          len(m.triangles) * 3, len(m.positions), materials[i],
                                          [b.encode("latin-1") for b in bones], binds,
                                          *(transform if transform else ())))
    n = sfnif.build_skinned_nif(out_name.rsplit("/", 1)[-1].encode(), skinned)
    files[f"meshes/{out_name}.nif"] = nifmod.serialize(n)
    return files


def write_armor(sf_data: str, out: str, name: str, full: str, shapes, binds: Dict[str, tuple], transform=None,
                anchor: bool = True, drop=()):
    """Write meshes\\S2S\\<name>.nif + its .mesh files and S2SArmorTest.esm (ARMA / ARMO / OTFT from the vanilla
    template) into the mod folder `out`. shapes in the body mesh's space, weights by Starfield bone name; binds per
    bone. Returns (files, records, record report, material, model path)."""
    tpl_arma_nif = None
    sf_esm = os.path.join(sf_data, "Starfield.esm")
    nif_rel = f"S2S\\{name}.nif"
    masters = ["Starfield.esm"]
    recs, prep = armor_records(sf_esm, nif_rel, name, len(masters), full, list(drop))
    model = next((sfplugin_zstring(d) for s_, d in recs[0][2] if s_ == b"MOD2"), "")
    vanilla_arma = next((r for r in sfplugin.records(sf_esm, [b"ARMA"]) if r[3] == int(prep["template_addon"], 16)),
                        None)
    if vanilla_arma is not None:
        vm = next((sfplugin_zstring(d) for s_, d in vanilla_arma[2] if s_ == b"MOD2"), "")
        try:
            tpl_arma_nif = hkx_to_af.vanilla_file("meshes/" + vm.replace("\\", "/"), sf_data)[0]
        except SystemExit:
            tpl_arma_nif = None
    material = nif_material(tpl_arma_nif or b"") or "Materials\\Clothes\\Outfit_Nightwear\\Outfit_Nightwear_01.mat"
    if anchor:
        shapes = [anchor_shape(binds)] + list(shapes)
    files = body_nif_files(shapes, [material] * len(shapes), binds, f"S2S/{name}", transform)
    for rel, data in files.items():
        dst = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
    info = sfplugin.header_info(sf_esm)
    with open(os.path.join(out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, info, author="Skyrim2Starfield armor test", masters=masters))
    return files, recs, prep, material, model


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--name", required=True, help="file / record name, e.g. Ralof_outfit")
    ap.add_argument("--full", default=None, help="the armor's in-game name (default: the name)")
    ap.add_argument("--out", required=True, help="a mod folder (outside the repository)")
    ap.add_argument("--url", default=os_probe.DEFAULT_URL)
    ap.add_argument("--token", default="")
    ap.add_argument("--skip", default="", help="comma-separated shape names to leave out, e.g. MaleBodyStormcloak")
    ap.add_argument("--drop-fields", default="", help="ARMA fields not copied from the vanilla template, e.g. FLLD")
    ap.add_argument("--no-shape-offset", action="store_true",
                    help="leave the shapes at 0 instead of the body's own offset (the old behaviour)")
    ap.add_argument("--no-anchor", dest="anchor", action="store_false",
                    help="leave out the 1 mm one-bone triangle written first (it absorbs the game's first-shape bar)")
    ap.add_argument("--reverse", action="store_true", help="write the shapes in reverse order (spike test)")
    ap.add_argument("--max-residual", type=float, default=0.002, help="metres (default %(default)s)")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    sf_data = os.path.join(a.starfield, "Data")
    client = os_probe.Client(a.url, a.token)
    client.initialize()
    os.makedirs(a.out, exist_ok=True)
    try:
        rep = export(client, sf_data, a.name, a.out, a.max_residual,
                     [x.strip() for x in a.skip.split(",") if x.strip()], a.reverse)
    except os_convert.StepFailed as e:
        print("failed:", e)
        return 1
    shapes, _world, binds = rep.pop("shapes_data"), rep.pop("world"), rep.pop("body_binds")
    files, recs, prep, material, model = write_armor(
        sf_data, a.out, a.name, a.full or a.name.replace("_", " "), shapes, binds,
        None if a.no_shape_offset else rep["body_transform"], a.anchor,
        [x.strip() for x in a.drop_fields.split(",") if x.strip()])
    rep.update(records=prep, material=material, files=sorted(files), model=model,
               arma_fields=[(sub.decode("latin-1"), bytes(d)[:80].hex()) for sub, d in recs[0][2]])
    with open(os.path.join(a.out, "armor_test.json"), "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in rep.items() if k != "steps"}, fh, indent=1)
    if rep.get("skipped"):
        print("left out:", ", ".join(rep["skipped"]))
    print(f"calibration: {rep['calibration']['rms_m'] * 1000:.2f} mm rms, scale {rep['calibration']['scale']:.5f}")
    for g, r in rep["shapes"].items():
        print(f"  {g}: {r['vertices']} vertices, {r['unweighted']} unweighted, {len(r['bones'])} bones")
    print("shape offset:", "none" if a.no_shape_offset else rep["body_transform"][0])
    print("shape order:", ", ".join(rep["shapes"]))
    print("ARMA fields:", " ".join(f for f, _d in rep["arma_fields"]))
    for sub, d in recs[0][2]:
        if sub in (b"FLLD", b"MODL", b"MNAM", b"TNAM", b"SNAM", b"VNAM", b"NAM4", b"NAM6", b"BSMP", b"DNAM"):
            print(f"  {sub.decode()}: {field_text(bytes(d))}")
    print(f"{PLUGIN}: ARMO {prep['ARMO']} (S2S_{a.name}), outfit {prep['OTFT']}; material {material}")
    print(f"in game: player.additem xx{int(prep['ARMO'], 16) & 0xFFFFFF:06X} 1  (xx = {PLUGIN}'s load order index)")
    return 0


def field_text(d: bytes) -> str:
    """A record field for a person: its printable text runs if it holds any, else its bytes in hex (first 48)."""
    runs = [r.decode("latin-1") for r in re.findall(rb"[ -~]{4,}", d)]
    return (" | ".join(runs) + f"  ({len(d)} bytes)") if runs else d[:48].hex() + (" ..." if len(d) > 48 else "")


def sfplugin_zstring(d) -> str:
    return bytes(d).split(b"\0")[0].decode("latin-1")


if __name__ == "__main__":
    sys.exit(main())
