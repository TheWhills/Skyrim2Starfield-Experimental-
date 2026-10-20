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


def _track(keys: List[Tuple[float, np.ndarray]], times: np.ndarray, dim: int) -> np.ndarray:
    """Linear interpolation of (time, value) keys at `times`; an implicit zero at time 0 when the first key is later;
    the last value holds after the last key."""
    keys = sorted(keys, key=lambda k: k[0])
    if not keys or keys[0][0] > 1e-6:
        keys = [(0.0, np.zeros(dim))] + keys
    kt = np.array([k[0] for k in keys])
    kv = np.array([k[1] for k in keys]).reshape(len(keys), dim)
    return np.stack([np.interp(times, kt, kv[:, d]) for d in range(dim)], axis=1)


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
