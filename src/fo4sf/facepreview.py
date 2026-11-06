"""A quick picture of head shapes to compare without the game (owner 2026-11-05: "not sure their features are being
matched to anything or if they're just generic faces"): each head as shaded points (normals from its triangles),
front and side, panels side by side, the differences to the first panel as a heat map in a second row."""
from typing import List, Sequence, Tuple

import numpy as np


def vertex_normals(v: np.ndarray, tris: np.ndarray) -> np.ndarray:
    t = np.asarray(tris, int)
    fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, t[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def _view(v, yaw_deg):
    a = np.radians(yaw_deg)
    r = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    return v @ r.T, r


def splat(v: np.ndarray, n: np.ndarray, size: int, yaw: float, bounds, color=None, radius: int = 2) -> np.ndarray:
    """(size, size, 3) uint8: points seen from the front (+Y towards the viewer) after turning by yaw, Lambert shaded
    (or `color` (V, 3) 0-255), nearest wins."""
    p, r = _view(v, yaw)
    nn = n @ r.T
    (x0, x1), (z0, z1) = bounds
    sc = (size - 1) / max(x1 - x0, z1 - z0)
    px = ((p[:, 0] - x0) * sc).astype(int)
    pz = ((z1 - p[:, 2]) * sc).astype(int)
    depth = p[:, 1]                                   # larger = nearer the viewer (+Y)
    nn = np.where((nn[:, 1] < 0)[:, None], -nn, nn)    # facing the viewer whatever the triangles' winding
    light = np.clip(nn @ np.array([0.35, 0.8, 0.45]) / np.linalg.norm([0.35, 0.8, 0.45]), 0, 1)
    rgb = (np.stack([light] * 3, 1) * 200 + 40) if color is None else np.asarray(color, float)
    img = np.full((size, size, 3), 235, np.uint8)
    zb = np.full((size, size), -np.inf)
    order = np.argsort(depth)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            x, z = px[order] + dx, pz[order] + dy
            ok = (x >= 0) & (x < size) & (z >= 0) & (z < size)
            for i in np.nonzero(ok)[0]:          # back to front: the last write is the nearest
                xi, zi = x[i], z[i]
                if depth[order[i]] >= zb[zi, xi]:
                    zb[zi, xi] = depth[order[i]]
                    img[zi, xi] = rgb[order[i]]
    return img


def heat(d: np.ndarray, top: float) -> np.ndarray:
    """Distances (m) to colours: white 0 -> red at `top`."""
    t = np.clip(d / max(top, 1e-9), 0, 1)[:, None]
    return np.hstack([np.full_like(t, 255), 255 * (1 - t), 255 * (1 - t)])


def sheet(heads: Sequence[np.ndarray], tris: np.ndarray, size: int = 220, focus_z: float = None) -> np.ndarray:
    """Rows: front shaded, side shaded, front heat map of each head's distance to heads[0] (the same scale for all,
    the largest difference). Columns: the heads. Only the face (vertices in front of the head's middle and above
    the chin line when focus_z is given) is framed."""
    base = heads[0]
    keep = base[:, 1] > np.median(base[:, 1]) if focus_z is None else base[:, 2] > focus_z
    allp = np.vstack([h[keep] for h in heads])
    bounds = ((allp[:, 0].min(), allp[:, 0].max()), (allp[:, 2].min(), allp[:, 2].max()))
    turned = _view(allp, 90)[0]
    side_b = ((turned[:, 0].min(), turned[:, 0].max()), bounds[1])
    top = max(float(np.linalg.norm(h - base, axis=1).max()) for h in heads) or 1e-3
    rows = [[], [], []]
    for h in heads:
        n = vertex_normals(h, tris)
        rows[0].append(splat(h, n, size, 0, bounds))
        rows[1].append(splat(h, n, size, 90, side_b))
        rows[2].append(splat(h, n, size, 0, bounds, color=heat(np.linalg.norm(h - base, axis=1), top)))
    return np.vstack([np.hstack(r) for r in rows])
