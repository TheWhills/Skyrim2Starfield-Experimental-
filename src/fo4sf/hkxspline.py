"""Decode Havok 2010 hkaSplineCompressedAnimation track data (Skyrim .hkx) into per-frame transforms.

Written for this repository from the layout below; checked value by value against an independent decoder (PyNifly's
anim_skyrim.py, GPL, run outside the repo as a black box) on real Skyrim SE / LE files (tests/test_hkx_spline.py uses
synthetic data; the real-file comparison is scripts/armor/hkx_decode_check.py).

Layout of one block (the bytes at data[blockOffsets[b]:]), offsets aligned relative to the data start:
  per transform track: a 4-byte mask (quantization types, position types, rotation types, scale types)
  per float track: a 1-byte mask
  align 4
  per transform track: position, rotation, scale, each:
    vector (position, scale):
      any spline axis (type bits 4-6):
        u16 control-point count - 1 (n), u8 degree (p), u8 knots[n + p + 2], align 4,
        per axis: spline -> f32 min, f32 max; static (bits 0-2) -> f32 value; neither -> default,
        (n + 1) control points of the spline axes, 8- or 16-bit each (quantization bits 0-1 position, 6-7 scale),
        align 4
      else per static axis: f32 value
    rotation (quantization bits 2-5 select the encoding; spline = bits 4-7, static = bits 0-3):
      spline: u16 n, u8 p, u8 knots[n + p + 2], align to the encoding, (n + 1) quaternions
      static: align to the encoding, one quaternion
      align 4
  float tracks follow (not decoded here).
Each block covers maxFramesPerBlock frames; consecutive blocks share one frame (block b starts at frame
b * (maxFramesPerBlock - 1)). Splines are evaluated at the frame index inside the block (knots are frame numbers).
"""
import math
import struct
from typing import List, Optional, Sequence, Tuple

ROT_SIZES = {0: (4, 4), 1: (5, 1), 2: (6, 2), 3: (3, 1), 4: (2, 2), 5: (16, 4)}     # encoding -> (bytes, alignment)
ROT_NAMES = {0: "polar32", 1: "threecomp40", 2: "threecomp48", 3: "threecomp24", 4: "straight16", 5: "uncompressed"}


class SplineError(ValueError):
    pass


def _align(p: int, a: int) -> int:
    return (p + a - 1) // a * a if a > 1 else p


# ------------------------------------------------------------------------------------------------- quaternions
def quat_threecomp48(b: bytes) -> Tuple[float, float, float, float]:
    """6 bytes: three 15-bit components (offset 0x3FFF, scale 1/sqrt(2) / 0x3FFF); the two top bits of the first two
    words give which component (x, y, z, w) was dropped, the top bit of the third its sign."""
    a, c, d = struct.unpack("<3H", b)
    shift = ((c >> 14) & 2) | ((a >> 15) & 1)
    neg = (d >> 15) & 1
    k = (1.0 / math.sqrt(2.0)) / 16383.0
    v = [((a & 0x7FFF) - 16383) * k, ((c & 0x7FFF) - 16383) * k, ((d & 0x7FFF) - 16383) * k]
    m = math.sqrt(max(0.0, 1.0 - sum(x * x for x in v)))
    if neg:
        m = -m
    v.insert(shift, m)
    return tuple(v)


def quat_threecomp40(b: bytes) -> Tuple[float, float, float, float]:
    """5 bytes: three 12-bit components (offset 2047, scale 1/sqrt(2) / 2047), 2 bits dropped component, 1 bit sign."""
    v = int.from_bytes(b, "little")
    k = (1.0 / math.sqrt(2.0)) / 2047.0
    comps = [(((v >> (12 * i)) & 0xFFF) - 2047) * k for i in range(3)]
    shift = (v >> 36) & 3
    m = math.sqrt(max(0.0, 1.0 - sum(x * x for x in comps)))
    if (v >> 38) & 1:
        m = -m
    comps.insert(shift, m)
    return tuple(comps)


def quat_uncompressed(b: bytes):
    return struct.unpack("<4f", b)


DECODERS = {1: quat_threecomp40, 2: quat_threecomp48, 5: quat_uncompressed}


# ------------------------------------------------------------------------------------------------- B-splines
def find_span(n: int, p: int, u: float, knots: Sequence[float]) -> int:
    if u >= knots[n + 1]:
        return n
    if u <= knots[p]:
        return p
    lo, hi = p, n + 1
    mid = (lo + hi) // 2
    while u < knots[mid] or u >= knots[mid + 1]:
        if u < knots[mid]:
            hi = mid
        else:
            lo = mid
        mid = (lo + hi) // 2
    return mid


def basis(span: int, u: float, p: int, knots: Sequence[float]) -> List[float]:
    """The p + 1 non-zero B-spline basis functions at u (Piegl & Tiller A2.2)."""
    N = [1.0] + [0.0] * p
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)
    for j in range(1, p + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            den = right[r + 1] + left[j - r]
            t = N[r] / den if den != 0 else 0.0
            N[r] = saved + right[r + 1] * t
            saved = left[j - r] * t
        N[j] = saved
    return N


def evaluate(u: float, p: int, knots, points):
    """Spline value at u: points is a list of equal-length tuples (n + 1 control points)."""
    n = len(points) - 1
    span = find_span(n, p, u, knots)
    N = basis(span, u, p, knots)
    dim = len(points[0])
    out = [0.0] * dim
    for i in range(p + 1):
        cp = points[span - p + i]
        for d in range(dim):
            out[d] += N[i] * cp[d]
    return out


# ------------------------------------------------------------------------------------------------- one block
class _Reader:
    def __init__(self, data: bytes, pos: int):
        self.d, self.p = data, pos

    def take(self, n: int) -> bytes:
        if self.p + n > len(self.d):
            raise SplineError(f"read past the data at {self.p} (+{n})")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def unpack(self, fmt: str):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def align(self, a: int):
        self.p = _align(self.p, a)


def _vector(r: _Reader, types: int, quant: int, default: float):
    """(constant (3,), or None) and (spline description or None)."""
    spline_axes = [a for a in range(3) if types & (0x10 << a)]
    if spline_axes:
        n, p = r.unpack("<HB")
        knots = list(r.take(n + p + 2))
        r.align(4)
        lo_hi, const = {}, [default] * 3
        for a in range(3):
            if types & (0x10 << a):
                lo_hi[a] = r.unpack("<2f")
            elif types & (1 << a):
                const[a], = r.unpack("<f")
        size = 1 if quant == 0 else 2
        cps = []
        for _ in range(n + 1):
            row = []
            for a in spline_axes:
                q, = r.unpack("<B" if size == 1 else "<H")
                lo, hi = lo_hi[a]
                row.append(lo + (hi - lo) * q / (255.0 if size == 1 else 65535.0))
            cps.append(row)
        r.align(4)
        return const, {"degree": p, "knots": knots, "axes": spline_axes, "points": cps}
    const = [default] * 3
    for a in range(3):
        if types & (1 << a):
            const[a], = r.unpack("<f")
    return const, None


def _rotation(r: _Reader, types: int, enc: int):
    if enc not in DECODERS:
        raise SplineError(f"rotation encoding {ROT_NAMES.get(enc, enc)} not supported")
    size, al = ROT_SIZES[enc]
    dec = DECODERS[enc]
    if types & 0xF0:
        n, p = r.unpack("<HB")
        knots = list(r.take(n + p + 2))
        r.align(al)
        pts = [dec(r.take(size)) for _ in range(n + 1)]
        r.align(4)
        return None, {"degree": p, "knots": knots, "points": pts}
    if types & 0x0F:
        r.align(al)
        q = dec(r.take(size))
        r.align(4)
        return q, None
    r.align(4)
    return (0.0, 0.0, 0.0, 1.0), None


def _sample_vector(const, spl, u):
    if spl is None:
        return tuple(const)
    v = list(const)
    val = evaluate(u, spl["degree"], spl["knots"], spl["points"])
    for i, a in enumerate(spl["axes"]):
        v[a] = val[i]
    return tuple(v)


def _sample_rotation(const, spl, u):
    if spl is None:
        return const
    q = evaluate(u, spl["degree"], spl["knots"], spl["points"])
    s = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / s for c in q)


def decode(data: bytes, block_offsets: Sequence[int], n_tracks: int, n_float: int, n_frames: int,
           max_frames_per_block: int, stats: Optional[dict] = None):
    """[frame][track] -> (translation (3,), rotation quaternion (x, y, z, w), scale (3,))."""
    frames: List[list] = [None] * n_frames
    per = max_frames_per_block - 1 if max_frames_per_block > 1 else 1
    for b, start in enumerate(block_offsets):
        r = _Reader(data, start)
        masks = [r.unpack("<4B") for _ in range(n_tracks)]
        r.take(n_float)
        r.align(4)
        tracks = []
        for q, pt, rt, st in masks:
            if stats is not None:
                stats.setdefault("rotation_encodings", {})
                e = ROT_NAMES.get((q >> 2) & 0xF, (q >> 2) & 0xF)
                stats["rotation_encodings"][e] = stats["rotation_encodings"].get(e, 0) + 1
            pos = _vector(r, pt, q & 3, 0.0)
            rot = _rotation(r, rt, (q >> 2) & 0xF)
            scl = _vector(r, st, (q >> 6) & 3, 1.0)
            tracks.append((pos, rot, scl))
        first = b * per
        last = min(n_frames - 1, first + per)
        for f in range(first, last + 1):
            u = float(f - first)
            frames[f] = [(_sample_vector(*pos, u), _sample_rotation(*rot, u), _sample_vector(*scl, u))
                         for pos, rot, scl in tracks]
    if any(f is None for f in frames):
        raise SplineError("blocks did not cover every frame")
    return frames
