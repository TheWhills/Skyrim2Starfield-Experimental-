"""Root motion: Skyrim clip annotations -> the Root track and .af header of a Starfield clip.

Skyrim side (verified 2026-10-19 on the 202 clips BFCO ships, nexusmods.com/skyrimspecialedition/mods/117052, read
for the format only): animation packs carry the character's movement in the clip's own annotations, as
`animmotion X Y Z` (the displacement from the clip's start, game units, at that annotation's time; keys may be dense,
one per frame, or sparse, linear in between - BFCO_JumpAttack has two: 0 at 0 s and Y = 333.4 at 0.9 s) and
`animrotation A` (the accumulated turn about the up axis at that time, in degrees; every key in BFCO's own clips is
0, so the sign is **unresolved**: taken here as counter-clockwise seen from above, i.e. positive = turn left, like
a right-handed rotation about +Z). Skyrim's forward is +Y, up +Z, as in Starfield. The NPC Root bone of those clips
stays put (verified on BFCO_Attack1 / PowerAttackA); the motion is only in the annotations.

Starfield side (verified 2026-10-19 on the owner's vanilla clips, 966 .af): the Root bone's own track is the motion
(vanilla MeleeAttack_A: Root translation keys from 0 to (0, 1.847, 0) m; turning clips also key Root rotation), and
the .af header repeats where it ends: header rotation (f32 w, x, y, z at byte 8) = the last Root rotation and header
translation (f32 x, y, z at byte 24) = the last Root translation, in all 582 clips with a header translation and all
156 with a header rotation checked. Clips without motion leave Root out and the header at identity / zero.
"""
import math
import re
import struct
from typing import Dict, List, Optional, Tuple

import numpy as np

MOTION = re.compile(r"^\s*animmotion\s+(\S+)\s+(\S+)\s+(\S+)", re.I)
ROTATION = re.compile(r"^\s*animrotation\s+(\S+)", re.I)
HEADER_ROTATION, HEADER_TRANSLATION = 8, 24


def is_motion_annotation(text: str) -> bool:
    return bool(MOTION.match(text or "") or ROTATION.match(text or ""))


def _pchip(x: np.ndarray, y: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Monotone cubic (Fritsch-Carlson / PCHIP) through (x, y), evaluated at t; constant outside [x0, xn]. Passes
    through every key, never overshoots between them (a hold stays a hold), and keeps the speed continuous."""
    n = len(x)
    if n == 1:
        return np.full_like(t, y[0], dtype=float)
    h = np.diff(x)
    d = np.diff(y) / h
    m = np.zeros(n)
    if n == 2:
        m[:] = d[0]
    else:
        for i in range(1, n - 1):
            if d[i - 1] * d[i] > 0:
                w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
                m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
        for i, dd, nb, hm, hn in ((0, d[0], d[1], h[0], h[1]), (n - 1, d[-1], d[-2], h[-1], h[-2])):
            v = ((2 * hm + hn) * dd - hm * nb) / (hm + hn)
            if np.sign(v) != np.sign(dd):
                v = 0.0
            elif np.sign(dd) != np.sign(nb) and abs(v) > abs(3 * dd):
                v = 3 * dd
            m[i] = v
    tc = np.clip(t, x[0], x[-1])
    k = np.clip(np.searchsorted(x, tc, side="right") - 1, 0, n - 2)
    u = (tc - x[k]) / h[k]
    h00, h10, h01, h11 = 2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u, -2 * u**3 + 3 * u**2, u**3 - u**2
    return h00 * y[k] + h10 * h[k] * m[k] + h01 * y[k + 1] + h11 * h[k] * m[k + 1]


def _track(keys: List[Tuple[float, np.ndarray]], times: np.ndarray, dim: int) -> np.ndarray:
    """The keys interpolated at `times`; an implicit zero at time 0 when the first key is later; the last value
    holds after the last key. Monotone cubic (PCHIP) between keys: pack clips often carry a handful of keys per
    attack (Nordic Combat Animations' mco_attack1: 6 over 1.83 s), and linear interpolation made the root speed jump
    (0 -> 2.4 -> 5.9 -> 0 m/s from one frame to the next; owner: "less smooth than in Skyrim")."""
    keys = sorted(keys, key=lambda k: k[0])
    if not keys or keys[0][0] > 1e-6:
        keys = [(0.0, np.zeros(dim))] + keys
    kt = np.array([k[0] for k in keys])
    kv = np.array([k[1] for k in keys]).reshape(len(keys), dim)
    idx = [i for i in range(len(kt)) if i == len(kt) - 1 or kt[i + 1] - kt[i] > 1e-9]   # same time: later wins
    kt, kv = kt[idx], kv[idx]
    if len(times) and kt[-1] < times[-1] - 1e-6:          # the motion holds after the last key: end it at rest
        kt, kv = np.r_[kt, times[-1]], np.vstack([kv, kv[-1:]])
    return np.stack([_pchip(kt, kv[:, d], times) for d in range(dim)], axis=1)


def from_annotations(annotations, frames: int, fps: float) -> Optional[Dict]:
    """{"t": (F, 3) game units, "yaw": (F,) degrees} from animmotion / animrotation annotations, or None without any."""
    mot, rot = [], []
    for a in annotations or []:
        m = MOTION.match(a.get("text", ""))
        if m:
            mot.append((float(a["time"]), np.array([float(x) for x in m.groups()])))
            continue
        r = ROTATION.match(a.get("text", ""))
        if r:
            rot.append((float(a["time"]), np.array([float(r.group(1))])))
    if not mot and not rot:
        return None
    times = np.arange(frames) / float(fps)
    return {"t": _track(mot, times, 3), "yaw": _track(rot, times, 1)[:, 0]}


def root_track(motion: Dict, metres_per_unit: float, scale: float = 1.0) -> Tuple[np.ndarray, np.ndarray]:
    """(F, 3) metres and (F, 4) quaternions (x, y, z, w) about +Z for the Root bone."""
    t = np.asarray(motion["t"], float) * metres_per_unit * scale
    half = np.radians(np.asarray(motion["yaw"], float)) / 2.0
    q = np.zeros((len(half), 4))
    q[:, 2], q[:, 3] = np.sin(half), np.cos(half)
    return t, q


def moves(t, q, tol_m: float = 1e-3, tol_deg: float = 0.05) -> bool:
    t, q = np.asarray(t, float), np.asarray(q, float)
    ang = np.degrees(2 * np.arccos(np.clip(np.abs(q[:, 3]), 0, 1)))
    return bool(np.max(np.abs(t)) > tol_m or np.max(ang) > tol_deg)


def patch_header(af_path: str, t, q_xyzw) -> None:
    """Write the clip's end of root motion into the .af header (rotation w, x, y, z at byte 8; translation at 24)."""
    x, y, z, w = (float(v) for v in q_xyzw)
    with open(af_path, "r+b") as fh:
        fh.seek(HEADER_ROTATION)
        fh.write(struct.pack("<4f", w, x, y, z))
        fh.seek(HEADER_TRANSLATION)
        fh.write(struct.pack("<3f", *(float(v) for v in t)))


def read_header(data: bytes) -> Tuple[Tuple[float, float, float, float], Tuple[float, float, float]]:
    """((x, y, z, w), (x, y, z)) of an .af header."""
    w, x, y, z = struct.unpack_from("<4f", data, HEADER_ROTATION)
    return (x, y, z, w), struct.unpack_from("<3f", data, HEADER_TRANSLATION)


def yaw_degrees(q_xyzw) -> float:
    x, y, z, w = q_xyzw
    return math.degrees(2 * math.atan2(z, w))
