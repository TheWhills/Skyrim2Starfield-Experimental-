"""A head shape baked into a head's own geometry (2026-11-10, owner: "Why arent we adding the changes we made to this
race": a race change keeps the character's face recipe, so a race shape kept as an optional chargen blend does not
show until the face picks it; baked into the race's head mesh, every face of the race starts from it and the vanilla
blends and sliders still work on top, their morph.dat deltas being per vertex index).

baked_mesh: a Starfield .mesh with per-vertex displacements added (metres, the mesh's own frame, as race_heads'
transferred race shapes); normals and tangents turned by the change of the surface normal; the position scale widened
if needed, keeping the vanilla room for chargen morphs; the meshlet cull boxes recomputed over the vanilla meshlets.
A mesh with another vertex count (a LOD file) takes, per vertex, the displacement of the nearest head vertex.

baked_head_files: the head NIF with its head geometry (every LOD slot of the BSGeometry whose LOD 0 is the head mesh)
pointed at baked meshes: {Data-relative path: bytes}.
"""
from typing import Callable, Dict

import numpy as np

from . import headcorr, nif as nifmod, sfmesh, sfnif
from .convert_static import mesh_file_path


def nearest(src: np.ndarray, pts: np.ndarray, chunk: int = 256) -> np.ndarray:
    """Index into src of the nearest point for each of pts (brute force in chunks; numpy only)."""
    src = np.asarray(src, float)
    pts = np.asarray(pts, float)
    out = np.empty(len(pts), int)
    s2 = (src ** 2).sum(1)
    for a in range(0, len(pts), chunk):
        p = pts[a:a + chunk]
        d = s2[None, :] - 2.0 * p @ src.T
        out[a:a + chunk] = d.argmin(1)
    return out


def _rotate(x: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """x (N, 3) turned per row by the rotation taking unit a to unit b (Rodrigues); rows where a or b is zero, or
    they are opposite, unchanged."""
    v = np.cross(a, b)
    c = (a * b).sum(1)
    ok = (np.linalg.norm(a, axis=1) > 0.5) & (np.linalg.norm(b, axis=1) > 0.5) & (c > -0.99)
    k = np.where(ok, 1.0 / np.maximum(1.0 + c, 1e-6), 0.0)[:, None]
    out = x * np.where(ok, c, 1.0)[:, None] + np.where(ok[:, None], np.cross(v, x), 0.0) \
        + v * (v * x).sum(1, keepdims=True) * k
    return out


def _unit(n):
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return np.where(ln > 1e-12, n / np.maximum(ln, 1e-12), 0.0)


def baked_mesh(mesh: sfmesh.SfMesh, src_vertices, disp) -> sfmesh.SfMesh:
    """A copy of mesh with disp (V, 3) added: directly when mesh has src_vertices' vertices at the same positions,
    else per vertex from the nearest of src_vertices."""
    pos = np.array([sfmesh.decode_position(p, mesh.scale) for p in mesh.positions], float)
    src = np.asarray(src_vertices, float)
    disp = np.asarray(disp, float)
    if len(pos) == len(src) and np.abs(pos - src).max(initial=0.0) < 1e-3:
        d = disp
    else:
        d = disp[nearest(src, pos)]
    new = pos + d
    tris = np.asarray(mesh.triangles, int).reshape(-1, 3)
    out = sfmesh.SfMesh(**{k: getattr(mesh, k) for k in mesh.__dataclass_fields__})
    if len(tris):
        n0 = _unit(headcorr.vertex_normals(pos, tris))
        n1 = _unit(headcorr.vertex_normals(new, tris))
        for name in ("normals", "tangents"):
            packed = getattr(mesh, name)
            if len(packed) != len(pos):
                continue
            dec = np.array([sfmesh.decode_packed(u) for u in packed], float)
            xyz = _rotate(dec[:, :3], n0, n1)
            setattr(out, name, [sfmesh.encode_packed(x, y, z, w) for (x, y, z), w in zip(xyz, dec[:, 3])])
    room = max(float(mesh.scale) - float(np.abs(pos).max(initial=0.0)), 0.0)
    top = float(np.abs(new).max(initial=0.0))
    scale = max(float(mesh.scale), top + room)
    out.scale, out.positions = sfmesh.encode_positions([tuple(p) for p in new], margin=scale - top)
    if mesh.has_meshlet_section and mesh.meshlets:
        groups, start = [], 0
        for _vc, _vo, count, _to in mesh.meshlets:
            groups.append((start, count))
            start += count
        sfmesh.build_meshlets(out, groups)
    return out


def baked_head_files(nif_bytes: bytes, read: Callable[[str], bytes], head_mesh_path: str, src_vertices, disp,
                     out_nif: str) -> Dict[str, bytes]:
    """{out_nif: the NIF, "geometries/<d>/<f>.mesh": baked meshes}. head_mesh_path: the head's LOD 0 path as the NIF
    names it (facefit.starfield_head_parts); read: Data-relative path -> bytes."""
    n = nifmod.parse(nif_bytes)
    files: Dict[str, bytes] = {}
    want = head_mesh_path.replace("/", "\\").lower()
    done = 0
    for i, b in enumerate(n.blocks):
        if n.type_of(i) != "BSGeometry":
            continue
        g = sfnif.parse_bsgeometry(b)
        first = next((m for m in g.meshes if m is not None), None)
        if first is None or first.path.decode("latin-1").replace("/", "\\").lower() != want:
            continue
        for m in g.meshes:
            if m is None:
                continue
            rel = "geometries/" + m.path.decode("latin-1").replace("\\", "/") + ".mesh"
            data = sfmesh.serialize(baked_mesh(sfmesh.parse(read(rel)), src_vertices, disp))
            d, f = mesh_file_path(data)
            files[f"geometries/{d}/{f}.mesh"] = data
            m.path = f"{d}\\{f}".encode("latin-1")
        n.blocks[i] = sfnif.build_bsgeometry(g)
        done += 1
    if not done:
        raise ValueError(f"no BSGeometry with LOD 0 {head_mesh_path} in the head NIF")
    files[out_nif] = nifmod.serialize(n)
    return files


# --- head parts (2026-11-10, owner: "hard to test without the eyebrows, eyes, beards, and teeth with baking") -------
# A face head part (eyes, brows, beard, teeth, lashes, jewelry) is skinned to the head's bones; its .mesh is in its own
# frame (the teeth: C_Head's frame, docs/npc/races.md 2026-11-09). A point v of it sits on the head mesh at
# inv(B_head) B_part v for a bone both skin to (B: that bone's bind, mesh -> bone). The candidate frame whose points
# lie closest to the head surface (median distance to the nearest head vertex) is used; each part point then moves
# like its nearest head vertex.

def bind_matrix(bind, transpose: bool = False) -> np.ndarray:
    """4x4 of a Starfield skin bind (sphere, rot 9, trans 3, scale): mesh point -> bone space, s R v + t (transpose:
    the 9 floats read column-major); as mouth_probe.bind_matrix."""
    _sphere, rot, trans, scale = bind
    R = np.array(rot, float).reshape(3, 3)
    m = np.eye(4)
    m[:3, :3] = (R.T if transpose else R) * (float(scale) or 1.0)
    m[:3, 3] = trans
    return m


def geometry_skin(n, g) -> dict:
    """{"bones": [names], "binds": [...]} of one BSGeometry: bone names from its SkinAttach extra data, binds from
    the BoneData its BSSkin::Instance names. {} if unskinned."""
    import struct
    out = {}
    for r in g.extra_refs:
        if 0 <= r < len(n.blocks) and n.type_of(r) == "SkinAttach":
            b = n.blocks[r]
            cnt, = struct.unpack_from("<I", b, 4)
            p, names = 8, []
            for _ in range(cnt):
                ln, = struct.unpack_from("<I", b, p)
                names.append(b[p + 4:p + 4 + ln])
                p += 4 + ln
            out["bones"] = names
    if 0 <= g.skin < len(n.blocks) and n.type_of(g.skin) == "BSSkin::Instance":
        _root, data, _nb = struct.unpack_from("<iiI", n.blocks[g.skin], 0)
        if 0 <= data < len(n.blocks) and n.type_of(data) == "BSSkin::BoneData":
            b = n.blocks[data]
            cnt, = struct.unpack_from("<I", b, 0)
            out["binds"] = [(v[:4], v[4:13], v[13:16], v[16]) for v in
                            (struct.unpack_from("<17f", b, 4 + 68 * k) for k in range(cnt))]
    return out


def _binds_by_name(skin):
    bones = [b.decode("latin-1").lower() if isinstance(b, bytes) else str(b).lower() for b in skin.get("bones", [])]
    return dict(zip(bones, skin.get("binds", [])))


def apply4(M, pts):
    pts = np.asarray(pts, float)
    return pts @ M[:3, :3].T + M[:3, 3]


def part_to_head(part_pts, part_skin, head_skin, head_pts, max_bones: int = 8):
    """(4x4 part mesh -> head mesh, report): candidates identity and, per bone both skin to (C_Head first),
    inv(B_head) B_part in both bind conventions; the one with the smallest median distance to the head's vertices."""
    head_pts = np.asarray(head_pts, float)
    sample = np.asarray(part_pts, float)
    if len(sample) > 2000:
        sample = sample[np.linspace(0, len(sample) - 1, 2000).astype(int)]
    hb, pb = _binds_by_name(head_skin or {}), _binds_by_name(part_skin or {})
    shared = sorted(set(hb) & set(pb), key=lambda b: (b != "c_head", b))[:max_bones]
    cands = [("identity", np.eye(4))]
    for b in shared:
        for tr in (False, True):
            try:
                M = np.linalg.inv(bind_matrix(hb[b], tr)) @ bind_matrix(pb[b], tr)
            except np.linalg.LinAlgError:
                continue
            cands.append((f"{b} binds{' (transposed)' if tr else ''}", M))
    best, rep = None, {}
    for name, M in cands:
        p = apply4(M, sample)
        d = np.linalg.norm(head_pts[nearest(head_pts, p)] - p, axis=1)
        med = float(np.median(d))
        rep[name] = round(med, 4)
        if best is None or med < best[0]:
            best = (med, name, M)
    return best[2], {"used": best[1], "median_to_head_m": round(best[0], 4), "candidates": rep}


def part_displacement(part_pts, M, head_pts, head_disp):
    """Per part vertex (its own frame): the displacement of the nearest head vertex, taken back through M."""
    p = apply4(M, part_pts)
    d_head = np.asarray(head_disp, float)[nearest(np.asarray(head_pts, float), p)]
    return d_head @ np.linalg.inv(M[:3, :3]).T


def baked_part_files(nif_bytes: bytes, read: Callable[[str], bytes], head_pts, head_disp, head_skin,
                     out_nif: str):
    """({out_nif: NIF, "geometries/<d>/<f>.mesh": meshes}, report) of a head part with every skinned or unskinned
    BSGeometry baked: LOD 0 moved per vertex like its nearest head vertex (part_to_head's frame), the other LOD slots
    by nearest LOD 0 vertex. Shapes whose LOD 0 lies farther than 0.25 m (median) from the head are left as they are."""
    n = nifmod.parse(nif_bytes)
    files: Dict[str, bytes] = {}
    rep = {"shapes": []}
    for i, b in enumerate(n.blocks):
        if n.type_of(i) != "BSGeometry":
            continue
        g = sfnif.parse_bsgeometry(b)
        refs = [m for m in g.meshes if m is not None]
        if not refs:
            continue
        lod0 = sfmesh.parse(read("geometries/" + refs[0].path.decode("latin-1").replace("\\", "/") + ".mesh"))
        pts = np.array([sfmesh.decode_position(p, lod0.scale) for p in lod0.positions], float)
        M, frame = part_to_head(pts, geometry_skin(n, g), head_skin, head_pts)
        srep = {"vertices": len(pts), **frame}
        rep["shapes"].append(srep)
        if frame["median_to_head_m"] > 0.25:
            srep["left"] = "far from the head"
            continue
        disp = part_displacement(pts, M, head_pts, head_disp)
        srep["max_move_m"] = round(float(np.linalg.norm(disp, axis=1).max(initial=0.0)), 4)
        for m in refs:
            rel = "geometries/" + m.path.decode("latin-1").replace("\\", "/") + ".mesh"
            mesh = lod0 if m is refs[0] else sfmesh.parse(read(rel))
            data = sfmesh.serialize(baked_mesh(mesh, pts, disp))
            d, f = mesh_file_path(data)
            files[f"geometries/{d}/{f}.mesh"] = data
            m.path = f"{d}\\{f}".encode("latin-1")
        n.blocks[i] = sfnif.build_bsgeometry(g)
    files[out_nif] = nifmod.serialize(n)
    return files, rep
