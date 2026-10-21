"""Fit Starfield face sliders to a Skyrim face: the face of a converted NPC set from its Skyrim FaceGen head.

Starfield's face model (verified on the facial-bone-region files, humanracefacialboneregions{male,female}.txt, and
xEdit's wbDefinitionsSF1): a head mesh skinned to ~48 face bones (more with face-bone mods); chargen sliders ("face
dials", NPC_ FMSI index + FMRS position; race RACE Face Dials FDSI / FDSL) each move a few bones between a Minima and a
Maxima offset (position, rotation, scale); "phenotype" regions (ZeroToOne, e.g. male_eu_md2) move all of them at once.
Units (supported hypothesis, calibrated on the PC): positions in centimetres (pos_unit 0.01 into the head's metres),
rotations in degrees, scales as deltas.

Model used here: a slider at value v moves bone b by v * Maxima (v > 0) or -v * Minima (v < 0); each moved bone
deforms the vertices it weights (rotation and scale about the bone's pivot, in the bone's frame). For fitting, rotation
and scale are linearised (small angles), so the face is a piecewise-linear function of the slider values and the
fit is a bounded least-squares problem: each slider becomes a "plus" and a "minus" column with 0 <= x <= 1 (ZeroToOne
sliders only plus), solved by coordinate descent on the normal equations with a small ridge term (no scipy needed).

Skyrim side: per NPC, displacement = FaceGen head - Skyrim's base head (same topology); carried to the Starfield head
through a one-off alignment of the two base heads (similarity ICP) and inverse-distance weights over the nearest
Skyrim vertices.
"""
import dataclasses
import json
import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


@dataclasses.dataclass
class Slider:
    id: int
    name: str
    region: str
    zero_to_one: bool
    sculpt: bool
    bones: Dict[str, Tuple[np.ndarray, np.ndarray]]    # bone -> (minima[9], maxima[9]): pos xyz, rot xyz, scale xyz


def _vec9(d) -> np.ndarray:
    d = d or {}
    out = []
    for key in ("Position", "Rotation", "Scale"):
        v = d.get(key) or {}
        out += [float(v.get(c, 0.0)) for c in "xyz"]
    return np.array(out)


def load_regions(text: str) -> List[Slider]:
    """Sliders of a humanracefacialboneregions file (JSON: Regions[] -> SlidersA[] -> BonesA[])."""
    data = json.loads(text)
    out = []
    for r in data.get("Regions") or []:
        for s in (r.get("SlidersA") or []) + (r.get("SlidersB") or []):
            bones = {}
            for b in (s.get("BonesA") or []) + (s.get("BonesB") or []):
                bones[b["Bone"]] = (_vec9(b.get("Minima")), _vec9(b.get("Maxima")))
            out.append(Slider(int(s["ID"]), s.get("Name") or r.get("Name") or "", r.get("Name") or "",
                              bool(s.get("ZeroToOne")), bool(r.get("SculptRegion")), bones))
    return out


@dataclasses.dataclass
class Head:
    """A head mesh skinned to face bones: vertices (V, 3), weights (V, B) over `bones`, each bone's pivot (B, 3) and
    frame (B, 3, 3; columns = the bone's axes in head space), all in the head's space (metres)."""
    vertices: np.ndarray
    bones: List[str]
    weights: np.ndarray
    pivots: np.ndarray
    frames: np.ndarray

    def bone_index(self) -> Dict[str, int]:
        return {b: i for i, b in enumerate(self.bones)}


def _rot(rx, ry, rz) -> np.ndarray:
    """Rotation matrix from x, y, z angles (radians), applied x then y then z."""
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return mz @ my @ mx


def bone_offsets(sliders: Sequence[Slider], values: Dict[int, float]) -> Dict[str, np.ndarray]:
    """Summed 9-vectors (pos, rot, scale deltas, file units) per bone for slider values {id: value}."""
    out: Dict[str, np.ndarray] = {}
    for s in sliders:
        v = float(values.get(s.id, 0.0))
        if v == 0.0:
            continue
        for bone, (mn, mx) in s.bones.items():
            out[bone] = out.get(bone, np.zeros(9)) + (mx * v if v > 0 else mn * -v)
    return out


def deform(head: Head, sliders: Sequence[Slider], values: Dict[int, float], pos_unit: float = 0.01) -> np.ndarray:
    """Vertices after the sliders (exact rotations and scales; linear blend skinning over the face bones)."""
    idx = head.bone_index()
    v = head.vertices
    out = v.copy()
    for bone, off in bone_offsets(sliders, values).items():
        b = idx.get(bone)
        if b is None:
            continue
        F, p = head.frames[b], head.pivots[b]
        local = F @ (_rot(*np.radians(off[3:6])) @ np.diag(1.0 + off[6:9])) @ F.T
        moved = (v - p) @ local.T + p + F @ (off[0:3] * pos_unit)
        out += head.weights[:, b:b + 1] * (moved - v)
    return out


def _column(head: Head, bone_vecs: Dict[str, np.ndarray], pos_unit: float) -> np.ndarray:
    """Linearised displacement (V, 3) of the bone offsets (rotation as a small angle, scale as a small stretch)."""
    idx = head.bone_index()
    v = head.vertices
    out = np.zeros_like(v)
    for bone, off in bone_vecs.items():
        b = idx.get(bone)
        if b is None:
            continue
        F, p = head.frames[b], head.pivots[b]
        r = F @ np.radians(off[3:6])                       # small rotation vector in head space
        rel = v - p
        d = np.cross(r, rel) + (rel @ F) * off[6:9] @ F.T + F @ (off[0:3] * pos_unit)
        out += head.weights[:, b:b + 1] * d
    return out


def basis(head: Head, sliders: Sequence[Slider], pos_unit: float = 0.01):
    """(columns (V*3, K), [(slider id, sign)]): one column per slider direction (+1 Maxima, -1 Minima)."""
    cols, keys = [], []
    for s in sliders:
        dirs = [(1, {b: mx for b, (mn, mx) in s.bones.items()})]
        if not s.zero_to_one:
            dirs.append((-1, {b: mn for b, (mn, mx) in s.bones.items()}))
        for sign, vecs in dirs:
            c = _column(head, vecs, pos_unit)
            if np.any(c):
                cols.append(c.reshape(-1))
                keys.append((s.id, sign))
    A = np.stack(cols, axis=1) if cols else np.zeros((head.vertices.size, 0))
    return A, keys


def bounded_lsq(A: np.ndarray, b: np.ndarray, w: Optional[np.ndarray] = None, ridge: float = 1e-6,
                iters: int = 400, tol: float = 1e-10) -> np.ndarray:
    """argmin_x ||sqrt(w) (A x - b)||^2 + ridge ||x||^2 with 0 <= x <= 1 (coordinate descent)."""
    if w is not None:
        A = A * w[:, None]
        b = b * w
    G = A.T @ A
    h = A.T @ b
    scale = max(float(np.mean(np.diag(G))), 1e-30)
    G = G + np.eye(len(G)) * ridge * scale
    x = np.zeros(len(G))
    d = np.diag(G).copy()
    for _ in range(iters):
        biggest = 0.0
        for i in range(len(x)):
            if d[i] <= 0:
                continue
            new = min(1.0, max(0.0, x[i] + (h[i] - G[i] @ x) / d[i]))
            biggest = max(biggest, abs(new - x[i]))
            x[i] = new
        if biggest < tol:
            break
    return x


def fit(head: Head, sliders: Sequence[Slider], target: np.ndarray, vertex_weights: Optional[np.ndarray] = None,
        pos_unit: float = 0.01, ridge: float = 1e-6, refine: int = 2) -> Tuple[Dict[int, float], Dict]:
    """Slider values {id: value} that move head.vertices toward target (V, 3), and a report (RMS before / after with
    the exact deformation). refine > 0 re-linearises around the solution (rotations / scales) that many times."""
    wv = np.ones(len(head.vertices)) if vertex_weights is None else np.asarray(vertex_weights, float)
    w = np.repeat(np.sqrt(np.maximum(wv, 0.0)), 3)
    A, keys = basis(head, sliders, pos_unit)
    values: Dict[int, float] = {}
    base = head.vertices
    for _ in range(1 + max(0, refine)):
        # residual of the exact model at the current values, solved for the change of the linear part
        current = deform(head, sliders, values, pos_unit)
        x0 = np.array([max(0.0, values.get(k, 0.0) * s) for k, s in keys])
        rhs = (target - current).reshape(-1) + A @ x0
        x = bounded_lsq(A, rhs, w, ridge)
        new: Dict[int, float] = {}
        for (k, s), xi in zip(keys, x):
            new[k] = new.get(k, 0.0) + s * xi
        values = {k: v for k, v in new.items() if abs(v) > 1e-6}
    final = deform(head, sliders, values, pos_unit)
    mask = wv > 0

    def rms(a):
        return float(np.sqrt(np.mean(np.sum((a[mask] - target[mask]) ** 2, axis=1)))) if mask.any() else 0.0
    return values, {"rms_before": rms(base), "rms_after": rms(final), "sliders_used": len(values),
                    "columns": len(keys)}


# ------------------------------------------------------------------------------------------------ Skyrim -> Starfield
def _nearest(src: np.ndarray, dst: np.ndarray, k: int = 1, chunk: int = 2048) -> Tuple[np.ndarray, np.ndarray]:
    """For each dst point: indices (M, k) and distances (M, k) of the k nearest src points (numpy only)."""
    idx = np.empty((len(dst), k), int)
    dist = np.empty((len(dst), k))
    s2 = np.sum(src ** 2, axis=1)
    for a in range(0, len(dst), chunk):
        q = dst[a:a + chunk]
        d2 = np.sum(q ** 2, axis=1)[:, None] - 2 * q @ src.T + s2[None, :]
        part = np.argpartition(d2, kth=min(k, len(src) - 1) - 1 if k < len(src) else len(src) - 1, axis=1)[:, :k]
        pd = np.take_along_axis(d2, part, axis=1)
        order = np.argsort(pd, axis=1)
        idx[a:a + chunk] = np.take_along_axis(part, order, axis=1)
        dist[a:a + chunk] = np.sqrt(np.maximum(np.take_along_axis(pd, order, axis=1), 0.0))
    return idx, dist


def similarity(src: np.ndarray, dst: np.ndarray) -> Tuple[float, np.ndarray, np.ndarray]:
    """(s, R, t) minimising ||s R src + t - dst|| over paired points (Umeyama)."""
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    U, S, Vt = np.linalg.svd(b.T @ a / len(src))
    D = np.eye(3)
    if np.linalg.det(U @ Vt) < 0:
        D[2, 2] = -1
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / np.mean(np.sum(a ** 2, axis=1)))
    return s, R, md - s * R @ ms


def align_heads(src: np.ndarray, dst: np.ndarray, iters: int = 40, rotate: bool = True,
                init: Optional[Tuple[float, np.ndarray, np.ndarray]] = None):
    """(s, R, t, rms) taking the src head onto the dst head: centroid / size first (same facing assumed: both games
    face +Y with Z up), then ICP with scale (rotation too when `rotate`)."""
    if init is None:
        s = math.sqrt(np.mean(np.sum((dst - dst.mean(0)) ** 2, 1)) / np.mean(np.sum((src - src.mean(0)) ** 2, 1)))
        R = np.eye(3)
        t = dst.mean(0) - s * src.mean(0)
    else:
        s, R, t = init
    rms = float("inf")
    for _ in range(iters):
        moved = s * src @ R.T + t
        j, d = _nearest(dst, moved, 1)                  # src -> nearest dst
        i, e = _nearest(moved, dst, 1)                  # dst -> nearest src: both ways, so neither sampling biases
        new_rms = float(np.sqrt((np.sum(d ** 2) + np.sum(e ** 2)) / (len(d) + len(e))))
        a_pts = np.concatenate([src, src[i[:, 0]]])
        b_pts = np.concatenate([dst[j[:, 0]], dst])
        s2, R2, t2 = similarity(a_pts, b_pts)
        if not rotate:
            # scale and shift only: solve with the rotation fixed
            a = a_pts @ R.T
            ac, pc = a - a.mean(0), b_pts - b_pts.mean(0)
            s2 = float(np.sum(ac * pc) / np.sum(ac * ac))
            R2, t2 = R, b_pts.mean(0) - s2 * a.mean(0)
        s, R, t = s2, R2, t2
        if abs(rms - new_rms) < 1e-9:
            rms = new_rms
            break
        rms = new_rms
    return s, R, t, rms


def transfer(src_base: np.ndarray, src_face: np.ndarray, alignment, dst_vertices: np.ndarray, k: int = 4):
    """Displacement (M, 3) for the dst head's vertices: the src face's displacement from its base head, moved into
    the dst frame (scaled and rotated by the alignment) and averaged over the k nearest src vertices (1 / distance)."""
    s, R, t = alignment[:3]
    disp = (src_face - src_base) @ R.T * s
    moved = s * src_base @ R.T + t
    j, d = _nearest(moved, dst_vertices, k)
    w = 1.0 / np.maximum(d, 1e-9)
    w /= w.sum(1, keepdims=True)
    return np.einsum("mk,mkc->mc", w, disp[j])


def face_weights(head: Head, minimum: float = 1e-3) -> np.ndarray:
    """Per-vertex fit weight: how much the face bones drive the vertex (0 where they do not)."""
    w = head.weights.sum(1)
    return np.where(w > minimum, w, 0.0)


# ------------------------------------------------------------------------------------------------ Starfield head files
def starfield_head_parts(nif_bytes: bytes):
    """(mesh paths of the first skinned BSGeometry, LOD 0 first; skin dict from sfnif.parse_skin) of a head NIF such
    as meshes\\actors\\human\\characterassets\\male\\malehead_facebones.nif (geometry in geometries\\<path>.mesh)."""
    from . import nif as nifmod, sfnif
    n = nifmod.parse(nif_bytes)
    paths = []
    for i, b in enumerate(n.blocks):
        if n.type_of(i) == "BSGeometry":
            g = sfnif.parse_bsgeometry(b)
            paths = [m.path.decode("latin-1") for m in g.meshes if m is not None]
            if paths:
                break
    return paths, sfnif.parse_skin(n)


def _bind_pivot_frame(bind, transpose: bool):
    """(pivot, frame) of a bone from its skin bind (sphere, rot 9 row-major, trans 3, scale): the bind maps a head
    point v into the bone's space as s R v + t, so the bone origin in head space is -R^T t / s and its axes are R^T's
    columns. transpose: read the 9 floats column-major instead (the convention is checked by face_head)."""
    _sphere, rot, trans, scale = bind
    R = np.array(rot, float).reshape(3, 3)
    if transpose:
        R = R.T
    s = float(scale) or 1.0
    return -R.T @ np.array(trans, float) / s, R.T


def face_head(mesh_positions: np.ndarray, weights: List[List[Tuple[int, float]]], bones: List[str], binds,
              bone_filter=lambda b: b.lower().startswith("facebone")) -> Tuple[Head, Dict]:
    """A Head from a skinned Starfield head: positions (V, 3), per-vertex [(bone index, weight)], skin bone names and
    binds. Only bones passing bone_filter become fit bones (the rest stay as they are). The bind convention is chosen
    by which one puts the face-bone pivots on the head (inside its box grown by 2 cm); reported."""
    V = np.asarray(mesh_positions, float)
    keep = [i for i, b in enumerate(bones) if bone_filter(b)]
    col = {b: j for j, b in enumerate(keep)}
    W = np.zeros((len(V), len(keep)))
    for v, ws in enumerate(weights):
        for bi, w in ws:
            if bi in col:
                W[v, col[bi]] += w
    lo, hi = V.min(0) - 0.02, V.max(0) + 0.02
    best = None
    for transpose in (False, True):
        pf = [_bind_pivot_frame(binds[i], transpose) for i in keep]
        piv = np.array([p for p, _f in pf]) if pf else np.zeros((0, 3))
        inside = int(np.sum(np.all((piv >= lo) & (piv <= hi), axis=1))) if len(piv) else 0
        if best is None or inside > best[0]:
            best = (inside, transpose, piv, np.array([f for _p, f in pf]) if pf else np.zeros((0, 3, 3)))
    inside, transpose, piv, frames = best
    head = Head(V, [bones[i] for i in keep], W, piv, frames)
    return head, {"face_bones": len(keep), "pivots_on_head": inside, "bind_read_transposed": transpose,
                  "vertices": len(V), "vertices_moved_by_face_bones": int(np.sum(W.sum(1) > 1e-3))}


def mesh_arrays(mesh) -> Tuple[np.ndarray, List[List[Tuple[int, float]]]]:
    """(positions (V, 3) metres, per-vertex [(bone index, weight 0..1)]) of an sfmesh.SfMesh."""
    from . import sfmesh
    pos = np.array([sfmesh.decode_position(p, mesh.scale) for p in mesh.positions], float)
    k = mesh.weights_per_vertex
    ws = []
    for v in range(len(pos)):
        ws.append([(b, w / 65535.0) for b, w in mesh.weights[v * k:(v + 1) * k] if w] if k else [])
    return pos, ws
