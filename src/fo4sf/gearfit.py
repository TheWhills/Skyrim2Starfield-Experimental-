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
CARRY = 0.10                    # m: gear takes the body offset of Skyrim body points within this distance
KEEP_REACH = 0.06               # m: gear that sat within this of Skyrim's body keeps its Skyrim gap on Starfield's
PULL_MAX = 0.04                 # m: most a vertex is pulled back in
COVER_MAX = 0.025               # m: most a gear vertex is moved to cover body points coming through it
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


# torso bones: moved onto Starfield's joints only, no turn or stretch (2026-11-06, Ralof: Skyrim's pelvis joint sits
# level with the spine base, so pelvis -> spine pointed sideways and turned the hips 53 deg; Starfield has four spine
# bones to Skyrim's three, so segment lengths do not compare and the clamp squashed them to 0.75)
NO_TURN = ("NPC Pelvis [Pelv]", "NPC Spine [Spn0]", "NPC Spine1 [Spn1]", "NPC Spine2 [Spn2]", "NPC Root [Root]",
           "NPC COM [COM ]",
           # the neck too (2026-11-06, Ralof's cowl: weighted chest + neck, the neck moved onto its own Starfield joint
           # and the two halves pulled the cowl out into a bulge behind the neck)
           "NPC Neck [Neck]",
           # and the head (2026-11-06: the cowl's top is partly head-weighted; Starfield's head joint sits farther
           # forward, so moving it onto that joint pulled the cowl forward). Helmets will want their own head fit.
           "NPC Head [Head]")
# joints the overall fit lines up: the body's axis and legs. Arms and fingers are left out (2026-11-06, Ralof: with
# them in, Skyrim's different A-pose arm angle tipped the whole torso back, chest forward and coat hem behind); the
# arms get their own per-bone turns.
AXIAL = ("NPC Pelvis [Pelv]", "NPC Spine [Spn0]", "NPC Spine1 [Spn1]", "NPC Spine2 [Spn2]", "NPC Neck [Neck]",
         "NPC Head [Head]", "NPC L Thigh [LThg]", "NPC R Thigh [RThg]", "NPC L Calf [LClf]", "NPC R Calf [RClf]",
         "NPC L Foot [Lft ]", "NPC R Foot [Rft ]")
AGREE = 0.7                     # body offsets: Skyrim and Starfield normals must agree this well (cos)
CAP = 0.04                      # m: largest body offset
SKIN_GAP = 0.002                # m: skin pieces (Skyrim body-textured parts, e.g. trousers painted on) pushed this far
ENVELOPE = {s: ((f"NPC {s} Foot [{s}ft ]", f"NPC {s} Toe0 [{s}Toe]"), (f"{s}_Foot", f"{s}_Toe")) for s in "LR"}
ENVELOPE_SCALE = (0.9, 1.35)    # per-axis clamp of the foot box fit
NEAR_WEIGHTS = (0.025, 0.05)    # m: gear this close to the body takes the body's weights, fading to its own by the 2nd
# weights only (animation keeps skeletonmap's bones): Starfield's body turns its neck with C_Neck_Twist (395 body
# vertices; C_Neck moves none), so gear on C_Neck stayed put when the head turned (owner 2026-11-06)
WEIGHT_REMAP = {"C_Neck": "C_Neck_Twist"}
NECK_SQUASH = (0.7, 1.0)        # clamp of the neck height ratio (Starfield / Skyrim, neck joint -> head joint)
DROP_TO_JOINT = ("NPC Neck [Neck]", "NPC Head [Head]")   # torso bones that still take their joint's height
FAR = 0.5                       # m: gear farther than this outside the Starfield body box means a broken transform


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
    axial = [(b, f) for b, f in pairs if b in AXIAL]
    fit_pairs = axial if len(axial) >= 4 else pairs
    src = np.array([joints[b][:3, 3] for b, _f in fit_pairs])
    dst = np.array([sf_world[f][:3, 3] for _b, f in fit_pairs])
    g = similarity(src, dst)
    rep_fit = [b for b, _f in fit_pairs]
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
        if b in NO_TURN:
            # the torso moves as one piece, by the overall fit (2026-11-06, Ralof: each torso joint moved onto its own
            # Starfield joint stepped the chest forward of the belly into a bulge with a crease)
            turn[b] = np.eye(3)
            out[b] = g.copy()
            rep["bones"][b] = {"to": f, "stretch": 1.0, "turn_deg": 0.0, "torso": True}
            if b in DROP_TO_JOINT:
                # height only (2026-11-06, Ralof's cowl too high: Starfield's neck sits lower on the shoulders);
                # forward / sideways stay with the torso (moving onto the joint fully made the cowl jut forward)
                dz = float(sf_world[f][2, 3] - (gl @ joints[b][:3, 3] + g[:3, 3])[2])
                out[b][2, 3] += dz
                rep["bones"][b]["height_mm"] = round(dz * 1000, 1)
                head_sky, head_sf = "NPC Head [Head]", sf_main("NPC Head [Head]")
                if b == "NPC Neck [Neck]" and head_sky in joints and head_sf:
                    # Starfield's neck is shorter: squash the neck's gear in height about the neck joint
                    # (2026-11-06, owner: the cowl a turtleneck where Skyrim's is a half one)
                    sky_len = float(np.linalg.norm(aligned[head_sky] - aligned[b]))
                    sf_len = float(np.linalg.norm(sf_world[head_sf][:3, 3] - sf_world[f][:3, 3]))
                    r = float(np.clip(sf_len / max(sky_len, 1e-6), *NECK_SQUASH))
                    qz = float(sf_world[f][2, 3])
                    sq = np.eye(4)
                    sq[2, 2], sq[2, 3] = r, qz * (1.0 - r)
                    out[b] = sq @ out[b]
                    rep["bones"][b]["neck_height_ratio"] = round(r, 3)
            continue
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
    rep["fit_joints"] = rep_fit
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
                f = WEIGHT_REMAP.get(f, f)
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


def _knn_mean_facing(src: np.ndarray, src_n: np.ndarray, values: np.ndarray, query: np.ndarray, query_n: np.ndarray,
                     k: int, radius: float, chunk: int = 256) -> np.ndarray:
    """As _knn_mean, each source weighted also by how well its normal agrees with the query's (cos^2, facing only):
    a shin point learns from the shin, not from the calf behind it (2026-11-06, owner: the leg's shape differs)."""
    out = np.zeros((len(query), values.shape[1]))
    ss = (src * src).sum(1)
    for c in range(0, len(query), chunk):
        q, qn = query[c:c + chunk], query_n[c:c + chunk]
        d2 = (q * q).sum(1)[:, None] + ss[None, :] - 2.0 * q @ src.T
        kk = min(k, len(src))
        idx = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
        d = np.sqrt(np.maximum(np.take_along_axis(d2, idx, 1), 0.0))
        face = np.clip(np.einsum("ij,ikj->ik", qn, src_n[idx]), 0.0, 1.0) ** 2
        w = np.where(d < radius, face / np.maximum(d, 1e-3), 0.0)
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
                 smooth: int = 2, sky_nrm: Optional[np.ndarray] = None, agree: float = AGREE,
                 cap: float = CAP) -> Tuple[np.ndarray, Dict]:
    """Per moved-Skyrim-body point the offset onto the Starfield surface (along Starfield's normal), smoothed. A
    point counts only when the two surfaces face the same way there (normals within acos(agree)); offsets are capped
    (2026-11-06, Ralof: unchecked matches moved the chest up to 68 mm into a shelf)."""
    depth, dist, idx = nearest_surface(sky_body, sf_pts, sf_nrm)
    ok = dist < reach
    if sky_nrm is not None and len(sky_nrm) == len(sky_body):
        ok &= np.einsum("ij,ij->i", sky_nrm, sf_nrm[idx]) > agree
    depth = np.clip(depth, -cap, cap)
    off = np.where(ok[:, None], -depth[:, None] * sf_nrm[idx], 0.0)
    for _ in range(smooth):
        off = _knn_mean(sky_body, off, sky_body, 6, 0.03)
    return off, {"matched": int(ok.sum()), "points": int(len(sky_body)),
                 "median_depth_mm": float(np.median(np.abs(depth[ok])) * 1000) if ok.any() else None}


def closest_on_mesh(points: np.ndarray, verts: np.ndarray, tris: np.ndarray, vnrm: np.ndarray, k: int = 6,
                    chunk: int = 256, with_normals: bool = False):
    """(closest surface point, signed depth along the outward face normal, distance) of each point on a triangle
    mesh, searching the triangles around its k nearest vertices (2026-11-06: nearest-VERTEX depth missed boot and
    sole points just inside the shins and feet, where the body's vertices lie several cm apart)."""
    tris = np.asarray(tris, int).reshape(-1, 3)
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    flip = np.einsum("ij,ij->i", fn, vnrm[tris].sum(1)) < 0          # face normals the way the vertex normals point
    fn[flip] *= -1
    vt = [[] for _ in range(len(verts))]
    for t, tri in enumerate(tris):
        for v in tri:
            vt[v].append(t)
    vv = (verts * verts).sum(1)
    best_p = np.zeros_like(points)
    best_d = np.full(len(points), np.inf)
    best_s = np.zeros(len(points))
    best_n = np.zeros_like(points)
    for c0 in range(0, len(points), chunk):
        q = points[c0:c0 + chunk]
        d2 = (q * q).sum(1)[:, None] + vv[None, :] - 2.0 * q @ verts.T
        kk = min(k, len(verts))
        near = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
        for j in range(len(q)):
            cand = np.unique([t for v in near[j] for t in vt[v]])
            if not len(cand):
                continue
            cp = _closest_on_triangles(q[j], a[cand], b[cand], c[cand])
            dist = np.linalg.norm(cp - q[j], axis=1)
            i = int(np.argmin(dist))
            best_p[c0 + j], best_d[c0 + j] = cp[i], dist[i]
            best_s[c0 + j] = float((q[j] - cp[i]) @ fn[cand[i]])
            best_n[c0 + j] = fn[cand[i]]
    if with_normals:
        return best_p, best_s, best_d, best_n
    return best_p, best_s, best_d


def _closest_on_triangles(p, a, b, c) -> np.ndarray:
    """Closest point to p on each triangle (a, b, c) (Ericson, Real-Time Collision Detection 5.1.5), vectorised."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = np.where(np.abs(va + vb + vc) > 1e-20, va + vb + vc, 1e-20)
    v, w = vb / den, vc / den
    out = a + ab * v[:, None] + ac * w[:, None]                       # inside the face
    with np.errstate(divide="ignore", invalid="ignore"):
        # edges
        e_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        t = np.where(e_ab, d1 / np.where(d1 - d3 != 0, d1 - d3, 1), 0)
        out = np.where(e_ab[:, None], a + ab * t[:, None], out)
        e_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        t = np.where(e_ac, d2 / np.where(d2 - d6 != 0, d2 - d6, 1), 0)
        out = np.where(e_ac[:, None], a + ac * t[:, None], out)
        e_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        t = np.where(e_bc, (d4 - d3) / np.where((d4 - d3) + (d5 - d6) != 0, (d4 - d3) + (d5 - d6), 1), 0)
        out = np.where(e_bc[:, None], b + (c - b) * t[:, None], out)
    # vertices
    out = np.where(((d1 <= 0) & (d2 <= 0))[:, None], a, out)
    out = np.where(((d3 >= 0) & (d4 <= d3))[:, None], b, out)
    out = np.where(((d6 >= 0) & (d5 <= d6))[:, None], c, out)
    return out


def _neighbours(n: int, tris: np.ndarray) -> List[np.ndarray]:
    nb = [set() for _ in range(n)]
    for a, b, c in tris:
        nb[a] |= {b, c}
        nb[b] |= {a, c}
        nb[c] |= {a, b}
    return [np.array(sorted(x), int) for x in nb]


def cover(gear: np.ndarray, gear_nrm: np.ndarray, gear_tris, body: np.ndarray, body_nrm: Optional[np.ndarray] = None,
          gap: float = GAP, reach: float = 0.04, iters: int = 6, k: int = 3,
          most: float = COVER_MAX) -> Tuple[np.ndarray, int]:
    """Push gear faces out over body points that come through them (2026-11-06, Ralof's boots: 202 vertices, every one
    outside the leg, yet the flat faces between them cut through the calf and toes). A body point counts when its
    closest gear point is within `reach`, lies inside a face (the offset runs along the face normal, not off an
    edge, so the leg above an opening does not drag its rim), that face looks away from the body (its normal agrees
    with the body's there: inner layers facing the skin are left alone) and the point is less than `gap` inside it.
    The k gear vertices nearest the spot get the shortfall; the push is spread over each vertex's neighbours (two
    averaging passes, so single vertices do not spike), capped at `most` in total, and repeated."""
    tris = np.asarray(gear_tris, int).reshape(-1, 3)
    if not len(tris) or not len(body):
        return gear, 0
    out = gear.copy()
    nrm = gear_nrm / np.maximum(np.linalg.norm(gear_nrm, axis=1, keepdims=True), 1e-12)
    lo, hi = gear.min(0) - reach, gear.max(0) + reach
    sel = ((body >= lo) & (body <= hi)).all(1)
    near_body = body[sel]
    near_n = body_nrm[sel] if body_nrm is not None else None
    nb = _neighbours(len(out), tris)
    total = np.zeros(len(out))
    for _ in range(iters):
        if not len(near_body):
            break
        cp, depth, dist, fn = closest_on_mesh(near_body, out, tris, nrm, with_normals=True)
        along = np.abs(depth) >= 0.9 * np.maximum(dist, 1e-9)
        bad = (dist < reach) & along & (depth > -gap)
        if near_n is not None:
            bad &= np.einsum("ij,ij->i", fn, near_n) > 0.3
        if not bad.any():
            break
        need = depth[bad] + gap
        push = np.zeros(len(out))
        gg = (out * out).sum(1)
        q = cp[bad]
        d2 = (q * q).sum(1)[:, None] + gg[None, :] - 2.0 * q @ out.T
        kk = min(k, len(out))
        idx = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
        for j in range(len(q)):
            for v in idx[j]:
                if need[j] > push[v]:
                    push[v] = need[j]
        for _p in range(2):                               # spread to neighbours: no single-vertex spikes
            spread = np.array([max(push[v], push[nb[v]].mean() if len(nb[v]) else 0.0) * 1.0
                               if push[v] > 0 else (0.5 * push[nb[v]].max() if len(nb[v]) else 0.0)
                               for v in range(len(out))])
            push = spread
        push = np.minimum(push, np.maximum(most - total, 0.0))
        if not (push > 1e-5).any():
            break
        out += push[:, None] * nrm
        total += push
    return out, int((total > 1e-5).sum())


NECK_RATIO = (0.6, 1.0)        # clamp of the Starfield / Skyrim neck height ratio (clavicles -> head joint)
NECK_RADIUS = (0.07, 0.14)      # m from the neck's axis: full squash inside the first, none past the second


def neck_squash_params(joints: Dict[str, np.ndarray], transforms: Dict[str, np.ndarray],
                       sf_world: Dict[str, np.ndarray]):
    """(ratio, Starfield clavicle height, neck axis x y) or None: Starfield's neck is shorter than Skyrim's (clavicles
    to head joint), so gear around it is squashed in height above the clavicles (2026-11-06, Ralof: the cowl's top
    sat ~5 cm higher on Starfield's neck than on Skyrim's: a turtleneck where Skyrim's is a half one)."""
    g = transforms.get("NPC Spine2 [Spn2]")
    clav_sky = [joints[b][:3, 3] for b in ("NPC L Clavicle [LClv]", "NPC R Clavicle [RClv]") if b in joints]
    clav_sf = [sf_world[b][:3, 3] for b in ("L_Clavicle", "R_Clavicle") if b in sf_world]
    if g is None or not clav_sky or not clav_sf or "NPC Head [Head]" not in joints or "C_Head" not in sf_world:
        return None
    sky = lambda p: g[:3, :3] @ p + g[:3, 3]
    sky_base = float(np.mean([sky(p)[2] for p in clav_sky]))
    sky_top = float(sky(joints["NPC Head [Head]"][:3, 3])[2])
    sf_base = float(np.mean([p[2] for p in clav_sf]))
    sf_top = float(sf_world["C_Head"][2, 3])
    r = float(np.clip((sf_top - sf_base) / max(sky_top - sky_base, 1e-6), *NECK_RATIO))
    axis = (sf_world["C_Neck"] if "C_Neck" in sf_world else sf_world["C_Head"])[:2, 3]
    return r, sf_base, np.asarray(axis, float)


def neck_squash(pts: np.ndarray, params) -> np.ndarray:
    if params is None or not len(pts):
        return pts
    r, base, axis = params
    rho = np.linalg.norm(pts[:, :2] - axis, axis=1)
    w = np.clip((NECK_RADIUS[1] - rho) / (NECK_RADIUS[1] - NECK_RADIUS[0]), 0.0, 1.0)
    above = pts[:, 2] > base
    out = pts.copy()
    out[:, 2] = np.where(above, pts[:, 2] + w * (base + r * (pts[:, 2] - base) - pts[:, 2]), pts[:, 2])
    return out


CHIN_REACH = 0.08     # m: gear with the Skyrim head this close straight above it keeps that clearance under the head


def gap_above(pts: np.ndarray, mesh_pts: np.ndarray, mesh_tris, chunk: int = 256) -> np.ndarray:
    """Per point, the distance straight up (+z) to the mesh (inf: no triangle above it)."""
    pts = np.asarray(pts, float)
    out = np.full(len(pts), np.inf)
    t = np.asarray(mesh_tris, int).reshape(-1, 3)
    if not len(pts) or not len(t):
        return out
    a, b, c = (np.asarray(mesh_pts, float)[t[:, k]] for k in range(3))
    v0, v1 = (b - a)[:, :2], (c - a)[:, :2]
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    ok = np.abs(den) > 1e-12
    a, b, c, v0, v1, den = a[ok], b[ok], c[ok], v0[ok], v1[ok], den[ok]
    for i in range(0, len(pts), chunk):
        p = pts[i:i + chunk]
        q = p[:, None, :2] - a[None, :, :2]
        u = (q[..., 0] * v1[:, 1] - v1[:, 0] * q[..., 1]) / den
        v = (v0[:, 0] * q[..., 1] - q[..., 0] * v0[:, 1]) / den
        inside = (u >= 0) & (v >= 0) & (u + v <= 1)
        z = a[None, :, 2] + u * (b[None, :, 2] - a[None, :, 2]) + v * (c[None, :, 2] - a[None, :, 2])
        d = np.where(inside & (z > p[:, None, 2]), z - p[:, None, 2], np.inf)
        out[i:i + chunk] = d.min(1)
    return out


def chin_clearance(sky_pts: np.ndarray, pts: np.ndarray, tris, sky_head, sf_head, scale: float = 1.0,
                   reach: float = CHIN_REACH):
    """Gear lowered so the gap straight up to the Starfield head is at least its gap to the Skyrim head in Skyrim
    (times scale) (2026-11-07, Ralof: the cowl's front stood up to the chin, a turtleneck where Skyrim's folds below
    it; the clavicle-to-head ratio is 1.0, so the neck squash does nothing). sky_head / sf_head: (points, triangles)
    in the same space as sky_pts / pts. Neighbours follow (smoothed), never less than each vertex's own need.
    Returns (points, vertices lowered, largest drop in m)."""
    g_sky = gap_above(sky_pts, *sky_head) * scale
    near = g_sky < reach
    if not near.any():
        return pts, 0, 0.0
    g_sf = gap_above(pts, *sf_head)
    need = np.where(near & np.isfinite(g_sf), np.maximum(0.0, g_sky - g_sf), 0.0)
    if not (need > 0).any():
        return pts, 0, 0.0
    raw = np.zeros_like(pts)
    raw[:, 2] = -need
    soft = smooth_moves(pts, pts + raw, tris, rounds=4) - pts
    d = np.minimum(raw, soft)
    return pts + d, int((need > 0).sum()), float(need.max())


def smooth_moves(base: np.ndarray, pts: np.ndarray, tris, rounds: int = 3) -> np.ndarray:
    """The fit's moves (pts - base) averaged with each vertex's neighbours: neighbours pushed apart (pull-in,
    push-out, cover each moving single vertices) folded the small subdivided faces over, and folded faces are not
    drawn (2026-11-06, Ralof: see-through patches on the chest under the cowl)."""
    t = np.asarray(tris, int).reshape(-1, 3)
    if not len(t):
        return pts
    nb = _neighbours(len(pts), t)
    d = pts - base
    for _ in range(rounds):
        d = np.array([(d[v] + d[nb[v]].sum(0)) / (1 + len(nb[v])) if len(nb[v]) else d[v] for v in range(len(d))])
    return base + d


def weld(original: np.ndarray, pts: np.ndarray, decimals: int = 5) -> Tuple[np.ndarray, int]:
    """Vertices that were one point in the Skyrim mesh (copies along UV seams) put back on one point: their mean
    (2026-11-06, Ralof's boots: the fit steps moved the two sides of the heel seam apart into a crack)."""
    key = np.round(np.asarray(original, float), decimals)
    _u, inv, counts = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    if (counts > 1).sum() == 0:
        return pts, 0
    sums = np.zeros((len(counts), 3))
    np.add.at(sums, inv, pts)
    mean = sums / counts[:, None]
    out = np.where((counts[inv] > 1)[:, None], mean[inv], pts)
    return out, int((counts[inv] > 1).sum())


def top_bones(sky_pts: np.ndarray, weights, share: float = 0.1, n: int = 6) -> Dict[str, float]:
    """Mean weight per bone of the top tenth of a shape by its Skyrim height (on a coat, the collar): which bones it
    follows (2026-11-06: does the cowl turn with the head?)."""
    if not len(sky_pts):
        return {}
    sel = np.nonzero(sky_pts[:, 2] >= np.quantile(sky_pts[:, 2], 1.0 - share))[0]
    acc: Dict[str, float] = {}
    for v in sel:
        for b, w in weights[v]:
            acc[b] = acc.get(b, 0.0) + w / len(sel)
    return {b: round(w, 3) for b, w in sorted(acc.items(), key=lambda kv: -kv[1])[:n]}


def gap_report(sky_pts: np.ndarray, sky_gap: np.ndarray, pts: np.ndarray, sf_pts, sf_tris, sf_nrm) -> Dict:
    """Median gap to the body (mm) in Skyrim and now in Starfield, for the vertices that sat within KEEP_REACH of
    Skyrim's body: all of them and the top tenth by height (on a coat, the collar)."""
    _cp, now, _d = closest_on_mesh(pts, sf_pts, np.asarray(sf_tris, int).reshape(-1, 3), sf_nrm)
    near = np.isfinite(sky_gap) & (sky_gap > -0.005) & (sky_gap < KEEP_REACH)
    out = {}
    for name, sel in (("all", near), ("top", near & (sky_pts[:, 2] >= np.quantile(sky_pts[:, 2], 0.9)))):
        if sel.any():
            out[name] = {"skyrim": round(float(np.median(sky_gap[sel])) * 1000, 1),
                         "starfield": round(float(np.median(now[sel])) * 1000, 1), "vertices": int(sel.sum())}
    return out


def keep_gap(pts: np.ndarray, sky_gap: np.ndarray, sf_pts: np.ndarray, sf_tris, sf_nrm: np.ndarray, gap: float = GAP,
             reach: float = KEEP_REACH, most: float = PULL_MAX) -> Tuple[np.ndarray, int]:
    """Pull gear back in to the gap it had on Skyrim's body (2026-11-06, owner: sleeve hems standing off the arm, the
    collar thicker than in Skyrim, boot tops off the leg: the fit only ever moves gear outward). sky_gap: each
    vertex's signed distance outside Skyrim's body; a vertex now farther than that (and than `gap`) outside
    Starfield's body moves toward it by the excess (at most `most`); push-out and cover run after this."""
    cp, depth, dist = closest_on_mesh(pts, sf_pts, np.asarray(sf_tris, int).reshape(-1, 3), sf_nrm)
    target = np.maximum(sky_gap, gap)
    excess = depth - target
    ok = (sky_gap > -0.005) & (sky_gap < reach) & (dist < reach + 0.03) & (excess > 0.002) & (depth > 0)
    out = pts.copy()
    move = np.minimum(excess[ok], most)
    toward = (cp[ok] - pts[ok]) / np.maximum(dist[ok], 1e-9)[:, None]
    out[ok] += toward * move[:, None]
    return out, int(ok.sum())


def push_out(points: np.ndarray, sf_pts: np.ndarray, sf_nrm: np.ndarray, gap: float = GAP,
             reach: float = PUSH_REACH, tris: Optional[np.ndarray] = None) -> Tuple[np.ndarray, int]:
    """Gear points inside (or within `gap` of) the body moved out to `gap` along the body's outward normal; against
    the triangles when given, else the nearest vertex."""
    if tris is not None and len(tris):
        cp, depth, dist = closest_on_mesh(points, sf_pts, tris, sf_nrm)
        tri_n = np.zeros_like(points)
        ok = np.isfinite(dist)
        diff = points - cp
        # outward direction: from the surface point to the gear point when outside, the reverse when inside
        nn = np.linalg.norm(diff, axis=1, keepdims=True)
        tri_n[ok] = np.where(nn[ok] > 1e-9, diff[ok] / np.maximum(nn[ok], 1e-12) * np.sign(depth[ok])[:, None],
                             0.0)
        bad = ok & (dist < reach) & (depth < gap)
        _d, _dist, idx = nearest_surface(points[bad], sf_pts, sf_nrm)
        fallback = sf_nrm[idx]
        nrm = np.where((np.linalg.norm(tri_n[bad], axis=1) > 0.5)[:, None], tri_n[bad], fallback)
        out = points.copy()
        out[bad] = cp[bad] + gap * nrm
        return out, int(bad.sum())
    depth, dist, idx = nearest_surface(points, sf_pts, sf_nrm)
    bad = (dist < reach) & (depth < gap)
    out = points.copy()
    out[bad] += (gap - depth[bad])[:, None] * sf_nrm[idx[bad]]
    return out, int(bad.sum())


@dataclass
class FitResult:
    shapes: List[HairShape]          # Starfield skeleton space, Starfield bone names
    report: Dict


def region(points: np.ndarray, bones: List[str], weights, wanted, min_weight: float = 0.5) -> np.ndarray:
    """The points whose weights on the wanted bones sum to at least min_weight."""
    keep = [v for v, vw in enumerate(weights)
            if sum(w for bi, w in vw if 0 <= bi < len(bones) and bones[bi] in wanted) >= min_weight]
    return points[keep] if keep else np.zeros((0, 3))


def box_fit(src: np.ndarray, dst: np.ndarray, clamp=ENVELOPE_SCALE) -> np.ndarray:
    """4x4 taking src's axis-aligned box onto dst's: centre onto centre, per-axis scale (clamped)."""
    lo_s, hi_s, lo_d, hi_d = src.min(0), src.max(0), dst.min(0), dst.max(0)
    sc = np.clip((hi_d - lo_d) / np.maximum(hi_s - lo_s, 1e-6), *clamp)
    m = np.eye(4)
    m[:3, :3] = np.diag(sc)
    m[:3, 3] = (lo_d + hi_d) / 2 - sc * (lo_s + hi_s) / 2
    return m


def fit(gear: List[SkyShape], sky_body: List[SkyShape], sf_world: Dict[str, np.ndarray], sf_body_pts: np.ndarray,
        sf_body_tris: np.ndarray, gap: float = GAP, sf_body_weights=None, size_feet: bool = False,
        weight_src=None, heads=None) -> FitResult:
    """The gear in Starfield skeleton space. sf_body_pts: the Starfield body in skeleton space (metres);
    sf_body_weights: its per-vertex [(Starfield bone name, weight)] (feet box fit; None skips it). weight_src:
    (points, triangles, weights) gear near it takes its weights from instead of the body surface (the whole head as
    well, so a collar under the jaw turns with the head as the head's own neck skin does). heads: ((Skyrim head points
    in Skyrim space, triangles), (Starfield head points in skeleton space, triangles)) for chin_clearance."""
    joints: Dict[str, np.ndarray] = {}
    for s in sky_body + gear:
        for b, w in s.joints.items():
            joints.setdefault(b, w)
    transforms, rep = bone_transforms(joints, sf_world)
    follows = follow_map(joints, transforms)
    sf_nrm = _vertex_face_normals(sf_body_pts, np.asarray(sf_body_tris, int).reshape(-1, 3))
    sf_nrm = outward(sf_body_pts, sf_nrm / np.maximum(np.linalg.norm(sf_nrm, axis=1, keepdims=True), 1e-12))
    if weight_src is not None:
        w_pts, w_tris, w_w = np.asarray(weight_src[0], float), np.asarray(weight_src[1], int).reshape(-1, 3), \
            list(weight_src[2])
        w_nrm = _vertex_face_normals(w_pts, w_tris)
        w_nrm = outward(w_pts, w_nrm / np.maximum(np.linalg.norm(w_nrm, axis=1, keepdims=True), 1e-12))
    body_moved = [blend(s.points, s.normals, s.bones, s.weights, transforms) for s in sky_body]
    # off by default (2026-11-06, Ralof: scaling only the foot section opened a seam at the ankle; cover keeps the toes in)
    if size_feet and sf_body_weights is not None and sky_body:
        # feet: the joints alone leave Starfield's longer foot sticking out of the boot (2026-11-06, Ralof running:
        # toes and heels through the boot); fit the moved Skyrim foot's box onto Starfield's foot box
        rep["feet"] = {}
        sf_names = sorted({b for vw in sf_body_weights for b, _w in vw})
        sf_idx = [[(sf_names.index(b), w) for b, w in vw] for vw in sf_body_weights]
        for side, (sky_b, sf_b) in ENVELOPE.items():
            src = np.concatenate([region(p, s.bones, s.weights, sky_b) for (p, _n), s in zip(body_moved, sky_body)])
            dst = region(sf_body_pts[:len(sf_idx)], sf_names, sf_idx, sf_b)
            if len(src) >= 20 and len(dst) >= 20:
                c = box_fit(src, dst)
                for b in sky_b:
                    if b in transforms:
                        transforms[b] = c @ transforms[b]
                rep["feet"][side] = {"scale": np.diag(c)[:3].round(3).tolist(),
                                     "shift_mm": (c[:3, 3] * 1000).round(0).tolist()}
        body_moved = [blend(s.points, s.normals, s.bones, s.weights, transforms) for s in sky_body]
    body_moved = [(neck_squash(p, neck_squash_params(joints, transforms, sf_world)), n) for p, n in body_moved]
    bp = np.concatenate([p for p, _n in body_moved]) if body_moved else np.zeros((0, 3))
    sky_bp = np.concatenate([s.points for s in sky_body]) if sky_body else np.zeros((0, 3))
    sky_bn = np.concatenate([s.normals for s in sky_body]) if sky_body else np.zeros((0, 3))
    sky_bt, base = [], 0
    for s_ in sky_body:
        sky_bt += [(a + base, b + base, c + base) for a, b, c in s_.triangles]
        base += len(s_.points)
    sky_bt = np.array(sky_bt, int).reshape(-1, 3)
    if len(sky_bn):
        sky_bn = outward(sky_bp, sky_bn)
    bn = np.concatenate([n for _p, n in body_moved]) if body_moved else np.zeros((0, 3))
    if len(bn):
        bn = outward(bp, bn)
    off, rep["body"] = body_offsets(bp, sf_body_pts, sf_nrm, sky_nrm=bn) if len(bp) else (np.zeros((0, 3)), {})
    shapes, rep["shapes"] = [], {}
    neck = neck_squash_params(joints, transforms, sf_world)
    if neck is not None:
        rep["neck_squash"] = {"ratio": round(neck[0], 3), "clavicle_height_m": round(neck[1], 3)}
    for s in gear:
        pts, nrm = blend(s.points, s.normals, s.bones, s.weights, transforms)
        pts = neck_squash(pts, neck)
        moved_base = pts.copy()
        skin = False
        sky_gap = None
        if len(sky_bp):
            d, dist, _i = nearest_surface(s.points, sky_bp, sky_bn)
            skin = bool(np.median(np.abs(d)) < SKIN_DEPTH and np.median(dist) < 0.01)
            if len(sky_bt):
                _cp, sky_gap, sky_dist = closest_on_mesh(s.points, sky_bp, sky_bt, sky_bn)
                sky_gap = np.where(sky_dist < KEEP_REACH + 0.03, sky_gap, np.inf)
        shift = _knn_mean_facing(bp, bn, off, pts, nrm, 24, CARRY) if len(bp) else np.zeros_like(pts)
        pts = pts + shift
        pulled = 0
        if not skin and sky_gap is not None and len(sf_body_pts):
            pts, pulled = keep_gap(pts, sky_gap, sf_body_pts, sf_body_tris, sf_nrm, gap)
        pushed = 0
        if len(sf_body_pts):
            # skin pieces too, closer: Skyrim paints clothes on body-textured parts (Stormcloak trousers)
            pts, pushed = push_out(pts, sf_body_pts, sf_nrm, SKIN_GAP if skin else gap,
                                   tris=np.asarray(sf_body_tris, int).reshape(-1, 3))
        covered = 0
        if not skin and len(sf_body_pts):
            pts, covered = cover(pts, nrm, s.triangles, sf_body_pts, sf_nrm, gap)
            # smooth the moves (no folded faces), then make sure nothing came back inside the body
            pts = smooth_moves(moved_base, pts, s.triangles)
            pts, _again = push_out(pts, sf_body_pts, sf_nrm, gap, tris=np.asarray(sf_body_tris, int).reshape(-1, 3))
        lowered, drop = 0, 0.0
        if heads is not None and not skin:
            pts, lowered, drop = chin_clearance(s.points, pts, s.triangles, heads[0], heads[1],
                                                rep.get("global_scale", 1.0))
            if lowered and len(sf_body_pts):
                pts, _again = push_out(pts, sf_body_pts, sf_nrm, gap,
                                       tris=np.asarray(sf_body_tris, int).reshape(-1, 3))
        pts, welded = weld(s.points, pts)
        bad = ~np.isfinite(pts).all(1)
        if len(sf_body_pts):
            lo, hi = sf_body_pts.min(0) - FAR, sf_body_pts.max(0) + FAR
            far = int((((pts < lo) | (pts > hi)).any(1) & ~bad).sum())
        else:
            far = 0
        w = sf_weights(s.bones, s.weights, set(sf_world), follows)
        near = 0
        if weight_src is not None and len(pts):
            w, near = body_weights_near(pts, w, w_pts, w_nrm, w_w, set(sf_world))
        elif sf_body_weights is not None and len(sf_body_weights) == len(sf_body_pts) and len(pts):
            w, near = body_weights_near(pts, w, sf_body_pts, sf_nrm, sf_body_weights, set(sf_world))
        shapes.append(HairShape(s.name, pts, nrm, np.zeros_like(nrm), list(s.uvs), list(s.triangles), w, -1, -1, -1,
                                colors=[(255, 255, 255, 255)] * len(pts)))
        rep["shapes"][s.name.decode("latin-1", "replace")] = {
            "vertices": int(len(pts)), "skin_piece": skin, "pushed_out": pushed,
            "max_body_shift_mm": float(np.linalg.norm(shift, axis=1).max() * 1000) if len(shift) else 0.0,
            "not_finite": int(bad.sum()), "far_outside": far,
            "box_m": [np.nanmin(pts, 0).round(3).tolist(), np.nanmax(pts, 0).round(3).tolist()] if len(pts) else [],
            "unweighted": sum(1 for x in w if not x), "bones": sorted({b for x in w for b, _ in x}),
            "body_weighted": near, "covered": covered, "pulled_in": pulled, "welded": welded,
            "chin_lowered": lowered, "chin_drop_mm": round(drop * 1000, 1),
            "top_bones": top_bones(s.points, w),
            "gaps_mm": gap_report(s.points, sky_gap, pts, sf_body_pts, sf_body_tris, sf_nrm) if (
                sky_gap is not None and len(sf_body_pts) and not skin) else {}}
    return FitResult(shapes, rep)


def body_weights_near(pts: np.ndarray, own, body_pts: np.ndarray, body_nrm: np.ndarray, body_w, bones,
                      near=NEAR_WEIGHTS) -> Tuple[list, int]:
    """Gear lying on the body takes the nearest body vertex's weights (fully within near[0], blended to its own by
    near[1]), so it bends exactly like the skin under it (2026-11-06, Ralof running: boot heels and the Starfield
    heel moved apart with Skyrim's own weights)."""
    _d, dist, idx = nearest_surface(pts, body_pts, body_nrm)
    t = np.clip((dist - near[0]) / max(near[1] - near[0], 1e-6), 0.0, 1.0)
    out, n = [], 0
    for v, vw in enumerate(own):
        bw = [(b, x) for b, x in body_w[idx[v]] if b in bones]
        if t[v] >= 1.0 or not bw:
            out.append(vw)
            continue
        acc: Dict[str, float] = {}
        for b, x in bw:
            acc[b] = acc.get(b, 0.0) + (1.0 - t[v]) * x
        for b, x in vw:
            acc[b] = acc.get(b, 0.0) + t[v] * x
        top = [(b, float(x)) for b, x in sorted(acc.items(), key=lambda kv: -kv[1])[:MAX_WEIGHTS] if x > 1e-6]
        tot = sum(x for _b, x in top)
        out.append([(b, x / tot) for b, x in top] if tot > 0 else vw)
        n += 1
    return out, n


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


def morph_path(nif_rel: str, shape_name: str) -> str:
    """Where the game looks for a worn shape's body-slider morphs (verified 2026-11-06 from the vanilla layout:
    meshes/morphs/<NIF path below meshes, no .nif>/chargen/<shape name, lower case, no ':N'>/morph.dat)."""
    stem = nif_rel.replace("\\", "/").lower()
    stem = stem[len("meshes/"):] if stem.startswith("meshes/") else stem
    stem = stem[:-4] if stem.endswith(".nif") else stem
    shape = shape_name.split(":")[0].lower()
    return f"meshes/morphs/{stem}/chargen/{shape}/morph.dat"


def morph_deltas(points: np.ndarray, body_pts: np.ndarray, body_morph, k: int = 6, chunk: int = 256):
    """({key: {vertex: delta}}, {key: {vertex: (colour, normal, tangent)}}) for gear points (body mesh space): the
    inverse-distance blend of the k nearest body vertices' slider deltas, the packed words of the nearest one."""
    keys = list(body_morph.keys)
    nb = len(body_pts)
    dense = {key: np.zeros((nb, 3)) for key in keys}
    for key in keys:
        for v, d in body_morph.deltas[key].items():
            if v < nb:
                dense[key][v] = d
    out = {key: {} for key in keys}
    extra = {key: {} for key in keys}
    bb = (body_pts * body_pts).sum(1)
    for c in range(0, len(points), chunk):
        q = points[c:c + chunk]
        d2 = (q * q).sum(1)[:, None] + bb[None, :] - 2.0 * q @ body_pts.T
        kk = min(k, nb)
        idx = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
        d = np.sqrt(np.maximum(np.take_along_axis(d2, idx, 1), 0.0))
        w = 1.0 / np.maximum(d, 1e-3)
        w /= w.sum(1, keepdims=True)
        near = idx[np.arange(len(q)), np.argmin(d, axis=1)]
        for key in keys:
            blend = (w[:, :, None] * dense[key][idx]).sum(1)
            for j in range(len(q)):
                if np.abs(blend[j]).max() > 1e-5:
                    out[key][c + j] = tuple(float(x) for x in blend[j])
                    extra[key][c + j] = body_morph.extra[key].get(int(near[j]), (0, 0, 0))
    return out, extra
