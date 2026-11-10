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
                iters: int = 400, tol: float = 1e-10, upper: float = 1.0) -> np.ndarray:
    """argmin_x ||sqrt(w) (A x - b)||^2 + ridge ||x||^2 with 0 <= x <= upper (coordinate descent)."""
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
            new = min(upper, max(0.0, x[i] + (h[i] - G[i] @ x) / d[i]))
            biggest = max(biggest, abs(new - x[i]))
            x[i] = new
        if biggest < tol:
            break
    return x


def fit(head: Head, sliders: Sequence[Slider], target: np.ndarray, vertex_weights: Optional[np.ndarray] = None,
        pos_unit: float = 0.01, ridge: float = 1e-6, refine: int = 2, limit: float = 1.0
        ) -> Tuple[Dict[int, float], Dict]:
    """Slider values {id: value} that move head.vertices toward target (V, 3), and a report (RMS before / after with
    the exact deformation). refine > 0 re-linearises around the solution (rotations / scales) that many times.
    limit: the largest |value| (1 = the looks menu's range; more is a test of what the game accepts)."""
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
        x = bounded_lsq(A, rhs, w, ridge, upper=limit)
        new: Dict[int, float] = {}
        for (k, s), xi in zip(keys, x):
            new[k] = new.get(k, 0.0) + s * xi
        values = {k: v for k, v in new.items() if abs(v) > 1e-6}
    final = deform(head, sliders, values, pos_unit)
    mask = wv > 0

    def rms(a):
        return float(np.sqrt(np.mean(np.sum((a[mask] - target[mask]) ** 2, axis=1)))) if mask.any() else 0.0
    at_limit = sorted(k for k, v in values.items() if abs(v) >= limit - 1e-4)
    err = np.sqrt(np.sum((final - target) ** 2, axis=1))[mask]
    moved = np.sqrt(np.sum((final - base) ** 2, axis=1))[mask]
    return values, {"rms_before": rms(base), "rms_after": rms(final), "sliders_used": len(values),
                    "columns": len(keys), "sliders_at_limit": at_limit, "ridge": ridge,
                    "max_error_m": float(err.max()) if len(err) else 0.0,
                    "max_change_m": float(moved.max()) if len(moved) else 0.0}


def mirror_index(vertices: np.ndarray, axis: int = 0) -> np.ndarray:
    """For each vertex the index of the vertex nearest its mirror image across the head's middle (median along
    `axis`; both games' heads in model space face +Y with X across)."""
    v = np.asarray(vertices, float)
    c = float(np.median(v[:, axis]))
    m = v.copy()
    m[:, axis] = 2 * c - m[:, axis]
    return _nearest(v, m)[0][:, 0]


def lateral_axis(vertices: np.ndarray) -> int:
    """The axis a head mesh is mirror-symmetric across (2026-11-09: Starfield's head .mesh files are in C_Head's
    frame, not model space, so X is not always across): the one whose mirror image lands closest to the mesh."""
    v = np.asarray(vertices, float)
    ext = v.max(0) - v.min(0)
    best = None
    for ax in range(3):
        if ext[ax] < 0.25 * ext.max():          # a flat axis mirrors onto itself: not "across"
            continue
        c = float(np.median(v[:, ax]))
        m = v.copy()
        m[:, ax] = 2 * c - m[:, ax]
        _i, d = _nearest(v, m[::max(1, len(v) // 2000)])
        score = float(np.mean(d))
        if best is None or score < best[0]:
            best = (score, ax)
    return best[1]


def symmetrize(field: np.ndarray, vertices: np.ndarray, axis: int = 0, mode: str = "mean") -> np.ndarray:
    """A displacement field made mirror-symmetric (2026-11-05: with More Sliders' left / right sliders the fit chased
    the transfer's left-right noise: Ralof came out deformed). mode "mean": the mean of the field and its mirror
    image; "stronger": per vertex the larger of the two (2026-11-09, owner: with the mean the race heads' ears came out
    half-pointed: one side of the transfer had the point, the other had lost it)."""
    m = mirror_index(vertices, axis)
    flip = np.ones(3)
    flip[axis] = -1.0
    f = np.asarray(field, float)
    flipped = f[m] * flip
    if mode == "stronger":
        own = np.linalg.norm(f, axis=1) >= np.linalg.norm(flipped, axis=1)
        return np.where(own[:, None], f, flipped)
    return 0.5 * (f + flipped)


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


def skin_to_model_matrix(skin_transform) -> np.ndarray:
    """4x4 taking a Skyrim skinned shape's vertices (stored in skin space) to model space: the inverse of its NiSkinData
    overall transform (fo4sf.skyrimhair.skin_to_model as a matrix; identity without one)."""
    m = np.eye(4)
    if skin_transform is None:
        return m
    rs = np.array(skin_transform.rotation, float).reshape(3, 3)
    ts = np.array(skin_transform.translation, float)
    sc = float(skin_transform.scale) or 1.0
    m[:3, :3] = rs.T / sc
    m[:3, 3] = -rs.T @ ts / sc
    return m


def skyrim_model_matrix(nif_file, shape) -> np.ndarray:
    """4x4 skin -> model space of a Skyrim skinned shape, from its most-weighted bone: the bone node's bind-pose
    world transform in the NIF times that bone's skin -> bone transform (NiSkinData). 2026-11-09 (owner's beast and
    mouth probes, checked on vanilla eyesmale.nif and maleheadargonian.nif): some shapes' NiSkinData overall transform
    is the identity while their vertices are not in model space (eyes and the Argonian male head came out 120 units
    low), and the bone route puts them on the head; for the human heads both routes agree exactly. Falls back to
    skin_to_model_matrix when the NIF has no node for that bone."""
    from . import nif as nifmod, skyrimnif
    if not shape.binds or not shape.bones:
        return skin_to_model_matrix(shape.skin_transform)
    tot = np.zeros(len(shape.bones))
    for vw in shape.weights or []:
        for b, w in vw:
            tot[b] += w
    k = int(tot.argmax())
    bi = next((i for i in range(len(nif_file.blocks)) if nif_file.type_of(i).endswith("Node")
               and skyrimnif._name(nif_file, nif_file.blocks[i]) == shape.bones[k]), None)
    if bi is None:
        return skin_to_model_matrix(shape.skin_transform)
    t, r, sc = nifmod.world_transforms(nif_file)(bi)
    w4 = np.eye(4)
    w4[:3, :3] = np.array(r, float).reshape(3, 3) * sc
    w4[:3, 3] = t
    b = shape.binds[k]
    b4 = np.eye(4)
    b4[:3, :3] = np.array(b.rotation, float).reshape(3, 3) * b.scale
    b4[:3, 3] = b.translation
    return w4 @ b4


def apply4(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return np.asarray(pts, float) @ m[:3, :3].T + m[:3, 3]


def align_to_local(sky_model: np.ndarray, sf_local: np.ndarray, sf_node: np.ndarray, iters: int = 40):
    """(s, R, t, rms) taking Skyrim head points in Skyrim MODEL space (units) onto a Starfield head's MESH-LOCAL frame
    (the frame its .mesh vertices, binds and morph.dat deltas are in), for transfer().
    2026-11-09: the Starfield heads store their mesh in C_Head's rotated frame (x up; hair_pack.game_mesh_of applies
    the shape node's transform for that), and an ICP from the identity (align_heads on the raw mesh) settled 90 degrees
    off (race_probe, owner's run: rms 2.3 cm). Both games' model spaces share axes (+Y forward, +Z up; skyrimhair, rms
    6.7 mm on the cranium), so: Starfield points to model space with the node transform sf_node (4x4, local -> model),
    a scale-and-shift ICP without rotation there (Starfield points below the lowest moved Skyrim point left out each
    round: its neck is longer), then back to the local frame."""
    dst = apply4(sf_node, sf_local)
    src = np.asarray(sky_model, float)
    # start: tops together (the neck lengths differ), size from the spread across (x, y) of the part of the Starfield
    # head as tall as the Skyrim one
    s = math.sqrt(np.mean(np.sum((dst[:, :2] - dst[:, :2].mean(0)) ** 2, 1))
                  / np.mean(np.sum((src[:, :2] - src[:, :2].mean(0)) ** 2, 1)))
    for _ in range(3):
        top = dst[dst[:, 2] >= dst[:, 2].max() - s * np.ptp(src[:, 2])]
        s = math.sqrt(np.mean(np.sum((top[:, :2] - top[:, :2].mean(0)) ** 2, 1))
                      / np.mean(np.sum((src[:, :2] - src[:, :2].mean(0)) ** 2, 1)))
    t = np.array([*(top[:, :2].mean(0) - s * src[:, :2].mean(0)), dst[:, 2].max() - s * src[:, 2].max()])
    rms = float("inf")
    for _ in range(iters):
        moved = s * src + t
        d_use = dst[dst[:, 2] >= moved[:, 2].min() - 0.005]
        j, d = _nearest(d_use, moved, 1)
        i, e = _nearest(moved, d_use, 1)
        new_rms = float(np.sqrt((np.sum(d ** 2) + np.sum(e ** 2)) / (len(d) + len(e))))
        a = np.concatenate([src, src[i[:, 0]]])
        b = np.concatenate([d_use[j[:, 0]], d_use])
        ac, bc = a - a.mean(0), b - b.mean(0)
        s = float(np.sum(ac * bc) / np.sum(ac * ac))
        t = b.mean(0) - s * a.mean(0)
        if abs(rms - new_rms) < 1e-9:
            rms = new_rms
            break
        rms = new_rms
    fit = np.eye(4)
    fit[:3, :3] *= s
    fit[:3, 3] = t
    total = np.linalg.inv(sf_node) @ fit                 # Skyrim model -> Starfield local
    k = float(np.cbrt(np.linalg.det(total[:3, :3])))
    return k, total[:3, :3] / k, total[:3, 3], rms


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


def smooth_field(field: np.ndarray, triangles, iterations: int = 10, keep: float = 0.5) -> np.ndarray:
    """field (V, k) averaged with its mesh neighbours `iterations` times (each step: keep x own + (1 - keep) x the
    neighbours' mean). For the Skyrim displacement moved onto Starfield's 15,000-vertex head from Skyrim's ~900: the
    owner's preview 2026-11-05 showed it lumpy at Skyrim's vertex spacing, noise no slider can follow."""
    f = np.asarray(field, float).copy()
    t = np.asarray(triangles, int)
    if iterations <= 0 or not len(t):
        return f
    a = np.concatenate([t[:, 0], t[:, 1], t[:, 2], t[:, 1], t[:, 2], t[:, 0]])
    b = np.concatenate([t[:, 1], t[:, 2], t[:, 0], t[:, 0], t[:, 1], t[:, 2]])
    deg = np.bincount(a, minlength=len(f)).astype(float)
    for _ in range(iterations):
        acc = np.zeros_like(f)
        np.add.at(acc, a, f[b])
        mean = np.where(deg[:, None] > 0, acc / np.maximum(deg, 1)[:, None], f)
        f = keep * f + (1 - keep) * mean
    return f


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


# ------------------------------------------------------------------------------- face-bone mods (More Sliders, 18445)
def _mesh_key(path: str) -> str:
    p = path.replace("\\", "/").lower()
    return p[len("geometries/"):] if p.startswith("geometries/") else p


def load_recipe(text: str) -> Dict[str, Dict]:
    """The weight patches of a MoreSlidersFaceBones_recipe.txt (owner 2026-11-05, More Sliders 2.1; read on its file):
    tab-separated lines; 'MESH <geometries\\...mesh> <vertex count> <W line count> <checksum>' starts a block, each
    'W <vertex> <parent bone> <child bone> <alpha16>' after it moves alpha16 / 65535 of the vertex's parent-bone weight
    to the child bone, in order (bone numbers index the mod's _facebones head NIF skin, which lists the vanilla bones
    first and the new faceBone_MS_* bones after them). Its SFSE plugin does this to the vanilla .mesh at load time, so
    the game files themselves never carry the new weights. NODE / FOLLOW lines (bones for the skeleton, parts that
    follow the head) are not needed for a fit and are skipped. Returns {mesh path (lower, '/', no 'geometries/'):
    {"vertices", "count", "checksum", "moves": [(vertex, parent, child, alpha16)]}}."""
    out: Dict[str, Dict] = {}
    cur = None
    for line in text.splitlines():
        f = line.rstrip("\r\n").split("\t")
        if f[0] == "MESH" and len(f) >= 4:
            cur = {"vertices": int(f[2]), "count": int(f[3]), "checksum": f[4] if len(f) > 4 else "", "moves": []}
            out[_mesh_key(f[1])] = cur
        elif f[0] == "W" and cur is not None and len(f) >= 5:
            cur["moves"].append((int(f[1]), int(f[2]), int(f[3]), int(f[4])))
        elif f[0] in ("NODE", "FOLLOW", "FOLLOWHEAD"):
            cur = None
    return out


def apply_recipe(weights: List[List[Tuple[int, float]]], moves) -> Tuple[List[List[Tuple[int, float]]], Dict]:
    """Per-vertex weights after a recipe block's moves (each vertex's total stays the same)."""
    ws = [dict() for _ in weights]
    for v, row in enumerate(weights):
        for b, w in row:
            ws[v][b] = ws[v].get(b, 0.0) + w
    moved = skipped = 0
    for v, parent, child, alpha in moves:
        if v >= len(ws) or ws[v].get(parent, 0.0) <= 0.0:
            skipped += 1
            continue
        amount = ws[v][parent] * alpha / 65535.0
        ws[v][parent] -= amount
        ws[v][child] = ws[v].get(child, 0.0) + amount
        moved += 1
    out = [[(b, w) for b, w in sorted(d.items()) if w > 0.0] for d in ws]
    return out, {"moves": moved, "skipped": skipped,
                 "new_bones_weighted": len({c for _v, _p, c, _a in moves})}


def mesh_arrays(mesh) -> Tuple[np.ndarray, List[List[Tuple[int, float]]]]:
    """(positions (V, 3) metres, per-vertex [(bone index, weight 0..1)]) of an sfmesh.SfMesh."""
    from . import sfmesh
    pos = np.array([sfmesh.decode_position(p, mesh.scale) for p in mesh.positions], float)
    k = mesh.weights_per_vertex
    ws = []
    for v in range(len(pos)):
        ws.append([(b, w / 65535.0) for b, w in mesh.weights[v * k:(v + 1) * k] if w] if k else [])
    return pos, ws
