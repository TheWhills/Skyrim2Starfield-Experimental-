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
import re
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


# Skyrim's skirt chains (SkirtFBone01..03 etc.) have no Starfield bones; the animations swing them part way with the
# legs. Shared between the hips and the thighs (2026-11-07, owner: Hadvar's tassets lifted with each leg when running,
# opening round the legs; they had taken the thigh skin's weights). Front / back plates between both thighs.
SKIRT_SHARES = {"F": (("C_Hips", 0.5), ("L_Thigh", 0.25), ("R_Thigh", 0.25)),
                "B": (("C_Hips", 0.5), ("L_Thigh", 0.25), ("R_Thigh", 0.25)),
                "L": (("C_Hips", 0.6), ("L_Thigh", 0.4)),
                "R": (("C_Hips", 0.6), ("R_Thigh", 0.4))}


def skirt_shares(sky_bone: str) -> List[Tuple[str, float]]:
    m = re.match(r"Skirt([FBLR])Bone\d+$", sky_bone or "")
    return list(SKIRT_SHARES[m.group(1)]) if m else []


SKIRT_THIGH = (0.3, 0.9)     # thigh share at the skirt's top (the hips) and at knee height; it rises with the square
#                              root of the way down (2026-11-07, owner: in a wide combat stance the thighs still came
#                              through the middle of the skirt with (0.2, 0.8) rising evenly)


def skirt_gradient(points: np.ndarray, joints: Dict[str, np.ndarray]):
    """Per point [(Starfield bone, weight)]: hips at the top, more and more thigh down to knee height, split between
    the thighs by how far left or right the point is (2026-11-07, owner: with fixed hips / thigh shares Hadvar's
    tassets stood out like a tutu and the thighs showed through them in a wide combat stance; Skyrim's skirt bones
    are swung by the animations, Starfield has none). None without pelvis, thigh and calf joints."""
    need = ("NPC Pelvis [Pelv]", "NPC L Thigh [LThg]", "NPC R Thigh [RThg]", "NPC L Calf [LClf]", "NPC R Calf [RClf]")
    if any(b not in joints for b in need):
        return None
    pel, lt, rt, lc, rc = (np.asarray(joints[b], float)[:3, 3] for b in need)
    top, knee = pel[2], (lc[2] + rc[2]) / 2
    p = np.asarray(points, float)
    t = np.clip((top - p[:, 2]) / max(top - knee, 1e-6), 0.0, 1.0)
    thigh = SKIRT_THIGH[0] + (SKIRT_THIGH[1] - SKIRT_THIGH[0]) * np.sqrt(t)
    span = lt[0] - rt[0]
    f = np.clip((p[:, 0] - rt[0]) / (span if abs(span) > 1e-6 else 1e-6), 0.0, 1.0)   # 1: left side
    out = []
    for h, fl in zip(thigh, f):
        vw = [("C_Hips", 1.0 - h), ("L_Thigh", h * fl), ("R_Thigh", h * (1.0 - fl))]
        out.append(sorted(((b, float(x)) for b, x in vw if x > 1e-4), key=lambda bx: -bx[1]))
    return out


HANG_GAP = 0.04      # m (2026-11-07, owner: at 2 cm the skirt hugged the legs and they came through in a
#                      wide stance): a hanging skirt's distance outside the body's outline (both legs and the hips together)
HANG_KEEP = 0.35     # share of the skirt's own outward flare kept (2026-11-07, owner's side views: Skyrim's in-game
#                      skirt leaves room in front of the thigh and tilts out a little)
HANG_RAMP = 0.15     # m below the skirt's top over which the gap (and kept flare) grows from nothing
HANG_SECTORS = 48
HANG_BODY_R = 0.22   # m from the hips' axis: the body's section without the hands hanging at its sides


def _hull(points2: np.ndarray) -> np.ndarray:
    """Convex hull (counter-clockwise) of 2-D points."""
    p = np.unique(np.round(np.asarray(points2, float), 6), axis=0)
    if len(p) < 3:
        return p
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def half(pts):
        h = []
        for q in pts:
            while len(h) >= 2 and ((h[-1][0] - h[-2][0]) * (q[1] - h[-2][1])
                                   - (h[-1][1] - h[-2][1]) * (q[0] - h[-2][0])) <= 0:
                h.pop()
            h.append(q)
        return h
    lower, upper = half(p), half(p[::-1])
    return np.array(lower[:-1] + upper[:-1])


def _hull_radius(hull: np.ndarray, angles: np.ndarray) -> np.ndarray:
    """Distance from the origin to the hull boundary along each angle (atan2(x, y) convention); nan if none."""
    out = np.full(len(angles), np.nan)
    if len(hull) < 3:
        return out
    a, b = hull, np.roll(hull, -1, axis=0)
    for k, t in enumerate(angles):
        d = np.array([np.sin(t), np.cos(t)])
        e = b - a
        den = d[0] * e[:, 1] - d[1] * e[:, 0]
        ok = np.abs(den) > 1e-12
        s_ = np.where(ok, (a[:, 0] * e[:, 1] - a[:, 1] * e[:, 0]) / np.where(ok, den, 1), np.nan)
        u = np.where(ok, (a[:, 0] * d[1] - a[:, 1] * d[0]) / np.where(ok, den, 1), np.nan)
        hit = ok & (s_ > 0) & (u >= -1e-9) & (u <= 1 + 1e-9)
        if hit.any():
            out[k] = float(np.nanmax(np.where(hit, s_, np.nan)))
    return out


def _ring_radius(r: np.ndarray, sec: np.ndarray, z: np.ndarray, top: float) -> np.ndarray:
    """Per sector, the median radius of the points within 3 cm of the top (gaps filled round)."""
    out = np.full(HANG_SECTORS, np.nan)
    for k in range(HANG_SECTORS):
        m = (sec == k) & (z > top - 0.03)
        if m.any():
            out[k] = np.median(r[m])
    good = ~np.isnan(out)
    if not good.any():
        return out
    return np.interp(np.arange(HANG_SECTORS), np.nonzero(good)[0], out[good], period=HANG_SECTORS)


def _polar(p: np.ndarray, axis) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    d = p[:, :2] - np.asarray(axis, float)[:2]
    r = np.hypot(d[:, 0], d[:, 1])
    ang = np.arctan2(d[:, 0], d[:, 1])
    sec = np.mod(((ang + np.pi) / (2 * np.pi) * HANG_SECTORS).astype(int), HANG_SECTORS)
    return d, r, ang, sec


def hang_skirt(pts: np.ndarray, mask: np.ndarray, body_pts: np.ndarray, axis, gap: float = HANG_GAP,
               sky_pts=None, sky_axis=None, scale: float = 1.0):
    """Skirt vertices hung down round the body's outline (2026-11-07, measured on the owner's Hadvar debug meshes:
    Skyrim's skirt is modelled flared, an A 27 cm from the centre at the hem against 20 cm of hips; Skyrim's
    animations turn its skirt bones so it hangs; Starfield has none, so ours stood out and up like a tutu). Per 2 cm
    band the outline is the convex hull of the body's section (both legs and the hips together, so front and back
    plates hang flat across). Each skirt vertex below the top band goes to the outline + gap (+ its layer: how far
    it lay outside the innermost skirt vertex of its band and direction, up to 3 cm, so plates stay over the cloth)
    and hangs from the skirt's top ring at its Skyrim distance from that ring (sky_pts, times scale; else the
    current one): it swings in and down, as Skyrim's does. Returns (points, vertices moved)."""
    pts = np.asarray(pts, float).copy()
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return pts, 0
    ax = np.asarray(axis, float)[:2]
    body = np.asarray(body_pts, float)
    sk = pts[idx]
    d, r, ang, sec = _polar(sk, ax)
    top = float(sk[:, 2].max())
    r_top = _ring_radius(r, sec, sk[:, 2], top)
    if np.isnan(r_top).all():
        return pts, 0
    length = np.hypot(r - r_top[sec], top - sk[:, 2])
    if sky_pts is not None and sky_axis is not None:
        sp = np.asarray(sky_pts, float)[idx]
        _d2, r2, _a2, sec2 = _polar(sp, sky_axis)
        top2 = float(sp[:, 2].max())
        rt2 = _ring_radius(r2, sec2, sp[:, 2], top2)
        if not np.isnan(rt2).all():
            length = np.hypot(r2 - rt2[sec2], top2 - sp[:, 2]) * scale
    zs = np.round(sk[:, 2] / 0.02) * 0.02
    outline = np.full(len(sk), np.nan)
    for z in np.unique(zs):
        band = body[(np.abs(body[:, 2] - z) < 0.012) & (np.hypot(body[:, 0] - ax[0], body[:, 1] - ax[1]) < HANG_BODY_R)]
        if len(band) >= 10:
            sel = np.nonzero(zs == z)[0]
            outline[sel] = _hull_radius(_hull(band[:, :2] - ax), ang[sel])
    excess = r - outline
    layer = np.zeros(len(sk))
    for z in np.unique(zs):
        for k in np.unique(sec[zs == z]):
            m = (zs == z) & (sec == k) & np.isfinite(excess)
            if m.any():
                layer[m] = np.clip(excess[m] - excess[m].min(), 0.0, 0.03)
    moved = 0
    for j in range(len(sk)):
        if not np.isfinite(outline[j]) or sk[j, 2] > top - 0.03:
            continue
        down = float(np.clip((top - sk[j, 2]) / HANG_RAMP, 0.0, 1.0))
        flare = max(excess[j] - layer[j], 0.0) if np.isfinite(excess[j]) else 0.0
        new_r = outline[j] + layer[j] + down * (gap + HANG_KEEP * flare)
        rt = r_top[sec[j]]
        dz = np.sqrt(max(length[j] ** 2 - (new_r - rt) ** 2, 0.0))
        u = d[j] / max(r[j], 1e-9)
        pts[idx[j], :2] = ax + u * new_r
        pts[idx[j], 2] = top - dz
        moved += 1
    return pts, moved


def skirt_weighted(bones: List[str], weights, share: float = 0.5) -> np.ndarray:
    """Vertices with at least `share` of their Skyrim weight on skirt bones."""
    sk = np.array([bool(skirt_shares(b)) for b in bones], bool)
    out = np.zeros(len(weights), bool)
    for i, vw in enumerate(weights):
        tot = sum(w for _b, w in vw)
        out[i] = tot > 0 and sum(w for b, w in vw if 0 <= b < len(sk) and sk[b]) >= share * tot
    return out


def sf_weights(bones: List[str], weights, sf_bones, follows: Dict[str, str]) -> List[List[Tuple[str, float]]]:
    """Skyrim weights renamed to Starfield bones (SPLIT shared, unmapped via the bone they follow), top 4."""
    out = []
    for vw in weights:
        acc: Dict[str, float] = {}
        for bi, w in vw:
            if not (0 <= bi < len(bones)) or w <= 0:
                continue
            b = bones[bi]
            hits = skirt_shares(b) or sf_of(b) or sf_of(follows.get(b) or "")
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


def wrap_params(heads, sky_bp, sky_bt, sf_pts, sf_tris, joints, sf_world):
    """neck_wrap's (Skyrim surface, Starfield surface, axes, clavicle heights): the bodies plus the whole heads."""
    sky_clav = [joints[b][:3, 3] for b in ("NPC L Clavicle [LClv]", "NPC R Clavicle [RClv]") if b in joints]
    sf_clav = [sf_world[b][:3, 3] for b in ("L_Clavicle", "R_Clavicle") if b in sf_world]
    if heads is None or "NPC Neck [Neck]" not in joints or "C_Neck" not in sf_world or not sky_clav or not sf_clav:
        return None
    (sh_p, sh_t), (fh_p, fh_t) = heads

    def join(p1, t1, p2, t2):
        p1, p2 = np.asarray(p1, float).reshape(-1, 3), np.asarray(p2, float).reshape(-1, 3)
        return (np.concatenate([p1, p2]), np.concatenate([np.asarray(t1, int).reshape(-1, 3),
                                                          np.asarray(t2, int).reshape(-1, 3) + len(p1)]))
    return (join(sky_bp, sky_bt, sh_p, sh_t), join(sf_pts, sf_tris, fh_p, fh_t),
            joints["NPC Neck [Neck]"][:3, 3], sf_world["C_Neck"][:3, 3],
            float(np.mean([p[2] for p in sky_clav])), float(np.mean([p[2] for p in sf_clav])))


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
    ok = near & np.isfinite(g_sf)
    need = np.zeros(len(pts))
    need[ok] = np.maximum(0.0, g_sky[ok] - g_sf[ok])
    if not (need > 0).any():
        return pts, 0, 0.0
    raw = np.zeros_like(pts)
    raw[:, 2] = -need
    soft = smooth_moves(pts, pts + raw, tris, rounds=4) - pts
    d = np.minimum(raw, soft)
    return pts + d, int((need > 0).sum()), float(need.max())


WRAP_REACH = (0.025, 0.045)   # m: Skyrim gap to the neck fully kept inside the first, not at all past the second
WRAP_MIN = 0.004              # m: closest the wrapped collar comes to the neck


def ray_hits(origins: np.ndarray, dirs: np.ndarray, mesh_pts: np.ndarray, mesh_tris, chunk: int = 32) -> np.ndarray:
    """Per ray, the distance to its first hit on the mesh (either side), inf if none (Moller-Trumbore)."""
    o, dv = np.asarray(origins, float), np.asarray(dirs, float)
    out = np.full(len(o), np.inf)
    t = np.asarray(mesh_tris, int).reshape(-1, 3)
    if not len(o) or not len(t):
        return out
    mp = np.asarray(mesh_pts, float)
    a = mp[t[:, 0]]
    e1, e2 = mp[t[:, 1]] - a, mp[t[:, 2]] - a
    for i in range(0, len(o), chunk):
        oo, dd = o[i:i + chunk, None, :], dv[i:i + chunk, None, :]
        p = np.cross(dd, e2[None])
        det = np.einsum("ijk,jk->ij", p, e1)
        good = np.abs(det) > 1e-12
        inv = np.where(good, 1.0 / np.where(good, det, 1.0), 0.0)
        s = oo - a[None]
        u = np.einsum("ijk,ijk->ij", s, p) * inv
        q = np.cross(s, e1[None])
        v = np.einsum("ijk,ijk->ij", np.broadcast_to(dd, q.shape), q) * inv
        tt = np.einsum("ijk,jk->ij", q, e2) * inv
        hit = good & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (tt > 1e-6)   # edges count
        out[i:i + chunk] = np.where(hit, tt, np.inf).min(1)
    return out


def neck_wrap(sky_pts: np.ndarray, pts: np.ndarray, tris, sky_surface, sf_surface, sky_axis, sf_axis,
              sky_base: float, sf_base: float, scale: float = 1.0, reach=WRAP_REACH):
    """Collar wrapped round the Starfield neck as it wraps Skyrim's (2026-11-07, Ralof: the cowl stood off the back
    and sides of the neck, not rounding it). Above the clavicles, each gear vertex's horizontal distance out from the
    neck surface (a ray from the neck axis at its height, through it) is measured in Skyrim; where that gap is small
    (reach), the vertex is moved in or out horizontally to the same gap (times scale, at least WRAP_MIN) over the
    Starfield neck / head. surfaces: (points, triangles); axes: neck joint x, y. Returns (points, moved, largest move
    in m)."""
    sky_pts, pts = np.asarray(sky_pts, float), np.asarray(pts, float)
    sel = np.nonzero((sky_pts[:, 2] > sky_base) & (pts[:, 2] > sf_base))[0]
    if not len(sel):
        return pts, 0, 0.0

    def radial(p, axis, surface):
        d = p[:, :2] - np.asarray(axis, float)[:2]
        r = np.linalg.norm(d, axis=1)
        u = d / np.maximum(r, 1e-9)[:, None]
        dirs = np.column_stack([u, np.zeros(len(u))])
        orig = np.column_stack([np.broadcast_to(np.asarray(axis, float)[:2], (len(p), 2)), p[:, 2]])
        sp, st = np.asarray(surface[0], float), np.asarray(surface[1], int).reshape(-1, 3)
        tz = sp[st][:, :, 2]                             # only triangles spanning the rays' heights
        st = st[(tz.max(1) >= p[:, 2].min() - 0.01) & (tz.min(1) <= p[:, 2].max() + 0.01)]
        return r, ray_hits(orig, dirs, sp, st), dirs
    r_sky, n_sky, _d = radial(sky_pts[sel], sky_axis, sky_surface)
    r_sf, n_sf, dirs = radial(pts[sel], sf_axis, sf_surface)
    gap = (r_sky - n_sky) * scale
    ok = np.isfinite(n_sky) & np.isfinite(n_sf) & (gap < reach[1]) & (gap >= 0.0)   # inside: bury's
    w = np.clip((reach[1] - gap) / (reach[1] - reach[0]), 0.0, 1.0) * ok
    target = n_sf + np.maximum(np.where(ok, gap, 0.0), WRAP_MIN)
    step = np.where(ok, (target - r_sf) * w, 0.0)
    move = np.zeros_like(pts)
    move[sel] = dirs * step[:, None]
    if not (np.abs(step) > 1e-4).any():
        return pts, 0, 0.0
    out = smooth_moves(pts, pts + move, tris, rounds=2)
    return out, int((np.abs(step) > 1e-4).sum()), float(np.abs(step).max())


def neck_inside(sky_pts: np.ndarray, pts: np.ndarray, tris, sky_surface, sf_surface, sky_axis, sf_axis,
                sky_base: float, sf_base: float, scale: float = 1.0, depth: float = 0.003):
    """Gear that lies inside Skyrim's neck, measured horizontally from the neck axis (a ray through it, as
    neck_wrap), put as far inside Starfield's neck (2026-11-07, measured on the owner's Farengar debug meshes: the
    robe's top closes across inside Skyrim's neck at shoulder height, so its neckline is low and the neck shows;
    push-out stood those parts up round Starfield's thinner neck as a band collar; bury, which measures depth to the
    nearest surface, missed them where the nearest surface is the body's open top). Returns (points, moved mask)."""
    sky_pts, pts = np.asarray(sky_pts, float), np.asarray(pts, float)
    mask = np.zeros(len(pts), bool)
    sel = np.nonzero((sky_pts[:, 2] > sky_base) & (pts[:, 2] > sf_base))[0]
    if not len(sel):
        return pts, mask

    def radial(p, axis, surface):
        d = p[:, :2] - np.asarray(axis, float)[:2]
        r = np.linalg.norm(d, axis=1)
        u = d / np.maximum(r, 1e-9)[:, None]
        dirs = np.column_stack([u, np.zeros(len(u))])
        orig = np.column_stack([np.broadcast_to(np.asarray(axis, float)[:2], (len(p), 2)), p[:, 2]])
        sp, st = np.asarray(surface[0], float), np.asarray(surface[1], int).reshape(-1, 3)
        tz = sp[st][:, :, 2]
        st = st[(tz.max(1) >= p[:, 2].min() - 0.01) & (tz.min(1) <= p[:, 2].max() + 0.01)]
        return r, ray_hits(orig, dirs, sp, st), dirs
    r_sky, n_sky, _d = radial(sky_pts[sel], sky_axis, sky_surface)
    r_sf, n_sf, dirs = radial(pts[sel], sf_axis, sf_surface)
    gap = (r_sky - n_sky) * scale
    ok = np.isfinite(n_sky) & np.isfinite(n_sf) & (gap < -depth)
    if not ok.any():
        return pts, mask
    target = np.maximum(n_sf + gap, 0.3 * n_sf)
    step = np.where(ok, np.minimum(target - r_sf, 0.0), 0.0)        # only inwards
    out = pts.copy()
    out[sel] += dirs * step[:, None]
    mask[sel[ok]] = True
    soft = smooth_moves(pts, out, tris, rounds=2)
    soft[mask] = out[mask]
    return soft, mask


BURY = 0.003     # m: gear deeper than this inside Skyrim's neck / head stays inside Starfield's


def bury(pts: np.ndarray, sky_gap: np.ndarray, mask: np.ndarray, tris, sf_pts: np.ndarray, sf_tris, sf_nrm: np.ndarray,
         gap: float = GAP, scale: float = 1.0):
    """Gear hidden inside the Skyrim neck / head kept inside Starfield's at the same depth (2026-11-07, verified on
    the owner's fit debug meshes: the Stormcloak cowl's top rim lies 2-3 cm from the neck's axis, up to 48 mm inside
    Skyrim's neck, so only its lower part shows: a half turtleneck; push-out had lifted the whole rim out round the
    neck, a full one). mask: the vertices to bury; sky_gap: their signed gaps in Skyrim (negative inside). Moved only
    inwards; neighbours follow (smoothed), the rest is pushed back out. Returns (points, buried count)."""
    b = np.nonzero(mask)[0]
    t = np.asarray(sf_tris, int).reshape(-1, 3)
    _cp, depth, _dist, nrm = closest_on_mesh(pts[b], sf_pts, t, sf_nrm, with_normals=True)
    step = np.minimum(0.0, sky_gap[b] * scale - depth)
    out = pts.copy()
    out[b] = pts[b] + nrm * step[:, None]
    soft = smooth_moves(pts, out, tris, rounds=2)
    soft[b] = out[b]
    rest = np.nonzero(~mask)[0]
    if len(rest):
        soft[rest], _n = push_out(soft[rest], sf_pts, sf_nrm, gap, tris=t)
    return soft, int((step < -1e-4).sum())


DRAPE_REACH = (0.06, 0.10)   # m above the shoulders: fully draped inside the first, not past the second
DRAPE_MAX = 0.10             # m: a longer move means the surfaces below do not correspond
DRAPE_UP = 0.3               # a surface counts as shoulder top when its normal's z is above this


def surface_below(pts: np.ndarray, mesh_pts: np.ndarray, mesh_tris, chunk: int = 128):
    """Per point, the first mesh surface straight below it: (height, the triangle normal's |z|); nan, 0 if none."""
    pts = np.asarray(pts, float)
    h, nz = np.full(len(pts), np.nan), np.zeros(len(pts))
    t = np.asarray(mesh_tris, int).reshape(-1, 3)
    if not len(pts) or not len(t):
        return h, nz
    a, b, c = (np.asarray(mesh_pts, float)[t[:, k]] for k in range(3))
    n = np.cross(b - a, c - a)
    tz = np.abs(n[:, 2]) / np.maximum(np.linalg.norm(n, axis=1), 1e-12)
    v0, v1 = (b - a)[:, :2], (c - a)[:, :2]
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    ok = np.abs(den) > 1e-12
    a, b, c, v0, v1, den, tz = a[ok], b[ok], c[ok], v0[ok], v1[ok], den[ok], tz[ok]
    for i in range(0, len(pts), chunk):
        p = pts[i:i + chunk]
        q = p[:, None, :2] - a[None, :, :2]
        u = (q[..., 0] * v1[:, 1] - v1[:, 0] * q[..., 1]) / den
        v = (v0[:, 0] * q[..., 1] - q[..., 0] * v0[:, 1]) / den
        z = a[None, :, 2] + u * (b[None, :, 2] - a[None, :, 2]) + v * (c[None, :, 2] - a[None, :, 2])
        hit = (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (z <= p[:, None, 2])
        zz = np.where(hit, z, -np.inf)
        j = zz.argmax(1)
        got = np.isfinite(zz[np.arange(len(p)), j])
        h[i:i + chunk] = np.where(got, zz[np.arange(len(p)), j], np.nan)
        nz[i:i + chunk] = np.where(got, tz[j], 0.0)
    return h, nz


def drape(sky_pts: np.ndarray, pts: np.ndarray, tris, sky_surface, sf_surface, sky_axis, sf_axis, sky_base: float,
          scale: float = 1.0, reach=DRAPE_REACH):
    """Gear lying on the shoulders round the neck placed on Starfield's shoulders as on Skyrim's (2026-11-07,
    measured on the owner's fit debug meshes: relative to the crown, Starfield's shoulders start 1.5-3 cm lower and
    narrower than Skyrim's; the cowl kept its height and was pulled in round the neck, a turtleneck, where Skyrim's
    lies out on the trapezius 4-6 cm further from the neck). For each gear vertex above the Skyrim clavicles with an
    upward-facing Skyrim body surface straight below it within reach: its direction and distance (times scale) from
    the neck axis and its height above that surface are kept over Starfield's (same direction and distance from its
    neck axis, height above its surface there). Blended out with height; smoothed. Returns (points, moved, largest
    move in m)."""
    sky_pts, pts = np.asarray(sky_pts, float), np.asarray(pts, float)
    sel = np.nonzero(sky_pts[:, 2] > sky_base)[0]
    if not len(sel):
        return pts, 0, 0.0
    sp = sky_pts[sel]
    h_sky, nz_sky = surface_below(sp, *sky_surface)
    above = (sp[:, 2] - h_sky) * scale
    d = (sp[:, :2] - np.asarray(sky_axis, float)[:2]) * scale
    xy = np.asarray(sf_axis, float)[:2] + d
    probe = np.column_stack([xy, np.maximum(pts[sel, 2], sp[:, 2]) + 0.05])
    h_sf, nz_sf = surface_below(probe, *sf_surface)
    ok = np.isfinite(h_sky) & np.isfinite(h_sf) & (nz_sky > DRAPE_UP) & (nz_sf > DRAPE_UP) & (above > -0.01)
    w = np.clip((reach[1] - above) / (reach[1] - reach[0]), 0.0, 1.0) * ok
    w *= np.clip((sp[:, 2] - sky_base) / 0.03, 0.0, 1.0)
    target = np.column_stack([xy, h_sf + np.where(ok, above, 0.0)])
    far = ~ok | (np.linalg.norm(np.where(ok[:, None], target, pts[sel]) - pts[sel], axis=1) > DRAPE_MAX)
    w = np.where(far, 0.0, w)            # another surface below (an arm), not the shoulder: left alone
    move = np.zeros_like(pts)
    move[sel] = (np.where(ok[:, None], target, pts[sel]) - pts[sel]) * w[:, None]
    if not (np.linalg.norm(move, axis=1) > 1e-4).any():
        return pts, 0, 0.0
    out = smooth_moves(pts, pts + move, tris, rounds=2)
    return out, int((np.linalg.norm(move, axis=1) > 1e-4).sum()), float(np.linalg.norm(move, axis=1).max())


RELAX_ROUNDS = 8      # rounds of smoothing of the fit's total moves (neighbour averaging over the mesh)
SHOULDER_RADII = (0.09, 0.11, 0.13)     # m from the neck axis where the shoulder heights are compared
SHOULDER_ANGLES = 24
SHOULDER_DROP_LIMITS = (-0.08, 0.03)    # m
SHOULDER_REACH = (0.16, 0.22)           # m from the neck axis: full drop inside the first, none past the second
SHOULDER_FADE = (-0.02, 0.02)           # m relative to the clavicles: no drop below the first, full above the second


def shoulder_drop_field(sky_pts: np.ndarray, sky_tris, sf_pts: np.ndarray, sf_tris, axis, top: float):
    """Per direction round the neck (SHOULDER_ANGLES, from +y towards +x), how much lower (negative) Starfield's
    shoulder top lies than the fitted Skyrim body's, compared straight below points SHOULDER_RADII from the neck
    axis (upward-facing surfaces only; median over the radii; missing directions filled from their neighbours;
    clamped; smoothed round). axis: the neck joint (x, y); top: a height above both shoulders. None if unmeasured."""
    a = np.arange(SHOULDER_ANGLES) * 2 * np.pi / SHOULDER_ANGLES
    d = np.zeros(SHOULDER_ANGLES)
    got = np.zeros(SHOULDER_ANGLES, bool)
    for k, t in enumerate(a):
        u = np.array([np.sin(t), np.cos(t)])
        probe = np.array([[axis[0] + r * u[0], axis[1] + r * u[1], top] for r in SHOULDER_RADII])
        h1, n1 = surface_below(probe, sky_pts, sky_tris)
        h2, n2 = surface_below(probe, sf_pts, sf_tris)
        ok = np.isfinite(h1) & np.isfinite(h2) & (n1 > DRAPE_UP) & (n2 > DRAPE_UP)
        if ok.any():
            d[k], got[k] = float(np.median(h2[ok] - h1[ok])), True
    if not got.any():
        return None
    idx = np.nonzero(got)[0]
    ext = np.concatenate([idx - SHOULDER_ANGLES, idx, idx + SHOULDER_ANGLES])
    d = np.interp(np.arange(SHOULDER_ANGLES), ext, np.tile(d[idx], 3))
    d = np.clip(d, *SHOULDER_DROP_LIMITS)
    return (np.roll(d, 1) + 2 * d + np.roll(d, -1)) / 4


def shoulder_drop(pts: np.ndarray, field, axis, clav_z: float) -> np.ndarray:
    """pts moved down (or up) by the field's value for their direction round the neck axis, near the neck (REACH)
    and above the clavicles (FADE) (2026-11-07, owner: the cowl sat up on the chest as a separate piece where
    Skyrim's lies low round the base of the neck and the neck shows; measured: Starfield's shoulders 3-5 cm lower
    than Skyrim's under the head)."""
    if field is None or not len(pts):
        return pts
    p = np.asarray(pts, float)
    dx, dy = p[:, 0] - axis[0], p[:, 1] - axis[1]
    t = np.mod(np.arctan2(dx, dy), 2 * np.pi) / (2 * np.pi) * SHOULDER_ANGLES
    i0 = np.floor(t).astype(int) % SHOULDER_ANGLES
    f = t - np.floor(t)
    dz = field[i0] * (1 - f) + field[(i0 + 1) % SHOULDER_ANGLES] * f
    r = np.hypot(dx, dy)
    w = np.clip((SHOULDER_REACH[1] - r) / (SHOULDER_REACH[1] - SHOULDER_REACH[0]), 0, 1)
    w *= np.clip((p[:, 2] - clav_z - SHOULDER_FADE[0]) / (SHOULDER_FADE[1] - SHOULDER_FADE[0]), 0, 1)
    out = p.copy()
    out[:, 2] += dz * w
    return out


OWN_WEIGHT_BLEND = 0.03   # m above the clavicles over which gear goes from the body's weights to its own
COLLAR_SECTORS = 8
NECKLINE_R = 0.085       # m from the neck axis: lowered collar this close may stay inside the body (the shoulders
#                          beyond are pushed back out, or skin showed through them)
COLLAR_RADIUS = 0.13     # m from the neck axis: gear counted as the collar
COLLAR_DEPTH = (-0.10, 0.0)   # m: clamp of the collar's height correction (never raised)


def with_normals(points, tris):
    """(points, triangles, outward vertex normals) of a mesh."""
    p, t = np.asarray(points, float), np.asarray(tris, int).reshape(-1, 3)
    n = _vertex_face_normals(p, t)
    return p, t, outward(p, n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12))


def inside_mesh(pts: np.ndarray, mesh) -> np.ndarray:
    """Which points lie inside a closed-ish mesh (points, triangles, outward normals) (all False for None)."""
    pts = np.asarray(pts, float)
    if mesh is None or not len(pts):
        return np.zeros(len(pts), bool)
    _cp, depth, dist = closest_on_mesh(pts, *mesh)
    return (depth < 0) & (dist < 0.15)


def collar_height_field(sky_pts, sky_vis, sky_axis, sky_crown, pts, vis, sf_axis, sf_crown, scale: float = 1.0):
    """Per direction round the neck (SHOULDER_ANGLES), how far the collar's visible top edge must come down to sit
    as far below the crown as Skyrim's does (2026-11-07, measured on the owner's debug meshes, heads lined up at the
    crown: our visible collar top 5.8 cm too high at the front, 2-2.6 cm at the sides and back; Skyrim's lies at the
    base of the neck and the neck shows). The top edge: the 2nd percentile of 'below the crown' of the visible gear
    within COLLAR_RADIUS of each neck axis, per sector; sectors without gear filled from their neighbours.
    *_vis: visible (outside the body) masks. None if nothing to compare."""
    def tops(p, v, axis, crown, sc):
        p = np.asarray(p, float)
        d = p[:, :2] - np.asarray(axis, float)[:2]
        near = v & (np.hypot(d[:, 0], d[:, 1]) * sc < COLLAR_RADIUS)
        sec = (np.mod(np.arctan2(d[:, 0], d[:, 1]), 2 * np.pi) / (2 * np.pi) * COLLAR_SECTORS).astype(int)
        below = (crown - p[:, 2]) * sc
        out = np.full(COLLAR_SECTORS, np.nan)
        for k in range(COLLAR_SECTORS):
            m = near & (sec == k)
            if m.sum() >= 3:
                out[k] = np.percentile(below[m], 2)
        return out
    a = tops(sky_pts, np.asarray(sky_vis, bool), sky_axis, sky_crown, scale)
    b = tops(pts, np.asarray(vis, bool), sf_axis, sf_crown, 1.0)
    d = b - a                      # ours closer to the crown -> negative: come down
    ok = np.isfinite(d)
    if not ok.any():
        return None
    idx = np.nonzero(ok)[0]
    ext = np.concatenate([idx - COLLAR_SECTORS, idx, idx + COLLAR_SECTORS])
    centres = (np.arange(SHOULDER_ANGLES) + 0.5) / SHOULDER_ANGLES * COLLAR_SECTORS - 0.5
    f = np.interp(centres, ext, np.tile(d[idx], 3))
    f = np.clip(f, *COLLAR_DEPTH)
    return (np.roll(f, 1) + 2 * f + np.roll(f, -1)) / 4


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
        weight_src=None, heads=None, shoulders: bool = False, drape_on: bool = False,
        wrap_on: bool = True) -> FitResult:
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
    drop_field, drop_axis = None, None
    sf_clav = [sf_world[b][2, 3] for b in ("L_Clavicle", "R_Clavicle") if b in sf_world]
    sf_clav_z = float(np.mean(sf_clav)) if sf_clav else None
    if shoulders and len(bp) and len(sky_bt) and sf_clav and "C_Neck" in sf_world:
        drop_axis = sf_world["C_Neck"][:2, 3]
        drop_field = shoulder_drop_field(bp, sky_bt, sf_body_pts, np.asarray(sf_body_tris, int).reshape(-1, 3),
                                         drop_axis, float(max(bp[:, 2].max(), sf_body_pts[:, 2].max()) + 0.1))
        if drop_field is not None:
            rep["shoulder_drop_mm"] = (drop_field * 1000).round(0).tolist()
            bp = shoulder_drop(bp, drop_field, drop_axis, sf_clav_z)
    off, rep["body"] = body_offsets(bp, sf_body_pts, sf_nrm, sky_nrm=bn) if len(bp) else (np.zeros((0, 3)), {})
    shapes, rep["shapes"] = [], {}
    neck = neck_squash_params(joints, transforms, sf_world)
    wrap = wrap_params(heads, sky_bp, sky_bt, sf_body_pts, sf_body_tris, joints, sf_world)
    head_sky = head_sf = None
    if heads is not None:
        head_sky, head_sf = (with_normals(*h) for h in heads)
    sky_clav = [joints[b][:3, 3][2] for b in ("NPC L Clavicle [LClv]", "NPC R Clavicle [RClv]") if b in joints]
    sky_clav_z = float(np.mean(sky_clav)) if sky_clav else None
    if neck is not None:
        rep["neck_squash"] = {"ratio": round(neck[0], 3), "clavicle_height_m": round(neck[1], 3)}
    for s in gear:
        pts, nrm = blend(s.points, s.normals, s.bones, s.weights, transforms)
        pts = neck_squash(pts, neck)
        pts = shoulder_drop(pts, drop_field, drop_axis, sf_clav_z) if drop_field is not None else pts
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
            # not round the neck (2026-11-07, measured: pulling the cowl to its Skyrim gap from the nearest surface
            # drew it 2-3 cm in onto Starfield's neck, a tube up the neck where Skyrim's slopes out over the shoulders)
            kg = sky_gap if sky_clav_z is None else np.where(np.asarray(s.points)[:, 2] > sky_clav_z, np.inf, sky_gap)
            pts, pulled = keep_gap(pts, kg, sf_body_pts, sf_body_tris, sf_nrm, gap)
        pushed = 0
        if len(sf_body_pts):
            # skin pieces too, closer: Skyrim paints clothes on body-textured parts (Stormcloak trousers)
            pts, pushed = push_out(pts, sf_body_pts, sf_nrm, SKIN_GAP if skin else gap,
                                   tris=np.asarray(sf_body_tris, int).reshape(-1, 3))
        covered = 0
        if not skin and len(sf_body_pts):
            before_cover = pts
            pts, covered = cover(pts, nrm, s.triangles, sf_body_pts, sf_nrm, gap)
            hang = skirt_weighted(s.bones, s.weights)
            if hang.any():
                # skirt plates hang: cover's outward pull flared them (2026-11-07, owner: Hadvar's tassets stood out
                # like a tutu where Skyrim's hang straight down); push-out still keeps them off the thighs
                pts = np.where(hang[:, None], before_cover, pts)
            # smooth the moves (no folded faces), then make sure nothing came back inside the body
            pts = smooth_moves(moved_base, pts, s.triangles)
            pts, _again = push_out(pts, sf_body_pts, sf_nrm, gap, tris=np.asarray(sf_body_tris, int).reshape(-1, 3))
        # chin_clearance is not used (2026-11-07: it dropped the cowl's back 7.6 cm under the skull while its front
        # stayed; the real difference was the buried top, see bury)
        lowered, drop = 0, 0.0
        hung = 0
        if not skin and len(sf_body_pts) and "C_Hips" in sf_world:
            hang_mask = skirt_weighted(s.bones, s.weights)
            if hang_mask.any():
                pel = joints.get("NPC Pelvis [Pelv]")
                hung_pts, hung = hang_skirt(pts, hang_mask, sf_body_pts, sf_world["C_Hips"][:3, 3],
                                            sky_pts=s.points, sky_axis=None if pel is None else pel[:3, 3],
                                            scale=rep.get("global_scale", 1.0))
                pts = smooth_moves(pts, hung_pts, s.triangles, rounds=2)
                pts[hang_mask] = hung_pts[hang_mask]
        if not skin and RELAX_ROUNDS and len(sf_body_pts):
            # the moves of all the steps above, smoothed hard over the mesh, then out of the body once more
            # (2026-11-07, owner: the cloth lines of the texture, smooth curves in Skyrim, wiggled in Starfield: each
            # step moved single vertices)
            pts = smooth_moves(moved_base, pts, s.triangles, rounds=RELAX_ROUNDS)
            bt_ = np.asarray(sf_body_tris, int).reshape(-1, 3)
            for _ in range(2):           # push-outs spread to the neighbours too, so no single vertex jumps
                before = pts
                pushed_, _n = push_out(pts, sf_body_pts, sf_nrm, gap, tris=bt_)
                pts = smooth_moves(before, pushed_, s.triangles, 2)
                pts = np.where((np.linalg.norm(pushed_ - before, axis=1) > 0)[:, None], pushed_, pts)
            pts, _again = push_out(pts, sf_body_pts, sf_nrm, gap, tris=bt_)
        collar_mm = None
        collar_keep = np.zeros(len(pts), bool)
        if heads is not None and not skin and sky_gap is not None and sky_clav_z is not None and sf_clav_z is not None \
                and wrap is not None and len(sf_body_pts):
            bt_ = np.asarray(sf_body_tris, int).reshape(-1, 3)
            _cp, dep_now, _dd = closest_on_mesh(pts, sf_body_pts, bt_, sf_nrm)
            sky_vis = np.isfinite(sky_gap) & (sky_gap > 0) & ~inside_mesh(s.points, head_sky)
            vis_now = (dep_now > 0) & ~inside_mesh(pts, head_sf)
            cfield = collar_height_field(s.points, sky_vis, wrap[2],
                                         float(np.asarray(heads[0][0])[:, 2].max()), pts, vis_now, wrap[3],
                                         float(np.asarray(heads[1][0])[:, 2].max()), rep.get("global_scale", 1.0))
            if cfield is not None:
                collar_mm = (cfield * 1000).round(0).tolist()
                lowered_pts = shoulder_drop(pts, cfield, wrap[3][:2], sf_clav_z)
                lowered_pts = smooth_moves(pts, lowered_pts, s.triangles, rounds=2)
                # what came down stays down, even where that is inside the body: the neckline is where the cloth
                # goes into the skin, as Skyrim's (2026-11-07, measured on the owner's Farengar meshes: the field asked
                # for 2-3.4 cm down all round, push-out put it straight back up the neck)
                came_down = ((pts[:, 2] - lowered_pts[:, 2]) > 1e-4) & (
                    np.hypot(lowered_pts[:, 0] - wrap[3][0], lowered_pts[:, 1] - wrap[3][1]) < NECKLINE_R)
                pts = lowered_pts
                rest = np.nonzero(~came_down)[0]
                if len(rest):
                    pts[rest], _again = push_out(pts[rest], sf_body_pts, sf_nrm, gap, tris=bt_)
                collar_keep = came_down
        draped, drape_max = 0, 0.0
        if drape_on and wrap is not None and not skin and sky_clav_z is not None and len(sky_bt):
            pts, draped, drape_max = drape(s.points, pts, s.triangles, (sky_bp, sky_bt),
                                           (sf_body_pts, np.asarray(sf_body_tris, int).reshape(-1, 3)), wrap[2],
                                           wrap[3], sky_clav_z, rep.get("global_scale", 1.0))
            if draped and len(sf_body_pts):
                pts, _again = push_out(pts, sf_body_pts, sf_nrm, gap,
                                       tris=np.asarray(sf_body_tris, int).reshape(-1, 3))
        wrapped, wrap_max = 0, 0.0
        if wrap_on and wrap is not None and not skin:
            pts, wrapped, wrap_max = neck_wrap(s.points, pts, s.triangles, *wrap, rep.get("global_scale", 1.0))
            if wrapped and len(sf_body_pts):
                rest = np.nonzero(~collar_keep)[0]
                pts[rest], _again = push_out(pts[rest], sf_body_pts, sf_nrm, gap,
                                             tris=np.asarray(sf_body_tris, int).reshape(-1, 3))
        buried = 0
        if not skin and sky_gap is not None and sky_clav_z is not None and len(sf_body_pts):
            mask = np.isfinite(sky_gap) & (sky_gap < -BURY) & (np.asarray(s.points)[:, 2] > sky_clav_z)
            if mask.any() and heads is not None and wrap is not None:
                # the hidden part first back where Skyrim has it relative to the head (crown and neck axis lined
                # up, scaled): 2026-11-07, owner looking at the cuts: ours ran up into the head where Skyrim's runs
                # straight across inside the neck
                sc = rep.get("global_scale", 1.0)
                sky_c = float(np.asarray(heads[0][0])[:, 2].max())
                sf_c = float(np.asarray(heads[1][0])[:, 2].max())
                sp_ = np.asarray(s.points, float)[mask]
                head_mapped = np.column_stack([np.asarray(wrap[3][:2]) + (sp_[:, :2] - np.asarray(wrap[2][:2])) * sc,
                                               sf_c + (sp_[:, 2] - sky_c) * sc])
                moved_ = pts.copy()
                moved_[mask] = head_mapped
                pts = smooth_moves(pts, moved_, s.triangles, rounds=2)
                pts[mask] = head_mapped
            if mask.any():
                keep_ = pts.copy()
                pts, buried = bury(pts, sky_gap, mask, s.triangles, sf_body_pts, sf_body_tris, sf_nrm, gap,
                                   rep.get("global_scale", 1.0))
                lowered_only = collar_keep & ~mask
                pts[lowered_only] = keep_[lowered_only]          # bury's push-out must not lift the neckline
        inside_n = 0
        if wrap_on and wrap is not None and not skin:
            pts, ins = neck_inside(s.points, pts, s.triangles, *wrap, rep.get("global_scale", 1.0))
            inside_n = int(ins.sum())
        pts, welded = weld(s.points, pts)
        bad = ~np.isfinite(pts).all(1)
        if len(sf_body_pts):
            lo, hi = sf_body_pts.min(0) - FAR, sf_body_pts.max(0) + FAR
            far = int((((pts < lo) | (pts > hi)).any(1) & ~bad).sum())
        else:
            far = 0
        w = sf_weights(s.bones, s.weights, set(sf_world), follows)
        own = list(w)
        near = 0
        if weight_src is not None and len(pts):
            w, near = body_weights_near(pts, w, w_pts, w_nrm, w_w, set(sf_world))
        elif sf_body_weights is not None and len(sf_body_weights) == len(sf_body_pts) and len(pts):
            w, near = body_weights_near(pts, w, sf_body_pts, sf_nrm, sf_body_weights, set(sf_world))
        if not skin:
            # skirt plates hang free of the legs: their own (hips + thighs) weights, not the thigh skin's
            skirt_v = np.nonzero(skirt_weighted(s.bones, s.weights))[0]
            grad = skirt_gradient(np.asarray(s.points)[skirt_v], joints) if len(skirt_v) else None
            for k, i in enumerate(skirt_v):
                w[i] = [(b, x) for b, x in grad[k] if b in sf_world] if grad is not None else own[i]
        if not skin and sky_clav_z is not None:
            # above the clavicles the gear keeps its own (Skyrim's) weights: 2026-11-07, owner: Skyrim's cowl sits on
            # the outfit and does not move with the neck or head; with the neck skin's weights its side rose when the
            # head turned
            zz = np.asarray(s.points)[:, 2] - sky_clav_z
            for i in np.nonzero(zz > 0)[0]:
                t = min(1.0, zz[i] / OWN_WEIGHT_BLEND)          # blended in over the first few cm
                mix: Dict[str, float] = {}
                for b, x in w[i]:
                    mix[b] = mix.get(b, 0.0) + (1 - t) * x
                for b, x in own[i]:
                    mix[b] = mix.get(b, 0.0) + t * x
                w[i] = sorted(((b, x) for b, x in mix.items() if x > 0), key=lambda bx: -bx[1])
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
            "neck_wrapped": wrapped, "neck_wrap_mm": round(wrap_max * 1000, 1),
            "buried": buried, "inside_neck": inside_n,
            "skirt_hung": hung,
            "skirt_vertices": int(len(skirt_v)) if not skin else 0,
            "collar_drop_mm": collar_mm,
            "draped": draped, "drape_mm": round(drape_max * 1000, 1),
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
