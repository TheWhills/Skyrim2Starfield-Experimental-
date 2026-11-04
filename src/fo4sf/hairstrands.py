"""Starfield-style hair cards grown over a converted Skyrim hair (owner 2026-11-03: "do we need to make it so it has
all the strands like Starfield's" - yes).

Skyrim's vanilla hairstyles are a few low-poly shells with strands painted on (200-2000 vertices; Starfield's own
hairs are thousands of thin strand strips, 20-50k triangles). Under Starfield's hair shader the shells light as a few
big surfaces (patches, bands) however their textures are prepared. Here the Skyrim hair, already fitted to Starfield's
head, is only a guide: its surface and the direction its strands run on it. Over it grow many thin ribbons ("cards")
along that direction, in layers a little apart, each mapped onto one strand strip of a vanilla Starfield hair texture,
so the hair uses the game's own hair material (as IDG's hairs do: no textures of their own) and its strands, roots,
AO, depth and hair colour behave as vanilla's.

    strips = strip_layout(opacity)                 # strand strips of the vanilla texture, (u0, v0, u1, v1), root at v0
    cards, report = grow_cards(hair, head, strips) # a Hair of ribbon shapes, weights copied from the guide

All lengths in metres, Starfield model space.
"""
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .skyrimhair import Hair, HairShape

CARD_WIDTH = 0.012          # m: a card across (vanilla strips are ~1/11 of a 1024 texture wide)
CARD_STEP = 0.006           # m: between a card's rows of vertices along its length
CARD_SPACING = 0.007        # m: the least distance between neighbouring cards' centre lines in one layer
LAYER_GAP = 0.0015          # m: each layer this much further out from the guide surface
LAYERS = 3
SURFACE_REACH = 0.010       # m: a trace leaving the guide by more than this stops (its edge)
MAX_TURN_DEG = 50.0         # a trace turning more than this in one step stops (a fold or a parting)


# ------------------------------------------------------------------------------------------------- texture strips
def strip_layout(opacity, min_rows: int = 2, max_rows: int = 6) -> List[Tuple[float, float, float, float]]:
    """The strand strips of a hair opacity map (h, w), as UV rectangles (u0, v0, u1, v1): rows of strips found where
    the texture is empty across its whole width (or nearly: the deepest valleys of the row profile), strips within a
    row where its columns are. Verified on the owner's game 2026-11-03 (hair_probe): Medium_Hair_Shared's opacity is
    3 rows of 9-11 strips, strands running down each, roots at the top (its albedo is darker there)."""
    a = np.asarray(opacity, np.float64)
    if a.ndim == 3:
        a = a[:, :, 0]
    a = a / max(float(a.max()), 1.0)
    h, w = a.shape
    rows = _bands(a.mean(1), max(1, h // 512), min_rows, max_rows, min_size=h // 16)
    out = []
    for r0, r1 in rows:
        cols = _bands(a[r0:r1].mean(0), max(1, w // 256), 1, 24, min_size=w // 64)
        for c0, c1 in cols:
            if a[r0:r1, c0:c1].mean() > 0.02:
                out.append((c0 / w, r0 / h, c1 / w, r1 / h))
    return out


def _bands(profile, smooth: int, lo: int, hi: int, min_size: int) -> List[Tuple[int, int]]:
    """Runs of a 1-D coverage profile split at its empty stretches (below 8 % of its median where covered), merged
    to at least `min_size`; between `lo` and `hi` runs, else the profile cut evenly into `lo` parts."""
    p = np.convolve(np.asarray(profile, np.float64), np.ones(2 * smooth + 1) / (2 * smooth + 1), mode="same")
    n = len(p)
    covered = p[p > 1e-6]
    if not len(covered):
        return [(0, n)]
    on = p > 0.08 * float(np.median(covered))
    runs, k = [], 0
    while k < n:
        if on[k]:
            j = k
            while j < n and on[j]:
                j += 1
            runs.append([k, j])
            k = j
        else:
            k += 1
    merged = []
    for r in runs:
        if merged and (r[1] - r[0] < min_size or merged[-1][1] - merged[-1][0] < min_size) and \
                r[0] - merged[-1][1] < min_size:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    merged = [(int(a), int(b)) for a, b in merged if b - a >= min_size]
    if not (lo <= len(merged) <= hi):
        edges = np.linspace(0, n, lo + 1).astype(int)
        return [(int(edges[i]), int(edges[i + 1])) for i in range(lo)]
    return merged


# ------------------------------------------------------------------------------------------------- the guide
class Guide:
    """The guide surface: every vertex of the hair's shapes with its outward normal, strand direction (root to tip:
    cross(normal, tangent), turned to point away from the crown) and bone weights."""

    def __init__(self, hair: Hair, head: np.ndarray):
        pts, nrm, tan, wts = [], [], [], []
        for sh in hair.shapes:
            p = np.asarray(sh.positions, float)
            if not len(p) or sh.normals is None or sh.tangents is None:
                continue
            n = np.asarray(sh.normals, float)
            t = np.asarray(sh.tangents, float)
            if n.shape != p.shape or t.shape != p.shape:
                continue
            pts.append(p)
            nrm.append(n)
            tan.append(t)
            wts += list(sh.weights)
        if not pts:
            raise ValueError("no guide surface (shapes without normals / tangents)")
        self.p = np.concatenate(pts)
        n = np.concatenate(nrm)
        self.n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        s = np.cross(self.n, np.concatenate(tan))
        s /= np.maximum(np.linalg.norm(s, axis=1, keepdims=True), 1e-12)
        self.crown = np.asarray(head, float)[:3, 3] + np.array([0.0, 0.0, 0.12])
        away = self.p - self.crown
        s *= np.where((s * away).sum(1) < 0, -1.0, 1.0)[:, None]          # root -> tip: away from the crown
        self.s = s
        self.weights = wts
        self.pp = (self.p * self.p).sum(1)

    def nearest(self, q: np.ndarray, chunk: int = 256) -> Tuple[np.ndarray, np.ndarray]:
        """(index of the nearest guide vertex, its distance) for points q (m, 3)."""
        q = np.asarray(q, float)
        idx, dist = np.empty(len(q), int), np.empty(len(q))
        for c in range(0, len(q), chunk):
            x = q[c:c + chunk]
            d2 = (x * x).sum(1)[:, None] + self.pp[None, :] - 2.0 * x @ self.p.T
            j = np.argmin(d2, axis=1)
            idx[c:c + chunk] = j
            dist[c:c + chunk] = np.sqrt(np.maximum(d2[np.arange(len(x)), j], 0.0))
        return idx, dist

    def area_samples(self, hair: Hair, spacing: float, rng) -> np.ndarray:
        """Random points on the guide's triangles, about one per spacing^2 of its area."""
        out = []
        for sh in hair.shapes:
            p = np.asarray(sh.positions, float)
            t = np.asarray(sh.triangles, int).reshape(-1, 3)
            if not len(t):
                continue
            a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
            area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
            k = rng.poisson(area / (spacing * spacing))
            rep = np.repeat(np.arange(len(t)), k)
            if not len(rep):
                continue
            r1, r2 = rng.random(len(rep)), rng.random(len(rep))
            f = r1 + r2 > 1
            r1[f], r2[f] = 1 - r1[f], 1 - r2[f]
            out.append(a[rep] + r1[:, None] * (b[rep] - a[rep]) + r2[:, None] * (c[rep] - a[rep]))
        return np.concatenate(out) if out else np.zeros((0, 3))


def trace(guide: Guide, seeds: np.ndarray, sign: float, step: float = CARD_STEP, max_steps: int = 120,
          reach: float = SURFACE_REACH, max_turn: float = MAX_TURN_DEG) -> List[np.ndarray]:
    """Each seed followed over the guide along its strand direction (sign +1: toward the tips, -1: toward the roots),
    all seeds at once: a step along the nearest vertex's direction, then back onto that vertex's tangent plane. A
    trace stops off the guide (beyond `reach`), turning too sharply (also where the root-to-tip direction reverses:
    the crown or a parting, where strands start), or after max_steps. Returns each seed's points (the seed first)."""
    pos = np.asarray(seeds, float).copy()
    paths = [[p.copy()] for p in pos]
    j, _d = guide.nearest(pos)
    prev = guide.s[j] * sign
    alive = np.ones(len(pos), bool)
    cos_max = np.cos(np.radians(max_turn))
    for _ in range(max_steps):
        if not alive.any():
            break
        ids = np.nonzero(alive)[0]
        j, _d = guide.nearest(pos[ids])
        d = guide.s[j] * sign                         # root -> tip everywhere: a reversal is the crown (whorl /
        turn_ok = (d * prev[ids]).sum(1) >= cos_max    # parting), where a strand starts: stop there
        nxt = pos[ids] + d * step
        j2, dist = guide.nearest(nxt)
        nxt -= ((nxt - guide.p[j2]) * guide.n[j2]).sum(1, keepdims=True) * guide.n[j2]
        ok = turn_ok & (dist <= reach)
        for k, i in enumerate(ids):
            if ok[k]:
                pos[i] = nxt[k]
                prev[i] = d[k]
                paths[i].append(nxt[k].copy())
            else:
                alive[i] = False
    return [np.asarray(p) for p in paths]


# ------------------------------------------------------------------------------------------------- cards
def _ribbon(line: np.ndarray, normals: np.ndarray, width: float, offset: float, strip, weights_of):
    """(positions, normals, uvs, triangles, weights) of one card along `line` (k, 3) with surface normals: two
    vertices per point, `width` across, `offset` out along the normal; u across the strip, v root (v0) to tip (v1)
    by arc length; the card faces out."""
    k = len(line)
    seg = np.diff(line, axis=0)
    along = np.vstack([seg[:1], (seg[:-1] + seg[1:]) / 2.0, seg[-1:]]) if k > 2 else np.vstack([seg, seg])[:k]
    along /= np.maximum(np.linalg.norm(along, axis=1, keepdims=True), 1e-12)
    across = np.cross(normals, along)
    across /= np.maximum(np.linalg.norm(across, axis=1, keepdims=True), 1e-12)
    centre = line + normals * offset
    pos = np.empty((2 * k, 3))
    pos[0::2] = centre - across * width / 2.0
    pos[1::2] = centre + across * width / 2.0
    nrm = np.repeat(normals, 2, axis=0)
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(seg, axis=1))])
    t = arc / max(arc[-1], 1e-9)
    u0, v0, u1, v1 = strip
    uv = []
    for ti in t:
        v = v0 + (v1 - v0) * ti
        uv += [(u0, v), (u1, v)]
    tris = []
    for i in range(k - 1):
        a, b, c, d = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
        tris += [(a, c, b), (b, c, d)]
    # winding so the faces' normal agrees with the surface normal (outward)
    if tris:
        a, b, c = pos[tris[0][0]], pos[tris[0][1]], pos[tris[0][2]]
        if np.dot(np.cross(b - a, c - a), normals[0]) < 0:
            tris = [(x, z, y) for x, y, z in tris]
    wts = [w for w in weights_of for _ in (0, 1)]
    return pos, nrm, uv, tris, wts


def grow_cards(hair: Hair, head: np.ndarray, strips: Sequence[Tuple[float, float, float, float]],
               layers: int = LAYERS, width: float = CARD_WIDTH, spacing: float = CARD_SPACING,
               gap: float = LAYER_GAP, step: float = CARD_STEP, min_length: float = 0.02, seed: int = 11,
               max_cards: int = 1500) -> Tuple[Hair, Dict]:
    """Cards over the guide hair, one shape per layer: per layer, random seed points on the guide each traced to its
    root and to its tip; a line is kept when most of its points are not within `spacing` of a line already kept in
    that layer (evenly spaced lines); each kept line becomes a ribbon `width` wide, (layer + 1) * gap out from the
    guide, mapped onto a random strip, with the bone weights of the guide vertex
    under each point. Returns (Hair of the card shapes with the guide's bones, report)."""
    if not strips:
        raise ValueError("no texture strips to map the cards onto")
    guide = Guide(hair, head)
    rng = np.random.default_rng(seed)
    strips = list(strips)
    shapes, report = [], {"layers": []}
    total = 0
    for layer in range(layers):
        seeds = guide.area_samples(hair, spacing * 1.5, rng)
        rng.shuffle(seeds)
        seeds = seeds[:4 * max_cards // layers]
        up = trace(guide, seeds, -1.0, step)
        down = trace(guide, seeds, +1.0, step)
        cell = spacing
        occupied = set()
        pos_l, nrm_l, uv_l, tri_l, w_l = [], [], [], [], []
        kept = 0
        for a, b in zip(up, down):
            line = np.vstack([a[::-1], b[1:]])
            if len(line) < 3 or np.linalg.norm(np.diff(line, axis=0), axis=1).sum() < min_length:
                continue
            keys = [tuple(k) for k in np.floor(line / cell).astype(int)]
            if sum(1 for k in keys if k in occupied) > 0.5 * len(keys):
                continue
            for k in keys:
                occupied.add(k)
            j, _d = guide.nearest(line)
            strip = strips[rng.integers(len(strips))]
            pos, nrm, uv, tris, wts = _ribbon(line, guide.n[j], width * rng.uniform(0.8, 1.2),
                                              gap * (layer + 1) + rng.uniform(0, gap / 2), strip,
                                              [guide.weights[x] for x in j])
            base = sum(len(p) for p in pos_l)
            pos_l.append(pos)
            nrm_l.append(nrm)
            uv_l += uv
            tri_l += [(x + base, y + base, z + base) for x, y, z in tris]
            w_l += wts
            kept += 1
            if total + kept >= max_cards:
                break
        total += kept
        report["layers"].append({"seeds": int(len(seeds)), "cards": kept})
        if kept:
            p = np.vstack(pos_l)
            shapes.append(HairShape(f"Cards{layer}".encode(), p, np.vstack(nrm_l), np.zeros_like(p), uv_l, tri_l,
                                    w_l, -1, -1, 0))
        if total >= max_cards:
            break
    report["cards"] = total
    report["vertices"] = int(sum(len(s.positions) for s in shapes))
    report["triangles"] = int(sum(len(s.triangles) for s in shapes))
    return Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, strand_cards=True)), report
