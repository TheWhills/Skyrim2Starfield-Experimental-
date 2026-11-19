"""A Skyrim child's own face shape on Starfield's child head, feature by feature (2026-11-19, owner's option 2).

Why: the first child fit carried over "FaceGen head minus its base head". RS Children Overhaul's base child head has
adult proportions (Skyrim's adult female head layout) and a Realistic RS face is a real child's, so that difference
is mostly "make an adult face a child's"; added onto Starfield's child head, which already is one, and with the two
heads 8.5 mm rms apart, it landed beside the features (owner in game: Frodnar read African, broad nose and cheeks;
only Starfield's own head looked decent). Measured on the owner's shapes (faces_preview .npz): Frodnar's Skyrim face
is narrower (jaw 17 mm each side), its eyes 5 mm closer each and its chin 12 mm further back than Starfield's head.

What this does instead, in Starfield model space (metres):
1. landmarks on both heads: the eyes (Starfield: its eye openings, open-edge loops; Skyrim: the FaceGen NIF's eyes
   shape), the mouth (Starfield: its lip loop; Skyrim: its mouth opening), nose tip, nasion, chin and forehead on the
   midline;
2. the FaceGen head moved and scaled (no turn) onto Starfield's landmarks, the eyes weighted most (prealign): the
   eyeballs are head parts placed for Starfield's sockets, so the face is fitted around them;
3. a non-rigid fit of Starfield's head onto that face (fit): each round every face vertex is pulled to the nearest
   point of the Skyrim face whose surface faces the same way, the pulls are smoothed over the mesh (coarse to fine,
   so only the shape carries over, not the low-poly Skyrim facets), and applied; the face region fades out before
   the ears, the crown and the neck (hair and seams stay), the eye sockets stay put (the eyeballs) and the lips do not
   pull (Starfield's closed lips vs Skyrim's open mouth; they move with the face around them).
Result: Starfield's mesh and detail with the child's own proportions. Tried and drawn on Frodnar's shapes before use
(work notes: docs/npc/children-mods.md).
"""
import re
from typing import Dict, Optional, Tuple

import numpy as np

from . import headcorr

LM_WEIGHTS = {"eyeL": 4.0, "eyeR": 4.0, "nasion": 1.0, "nose": 1.0, "mouth": 1.0, "chin": 1.0, "forehead": 1.0}
# (smoothing passes, step): coarse to fine. 2026-11-19 (owner on the first version: not smooth, nose too wide, chin
# too bold): finer rounds onto a smoothed, denser Skyrim surface (refined_target), then the moves smoothed (FINISH)
ROUNDS = ((400, 0.7), (250, 0.7), (150, 0.7), (100, 0.7), (100, 0.7))
# then rounds along each vertex's normal only (sliding sideways over the target made lumps, 2026-11-19 try)
NORMAL_ROUNDS = ((60, 0.7), (40, 0.7), (25, 0.7))
NOSE_REACH = 0.032     # m around the nose tip: the only part the normal rounds work on (2026-11-19: everywhere else
#                        they copied Realistic RS's sculpted creases - frown line, eye bags - as bumps)
NORMAL_SMOOTH = 60     # passes: the head the normal rounds take their directions from
FINISH = 30            # Taubin passes over the moves at the end (no shrink): no low-poly facets left
EAR_ROUNDS = 400       # the ears take part in rounds this coarse or coarser: size and place, not their folds
REACH = 0.035          # m: farthest pull
FACING = 0.6           # pull only to a Skyrim surface facing within ~53 degrees of the vertex's own normal
EYE_LOCK = 0.010       # m around each eye opening's centre (and its socket behind) that does not move, fading
EYE_FADE = 0.025       # over EYE_FADE: the eyeballs stay covered, the lids take the child's shape (owner: "the eyes
#                        are unchanged" with 14 + 12 mm)
MOUTH_FREE = 0.010     # m around the mouth centre that does not pull (moves with the face); 16 left the skin above
#                        the upper lip standing out
UNDER_EYE = 0.045      # m from an eye opening's centre, below it and to its side: the moves smoothed there (2026-11-19,
UNDER_EYE_PASSES = 40  # owner: "kind've creepy, like in the eyes" - the Realistic RS face's under-eye creases came
                       # through as bags on Starfield's smooth head)
FACE_SMOOTH = 200      # passes over the moves on the whole head at the end (2026-11-19, owner: "maybe he needs some
                       # smoothing overall?" - the Realistic RS sculpt's creases on forehead, cheeks and around the
                       # mouth read as aged on Starfield's lighting; 80 passes change the moves 0.65 mm rms, the
                       # nose, chin and cheeks keep their shape)
# 2026-11-19 (owner: "whats causing the bottom to not be smooth like the top"): measured on Frodnar, the extra
# bumps sat on a ring around each eye - the locked sockets (0 move) against the face's 1.4 mm moves 22 mm out, over a
# 12 mm fade - and in folds from the Skyrim sculpt (nasolabial, under the lips). EYE_FADE 25 mm and 200 passes:
# both gone on the preview, nose widths unchanged.
ALMOND = 0.12          # of the eye opening's height: the upper lid lowered at its middle (none at the corners;
                       # 2026-11-19, owner: "his eyes could stand to be slightly more almondy" - Starfield's child eye
                       # openings are round, 29.5 x 12.3 mm on Frodnar)
LID_FALLOFF = 0.008    # m above the upper lid's edge over which the lid skin follows it
EYEBALL_R = 0.012      # m: the lid edge is moved forward by the sagitta of an eyeball this round, so it stays on it
VERSION = 14


def apply4(m, p):
    p = np.asarray(p, float)
    return p @ np.asarray(m, float)[:3, :3].T + np.asarray(m, float)[:3, 3]


def welded(v, t) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(welded vertices, welded triangles without degenerate ones, inv: vertex -> welded)."""
    inv, _cnt = headcorr.weld_index(v, 1e-6)
    wv = np.zeros((inv.max() + 1, 3))
    np.add.at(wv, inv, v)
    wv /= np.bincount(inv)[:, None]
    wt = inv[np.asarray(t, int)]
    wt = wt[(wt[:, 0] != wt[:, 1]) & (wt[:, 1] != wt[:, 2]) & (wt[:, 0] != wt[:, 2])]
    return wv, wt, inv


def loops(v, t):
    """[(size, centre)] of the open-edge loops of a mesh (unwelded: Starfield's eye and lip openings)."""
    return [(len(lp), np.asarray(v, float)[lp].mean(0)) for lp in headcorr.boundary_loops(np.asarray(t, int))]


def starfield_eyes_mouth(v, t) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """((2, 3) eye opening centres left / right, mouth centre) of Starfield's head in model space (+Y forward, +Z
    up): the eyes are the highest pair of front loops of about the same size on either side of the midline; the
    mouth the largest loop on the midline below them (the frontmost of equal ones). (None, None) when not found."""
    v = np.asarray(v, float)
    front = [(n, c) for n, c in loops(v, t) if n >= 12 and c[1] > np.median(v[:, 1])]
    best = None
    for n1, c1 in front:
        for n2, c2 in front:
            if c1[0] < -0.01 and c2[0] > 0.01 and abs(n1 - n2) <= 0.2 * max(n1, n2) \
                    and abs(c1[2] - c2[2]) < 0.01 and abs(c1[0] + c2[0]) < 0.01:
                if best is None or c1[2] + c2[2] > best[0]:
                    best = (c1[2] + c2[2], np.array([c1, c2]))
    if best is None:
        return None, None
    eyes = best[1]
    # the largest such loop (2026-11-19, Dorthe: Starfield's girl head has a 20-vertex loop by the nose, 6 mm off the
    # midline and in front of the 84-vertex mouth; taken as the mouth it put hers 37 mm high and dragged her face)
    mid = [(n, c) for n, c in front if abs(c[0]) < 0.008 and c[2] < eyes[:, 2].mean() - 0.03]
    mouth = max(mid, key=lambda nc: (nc[0], nc[1][1]))[1] if mid else None
    return eyes, mouth


def skyrim_mouth(v, t) -> Optional[np.ndarray]:
    """The mouth opening's centre of a Skyrim head (welded: its open loops other than the neck)."""
    wv, wt, _inv = welded(v, t)
    cand = [(len(lp), wv[lp].mean(0)) for lp in headcorr.boundary_loops(wt)]
    cand = [c for n, c in cand if n >= 10 and c[1] > np.median(wv[:, 1])]
    return max(cand, key=lambda c: c[1]) if cand else None


EYE_SHAPE = re.compile(r"eye", re.I)
NOT_EYES = re.compile(r"brows?(?!n)|lash", re.I)      # brows / lashes, not "Brown" (2026-11-19: Faendal's
                                                       # MaleEyesWoodElfDeepBrown was skipped as a brow)


def is_eye_shape(name: str) -> bool:
    return bool(EYE_SHAPE.search(name or "")) and not NOT_EYES.search(name or "")


def facegen_eyes(nif_bytes, head_points=None) -> Optional[np.ndarray]:
    """(2, 3) eye centres (left, right) of a Skyrim FaceGen NIF (units), in the space of head_points (its head shape's
    points as the caller uses them) when given. Two ways to place the eyes shape, the one landing nearest the head's
    middle is taken: (1) the head bone's rest place @ inverse(bind) (verified on Realistic RS Children, whose eyes are
    stored in the head bone's frame with an identity bind and whose head the caller places with the base head's
    matrix); (2) the eyes shape's own skin -> model matrix (facefit.skyrim_model_matrix; vanilla FaceGen: the head
    bone's node is at the origin, the eyes come 120 units low by (1) - 2026-11-19, Faendal). Without head_points: (1)."""
    from . import facefit, nif as nifmod, skyrimhair, skyrimskin
    n = nifmod.parse(nif_bytes)
    nodes, _p = skyrimhair.node_worlds(n)
    anchor = skyrimhair.head_anchor(n, nodes)
    for s in skyrimskin.skinned_shapes(n):
        nm = (s.name or b"").decode("latin-1")
        if not is_eye_shape(nm):
            continue
        names = [b.decode("latin-1") if isinstance(b, bytes) else b for b in s.bones]
        if skyrimhair.SKY_HEAD not in names:
            continue
        pos = np.asarray(s.positions, float)
        cands = [apply4(anchor @ np.linalg.inv(skyrimhair._bind_world(s, names.index(skyrimhair.SKY_HEAD))), pos)]
        if head_points is not None:
            cands.append(apply4(facefit.skyrim_model_matrix(n, s), pos))
            mid = np.asarray(head_points, float).mean(0)
            cands.sort(key=lambda p: float(np.linalg.norm(p.mean(0) - mid)))
        p = cands[0]
        if not (p[:, 0] < 0).any() or not (p[:, 0] > 0).any():
            continue
        return np.array([p[p[:, 0] < 0].mean(0), p[p[:, 0] > 0].mean(0)])
    return None


def landmarks(v, eyes, mouth) -> Dict[str, np.ndarray]:
    """{name: point}: the given eyes and mouth, and on the midline the nose tip (frontmost between mouth and eyes),
    nasion (deepest at the eyes' height and a little above), chin (frontmost 1.5-7 cm below the mouth), forehead
    (frontmost 3-6 cm above the eyes). Metres, +Y forward."""
    v = np.asarray(v, float)
    out = {"eyeL": eyes[0], "eyeR": eyes[1], "mouth": mouth}
    ez, mz = float(np.mean(eyes[:, 2])), float(mouth[2])
    mid = v[(np.abs(v[:, 0]) < 0.004) & (v[:, 1] > np.median(v[:, 1]))]

    def pick(lo, hi, fn):
        band = mid[(mid[:, 2] > lo) & (mid[:, 2] < hi)]
        return band[fn(band[:, 1])] if len(band) else None
    out["nose"] = pick(mz, ez, np.argmax)
    out["nasion"] = pick(ez - 0.005, ez + 0.03, np.argmin)
    out["chin"] = pick(mz - 0.07, mz - 0.015, np.argmax)
    out["forehead"] = pick(ez + 0.03, ez + 0.06, np.argmax)
    return out


def prealign(sky_v, sky_lm, sf_lm) -> Tuple[np.ndarray, Dict]:
    """The Skyrim head moved and scaled (no turn) so its landmarks meet Starfield's in the weighted least-squares
    sense (LM_WEIGHTS: the eyes most). (moved points, report; report["matrix"]: the 4x4 move; report["hair_lift_m"]:
    how far it raises the forehead, what the child's hair is lifted by - 2026-11-19, owner: Frodnar's hairline low
    on his forehead. Not the whole move: scaled with the face (1.11x for Dorthe) the hair's back stood out from her
    head like a bulb, owner: "what is this bulb in her hair")."""
    ks = [k for k in LM_WEIGHTS if sky_lm.get(k) is not None and sf_lm.get(k) is not None]
    w = np.array([LM_WEIGHTS[k] for k in ks])[:, None]
    a = np.array([sky_lm[k] for k in ks], float)
    b = np.array([sf_lm[k] for k in ks], float)
    ac, bc = (w * a).sum(0) / w.sum(), (w * b).sum(0) / w.sum()
    s = float((w * (a - ac) * (b - bc)).sum() / (w * (a - ac) ** 2).sum())
    moved = (np.asarray(sky_v, float) - ac) * s + bc
    P = np.eye(4)
    P[:3, :3] *= s
    P[:3, 3] = bc - s * ac
    lift = None
    if sky_lm.get("forehead") is not None:      # how far the move raises the forehead: the hair's lift (hair_lift)
        lift = round(float((sky_lm["forehead"][2] - ac[2]) * s + bc[2] - sky_lm["forehead"][2]), 5)
    rep = {"scale": round(s, 4), "landmarks": ks, "matrix": [[round(float(x), 7) for x in r] for r in P],
           "hair_lift_m": lift,
           "before_mm": {k: round(float(np.linalg.norm(sky_lm[k] - sf_lm[k])) * 1000, 1) for k in ks},
           "after_mm": {k: round(float(np.linalg.norm((sky_lm[k] - ac) * s + bc - sf_lm[k])) * 1000, 1) for k in ks}}
    return moved, rep


def _closest_pairs(p, a, b, c):
    """Closest points of p (N, 1, 3) on triangles a, b, c (N, K, 3) (Ericson 5.1.5, elementwise): (points, d2)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    bp = p - b
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    cp = p - c
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = va + vb + vc
    den = np.where(np.abs(den) < 1e-30, 1e-30, den)
    v, w = vb / den, vc / den
    with np.errstate(divide="ignore", invalid="ignore"):
        vab, vac, wbc = d1 / (d1 - d3), d2 / (d2 - d6), (d4 - d3) / ((d4 - d3) + (d5 - d6))
    u = 1 - v - w
    for m, (x, y, z) in (((vc <= 0) & (d1 >= 0) & (d3 <= 0), (1 - vab, vab, 0 * vab)),
                         ((vb <= 0) & (d2 >= 0) & (d6 <= 0), (1 - vac, 0 * vac, vac)),
                         ((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), (0 * wbc, 1 - wbc, wbc)),
                         ((d6 >= 0) & (d5 <= d6), (0 * d1, 0 * d1, 0 * d1 + 1)),
                         ((d3 >= 0) & (d4 <= d3), (0 * d1, 0 * d1 + 1, 0 * d1)),
                         ((d1 <= 0) & (d2 <= 0), (0 * d1 + 1, 0 * d1, 0 * d1))):
        u, v, w = np.where(m, x, u), np.where(m, y, v), np.where(m, z, w)
    q = u[..., None] * a + v[..., None] * b + w[..., None] * c
    return q, ((q - p) ** 2).sum(-1)


def closest_points(p, v, t, chunk: int = 1024, k: int = 16):
    """(points, distances, triangle index) of the closest points on mesh (v, t) to p: the k triangles with the
    nearest centroids, exactly."""
    t = np.asarray(t, int)
    p = np.asarray(p, float)
    A, B, C = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    cen = (A + B + C) / 3
    cc = (cen ** 2).sum(1)
    k = min(k, len(t))
    out, dist, tri = np.zeros_like(p), np.zeros(len(p)), np.zeros(len(p), int)
    for c0 in range(0, len(p), chunk):
        q = p[c0:c0 + chunk]
        d2c = (q ** 2).sum(1)[:, None] + cc[None] - 2 * q @ cen.T
        cand = np.argpartition(d2c, k - 1, axis=1)[:, :k]
        pts, d2 = _closest_pairs(q[:, None, :], A[cand], B[cand], C[cand])
        j = np.argmin(d2, axis=1)
        r = np.arange(len(q))
        out[c0:c0 + chunk] = pts[r, j]
        dist[c0:c0 + chunk] = np.sqrt(d2[r, j])
        tri[c0:c0 + chunk] = cand[r, j]
    return out, dist, tri


def closest_points_all(p, v, t, chunk: int = 384):
    """(points, distances, triangle index) of the closest points on mesh (v, t) to p (every triangle, chunked)."""
    t = np.asarray(t, int)
    A, B, C = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    out, dist, tri = np.zeros_like(p), np.zeros(len(p)), np.zeros(len(p), int)
    for c0 in range(0, len(p), chunk):
        q = p[c0:c0 + chunk]
        bary, d2 = headcorr.closest_on_triangles(q, A, B, C)
        j = np.argmin(d2, axis=1)
        r = np.arange(len(q))
        bb = bary[r, j]
        out[c0:c0 + chunk] = bb[:, :1] * A[j] + bb[:, 1:2] * B[j] + bb[:, 2:] * C[j]
        dist[c0:c0 + chunk] = np.sqrt(d2[r, j])
        tri[c0:c0 + chunk] = j
    return out, dist, tri


def edges(t) -> np.ndarray:
    t = np.asarray(t, int)
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    return np.unique(np.sort(e, 1), axis=0)


def smooth(field, e, nv: int, passes: int) -> np.ndarray:
    """field averaged with its mesh neighbours `passes` times (half own, half neighbours)."""
    deg = np.maximum(np.bincount(e.ravel(), minlength=nv).astype(float), 1)[:, None]
    f = np.array(field, float)
    for _ in range(passes):
        acc = np.zeros_like(f)
        np.add.at(acc, e[:, 0], f[e[:, 1]])
        np.add.at(acc, e[:, 1], f[e[:, 0]])
        f = 0.5 * f + 0.5 * acc / deg
    return f


def outward_normals(v, t) -> np.ndarray:
    """Vertex normals turned outward as a whole (the winding of either game's heads is not relied on)."""
    n = headcorr.vertex_normals(v, t)
    if ((np.asarray(v, float) - np.mean(v, 0)) * n).sum() < 0:
        n = -n
    return n


def face_weight(v, eyes, mouth) -> np.ndarray:
    """1 on the face, fading to 0 before the ears (y), below the jaw and above the forehead (metres)."""
    v = np.asarray(v, float)
    w = np.clip(v[:, 1] / 0.035, 0, 1)
    w *= np.clip((v[:, 2] - (mouth[2] - 0.095)) / 0.03, 0, 1)        # the whole chin (2026-11-19: it stood 4-6 mm out)
    w *= np.clip(((float(np.mean(eyes[:, 2])) + 0.075) - v[:, 2]) / 0.03, 0, 1)
    return w


def nose_tip(v, eyes, mouth) -> Optional[np.ndarray]:
    return landmarks(v, np.asarray(eyes, float), np.asarray(mouth, float)).get("nose")


def socket_lock(v, eyes) -> np.ndarray:
    """0 = does not move: within EYE_LOCK of an eye opening's centre, and the socket behind it (within EYE_LOCK of
    the eye's front-to-back axis, behind the opening: Starfield's sockets run back into the head, and pulling those
    walls to the face would push them through the lids); 1 = free, fading over EYE_FADE."""
    v = np.asarray(v, float)
    out = np.ones(len(v))
    for c in np.asarray(eyes, float):
        d3 = np.linalg.norm(v - c, axis=1)
        dax = np.linalg.norm((v - c)[:, [0, 2]], axis=1)
        d = np.where(v[:, 1] < c[1], dax, d3)
        out = np.minimum(out, np.clip((d - EYE_LOCK) / EYE_FADE, 0, 1))
    return out


def inside_mouth(v, mouth) -> np.ndarray:
    """1 for the mouth's inside (behind the lip line, within 3 cm across): it does not pull to the face."""
    v = np.asarray(v, float)
    dax = np.linalg.norm((v - mouth)[:, [0, 2]], axis=1)
    return ((v[:, 1] < mouth[1] - 0.004) & (dax < 0.03)).astype(float)


def subdivide(v, t) -> Tuple[np.ndarray, np.ndarray]:
    """One midpoint subdivision (each triangle into four)."""
    v = np.asarray(v, float)
    t = np.asarray(t, int)
    e = edges(t)
    key = {(int(a), int(b)): len(v) + i for i, (a, b) in enumerate(e)}
    mid = (v[e[:, 0]] + v[e[:, 1]]) / 2

    def m(a, b):
        return np.array([key[(min(x, y), max(x, y))] for x, y in zip(a, b)])
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    ab, bc, ca = m(a, b), m(b, c), m(c, a)
    nt = np.concatenate([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1),
                         np.stack([ab, bc, ca], 1)])
    return np.vstack([v, mid]), nt


def taubin(field, e, nv: int, passes: int, lam: float = 0.5, mu: float = -0.53) -> np.ndarray:
    """Taubin smoothing (lambda / mu steps): removes small bumps without shrinking the whole."""
    deg = np.maximum(np.bincount(e.ravel(), minlength=nv).astype(float), 1)[:, None]
    f = np.array(field, float)
    for _ in range(passes):
        for k in (lam, mu):
            acc = np.zeros_like(f)
            np.add.at(acc, e[:, 0], f[e[:, 1]])
            np.add.at(acc, e[:, 1], f[e[:, 0]])
            f = f + k * (acc / deg - f)
    return f


def refined_target(v, t, levels: int = 2, passes: int = 30) -> Tuple[np.ndarray, np.ndarray]:
    """The Skyrim head welded, subdivided `levels` times and Taubin-smoothed: a rounded, denser surface to fit to
    (its ~1,000 vertices' facets otherwise showed on Starfield's head as a fine bumpy texture)."""
    sv, st, _inv = welded(v, t)
    for _ in range(levels):
        sv, st = subdivide(sv, st)
    return taubin(sv, edges(st), len(sv), passes), st


def ear_weight(v, eyes) -> np.ndarray:
    """1 on the ears (beside the head at eye height), 0 elsewhere, fading over 1.5 cm."""
    v = np.asarray(v, float)
    ez = float(np.mean(np.asarray(eyes)[:, 2]))
    out = np.zeros(len(v))
    for side in (-1.0, 1.0):
        lat = side * v[:, 0]
        cand = v[(lat > np.percentile(lat, 97)) & (np.abs(v[:, 2] - ez) < 0.05) & (v[:, 1] < 0.02)]
        if not len(cand):
            continue
        c = cand.mean(0)
        out = np.maximum(out, np.clip((0.045 - np.linalg.norm(v - c, axis=1)) / 0.015, 0, 1) * (lat > 0.05))
    return out


NOSE_DEPTHS = (0.008, 0.012, 0.016, 0.020)   # m behind the tip where the nose's width is measured
NOSE_FEATHER = 0.006


def nose_widths(v, tip) -> np.ndarray:
    """Across-widths (m) of the head at NOSE_DEPTHS behind the nose tip, in the band from 14 mm below the tip to 2 mm
    above it: the nose wings and the cheek beside them as seen from the front."""
    v = np.asarray(v, float)
    band = v[(v[:, 2] > tip[2] - 0.014) & (v[:, 2] < tip[2] + 0.002)]
    out = []
    for dep in NOSE_DEPTHS:
        b = band[band[:, 1] > tip[1] - dep]
        out.append(float(b[:, 0].max() - b[:, 0].min()) if len(b) > 1 else np.nan)
    return np.array(out)


def narrow_nose(v, tip, nasion, target_widths) -> Tuple[np.ndarray, Dict]:
    """v with the nose region scaled across (about the tip's x) so its widths at NOSE_DEPTHS become the target's
    (2026-11-19, owner in game: "that nose is still big" - the fit left the wings 42 mm wide at 14 mm behind the tip
    where his are 34). The scale varies smoothly with depth and fades out over NOSE_FEATHER around the region (from
    the nostrils' bottom to the nasion, 2.4 cm behind the tip, 3.2 cm across). Only narrowing (scale <= 1)."""
    v = np.asarray(v, float)
    have = nose_widths(v, tip)
    ok = np.isfinite(have) & np.isfinite(target_widths) & (have > 0)
    if not ok.any():
        return v, {"nose": "not measured"}
    sc = np.ones(len(NOSE_DEPTHS))
    sc[ok] = np.clip(np.asarray(target_widths)[ok] / have[ok], 0.6, 1.0)
    depth = tip[1] - v[:, 1]
    s = np.interp(depth, np.array(NOSE_DEPTHS), sc)
    f = NOSE_FEATHER

    def ramp(x):
        return np.clip(x / f, 0, 1)
    r = ramp(v[:, 2] - (tip[2] - 0.016)) * ramp(float(nasion[2]) - v[:, 2]) * ramp(0.024 + f - depth) \
        * ramp(depth + f) * ramp(0.032 + f - np.abs(v[:, 0] - tip[0]))
    out = v.copy()
    out[:, 0] = tip[0] + (v[:, 0] - tip[0]) * (1 - r * (1 - s))
    return out, {"nose_widths_mm": [round(x * 1000, 1) for x in have],
                 "target_mm": [round(x * 1000, 1) for x in target_widths],
                 "after_mm": [round(x * 1000, 1) for x in nose_widths(out, tip)]}


def fit(sf_v, sf_t, sky_v, sky_t, eyes, mouth, rounds=ROUNDS, normal_rounds=NORMAL_ROUNDS) -> Tuple[np.ndarray, Dict]:
    """(moves (V, 3) per Starfield vertex, report): Starfield's head (model space, its triangles) fitted onto the
    (prealigned) Skyrim face, see the module text. eyes / mouth: Starfield's (starfield_eyes_mouth)."""
    sf_v = np.asarray(sf_v, float)
    wv, wt, inv = welded(sf_v, sf_t)
    e = edges(wt)
    nw = len(wv)
    w_face = face_weight(wv, eyes, mouth)
    w_ear = ear_weight(wv, eyes)
    lock = socket_lock(wv, eyes)
    tip = nose_tip(wv, eyes, mouth)
    w_nose = np.clip((NOSE_REACH - np.linalg.norm(wv - tip, axis=1)) / 0.012, 0, 1) if tip is not None else \
        np.zeros(len(wv))
    free = np.clip((np.linalg.norm(wv - mouth, axis=1) - MOUTH_FREE) / 0.008, 0, 1) * (1.0 - inside_mouth(wv, mouth))
    sky_v, sky_t = refined_target(sky_v, sky_t)
    fn = np.cross(sky_v[sky_t[:, 1]] - sky_v[sky_t[:, 0]], sky_v[sky_t[:, 2]] - sky_v[sky_t[:, 0]])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    fn *= np.sign(((sky_v[sky_t].mean(1) - sky_v.mean(0)) * fn).sum(1))[:, None]      # outward
    cur = wv.copy()
    pulled = []
    for k, (passes, step) in enumerate(tuple(rounds) + tuple(normal_rounds)):
        w = np.maximum(w_face, w_ear) if passes >= EAR_ROUNDS else w_face
        if k >= len(rounds):
            w = w * w_nose
        w_pull = w * free
        tgt, dist, j = closest_points(cur, sky_v, sky_t)
        cn = outward_normals(cur, wt)
        ok = (dist < REACH) & ((fn[j] * cn).sum(1) > FACING)
        raw = np.where(ok[:, None], tgt - cur, 0.0) * w_pull[:, None]
        if k >= len(rounds):     # along the normal of the smoothed head only (its own normals carry skin detail)
            sn = outward_normals(smooth(cur, e, nw, NORMAL_SMOOTH), wt)
            raw = (raw * sn).sum(1)[:, None] * sn
        move = smooth(raw, e, nw, passes)
        cover = smooth(np.where(ok, w_pull, 0.0)[:, None], e, nw, passes)
        move = move / np.maximum(cover, 0.2) * w[:, None] * lock[:, None]
        cur = cur + step * move
        pulled.append(int((ok & (w_pull > 0)).sum()))
    moves = taubin(cur - wv, e, nw, FINISH) * lock[:, None]
    disp = moves[inv]
    mag = np.linalg.norm(disp, axis=1)
    return disp, {"version": VERSION, "rounds": len(rounds), "vertices_pulling": pulled,
                  "max_move_mm": round(float(mag.max()) * 1000, 1),
                  "rms_move_mm": round(float(np.sqrt(np.mean(mag ** 2))) * 1000, 2)}


def child_shape(sf_model, sf_t, sky_model, sky_t, sky_eyes, sky_mouth) -> Tuple[np.ndarray, Dict]:
    """(moves (V, 3) in model space per Starfield vertex, report) for one child: landmarks, prealign, fit. Raises
    ValueError when a landmark is not found (the caller falls back to the difference transfer)."""
    eyes, mouth = starfield_eyes_mouth(sf_model, sf_t)
    if eyes is None or mouth is None:
        raise ValueError("Starfield head: eye / mouth openings not found")
    if sky_eyes is None or sky_mouth is None:
        what = [w for w, x in (("eyes shape", sky_eyes), ("mouth opening", sky_mouth)) if x is None]
        wv, wt, _inv = welded(np.asarray(sky_model, float), sky_t)
        found = sorted(((len(lp), [round(float(x) * 1000) for x in wv[lp].mean(0)])
                        for lp in headcorr.boundary_loops(wt)), reverse=True)[:6]
        raise ValueError(f"Skyrim FaceGen head: {' and '.join(what)} not found (its open loops: size, centre mm: "
                         f"{found}; median depth {round(float(np.median(wv[:, 1])) * 1000)} mm)")
    sf_lm = landmarks(sf_model, eyes, mouth)
    sky_lm = landmarks(sky_model, np.asarray(sky_eyes, float), np.asarray(sky_mouth, float))
    moved, pre = prealign(sky_model, sky_lm, sf_lm)
    disp, rep = fit(sf_model, sf_t, moved, sky_t, eyes, mouth)
    rep["prealign"] = pre
    cur = np.asarray(sf_model, float) + disp
    lm = landmarks(cur, eyes, mouth)
    if lm.get("nose") is not None and lm.get("nasion") is not None:
        tv, _tt = refined_target(moved, sky_t)
        tip_sky = landmarks(tv, eyes, mouth).get("nose")
        if tip_sky is not None:
            narrowed, rep["nose"] = narrow_nose(cur, lm["nose"], lm["nasion"], nose_widths(tv, tip_sky))
            disp = (narrowed - np.asarray(sf_model, float)) * socket_lock(sf_model, eyes)[:, None]
    disp = smooth_under_eyes(sf_model, sf_t, disp, eyes)
    disp = smooth_moves(sf_model, sf_t, disp, eyes, FACE_SMOOTH)
    rep["smoothed_passes"] = FACE_SMOOTH
    lids, rep["almond"] = almond_moves(np.asarray(sf_model, float) + disp, sf_t, eyes)
    return disp + lids, rep


def eye_rims(v, t, eyes, near: float = 0.005):
    """Per eye, the vertex indices of its opening's edge (the unwelded open loops of 12+ vertices whose centre is
    within `near` of the eye's centre; Starfield doubles the edge: both loops)."""
    v = np.asarray(v, float)
    out = []
    for c in np.asarray(eyes, float):
        idx = [i for lp in headcorr.boundary_loops(np.asarray(t, int)) if len(lp) >= 12 and
               np.linalg.norm(v[lp].mean(0) - c) < near for i in lp]
        out.append(np.array(sorted(set(idx)), int))
    return out


def almond_moves(v, t, eyes, close: float = ALMOND) -> Tuple[np.ndarray, Dict]:
    """(moves (V, 3), report): each upper lid edge vertex moved `close` of the way to the lower edge below it, most at
    the middle (a sine across the opening), forward by the eyeball's sagitta so the edge stays on the eye; the lid
    skin within LID_FALLOFF above the edge follows its nearest edge vertex, fading."""
    v = np.asarray(v, float)
    moves = np.zeros_like(v)
    rep = {"close": close, "eyes": []}
    for c, rim in zip(np.asarray(eyes, float), eye_rims(v, t, eyes)):
        if len(rim) < 12:
            rep["eyes"].append("no opening edge found")
            continue
        p = v[rim]
        x0, x1 = p[:, 0].min(), p[:, 0].max()
        up = p[:, 2] > c[2]
        lo = p[~up]
        if not up.any() or len(lo) < 3:
            rep["eyes"].append("no upper / lower edge")
            continue
        order = np.argsort(lo[:, 0])
        lx = lo[order, 0]
        lz = np.interp(p[up, 0], lx, lo[order, 2])
        ly = np.interp(p[up, 0], lx, lo[order, 1])
        taper = np.sin(np.pi * np.clip((p[up, 0] - x0) / max(x1 - x0, 1e-6), 0, 1))
        a = close * taper
        h = p[up, 2] - lz
        mv = np.stack([np.zeros(len(h)), a * (ly - p[up, 1]), a * (lz - p[up, 2])], 1)
        mv[:, 1] += a * (1 - a) * h ** 2 / (2 * EYEBALL_R)          # stay on the eyeball, not inside it
        edge_pts, edge_mv = p[up], mv
        # every vertex at an edge point's place (the doubled edge) and the lid skin above it
        d = np.linalg.norm(v[:, None, :] - edge_pts[None, :, :], axis=2)
        j = d.argmin(1)
        dist = d[np.arange(len(v)), j]
        above = (v[:, 2] >= edge_pts[j, 2] - 1e-6) & (v[:, 1] > c[1] - 0.006)
        w = np.where(dist < 1e-6, 1.0, np.clip(1 - dist / LID_FALLOFF, 0, 1) * above)
        moves += w[:, None] * edge_mv[j]
        rep["eyes"].append({"opening_mm": [round(float(x1 - x0) * 1000, 1), round(float(h.max()) * 1000, 1)],
                            "lowered_mm": round(float(-mv[:, 2].min()) * 1000, 2)})
    return moves, rep


def smooth_moves(sf_model, sf_t, disp, eyes, passes: int, weight=None) -> np.ndarray:
    """disp with its fine detail smoothed away (on the welded head; weight (welded V,) 0-1: where, everywhere by
    default), the eye lock kept."""
    wv, wt, inv = welded(np.asarray(sf_model, float), sf_t)
    nw = len(wv)
    cnt = np.maximum(np.bincount(inv, minlength=nw), 1)[:, None]
    wd = np.zeros((nw, 3))
    np.add.at(wd, inv, np.asarray(disp, float))
    wd /= cnt
    sm = smooth(wd, edges(wt), nw, passes) if passes > 0 else wd
    w = np.ones((nw, 1)) if weight is None else np.asarray(weight, float)[:, None]
    out = (wd * (1 - w) + sm * w) * socket_lock(wv, eyes)[:, None]
    return out[inv]


def under_eye_weight(v, eyes) -> np.ndarray:
    """1 in the band under and beside each eye (within UNDER_EYE of its centre, below 4 mm above it), fading over
    8 mm; 0 elsewhere."""
    v = np.asarray(v, float)
    out = np.zeros(len(v))
    for c in np.asarray(eyes, float):
        d = np.linalg.norm(v - c, axis=1)
        w = np.clip((UNDER_EYE - d) / 0.008, 0, 1) * np.clip((c[2] + 0.004 - v[:, 2]) / 0.004, 0, 1)
        out = np.maximum(out, w)
    return out


def smooth_under_eyes(sf_model, sf_t, disp, eyes, passes: int = UNDER_EYE_PASSES) -> np.ndarray:
    """disp with its fine detail smoothed away under and beside the eyes (under_eye_weight; the eye lock kept)."""
    wv, _wt, _inv = welded(np.asarray(sf_model, float), sf_t)
    return smooth_moves(sf_model, sf_t, disp, eyes, passes, under_eye_weight(wv, eyes))
