"""How thick each body part is, around its bone, for Skyrim's and Starfield's bodies: the basis for keeping a hand's
contact with the body when a Skyrim clip plays on Starfield's (thicker) body.

2026-11-14 (owner): "the difference in body is going to cause issues with every animation, can we account for that
when we convert": Skyrim's seated hands sank into Starfield's thighs (hands 0.05 m above the hip-knee line, Starfield's
own chair Idle 0.13 m), the wall-lean's crossed forearms into the chest. So, once per body: each segment (a bone to the
next joint: thigh, calf, upper arm, forearm, hips, belly, chest) gets a radius grid, the body surface's distance from
the segment by position along it (T_BINS) and direction around it (A_BINS), measured from the skinned body mesh in its
bind pose. A hand's place relative to Skyrim's surface can then be put at the same place relative to Starfield's.

Directions around a segment are measured in a frame fixed to the segment at rest: its axis, the actor's forward (+Y)
made perpendicular to it (or +X for a segment along Y), and their cross product. Both skeletons face +Y with +Z up.
"""
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

T_BINS = 5
A_BINS = 16

# (segment, Skyrim joint at its start, Skyrim joint at its end, Starfield start, Starfield end); joints as in
# skeletonmap.MAP. The hands are not segments (they are what touches); the head is left out for now.
SEGMENTS: List[Tuple[str, str, str, str, str]] = [
    ("hips", "NPC Pelvis [Pelv]", "NPC Spine [Spn0]", "C_Hips", "C_Spine"),
    ("belly", "NPC Spine [Spn0]", "NPC Spine2 [Spn2]", "C_Spine", "C_Chest"),
    ("chest", "NPC Spine2 [Spn2]", "NPC Neck [Neck]", "C_Chest", "C_Neck"),
]
for _s in ("L", "R"):
    SEGMENTS += [
        (f"{_s}_thigh", f"NPC {_s} Thigh [{_s}Thg]", f"NPC {_s} Calf [{_s}Clf]", f"{_s}_Thigh", f"{_s}_Calf"),
        (f"{_s}_calf", f"NPC {_s} Calf [{_s}Clf]", f"NPC {_s} Foot [{_s}ft ]", f"{_s}_Calf", f"{_s}_Foot"),
        (f"{_s}_upperarm", f"NPC {_s} UpperArm [{_s}Uar]", f"NPC {_s} Forearm [{_s}Lar]", f"{_s}_Biceps",
         f"{_s}_Forearm"),
        (f"{_s}_forearm", f"NPC {_s} Forearm [{_s}Lar]", f"NPC {_s} Hand [{_s}Hnd]", f"{_s}_Forearm", f"{_s}_Wrist"),
    ]


def segment_frame(a, b) -> np.ndarray:
    """3x3 rows (axis, ref0, ref1) of a segment from a to b at rest."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    u = b - a
    u = u / max(np.linalg.norm(u), 1e-12)
    ref = np.array([0.0, 1.0, 0.0])
    if abs(float(np.dot(u, ref))) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    r0 = ref - np.dot(ref, u) * u
    r0 = r0 / np.linalg.norm(r0)
    return np.stack([u, r0, np.cross(u, r0)])


def local_coords(a, b, frame, points) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(t along the segment, unclamped; angle around it in radians; distance from the axis) for points (N, 3)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    p = np.asarray(points, float).reshape(-1, 3) - a
    length = max(np.linalg.norm(b - a), 1e-12)
    along = p @ frame[0]
    t = along / length
    perp = p - along[:, None] * frame[0][None]
    ang = np.arctan2(perp @ frame[2], perp @ frame[1])
    return t, ang, np.linalg.norm(perp, axis=1)


def _bin(t, ang):
    ti = np.clip(np.floor(np.asarray(t) * T_BINS).astype(int), 0, T_BINS - 1)
    ai = np.floor((np.asarray(ang) + np.pi) / (2 * np.pi) * A_BINS).astype(int) % A_BINS
    return ti, ai


def measure(joints: Dict[str, np.ndarray], points, segments: Sequence[Tuple[str, str, str]]) -> Dict[str, Dict]:
    """{segment: {"a", "b", "frame", "radius" (T_BINS x A_BINS), "samples"}} from body points (N, 3, skeleton space,
    metres) and joint positions. segments: (name, start joint, end joint). Each point goes to the segment nearest to it
    (by distance to the segment, t clamped to [0, 1]); a segment keeps its points with t in [0, 1], and each bin's
    radius is their median distance from the axis. Empty bins take the mean of their filled neighbours around the
    axis, then of the segment."""
    pts = np.asarray(points, float).reshape(-1, 3)
    segs = [(n, np.asarray(joints[a], float), np.asarray(joints[b], float)) for n, a, b in segments
            if a in joints and b in joints]
    if not segs:
        return {}
    dist = np.empty((len(segs), len(pts)))
    for k, (_n, a, b) in enumerate(segs):
        ab = b - a
        t = np.clip((pts - a) @ ab / max(float(ab @ ab), 1e-12), 0.0, 1.0)
        dist[k] = np.linalg.norm(pts - (a + t[:, None] * ab[None]), axis=1)
    owner = np.argmin(dist, axis=0)
    out = {}
    for k, (n, a, b) in enumerate(segs):
        frame = segment_frame(a, b)
        mine = pts[owner == k]
        t, ang, r = local_coords(a, b, frame, mine)
        keep = (t >= 0.0) & (t <= 1.0)
        t, ang, r = t[keep], ang[keep], r[keep]
        grid = np.full((T_BINS, A_BINS), np.nan)
        ti, ai = _bin(t, ang)
        for i in range(T_BINS):
            for j in range(A_BINS):
                sel = (ti == i) & (ai == j)
                if np.any(sel):
                    grid[i, j] = float(np.median(r[sel]))
        for _pass in range(A_BINS):                                # fill around the axis from filled neighbours
            if not np.isnan(grid).any():
                break
            nb = np.stack([np.roll(grid, 1, axis=1), np.roll(grid, -1, axis=1)])
            fill = np.isnan(grid) & ~np.all(np.isnan(nb), axis=0)
            grid[fill] = np.nanmean(nb, axis=0)[fill]
        if np.isnan(grid).all():
            continue
        grid[np.isnan(grid)] = float(np.nanmean(grid))
        out[n] = {"a": a.tolist(), "b": b.tolist(), "frame": frame.tolist(), "radius": grid.round(4).tolist(),
                  "samples": int(keep.sum())}
    return out


def radius_at(profile: Dict, t, ang) -> np.ndarray:
    """Surface distance from a segment's axis at (t, angle) (arrays): bilinear in t and angle over the grid's bin
    centres, t clamped to the segment."""
    g = np.asarray(profile["radius"], float)
    tf = np.clip(np.asarray(t, float) * T_BINS - 0.5, 0, T_BINS - 1)
    af = (np.asarray(ang, float) + np.pi) / (2 * np.pi) * A_BINS - 0.5
    t0 = np.floor(tf).astype(int)
    t1 = np.minimum(t0 + 1, T_BINS - 1)
    wt = tf - t0
    a0 = np.floor(af).astype(int)
    wa = af - a0
    a0 %= A_BINS
    a1 = (a0 + 1) % A_BINS
    r0 = g[t0, a0] * (1 - wa) + g[t0, a1] * wa
    r1 = g[t1, a0] * (1 - wa) + g[t1, a1] * wa
    return r0 * (1 - wt) + r1 * wt


def summary(sky: Dict[str, Dict], sf: Dict[str, Dict]) -> List[Dict]:
    """Per segment: mean radius in each body and their ratio (Starfield / Skyrim)."""
    rows = []
    for name, *_ in SEGMENTS:
        if name in sky and name in sf:
            rs, rf = float(np.mean(sky[name]["radius"])), float(np.mean(sf[name]["radius"]))
            rows.append({"segment": name, "skyrim_m": round(rs, 4), "starfield_m": round(rf, 4),
                         "ratio": round(rf / rs, 3) if rs > 0 else None})
    return rows


def segments_for(side: str) -> List[Tuple[str, str, str]]:
    """(name, start, end) for one skeleton: side "skyrim" or "starfield"."""
    k = 1 if side == "skyrim" else 3
    return [(s[0], s[k], s[k + 1]) for s in SEGMENTS]


def nearest(profiles: Dict[str, Dict], point) -> Optional[Tuple[str, float]]:
    """(segment, distance from its surface) nearest to a rest-pose point; for checks."""
    best = None
    for n, pr in profiles.items():
        a, b, fr = np.array(pr["a"]), np.array(pr["b"]), np.array(pr["frame"])
        t, ang, r = local_coords(a, b, fr, [point])
        tc = float(np.clip(t[0], 0, 1))
        d = float(r[0] - radius_at(pr, tc, ang[0])) if 0 <= t[0] <= 1 else float(
            np.linalg.norm(np.asarray(point) - (a + tc * (b - a))))
        if best is None or d < best[1]:
            best = (n, d)
    return best
