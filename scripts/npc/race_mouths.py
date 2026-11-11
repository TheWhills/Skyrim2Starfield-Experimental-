"""A Skyrim race's own mouth (the orc's teeth and tusks) as that race's Starfield teeth head part (owner 2026-11-10:
"teeth and tusks", races plan step 3).

Skyrim keeps the orc's teeth in a head part of their own (MouthOrc.nif / MouthOrcFemale.nif, 348 vertices, made for the
orc head; race_survey). Starfield's teeth (Human_Male_Teeth / Human_Female_Teeth, type Teeth) are skinned to C_Head
only and open with the performance morph jawOpen (lower teeth drop ~2.5 cm; owner's mouth probe 2026-11-09, verified).
So per sex (decisions.md 2026-11-09, "Plan for converted mouths"):
  1. the Skyrim mouth's shapes, merged into one (one morph record drives one shape), placed on Starfield's head with
     race_heads' head alignment (the Skyrim orc mouth sits on the Skyrim orc head; our race head carries that shape),
     then into the vanilla teeth's own mesh frame (headbake.part_to_head through the C_Head binds);
  2. each vertex marked jaw / upper by Skyrim's Aah expression (mouth_probe.jaw_labels); the vanilla teeth's lower
     vertices are the ones jawOpen moves;
  3. every performance (TMPP) and chargen (TCMP) key of the vanilla teeth copied per vertex from the nearest vanilla
     tooth vertex on the same side, so the lower teeth and tusks drop with jawOpen and follow lip sync;
  4. written as a NIF like the vanilla teeth (C_Head with its bind, its node), the material converted from Skyrim's
     texture set (SkyrimConverter; the vanilla teeth material if no converter), the morph.dat files under
     meshes\\morphs\\s2s\\races\\<race>\\mouth_<m|f>\\{performance,chargen} (each with its morph.dat).
race_heads (--race-shape baked) calls convert_mouth for races in RACE_MOUTHS and makes the head part and its morph
record (race_heads.race_part_records).
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import facefit, headbake, sfmesh, sfmorph, sfnif, skyrimskin, skyrimtri  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
from fo4sf.convert_static import mesh_file_path  # noqa: E402

RACE_MOUTHS = {"OrcRace": "orc"}               # Skyrim race -> mouth_probe.SKY_MOUTHS kind
TEETH_TYPE = 9
JAW_SHARE = 0.25


def skyrim_shapes(data):
    """(NIF, [{"shape", "pts" model space (Skyrim units), "normals", "uvs", "tris", "M"}]) of a Skyrim mouth."""
    n = nifmod.parse(data)
    out = []
    for s in skyrimskin.skinned_shapes(n):
        p = np.asarray(s.positions, float)
        if not len(p):
            continue
        M = np.asarray(facefit.skyrim_model_matrix(n, s), float)
        tris = np.asarray(s.triangles, int).reshape(-1, 3)
        pts = headbake.apply4(M, p)
        if s.normals and len(s.normals) == len(p):
            nr = np.asarray(s.normals, float) @ M[:3, :3].T
        else:
            nr = facefit_normals(pts, tris)
        nr /= np.maximum(np.linalg.norm(nr, axis=1, keepdims=True), 1e-12)
        out.append({"shape": s, "pts": pts, "skin_pts": p, "normals": nr, "uvs": [tuple(map(float, u)) for u in s.uvs]
                    if s.uvs else [(0.0, 0.0)] * len(p), "tris": tris, "M": M})
    return n, out


def facefit_normals(pts, tris):
    from fo4sf import headcorr
    return headcorr.vertex_normals(np.asarray(pts, float), np.asarray(tris, int))


def merge(shapes):
    """One shape from several: (pts, normals, uvs, tris, offsets)."""
    pts, nrm, uvs, tris, offs, base = [], [], [], [], [], 0
    for sh in shapes:
        offs.append(base)
        pts.append(sh["pts"])
        nrm.append(sh["normals"])
        uvs += list(sh["uvs"])
        tris.append(sh["tris"] + base)
        base += len(sh["pts"])
    return np.concatenate(pts), np.concatenate(nrm), uvs, np.concatenate(tris), offs


def jaw_labels(shapes, tri):
    """Per merged vertex: True on the jaw (Skyrim's Aah drops it, mouth_probe.jaw_labels), from the mouth's .tri."""
    import mouth_probe
    aah = next((m["deltas"] for m in tri["morphs"] if m["name"].lower() == "aah"), None) if tri else None
    out = []
    for sh in shapes:
        if aah is None:
            out.append(np.zeros(len(sh["pts"]), bool))
            continue
        jaw, _drop = mouth_probe.jaw_labels(sh["skin_pts"], tri["base"], aah, sh["M"], JAW_SHARE)
        out.append(jaw)
    return np.concatenate(out) if out else np.zeros(0, bool)


def lower_vertices(morph, num_vertices, share=JAW_SHARE):
    """Vanilla teeth vertices jawOpen moves by at least share of its largest move (the lower teeth); all False if
    no such key."""
    key = next((k for k in morph.keys if k.lower() == "jawopen"), None) if morph is not None else None
    out = np.zeros(num_vertices, bool)
    if key is None:
        return out, None
    d = morph.deltas.get(key, {})
    if not d:
        return out, key
    mag = {i: float(np.linalg.norm(v)) for i, v in d.items()}
    top = max(mag.values())
    for i, m in mag.items():
        if i < num_vertices and m >= share * top and m > 0:
            out[i] = True
    return out, key


def side_nearest(points, jaw, sf_pts, sf_lower):
    """Per point the index of the nearest vanilla vertex on the same side (jaw -> lower; any side if that side is
    empty), and the distances."""
    sf_pts = np.asarray(sf_pts, float)
    idx, dist = np.zeros(len(points), int), np.zeros(len(points))
    for side in (True, False):
        mine = np.nonzero(jaw == side)[0]
        pool = np.nonzero(sf_lower == side)[0]
        if not len(pool):
            pool = np.arange(len(sf_pts))
        if not len(mine):
            continue
        j = headbake.nearest(sf_pts[pool], np.asarray(points, float)[mine])
        idx[mine] = pool[j]
        dist[mine] = np.linalg.norm(sf_pts[pool[j]] - np.asarray(points, float)[mine], axis=1)
    return idx, dist


def copied_morph(morph, idx):
    """A morph.dat for vertices that each take vanilla vertex idx[i]'s deltas (and colour / normal / tangent words)."""
    deltas, extra = {}, {}
    for k in morph.keys:
        src, sx = morph.deltas.get(k, {}), morph.extra.get(k, {})
        dk, ek = {}, {}
        for i, j in enumerate(idx):
            j = int(j)
            if j in src:
                dk[i] = src[j]
                if j in sx:
                    ek[i] = sx[j]
        deltas[k], extra[k] = dk, ek
    return sfmorph.build(len(idx), list(morph.keys), deltas, extra)


def vanilla_material(nif_bytes):
    """The material path of a Starfield NIF's first BSGeometry (its BSLightingShaderProperty's name)."""
    import struct
    n = nifmod.parse(nif_bytes)
    for i, b in enumerate(n.blocks):
        if n.type_of(i) == "BSGeometry":
            g = sfnif.parse_bsgeometry(b)
            if 0 <= g.shader < len(n.blocks):
                k, = struct.unpack_from("<i", n.blocks[g.shader], 0)
                if 0 <= k < len(n.strings):
                    return n.strings[k].decode("latin-1")
    return ""


def teeth_template(nif_bytes):
    """(BSGeometry, skin, LOD 0 path) of the vanilla teeth NIF's first geometry with a mesh."""
    n = nifmod.parse(nif_bytes)
    for i, b in enumerate(n.blocks):
        if n.type_of(i) == "BSGeometry":
            g = sfnif.parse_bsgeometry(b)
            refs = [m for m in g.meshes if m is not None]
            if refs:
                return g, headbake.geometry_skin(n, g), refs[0].path.decode("latin-1")
    raise ValueError("teeth NIF without geometry")


def build_mouth(pts, normals, uvs, tris, bind, bones, name, translation, rotation, material):
    """{"mesh path": bytes, nif bytes} of a C_Head-skinned mouth (points in the teeth's mesh frame, metres)."""
    from fo4sf import skyrimhair
    sh = skyrimhair.HairShape(name.encode(), np.asarray(pts, float), np.asarray(normals, float), None,
                              list(uvs), [tuple(int(x) for x in t) for t in tris],
                              [[(bones[0], 1.0)] for _ in range(len(pts))], -1, -1, -1,
                              colors=[(255, 255, 255, 255)] * len(pts))
    hair, _r = skyrimhair.uv_tangents(skyrimhair.Hair([sh], [], {}, {}))
    import dataclasses
    sh = dataclasses.replace(hair.shapes[0], colors=[(255, 255, 255, 255)] * len(pts))   # white: no hair strand colours
    m = skyrimhair._mesh(sh, [bones[0]], False)
    data = sfmesh.serialize(m)
    d, f = mesh_file_path(data)
    nif = sfnif.build_skinned_nif(name.encode(), [sfnif.SkinnedShape(
        name.encode(), f"{d}\\{f}".encode(), len(tris) * 3, len(pts), material, [bones[0].encode()], [bind],
        tuple(translation), tuple(rotation))])
    return f"geometries/{d}/{f}.mesh", data, nifmod.serialize(nif)


def convert_mouth(read_sky, read_sf, sky_path, align, head_pts, head_skin, teeth_nif, teeth_morphs, out_base,
                  material=None):
    """Files and info of a Skyrim mouth as a Starfield teeth part.
    read_sky / read_sf: path -> bytes; sky_path: the Skyrim mouth NIF; align: (s, R, t) Skyrim model -> Starfield head
    mesh frame (race_probe.race_transfer); head_pts / head_skin: the head (mesh frame, its skin); teeth_nif: the
    vanilla teeth NIF; teeth_morphs: {"TMPP" / "TCMP": Morph or None} of the vanilla teeth; out_base: Data-relative
    stem, e.g. "meshes/s2s/races/orc/mouth_m" (the NIF is out_base + ".nif"); material: .mat path (None: vanilla's).
    Returns ({Data path: bytes}, info)."""
    s_al, R, t = align
    # morph folders under meshes/morphs/, as vanilla's (Meshes\Morphs\Human\Male\Chargen\Head)
    morph_base = "meshes/morphs/" + out_base[len("meshes/"):] if out_base.startswith("meshes/") else out_base
    _n, shapes = skyrim_shapes(read_sky(sky_path))
    if not shapes:
        raise ValueError(f"{sky_path}: no skinned shape")
    try:
        tri = skyrimtri.parse(read_sky(sky_path[:-4] + ".tri"), deltas=True)
    except Exception:                               # no expression tri: no jaw labels (all upper)
        tri = None
    pts, nrm, uvs, tris, _offs = merge(shapes)
    jaw = jaw_labels(shapes, tri)
    head_frame = s_al * pts @ np.asarray(R, float).T + np.asarray(t, float)
    g, skin, lod0 = teeth_template(teeth_nif)
    tmesh = sfmesh.parse(read_sf("geometries/" + lod0.replace("\\", "/") + ".mesh"))
    tpts = np.array([sfmesh.decode_position(p, tmesh.scale) for p in tmesh.positions], float)
    Mt, frame = headbake.part_to_head(tpts, skin, head_skin, head_pts)
    inv = np.linalg.inv(Mt)
    local = headbake.apply4(inv, head_frame)
    lnrm = np.asarray(nrm, float) @ np.asarray(R, float).T @ inv[:3, :3].T
    lnrm /= np.maximum(np.linalg.norm(lnrm, axis=1, keepdims=True), 1e-12)
    perf = teeth_morphs.get("TMPP")
    lower, key = lower_vertices(perf, len(tpts))
    idx, dist = side_nearest(local, jaw, tpts, lower)
    files, info = {}, {"skyrim_mouth": sky_path, "vertices": int(len(local)), "shapes": len(shapes),
                       "jaw_vertices": int(jaw.sum()), "jaw_from": "Aah" if tri is not None else "none (no .tri)",
                       "teeth_frame": frame, "vanilla_vertices": int(len(tpts)),
                       "vanilla_lower_vertices": int(lower.sum()), "lower_key": key,
                       "nearest_tooth_m_median": round(float(np.median(dist)), 4),
                       "nearest_tooth_m_max": round(float(dist.max()), 4), "morph_folders": {}}
    for sig, morph in teeth_morphs.items():
        folder = f"{morph_base}/{'performance' if sig == 'TMPP' else 'chargen'}"
        info["morph_folders"][sig] = folder.replace("/", "\\")
        if morph is not None:
            files[f"{folder}/morph.dat"] = copied_morph(morph, idx)
    bones = [b.decode("latin-1") if isinstance(b, bytes) else str(b) for b in skin.get("bones", [])] or ["C_Head"]
    ci = next((k for k, b in enumerate(bones) if b.lower() == "c_head"), 0)
    bind = skin["binds"][ci] if skin.get("binds") else ((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)
    mat = material or vanilla_material(teeth_nif)
    mpath, mdata, nif = build_mouth(local, lnrm, uvs, tris, bind, [bones[ci]], os.path.basename(out_base),
                                    g.translation, g.rotation, mat)
    files[mpath] = mdata
    files[out_base + ".nif"] = nif
    info.update(material=mat, model=out_base[len("meshes/"):].replace("/", "\\") + ".nif")
    return files, info


def shape_report(data):
    """[{name, vertices, triangles, textures, uv_min, uv_max}] per skinned shape of a Skyrim mouth NIF (2026-11-11:
    the merged mouth takes its FIRST shape's material for all shapes; the owner's Orc tusks came out pink in the
    looks menu and dark in the world: which textures do the shapes really use?)."""
    from fo4sf import skyrimnif
    n = nifmod.parse(data)
    out = []
    for s in skyrimskin.skinned_shapes(n):
        uv = np.asarray(s.uvs, float) if s.uvs else np.zeros((0, 2))
        out.append({"name": (s.name.decode("latin-1") if isinstance(s.name, bytes) else str(s.name)),
                    "vertices": len(s.positions), "triangles": int(np.asarray(s.triangles, int).reshape(-1, 3).shape[0]),
                    "textures": skyrimnif.texture_set(n, s.shader_ref) or [],
                    "uv_min": uv.min(0).round(3).tolist() if len(uv) else None,
                    "uv_max": uv.max(0).round(3).tolist() if len(uv) else None})
    return out


def main(argv=None):
    """Read-only: the shapes and textures of Skyrim's mouths (mouth_probe.SKY_MOUTHS)."""
    import argparse
    import json
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--dump", help="also copy each mouth (.nif, .tri) and its texture files (.dds) into this folder, "
                                   "to look at (game files: never commit them)")
    a = ap.parse_args(argv)
    sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))
    import hkx_to_af
    import mouth_probe
    from fo4sf import bsa
    sky = bsa.SkyrimArchives(a.skyrim_data)
    for female, kinds in mouth_probe.SKY_MOUTHS.items():
        for kind, path in kinds.items():
            try:
                rows = shape_report(hkx_to_af.read_any(path, sky))
            except SystemExit as e:
                print(f"{path}: {e}")
                continue
            print(path)
            if a.dump:                                       # the mouth itself too (its UVs: where the tusks sample)
                os.makedirs(a.dump, exist_ok=True)
                for src in (path, path[:-4] + ".tri"):
                    try:
                        data = hkx_to_af.read_any(src, sky)
                    except SystemExit:
                        continue
                    with open(os.path.join(a.dump, os.path.basename(src.replace("\\", "/"))), "wb") as fh:
                        fh.write(data)
            for r in rows:
                print("   " + json.dumps(r))
                for tex in (r["textures"] if a.dump else []):
                    if not tex:
                        continue
                    try:
                        data = hkx_to_af.read_any(tex, sky)
                    except SystemExit as e:
                        print(f"      {tex}: {e}")
                        continue
                    os.makedirs(a.dump, exist_ok=True)
                    dst = os.path.join(a.dump, os.path.basename(tex.replace("\\", "/")))
                    with open(dst, "wb") as fh:
                        fh.write(data)
                    print(f"      -> {dst} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
