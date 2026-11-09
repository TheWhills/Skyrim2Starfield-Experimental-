"""FaceGen .tri morph files (Skyrim head parts: race morphs, expression / phoneme morphs, chargen sliders). Read side.

Layout (FaceGen "FRTRI003", as Skyrim's head parts use it; read by NifSkope / Outfit Studio; checked here against
synthetic files only, the owner's run reports any file that does not read to its end):
    char magic[8]                 "FRTRI003"
    i32 V, T, Q                   vertices, triangles, quads
    i32 LV, LS                    labelled vertices, labelled surface points
    i32 X                         texture coordinates
    i32 ext                       bit 0: texture coordinates present
    i32 Md, Ms, K                 difference morphs, statistical morphs, extra vertices the stat morphs add
    u8  reserved[16]
    f32 vertices[(V + K) * 3]
    i32 tris[T * 3], quads[Q * 4]
    LV x (i32 vertex, i32 n, char label[n])
    LS x (i32 triangle, f32 xyz[3], i32 n, char label[n])
    if ext & 1: f32 uv[X * 2], i32 uv_tris[T * 3], i32 uv_quads[Q * 4]
    Md x (i32 n, char name[n], f32 scale, i16 delta[V * 3])        a morph: vertex += delta * scale
    Ms x (i32 n, char name[n], i32 L, i32 vertex[L])               those vertices move to the extra (K) positions
Chargen tris (the race's sliders: NoseLong, BrowUp, ...) and the race morph tri carry difference morphs.
"""
import struct
from typing import Dict

import numpy as np

MAGIC = b"FRTRI003"
HEADER = 64


class TriError(ValueError):
    pass


def _name(d: bytes, p: int):
    n = struct.unpack_from("<i", d, p)[0]
    if not 0 < n < 4096 or p + 4 + n > len(d):
        raise TriError(f"bad name length {n} at {p}")
    return d[p + 4:p + 4 + n].split(b"\0", 1)[0].decode("latin-1"), p + 4 + n


def parse(d: bytes, deltas: bool = False) -> Dict:
    """{vertices, triangles, quads, uv, morphs: [{name, scale[, max_m]}], stat_morphs: [{name, vertices}],
    complete: whether the file was read to its end}. deltas=True also returns each morph's (V, 3) offsets."""
    if len(d) < HEADER or d[:8] != MAGIC:
        raise TriError("not a FRTRI003 file")
    V, T, Q, LV, LS, X, ext, Md, Ms, K = struct.unpack_from("<10i", d, 8)
    if min(V, T, Q, LV, LS, X, Md, Ms, K) < 0 or V > 1_000_000:
        raise TriError("bad header counts")
    p = HEADER
    base = np.frombuffer(d, "<f4", (V + K) * 3, p).reshape(-1, 3)
    p += (V + K) * 12 + T * 12 + Q * 16
    for _ in range(LV):
        p += 4
        _n, p = _name(d, p)
    for _ in range(LS):
        p += 16
        _n, p = _name(d, p)
    if ext & 1:
        p += X * 8 + T * 12 + Q * 16
    out = {"vertices": V, "triangles": T, "quads": Q, "uv": X if ext & 1 else 0, "morphs": [], "stat_morphs": [],
           "complete": False}
    for _ in range(Md):
        name, p = _name(d, p)
        scale = struct.unpack_from("<f", d, p)[0]
        p += 4
        if p + V * 6 > len(d):
            raise TriError(f"morph {name!r} runs past the end")
        dv = np.frombuffer(d, "<i2", V * 3, p).reshape(-1, 3).astype(np.float64) * scale
        p += V * 6
        m = {"name": name, "scale": round(float(scale), 8),
             "max_offset": round(float(np.abs(dv).max()), 4) if V else 0.0}
        if deltas:
            m["deltas"] = dv
        out["morphs"].append(m)
    for _ in range(Ms):
        name, p = _name(d, p)
        L = struct.unpack_from("<i", d, p)[0]
        p += 4 + 4 * max(L, 0)
        out["stat_morphs"].append({"name": name, "vertices": L})
    out["complete"] = p == len(d)
    out["base"] = base[:V]
    return out
