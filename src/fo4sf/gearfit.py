"""Skyrim worn gear onto Starfield's body by its own skeleton (owner 2026-11-06: "fit the Starfield body the way it
does on Skyrim's"; Outfit Studio's fit left the collar over the face, the gloves on hip weights and the coat folded).

1. Bones: every Skyrim bone the meshes use gets a transform Skyrim model space -> Starfield skeleton space. A
   similarity fit of the matched joints (skeletonmap) lines the skeletons up as a whole; then each mapped bone moves
   its joint onto the Starfield joint, turns its direction (joint -> child joint) onto Starfield's and stretches along
   that direction by the length ratio (clamped). Bones without a child inherit their parent's turn; unmapped Skyrim
   bones (skirt chains, pauldrons, belly) follow the nearest mapped joint.
2. Gear: each vertex moves by the blend of its own Skyrim bones' transforms (linear blend, its Skyrim weights), so the
   collar follows the neck, the gloves the hands and the boots the feet.
3. Body: the Skyrim body moved the same way is compared with the Starfield body (nearest surface); the offset that
   puts it on the Starfield surface is smoothed and carried onto the gear nearby (girth, shoulders, chest). Gear left
   inside the Starfield body is pushed out to a small gap; skin pieces (gear lying on the Skyrim body) follow the
   offset only.
4. Weights: Skyrim bones renamed to Starfield bones (skeletonmap; a SPLIT bone shares its weight), at most 4.
Binds for the writer: bone rest world (skeleton.nif) against the body mesh's frame, as the game's own body.

Supported hypothesis until the owner's screenshots: the clamp range, the smoothing, the gap.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import skeletonmap
from .skyrimhair import MAX_WEIGHTS, UNIT, HairShape, nearest_surface, _vertex_face_normals

STRETCH = (0.75, 1.33)          # bone length ratio clamp
REACH = 0.08                    # m: Skyrim body points farther from Starfield's surface get no offset
CARRY = 0.15                    # m: gear takes the body offset of Skyrim body points within this distance
GAP = 0.004                     # m: gear pushed this far outside the Starfield body
PUSH_REACH = 0.06               # m: only gear this close to the Starfield body is pushed
SKIN_DEPTH = 0.003              # m: a shape whose vertices lie this close to the Skyrim body is a skin piece


def _chains() -> List[Tuple[str, str]]:
    out = [("NPC Pelvis [Pelv]", "NPC Spine [Spn0]"), ("NPC Spine [Spn0]", "NPC Spine1 [Spn1]"),
           ("NPC Spine1 [Spn1]", "NPC Spine2 [Spn2]"), ("NPC Spine2 [Spn2]", "NPC Neck [Neck]"),
           ("NPC Neck [Neck]", "NPC Head [Head]")]
    for s in "LR":
        out += [(f"NPC {s} Thigh [{s}Thg]", f"NPC {s} Calf [{s}Clf]"),
                (f"NPC {s} Calf [{s}Clf]", f"NPC {s} Foot [{s}ft ]"),
                (f"NPC {s} Foot [{s}ft ]", f"NPC {s} Toe0 [{s}Toe]"),
                (f"NPC {s} Clavicle [{s}Clv]", f"NPC {s} UpperArm [{s}Uar]"),
                (f"NPC {s} UpperArm [{s}Uar]", f"NPC {s} Forearm [{s}Lar]"),
                (f"NPC {s} Forearm [{s}Lar]", f"NPC {s} Hand [{s}Hnd]"),
                (f"NPC {s} Hand [{s}Hnd]", f"NPC {s} Finger20 [{s}F20]")]
        for d in "01234":
            out += [(f"NPC {s} Finger{d}0 [{s}F{d}0]", f"NPC {s} Finger{d}1 [{s}F{d}1]"),
                    (f"NPC {s} Finger{d}1 [{s}F{d}1]", f"NPC {s} Finger{d}2 [{s}F{d}2]")]
    return out


CHILD: Dict[str, str] = dict(_chains())
# bones with no child of their own turn like this one
INHERIT: Dict[str, str] = {"NPC Head [Head]": "NPC Neck [Neck]", "NPC Root [Root]": "NPC Pelvis [Pelv]",
                           "NPC COM [COM ]": "NPC Pelvis [Pelv]"}
for _s in "LR":
    INHERIT.update({f"NPC {_s} UpperarmTwist1 [{_s}Ut1]": f"NPC {_s} UpperArm [{_s}Uar]",
                    f"NPC {_s} UpperarmTwist2 [{_s}Ut2]": f"NPC {_s} UpperArm [{_s}Uar]",
                    f"NPC {_s} ForearmTwist1 [{_s}Lt1]": f"NPC {_s} Forearm [{_s}Lar]",
                    f"NPC {_s} ForearmTwist2 [{_s}Lt2]": f"NPC {_s} Forearm [{_s}Lar]",
                    f"NPC {_s} Toe0 [{_s}Toe]": f"NPC {_s} Foot [{_s}ft ]"})
    for _d in "01234":
        INHERIT[f"NPC {_s} Finger{_d}2 [{_s}F{_d}2]"] = f"NPC {_s} Finger{_d}1 [{_s}F{_d}1]"


@dataclass
class SkyShape:
    """A Skyrim skinned shape in metres, Skyrim model space."""
    name: bytes
    points: np.ndarray
    normals: np.ndarray
    uvs: list
    triangles: list
    bones: List[str]
    weights: list                    # per vertex [(bone index, weight)]
    joints: Dict[str, np.ndarray] = field(default_factory=dict)     # bone -> 4x4 bind world, metres


def from_skyrim(s) -> SkyShape:
    """A skyrimskin.SkinnedShape as a SkyShape (vertices to model space, units to metres, bind worlds per bone)."""
    from .skyrimhair import _bind_world, skin_to_model
    to_model, rot = skin_to_model(s)
    pts = np.array([to_model(v) for v in s.positions], float).reshape(-1, 3) * UNIT
    names = [b.decode("latin-1") if isinstance(b, bytes) else b for b in s.bones]
    tris = [tuple(int(i) for i in t) for t in s.triangles]
    if s.normals:
        nrm = np.array([rot(v) for v in s.normals], float)
    else:
        nrm = _vertex_face_normals(pts, np.array(tris, int).reshape(-1, 3))
    nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    joints = {}
    for k, nm in enumerate(names):
        if k < len(s.binds):
            w = _bind_world(s, k).copy()
            w[:3, 3] *= UNIT
            joints[nm] = w
    return SkyShape(s.name, pts, nrm, list(s.uvs), tris, names, [list(vw) for vw in s.weights], joints)


def sf_of(sky_bone: str) -> List[Tuple[str, float]]:
    if sky_bone in skeletonmap.MAP:
        return [(skeletonmap.MAP[sky_bone], 1.0)]
    if sky_bone in skeletonmap.SPLIT:
        return list(skeletonmap.SPLIT[sky_bone])
    return []


def similarity(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """4x4 s R x + t taking src points onto dst points (least squares, Umeyama)."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    u, sv, vt = np.linalg.svd(b.T @ a / len(src))
    d = np.eye(3)
    if np.linalg.det(u @ vt) < 0:
        d[2, 2] = -1
    r = u @ d @ vt
    s = float(np.trace(np.diag(sv) @ d) / ((a * a).sum() / len(src)))
    m = np.eye(4)
    m[:3, :3] = s * r
    m[:3, 3] = md - s * r @ ms
    return m


def rot_between(a, b) -> np.ndarray:
    """The smallest rotation turning direction a onto direction b."""
    a = np.asarray(a, float) / (np.linalg.norm(a) or 1.0)
    b = np.asarray(b, float) / (np.linalg.norm(b) or 1.0)
    v, c = np.cross(a, b), float(a @ b)
    if c < -0.999999:
        axis = np.cross(a, [1.0, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1.0, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1.0 + c)


def bone_transforms(joints: Dict[str, np.ndarray], sf_world: Dict[str, np.ndarray],
                    stretch=STRETCH) -> Tuple[Dict[str, np.ndarray], Dict]:
    """({Skyrim bone: 4x4 Skyrim model (m) -> Starfield skeleton space}, report)."""
    def sf_main(b):
        hits = [n for n, _w in sorted(sf_of(b), key=lambda x: -x[1]) if n in sf_world]
        return hits[0] if hits else None
    pairs = [(b, sf_main(b)) for b in joints if sf_main(b)]
    if len(pairs) < 3:
        raise ValueError(f"only {len(pairs)} Skyrim joints match Starfield bones")
    src = np.array([joints[b][:3, 3] for b, _f in pairs])
    dst = np.array([sf_world[f][:3, 3] for _b, f in pairs])
    g = similarity(src, dst)
    gl = g[:3, :3]
    aligned = {b: g[:3, :3] @ m[:3, 3] + g[:3, 3] for b, m in joints.items()}
    turn, out, rep = {}, {}, {"global_scale": float(np.cbrt(np.linalg.det(gl))), "bones": {}}

    def make(b, r, s_len, u):
        """x -> q + R S (G x - G p): the joint onto Starfield's, turned and stretched about it."""
        q = sf_world[sf_main(b)][:3, 3]
        rs = r @ (np.eye(3) + (s_len - 1.0) * np.outer(u, u)) @ gl
        a = np.eye(4)
        a[:3, :3] = rs
        a[:3, 3] = q - rs @ joints[b][:3, 3]
        return a

    for b, f in pairs:
        c = CHILD.get(b)
        cf = sf_main(c) if c in joints else None
        if c in joints and cf:
            ds = aligned[c] - aligned[b]
            df = sf_world[cf][:3, 3] - sf_world[f][:3, 3]
            if np.linalg.norm(ds) > 1e-4 and np.linalg.norm(df) > 1e-4:
                r = rot_between(ds, df)
                s_len = float(np.clip(np.linalg.norm(df) / np.linalg.norm(ds), *stretch))
                turn[b] = r
                out[b] = make(b, r, s_len, ds / np.linalg.norm(ds))
                rep["bones"][b] = {"to": f, "stretch": round(s_len, 3),
                                   "turn_deg": round(float(np.degrees(np.arccos(np.clip((np.trace(r) - 1) / 2, -1, 1)))), 1)}
    for _ in range(4):                                     # childless bones: their parent's turn, no stretch
        for b, f in pairs:
            if b in out:
                continue
            p = INHERIT.get(b)
            if p in turn or p is None:
                r = turn.get(p, np.eye(3))
                turn[b] = r
                out[b] = make(b, r, 1.0, np.array([0.0, 0.0, 1.0]))
                rep["bones"][b] = {"to": f, "stretch": 1.0, "turn_from": p}
    for b, f in pairs:                                     # anything left: no turn
        if b not in out:
            out[b] = make(b, np.eye(3), 1.0, np.array([0.0, 0.0, 1.0]))
            rep["bones"][b] = {"to": f, "stretch": 1.0, "turn_from": None}
    mapped = list(out)
    mp = np.array([aligned[b] for b in mapped])
    for b in joints:                                       # unmapped Skyrim bones follow the nearest mapped joint
        if b not in out:
            near = mapped[int(np.argmin(np.linalg.norm(mp - aligned[b], axis=1)))]
            out[b] = out[near]
            rep["bones"][b] = {"follows": near}
    rep["joint_rms_m"] = float(np.sqrt(np.mean(np.sum((src @ gl.T + g[:3, 3] - dst) ** 2, axis=1))))
    return out, rep


def follow_map(joints: Dict[str, np.ndarray], transforms: Dict[str, np.ndarray]) -> Dict[str, str]:
    """{unmapped Skyrim bone: mapped Skyrim bone it follows} (same transform object)."""
    mapped = {b for b in transforms if sf_of(b)}
    out = {}
    for b in transforms:
        if b not in mapped:
            out[b] = next((m for m in mapped if transforms[m] is transforms[b]), None)
    return out


def blend(points: np.ndarray, normals: np.ndarray, bones: List[str], weights, transforms) -> Tuple[np.ndarray,
                                                                                                    np.ndarray]:
    """Linear blend of each vertex's Skyrim bone transforms (its own weights); normals by the blended matrix."""
    pts = np.empty_like(points)
    nrm = np.empty_like(normals)
    for v, vw in enumerate(weights):
        m = np.zeros((4, 4))
        tot = 0.0
        for bi, w in vw:
            t = transforms.get(bones[bi]) if 0 <= bi < len(bones) else None
            if t is not None and w > 0:
                m += w * t
                tot += w
        if tot <= 0:
            m = next(iter(transforms.values()))
        else:
            m /= tot
        pts[v] = m[:3, :3] @ points[v] + m[:3, 3]
        n = np.linalg.inv(m[:3, :3]).T @ normals[v]
        nrm[v] = n / (np.linalg.norm(n) or 1.0)
    return pts, nrm


def sf_weights(bones: List[str], weights, sf_bones, follows: Dict[str, str]) -> List[List[Tuple[str, float]]]:
    """Skyrim weights renamed to Starfield bones (SPLIT shared, unmapped via the bone they follow), top 4."""
    out = []
    for vw in weights:
        acc: Dict[str, float] = {}
        for bi, w in vw:
            if not (0 <= bi < len(bones)) or w <= 0:
                continue
            b = bones[bi]
            hits = sf_of(b) or sf_of(follows.get(b) or "")
            for f, share in hits:
                if f in sf_bones:
                    acc[f] = acc.get(f, 0.0) + w * share
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:MAX_WEIGHTS]
        tot = sum(w for _b, w in top)
        out.append([(b, w / tot) for b, w in top] if tot > 0 else [])
    return out


def _knn_mean(src: np.ndarray, values: np.ndarray, query: np.ndarray, k: int, radius: float,
              chunk: int = 256) -> np.ndarray:
    """Inverse-distance mean of `values` at the k nearest `src` points within radius of each query (0 if none)."""
    out = np.zeros((len(query), values.shape[1]))
    ss = (src * src).sum(1)
    for c in range(0, len(query), chunk):
        q = query[c:c + chunk]
        d2 = (q * q).sum(1)[:, None] + ss[None, :] - 2.0 * q @ src.T
        kk = min(k, len(src))
        idx = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
        d = np.sqrt(np.maximum(np.take_along_axis(d2, idx, 1), 0.0))
        w = np.where(d < radius, 1.0 / np.maximum(d, 1e-3), 0.0)
        tot = w.sum(1, keepdims=True)
        out[c:c + chunk] = np.where(tot > 0, (w[:, :, None] * values[idx]).sum(1) / np.maximum(tot, 1e-12), 0.0)
    return out


def outward(points: np.ndarray, normals: np.ndarray) -> np.ndarray:
    """Normals flipped if most point toward the body's vertical axis (a body surface's normals point out)."""
    c = points.mean(0)
    radial = points - c
    radial[:, 2] = 0.0
    s = np.einsum("ij,ij->i", normals, radial)
    return -normals if np.median(s) < 0 else normals


def body_offsets(sky_body: np.ndarray, sf_pts: np.ndarray, sf_nrm: np.ndarray, reach: float = REACH,
                 smooth: int = 3) -> Tuple[np.ndarray, Dict]:
    """Per moved-Skyrim-body point the offset onto the Starfield surface (along Starfield's normal), smoothed."""
    depth, dist, idx = nearest_surface(sky_body, sf_pts, sf_nrm)
    ok = dist < reach
    off = np.where(ok[:, None], -depth[:, None] * sf_nrm[idx], 0.0)
    for _ in range(smooth):
        off = _knn_mean(sky_body, off, sky_body, 8, 0.05)
    return off, {"matched": int(ok.sum()), "points": int(len(sky_body)),
                 "median_depth_mm": float(np.median(np.abs(depth[ok])) * 1000) if ok.any() else None}


def push_out(points: np.ndarray, sf_pts: np.ndarray, sf_nrm: np.ndarray, gap: float = GAP,
             reach: float = PUSH_REACH) -> Tuple[np.ndarray, int]:
    depth, dist, idx = nearest_surface(points, sf_pts, sf_nrm)
    bad = (dist < reach) & (depth < gap)
    out = points.copy()
    out[bad] += (gap - depth[bad])[:, None] * sf_nrm[idx[bad]]
    return out, int(bad.sum())


@dataclass
class FitResult:
    shapes: List[HairShape]          # Starfield skeleton space, Starfield bone names
    report: Dict


def fit(gear: List[SkyShape], sky_body: List[SkyShape], sf_world: Dict[str, np.ndarray], sf_body_pts: np.ndarray,
        sf_body_tris: np.ndarray, gap: float = GAP) -> FitResult:
    """The gear in Starfield skeleton space. sf_body_pts: the Starfield body in skeleton space (metres)."""
    joints: Dict[str, np.ndarray] = {}
    for s in sky_body + gear:
        for b, w in s.joints.items():
            joints.setdefault(b, w)
    transforms, rep = bone_transforms(joints, sf_world)
    follows = follow_map(joints, transforms)
    sf_nrm = _vertex_face_normals(sf_body_pts, np.asarray(sf_body_tris, int).reshape(-1, 3))
    sf_nrm = outward(sf_body_pts, sf_nrm / np.maximum(np.linalg.norm(sf_nrm, axis=1, keepdims=True), 1e-12))
    body_moved = [blend(s.points, s.normals, s.bones, s.weights, transforms) for s in sky_body]
    bp = np.concatenate([p for p, _n in body_moved]) if body_moved else np.zeros((0, 3))
    sky_bp = np.concatenate([s.points for s in sky_body]) if sky_body else np.zeros((0, 3))
    sky_bn = np.concatenate([s.normals for s in sky_body]) if sky_body else np.zeros((0, 3))
    if len(sky_bn):
        sky_bn = outward(sky_bp, sky_bn)
    off, rep["body"] = body_offsets(bp, sf_body_pts, sf_nrm) if len(bp) else (np.zeros((0, 3)), {})
    shapes, rep["shapes"] = [], {}
    for s in gear:
        pts, nrm = blend(s.points, s.normals, s.bones, s.weights, transforms)
        skin = False
        if len(sky_bp):
            d, dist, _i = nearest_surface(s.points, sky_bp, sky_bn)
            skin = bool(np.median(np.abs(d)) < SKIN_DEPTH and np.median(dist) < 0.01)
        shift = _knn_mean(bp, off, pts, 8, CARRY) if len(bp) else np.zeros_like(pts)
        pts = pts + shift
        pushed = 0
        if not skin and len(sf_body_pts):
            pts, pushed = push_out(pts, sf_body_pts, sf_nrm, gap)
        w = sf_weights(s.bones, s.weights, set(sf_world), follows)
        shapes.append(HairShape(s.name, pts, nrm, np.zeros_like(nrm), list(s.uvs), list(s.triangles), w, -1, -1, -1,
                                colors=[(255, 255, 255, 255)] * len(pts)))
        rep["shapes"][s.name.decode("latin-1", "replace")] = {
            "vertices": int(len(pts)), "skin_piece": skin, "pushed_out": pushed,
            "max_body_shift_mm": float(np.linalg.norm(shift, axis=1).max() * 1000) if len(shift) else 0.0,
            "unweighted": sum(1 for x in w if not x), "bones": sorted({b for x in w for b, _ in x})}
    return FitResult(shapes, rep)


def mesh_frame(body_binds: Dict[str, tuple], sf_world: Dict[str, np.ndarray]) -> np.ndarray:
    """4x4 body mesh space -> skeleton space: world @ bind, the same for every bone of the game's body (median)."""
    ms = []
    for b, (_sp, rot, trans, scale) in body_binds.items():
        if b in sf_world:
            m = np.eye(4)
            m[:3, :3] = np.array(rot, float).reshape(3, 3) * float(scale or 1.0)
            m[:3, 3] = trans
            ms.append(sf_world[b] @ m)
    if not ms:
        raise ValueError("no body bone in the skeleton")
    return np.median(np.stack(ms), axis=0)


def skeleton_binds(bones, sf_world: Dict[str, np.ndarray], frame: np.ndarray, shapes=()) -> Dict[str, tuple]:
    """{bone: (sphere, rot 9, trans 3, scale)}: bind = inverse(rest world) @ frame, the game body's convention; the
    sphere (bone space) around the vertices weighted to the bone, from shapes given in mesh space."""
    out = {}
    for b in bones:
        bind = np.linalg.inv(sf_world[b]) @ frame
        pts = [np.asarray(sh.positions[k]) for sh in shapes for k, vw in enumerate(sh.weights)
               if any(x == b for x, _w in vw)]
        if pts:
            loc = np.array(pts) @ bind[:3, :3].T + bind[:3, 3]
            c = (loc.min(0) + loc.max(0)) / 2
            r = float(np.linalg.norm(loc - c, axis=1).max())
        else:
            c, r = np.zeros(3), 0.0
        out[b] = (tuple(map(float, c)) + (r,), tuple(map(float, bind[:3, :3].reshape(9))),
                  tuple(map(float, bind[:3, 3])), 1.0)
    return out


def to_mesh_space(shapes: List[HairShape], frame: np.ndarray) -> List[HairShape]:
    inv = np.linalg.inv(frame)
    out = []
    for sh in shapes:
        p = np.asarray(sh.positions) @ inv[:3, :3].T + inv[:3, 3]
        n = np.asarray(sh.normals) @ inv[:3, :3].T
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        out.append(HairShape(sh.name, p, n, sh.tangents, sh.uvs, sh.triangles, sh.weights, -1, -1, -1,
                             colors=sh.colors))
    return out
