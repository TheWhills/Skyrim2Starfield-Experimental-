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


def boundary_vertices(tris) -> np.ndarray:
    """Vertices on edges used by one triangle only (a mesh's open rims: a head's neck opening, eye holes, mouth)."""
    t = np.asarray(tris, int)
    e = np.sort(np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), axis=1)
    uniq, cnt = np.unique(e, axis=0, return_counts=True)
    return np.unique(uniq[cnt == 1].ravel())


def orientation(v: np.ndarray, tris=None) -> np.ndarray:
    """A rotation putting a head upright and facing +Y: up = the axis the head is longest along (top = the side the
    face's widest part is not ... approximated: the end farther from the centroid's mass), front = of the other two
    axes, the one the nose sticks out along (the most extreme point relative to the centre). Owner's first preview
    2026-11-05: Starfield's head mesh is not Z-up, the faces lay sideways."""
    c = v - v.mean(0)
    ext = c.max(0) - c.min(0)
    up = int(np.argmax(ext))
    rest = [i for i in range(3) if i != up]
    reach = [max(c[:, i].max(), -c[:, i].min()) / max(ext[i], 1e-9) for i in rest]
    front = rest[int(np.argmax(reach))]
    fsign = 1.0 if c[:, front].max() >= -c[:, front].min() else -1.0
    # the chin / neck end is narrower than the cranium: the top is where the cross-section is wider
    hi = c[:, up] > np.percentile(c[:, up], 80)
    lo = c[:, up] < np.percentile(c[:, up], 20)
    width = lambda m: np.ptp(c[m][:, rest], axis=0).prod() if m.any() else 0.0
    usign = 1.0 if width(hi) >= width(lo) else -1.0
    if tris is not None and len(tris):
        rim = boundary_vertices(tris)
        if len(rim) > 20:                              # the neck opening is the largest rim: it is at the bottom
            # (owner's second preview 2026-11-05: Starfield's head carries a flared neck, wider than the cranium,
            # so the widest end was taken for the top and the faces were drawn upside down)
            usign = -1.0 if c[rim, up].mean() > 0 else 1.0
    R = np.zeros((3, 3))
    R[2, up] = usign                                   # new z = up
    R[1, front] = fsign                                # new y = front
    R[0] = np.cross(R[1], R[2])                        # new x completes a right-handed frame
    return R


def sheet(heads: Sequence[np.ndarray], tris: np.ndarray, size: int = 220, focus_z: float = None) -> np.ndarray:
    """Rows: front shaded, side shaded, front heat map of each head's distance to heads[0] (the same scale for all,
    the largest difference). Columns: the heads. Only the face (vertices in front of the head's middle and above
    the chin line when focus_z is given) is framed."""
    R = orientation(heads[0], tris)
    heads = [np.asarray(h, float) @ R.T for h in heads]
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


# ------------------------------------------------------------------ solid renders of meshes with their own triangles
LIGHT = np.array([0.35, 0.8, 0.45]) / np.linalg.norm([0.35, 0.8, 0.45])


def render(v: np.ndarray, tris: np.ndarray, size: int, yaw: float, bounds, color=None) -> np.ndarray:
    """(size, size, 3) uint8: the mesh's triangles filled with a z-buffer, seen from +Y after turning by yaw (as
    splat), smooth Lambert shading from vertex normals (or per-vertex `color` 0-255). 2026-11-19 (owner: compare the
    children's faces without the game): points were too coarse to judge a nose or lips, and the Skyrim heads have
    ~1,000 vertices."""
    v = np.asarray(v, float)
    t = np.asarray(tris, int).reshape(-1, 3)
    p, r = _view(v, yaw)
    n = vertex_normals(v, t) @ r.T
    (x0, x1), (z0, z1) = bounds
    sc = (size - 1) / max(x1 - x0, z1 - z0, 1e-12)
    sx = (p[:, 0] - x0) * sc
    sz = (z1 - p[:, 2]) * sc
    depth = p[:, 1]
    if color is None:
        nn = np.where((n[:, 1] < 0)[:, None], -n, n)
        shade = np.clip(nn @ LIGHT, 0, 1)
        col = np.stack([shade * 190 + 50, shade * 175 + 50, shade * 160 + 50], 1)
    else:
        col = np.asarray(color, float)
    img = np.full((size, size, 3), 235.0)
    zb = np.full((size, size), -np.inf)
    for a, b, c in t:
        xs, zs = sx[[a, b, c]], sz[[a, b, c]]
        lo_x, hi_x = int(max(np.floor(xs.min()), 0)), int(min(np.ceil(xs.max()), size - 1))
        lo_z, hi_z = int(max(np.floor(zs.min()), 0)), int(min(np.ceil(zs.max()), size - 1))
        if lo_x > hi_x or lo_z > hi_z:
            continue
        den = (zs[1] - zs[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (zs[0] - zs[2])
        if abs(den) < 1e-12:
            continue
        gx, gz = np.meshgrid(np.arange(lo_x, hi_x + 1) + 0.5, np.arange(lo_z, hi_z + 1) + 0.5)
        w0 = ((zs[1] - zs[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gz - zs[2])) / den
        w1 = ((zs[2] - zs[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gz - zs[2])) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        d = w0 * depth[a] + w1 * depth[b] + w2 * depth[c]
        zz, xx = gz.astype(int), gx.astype(int)
        cur = zb[zz, xx]
        win = inside & (d > cur)
        if not win.any():
            continue
        zb[zz[win], xx[win]] = d[win]
        img[zz[win], xx[win]] = (w0[win, None] * col[a] + w1[win, None] * col[b] + w2[win, None] * col[c])
    return np.clip(img, 0, 255).astype(np.uint8)


def face_bounds(meshes, keep, yaw: float = 0.0, margin: float = 0.05):
    """((x0, x1), (z0, z1)) framing the points `keep` of every mesh seen at yaw (a list of (V, 3) arrays and their
    boolean masks), with a margin (share of the size)."""
    pts = np.vstack([_view(np.asarray(m, float)[k], yaw)[0] for m, k in zip(meshes, keep)])
    x0, x1, z0, z1 = pts[:, 0].min(), pts[:, 0].max(), pts[:, 2].min(), pts[:, 2].max()
    m = margin * max(x1 - x0, z1 - z0)
    return (x0 - m, x1 + m), (z0 - m, z1 + m)


def mesh_sheet(meshes, size: int = 360, yaws=(0, 35, 90), frame=None, heat_of=None) -> np.ndarray:
    """Columns: meshes [(V, 3), triangles] in one model space (metres); rows: one per yaw (front, three-quarter,
    side), solid renders on shared bounds. frame: the vertices to frame per mesh (masks), default the part above
    each mesh's lowest 40 %. heat_of: (mesh index, per-vertex distances m) - an extra row with that mesh coloured
    by the distances (white 0 -> red at the largest)."""
    vs = [np.asarray(m[0], float) for m in meshes]
    if frame is None:
        frame = [v[:, 2] > v[:, 2].min() + 0.4 * np.ptp(v[:, 2]) for v in vs]
    rows = []
    for yaw in yaws:
        b = face_bounds(vs, frame, yaw)
        rows.append(np.hstack([render(v, m[1], size, yaw, b) for v, m in zip(vs, meshes)]))
    if heat_of is not None:
        k, dist = heat_of
        b = face_bounds(vs, frame, 0)
        top = float(np.max(dist)) or 1e-3
        cells = [np.full((size, size, 3), 235, np.uint8) for _ in vs]
        cells[k] = render(vs[k], meshes[k][1], size, 0, b, color=heat(np.asarray(dist, float), top))
        rows.append(np.hstack(cells))
    return np.vstack(rows)
