"""Skyrim grass cards cut into blade-shaped geometry following their cut-out texture (2026-11-24).

Why (docs/terrain/skyrim-objects.md, grass slot test runs 9-13): Starfield grows our converted Skyrim grass, but some
cards draw as solid triangles ("fins") even up close: some of Starfield's grass rendering applies the cut-out weakly or
not at all. Vanilla Starfield grass is real blade geometry (the cut-out only trims edges), Skyrim's is a few big cards
shaped only by the cut-out (FieldGrass01: 3 triangles). So each card triangle becomes strips that follow the opaque
parts of its texture: a grid over the card's UV area, cells with any texel at or over the alpha threshold kept, runs of
kept cells down a column merged into one quad, each quad placed on the card's own plane (the triangle's affine UV ->
position map), with the card's UVs, normal and tangent. The material (and its cut-out) stays: where the cut-out works
the blades stay crisp; where it is skipped, blade strips show instead of a triangle.
"""
import dataclasses
from typing import List, Optional, Tuple

import numpy as np


def _sample(alpha, u, v):
    """Alpha texels at UVs (wrap addressing, row 0 = v 0)."""
    h, w = alpha.shape
    x = np.floor(np.mod(u, 1.0) * w).astype(int) % w
    y = np.floor(np.mod(v, 1.0) * h).astype(int) % h
    return alpha[y, x]


def _inside(p, a, b, c, eps=1e-6):
    """Points p (n, 2) inside triangle abc (2D), edges included."""
    def cross(o, q, r):
        return (q[0] - o[0]) * (r[..., 1] - o[1]) - (q[1] - o[1]) * (r[..., 0] - o[0])
    d1, d2, d3 = cross(a, b, p), cross(b, c, p), cross(c, a, p)
    neg = (d1 < -eps) | (d2 < -eps) | (d3 < -eps)
    pos = (d1 > eps) | (d2 > eps) | (d3 > eps)
    return ~(neg & pos)


def card_strips(uv_tri, alpha, ref: int, cols: int = 32, rows: int = 32, sub: int = 3):
    """[(u0, u1, v0, v1)] strips covering the opaque parts of one card: the card's UV bounding box in cols x rows cells,
    a cell kept when its centre lies in the UV triangle and any of sub x sub samples in it reaches ref; kept cells
    merged down each column."""
    t = np.asarray(uv_tri, float)
    umin, vmin = t.min(axis=0)
    umax, vmax = t.max(axis=0)
    if umax - umin <= 0 or vmax - vmin <= 0:
        return []
    du, dv = (umax - umin) / cols, (vmax - vmin) / rows
    keep = np.zeros((rows, cols), bool)
    cu = umin + (np.arange(cols) + 0.5) * du
    cv = vmin + (np.arange(rows) + 0.5) * dv
    gu, gv = np.meshgrid(cu, cv)
    centre = np.stack([gu, gv], axis=-1)
    inside = _inside(centre, t[0], t[1], t[2])
    offs = (np.arange(sub) + 0.5) / sub - 0.5
    for ou in offs:
        for ov in offs:
            keep |= _sample(alpha, gu + ou * du, gv + ov * dv) >= ref
    keep &= inside
    strips = []
    for c in range(cols):
        r = 0
        while r < rows:
            if keep[r, c]:
                r0 = r
                while r < rows and keep[r, c]:
                    r += 1
                strips.append((umin + c * du, umin + (c + 1) * du, vmin + r0 * dv, vmin + r * dv))
            else:
                r += 1
    return strips


def _affine(pos_tri, uv_tri):
    """(origin uv, origin pos, 3 x 2 matrix A) with pos = P0 + A @ (uv - T0), or None for a degenerate UV triangle."""
    p = np.asarray(pos_tri, float)
    t = np.asarray(uv_tri, float)
    m = np.column_stack([t[1] - t[0], t[2] - t[0]])
    if abs(np.linalg.det(m)) < 1e-12:
        return None
    a = np.column_stack([p[1] - p[0], p[2] - p[0]]) @ np.linalg.inv(m)
    return t[0], p[0], a


def blade_shape(sh, alpha, ref: int, cols: int = 32, rows: int = 32):
    """The shape with every card triangle replaced by blade strips (card_strips); triangles whose UVs are degenerate
    are kept as they are. Returns (new shape, stats)."""
    pos, uv, tris = sh.positions, sh.uvs, sh.triangles
    if not uv or not tris:
        return sh, {"cards": 0, "strips": 0}
    out_p: List[Tuple[float, float, float]] = []
    out_uv: List[Tuple[float, float]] = []
    out_n: List[Tuple[float, float, float]] = []
    out_t: List[Tuple[float, float, float]] = []
    out_tri: List[Tuple[int, int, int]] = []
    n_strips = 0
    for tri in tris:
        P = [pos[i] for i in tri]
        T = [uv[i] for i in tri]
        aff = _affine(P, T)
        face = np.cross(np.subtract(P[1], P[0]), np.subtract(P[2], P[0]))
        if sh.normals:
            want = np.mean([sh.normals[i] for i in tri], axis=0)
            if np.dot(face, want) < 0:
                face = -face
        ln = np.linalg.norm(face)
        if aff is None or ln == 0:                   # degenerate: keep the original triangle
            base = len(out_p)
            out_p += [tuple(P[k]) for k in range(3)]
            out_uv += [tuple(T[k]) for k in range(3)]
            nn = tuple(face / ln) if ln else (0.0, 0.0, 1.0)
            out_n += [nn] * 3
            out_t += [(1.0, 0.0, 0.0)] * 3
            out_tri.append((base, base + 1, base + 2))
            continue
        normal = face / ln
        t0, p0, a = aff
        tangent = a[:, 0] / (np.linalg.norm(a[:, 0]) or 1.0)
        for u0, u1, v0, v1 in card_strips(T, alpha, ref, cols, rows):
            corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            q = [tuple(p0 + a @ (np.array(c) - t0)) for c in corners]
            base = len(out_p)
            out_p += q
            out_uv += corners
            out_n += [tuple(normal)] * 4
            out_t += [tuple(tangent)] * 4
            if np.dot(np.cross(np.subtract(q[1], q[0]), np.subtract(q[2], q[0])), normal) >= 0:
                out_tri += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
            else:
                out_tri += [(base, base + 2, base + 1), (base, base + 3, base + 2)]
            n_strips += 1
    new = dataclasses.replace(sh, positions=out_p, uvs=out_uv, normals=out_n, tangents=out_t, colors=[],
                              triangles=out_tri)
    return new, {"cards": len(tris), "strips": n_strips, "tris": len(out_tri)}


def opacity_plane(dds: bytes) -> Optional[np.ndarray]:
    """Level 0 of a BC4 (DX10) opacity DDS as a uint8 plane, or None if it is not one."""
    from fo4sf import textures
    import struct
    if dds[:4] != b"DDS " or dds[84:88] != b"DX10":
        return None
    fmt, = struct.unpack_from("<I", dds, 128)
    if fmt not in (79, 80, 81):                      # BC4 typeless / unorm / snorm
        return None
    h, w = struct.unpack_from("<2I", dds, 12)
    return textures.decode_bc4(dds[textures.DX10_HEADER_BYTES:], max(4, w), max(4, h))[:h, :w]
