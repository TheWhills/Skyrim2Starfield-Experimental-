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
